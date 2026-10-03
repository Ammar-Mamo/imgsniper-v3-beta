"""
Image analysis functionality for dimensions and properties
"""

import logging
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from .config import config
from .i18n.i18n import i18n
from ..utils.helpers.file_utils import (get_all_images, move_to_recycle_bin,
                                        reset_session_folder,
                                        handle_protected_files_with_user_choice,
                                        announce_scan_skips, reset_scan_skips)
from ..utils.helpers.image_codec import read_dimensions
from ..utils.helpers.scan_modes import scan_mode_manager
from ..utils.reports.report_generator import ReportGenerator


def _analyze_image_dimensions_worker(image_path: str, min_width: int, min_height: int) -> tuple:
    """Worker function for analyzing image dimensions.

    Round 6: dimensions are read through the central codec helper, so RAW
    (cr2/nef/...) and HEIC files report their REAL size here instead of
    surfacing as "error reading dimensions" and being skipped.
    """
    try:
        dimensions = read_dimensions(image_path)
    except Exception:
        return image_path, (None, None, False)
    if dimensions is None:
        return image_path, (None, None, False)
    width, height = dimensions
    is_small = width < min_width or height < min_height
    return image_path, (width, height, is_small)


class ImageAnalyzer:
    """Handles analysis of image properties like dimensions."""
    
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
    
    def process_small_images(self, folders: List[str], min_width: int = 300, min_height: int = 300):
        """Delete images smaller than specified dimensions."""
        console = Console()
        
        console.print(f"[yellow]🔍 {i18n.get('common.scanning_images')}[/yellow]")
        
        # Show حالي scan وضع info
        console.print(f"[dim]{self._get_system_info()}[/dim]")
        
        # جلب جميع صورةs
        # Round 12: same skip transparency as the other flows.
        reset_scan_skips()
        all_images = []
        for folder in folders:
            images = get_all_images(folder, self.supported_formats)
            all_images.extend(images)
        announce_scan_skips(console)
        if not all_images:
            console.print(f"[red]{i18n.get('common.no_images_found')}[/red]")
            return
        
        console.print(f"[blue]📊 {i18n.get('common.found_images').format(len(all_images))}[/blue]")
        console.print(f"[blue]📏 Minimum dimensions: {min_width}x{min_height}[/blue]")
        
        # البحث عن smجميع صورةs
        small_images = []
        all_files_info = {}
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(i18n.get('common.analyzing_images'), total=len(all_images))
            
            max_workers = self._get_max_workers()
            executor_class = self._get_executor_type()
            
            try:
                with executor_class(max_workers=max_workers) as executor:
                    # Submit جميع بُعد تحليل وظيفةs
                    future_to_file = {
                        executor.submit(_analyze_image_dimensions_worker, img_path, min_width, min_height): img_path 
                        for img_path in all_images
                    }
                    
                    # معالجة نتائج
                    for future in as_completed(future_to_file):
                        img_path = future_to_file[future]
                        try:
                            result_path, (width, height, is_small) = future.result()
                            
                            # Collect تفصيلed info for جميع صورةs
                            all_files_info[result_path] = self.report_generator.get_detailed_image_info(result_path)
                            
                            # فحص if صورة is smجميعer than حد أدنى بُعدs
                            if is_small and width is not None and height is not None:
                                small_images.append(result_path)
                                
                        except Exception as e:
                            console.print(f"[red]❌ Error reading {Path(img_path).name}: {e}[/red]")
                            continue
                        finally:
                            progress.advance(task)
            except Exception as e:
                # Fجميعback to واحد-خيطed عمليةing if executor fails
                console.print(f"[yellow]⚠️ Falling back to single-threaded processing: {e}[/yellow]")
                for img_path in all_images:
                    try:
                        result_path, (width, height, is_small) = _analyze_image_dimensions_worker(img_path, min_width, min_height)
                        
                        # Collect تفصيلed info for جميع صورةs
                        all_files_info[result_path] = self.report_generator.get_detailed_image_info(result_path)
                        
                        # فحص if صورة is smجميعer than حد أدنى بُعدs
                        if is_small and width is not None and height is not None:
                            small_images.append(result_path)
                    except Exception as e:
                        console.print(f"[red]❌ Error reading {Path(img_path).name}: {e}[/red]")
                    finally:
                        progress.advance(task)
        
        if not small_images:
            console.print(f"[green]✅ {i18n.get('common.no_small_images_found').format(min_width, min_height)}[/green]")
            return
        
        console.print(f"[yellow]📊 {i18n.get('common.found_small_images').format(len(small_images))}[/yellow]")
        
        # Show some مثالs
        console.print(f"[blue]📋 {i18n.get('common.examples_small_images')}[/blue]")
        for i, img_path in enumerate(small_images[:5]):
            try:
                dimensions = read_dimensions(img_path)
                if dimensions is None:
                    raise ValueError('unreadable')
                width, height = dimensions
                size_mb = Path(img_path).stat().st_size / (1024 * 1024)
                console.print(f"  📷 {Path(img_path).name} - {width}x{height} ({size_mb:.2f} MB)")
            except Exception:
                console.print(f"  📷 {Path(img_path).name} - {i18n.get('common.error_reading_dimensions')}")
        
        if len(small_images) > 5:
            console.print(f"  {i18n.get('common.and_more').format(len(small_images) - 5)}")
        
        # Confirm deletion
        console.print(f"\n[yellow]⚠️  {i18n.get('common.confirm_small_delete').format(len(small_images))}[/yellow]")
        confirm = input(f"{i18n.get('common.continue_prompt')}").strip().lower()
        
        if confirm not in ['y', 'yes']:
            console.print(f"[blue]{i18n.get('common.cancelled')}[/blue]")
            return
        
        # حذف smجميع صورةs
        console.print(f"[yellow]{i18n.get('common.deleting_small_images')}[/yellow]")
        
        # إعادة تعيين جلسة مجلد for جديد تشغيل
        reset_session_folder()
        
        # التعامل مع الملفات المحمية with مستخدم اختيار
        console.print("[yellow]🔍 Checking file permissions...[/yellow]")
        small_images, protected_count, force_deleted_count = handle_protected_files_with_user_choice(
            small_images, console, subfolder="small"
        )
        
        deleted_files = []
        moved_map = {}   # Round 8: {original path: recycle-bin destination}
        recycle_bin = None
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(i18n.get('common.deleting'), total=len(small_images))
            
            for image_path in small_images:
                try:
                    # نقل to recycle bin with 'smجميع' subمجلد
                    result = move_to_recycle_bin(image_path, subfolder="small")
                    if result and result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                        deleted_files.append(image_path)
                        if result != "dry_run":
                            moved_map[image_path] = result
                            # move_to_recycle_bin now returns the FULL file
                            # destination (round 8); the display wants the folder.
                            if recycle_bin is None:
                                recycle_bin = str(Path(result).parent)
                except Exception as e:
                    console.print(f"[red]❌ Error deleting {Path(image_path).name}: {e}[/red]")
                finally:
                    progress.advance(task)
        
        # Round 8: ONE dry-run summary line instead of one console line per
        # file (the per-file list now lives in imgsniper.log and the report).
        if config.get('safety.dry_run_mode', False):
            console.print(f"[bold magenta]🔍 {i18n.get('safety.dry_run_summary').format(len(deleted_files))}[/bold magenta]")
        
        # Show نتائج
        total_processed = len(deleted_files) + force_deleted_count
        console.print(f"[green]✅ Deleted {total_processed} small images[/green]")
        if recycle_bin:
            console.print(f"[blue]📁 {i18n.get('common.files_moved_to_recycle').format(len(deleted_files), recycle_bin)}[/blue]")
        
        # Show نهائي ملخص
        if total_processed > 0:
            console.print(f"[green]{i18n.get('protected_files.total_processed').format(total_processed, len(deleted_files), force_deleted_count)}[/green]")
        
        if protected_count > 0:
            console.print(f"[yellow]{i18n.get('protected_files.files_skipped_highly_protected').format(protected_count)}[/yellow]")
        
        # توليد تقرير
        try:
            report_path = self.report_generator.generate_small_images_report(deleted_files, all_files_info, min_width, min_height, moved_map)
            console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        except Exception as report_error:
            # Round 13: never let a report failure mask the completed operation.
            logging.warning('Small-images report could not be saved after a completed operation: %s',
                            report_error)
            console.print(
                f"[yellow]{i18n.get('common.report_failed').format(report_error)}[/yellow]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")