#!/usr/bin/env python3
"""Replay the decisions recorded in an existing deletion report with the CURRENT
selection engine, and report how many of them change.

Why this exists
---------------
A deletion report already contains everything needed to re-take the decision
offline: every file's dimensions, size, extracted date, date SOURCE and filename
importance. So after any change to the selection logic the user can measure its
effect on their own corpus BEFORE running it again -- no files are touched, the
report is only read.

    python scripts/replay_decisions.py reports/similar_2026-10-10_03-42-17.txt

Dates are re-derived rather than trusted blindly: a date the report says came
from the FILENAME was stored as midnight by the old extractor (it never read the
time), so it is recomputed from the name with the current extractor. An EXIF or
modification date is a real clock reading and is used exactly as recorded.

Read-only by design: nothing is moved, renamed, written or deleted.
"""

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.config import DEFAULT_PRIORITY_ORDER, config            # noqa: E402
from src.core.file_selector import (                                  # noqa: E402
    build_group_scoretable, compute_date_scores,
    compute_resolution_boost_from_pixels, date_criterion_decides)
from src.core import name_provenance                                  # noqa: E402
from src.utils.helpers.date_extractor import date_extractor           # noqa: E402
from src.utils.reports.report_formatter import ReportFormatter        # noqa: E402

GROUP_RE = re.compile(r'^\s*\U0001F9E9 Group #')
KEPT_RE = re.compile(r'^\s*\U0001F7E2 Kept Image')
DEL_RE = re.compile(r'^\s*\u274C Deleted Images')
SEL_RE = re.compile(r'^\s*\U0001F4CC Selection Reason:\s*(.*)$')
NAME_RE = re.compile(r'^\s*\U0001F4C4\s*(.*)$')
PATH_RE = re.compile(r'^\s*\U0001F4C1 Path:\s*(.*)$')
DATE_RE = re.compile(r'^\s*\U0001F4C5 Date Extracted:\s*(.*)$')
SRC_RE = re.compile(r'^\s*\U0001F9ED Date Source:\s*(.*)$')
IMP_RE = re.compile(r'^\s*\U0001F522 Filename Importance:\s*(\d+)')
DIM_RE = re.compile(r'^\s*\U0001F4D0 Dimensions:\s*(\d+)x(\d+)')
SIZE_RE = re.compile(r'^\s*\U0001F4BE Size:\s*([\d.]+)\s*MB')
MOD_RE = re.compile(r'^\s*\U0001F552 Modified:\s*(.*)$')


def parse(path):
    """Every group of a report: the kept file, its rivals and all their data."""
    groups = []
    cur = None
    role = None
    last = None
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            if GROUP_RE.match(line):
                cur = {'kept': {}, 'deleted': [], 'reason': None}
                groups.append(cur)
                role = None
                last = None
                continue
            if cur is None:
                continue
            if KEPT_RE.match(line):
                role = 'kept'
                continue
            if DEL_RE.match(line):
                role = 'deleted'
                continue
            match = SEL_RE.match(line)
            if match:
                cur['reason'] = match.group(1).strip().split('\n')[0]
                continue
            if 'Deletion Reason' in line:
                continue
            match = NAME_RE.match(line)
            if match:
                if role == 'kept':
                    last = cur['kept']
                elif role == 'deleted':
                    last = {}
                    cur['deleted'].append(last)
                if last is not None:
                    last['name'] = match.group(1).strip()
                continue
            if last is None:
                continue
            for regex, key in ((PATH_RE, 'path'), (DATE_RE, 'date'), (SRC_RE, 'src'),
                               (IMP_RE, 'imp'), (DIM_RE, 'dim'), (SIZE_RE, 'size'),
                               (MOD_RE, 'modified')):
                match = regex.match(line)
                if match:
                    last[key] = match.groups() if len(match.groups()) > 1 \
                        else match.group(1).strip()
                    break
    return groups


