"""
CLI menu handling functionality
"""
# واجهة سطر الأوامر - التفاعل مع المستخدم عبر Terminal

from typing import List, Optional
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.text import Text

from ..core.i18n.i18n import i18n
from ..utils.helpers.console_input import flush_pending_input


class CLIMenuHandler:
    """Handle CLI menu display and navigation."""
    
    def __init__(self, console: Console):
        self.console = console
    
    def show_image_menu(self) -> int:
        """Show image processing menu."""
        self.console.clear()
        
        title = Text(i18n.get('main_menu.title'), style="bold blue")
        self.console.print(Panel(title, expand=False))
        self.console.print()
        
        self.console.print(f"1 - {i18n.get('image_operations.corrupted')}")
        self.console.print(f"2 - {i18n.get('image_operations.duplicates')}")
        self.console.print(f"3 - {i18n.get('image_operations.similar')}")
        self.console.print(f"4 - {i18n.get('image_operations.small')}")
        self.console.print(f"5 - {i18n.get('image_operations.watermark')}")
        self.console.print(f"6 - {i18n.get('image_operations.face_detect_delete')}")
        # Round 18: undo for THIS section only -- it reads the image deletion
        # reports and cannot touch a video, an archive or an office file.
        self.console.print(f"7 - {i18n.get('restore.menu_option')}")
        # Round 8: settings moved to the MAIN menu -- this menu now contains
        # image operations only.
        self.console.print(f"8 - {i18n.get('image_operations.back')}")
        self.console.print(f"0 - {i18n.get('image_operations.exit')}")
        self.console.print()
        
        try:
            flush_pending_input()
            choice = IntPrompt.ask("", choices=[str(i) for i in range(9)], default="0")
            return int(choice)
        except KeyboardInterrupt:
            return 8
    
    def show_section_menu(self, section_key: str) -> Optional[str]:
        """Round 9: operation menu of a NON-image section (office/archives/other).

        The entries are generated FROM file_categories.SECTIONS, so adding an
        extension there adds a menu line here automatically. Returns the option
        id ('word', 'zip', 'all', 'custom', ...) or None when the user goes
        back.
        """
        from ..core.file_categories import SECTIONS
        
        options = SECTIONS[section_key]['options']
        
        self.console.clear()
        
        title = Text(i18n.get('main_menu.title'), style="bold blue")
        self.console.print(Panel(title, expand=False))
        self.console.print()
        
        for index, (option_id, _extensions, label_key) in enumerate(options, start=1):
            self.console.print(f"{index} - {i18n.get(label_key)}")
        # Round 18: the undo entry is a UTILITY, not a scan type, so it is drawn
        # after the scan options instead of being appended to SECTIONS['options'].
        # That list must stay "one entry per scan type" -- other code and the
        # round-9/11 tests rely on options[-1] being the combined 'all' entry.
        restore_index = len(options) + 1
        self.console.print(f"{restore_index} - {i18n.get('restore.menu_option')}")
        self.console.print(f"0 - {i18n.get('common.back')}")
        self.console.print()
        
        try:
            flush_pending_input()
            choice = IntPrompt.ask(
                "", choices=[str(i) for i in range(restore_index + 1)], default="0"
            )
        except KeyboardInterrupt:
            return None
        
        choice_int = int(choice)
        if choice_int == 0:
            return None
        if choice_int == restore_index:
            return 'restore'
        return options[choice_int - 1][0]
    
    def get_folders(self) -> List[str]:
        """Get folder paths from user input."""
        try:
            flush_pending_input()
            folder_count = IntPrompt.ask(i18n.get('common.folders_count'), default=1)
            folders = []
            
            for i in range(folder_count):
                while True:  # حلقة للتأكد من إدخال مسار صحيح
                    flush_pending_input()
                    folder_path = Prompt.ask(i18n.get('common.folder_path').format(i + 1))
                    
                    # التحقق من أن المسار ليس فارغاً
                    if not folder_path.strip():
                        self.console.print(f"[red]{i18n.get('common.empty_path_error')}[/red]")
                        continue  # إعادة طلب المسار
                    
                    # التحقق من وجود المجلد
                    if Path(folder_path).exists():
                        folders.append(folder_path)
                        break  # الخروج من الحلقة عند نجاح إدخال المسار
                    else:
                        self.console.print(f"[red]{i18n.get('common.folder_not_found').format(folder_path)}[/red]")
                        # الاستمرار في الحلقة لإعادة طلب المسار
                    
            return folders
        except KeyboardInterrupt:
            return []
    
