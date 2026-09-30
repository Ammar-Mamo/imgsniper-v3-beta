
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
from ..file_categories import collect_files


# Round 9: the generic (non-image) scan reads in 1 MiB blocks. Office files
# and archives run from a few MB to several GB, so the 4 KB image default
# would multiply the number of read() calls for no benefit at all.
GENERIC_CHUNK_SIZE = 1024 * 1024


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
    
    # ---------------------------------------------------------------------
    # Round 9: shared deletion plumbing (image + non-image flows)
    # ---------------------------------------------------------------------
    def _collect_group_info(self, duplicates: Dict[Any, List[str]], info_getter) -> Dict[str, Dict[str, Any]]:
        """Collect report info for EVERY file of every group BEFORE deletion.

        `info_getter` is the matching extractor: get_detailed_image_info for
        images, get_detailed_file_info for office/archive/other files. Doing
        this before the moves means a report can still describe a file that no
        longer sits at its original path.
        """
        all_files_info = {}

        # جلب info for جميع ملفات in نسخة مكررة groups
        for _group, files in duplicates.items():
            for file_path in files:
                all_files_info[file_path] = info_getter(file_path)
        return all_files_info

    def _move_files_to_bin(self, files_to_delete: List[str], console: Console,
                           subfolder: str) -> tuple:
        """Move files to the recycle bin; returns (deleted_files, moved_map).

        `deleted_files` keeps its historic meaning: every requested file that
        was handled -- including the dry-run sentinel, so counters and reports
        still show exactly what WOULD have been removed. `moved_map` only ever
        holds real destinations, so a dry-run report cannot claim a move.
        """
        deleted_files = []
        moved_map = {}   # Round 8: {original path: recycle-bin destination}

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

            for file_path in files_to_delete:
                try:
                    move_result = move_to_recycle_bin(file_path, subfolder=subfolder)
                    if move_result and move_result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                        deleted_files.append(file_path)
                        if move_result != "dry_run":
                            moved_map[file_path] = move_result
                except Exception:
                    pass  # Continue with other ملفات

                progress.advance(task)

        return deleted_files, moved_map

    def _print_deletion_footer(self, console: Console, deleted_files: List[str],
                               protected_count: int, force_deleted_count: int,
                               subfolder: str = None) -> None:
        """Dry-run summary + recycle-bin location + final counters.

        Round 8: ONE dry-run summary line instead of one console line per file
        (the per-file list lives in imgsniper.log and in the report).

        Round 9: `subfolder` is only used to SHOW where a non-image section
        put its files; the image flow passes None and prints exactly what it
        printed before.
        """
        if config.get('safety.dry_run_mode', False):
            console.print(f"[bold magenta]🔍 {i18n.get('safety.dry_run_summary').format(len(deleted_files))}[/bold magenta]")

        # Show recycle bin info
        if deleted_files:
            recycle_bin_path = config.get('paths.recycle_bin', 'recycle-bin')
            if isinstance(recycle_bin_path, str):
                recycle_bin = Path.cwd() / recycle_bin_path
                if subfolder:
                    recycle_bin = recycle_bin / subfolder
                console.print(f"[blue]📁 {i18n.get('common.files_moved_to_recycle').format(len(deleted_files), recycle_bin)}[/blue]")

        # Show نهائي ملخص
        total_processed = len(deleted_files) + force_deleted_count
        if total_processed > 0:
            console.print(f"[green]{i18n.get('protected_files.total_processed').format(total_processed, len(deleted_files), force_deleted_count)}[/green]")

        if protected_count > 0:
            console.print(f"[yellow]{i18n.get('protected_files.files_skipped_highly_protected').format(protected_count)}[/yellow]")

    @staticmethod
    def _store_hash(hash_to_files: Dict[Any, List[str]], file_path: str,
                    file_hash: Optional[str]) -> None:
        """Record a hash under its (extension, sha256) key (round 9)."""
        if not file_hash:
            return
        key = (Path(file_path).suffix.lower(), file_hash)
        if key not in hash_to_files:
            hash_to_files[key] = []
        hash_to_files[key].append(file_path)

    def find_duplicate_files(self, folders: List[str], console: Console,
                             extensions, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find byte-identical NON-image files (Round 9).

        Two-stage pipeline, because these files are big: one 4 GB archive takes
        as long to read as a thousand photos.

          1) SIZE PRE-FILTER (stat() only, nothing is read): files are grouped
             by (extension, exact byte size). A file whose size is unique
             cannot have a byte-identical twin, so it is dropped without a
             single read.
          2) SHA-256 (1 MiB blocks) on the remaining candidates only, matched
             on (extension, sha256) -- so a match is byte-for-byte, never a
             guess.

        The extension is part of the key ON PURPOSE: .doc and .docx (or .zip
        and .7z) never share a group, even in the combined "all types" scan.

        `spec` is the section descriptor from file_categories.SECTIONS and
        provides the found/duplicates labels.
        """
        console.print(f"[blue]{i18n.get('common.scanning')}[/blue]")

        all_files = collect_files(folders, extensions)
        console.print(f"[green]{i18n.get(spec['found_key']).format(len(all_files))}[/green]")

        if not all_files:
            return None

        # ---- Stage 1: size pre-filter (stat only) -------------------------
        size_groups: Dict[Any, List[str]] = {}
        for file_path in all_files:
            try:
                size = Path(file_path).stat().st_size
            except OSError:
                continue
            key = (Path(file_path).suffix.lower(), size)
            if key not in size_groups:
                size_groups[key] = []
            size_groups[key].append(file_path)

        candidates = [paths for paths in size_groups.values() if len(paths) > 1]
        total_candidates = sum(len(paths) for paths in candidates)
        skipped = len(all_files) - total_candidates
        console.print(f"[dim]{i18n.get('common.size_prefilter').format(total_candidates, len(all_files), skipped)}[/dim]")

        hash_to_files: Dict[Any, List[str]] = {}

        if total_candidates == 0:
            # Nothing shares a size: no file can have a twin, so not one byte
            # is read. Say so instead of looking like a silent failure.
            console.print(f"[red]{i18n.get('common.duplicates_found_generic').format(0)}[/red]")
            return {
                'duplicates': {},
                'total_scanned': len(all_files),
                'total_duplicates': 0,
                'operation': 'duplicates'
            }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:

            task = progress.add_task(i18n.get('common.searching'), total=total_candidates)

            max_workers = self._get_max_workers()
            executor_class = self._get_executor_type()

            try:
                with executor_class(max_workers=max_workers) as executor:
                    future_to_file = {
                        executor.submit(_calculate_file_hash_worker, candidate, GENERIC_CHUNK_SIZE): candidate
                        for paths in candidates
                        for candidate in paths
                    }

                    for future in as_completed(future_to_file):
                        candidate = future_to_file[future]
                        try:
                            result_path, file_hash = future.result()
                            self._store_hash(hash_to_files, result_path, file_hash)
                        except Exception as exc:
                            # Audit P2-20: never a silent pass -- a file that
                            # cannot be hashed is tellingly absent from the map.
                            logging.debug('File hash failed for %s: %s', candidate, exc)

                        progress.advance(task)
            except Exception as e:
                # سقوط احتياطي إلى معالجة أحادية الخيط إذا فشل المنفّذ
                console.print(f"[yellow]⚠️ Falling back to single-threaded processing: {e}[/yellow]")
                for paths in candidates:
                    for candidate in paths:
                        try:
                            result_path, file_hash = _calculate_file_hash_worker(candidate, GENERIC_CHUNK_SIZE)
                            self._store_hash(hash_to_files, result_path, file_hash)
                        except Exception as exc:
                            logging.debug('File hash failed for %s: %s', candidate, exc)
                        progress.advance(task)

        duplicates = {key: files for key, files in hash_to_files.items() if len(files) > 1}

        total_duplicates = sum(len(files) - 1 for files in duplicates.values())
        console.print(f"[red]{i18n.get('common.duplicates_found_generic').format(total_duplicates)}[/red]")

        return {
            'duplicates': duplicates,
            'total_scanned': len(all_files),
            'total_duplicates': total_duplicates,
            'operation': 'duplicates'
        }

    def delete_duplicate_files(self, result: Dict[str, Any], console: Console,
                               file_selector, spec: Dict[str, Any]):
        """Delete duplicate non-image files, keeping the best one per group.

        Same flow as delete_duplicate_images (both use the helpers above), with
        three differences that are the whole point of round 9:

          * the surviving copy is chosen with fallback_mtime=True: these files
            carry no EXIF, so the modification time is what keeps the OLDEST
            copy meaningful;
          * every removed file lands in the section's OWN recycle-bin
            subfolder (duplicates-office / -archives / -other);
          * the report is written with the section's title, labels and prefix.
        """
        duplicates = (result or {}).get('duplicates')
        if not duplicates:
            return

        reset_session_folder()
        subfolder = spec.get('recycle_subfolder', 'duplicates-other')

        files_to_delete = []
        for _group, files in duplicates.items():
            if len(files) > 1:
                best_file = file_selector.select_best_file(files, fallback_mtime=True)
                for file_path in files:
                    if file_path != best_file:
                        files_to_delete.append(file_path)

        console.print("[yellow]🔍 Checking file permissions...[/yellow]")
        files_to_delete, protected_count, force_deleted_count = handle_protected_files_with_user_choice(
            files_to_delete, console, subfolder=subfolder
        )

        console.print("[yellow]📊 Collecting file information...[/yellow]")
        all_files_info = self._collect_group_info(
            duplicates, self.report_generator.get_detailed_file_info)

        deleted_files, moved_map = self._move_files_to_bin(files_to_delete, console, subfolder)

        self._print_deletion_footer(console, deleted_files, protected_count,
                                    force_deleted_count, subfolder)

        report_path = self.report_generator.generate_file_duplicates_report_with_info(
            duplicates, deleted_files, all_files_info, moved_map, spec)
        console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")

    def delete_duplicate_images(self, result: Dict[str, Any], console: Console, file_selector):
        """Delete duplicate images keeping the best one from each group.

        Round 9: collecting the file information and the actual moves are
        delegated to the shared helpers, so the image flow and the non-image
        flows cannot drift apart. Console output and report content are
        unchanged (subfolder=None keeps the historic recycle-bin line).
        """
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
        all_files_info = self._collect_group_info(
            duplicates, self.report_generator.get_detailed_image_info)

        deleted_files, moved_map = self._move_files_to_bin(files_to_delete, console, "duplicates")

        self._print_deletion_footer(console, deleted_files, protected_count,
                                    force_deleted_count)

        # توليد تقرير with pre-collected inتنسيقion
        report_path = self.report_generator.generate_duplicates_report_with_info(duplicates, deleted_files, all_files_info, moved_map)
        console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")
