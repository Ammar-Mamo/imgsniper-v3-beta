"""
Exact duplicate videos report (Round 11).
تقرير الفيديوهات المتطابقة تمامًا.

Why a separate writer instead of reusing DuplicateReportGenerator
-----------------------------------------------------------------
The image/office writer is shared on purpose and stays untouched. A video group
has to state things that writer has no concept of, and adding them there would
change the report every other section produces:

  * the EXTENSION and the full SHA-256 of the group -- the two facts that make
    an exact video match verifiable after the fact;
  * the byte size, which is identical for the whole group BY DEFINITION;
  * the provenance class of each name and the FULL list of selection reasons
    (VideoFileSelector returns them; the image engine reconstructs reasons from
    a scoretable instead).

Conventions that ARE kept identical: a text file in paths.reports, the
"{prefix}_{timestamp}.txt" name (extended with the scanned option, so
"duplicate_video_mp4_..." and "duplicate_video_all_..." never collide), the
i18n title/date/system lines, the full original path plus the recycle-bin
destination through ReportFormatter.write_path_lines(), and the date-only
annotation through format_extracted_date().
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...core.i18n.i18n import i18n
from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter
from .image_info_extractor import format_extracted_date
from . import unique_report_path


class VideoDuplicateReportGenerator:
    """Write one report per exact-video-duplicate scan."""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()

    def _unique_path(self, prefix: str, safe_option: str, timestamp: str) -> Path:
        """Report path that never overwrites an existing report.

        The shared image/office writer names reports "{prefix}_{timestamp}.txt",
        so two scans inside the same second silently replace each other. A video
        scan can be started twice back to back (a dry run and then the real one),
        and losing the first report would make a run unauditable, so a numeric
        suffix is added only when the name is already taken.

        Round 13: the guard this method invented for videos now lives in
        `unique_report_path()` and every writer uses it, so the implementation
        exists once instead of twice.
        """
        return unique_report_path(self.reports_dir,
                                  f"{prefix}_{safe_option}_{timestamp}.txt")

    # ------------------------------------------------------------------
    @staticmethod
    def _split_group_key(key: Any) -> tuple:
        """(extension, sha256) out of a group key, defensively.

        The detector keys groups as (extension, sha256). Anything unexpected
        still produces a printable pair instead of raising inside a report.
        """
        if isinstance(key, (tuple, list)) and len(key) == 2:
            return str(key[0]), str(key[1])
        return '', str(key)

    def _info(self, all_files_info: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        """Report info for one file, or an empty dict when it could not be read."""
        try:
            return (all_files_info or {}).get(file_path) or {}
        except Exception:                              # pragma: no cover
            return {}

    def _write_reasons(self, out, reasons: List[str]) -> None:
        """Every reason on its own bullet line, so a decision is auditable."""
        line = i18n.get('reports.video_reason_line')
        if str(line).startswith('[Missing'):
            line = '     - {}'
        for reason in reasons or []:
            out.write(str(line).format(reason) + "\n")

    def generate_video_duplicates_report(self, duplicates: Dict[Any, List[str]],
                                         deleted_files: List[str],
                                         all_files_info: Dict[str, Dict[str, Any]],
                                         moved_map: Dict[str, str] = None,
                                         spec: Dict[str, Any] = None,
                                         option_id: str = 'all',
                                         selections: Dict[Any, Dict[str, Any]] = None) -> str:
        """Write the report and return its path.

        `selections` maps a group key to {'kept': path, 'decisions': {...}} as
        produced by VideoFileSelector, so the report prints the SAME reasons the
        engine used instead of inventing new ones.
        """
        spec = spec or {}
        selections = selections or {}
        deleted_files = deleted_files or []

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prefix = spec.get('report_prefix', 'duplicate_video')
        safe_option = ''.join(ch for ch in str(option_id or 'all')
                              if ch.isalnum() or ch in ('-', '_')) or 'all'
        report_path = self._unique_path(prefix, safe_option, timestamp)

        title = i18n.get(spec.get('report_title_key', 'reports.video_duplicates_title'))
        kept_label = i18n.get('reports.kept_file')
        deleted_label = i18n.get('reports.deleted_files')

        self.reports_dir.mkdir(parents=True, exist_ok=True)

        with open(report_path, 'w', encoding='utf-8') as out:
            out.write("=" * 80 + "\n")
            out.write(f"{title}\n")
            out.write("=" * 80 + "\n")
            out.write(i18n.get('reports.date_time').format(
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + "\n")
            out.write(i18n.get('reports.video_scanned_option').format(safe_option) + "\n")
            out.write(i18n.get('reports.video_match_rule') + "\n")
            try:
                # Round 18: record whether this was a dry run and where the
                # recycle bin actually was, so the report is self-describing.
                self.formatter.write_run_metadata(out)
                system_stats = system_monitor.get_detailed_info()
                if system_stats and 'error' not in system_stats:
                    # Same one-line format the image/office writer uses
                    # ("CPU Usage: x% | Memory Usage: y%"), read from the same
                    # helper with the same keys, so reports stay comparable.
                    out.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            except Exception as exc:
                # A report must never fail because a system statistic could not
                # be read -- but the failure is LOGGED, not swallowed: a wrong
                # key here once hid itself behind a bare "pass" and left the
                # video report with no system line at all.
                logging.debug('System stats unavailable for the video report: %s', exc)
            out.write(i18n.get('reports.total_groups').format(len(duplicates or {})) + "\n")
            out.write(i18n.get('reports.total_deleted').format(len(deleted_files)) + "\n")
            out.write("=" * 80 + "\n\n")

            self._write_groups(out, duplicates, deleted_files, all_files_info,
                               moved_map, selections, kept_label, deleted_label)

        return str(report_path)

    # ------------------------------------------------------------------
    def _write_groups(self, out, duplicates: Dict[Any, List[str]],
                      deleted_files: List[str], all_files_info: Dict[str, Any],
                      moved_map: Dict[str, str], selections: Dict[Any, Any],
                      kept_label: str, deleted_label: str) -> None:
        """One block per duplicate group: identity, kept file, removed files."""
        group_num = 1

        for key, files in (duplicates or {}).items():
            files = files or []
            extension, digest = self._split_group_key(key)
            selection = selections.get(key) or {}
            decisions = selection.get('decisions') or {}
            kept_file = selection.get('kept') or (files[0] if files else None)

            out.write(i18n.get('reports.group_number').format(group_num) + "\n")
            out.write(i18n.get('reports.video_extension').format(extension or 'n/a') + "\n")
            out.write(i18n.get('reports.video_sha256').format(digest) + "\n")
            out.write(i18n.get('reports.video_file_size').format(
                *self._group_size(files, decisions, all_files_info)) + "\n")
            out.write(i18n.get('reports.video_group_files').format(len(files)) + "\n")

            out.write(kept_label + "\n")
            self._write_file_block(out, kept_file, decisions.get(kept_file) or {},
                                   self._info(all_files_info, kept_file), None,
                                   i18n.get('reports.video_selection_reason'))

            out.write(deleted_label + "\n")
            removed = [path for path in files if path in deleted_files]
            for index, file_path in enumerate(removed):
                self._write_file_block(out, file_path, decisions.get(file_path) or {},
                                       self._info(all_files_info, file_path), moved_map,
                                       i18n.get('reports.video_deletion_reason'))
                if index < len(removed) - 1:
                    out.write("  " + "=" * 39 + "\n")
            if not removed:
                # Honest: a group can survive the run untouched when every
                # candidate was read-only/protected, or when nothing was moved.
                out.write("  " + self.formatter.get_localized_fallback(
                    '(no file of this group was removed)',
                    '(لم يُزل أي ملف من هذه المجموعة)') + "\n")

            out.write("=" * 60 + "\n")
            group_num += 1

    @staticmethod
    def _group_size(files: List[str], decisions: Dict[str, Any],
                    all_files_info: Dict[str, Any]) -> tuple:
        """(bytes, MB) shared by the whole group -- exact duplicates have one size."""
        for file_path in files or []:
            row = decisions.get(file_path) or {}
            if row.get('size_bytes'):
                size = int(row['size_bytes'])
                return size, round(size / (1024 * 1024), 2)
            info = (all_files_info or {}).get(file_path) or {}
            if info.get('size_bytes'):
                size = int(info['size_bytes'])
                return size, round(size / (1024 * 1024), 2)
        return 0, 0.0

    def _write_file_block(self, out, file_path: Optional[str], decision: Dict[str, Any],
                          info: Dict[str, Any], moved_map: Optional[Dict[str, str]],
                          reason_label: str) -> None:
        """One file: name, full path (+ destination), provenance, date, reasons."""
        if not file_path:
            return

        name = decision.get('name') or info.get('name') or Path(file_path).name
        out.write(f"  📄 {name}\n")
        # Round 8 convention, reused: the FULL original path, plus the
        # recycle-bin destination when the file was really moved.
        self.formatter.write_path_lines(out, file_path, moved_map)

        if decision.get('provenance_label'):
            out.write(i18n.get('reports.video_provenance').format(
                decision['provenance_label']) + "\n")

        if info.get('error'):
            # An unreadable file is reported as unreadable -- never dressed up
            # with invented size/date values.
            out.write(f"  ❌ Error reading file: {info['error']}\n")
        else:
            if info.get('size_mb') is not None:
                out.write(f"  💾 Size: {info.get('size_mb')} MB\n")
            out.write(f"  📅 Date Extracted: {self._decision_date(decision, info)}\n")
            out.write(f"  🧭 Date Source:    "
                      f"{decision.get('date_source') or info.get('date_source', 'n/a')}\n")
            if info.get('modified_time'):
                out.write(f"  🕒 Modified: {info['modified_time']}\n")

        out.write(reason_label + "\n")
        self._write_reasons(out, decision.get('reasons'))

    @staticmethod
    def _decision_date(decision: Dict[str, Any], info: Dict[str, Any]) -> str:
        """The date the DECISION used, with the same day-level annotation.

        A report must not show a different date than the one that decided which
        copy survives, so the decision's own value wins; the report info is only
        a fallback for a group that was never selected (nothing was deleted).
        """
        value = decision.get('date')
        if value:
            try:
                pseudo = {
                    'extracted_date': value.strftime('%Y-%m-%d %H:%M:%S'),
                    'date_only': decision.get('date_source') == 'filename'
                    and (value.hour, value.minute, value.second) == (0, 0, 0),
                }
                return format_extracted_date(pseudo)
            except (ValueError, AttributeError):       # pragma: no cover
                return str(value)
        return format_extracted_date(info or {'extracted_date': 'Unknown'})
