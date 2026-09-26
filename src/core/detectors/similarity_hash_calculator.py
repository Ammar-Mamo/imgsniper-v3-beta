"""
Perceptual hash calculation functionality for similarity detection
"""
# وحدة كشف وتحليل الصور - يحتوي على خوارزميات البحث والفحص


import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import imagehash
from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from ..i18n.i18n import i18n
from ...utils.helpers.scan_modes import scan_mode_manager


def _calculate_perceptual_hash_worker(img_path: str, hash_size: int = 8) -> tuple:
    """Worker function for calculating perceptual hash."""
    try:
        # Quick ملف حجم check to skip empty ملفات
        if Path(img_path).stat().st_size == 0:
            return img_path, None
            
        with Image.open(img_path) as img:
            # Skip conإصدار if alجاهز RGB or grayمقياس for سرعة
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            # Use optimized pHash
            phash = imagehash.phash(img, hash_size=hash_size)
            return img_path, phash
    except Exception:
        return img_path, None


class SimilarityHashCalculator:
    """Calculate perceptual hashes for similarity detection."""
    
    def __init__(self):
        pass
    
    def _get_max_workers(self) -> int:
        """Get max workers based on current scan mode."""
        mode_config = scan_mode_manager.get_mode_config()
        return mode_config['max_workers']
    
    def _get_executor_type(self):
        """Get the appropriate executor type."""
        # Alطريقةs use ThreadPoolExecutor to avoid Windows multiعمليةing مسألةs
        return ThreadPoolExecutor
    
    def calculate_image_hashes(self, all_images: List[str], console: Console) -> Dict[str, Any]:
        """Calculate perceptual hashes for all images."""
        image_hashes = {}
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(i18n.get('common.visual_similarity_check'), total=len(all_images))
            
            max_workers = self._get_max_workers()
            executor_class = self._get_executor_type()
            
            # جلب hash حجم from scan وضع إعدادات - توازنd for أداء vs دقة
            mode_config = scan_mode_manager.get_mode_config()
            if mode_config['name'] == 'Ultra':
                hash_size = 16  # High دقة for Ultra وضع
            elif mode_config['name'] == 'Advanced':
                hash_size = 12  # Balanced دقة for Advanced وضع
            elif mode_config['name'] == 'Medium':
                hash_size = 10  # Good توازن for Medium وضع
            else:  # Normal
                hash_size = 8   # Standard دقة for Normal وضع
            
            try:
                with executor_class(max_workers=max_workers) as executor:
                    # Submit جميع وظيفةs at once for consistent نتائج
                    future_to_file = {
                        executor.submit(_calculate_perceptual_hash_worker, img_path, hash_size): img_path 
                        for img_path in all_images
                    }
                    
                    # معالجة جميع كاملd futures
                    for future in as_completed(future_to_file):
                        img_path = future_to_file[future]
                        try:
                            result_path, img_hash = future.result()
                            if img_hash is not None:
                                image_hashes[result_path] = img_hash
                        except Exception:
                            pass  # Skip ملفات that can't be عمليةed
                        
                        progress.advance(task)
            except Exception as e:
                # Fجميعback to واحد-خيطed عمليةing if executor fails
                console.print(f"[yellow]⚠️ Falling back to single-threaded processing: {e}[/yellow]")
                for img_path in all_images:
                    try:
                        result_path, img_hash = _calculate_perceptual_hash_worker(img_path, hash_size)
                        if img_hash is not None:
                            image_hashes[result_path] = img_hash
                    except Exception as e:
                        # Audit P2-20: was a silent "pass". An image whose
                        # perceptual hash cannot be computed never enters
                        # image_hashes, so it is invisible to the entire
                        # similarity scan and no trace of it is left behind.
                        logging.debug('Perceptual hash failed for %s: %s', img_path, e)
                    progress.advance(task)
        
        return image_hashes
    
    def calculate_real_similarities(self, similar_groups: List[List[str]], image_hashes: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """Calculate real visual similarity percentages between images in each group."""
        similarity_data = {}
        
        for group in similar_groups:
            if len(group) < 2:
                continue
                
            # For now, just use the أول صورة as kept صورة
            # This will be مناسبly مقبضd when cجميعed from ImageProcessor
            kept_image = group[0]
            kept_hash = image_hashes.get(kept_image)
            
            if kept_hash is None:
                continue
                
            group_similarities = {}
            
            # حساب similarity between kept صورة and ALL other صورةs in group
            for other_image in group:
                if other_image == kept_image:
                    continue  # Skip the kept صورة itself
                    
                other_hash = image_hashes.get(other_image)
                if other_hash is not None:
                    try:
                        # Compute the Hamming distance between the two hashes
                        hamming_distance = kept_hash - other_hash

                        # Derive max_distance from the ACTUAL hash bit-length
                        # (hash_size^2). This keeps the percentage correct for
                        # every scan mode (Normal=64, Medium=100, Advanced=144,
                        # Ultra=256 bits) instead of assuming a fixed 64.
                        max_distance = kept_hash.hash.size
                        similarity_percentage = max(0.0, (max_distance - hamming_distance) / max_distance * 100)
                        
                        group_similarities[other_image] = round(similarity_percentage, 1)
                    except Exception:
                        # Deعيب عالي similarity if حساب fails
                        group_similarities[other_image] = 90.0
                else:
                    # Deعيب عالي similarity if hash not found
                    group_similarities[other_image] = 90.0
            
            if group_similarities:
                similarity_data[kept_image] = group_similarities
        
        return similarity_data