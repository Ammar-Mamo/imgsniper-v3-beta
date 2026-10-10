"""
Round 18: report for an UNDO (restore) operation.

Every other operation in ImgSniper writes a report, and an undo is the one
operation whose report matters MOST: it is the record of what went back, what
could not be found, and what had to be written under a different name because
live data already occupied the original spot. Without it the user would have to
eyeball thousands of folders to know whether the undo was complete.

The file name prefix is "restore_" on purpose. RestoreManager discovers deletions
by matching the prefixes in OPERATION_PREFIX ("corrupted_", "duplicates_", ...),
and a restore report must never be mistaken for a deletion report -- otherwise a
second undo would try to "restore" the files an earlier undo had just put back.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ...core.restore_manager import RestoreItem, operation_label
from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter
from . import unique_report_path

# Status -> (english label, arabic label, emoji).
_STATUS_LABELS: Dict[str, Any] = {
    'restored':      ('RESTORED (copied back)',          'تم الاسترجاع (نُسخ إلى مكانه)', '✅'),
    'would_restore': ('WOULD RESTORE (dry run)',         'سيُسترجع (وضع المحاكاة)',       '🔍'),
    'already_there': ('ALREADY IN PLACE (not touched)',  'موجود أصلاً (لم يُمَس)',        '⏭️'),
    'missing':       ('NOT FOUND in the recycle bin',    'غير موجود في السلة',            '❌'),
    'ambiguous':     ('AMBIGUOUS (needs a manual look)', 'غامض (يحتاج مراجعة يدوية)',      '⚠️'),
    'error':         ('ERROR while restoring',           'خطأ أثناء الاسترجاع',           '🛑'),
}


class RestoreReportGenerator:
    """Generate the report of a restore (undo) operation."""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()

    def _label(self, english: str, arabic: str) -> str:
        return self.formatter.get_localized_fallback(english, arabic)

    def generate_restore_report(self, section: str, plan: List[RestoreItem],
                                summary: Dict[str, Any]) -> str:
        """Write the restore report and return its path."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_path = unique_report_path(
            self.reports_dir, f"restore_{section}_{timestamp}.txt")

        counts = summary.get('counts', {}) or {}
        dry_run = bool(summary.get('dry_run', True))

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(self._label('RESTORE (UNDO DELETION) REPORT',
                                'تقرير الاسترجاع (التراجع عن الحذف)') + "\n")
            f.write("=" * 60 + "\n")
            f.write(self.formatter.get_text('date_time').format(
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + "\n")
            f.write(self._label('Section', 'القسم') + f": {section}\n")
            f.write(self._label('Files in plan', 'الملفات في الخطة')
                    + f": {summary.get('total', 0)}\n")
            # Round 18: dry-run flag + the real recycle-bin location. The flag is
            # passed explicitly: a restore ALWAYS previews first regardless of
            # safety.dry_run_mode, so the config value would misreport this run.
            self.formatter.write_run_metadata(f, dry_run=dry_run)
            system_stats = system_monitor.get_detailed_info()
            f.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            f.write("=" * 60 + "\n\n")

            # Which deletion reports were read -- the provenance of this undo.
            reports_used = summary.get('reports', {}) or {}
            f.write(self._label('Deletion reports used',
                                'تقارير الحذف المستخدمة') + "\n")
            if reports_used:
                for operation, names in reports_used.items():
                    f.write(f"  {operation_label(operation)} ({operation}): "
                            f"{len(names)}\n")
                    for name in names:
                        f.write(f"    📄 {name}\n")
            else:
                f.write("  " + self._label(
                    'NONE - no deletion report found for this section',
                    'لا شيء - لم يُعثر على تقرير حذف لهذا القسم') + "\n")
            f.write("\n")

            # Outcome summary, most important first.
            f.write(self._label('Result', 'النتيجة') + "\n")
            f.write("=" * 30 + "\n")
            for status in ('restored', 'would_restore', 'already_there',
                           'missing', 'ambiguous', 'error'):
                number = counts.get(status, 0)
                if not number:
                    continue
                english, arabic, emoji = _STATUS_LABELS[status]
                f.write(f"  {emoji} {self._label(english, arabic)}: {number}\n")
            for status, number in counts.items():
                if status not in _STATUS_LABELS and number:
                    f.write(f"  {status}: {number}\n")
            if not dry_run:
                megabytes = summary.get('restored_bytes', 0) / (1024 * 1024)
                f.write(self._label('Restored size', 'حجم المسترجَع')
                        + f": {megabytes:.2f} MB\n")
            f.write("\n")
            self._write_details(f, plan)

        return str(report_path)

    def _write_details(self, f, plan: List[RestoreItem]) -> None:
        """Per-file detail: what went back, from where, and to where.

        This is the section the user reads to TRUST the undo, so every file gets
        its original path, where it was actually found in the bin, and any note
        (a name clash, an ambiguity, an error). Missing files are listed too --
        knowing what could NOT be restored is as important as what was.
        """
        if not plan:
            f.write("✅ " + self._label(
                'Nothing to restore for this section',
                'لا شيء لاسترجاعه في هذا القسم') + "\n")
            return

        f.write(self._label('File details', 'تفاصيل الملفات') + "\n")
        f.write("=" * 30 + "\n")
        for index, item in enumerate(plan, 1):
            english, arabic, emoji = _STATUS_LABELS.get(
                item.status, (item.status, item.status, '❔'))
            f.write(f"{index}. {item.original.name}\n")
            f.write(f"   {emoji} {self._label(english, arabic)}\n")
            f.write(f"   {self._label('Operation', 'العملية')}: "
                    f"{operation_label(item.operation)}\n")
            f.write(f"   📁 {self._label('Original path', 'المسار الأصلي')}: "
                    f"{item.original}\n")
            if item.actual is not None:
                f.write(f"   📦 {self._label('Found in bin', 'وُجد في السلة')}: "
                        f"{item.actual}\n")
            elif item.reported is not None:
                f.write(f"   📥 {self._label('Report said', 'التقرير ذكر')}: "
                        f"{item.reported}\n")
            if item.detail:
                f.write(f"   📌 {self._label('Note', 'ملاحظة')}: {item.detail}\n")
            f.write(f"   🗂️ {self._label('Source report', 'تقرير المصدر')}: "
                    f"{item.report}\n")
            if index < len(plan):
                f.write("   " + "-" * 39 + "\n")
