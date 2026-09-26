"""
Small images report generation
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from ...utils.helpers.system_monitor import system_monitor
from .report_formatter import ReportFormatter


class SmallImagesReportGenerator:
    """Generate reports for small images operations."""
    
    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir
        self.formatter = ReportFormatter()
    
    def generate_small_images_report(self, deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], min_width: int, min_height: int) -> str:
        """Generate report for small images deletion operation."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_path = self.reports_dir / f"small_images_{timestamp}.txt"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"{self.formatter.get_text('small_title')}\n")
            f.write("=" * 60 + "\n")
            f.write(f"{self.formatter.get_text('date_time').format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}\n")
            f.write(f"{self.formatter.get_text('min_dimensions').format(f'{min_width}x{min_height}')}\n")
            f.write(f"{self.formatter.get_text('total_deleted').format(len(deleted_files))}\n")
            # Add نظام info
            system_stats = system_monitor.get_detailed_info()
            f.write(f"{system_stats['cpu']} | {system_stats['memory']}\n")
            f.write("=" * 60 + "\n\n")
            
            if not deleted_files:
                f.write(f"✅ {self.formatter.get_text('no_small_found')}\n")
                f.write(f"{self.formatter.get_text('all_meet_requirements').format(min_width, min_height)}\n")
            else:
                f.write(f"{self.formatter.get_text('deleted_images')}\n")
                
                for i, file_path in enumerate(deleted_files, 1):
                    file_info = all_files_info.get(file_path, {"error": "Info not available"})
                    if 'error' in file_info:
                        f.write(f"  📄 {Path(file_path).name}\n")
                        f.write(f"  ❌ {self.formatter.get_text('error_reading_file')}: {file_info['error']}\n")
                        f.write(f"  📌 {self.formatter.get_localized_fallback('Reason', 'السبب')}: {self.formatter.get_localized_fallback('File too small', 'ملف صغير جداً')}\n")
                    else:
                        f.write(f"  📄 {file_info['name']}\n")
                        f.write(f"  💾 Size: {file_info['size_mb']} MB\n")
                        f.write(f"  📐 Dimensions: {file_info['width']}x{file_info['height']}\n")
                        f.write(f"  📅 Date Extracted: {file_info.get('extracted_date', 'Unknown')}\n")
                        f.write(f"  🔢 Filename Importance: {file_info.get('filename_importance', 0)}/10\n")
                        f.write(f"  🕒 Modified: {file_info.get('modified_time', 'Unknown')}\n")
                        
                        # تحديد سبب الحذف بناءً على الأبعاد
                        width = file_info.get('width', 0)
                        height = file_info.get('height', 0)
                        if width < min_width and height < min_height:
                            reason = self.formatter.get_localized_fallback(
                                f"Both dimensions too small ({width}x{height} < {min_width}x{min_height})",
                                f"كلا البعدين صغير جداً ({width}x{height} < {min_width}x{min_height})"
                            )
                        elif width < min_width:
                            reason = self.formatter.get_localized_fallback(
                                f"Width too small ({width} < {min_width})",
                                f"العرض صغير جداً ({width} < {min_width})"
                            )
                        else:
                            reason = self.formatter.get_localized_fallback(
                                f"Height too small ({height} < {min_height})",
                                f"الارتفاع صغير جداً ({height} < {min_height})"
                            )
                        f.write(f"  📌 {self.formatter.get_localized_fallback('Reason', 'السبب')}: {reason}\n")
                    
                    # إضافة فاصل بين الصور (ما عدا الأخيرة)
                    if i < len(deleted_files):
                        f.write("  " + "=" * 39 + "\n")
                
                # Summary statistics
                f.write(f"\n{self.formatter.get_text('deletion_stats')}\n")
                f.write("=" * 30 + "\n")
                
                total_size = 0
                width_violations = 0
                height_violations = 0
                both_violations = 0
                
                for file_path in deleted_files:
                    file_info = all_files_info.get(file_path, {})
                    if 'error' not in file_info:
                        total_size += file_info.get('size_bytes', 0)
                        width = file_info.get('width', 0)
                        height = file_info.get('height', 0)
                        
                        if width < min_width and height < min_height:
                            both_violations += 1
                        elif width < min_width:
                            width_violations += 1
                        elif height < min_height:
                            height_violations += 1
                
                total_size_mb = total_size / (1024 * 1024)
                
                f.write(f"{self.formatter.get_text('total_files_deleted').format(len(deleted_files))}\n")
                f.write(f"{self.formatter.get_text('total_space_freed').format(f'{total_size_mb:.2f} MB')}\n")
                f.write(f"{self.formatter.get_text('width_violations_only').format(width_violations)}\n")
                f.write(f"{self.formatter.get_text('height_violations_only').format(height_violations)}\n")
                f.write(f"{self.formatter.get_text('both_violations').format(both_violations)}\n")
        
        return str(report_path)