"""
Image corruption detection functionality
"""
# وحدة كشف وتحليل الصور - يحتوي على خوارزميات البحث والفحص


import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import ImageFile
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from ...core.config import config
from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import (get_all_images, move_to_recycle_bin,
                                         reset_session_folder,
                                         handle_protected_files_with_user_choice,
                                         announce_scan_skips, reset_scan_skips)
from ...utils.helpers.image_codec import open_image_with_reason
from ...utils.helpers.scan_modes import scan_mode_manager
from ...utils.reports.report_generator import ReportGenerator

# تعطيل loading of truncated صورةs for strict corruption كشف
ImageFile.LOAD_TRUNCATED_IMAGES = False


def _check_image_corruption_worker(img_path: str) -> tuple:
    """Worker function for checking image corruption with strict detection.

    Returns ``(path, verdict)`` with verdict in {True, False, 'unsupported'}.
    'unsupported' means the file uses a format whose OPTIONAL decoder (rawpy
    for camera RAW, pillow-heif for HEIC/HEIF) is not installed -- round 6:
    such files are NO LONGER branded as corrupted. The previous PIL-only
    path could not read cr2/nef/heic at all, so every RAW or HEIC file a user
    owned was reported as "corrupted" and offered for deletion. With the
    codec installed those files are now genuinely verified instead.
    """
    try:
        # Quick file size check first
        file_size = Path(img_path).stat().st_size
        if file_size == 0:
            return img_path, True

        # Very small files are likely corrupted
        if file_size < 50:
            return img_path, True

        # Strict decode through the central codec helper: this forces the
        # COMPLETE pixel data to be read (Pillow / rawpy / pillow-heif), so a
        # damaged file raises exactly as the previous verify()+load() did.
        img, reason = open_image_with_reason(img_path)
        if img is None:
            if reason == 'missing_codec':
                logging.warning(
                    'Corruption scan: %s needs an optional decoder that is not '
                    'installed (rawpy / pillow-heif) -- skipped, NOT treated '
                    'as corrupted', img_path)
                return img_path, 'unsupported'
            return img_path, True

        try:
            width, height = img.size

            # Check for invalid dimensions
            if width <= 0 or height <= 0:
                return img_path, True

            # Additional check: convert to array for small images. This forces
            # complete pixel data reading and fails on corrupted data.
            if width * height < 1000000:
                try:
                    import numpy as np
                    img_array = np.array(img)
                    if img_array.size == 0:
                        return img_path, True
                except Exception:
                    # If numpy fails, still count as corrupted
                    return img_path, True
        finally:
            img.close()

        return img_path, False
    except Exception:
        return img_path, True


