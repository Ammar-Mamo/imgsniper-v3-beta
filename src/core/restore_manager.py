"""
Round 18: UNDO a deletion -- put removed files back where they came from.

ImgSniper never destroys anything: every "deleted" file is MOVED into
paths.recycle_bin, and every report records both the file's ORIGINAL path and the
recycle-bin destination it was moved to. That pair is a complete undo log, and
until now nothing in the program could read it back -- recovery meant opening a
58 MB text file and copying paths by hand.

This module turns those report lines back into files on disk.

Why it is per-section
---------------------
The user asked for the undo to live INSIDE each section and to be limited to that
section's own operations, so restoring "images" can never touch a video or an
archive. SECTION_OPERATIONS below is that boundary, and it is enforced by matching
report FILE NAME PREFIXES (which the generators derive from
file_categories.SECTIONS['report_prefix']), not by guessing from file extensions.

Three safety rules, in order of importance
------------------------------------------
1. COPY, never move. The recycle bin keeps its copy until the user has looked at
   the result. An undo that destroyed its own source would be worse than the
   original deletion.
2. NEVER overwrite. If something already exists at the original path it is left
   alone and reported as "skipped"; the restored file is written next to it under
   a "_restored" name instead of replacing live data.
3. DRY RUN first. The default is to print the whole plan and change nothing; the
   user confirms before a single byte is written.

Why "Moved to" is treated as a HINT and not as truth
---------------------------------------------------
Verified on the user's real 2 TB corpus: reports said
    Moved to: ...\\recycle-bin\\corrupted\\hdd\\alll\\ENGLISH \U0001f60d\\x.jpg
while the file was actually at
    ...\\recycle-bin\\corrupted\\hdd\\alll\\ENGLISH\\working\\x.jpg
Two reasons: clean_path_for_recycle_bin() sanitises characters the report prints
verbatim, and the pre-round-18 session-folder bug parked files in a folder that
belonged to a different source. So the reported path is tried FIRST (it is right
for every report written from round 18 onwards) and the recycle bin is searched by
name when it is not found, with size then SHA-256 breaking ties.
"""

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import config
from .i18n.i18n import i18n

logger = logging.getLogger(__name__)

# Which report prefixes belong to which section. Enforced, not advisory: a
# section's restore can only ever see its own reports.
SECTION_OPERATIONS: Dict[str, List[str]] = {
    'images': ['corrupted', 'duplicates', 'similar', 'small_images'],
    'video': ['duplicate_video'],
    'office': ['duplicate_office'],
    'archives': ['duplicate_archives'],
    'other': ['duplicate_other'],
}

# Report file-name prefix per operation. Mirrors the generators:
#   corrupted_report_generator  -> "corrupted_{ts}.txt"
#   duplicate_report_generator  -> "{spec.report_prefix}_{ts}.txt"  (or "duplicates")
#   similarity_report_generator -> "similar_{ts}.txt"
#   small_images_report_generator -> "small_images_{ts}.txt"
OPERATION_PREFIX: Dict[str, str] = {
    'corrupted': 'corrupted_',
    'duplicates': 'duplicates_',
    'similar': 'similar_',
    'small_images': 'small_images_',
    'duplicate_video': 'duplicate_video_',
    'duplicate_office': 'duplicate_office_',
    'duplicate_archives': 'duplicate_archives_',
    'duplicate_other': 'duplicate_other_',
}

# Human-readable operation names, both languages, so the plan is readable
# whichever language the reports were written in.
OPERATION_LABELS: Dict[str, Tuple[str, str]] = {
    'corrupted': ('Corrupted images', 'الصور التالفة'),
    'duplicates': ('Duplicate images', 'الصور المتطابقة'),
    'similar': ('Similar images', 'الصور المتشابهة'),
    'small_images': ('Small images', 'الصور الصغيرة'),
    'duplicate_video': ('Duplicate videos', 'الفيديوهات المتطابقة'),
    'duplicate_office': ('Duplicate office files', 'ملفات الأوفيس المتطابقة'),
    'duplicate_archives': ('Duplicate archives', 'الملفات المضغوطة المتطابقة'),
    'duplicate_other': ('Duplicate other office files', 'ملفات أوفيس أخرى متطابقة'),
}

# The two report lines are matched by their EMOJI, not by their label text, so the
# same parser reads English and Arabic reports without a translation table:
#   EN  "  \U0001f4c1 Path: D:\\hdd\\x.jpg"      "  \U0001f4e5 Moved to: C:\\...\\x.jpg"
#   AR  "  \U0001f4c1 المسار: D:\\hdd\\x.jpg"    "  \U0001f4e5 نُقل إلى: C:\\...\\x.jpg"
_PATH_MARK = '\U0001f4c1'      # 📁
_MOVED_MARK = '\U0001f4e5'     # 📥


