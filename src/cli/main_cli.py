# واجهة سطر الأوامر - التفاعل مع المستخدم عبر Terminal

"""
Main CLI interface for ImgSniper
"""

import os
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.text import Text

from ..core.config import config
from ..core.i18n.i18n import i18n
from .image_cli import ImageCLI

class MainCLI:
    """Main CLI interface."""
    
    def __init__(self):
        self.console = Console()
        self.image_cli = ImageCLI(self.console)
        
        # إنشاء المجلدات الضرورية
        self._create_directories()
        
        # تعيين اللغة من الإعدادات
        language = config.get('language', 'ar')
        if language and isinstance(language, str):
            i18n.set_language(language)
    
    def _create_directories(self):
        """Create necessary directories (recycle bin and reports)."""
        base_path = Path.cwd()

        # Create the recycle bin folder. parents=True so a nested path like
        # "bin/2025/session" works instead of raising FileNotFoundError.
        recycle_bin_path = config.get('paths.recycle_bin', 'recycle-bin')
        if recycle_bin_path and isinstance(recycle_bin_path, str):
            recycle_bin = base_path / recycle_bin_path
            recycle_bin.mkdir(parents=True, exist_ok=True)

        # Create the reports folder (also supports nested paths)
        reports_path = config.get('paths.reports', 'reports')
        if reports_path and isinstance(reports_path, str):
            reports = base_path / reports_path
            reports.mkdir(parents=True, exist_ok=True)
    
    def run(self):
        """Run the main CLI loop."""
        while True:
            choice = self._show_language_menu()
            
            if choice == 0:
                break
            elif choice == 1:
                i18n.set_language("en")
                config.set('language', 'en')
                self._show_category_menu()
            elif choice == 2:
                i18n.set_language("ar")
                config.set('language', 'ar')
                self._show_category_menu()
    
    def _show_language_menu(self) -> int:
        """Show language selection menu."""
        self.console.clear()
        
        title = Text(i18n.get('main_menu.title'), style="bold blue")
        self.console.print(Panel(title, expand=False))
        self.console.print()
        
        self.console.print(f"[bold]{i18n.get('main_menu.language_selection') or 'Language Selection:'}[/bold]")
        self.console.print(f"1 - {i18n.get('main_menu.english') or 'English'}")
        self.console.print(f"2 - {i18n.get('main_menu.arabic') or 'عربي'}")
        self.console.print(f"0 - {i18n.get('main_menu.exit') or 'Exit'}")
        self.console.print()
        
        try:
            choice = IntPrompt.ask("", choices=["0", "1", "2"], default="0")
            return int(choice)
        except KeyboardInterrupt:
            return 0
    
    def _show_category_menu(self):
        """Show category selection menu."""
        while True:
            self.console.clear()
            
            title = Text(i18n.get('main_menu.title'), style="bold blue")
            self.console.print(Panel(title, expand=False))
            self.console.print()
            
            self.console.print(f"1 - {i18n.get('categories.images')}")
            self.console.print(f"2 - {i18n.get('categories.videos')}")
            self.console.print(f"3 - {i18n.get('categories.office')}")
            self.console.print(f"4 - {i18n.get('categories.archives')}")
            self.console.print(f"5 - {i18n.get('categories.others')}")
            self.console.print(f"6 - {i18n.get('categories.back_to_languages')}")
            self.console.print(f"0 - {i18n.get('categories.exit')}")
            self.console.print()
            
            try:
                choice = IntPrompt.ask("", choices=["0", "1", "2", "3", "4", "5", "6"], default="0")
                choice_int = int(choice)
                
                if choice_int == 0:
                    sys.exit(0)
                elif choice_int == 1:
                    self.image_cli.run()
                elif choice_int == 2:
                    self._show_coming_soon()
                elif choice_int == 3:
                    self._show_coming_soon()
                elif choice_int == 4:
                    self._show_coming_soon()
                elif choice_int == 5:
                    self._show_coming_soon()
                elif choice_int == 6:
                    break
                    
            except KeyboardInterrupt:
                break
    
    def _show_coming_soon(self):
        """Show coming soon message."""
        self.console.print(f"\n[yellow]{i18n.get('common.coming_soon')}[/yellow]")
        input(i18n.get('common.press_any_key'))