class CorruptionDetector:
    """Handles detection and removal of corrupted images."""
    
    def __init__(self):
        self.supported_formats = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.webp', '.ico', '.psd', '.svg', '.raw', '.cr2', '.nef',
            '.arw', '.dng', '.orf', '.rw2', '.pef', '.srw', '.x3f',
            '.heic', '.heif'
        }
        self.report_generator = ReportGenerator()
    
    def _get_max_workers(self) -> int:
        """Get max workers based on current scan mode."""
        mode_config = scan_mode_manager.get_mode_config()
        return mode_config['max_workers']
    
    def _get_executor_type(self):
        """Get the appropriate executor type."""
        # Always use ThreadPoolExecutor to avoid Windows multiprocessing issues
        return ThreadPoolExecutor
    
    # كشف الصور التالفة أو غير القابلة للقراءة
    # ═════════════════════════════════════════
    # طرق الكشف:
    # 1. محاولة فتح الصورة بـ PIL
    # 2. التحقق من headers الملف
    # 3. قراءة بيانات EXIF
    # 4. التحقق من سلامة البيانات
    # النتيجة: قائمة بالصور التالفة للحذف
    def find_corrupted_images(self, folders: List[str], console: Console) -> Optional[Dict[str, Any]]:
        """Find corrupted images in the specified folders."""
        console.print(f"[blue]{i18n.get('common.scanning')}[/blue]")
        
        # جلب جميع ملفات الصور
        # Round 12: same skip transparency as the duplicate/video flows.
        reset_scan_skips()
        all_images = []
        for folder in folders:
            images = get_all_images(folder, self.supported_formats)
            all_images.extend(images)
        announce_scan_skips(console)
        
        console.print(f"[green]{i18n.get('common.found_images').format(len(all_images))}[/green]")
        
        if not all_images:
            return None
        
        corrupted_files = []
        unsupported_files = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(i18n.get('common.searching'), total=len(all_images))
            
            max_workers = self._get_max_workers()
            executor_class = self._get_executor_type()
            
            try:
                with executor_class(max_workers=max_workers) as executor:
                    future_to_file = {
                        executor.submit(_check_image_corruption_worker, img_path): img_path 
                        for img_path in all_images
                    }
                    
                    count = 0
                    for future in as_completed(future_to_file):
                        img_path = future_to_file[future]
                        try:
                            result_path, verdict = future.result()
                            if verdict is True:
                                corrupted_files.append(result_path)
                            elif verdict == 'unsupported':
                                unsupported_files.append(result_path)
                        except Exception as e:
                            # Consider ملفات that can't be عمليةed as corrupted
                            corrupted_files.append(img_path)
                        
                        progress.advance(task)
                        count += 1
            except Exception as e:
                # Fجميعback to واحد-خيطed عمليةing if executor fails
                console.print(f"[yellow]⚠️ Falling back to single-threaded processing: {e}[/yellow]")
                for img_path in all_images:
                    try:
                        result_path, verdict = _check_image_corruption_worker(img_path)
                        if verdict is True:
                            corrupted_files.append(result_path)
                        elif verdict == 'unsupported':
                            unsupported_files.append(result_path)
                    except Exception:
                        corrupted_files.append(img_path)
                    progress.advance(task)
        
        if unsupported_files:
            console.print(f"[yellow]{i18n.get('common.unsupported_codec_skipped').format(len(unsupported_files))}[/yellow]")

        console.print(f"[red]{i18n.get('common.corrupted_found').format(len(corrupted_files))}[/red]")
        
        return {
            'corrupted_files': corrupted_files,
            'unsupported_files': unsupported_files,
            'total_scanned': len(all_images),
            'operation': 'corrupted'
        }
    
    def delete_corrupted_images(self, result: Dict[str, Any], console: Console):
        """Delete corrupted images."""
        corrupted_files = result['corrupted_files']
        
        if not corrupted_files:
            return
        
        # إعادة تعيين جلسة مجلد for جديد تشغيل
        reset_session_folder()
        
        # التعامل مع الملفات المحمية with مستخدم اختيار
        console.print("[yellow]🔍 Checking file permissions...[/yellow]")
        corrupted_files, protected_count, force_deleted_count = handle_protected_files_with_user_choice(
            corrupted_files, console, subfolder="corrupted"
        )
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(i18n.get('common.deleting'), total=len(corrupted_files))
            
            deleted_files = []
            moved_map = {}   # Round 8: {original path: recycle-bin destination}
            for file_path in corrupted_files:
                try:
                    move_result = move_to_recycle_bin(file_path, subfolder="corrupted")
                    if move_result and move_result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                        deleted_files.append(file_path)
                        if move_result != "dry_run":
                            moved_map[file_path] = move_result
                except Exception as e:
                    pass  # Continue with other ملفات
                
                progress.advance(task)
        
        # Round 8: ONE dry-run summary line instead of one console line per
        # file (the per-file list now lives in imgsniper.log and the report).
        if config.get('safety.dry_run_mode', False):
            console.print(f"[bold magenta]🔍 {i18n.get('safety.dry_run_summary').format(len(deleted_files))}[/bold magenta]")
        
        # Show recycle bin info
        if deleted_files:
            recycle_bin_path = config.get('paths.recycle_bin', 'recycle-bin')
            if isinstance(recycle_bin_path, str):
                recycle_bin = Path.cwd() / recycle_bin_path
                console.print(f"[blue]📁 {i18n.get('common.files_moved_to_recycle').format(len(deleted_files), recycle_bin)}[/blue]")
        
        # Show نهائي ملخص
        total_processed = len(deleted_files) + force_deleted_count
        if total_processed > 0:
            console.print(f"[green]{i18n.get('protected_files.total_processed').format(total_processed, len(deleted_files), force_deleted_count)}[/green]")
        
        if protected_count > 0:
            console.print(f"[yellow]{i18n.get('protected_files.files_skipped_highly_protected').format(protected_count)}[/yellow]")
        
        # توليد تقرير
        try:
            report_path = self.report_generator.generate_corrupted_report(deleted_files, moved_map)
            console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        except Exception as report_error:
            # Round 13: the cleanup above already FINISHED. A report failure must
            # never surface as the operation's error -- that is how a real
            # 36528-file run ended in "❌ Error: [Errno 2] ...reports\x.txt" with
            # no report, after every file had already been moved.
            logging.warning('Report could not be saved after a completed operation: %s',
                            report_error)
            console.print(
                f"[yellow]{i18n.get('common.report_failed').format(report_error)}[/yellow]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")