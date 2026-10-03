"""
Corrupted images report generation
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ...core.i18n.i18n import i18n
from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter
from . import unique_report_path


class CorruptedReportGenerator:
    """Generate reports for corrupted images operations."""
    
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()
    
    def generate_corrupted_report(self, corrupted_files: List[str], moved_map: Dict[str, str] = None) -> str:
        """Generate report for corrupted images operation.

        moved_map (round 8): {original path: recycle-bin destination} for the
        files that were REALLY moved; in dry-run mode it is empty, so reports
        show only the original paths.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # Round 13: unique_report_path() re-creates the folder IMMEDIATELY before
        # the write and never overwrites an existing report. The folder used to
        # be created only once at startup, so a reports/ folder removed during a
        # long scan made every write fail with [Errno 2] -- and because the
        # exception escaped delete_corrupted_images(), a COMPLETED cleanup was
        # shown to the user as "❌ Error" with no report at all.
        report_path = unique_report_path(self.reports_dir, f"corrupted_{timestamp}.txt")

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(i18n.get('reports.corrupted_title') + "\n")
            f.write("=" * 60 + "\n")
            f.write(i18n.get('reports.date_time').format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')) + "\n")
            f.write(i18n.get('reports.total_corrupted').format(len(corrupted_files)) + "\n")
            # Add نظام info
            system_stats = system_monitor.get_detailed_info()
            f.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            f.write("=" * 60 + "\n\n")
            
            if corrupted_files:
                f.write(i18n.get('reports.deleted_images') + "\n")
                
                for i, file_path in enumerate(corrupted_files, 1):
                    f.write(f"  📄 {Path(file_path).name}\n")
                    # Round 8: shared path writer — the ORIGINAL path plus the
                    # recycle-bin destination when the file was really moved
                    # (the old line here wrote only the original path).
                    self.formatter.write_path_lines(f, file_path, moved_map)
                    # 'reports.corruption_reason' is already a complete,
                    # localized line — write it directly (no fragile surgery
                    # that produced a doubled emoji and a wrong label).
                    f.write(i18n.get('reports.corruption_reason') + "\n")
                    
                    # إضافة فاصل بين الصور (ما عدا الأخيرة)
                    if i < len(corrupted_files):
                        f.write("  " + "=" * 39 + "\n")
            else:
                f.write(i18n.get('reports.no_corrupted_files') + "\n")
        
        return str(report_path)