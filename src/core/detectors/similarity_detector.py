
# ══════════════════════════════════════════════════════════════════════════════
# 👁️ كاشف الصور المتشابهة - Similarity Detector  
# ══════════════════════════════════════════════════════════════════════════════
# الوظيفة: البحث عن الصور المتشابهة بصرياً (ليست متطابقة)
# الطريقة: Perceptual Hashing (pHash, dHash, wHash)
# المقارنة: المسافة الهمينغية Hamming Distance
# الحساسية: قابلة للتعديل حسب مستوى التشابه المطلوب
# ══════════════════════════════════════════════════════════════════════════════

"""
Similar image detection functionality - Main coordinator class
"""
# وحدة كشف وتحليل الصور - يحتوي على خوارزميات البحث والفحص


from typing import Dict, List, Any, Optional
from rich.console import Console

from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import get_all_images
from .similarity_hash_calculator import SimilarityHashCalculator
from .similarity_group_finder import SimilarityGroupFinder
from ..processors.similarity_processor import SimilarityProcessor


class SimilarityDetector:
    """Main coordinator for similar image detection operations."""
    
    def __init__(self):
        self.supported_formats = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.webp', '.ico', '.psd', '.svg', '.raw', '.cr2', '.nef',
            '.arw', '.dng', '.orf', '.rw2', '.pef', '.srw', '.x3f'
        }
        
        # تهيئة مكونات متخصصة
        self.hash_calculator = SimilarityHashCalculator()
        self.group_finder = SimilarityGroupFinder()
        self.processor = SimilarityProcessor()
    
    # البحث عن الصور المتشابهة بصرياً
        # يستخدم خوارزميات: pHash, dHash, wHash
        # يحسب المسافة الهمينغية للمقارنة
        # يدعم تعديل مستوى الحساسية للتشابه
    
    def find_similar_images(self, folders: List[str], console: Console) -> Optional[Dict[str, Any]]:
        """Find visually similar images using perceptual hashing."""
        console.print(f"[blue]{i18n.get('common.scanning')}[/blue]")
        
        # جلب جميع ملفات الصور
        all_images = []
        for folder in folders:
            images = get_all_images(folder, self.supported_formats)
            all_images.extend(images)
        
        console.print(f"[green]{i18n.get('common.found_images').format(len(all_images))}[/green]")
        
        if not all_images:
            return None
        
        # حساب perceptual hashes
        image_hashes = self.hash_calculator.calculate_image_hashes(all_images, console)
        
        # البحث عن similar صورةs
        similar_groups = self.group_finder.find_similar_groups(image_hashes, console)
        
        # حساب إجمالي similar صورةs (excluding the واحد to keep from كل group)
        total_similar_images = sum(len(group) - 1 for group in similar_groups)
        total_groups = len(similar_groups)
        
        console.print(f"[red]{i18n.get('common.similar_found').format(total_similar_images)}[/red]")
        console.print(f"[green]✅ {i18n.get('common.similarity_scan_complete').format(len(image_hashes), total_similar_images, total_groups)}[/green]")
        
        # حساب حقيقي visual similarity نسبة مئويةs between صورةs in كل group
        similarity_data = self.hash_calculator.calculate_real_similarities(similar_groups, image_hashes)
        
        return {
            'similar_groups': similar_groups,
            'total_scanned': len(all_images),
            'total_similar': total_similar_images,
            'total_groups': total_groups,
            'operation': 'similar',
            'similarity_data': similarity_data  # Add real similarity data
        }
    
    def delete_similar_images(self, result: Dict[str, Any], console: Console, file_selector):
        """Delete similar images keeping the best one from each group."""
        return self.processor.delete_similar_images(result, console, file_selector)