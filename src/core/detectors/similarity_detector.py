
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


import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from rich.console import Console

from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import (get_all_images, announce_scan_skips,
                                         reset_scan_skips)
from ...utils.helpers.progress_ui import live_counter
from ...utils.helpers.image_codec import (
    codec_status, HEIF_EXTENSIONS, RAW_EXTENSIONS,
)
from .similarity_hash_calculator import SimilarityHashCalculator
from .similarity_group_finder import SimilarityGroupFinder
from ..processors.similarity_processor import SimilarityProcessor


class SimilarityDetector:
    """Main coordinator for similar image detection operations."""
    
    def __init__(self):
        self.supported_formats = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.webp', '.ico', '.psd', '.svg', '.raw', '.cr2', '.nef',
            '.arw', '.dng', '.orf', '.rw2', '.pef', '.srw', '.x3f',
            '.heic', '.heif'
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
        # Round 12: same skip transparency as the duplicate/video flows.
        reset_scan_skips()
        all_images = []
        # Round 14: the directory walk now shows a running count. Walking a whole
        # USB hard disk printed nothing for minutes before -- which is exactly
        # when users start pressing keys. Which files are found is unchanged.
        with live_counter(console, i18n.get('common.scanning_files')) as counter:
            for folder in folders:
                images = get_all_images(folder, self.supported_formats,
                                        progress_cb=counter.bump)
                all_images.extend(images)
        announce_scan_skips(console)
        
        console.print(f"[green]{i18n.get('common.found_images').format(len(all_images))}[/green]")
        
        if not all_images:
            return None
        
        # حساب perceptual hashes
        # pHash + dHash (audit round 5): the dHash dict feeds the secondary
        # guard in the group finder -- both distances must be within the
        # threshold, which stops identical UI/screenshot templates with
        # different content (WhatsApp chats etc.) from grouping as similar.
        image_hashes, secondary_hashes = self.hash_calculator.calculate_image_hashes_dual(all_images, console)

        # Round 6 (RAW/HEIC): report every image that hashing excluded instead
        # of letting it vanish silently from the similarity scan.
        excluded_count = self._report_unhashed_images(all_images, image_hashes, console)
        
        # البحث عن similar صورةs
        similar_groups = self.group_finder.find_similar_groups(
            image_hashes, console, secondary_hashes=secondary_hashes
        )
        
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
            'total_excluded': excluded_count,
            'total_similar': total_similar_images,
            'total_groups': total_groups,
            'operation': 'similar',
            'similarity_data': similarity_data  # Add real similarity data
        }
    
    def _report_unhashed_images(self, all_images: List[str], image_hashes: Dict[str, Any], console: Console) -> int:
        """Announce images that could not be hashed and were EXCLUDED (round 6).

        RAW (cr2/nef/...) and HEIC files that neither Pillow nor the optional
        codecs could decode never enter image_hashes: before this round they
        dropped out of the similarity scan SILENTLY -- traceable only in a
        debug log line. They are now counted, printed, logged by name (first
        50, then a "+N more" tail), and returned so the result dict carries
        'total_excluded': the scan summary is honest about what was NOT
        checked and the user gets an install hint when the cause is a missing
        optional codec.
        """
        missing = [p for p in all_images if p not in image_hashes]
        if not missing:
            return 0

        names = ', '.join(Path(p).name for p in missing[:50])
        tail = ' (+%d more)' % (len(missing) - 50) if len(missing) > 50 else ''
        logging.warning(
            'Similarity scan excluded %d undecodable image(s) (RAW/HEIC '
            'without codec, or corrupt): %s%s', len(missing), names, tail)

        console.print(
            f"[yellow]{i18n.get('common.images_skipped_unreadable').format(len(missing))}[/yellow]")

        # Actionable hint only when the cause is a MISSING optional codec.
        status = codec_status()
        extensions = {Path(p).suffix.lower() for p in missing}
        if ((not status['raw'] and extensions & RAW_EXTENSIONS)
                or (not status['heif'] and extensions & HEIF_EXTENSIONS)):
            console.print(f"[yellow]{i18n.get('common.install_codec_hint')}[/yellow]")

        return len(missing)

    def delete_similar_images(self, result: Dict[str, Any], console: Console, file_selector):
        """Delete similar images keeping the best one from each group."""
        return self.processor.delete_similar_images(result, console, file_selector)