def stored_date(value):
    """Parse the report's 'extracted_date' string back into a datetime."""
    if not value or value == 'Unknown':
        return None
    try:
        return datetime.strptime(str(value).split(' (')[0], '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


def current_date(entry):
    """The date the CURRENT engine would use for this file.

    A FILENAME date is recomputed from the name: the old extractor stored it as
    midnight because it never read the time. An EXIF date is a real reading and
    is kept as recorded. A modification time is used only when that was the
    recorded source.
    """
    source = str(entry.get('src') or 'none').strip().lower()
    name = entry.get('name') or Path(str(entry.get('path') or '')).name
    if source == 'filename':
        return date_extractor.extract_date_from_filename(name), 'filename'
    if source == 'modified':
        try:
            return (datetime.strptime(str(entry['modified']), '%Y-%m-%d %H:%M:%S'),
                    'modified')
        except (KeyError, ValueError, TypeError):
            return stored_date(entry.get('date')), 'modified'
    if source == 'none':
        return None, 'none'
    return stored_date(entry.get('date')), source


def reason_kind(reason):
    if not reason:
        return 'MISSING'
    return re.sub(r'\s*\(.*$', '', str(reason).split('\n')[0]).strip()


def replay(groups):
    """Re-take every decision and classify what changed."""
    # The resolution-sacrifice warning opens the real image files, which a replay
    # must not do: the deleted ones were already moved into the recycle bin, so
    # every open would fail and every kept file would be decoded again. The
    # warning is about the FILESYSTEM, not about the decision, so it is skipped
    # here -- the reason sentence itself is computed exactly as a report does.
    ReportFormatter._append_sacrifice_warning = staticmethod(lambda reason, *a: reason)

    priority_order = config.get('priorities.order', list(DEFAULT_PRIORITY_ORDER))
    if not (isinstance(priority_order, list) and sorted(priority_order) == [1, 2, 3, 4]):
        priority_order = list(DEFAULT_PRIORITY_ORDER)
    want_oldest = str(config.get('priorities.date_priority', 'oldest')).strip().lower() != 'newest'
    formatter = ReportFormatter()

    changed = 0
    why = Counter()
    new_reasons = Counter()
    samples = []
    skipped = 0

    for group in groups:
        entries = [group['kept']] + group['deleted']
        entries = [e for e in entries if e.get('name')]
        if len(entries) < 2:
            skipped += 1
            continue

        paths = [str(e.get('path') or e['name']) for e in entries]
        pixels = {}
        sizes = {}
        importances = {}
        dates = {}
        sources = {}
        for entry, path in zip(entries, paths):
            dim = entry.get('dim')
            pixels[path] = int(dim[0]) * int(dim[1]) if dim else 0
            try:
                sizes[path] = int(float(entry.get('size', 0)) * 1024 * 1024)
            except (TypeError, ValueError):
                sizes[path] = 0
            try:
                importances[path] = int(entry.get('imp', 0))
            except (TypeError, ValueError):
                importances[path] = 0
            value, source = current_date(entry)
            dates[path] = value
            sources[path] = source

        date_scores = compute_date_scores(dates, want_oldest, sources)
        boost = compute_resolution_boost_from_pixels(list(pixels.values()))
        table = build_group_scoretable(pixels, sizes, importances, date_scores,
                                       priority_order, boost)
        # Round 21: the name gate is conditional -- it may veto only when the
        # date evidence is weak. Replay the engine's exact rule.
        date_decides = date_criterion_decides(dates, sources)
        gate = {p: name_provenance.effective_gate_tier(
            name_provenance.provenance_of(Path(p).name), date_decides) for p in paths}
        index = {p: i for i, p in enumerate(paths)}

        new_kept = min(paths, key=lambda p: (-gate[p], -table[p]['total'],
                                             Path(p).name.lower(), index[p]))
        old_kept = str(group['kept'].get('path') or group['kept']['name'])

        rival = min((p for p in paths if p != new_kept),
                    key=lambda p: (-gate[p], -table[p]['total'],
                                   Path(p).name.lower(), index[p]))
        infos = {}
        for entry, path in zip(entries, paths):
            dim = entry.get('dim')
            value, source = current_date(entry)
            infos[path] = {
                'name': entry.get('name'),
                'width': int(dim[0]) if dim else 0,
                'height': int(dim[1]) if dim else 0,
                'resolution': pixels[path],
                'size_bytes': sizes[path],
                'size_mb': entry.get('size'),
                'extracted_date': value.strftime('%Y-%m-%d %H:%M:%S') if value else 'Unknown',
                'date_source': source,
                'filename_importance': importances[path],
            }
        new_reason = formatter.get_detailed_selection_reason(new_kept, paths, infos)
        new_reasons[reason_kind(new_reason)] += 1

        if new_kept != old_kept:
            changed += 1
            old_tier = gate.get(old_kept, name_provenance.CLASS_NEUTRAL)
            new_tier = gate[new_kept]
            old_scores = compute_date_scores(
                {p: (datetime.strptime(str(e['date']).split(' (')[0], '%Y-%m-%d %H:%M:%S')
                     if e.get('date') and e.get('date') != 'Unknown' else None)
                 for p, e in zip(paths, entries)},
                want_oldest,
                {p: str(e.get('src') or 'none').strip().lower()
                 for p, e in zip(paths, entries)})
            old_tie = len(set(round(v, 6) for v in old_scores.values())) == 1
            new_tie = len(set(round(v, 6) for v in date_scores.values())) == 1
            if new_tier > old_tier:
                why['name-originality gate (a derived name used to survive)'] += 1
            elif old_tie and not new_tie:
                why['date criterion restored (the time was being thrown away)'] += 1
            else:
                why['re-scored (time/gate changed the weighted total)'] += 1
            if len(samples) < 12:
                samples.append((Path(old_kept).name, Path(new_kept).name,
                                reason_kind(group['reason']),
                                reason_kind(new_reason)))

    return {
        'total': len(groups),
        'skipped': skipped,
        'changed': changed,
        'why': why,
        'new_reasons': new_reasons,
        'samples': samples,
    }


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    for report in argv:
        path = Path(report)
        if not path.is_absolute():
            path = ROOT / report
        groups = parse(path)
        result = replay(groups)
        print('=' * 78)
        print(f'REPORT : {path.name}')
        print(f'groups : {result["total"]}   (unreadable/singleton: {result["skipped"]})')
        print(f'DECISIONS THAT CHANGE with the current engine: {result["changed"]} '
              f'({result["changed"] / max(result["total"], 1) * 100:.1f}%)')
        print('\nwhy they change:')
        for cause, count in result['why'].most_common():
            print(f'  {count:7d}  {cause}')
        print('\nwhat the reports would say NOW (selection reason histogram):')
        for kind, count in result['new_reasons'].most_common():
            print(f'  {count:7d}  {count / max(result["total"], 1) * 100:5.1f}%  {kind}')
        if result['samples']:
            print('\nsamples (old kept  ->  new kept):')
            for old, new, old_reason, new_reason in result['samples']:
                print(f'  {old[:44]:46} -> {new[:44]}')
                print(f'      was: {old_reason}')
                print(f'      now: {new_reason}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
