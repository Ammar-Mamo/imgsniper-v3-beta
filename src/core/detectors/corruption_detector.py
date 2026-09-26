"""
Image corruption detection functionality
"""
# وحدة كشف وتحليل الصور - يحتوي على خوارزميات البحث والفحص


import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageFile
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from ...core.config import config
from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import get_all_images, move_to_recycle_bin, reset_session_folder, handle_protected_files_with_user_choice
from ...utils.helpers.scan_modes import scan_mode_manager
from ...utils.reports.report_generator import ReportGenerator

# تعطيل loading of truncated صورةs for strict corruption كشف
ImageFile.LOAD_TRUNCATED_IMAGES = False


def _check_image_corruption_worker(img_path: str) -> tuple:
    """Worker function for checking image corruption with strict detection."""
    try:
        # Quick ملف حجم check أول
        file_size = Path(img_path).stat().st_size
        if file_size == 0:
            return img_path, True
        
        # Very smجميع ملفات are likely corrupted
        if file_size < 50:
            return img_path, True
        
        # Try to open and verify صورة هيكل
        with Image.open(img_path) as img:
            img.verify()
        
        # Try to فعليly load and عملية the صورة بيانات
        with Image.open(img_path) as img:
            # جلب أساسي خصائص
            width, height = img.size
            
            # فحص for invalid بُعدs
            if width <= 0 or height <= 0:
                return img_path, True
            
            # Force loading of صورة بيانات - this will fail on corrupted صورةs
            img.load()
            
            # Additional check: محاولة to convert to مصفوفة for smجميع صورةs
            # This قوةs كامل بيانات reading and will fail on corrupted بيانات
            if width * height < 1000000:  # Only for سببably حجمd صورةs
                try:
                    import numpy as np
                    img_array = np.array(img)
                    if img_array.size == 0:
                        return img_path, True
                except:
                    # If numpy fails, still عدد as corrupted
                    return img_path, True
        
        return img_path, False
    except Exception:
        return img_path, True


class CorruptionDetector:
    """Handles detection and removal of corrupted images."""
    
    def __init__(self):
        self.supported_formats = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.webp', '.ico', '.psd', '.svg', '.raw', '.cr2', '.nef',
            '.arw', '.dng', '.orf', '.rw2', '.pef', '.srw', '.x3f'
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
        all_images = []
        for folder in folders:
            images = get_all_images(folder, self.supported_formats)
            all_images.extend(images)
        
        console.print(f"[green]{i18n.get('common.found_images').format(len(all_images))}[/green]")
        
        if not all_images:
            return None
        
        corrupted_files = []
        
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
                            result_path, is_corrupted = future.result()
                            if is_corrupted:
                                corrupted_files.append(result_path)
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
                        result_path, is_corrupted = _check_image_corruption_worker(img_path)
                        if is_corrupted:
                            corrupted_files.append(result_path)
                    except Exception:
                        corrupted_files.append(img_path)
                    progress.advance(task)
        
        console.print(f"[red]{i18n.get('common.corrupted_found').format(len(corrupted_files))}[/red]")
        
        return {
            'corrupted_files': corrupted_files,
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
            for file_path in corrupted_files:
                try:
                    move_result = move_to_recycle_bin(file_path, subfolder="corrupted")
                    if move_result and move_result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                        deleted_files.append(file_path)
                except Exception as e:
                    pass  # Continue with other ملفات
                
                progress.advance(task)
        
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
        report_path = self.report_generator.generate_corrupted_report(deleted_files)
        console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")