
# ══════════════════════════════════════════════════════════════════════════════
# 🔍 كاشف الصور المكررة - Duplicate Detector
# ══════════════════════════════════════════════════════════════════════════════
# الوظيفة: البحث عن الصور المتطابقة تماماً باستخدام hash
# الطريقة: MD5 hashing للمحتوى + مقارنة البيانات الثنائية
# الأداء: معالجة متعددة الخيوط لتسريع العملية
# النتيجة: تجميع الصور المكررة واختيار أفضل نسخة
# ══════════════════════════════════════════════════════════════════════════════

"""
Duplicate image detection functionality using SHA256 hashing
"""
# وحدة كشف وتحليل الصور - يحتوي على خوارزميات البحث والفحص


import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from ...core.config import config
from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import get_all_images, move_to_recycle_bin, reset_session_folder, handle_protected_files_with_user_choice
from ...utils.helpers.scan_modes import scan_mode_manager
from ...utils.reports.report_generator import ReportGenerator


def _calculate_file_hash_worker(file_path: str, chunk_size: int = 4096) -> tuple:
    """Worker function for calculating file hash."""
    try:
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_sha256.update(chunk)
        return file_path, hash_sha256.hexdigest()
    except Exception:
        return file_path, None


class DuplicateDetector:
    """Handles detection and removal of duplicate images using SHA256 hash."""
    
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
        # Alطريقةs use ThreadPoolExecutor to avoid Windows multiعمليةing مسألةs
        return ThreadPoolExecutor
    
    def find_duplicate_images(self, folders: List[str], console: Console) -> Optional[Dict[str, Any]]:
        """Find duplicate images using SHA256 hash."""
        console.print(f"[blue]{i18n.get('common.scanning')}[/blue]")
        
        # جلب جميع ملفات الصور
        all_images = []
        for folder in folders:
            images = get_all_images(folder, self.supported_formats)
            all_images.extend(images)
        
        console.print(f"[green]{i18n.get('common.found_images').format(len(all_images))}[/green]")
        
        if not all_images:
            return None
        
        hash_to_files = {}
        
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
            
            # جلب chunk حجم from scan وضع إعدادات
            mode_config = scan_mode_manager.get_mode_config()
            chunk_size = mode_config.get('chunk_size', 4096)
            
            try:
                with executor_class(max_workers=max_workers) as executor:
                    future_to_file = {
                        executor.submit(_calculate_file_hash_worker, img_path, chunk_size): img_path 
                        for img_path in all_images
                    }
                    
                    count = 0
                    for future in as_completed(future_to_file):
                        img_path = future_to_file[future]
                        try:
                            result_path, file_hash = future.result()
                            if file_hash:
                                if file_hash not in hash_to_files:
                                    hash_to_files[file_hash] = []
                                hash_to_files[file_hash].append(result_path)
                        except Exception as e:
                            pass  # Skip ملفات that can't be hashed
                        
                        progress.advance(task)
                        count += 1
            except Exception as e:
                # Fجميعback to واحد-خيطed عمليةing if executor fails
                console.print(f"[yellow]⚠️ Falling back to single-threaded processing: {e}[/yellow]")
                for img_path in all_images:
                    try:
                        result_path, file_hash = _calculate_file_hash_worker(img_path, chunk_size)
                        if file_hash:
                            if file_hash not in hash_to_files:
                                hash_to_files[file_hash] = []
                            hash_to_files[file_hash].append(result_path)
                    except Exception as e:
                        # Audit P2-20: this was a silent "pass". A file that
                        # cannot be hashed is silently absent from the duplicate
                        # map, so it can never be matched against anything and
                        # the user had no way to find out why. DEBUG keeps this
                        # per-image loop quiet at the default INFO level.
                        logging.debug('File hash failed for %s: %s', img_path, e)
                    progress.advance(task)
        
        # البحث عن نسخة مكررةs
        duplicates = {h: files for h, files in hash_to_files.items() if len(files) > 1}
        
        total_duplicates = sum(len(files) - 1 for files in duplicates.values())
        console.print(f"[red]{i18n.get('common.duplicates_found').format(total_duplicates)}[/red]")
        
        return {
            'duplicates': duplicates,
            'total_scanned': len(all_images),
            'total_duplicates': total_duplicates,
            'operation': 'duplicates'
        }
    
    def delete_duplicate_images(self, result: Dict[str, Any], console: Console, file_selector):
        """Delete duplicate images keeping the best one from each group."""
        duplicates = result['duplicates']
        
        if not duplicates:
            return
        
        # إعادة تعيين جلسة مجلد for جديد تشغيل
        reset_session_folder()
        
        files_to_delete = []
        for file_hash, files in duplicates.items():
            if len(files) > 1:
                # Keep the أفضل ملف and mark others for deletion
                best_file = file_selector.select_best_file(files)
                for file_path in files:
                    if file_path != best_file:
                        files_to_delete.append(file_path)
        
        # التعامل مع الملفات المحمية with مستخدم اختيار
        console.print("[yellow]🔍 Checking file permissions...[/yellow]")
        files_to_delete, protected_count, force_deleted_count = handle_protected_files_with_user_choice(
            files_to_delete, console, subfolder="duplicates"
        )
        
        # Collect تفصيلed inتنسيقion for جميع ملفات BEFORE deletion
        console.print("[yellow]📊 Collecting file information...[/yellow]")
        all_files_info = {}
        
        # جلب info for جميع ملفات in نسخة مكررة groups
        for file_hash, files in duplicates.items():
            for file_path in files:
                all_files_info[file_path] = self.report_generator.get_detailed_image_info(file_path)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(i18n.get('common.deleting'), total=len(files_to_delete))
            
            deleted_files = []
            moved_map = {}   # Round 8: {original path: recycle-bin destination}
            for file_path in files_to_delete:
                try:
                    move_result = move_to_recycle_bin(file_path, subfolder="duplicates")
                    if move_result and move_result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                        deleted_files.append(file_path)
                        if move_result != "dry_run":
                            moved_map[file_path] = move_result
                except Exception:
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
        
        # توليد تقرير with pre-collected inتنسيقion
        report_path = self.report_generator.generate_duplicates_report_with_info(duplicates, deleted_files, all_files_info, moved_map)
        console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")