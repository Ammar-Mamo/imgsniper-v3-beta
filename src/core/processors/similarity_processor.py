"""
Similar image processing and deletion functionality
"""
# وحدة معالجة الصور - ينفذ العمليات على الصور المكتشفة


import logging
from pathlib import Path
from typing import Dict, List, Any
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from ...core.config import config
from ..i18n.i18n import i18n
from ...utils.helpers.file_utils import (move_to_recycle_bin, reset_session_folder,
                                         handle_protected_files_with_user_choice,
                                         ensure_recycle_bin_capacity,
                                         get_recycle_bin_root)
from ...utils.helpers.progress_ui import track
from ...utils.reports.report_generator import ReportGenerator


class SimilarityProcessor:
    """Process and delete similar images."""
    
    def __init__(self):
        self.report_generator = ReportGenerator()
    
    def delete_similar_images(self, result: Dict[str, Any], console: Console, file_selector):
        """Delete similar images keeping the best one from each group."""
        similar_groups = result['similar_groups']
        
        if not similar_groups:
            return
        
        # إعادة تعيين مجلد الجلسة للتشغيل الجديد
        reset_session_folder()
        
        # Round 14: this loop opens every image of every group THREE times
        # (dimensions, the resolution boost, then the EXIF date). On a USB hard
        # disk with 23666 groups that is minutes of real, necessary work -- and
        # it used to print absolutely nothing, so the console looked dead and
        # users started pressing keys. The selection logic is untouched; only
        # its progress is visible now.
        files_to_delete = []
        with track(console, i18n.get('common.selecting_best'),
                   len(similar_groups)) as (select_progress, select_task):
            for group in similar_groups:
                if len(group) > 1:
                    # الاحتفاظ بأفضل ملف وتحديد الباقي للحذف
                    best_file = file_selector.select_best_file(group)
                    for file_path in group:
                        if file_path != best_file:
                            files_to_delete.append(file_path)
                select_progress.advance(select_task)
        
        # التعامل مع الملفات المحمية مع اختيار المستخدم
        console.print(f"[yellow]{i18n.get('common.checking_permissions')}[/yellow]")
        files_to_delete, protected_count, force_deleted_count = handle_protected_files_with_user_choice(
            files_to_delete, console, subfolder="similar"
        )

        # Round 18: capacity gate. This is the exact operation that died on a
        # real 2 TB library: the recycle bin sat on a 172 GB system disk while
        # the images sat on a 2 TB disk, the disk filled part-way through, every
        # later move failed with ENOSPC, the failures were swallowed, and the
        # report writer hit ENOSPC too - so the run produced 0-byte husks and no
        # report at all. The check now runs BEFORE a single file is touched.
        if not ensure_recycle_bin_capacity(files_to_delete, console):
            return
        
        # جمع معلومات تفصيلية لجميع الملفات قبل الحذف
        all_files_info = {}

        # Round 14: a second full pass over every file of every group -- one
        # header probe plus one EXIF read each. It was silent before, which is
        # why a run could sit at 0% CPU with no output for minutes. Same values
        # are collected in the same order; only the count is shown now.
        _info_total = sum(len(group) for group in similar_groups)
        with track(console, i18n.get('common.collecting_info'),
                   _info_total) as (info_progress, info_task):
            for group in similar_groups:
                for file_path in group:
                    all_files_info[file_path] = self.report_generator.get_detailed_image_info(file_path)
                    info_progress.advance(info_task)
        
        # Add حقيقي similarity بيانات from the أصلي نتيجة
        if 'similarity_data' in result:
            all_files_info['similarity_data'] = result['similarity_data']
        
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
            failed_files = []   # Round 18: moves that returned False or raised
            moved_map = {}   # Round 8: {original path: recycle-bin destination}
            for file_path in files_to_delete:
                try:
                    if file_path:  # تأكد من أن المسار ليس فارغاً
                        # Use a distinct name so we don't shadow the `result`
                        # dict parameter (which holds similar_groups, etc.)
                        move_result = move_to_recycle_bin(file_path, subfolder="similar")
                        if move_result and move_result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                            deleted_files.append(file_path)
                            if move_result != "dry_run":
                                moved_map[file_path] = move_result
                        elif move_result is False:
                            failed_files.append(file_path)
                except Exception as e:
                    # Round 18: this used to be a bare `pass`. When the disk
                    # filled, EVERY remaining move raised here and the run still
                    # looked successful, so the user discovered the problem days
                    # later. Failures are now counted, logged and reported.
                    logging.error("Similar-images move raised for %s: %s", file_path, e)
                    failed_files.append(file_path)

                progress.advance(task)
        
        # Round 8: ONE dry-run summary line instead of one console line per
        # file (the per-file list now lives in imgsniper.log and the report).
        if config.get('safety.dry_run_mode', False):
            console.print(f"[bold magenta]🔍 {i18n.get('safety.dry_run_summary').format(len(deleted_files))}[/bold magenta]")

        # Round 18: failed moves are announced instead of vanishing. Every one of
        # these files is still exactly where it was - the run simply could not
        # move it - and the individual reasons are in imgsniper.log.
        if failed_files:
            console.print(f"[bold yellow]{i18n.get('safety.failed_moves_warning').format(len(failed_files))}[/bold yellow]")
            for path in failed_files:
                logging.error("Similar-images file NOT moved: %s", path)

        # عرض معلومات سلة المحذوفات
        if deleted_files:
            # Round 18: the same deterministic root move_to_recycle_bin() uses,
            # so the announced location can never differ from the real one.
            recycle_bin = get_recycle_bin_root()
            console.print(f"[blue]📁 {i18n.get('common.files_moved_to_recycle').format(len(deleted_files), recycle_bin)}[/blue]")
        
        # Show نهائي ملخص
        total_processed = len(deleted_files) + force_deleted_count
        if total_processed > 0:
            console.print(f"[green]{i18n.get('protected_files.total_processed').format(total_processed, len(deleted_files), force_deleted_count)}[/green]")
        
        if protected_count > 0:
            console.print(f"[yellow]{i18n.get('protected_files.files_skipped_highly_protected').format(protected_count)}[/yellow]")
        
        # تحويل similar_groups قائمة to dict تنسيق for تقرير geneنسبةn
        similar_groups_dict = {}
        for i, group in enumerate(similar_groups):
            if len(group) > 1:  # Only include groups with multiple ملفات
                similar_groups_dict[f"group_{i+1}"] = group
        
        # توليد تقرير with pre-collected inتنسيقion
        try:
            # Round 14: writing 23666 groups of detailed entries is the SECOND
            # silent window of a real run -- it sits right after "Total
            # processed" and can take minutes with no output at all.
            with console.status(i18n.get('common.report_writing')):
                report_path = self.report_generator.generate_similar_report_with_info(similar_groups_dict, deleted_files, all_files_info, moved_map)
            console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        except Exception as report_error:
            # Round 13: never let a report failure mask the completed operation.
            logging.warning('Similar-images report could not be saved after a completed operation: %s',
                            report_error)
            console.print(
                f"[yellow]{i18n.get('common.report_failed').format(report_error)}[/yellow]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")