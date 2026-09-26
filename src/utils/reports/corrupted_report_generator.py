"""
Corrupted images report generation
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List

from ...core.i18n.i18n import i18n
from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter


class CorruptedReportGenerator:
    """Generate reports for corrupted images operations."""
    
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()
    
    def generate_corrupted_report(self, corrupted_files: List[str]) -> str:
        """Generate report for corrupted images operation."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_path = self.reports_dir / f"corrupted_{timestamp}.txt"
        
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
                    # 'reports.image_path' is a format string ("  📁 Path: {}"),
                    # so use .format() — the old string-splitting hack wrote a
                    # literal "{}" into the report instead of the real path.
                    f.write(i18n.get('reports.image_path').format(file_path) + "\n")
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