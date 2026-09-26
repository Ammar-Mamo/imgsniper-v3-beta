"""
CLI operation handling functionality
"""
# واجهة سطر الأوامر - التفاعل مع المستخدم عبر Terminal


from rich.console import Console
from rich.prompt import Confirm, IntPrompt

from ..core.config import config
from ..core.i18n.i18n import i18n
from ..core.processors.image_processor import ImageProcessor


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
            if not Confirm.ask(i18n.get('safety.max_files_confirm'), default=False):
                return False
        
        # 3) Confirmation prompt -- now controlled by config, not hardcoded.
        if not config.get('safety.confirm_before_delete', True):
            return True
        
        self.console.print(f"\n[yellow]⚠️ {i18n.get('common.confirm_delete')}[/yellow]")
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
        
        input(i18n.get('common.press_any_key'))
    
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
        
        input(i18n.get('common.press_any_key'))
    
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
        
        input(i18n.get('common.press_any_key'))
    
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
        
        input(i18n.get('common.press_any_key'))
    
    def handle_watermark_removal(self):
        """معالجة عملية إزالة العلامات المائية - قادم قريباً."""
        self.console.print(f"[yellow]{i18n.get('common.coming_soon')}[/yellow]")
        input(i18n.get('common.press_any_key'))
    
    def handle_face_detection_delete(self):
        """Handle face detection and deletion."""
        self.console.print(f"[yellow]{i18n.get('common.coming_soon')}[/yellow]")
        input(i18n.get('common.press_any_key'))
    
    def _get_minimum_dimensions(self) -> tuple:
        """Get minimum dimensions for small images from user."""
        try:
            self.console.print(f"\n[bold blue]📏 Set Minimum Image Dimensions[/bold blue]")
            self.console.print(f"[dim]Default: 300x300 pixels[/dim]")
            
            min_width = IntPrompt.ask(
                "📏 Minimum width (pixels)", 
                default=300
            )
            
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