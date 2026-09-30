"""
Duplicate images report generation
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from ...core.i18n.i18n import i18n
from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter
from .image_info_extractor import ImageInfoExtractor, format_extracted_date


class DuplicateReportGenerator:
    """Generate reports for duplicate images operations."""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()
        self.info_extractor = ImageInfoExtractor()

    # ------------------------------------------------------------------
    # Public entry points -- every one of them writes through the single
    # _write_duplicates_report() below.
    # ------------------------------------------------------------------
    def generate_duplicates_report(self, duplicates: Dict[str, List[str]], deleted_files: List[str], moved_map: Dict[str, str] = None) -> str:
        """Generate report for duplicate images operation.

        moved_map (round 8): {original path: recycle-bin destination} for the
        files that were REALLY moved; in dry-run mode it is empty, so reports
        show only the original paths.
        """
        return self._write_duplicates_report(duplicates, deleted_files, None, moved_map)

    def generate_duplicates_report_with_info(self, duplicates: Dict[str, List[str]], deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], moved_map: Dict[str, str] = None) -> str:
        """Generate report for duplicate images operation with pre-collected file information.

        moved_map (round 8): {original path: recycle-bin destination} for the
        files that were REALLY moved; in dry-run mode it is empty, so reports
        show only the original paths.
        """
        return self._write_duplicates_report(duplicates, deleted_files, all_files_info, moved_map)

    def generate_file_duplicates_report_with_info(self, duplicates: Dict[Any, List[str]], deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], moved_map: Dict[str, str] = None, spec: Dict[str, Any] = None) -> str:
        """Round 9: report for a NON-image section (office/archives/other).

        Same writer as the image report -- same layout, same reason engine --
        with the section's title, labels and file-name prefix. `spec` is the
        section descriptor from file_categories.SECTIONS.
        """
        return self._write_duplicates_report(duplicates, deleted_files, all_files_info, moved_map, spec)

    # ------------------------------------------------------------------
    # The single writer
    # ------------------------------------------------------------------
    def _write_duplicates_report(self, duplicates, deleted_files, all_files_info=None, moved_map=None, spec=None) -> str:
        """Write ONE duplicates report; spec=None reproduces the image report.

        Round 9: the image flow and the non-image sections share this writer on
        purpose -- two writers would drift apart and the user would end up with
        a different layout (and different reasons) for the same operation.
        Everything that differs comes from `spec` or from the info source:

          * report file name prefix (images keep "duplicates_..."),
          * title / kept-label / deleted-label i18n keys,
          * the Dimensions line: written whenever the file HAS a resolution,
            so a Word document gets no meaningless "0x0" line while an image
            (or an image extension typed into "Other Files") keeps its size
            information;
          * when no pre-collected `all_files_info` is given, every file's info
            is extracted on demand -- exactly what the historic no-info
            variant did.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        prefix = 'duplicates' if spec is None else spec.get('report_prefix', 'duplicates')
        report_path = self.reports_dir / f"{prefix}_{timestamp}.txt"

        title_key = 'reports.duplicates_title' if spec is None else spec.get('report_title_key', 'reports.duplicates_title')
        kept_key = 'reports.kept_image' if spec is None else 'reports.kept_file'
        deleted_key = 'reports.deleted_images' if spec is None else 'reports.deleted_files'

        # Two details differ between the historic image variants and must be
        # preserved byte-for-byte: the separator closing each group, and the
        # info dict the reason engine reads from.
        group_separator = "\n" if all_files_info is not None else ("=" * 60 + "\n")

        def info_for(file_path):
            """Info dict for one file (pre-collected when available)."""
            if all_files_info is not None:
                return all_files_info.get(file_path, {"error": "Info not available"})
            if spec is not None:
                return self.info_extractor.get_detailed_file_info(file_path)
            return self.info_extractor.get_detailed_image_info(file_path)

        def write_dimensions(info):
            """Dimensions line only when the file really has dimensions."""
            if spec is not None and not (info.get('width') and info.get('height')):
                return
            f.write(f"  📐 Dimensions: {info['width']}x{info['height']}\n")

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(i18n.get(title_key) + "\n")
            f.write("=" * 60 + "\n")
            f.write(i18n.get('reports.date_time').format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + "\n")
            f.write(i18n.get('reports.total_groups').format(len(duplicates)) + "\n")
            f.write(i18n.get('reports.total_deleted').format(len(deleted_files)) + "\n")
            # Add نظام info
            system_stats = system_monitor.get_detailed_info()
            f.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            f.write("=" * 60 + "\n\n")

            group_num = 1
            for file_hash, files in duplicates.items():
                if len(files) > 1:
                    f.write(i18n.get('reports.group_number').format(group_num) + "\n")

                    # البحث عن the kept ملف (not in deleted_ملفات)
                    kept_file = None
                    for file_path in files:
                        if file_path not in deleted_files:
                            kept_file = file_path
                            break

                    # Info dict for the reason engine: the pre-collected one
                    # when the caller passed it, otherwise extracted per file.
                    # (The old no-info variant built this dict late, inside the
                    # kept-file branch, and blew up when that file was
                    # unreadable -- so the report could not be written at all.)
                    group_info = {}
                    if all_files_info is not None:
                        group_info = all_files_info
                    else:
                        for file_path in files:
                            group_info[file_path] = info_for(file_path)

                    if kept_file:
                        f.write(i18n.get(kept_key) + "\n")
                        kept_info = info_for(kept_file)
                        if 'error' in kept_info:
                            # Fجميعback for ملفات that can't be read
                            f.write(f"  📄 {Path(kept_file).name}\n")
                            # Round 8: full original path even for unreadable files.
                            self.formatter.write_path_lines(f, kept_file)
                            f.write(f"  ❌ Error reading file: {kept_info['error']}\n")
                            f.write(f"{i18n.get('reports.selection_reason_fallback')}\n")
                        else:
                            f.write(f"  📄 {kept_info['name']}\n")
                            # Round 8: full original path for every kept file.
                            self.formatter.write_path_lines(f, kept_file)
                            f.write(f"  💾 Size: {kept_info['size_mb']} MB\n")
                            write_dimensions(kept_info)
                            f.write(f"  📅 Date Extracted: {format_extracted_date(kept_info)}\n")
                            f.write(f"  🧭 Date Source:    {kept_info.get('date_source', 'n/a')}\n")
                            f.write(f"  🔢 Filename Importance: {kept_info['filename_importance']}/9\n")
                            f.write(f"  🕒 Modified: {kept_info['modified_time']}\n")
                            # Detailed اختيار سبب using جديد سجلic
                            reason_prefix = self.formatter.get_selection_reason_prefix()
                            f.write(f"{reason_prefix}: ")
                            selection_reason = self.formatter.get_detailed_selection_reason(kept_file, files, group_info)
                            f.write(selection_reason + "\n")

                    f.write(i18n.get(deleted_key) + "\n")
                    deleted_count = 0
                    for file_path in files:
                        if file_path in deleted_files:
                            deleted_count += 1
                            deleted_info = info_for(file_path)
                            if 'error' in deleted_info:
                                # Fجميعback for ملفات that can't be read
                                f.write(f"  📄 {Path(file_path).name}\n")
                                # Round 8: original path + recycle-bin destination
                                # (outside dry-run the file was really moved).
                                self.formatter.write_path_lines(f, file_path, moved_map)
                                f.write(f"  ❌ Error reading file: {deleted_info['error']}\n")
                                f.write(f"  📌 {self.formatter.get_text('reason_undetermined')}\n")
                            else:
                                f.write(f"  📄 {deleted_info['name']}\n")
                                # Round 8: original path + recycle-bin destination
                                # (outside dry-run the file was really moved).
                                self.formatter.write_path_lines(f, file_path, moved_map)
                                f.write(f"  💾 Size: {deleted_info['size_mb']} MB\n")
                                write_dimensions(deleted_info)
                                f.write(f"  📅 Date Extracted: {format_extracted_date(deleted_info)}\n")
                                f.write(f"  🧭 Date Source:    {deleted_info.get('date_source', 'n/a')}\n")
                                f.write(f"  🔢 Filename Importance: {deleted_info['filename_importance']}/9\n")
                                f.write(f"  🕒 Modified: {deleted_info['modified_time']}\n")
                                # إضافة سبب الحذف
                                deletion_reason = self.formatter.get_deletion_reason(file_path, kept_file, group_info)
                                reason_prefix = i18n.get('reports.deletion_reason')
                                if reason_prefix.startswith('[Missing'):
                                    reason_prefix = 'سبب الحذف' if i18n.current_language == 'ar' else 'Deletion Reason'
                                f.write(f"  📌 {reason_prefix}: {deletion_reason}\n")

                            # إضافة فاصل بين الصور المحذوفة (ما عدا الأخيرة)
                            deleted_files_in_group = [f for f in files if f in deleted_files]
                            if deleted_count < len(deleted_files_in_group):
                                f.write("  " + "=" * 39 + "\n")

                    f.write(group_separator)
                    group_num += 1

        return str(report_path)
