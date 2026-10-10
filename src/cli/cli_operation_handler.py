"""
CLI operation handling functionality
"""
# واجهة سطر الأوامر - التفاعل مع المستخدم عبر Terminal


from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt

from ..core.config import config
from ..core.i18n.i18n import i18n
from ..core.processors.image_processor import ImageProcessor
from ..utils.helpers.console_input import flush_pending_input, pause


class CLIOperationHandler:
    """Handle CLI operations for image processing."""
    
    def __init__(self, console: Console, menu_handler):
        self.console = console
        self.menu_handler = menu_handler
        self.processor = ImageProcessor()
    
    def _safety_gate(self, file_count: int = 0) -> bool:
        """Single gate honouring the `safety.*` config section before deletion.

        Previously `safety.dry_run_mode`, `safety.confirm_before_delete` and
        `safety.max_files_per_operation` existed in settings.json but were read
        by NO code at all -- the confirmation prompt was hardcoded and the other
        two were completely inert, giving users a false sense of protection.

        Returns True when the destructive operation may proceed.
        """
        # 1) Announce dry-run so the user knows nothing will actually be moved.
        if config.get('safety.dry_run_mode', False):
            self.console.print(
                f"[bold magenta]🔍 {i18n.get('safety.dry_run_banner')}[/bold magenta]"
            )
        
        # 2) Guard against accidentally huge batches.
        max_files = config.get('safety.max_files_per_operation', 0)
        try:
            max_files = int(max_files)
        except (TypeError, ValueError):
            max_files = 0
        if max_files > 0 and file_count > max_files:
            self.console.print(
                f"[red]⛔ {i18n.get('safety.max_files_exceeded').format(file_count, max_files)}[/red]"
            )
            flush_pending_input()
            if not Confirm.ask(i18n.get('safety.max_files_confirm'), default=False):
                return False
        
        # 3) Confirmation prompt -- now controlled by config, not hardcoded.
        if not config.get('safety.confirm_before_delete', True):
            return True
        
        self.console.print(f"\n[yellow]⚠️ {i18n.get('common.confirm_delete')}[/yellow]")
        flush_pending_input()
        return Confirm.ask(i18n.get('common.confirm_delete'))
    
    def _count_deletable(self, groups) -> int:
        """Best-effort count of files that WOULD be deleted (all minus one kept per group).

        Defensive: the duplicate/similar detectors return groups as lists of
        paths (or dicts wrapping them). Anything unexpected yields 0, which
        simply disables the max_files guard rather than reporting a wrong number.
        """
        total = 0
        try:
            # duplicate_detector returns a DICT {sha256: [paths]};
            # similarity_detector returns a LIST of [paths].
            items_iter = groups.values() if isinstance(groups, dict) else (groups or [])
            for g in items_iter:
                if isinstance(g, dict):
                    items = g.get('files') or g.get('paths') or g.get('group') or []
                elif isinstance(g, (list, tuple, set)):
                    items = g
                else:
                    items = []
                total += max(0, len(items) - 1)   # one file per group is kept
        except Exception:
            return 0
        return total
    
    def handle_corrupted_images(self):
        """Handle corrupted images detection and deletion."""
        try:
            # جلب المجلدات من المستخدم
            folders = self.menu_handler.get_folders()
            if not folders:
                return
            
            # البحث عن الصور التالفة
            result = self.processor.find_corrupted_images(folders, self.console)
            
            if result and result['corrupted_files']:
                # بوابة الأمان: dry_run_mode + confirm_before_delete + max_files
                if self._safety_gate(len(result['corrupted_files'])):
                    self.processor.delete_corrupted_images(result, self.console)
                else:
                    self.console.print(f"[yellow]{i18n.get('common.cancelled')}[/yellow]")
            else:
                self.console.print(f"[green]{i18n.get('corruption.no_corrupted_found')}[/green]")
            
        except Exception as e:
            self.console.print(f"[red]{i18n.get('common.error').format(str(e))}[/red]")
        
        pause(i18n.get('common.press_any_key'))
    
    def handle_duplicate_images(self):
        """Handle duplicate images detection and deletion."""
        try:
            # جلب المجلدات من المستخدم
            folders = self.menu_handler.get_folders()
            if not folders:
                return
            
            # البحث عن الصور المتطابقة
            result = self.processor.find_duplicate_images(folders, self.console)
            
            if result and result['duplicates']:
                # بوابة الأمان: dry_run_mode + confirm_before_delete + max_files
                if self._safety_gate(self._count_deletable(result['duplicates'])):
                    self.processor.delete_duplicate_images(result, self.console)
                else:
                    self.console.print(f"[yellow]{i18n.get('common.cancelled')}[/yellow]")
            else:
                self.console.print(f"[green]{i18n.get('duplicates.no_duplicates_found')}[/green]")
            
        except Exception as e:
            self.console.print(f"[red]{i18n.get('common.error').format(str(e))}[/red]")
        
        pause(i18n.get('common.press_any_key'))
    
    def handle_duplicate_files(self, section_key: str, extensions=None, option_id: str = 'all'):
        """Round 9: SHA-256 duplicate flow for office / archives / other files.

        One flow for every non-image section -- only the extension list and the
        section descriptor change. The "custom" option (Other Files) asks the
        user which extensions to scan and REFUSES to scan when the answer is
        empty/invalid, instead of silently reporting "no duplicates found" for
        a scan that never covered anything.
        """
        from ..core.file_categories import SECTIONS, normalize_extensions

        spec = SECTIONS[section_key]

        try:
            # "Other Files": the user picks the extensions at run time.
            if option_id == 'custom':
                flush_pending_input()
                raw = Prompt.ask(i18n.get('other_operations.enter_extensions'))
                extensions = normalize_extensions(raw)
                if not extensions:
                    self.console.print(
                        f"[yellow]⚠️ {i18n.get('other_operations.no_valid_extensions')}[/yellow]"
                    )
                    pause(i18n.get('common.press_any_key'))
                    return
                self.console.print(
                    f"[green]{i18n.get('other_operations.accepted').format(', '.join(extensions))}[/green]"
                )

            # جلب المجلدات من المستخدم
            folders = self.menu_handler.get_folders()
            if not folders:
                return

            # البحث عن المتطابقات: sha256 مع ترشيح بالحجم، وكل امتداد يقابل نفسه فقط
            if spec.get('engine') == 'video':
                # Round 11: the video section runs the EXACT-duplicate video
                # engine (size pre-filter + sample pre-filter + full SHA-256,
                # then the video filename heuristics). The branch is driven by
                # the registry's 'engine' key, not by a hardcoded section name.
                result = self.processor.find_duplicate_videos(folders, self.console, extensions, spec)
            else:
                result = self.processor.find_duplicate_files(folders, self.console, extensions, spec)

            if result and result['duplicates']:
                # بوابة الأمان: dry_run_mode + confirm_before_delete + max_files
                if self._safety_gate(self._count_deletable(result['duplicates'])):
                    if spec.get('engine') == 'video':
                        self.processor.delete_duplicate_videos(result, self.console, spec, option_id)
                    else:
                        self.processor.delete_duplicate_files(result, self.console, spec)
                else:
                    self.console.print(f"[yellow]{i18n.get('common.cancelled')}[/yellow]")
            else:
                self.console.print(f"[green]{i18n.get(spec['no_duplicates_key'])}[/green]")

        except Exception as e:
            self.console.print(f"[red]{i18n.get('common.error').format(str(e))}[/red]")

        pause(i18n.get('common.press_any_key'))

    def handle_similar_images(self):
        """Handle similar images detection and deletion."""
        try:
            # جلب المجلدات من المستخدم
            folders = self.menu_handler.get_folders()
            if not folders:
                return
            
            # البحث عن الصور المتشابهة
            result = self.processor.find_similar_images(folders, self.console)
            
            if result and result['similar_groups']:
                # بوابة الأمان: dry_run_mode + confirm_before_delete + max_files
                if self._safety_gate(self._count_deletable(result['similar_groups'])):
                    self.processor.delete_similar_images(result, self.console)
                else:
                    self.console.print(f"[yellow]{i18n.get('common.cancelled')}[/yellow]")
            else:
                self.console.print(f"[green]{i18n.get('similarity.no_similar_found')}[/green]")
            
        except Exception as e:
            self.console.print(f"[red]{i18n.get('common.error').format(str(e))}[/red]")
        
        pause(i18n.get('common.press_any_key'))
    
    def handle_small_images(self):
        """Handle small images detection and deletion."""
        try:
            # جلب المجلدات من المستخدم
            folders = self.menu_handler.get_folders()
            if not folders:
                return
            
            # جلب الأبعاد المطلوبة (استخدام القيم الافتراضية أو طلبها من المستخدم)
            min_width, min_height = self._get_minimum_dimensions()
            
            # بوابة الأمان: dry_run_mode + confirm_before_delete
            # (العدد غير معروف قبل الفحص، لذا max_files لا يُطبَّق هنا)
            if self._safety_gate(0):
                result = self.processor.process_small_images(folders, min_width, min_height)
                if result:
                    self.console.print(f"[green]✅ {i18n.get('common.completed')}[/green]")
            else:
                self.console.print(f"[yellow]{i18n.get('common.cancelled')}[/yellow]")
            
        except Exception as e:
            self.console.print(f"[red]{i18n.get('common.error').format(str(e))}[/red]")
        
        pause(i18n.get('common.press_any_key'))
    
    def handle_watermark_removal(self):
        """معالجة عملية إزالة العلامات المائية - قادم قريباً."""
        self.console.print(f"[yellow]{i18n.get('common.coming_soon')}[/yellow]")
        pause(i18n.get('common.press_any_key'))
    
    def handle_face_detection_delete(self):
        """Handle face detection and deletion."""
        self.console.print(f"[yellow]{i18n.get('common.coming_soon')}[/yellow]")
        pause(i18n.get('common.press_any_key'))
    
    def handle_restore(self, section_key: str = 'images'):
        """Round 18: UNDO the deletions of ONE section.

        Reads that section's own deletion reports and copies every removed file
        back to the path the report recorded. Three rules make it safe:

          * DRY RUN FIRST, always -- the plan is computed and shown before a
            single byte is written, and the user confirms explicitly.
          * COPY, never move -- the recycle bin keeps its copies, so a mistake
            here cannot destroy the only remaining copy of a file.
          * NEVER overwrite -- a file already sitting at the original path is
            left alone and the copy lands next to it as *_restored.

        Scoped by construction: RestoreManager only ever reads the report
        prefixes listed in SECTION_OPERATIONS[section_key], so restoring images
        cannot touch a video, an archive or an office file.
        """
        try:
            from ..core.restore_manager import RestoreManager

            self.console.clear()
            self.console.print(
                f"[bold cyan]{i18n.get('restore.title')}[/bold cyan]")
            self.console.print(
                f"[dim]{i18n.get('restore.scope_note').format(section_key)}[/dim]")
            self.console.print(f"[dim]{i18n.get('restore.copy_note')}[/dim]")
            self.console.print(
                f"[dim]{i18n.get('restore.never_overwrite_note')}[/dim]")
            self.console.print()
            self.console.print(i18n.get('restore.scanning'))

            manager = RestoreManager(section_key)
            reports = manager.find_reports()
            report_count = sum(len(v) for v in reports.values())
            if not report_count:
                self.console.print(
                    f"[yellow]{i18n.get('restore.no_reports')}[/yellow]")
                pause(i18n.get('common.press_any_key'))
                return
            self.console.print(
                i18n.get('restore.reports_found').format(report_count))

            # ---- DRY RUN: compute and show the plan, change nothing ----
            plan = manager.build_plan()
            if not plan:
                self.console.print(
                    f"[yellow]{i18n.get('restore.no_files')}[/yellow]")
                pause(i18n.get('common.press_any_key'))
                return
            preview = manager.restore_all(plan, dry_run=True)
            self._print_restore_counts(preview['counts'], dry_run=True)

            flush_pending_input()
            if not Confirm.ask(i18n.get('restore.confirm'), default=False):
                self.console.print(
                    f"[yellow]{i18n.get('restore.cancelled')}[/yellow]")
                # The plan is still worth keeping: it documents what COULD be
                # restored without the user having to run it again.
                self._save_restore_report(manager, section_key, plan, preview)
                pause(i18n.get('common.press_any_key'))
                return

            # ---- REAL RUN ----
            self.console.print(f"\n[bold green]{i18n.get('restore.running')}[/bold green]")
            plan = manager.build_plan()
            result = manager.restore_all(plan, dry_run=False,
                                         progress=self._restore_progress)
            self.console.print(
                f"\n[bold green]{i18n.get('restore.done_title')}[/bold green]")
            self._print_restore_counts(result['counts'], dry_run=False)
            if result.get('restored_bytes'):
                megabytes = result['restored_bytes'] / (1024 * 1024)
                self.console.print(
                    f"  {i18n.get('restore.size')}: {megabytes:.2f} MB")
            self._save_restore_report(manager, section_key, plan, result)

        except Exception as e:
            self.console.print(
                f"[red]{i18n.get('common.error').format(str(e))}[/red]")

        pause(i18n.get('common.press_any_key'))

    def _print_restore_counts(self, counts: dict, dry_run: bool) -> None:
        """Print the outcome of a restore, most important line first."""
        order = [('would_restore', 'restore.would_restore')] if dry_run else \
                [('restored', 'restore.restored')]
        order += [('already_there', 'restore.already_there'),
                  ('missing', 'restore.missing'),
                  ('ambiguous', 'restore.ambiguous'),
                  ('error', 'restore.errors')]
        for status, key in order:
            number = counts.get(status, 0)
            if number:
                style = 'red' if status == 'error' else (
                    'yellow' if status in ('missing', 'ambiguous') else 'green')
                self.console.print(f"  [{style}]{i18n.get(key)}: {number}[/{style}]")
        # Any status this list does not know about is still shown, so a future
        # status can never disappear silently from the summary.
        known = {status for status, _key in order}
        for status, number in counts.items():
            if status not in known and number:
                self.console.print(f"  {status}: {number}")

    def _save_restore_report(self, manager, section_key: str,
                             plan, summary) -> None:
        """Write the restore report next to the deletion reports.

        Uses manager.reports_dir so the undo report lands in the SAME folder as
        the reports it was built from -- a user looking for "what happened" finds
        both in one place.
        """
        try:
            from ..utils.reports.restore_report_generator import (
                RestoreReportGenerator)
            path = RestoreReportGenerator(manager.reports_dir) \
                .generate_restore_report(section_key, plan, summary)
            self.console.print(i18n.get('restore.report_saved').format(path))
        except Exception as e:
            # Round 13: a report failure must never mask a completed operation.
            self.console.print(
                f"[yellow]{i18n.get('common.error').format(str(e))}[/yellow]")

    def _restore_progress(self, position: int, total: int, _item) -> None:
        """Progress line for a restore that may cover tens of thousands of files.

        Prints at ~20 milestones instead of per file: a 60,000-file undo would
        otherwise scroll the summary off the screen.
        """
        if not total:
            return
        step = max(1, total // 20)
        if position % step == 0 or position == total:
            percent = (position * 100) // total
            self.console.print(f"  … {position}/{total} ({percent}%)")

    def _get_minimum_dimensions(self) -> tuple:
        """Get minimum dimensions for small images from user."""
        try:
            self.console.print(f"\n[bold blue]📏 Set Minimum Image Dimensions[/bold blue]")
            self.console.print(f"[dim]Default: 300x300 pixels[/dim]")
            
            flush_pending_input()
            min_width = IntPrompt.ask(
                "📏 Minimum width (pixels)", 
                default=300
            )
            
            flush_pending_input()
            min_height = IntPrompt.ask(
                "📏 Minimum height (pixels)", 
                default=300
            )
            
            # التحقق من صحة القيم
            if min_width <= 0 or min_height <= 0:
                self.console.print(f"[red]❌ Dimensions must be greater than 0[/red]")
                return 300, 300  # استخدام القيم الافتراضية
            
            self.console.print(f"[green]✅ Dimensions set to: {min_width}x{min_height}[/green]")
            return min_width, min_height
            
        except KeyboardInterrupt:
            self.console.print(f"[yellow]Using default dimensions: 300x300[/yellow]")
            return 300, 300