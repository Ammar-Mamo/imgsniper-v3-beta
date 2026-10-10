"""
Similar images report generation
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from ...core.i18n.i18n import i18n
from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter
from .image_info_extractor import ImageInfoExtractor, format_extracted_date
from . import unique_report_path


class SimilarityReportGenerator:
    """Generate reports for similar images operations."""
    
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()
        self.info_extractor = ImageInfoExtractor()
    
    def generate_similar_report(self, similar_groups: Dict[str, List[str]], deleted_files: List[str], moved_map: Dict[str, str] = None) -> str:
        """Generate report for similar images operation.

        moved_map (round 8): {original path: recycle-bin destination} for the
        files that were REALLY moved; in dry-run mode it is empty, so reports
        show only the original paths.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # Round 13: unique_report_path() re-creates the folder right before the
        # write and never overwrites an existing report (see
        # corrupted_report_generator for the failure this prevents).
        report_path = unique_report_path(self.reports_dir, f"similar_{timestamp}.txt")

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(i18n.get('reports.similar_title') + "\n")
            f.write("=" * 60 + "\n")
            f.write(i18n.get('reports.date_time').format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + "\n")
            f.write(i18n.get('reports.total_groups').format(len(similar_groups)) + "\n")
            f.write(i18n.get('reports.total_deleted').format(len(deleted_files)) + "\n")
            # Add نظام info
            # Round 18: record whether this was a dry run and where the
            # recycle bin actually was, so the report is self-describing.
            self.formatter.write_run_metadata(f)
            system_stats = system_monitor.get_detailed_info()
            f.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            f.write("=" * 60 + "\n\n")
            
            group_num = 1
            for group_hash, files in similar_groups.items():
                if len(files) > 1:
                    f.write(i18n.get('reports.group_number').format(group_num) + "\n")
                    
                    # البحث عن the kept ملف (not in deleted_ملفات)
                    kept_file = None
                    for file_path in files:
                        if file_path not in deleted_files:
                            kept_file = file_path
                            break
                    
                    if kept_file:
                        f.write(i18n.get('reports.kept_image') + "\n")
                        kept_info = self.info_extractor.get_detailed_image_info(kept_file)
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
                            f.write(f"  📐 Dimensions: {kept_info['width']}x{kept_info['height']}\n")
                            f.write(f"  📅 Date Extracted: {format_extracted_date(kept_info)}\n")
                            f.write(f"  🧭 Date Source:    {kept_info.get('date_source', 'n/a')}\n")
                            f.write(f"  🔢 Filename Importance: {kept_info['filename_importance']}/9\n")
                            f.write(f"  🕒 Modified: {kept_info['modified_time']}\n")
                            # Detailed اختيار سبب using جديد سجلic
                            reason_prefix = self.formatter.get_selection_reason_prefix()
                            f.write(f"{reason_prefix}: ")
                            # إنشاء temporary جميع_ملفات_info for this وظيفة
                            temp_all_files_info = {kept_file: kept_info}
                            for file_path in files:
                                if file_path != kept_file:
                                    temp_all_files_info[file_path] = self.info_extractor.get_detailed_image_info(file_path)
                            selection_reason = self.formatter.get_detailed_selection_reason(kept_file, files, temp_all_files_info)
                            f.write(selection_reason + "\n")
                    
                    f.write(i18n.get('reports.deleted_images') + "\n")
                    deleted_count = 0
                    for file_path in files:
                        if file_path in deleted_files:
                            deleted_count += 1
                            deleted_info = self.info_extractor.get_detailed_image_info(file_path)
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
                                f.write(f"  📐 Dimensions: {deleted_info['width']}x{deleted_info['height']}\n")
                                f.write(f"  📅 Date Extracted: {format_extracted_date(deleted_info)}\n")
                                f.write(f"  🧭 Date Source:    {deleted_info.get('date_source', 'n/a')}\n")
                                f.write(f"  🔢 Filename Importance: {deleted_info['filename_importance']}/9\n")
                                f.write(f"  🕒 Modified: {deleted_info['modified_time']}\n")
                                # إضافة سبب الحذف
                                deletion_reason = self.formatter.get_deletion_reason(file_path, kept_file, temp_all_files_info)
                                reason_prefix = i18n.get('reports.deletion_reason')
                                if reason_prefix.startswith('[Missing'):
                                    reason_prefix = 'سبب الحذف' if i18n.current_language == 'ar' else 'Deletion Reason'
                                f.write(f"  📌 {reason_prefix}: {deletion_reason}\n")
                            
                            # إضافة فاصل بين الصور المحذوفة (ما عدا الأخيرة)
                            deleted_files_in_group = [f for f in files if f in deleted_files]
                            if deleted_count < len(deleted_files_in_group):
                                f.write("  " + "=" * 39 + "\n")
                    
                    f.write("=" * 60 + "\n")
                    group_num += 1
        
        return str(report_path)
    
    def generate_similar_report_with_info(self, similar_groups: Dict[str, List[str]], deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], moved_map: Dict[str, str] = None) -> str:
        """Generate report for similar images operation with pre-collected file information.

        moved_map (round 8): {original path: recycle-bin destination} for the
        files that were REALLY moved; in dry-run mode it is empty, so reports
        show only the original paths.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # Round 13: unique_report_path() re-creates the folder right before the
        # write and never overwrites an existing report (see
        # corrupted_report_generator for the failure this prevents).
        report_path = unique_report_path(self.reports_dir, f"similar_{timestamp}.txt")

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(i18n.get('reports.similar_title') + "\n")
            f.write("=" * 60 + "\n")
            f.write(i18n.get('reports.date_time').format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + "\n")
            f.write(i18n.get('reports.total_groups').format(len(similar_groups)) + "\n")
            f.write(i18n.get('reports.total_deleted').format(len(deleted_files)) + "\n")
            # Add نظام info
            # Round 18: record whether this was a dry run and where the
            # recycle bin actually was, so the report is self-describing.
            self.formatter.write_run_metadata(f)
            system_stats = system_monitor.get_detailed_info()
            f.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            f.write("=" * 60 + "\n\n")
            
            group_num = 1
            for group_hash, files in similar_groups.items():
                if len(files) > 1:
                    f.write(i18n.get('reports.group_number').format(group_num) + "\n")
                    
                    # البحث عن the kept ملف (not in deleted_ملفات)
                    kept_file = None
                    for file_path in files:
                        if file_path not in deleted_files:
                            kept_file = file_path
                            break
                    
                    if kept_file:
                        f.write(i18n.get('reports.kept_image') + "\n")
                        kept_info = all_files_info.get(kept_file, {"error": "Info not available"})
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
                            f.write(f"  📐 Dimensions: {kept_info['width']}x{kept_info['height']}\n")
                            f.write(f"  📅 Date Extracted: {format_extracted_date(kept_info)}\n")
                            f.write(f"  🧭 Date Source:    {kept_info.get('date_source', 'n/a')}\n")
                            f.write(f"  🔢 Filename Importance: {kept_info['filename_importance']}/9\n")
                            f.write(f"  🕒 Modified: {kept_info['modified_time']}\n")
                            # Detailed اختيار سبب using جديد سجلic
                            reason_prefix = self.formatter.get_selection_reason_prefix()
                            f.write(f"{reason_prefix}: ")
                            selection_reason = self.formatter.get_detailed_selection_reason(kept_file, files, all_files_info)
                            f.write(selection_reason + "\n")
                    
                    f.write(i18n.get('reports.deleted_images') + "\n")
                    deleted_count = 0
                    for file_path in files:
                        if file_path in deleted_files:
                            deleted_count += 1
                            deleted_info = all_files_info.get(file_path, {"error": "Info not available"})
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
                                f.write(f"  📐 Dimensions: {deleted_info['width']}x{deleted_info['height']}\n")
                                f.write(f"  📅 Date Extracted: {format_extracted_date(deleted_info)}\n")
                                f.write(f"  🧭 Date Source:    {deleted_info.get('date_source', 'n/a')}\n")
                                f.write(f"  🔢 Filename Importance: {deleted_info['filename_importance']}/9\n")
                                f.write(f"  🕒 Modified: {deleted_info['modified_time']}\n")
                                # إضافة سبب الحذف
                                deletion_reason = self.formatter.get_deletion_reason(file_path, kept_file, all_files_info, files)
                                reason_prefix = i18n.get('reports.deletion_reason')
                                if reason_prefix.startswith('[Missing'):
                                    reason_prefix = 'سبب الحذف' if i18n.current_language == 'ar' else 'Deletion Reason'
                                f.write(f"  📌 {reason_prefix}: {deletion_reason}\n")
                            
                            # إضافة فاصل بين الصور المحذوفة (ما عدا الأخيرة)
                            deleted_files_in_group = [f for f in files if f in deleted_files]
                            if deleted_count < len(deleted_files_in_group):
                                f.write("  " + "=" * 39 + "\n")
                    
                    f.write("\n")
                    group_num += 1
        
        return str(report_path)