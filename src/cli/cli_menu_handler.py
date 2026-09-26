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
        self.console.print(f"7 - {i18n.get('image_operations.face_detect_blur')}")
        self.console.print(f"8 - {i18n.get('image_operations.priorities')}")
        self.console.print(f"9 - {i18n.get('image_operations.back')}")
        self.console.print(f"0 - {i18n.get('image_operations.exit')}")
        self.console.print()
        
        try:
            choice = IntPrompt.ask("", choices=[str(i) for i in range(10)], default="0")
            return int(choice)
        except KeyboardInterrupt:
            return 9
    
    def get_folders(self) -> List[str]:
        """Get folder paths from user input."""
        try:
            folder_count = IntPrompt.ask(i18n.get('common.folders_count'), default=1)
            folders = []
            
            for i in range(folder_count):
                while True:  # حلقة للتأكد من إدخال مسار صحيح
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
    
