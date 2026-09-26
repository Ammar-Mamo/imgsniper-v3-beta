"""
Core image processing functionality - Main coordinator class
"""
# وحدة معالجة الصور - ينفذ العمليات على الصور المكتشفة


from pathlib import Path
from typing import Dict, List, Any, Optional
from rich.console import Console

from ..config import config
from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import get_all_images
from ...utils.helpers.scan_modes import scan_mode_manager
from ...utils.helpers.system_monitor import system_monitor

# استيراد خاصized عمليةors
from ..detectors.corruption_detector import CorruptionDetector
from ..detectors.duplicate_detector import DuplicateDetector
from ..detectors.similarity_detector import SimilarityDetector
from ..file_selector import FileSelector
from ..image_analyzer import ImageAnalyzer


class ImageProcessor:
    """Main coordinator for image processing operations."""
    
    def __init__(self):
        self.supported_formats = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.webp', '.ico', '.psd', '.svg', '.raw', '.cr2', '.nef',
            '.arw', '.dng', '.orf', '.rw2', '.pef', '.srw', '.x3f'
        }
        
        # تهيئة كاشفات متخصصة
        self.corruption_detector = CorruptionDetector()
        self.duplicate_detector = DuplicateDetector()
        self.similarity_detector = SimilarityDetector()
        self.file_selector = FileSelector()
        self.image_analyzer = ImageAnalyzer()
        
        # بدء نظام المراقبة
        system_monitor.start_monitoring()
        
    def _get_system_info(self) -> str:
        """Get system information with mode and workers only."""
        mode_config = scan_mode_manager.get_mode_config()
        
        # Try to get localized نص for Mode and Workers
        try:
            mode_text = i18n.get('system_monitor.mode')
            workers_text = i18n.get('system_monitor.workers')
            # If ترجمة is missing, use deعيب
            if mode_text.startswith('[Missing:'):
                mode_text = "Mode"
            if workers_text.startswith('[Missing:'):
                workers_text = "Workers"
        except Exception:
            mode_text = "Mode"
            workers_text = "Workers"
        
        # Add executor نوع info
        use_process_pool = mode_config.get('use_process_pool', False)
        if use_process_pool:
            multiprocess_text = i18n.get('scan_modes.multiprocess_enabled')
            if multiprocess_text.startswith('[Missing:'):
                multiprocess_text = "🚀 Multi-process enabled"
            executor_info = f" | {multiprocess_text}"
        else:
            thread_text = i18n.get('scan_modes.thread_based')
            if thread_text.startswith('[Missing:'):
                thread_text = "🔄 Thread-based"
            executor_info = f" | {thread_text}"
        
        return f"🚀 {mode_text}: {mode_config['name']} | {workers_text}: {mode_config['max_workers']}{executor_info}"
    
    def __del__(self):
        """Stop monitoring when processor is destroyed."""
        try:
            system_monitor.stop_monitoring()
        except Exception:
            pass
    
    # Corruption Detection Methods
    def find_corrupted_images(self, folders: List[str], console: Console) -> Optional[Dict[str, Any]]:
        """Find corrupted images in the specified folders."""
        console.print(f"[dim]{self._get_system_info()}[/dim]")
        return self.corruption_detector.find_corrupted_images(folders, console)
    
    def delete_corrupted_images(self, result: Dict[str, Any], console: Console):
        """Delete corrupted images."""
        return self.corruption_detector.delete_corrupted_images(result, console)
    
    # Duplicate Detection Methods
    def find_duplicate_images(self, folders: List[str], console: Console) -> Optional[Dict[str, Any]]:
        """Find duplicate images using SHA256 hash."""
        console.print(f"[dim]{self._get_system_info()}[/dim]")
        return self.duplicate_detector.find_duplicate_images(folders, console)
    
    def delete_duplicate_images(self, result: Dict[str, Any], console: Console):
        """Delete duplicate images keeping the best one from each group."""
        return self.duplicate_detector.delete_duplicate_images(result, console, self.file_selector)
    
    # Similarity Detection Methods
    def find_similar_images(self, folders: List[str], console: Console) -> Optional[Dict[str, Any]]:
        """Find visually similar images using perceptual hashing."""
        console.print(f"[dim]{self._get_system_info()}[/dim]")
        return self.similarity_detector.find_similar_images(folders, console)
    
    def delete_similar_images(self, result: Dict[str, Any], console: Console):
        """Delete similar images keeping the best one from each group."""
        return self.similarity_detector.delete_similar_images(result, console, self.file_selector)
    
    # Image Analysis Methods
    def process_small_images(self, folders: List[str], min_width: int = 300, min_height: int = 300):
        """Delete images smaller than specified dimensions."""
        return self.image_analyzer.process_small_images(folders, min_width, min_height)