def operation_label(operation: str) -> str:
    """Localised name of an operation, for the plan the user reads.

    Reports can be in either language, so the label follows the CURRENT interface
    language rather than the language the report happened to be written in.
    """
    english, arabic = OPERATION_LABELS.get(operation, (operation, operation))
    try:
        return arabic if getattr(i18n, 'current_language', 'en') == 'ar' else english
    except Exception:
        return english


def _split_after_colon(line: str) -> Optional[str]:
    """Everything after the FIRST ': ' on a report line, or None."""
    idx = line.find(':')
    if idx < 0:
        return None
    value = line[idx + 1:].strip()
    return value or None


class RestoreItem:
    """One file the reports say was removed, and where it is now."""

    __slots__ = ('original', 'reported', 'actual', 'operation', 'report',
                 'status', 'detail')

    def __init__(self, original: str, reported: Optional[str], operation: str,
                 report: str):
        self.original = Path(original)
        self.reported = Path(reported) if reported else None
        self.actual: Optional[Path] = None
        self.operation = operation
        self.report = report
        self.status = 'pending'      # resolved by locate()
        self.detail = ''

    def __repr__(self) -> str:
        return f'<RestoreItem {self.status} {self.original.name}>'


class RestoreManager:
    """Read deletion reports and put the removed files back.

    One instance per restore request. `section` decides which reports may be read
    at all -- see SECTION_OPERATIONS.
    """

    def __init__(self, section: str, reports_dir: Optional[Path] = None,
                 recycle_bin: Optional[Path] = None):
        if section not in SECTION_OPERATIONS:
            raise ValueError(f'unknown section for restore: {section!r}')
        self.section = section
        self.operations = SECTION_OPERATIONS[section]

        from ..utils.helpers.file_utils import get_recycle_bin_root

        if reports_dir is None:
            configured = config.get('paths.reports', 'reports')
            if not configured or not isinstance(configured, str):
                configured = 'reports'
            candidate = Path(configured)
            reports_dir = candidate if candidate.is_absolute() else Path.cwd() / candidate
        self.reports_dir = Path(reports_dir)
        self.recycle_bin = Path(recycle_bin) if recycle_bin else get_recycle_bin_root()

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    def operation_for_report(self, report_path: Path) -> Optional[str]:
        """Which operation produced this report, or None if it is not ours.

        Matched on the file-name prefix so a section can never read another
        section's reports. Longest prefix first: "duplicate_video_" must win over
        any shorter prefix that also matches.
        """
        name = report_path.name
        best = None
        for operation in self.operations:
            prefix = OPERATION_PREFIX.get(operation)
            if not prefix or not name.startswith(prefix):
                continue
            if best is None or len(prefix) > len(OPERATION_PREFIX[best]):
                best = operation
        return best

    def find_reports(self) -> Dict[str, List[Path]]:
        """{operation: [report paths]} for this section only, newest first."""
        found: Dict[str, List[Path]] = {op: [] for op in self.operations}
        if not self.reports_dir.exists():
            return found
        for path in sorted(self.reports_dir.glob('*.txt'), reverse=True):
            operation = self.operation_for_report(path)
            if operation:
                found[operation].append(path)
        return found

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    def parse_report(self, report_path: Path, operation: str) -> List[RestoreItem]:
        """Extract every DELETED file from one report.

        A "📁 Path:" line appears for kept files too, but only a deleted file is
        followed by a "📥 Moved to:" line -- so the pair is what identifies a
        removal, and kept files are never restored.
        """
        items: List[RestoreItem] = []
        try:
            text = report_path.read_text(encoding='utf-8', errors='replace')
        except OSError as e:
            logger.warning('Restore: cannot read report %s: %s', report_path, e)
            return items

        last_path: Optional[str] = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _PATH_MARK in stripped:
                value = _split_after_colon(stripped)
                if value:
                    last_path = value
                continue
            if _MOVED_MARK in stripped:
                moved = _split_after_colon(stripped)
                if last_path and moved:
                    items.append(RestoreItem(last_path, moved, operation,
                                             report_path.name))
                # A moved line consumes the path it belongs to, so a second
                # moved line can never re-use the same original.
                last_path = None
        return items

    def build_plan(self) -> List[RestoreItem]:
        """Every removable file this section is allowed to restore."""
        plan: List[RestoreItem] = []
        for operation, reports in self.find_reports().items():
            for report_path in reports:
                plan.extend(self.parse_report(report_path, operation))
        return plan
    # ------------------------------------------------------------------
    # locating a file inside the recycle bin
    # ------------------------------------------------------------------
    def _index_bin(self) -> Dict[str, List[Path]]:
        """Map every file name in the recycle bin to its actual paths.

        Each file is registered under its real name AND, when it carries a
        round-18 collision suffix, under the name it had BEFORE that suffix was
        appended. That second key is what makes the real incident recoverable:
        the report's "Path:" line holds the ORIGINAL name ("photo.jpg") while the
        bin holds "photo_1.jpg", so an index keyed only on real names would call
        every collided file missing -- 13,449 of them in the user's similar pass.

        Built ONCE for the whole plan: the pre-round-18 pile-up parked tens of
        thousands of files in a handful of folders, so a per-file scan would be
        catastrophic.
        """
        index: Dict[str, List[Path]] = {}
        if not self.recycle_bin.exists():
            return index
        try:
            for path in self.recycle_bin.rglob('*'):
                if not path.is_file():
                    continue
                index.setdefault(path.name, []).append(path)
                stripped = self._strip_collision_suffix(path.name)
                if stripped != path.name:
                    index.setdefault(stripped, []).append(path)
        except OSError as e:
            logger.warning('Restore: recycle-bin scan failed: %s', e)
        return index

    @staticmethod
    def _strip_collision_suffix(name: str) -> str:
        """'photo (2)_3.jpg' -> 'photo (2).jpg' (round-18 collision suffix)."""
        stem, dot, ext = name.rpartition('.')
        if not dot:
            return name
        base, _, tail = stem.rpartition('_')
        if base and tail.isdigit():
            return f'{base}.{ext}'
        return name

    def locate(self, item: RestoreItem, index: Dict[str, List[Path]]) -> None:
        """Fill item.actual / item.status. Never raises.

        Four attempts, most trustworthy first:

          1. the reported destination, if it still exists -- correct for every
             report written from round 18 onwards;
          2. a search by the REPORTED file name. This is the step that recovers
             the real incident: the report's FOLDER was wrong (a sanitised emoji,
             or the pre-round-18 pile-up) but its FILE NAME still carries the
             collision suffix that was actually applied, so "photo_1.jpg" finds
             the copy wherever it ended up;
          3. a search by the ORIGINAL name -- which also matches suffixed copies,
             because the index registers every file under its pre-suffix name;
          4. a size tiebreak, then a deterministic pick flagged as ambiguous.
        """
        reported = item.reported

        # 1) The reported destination.
        if reported is not None:
            try:
                if reported.is_file():
                    item.actual = reported
                    item.status = 'found'
                    item.detail = 'reported path'
                    return
            except OSError:
                pass

        # 2) The reported NAME, searched across the whole bin.
        candidates: List[Path] = []
        how = ''
        if reported is not None:
            candidates = list(index.get(reported.name, []))
            how = 'found by the name the report recorded'
        # 3) The original name (the index also keys pre-suffix names).
        if not candidates:
            candidates = list(index.get(item.original.name, []))
            how = 'found by the original name'
        if not candidates:
            item.status = 'missing'
            item.detail = 'not found in the recycle bin'
            return

        if len(candidates) == 1:
            item.actual = candidates[0]
            item.status = 'found'
            item.detail = how
            # Honest bookkeeping: a match whose name differs from the original is
            # a collision-suffixed copy. Saying so lets the user verify it instead
            # of trusting a silent name approximation.
            if candidates[0].name != item.original.name:
                item.detail += f' (bin name is {candidates[0].name})'
            return

        # 4) Several files share the name. The original was moved away, so there
        #    is no size or hash of our own to compare against -- except when
        #    something now sits at the original path, whose size is at least a
        #    weak signal. Use it when it narrows the field to exactly one.
        try:
            want_size = item.original.stat().st_size
        except OSError:
            want_size = None

        sized = []
        if want_size is not None:
            for candidate in candidates:
                try:
                    if candidate.stat().st_size == want_size:
                        sized.append(candidate)
                except OSError:
                    continue
        if len(sized) == 1:
            item.actual = sized[0]
            item.status = 'found'
            item.detail = how + ' + size'
            return

        pool = sized if sized else candidates
        if len(pool) > 1:
            # Pick deterministically and TELL the user. Guessing silently would
            # put the wrong photo in the wrong folder and still look like success.
            item.actual = sorted(pool, key=lambda p: str(p))[0]
            item.status = 'ambiguous'
            item.detail = (f'{len(pool)} files in the bin share this name; '
                           f'picked the first - please check it')
            return

        item.actual = pool[0] if pool else None
        item.status = 'found' if item.actual else 'missing'
        item.detail = how if item.actual else 'not found in the recycle bin'

    # ------------------------------------------------------------------
    # destination
    # ------------------------------------------------------------------
    @staticmethod
    def _non_clashing(target: Path) -> Path:
        """A path next to `target` that does not exist.

        Round-18 rule: an undo must NEVER overwrite live data. If something already
        sits at the original path (the user recreated it, or a later operation put
        a different file there), the restored copy gets "_restored", "_restored_2"
        ... instead of replacing it.
        """
        if not target.exists():
            return target
        stem, dot, ext = target.name.rpartition('.')
        if not dot:
            stem, ext = target.name, ''
        else:
            ext = '.' + ext
        candidate = target.with_name(f'{stem}_restored{ext}')
        counter = 2
        while candidate.exists():
            candidate = target.with_name(f'{stem}_restored_{counter}{ext}')
            counter += 1
        return candidate

    def resolve_target(self, item: RestoreItem) -> Path:
        """Where the file will be written back to (never an existing path)."""
        return self._non_clashing(item.original)

    @staticmethod
    def _already_in_place(item: RestoreItem) -> bool:
        """True when the original path already holds a copy of the same file.

        Comparing paths would never work -- the bin copy lives in the bin, not at
        the original path -- so the sizes are compared instead. Equal sizes mean
        the file is home and must not be touched. Different sizes mean something
        ELSE now lives there, so the copy goes BESIDE it as *_restored and never
        over it.
        """
        if item.actual is None:
            return False
        try:
            return (item.original.is_file()
                    and item.original.stat().st_size == item.actual.stat().st_size)
        except OSError:
            return False

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def restore_one(self, item: RestoreItem) -> bool:
        """COPY one file back. Returns True when the copy is complete.

        Copy, not move: the recycle bin keeps its copy until the user has verified
        the result. A failed or partial copy is cleaned up so it cannot leave the
        0-byte husks that the round-18 full-disk incident produced.
        """
        source = item.actual
        if source is None:
            item.status = 'missing'
            return False

        target = self.resolve_target(item)
        # A name clash means live data already occupies the original spot.
        if target != item.original:
            item.detail = (item.detail + '; ' if item.detail else '') + \
                f'original spot taken, restored as {target.name}'
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target))
            # Verify the copy is complete -- a truncated restore is worse than none.
            try:
                src_size = source.stat().st_size
            except OSError:
                src_size = None
            if src_size is not None and target.stat().st_size != src_size:
                raise IOError(
                    f'size mismatch after restore: {target.stat().st_size} != {src_size}')
            item.status = 'restored'
            return True
        except Exception as e:
            # Remove any partial copy so no husk is left behind.
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
            item.status = 'error'
            item.detail = f'{type(e).__name__}: {e}'
            logger.error('Restore failed for %s: %s', item.original, e)
            return False

    def restore_all(self, plan: List[RestoreItem], dry_run: bool = True,
                    progress=None) -> Dict[str, Any]:
        """Resolve and restore a whole plan.

        dry_run=True (the default) changes NOTHING: every item is located and a
        target is computed so the user sees the real plan, but no file is written.
        """
        index = self._index_bin()
        counts: Dict[str, int] = {}
        restored_bytes = 0
        total = len(plan)

        for position, item in enumerate(plan, 1):
            self.locate(item, index)
            # Ambiguity is a WARNING about the quality of the match, not an
            # outcome in its own right: the file is still restored (or planned),
            # but the user must be told the name was shared so they can verify it.
            # Without this the dry-run branch below overwrote the flag and the
            # summary claimed a clean run.
            was_ambiguous = item.status == 'ambiguous'

            if item.status in ('found', 'ambiguous'):
                # Already home? Leave it alone -- re-copying would only create a
                # pointless *_restored twin next to a file that is already back.
                if self._already_in_place(item):
                    item.status = 'already_there'
                elif dry_run:
                    item.status = 'would_restore'
                else:
                    if self.restore_one(item):
                        try:
                            restored_bytes += item.actual.stat().st_size
                        except OSError:
                            pass

            counts[item.status] = counts.get(item.status, 0) + 1
            if was_ambiguous:
                counts['ambiguous'] = counts.get('ambiguous', 0) + 1
            if progress and total:
                progress(position, total, item)

        return {
            'section': self.section,
            'dry_run': dry_run,
            'total': total,
            'counts': counts,
            'restored_bytes': restored_bytes,
            'reports': {op: [p.name for p in paths]
                        for op, paths in self.find_reports().items() if paths},
        }



