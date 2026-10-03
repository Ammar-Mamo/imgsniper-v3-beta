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
from ...utils.helpers.file_utils import move_to_recycle_bin, reset_session_folder, handle_protected_files_with_user_choice
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
        
        files_to_delete = []
        for group in similar_groups:
            if len(group) > 1:
                # الاحتفاظ بأفضل ملف وتحديد الباقي للحذف
                best_file = file_selector.select_best_file(group)
                for file_path in group:
                    if file_path != best_file:
                        files_to_delete.append(file_path)
        
        # التعامل مع الملفات المحمية مع اختيار المستخدم
        console.print("[yellow]🔍 Checking file permissions...[/yellow]")
        files_to_delete, protected_count, force_deleted_count = handle_protected_files_with_user_choice(
            files_to_delete, console, subfolder="similar"
        )
        
        # جمع معلومات تفصيلية لجميع الملفات قبل الحذف
        console.print("[yellow]📊 Collecting file information...[/yellow]")
        all_files_info = {}
        
        # جلب info for جميع ملفات in similar groups
        for group in similar_groups:
            for file_path in group:
                all_files_info[file_path] = self.report_generator.get_detailed_image_info(file_path)
        
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
                except Exception:
                    pass  # المتابعة مع الملفات الأخرى
                
                progress.advance(task)
        
        # Round 8: ONE dry-run summary line instead of one console line per
        # file (the per-file list now lives in imgsniper.log and the report).
        if config.get('safety.dry_run_mode', False):
            console.print(f"[bold magenta]🔍 {i18n.get('safety.dry_run_summary').format(len(deleted_files))}[/bold magenta]")
        
        # عرض معلومات سلة المحذوفات
        if deleted_files:
            recycle_bin_path = config.get('paths.recycle_bin', 'recycle-bin')
            if not recycle_bin_path:
                recycle_bin_path = 'recycle-bin'
            recycle_bin = Path.cwd() / recycle_bin_path
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
            report_path = self.report_generator.generate_similar_report_with_info(similar_groups_dict, deleted_files, all_files_info, moved_map)
            console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        except Exception as report_error:
            # Round 13: never let a report failure mask the completed operation.
            logging.warning('Similar-images report could not be saved after a completed operation: %s',
                            report_error)
            console.print(
                f"[yellow]{i18n.get('common.report_failed').format(report_error)}[/yellow]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")