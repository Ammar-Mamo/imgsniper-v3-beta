"""
Report generation utilities - Main coordinator class
"""
# وحدة التقارير - ينشئ ملفات HTML وإحصائيات مفصلة


from pathlib import Path
from typing import List, Dict, Any, Optional

from ...core.config import config

# استيراد خاصized تقرير مولدs
from .image_info_extractor import ImageInfoExtractor
from .report_formatter import ReportFormatter
from .corrupted_report_generator import CorruptedReportGenerator
from .duplicate_report_generator import DuplicateReportGenerator
from .similarity_report_generator import SimilarityReportGenerator
from .small_images_report_generator import SmallImagesReportGenerator



class ReportGenerator:
    """Main coordinator for report generation operations."""
    
    def __init__(self):
        reports_path = config.get('paths.reports', 'reports')
        if not reports_path or not isinstance(reports_path, str):
            reports_path = 'reports'
        self.reports_dir = Path.cwd() / reports_path
        # parents=True so a nested paths.reports ("reports/2026") also works.
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        # تهيئة خاصized مولدs
        self.info_extractor = ImageInfoExtractor()
        self.formatter = ReportFormatter()
        self.corrupted_generator = CorruptedReportGenerator(self.reports_dir)
        self.duplicate_generator = DuplicateReportGenerator(self.reports_dir)
        self.similarity_generator = SimilarityReportGenerator(self.reports_dir)
        self.small_images_generator = SmallImagesReportGenerator(self.reports_dir)

    
    # Image Inتنسيقion Methods
    def get_detailed_image_info(self, file_path: str) -> Dict[str, Any]:
        """Get detailed information about an image file."""
        return self.info_extractor.get_detailed_image_info(file_path)
    
    # Text Formatting Methods
    def get_text(self, key: str) -> str:
        """Get text from reports section, fallback to common section."""
        return self.formatter.get_text(key)
    
    def get_localized_fallback(self, english_text: str, arabic_text: str) -> str:
        """Get fallback text based on current language."""
        return self.formatter.get_localized_fallback(english_text, arabic_text)
    
    def get_selection_reason_prefix(self) -> str:
        """Get selection reason prefix based on current language."""
        return self.formatter.get_selection_reason_prefix()
    
    def get_error_reading_text(self, error_msg: str) -> str:
        """Get error reading file text based on current language."""
        return self.formatter.get_error_reading_text(error_msg)
    
    def calculate_similarity_percentage(self, deleted_file: str, kept_file: str, all_files_info: Optional[Dict[str, Any]] = None, similarity_data: Optional[Dict[str, Dict[str, float]]] = None) -> float:
        """Calculate REAL visual similarity percentage between two images."""
        # تحويل None إلى قاموس فارغ إذا لزم الأمر
        safe_all_files_info = all_files_info if all_files_info is not None else {}
        safe_similarity_data = similarity_data if similarity_data is not None else {}
        
        result = self.formatter.calculate_similarity_percentage(deleted_file, kept_file, safe_all_files_info, safe_similarity_data)
        return result if result is not None else 0.0
    
    def get_deletion_reason(self, deleted_file: str, kept_file: str, all_files_info: Dict[str, Any]) -> str:
        """Get specific deletion reason based on priorities and file comparison."""
        return self.formatter.get_deletion_reason(deleted_file, kept_file, all_files_info)
    
    # Corrupted Images Reports
    def generate_corrupted_report(self, deleted_files: List[str], moved_map: Dict[str, str] = None) -> str:
        """Generate report for corrupted images operation."""
        return self.corrupted_generator.generate_corrupted_report(deleted_files, moved_map)
    
    # Duplicate Images Reports
    def generate_duplicates_report(self, duplicates: Dict[str, List[str]], deleted_files: List[str], moved_map: Dict[str, str] = None) -> str:
        """Generate report for duplicate images operation."""
        return self.duplicate_generator.generate_duplicates_report(duplicates, deleted_files, moved_map)
    
    def generate_duplicates_report_with_info(self, duplicates: Dict[str, List[str]], deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], moved_map: Dict[str, str] = None) -> str:
        """Generate report for duplicate images operation with pre-collected file information."""
        return self.duplicate_generator.generate_duplicates_report_with_info(duplicates, deleted_files, all_files_info, moved_map)
    
    def get_detailed_file_info(self, file_path: str) -> Dict[str, Any]:
        """Round 9: information about ANY file (image or not).

        Images keep exactly the dict they always had; other files report
        kind='file', no dimensions, and the modification time as their date
        fallback so the date criterion and the report stay meaningful.
        """
        return self.info_extractor.get_detailed_file_info(file_path)
    
    def generate_file_duplicates_report_with_info(self, duplicates: Dict[Any, List[str]], deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], moved_map: Dict[str, str] = None, spec: Dict[str, Any] = None) -> str:
        """Round 9: duplicates report for a NON-image section.

        Same layout and reason engine as the image report; `spec` (from
        file_categories.SECTIONS) supplies the title, the labels and the
        report file-name prefix.
        """
        return self.duplicate_generator.generate_file_duplicates_report_with_info(
            duplicates, deleted_files, all_files_info, moved_map, spec
        )
    
    # Similar Images Reports
    def generate_similar_report(self, similar_groups: Dict[str, List[str]], deleted_files: List[str], moved_map: Dict[str, str] = None) -> str:
        """Generate report for similar images operation."""
        return self.similarity_generator.generate_similar_report(similar_groups, deleted_files, moved_map)
    
    def generate_similar_report_with_info(self, similar_groups: Dict[str, List[str]], deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], moved_map: Dict[str, str] = None) -> str:
        """Generate report for similar images operation with pre-collected file information."""
        return self.similarity_generator.generate_similar_report_with_info(similar_groups, deleted_files, all_files_info, moved_map)
    
    # Smجميع Images Reports
    def generate_small_images_report(self, deleted_files: List[str], all_files_info: Dict[str, Dict[str, Any]], min_width: int, min_height: int, moved_map: Dict[str, str] = None) -> str:
        """Generate report for small images deletion operation."""
        return self.small_images_generator.generate_small_images_report(deleted_files, all_files_info, min_width, min_height, moved_map)
    
