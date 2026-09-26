"""
CLI settings and configuration handling functionality
"""
# واجهة سطر الأوامر - التفاعل مع المستخدم عبر Terminal

from typing import List, Any
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Confirm
from rich.text import Text

from ..core.config import config, DEFAULT_PRIORITY_ORDER
from ..core.i18n.i18n import i18n


class CLISettingsHandler:
    """Handle CLI settings and configuration operations."""
    
    def __init__(self, console: Console):
        self.console = console
    
    def handle_priority_settings(self):
        """Handle priority settings configuration."""
        while True:
            self.console.clear()
            
            title = Text(i18n.get('priorities.title'), style="bold blue")
            self.console.print(Panel(title, expand=False))
            self.console.print()
            
            # عرض الإعدادات الحالية
            self.console.print(f"[bold]{i18n.get('priorities.current_settings')}[/bold]")
            
            # جلب أولوية أمر
            priority_order = config.get('priorities.order', [1, 2, 3, 4])
            if not isinstance(priority_order, list):
                priority_order = [1, 2, 3, 4]
            priorities = ['resolution', 'size', 'date', 'filename']
            
            self.console.print(f"[bold]{i18n.get('priorities.priority_order')}:[/bold]")
            for i, priority_type in enumerate(priorities):
                order_pos = priority_order[i] if i < len(priority_order) else i + 1
                enabled = config.get(f'priorities.{priority_type}_priority', True)
                status = "✅" if enabled else "❌"
                self.console.print(f"  {order_pos}. {status} {i18n.get(f'priorities.{priority_type}')}")
            
            self.console.print()
            self.console.print(f"🔢 {i18n.get('priorities.phash_threshold')}: {config.get('processing.phash_threshold', 5)}")
            self.console.print(f"📅 {i18n.get('priorities.date')}: {config.get('priorities.date_priority', 'oldest')}")
            self.console.print()
            
            self.console.print(f"[bold]{i18n.get('priorities.options')}[/bold]")
            self.console.print(f"1 - {i18n.get('priorities.toggle_resolution')}")
            self.console.print(f"2 - {i18n.get('priorities.toggle_size')}")
            self.console.print(f"3 - {i18n.get('priorities.change_date')}")
            self.console.print(f"4 - {i18n.get('priorities.change_threshold')}")
            self.console.print(f"5 - {i18n.get('priorities.change_order')}")
            self.console.print(f"6 - {i18n.get('scan_modes.title')}")
            self.console.print(f"7 - {i18n.get('priorities.reset_defaults')}")
            self.console.print(f"0 - {i18n.get('priorities.back')}")
            self.console.print()
            
            try:
                choice = IntPrompt.ask("", choices=[str(i) for i in range(8)], default="0")
                choice_int = int(choice)
                
                if choice_int == 0:
                    break
                elif choice_int == 1:
                    current = config.get('priorities.resolution_priority', True)
                    config.set('priorities.resolution_priority', not current)
                    self.console.print(f"[green]{i18n.get('priorities.resolution_updated').format(not current)}[/green]")
                elif choice_int == 2:
                    current = config.get('priorities.size_priority', True)
                    config.set('priorities.size_priority', not current)
                    self.console.print(f"[green]{i18n.get('priorities.size_updated').format(not current)}[/green]")
                elif choice_int == 3:
                    current = config.get('priorities.date_priority', 'oldest')
                    new_value = 'newest' if current == 'oldest' else 'oldest'
                    config.set('priorities.date_priority', new_value)
                    self.console.print(f"[green]{i18n.get('priorities.date_updated').format(new_value)}[/green]")
                elif choice_int == 4:
                    current = config.get('processing.phash_threshold', 5)
                    if not isinstance(current, int):
                        current = 5
                    self.console.print(f"{i18n.get('priorities.threshold_info')}")
                    new_threshold = IntPrompt.ask(i18n.get('priorities.enter_threshold'), default=current)
                    new_threshold_int = int(new_threshold)
                    if 0 <= new_threshold_int <= 64:
                        config.set('processing.phash_threshold', new_threshold_int)
                        self.console.print(f"[green]{i18n.get('priorities.threshold_updated').format(new_threshold_int)}[/green]")
                    else:
                        self.console.print(f"[red]{i18n.get('priorities.invalid_threshold')}[/red]")
                elif choice_int == 5:
                    self._handle_priority_order()
                elif choice_int == 6:
                    self._handle_scan_modes()
                elif choice_int == 7:
                    if Confirm.ask(i18n.get('priorities.confirm_reset')):
                        config.set('priorities.resolution_priority', True)
                        config.set('priorities.size_priority', True)
                        config.set('priorities.date_priority', 'oldest')
                        # Use the single canonical default so Reset always
                        # matches a fresh install (no more silent drift).
                        config.set('priorities.order', list(DEFAULT_PRIORITY_ORDER))
                        config.set('processing.phash_threshold', 5)
                        self.console.print(f"[green]{i18n.get('priorities.reset_complete')}[/green]")
                
                if choice_int != 0:
                    input(i18n.get('common.press_any_key'))
                    
            except KeyboardInterrupt:
                break
    
    def _handle_priority_order(self):
        """Handle priority order configuration with duplicate-rank validation."""
        self.console.clear()
        self.console.print(f"[bold]{i18n.get('priorities.change_order')}[/bold]")
        self.console.print(f"{i18n.get('priorities.order_info')}")
        self.console.print()

        priorities = ['resolution', 'size', 'date', 'filename']
        current_order = config.get('priorities.order', list(DEFAULT_PRIORITY_ORDER))
        if not isinstance(current_order, list) or sorted(current_order) != [1, 2, 3, 4]:
            current_order = list(DEFAULT_PRIORITY_ORDER)
        new_order = list(current_order)

        while True:
            for i, priority_type in enumerate(priorities):
                current_pos = new_order[i]
                self.console.print(f"Current: {i18n.get(f'priorities.{priority_type}')} = Position {current_pos}")
                new_pos = IntPrompt.ask(
                    i18n.get('priorities.enter_new_order').format(i18n.get(f'priorities.{priority_type}')),
                    choices=['1', '2', '3', '4'],
                    default=str(current_pos)
                )
                new_order[i] = int(new_pos)

            # Validate: the four ranks must be a permutation of 1..4 (no
            # duplicates). Previously a duplicate like [1,1,2,3] was accepted
            # silently; because Python's sort is stable, the effective order
            # then fell back to the list default and ignored the user's input.
            if sorted(new_order) == [1, 2, 3, 4]:
                break

            self.console.print(f"[red]{i18n.get('priorities.order_duplicate_error')}[/red]")
            self.console.print(f"[yellow]{new_order} -> each position 1-4 must be used exactly once.[/yellow]")
            if not Confirm.ask(i18n.get('priorities.order_retry'), default=True):
                self.console.print(f"[yellow]{i18n.get('common.cancelled')}[/yellow]")
                return

        config.set('priorities.order', new_order)
        self.console.print(f"[green]{i18n.get('priorities.order_updated')}[/green]")
    
    def _handle_scan_modes(self):
        """Handle scan mode selection."""
        from ..utils.helpers.scan_modes import scan_mode_manager
        
        while True:
            self.console.clear()
            
            title = Text(i18n.get('scan_modes.title'), style="bold blue")
            self.console.print(Panel(title, expand=False))
            self.console.print()
            
            self.console.print(f"[bold]{i18n.get('scan_modes.description')}[/bold]")
            self.console.print()
            
            # Show نظام info
            system_info = scan_mode_manager.get_system_info()
            self.console.print(f"💻 CPU: {system_info['cpu_count']} cores ({system_info['cpu_usage']})")
            self.console.print(f"🧠 RAM: {system_info['total_ram_gb']} ({system_info['ram_usage']} used)")
            self.console.print()
            
            # Show متاح وضعs
            modes = scan_mode_manager.get_available_modes()
            current_mode = scan_mode_manager.current_mode
            
            for i, (mode_key, mode_info) in enumerate(modes.items(), 1):
                current_marker = "👉 " if mode_key == current_mode else "   "
                self.console.print(f"{current_marker}{i} - {i18n.get(f'scan_modes.{mode_key}')}")
                self.console.print(f"     {i18n.get('scan_modes.performance_info').format(mode_info['performance'], mode_info['cpu_usage'], mode_info['ram_usage'])}")
                self.console.print()
            
            self.console.print(f"0 - {i18n.get('priorities.back')}")
            self.console.print()
            
            try:
                choice = IntPrompt.ask(i18n.get('scan_modes.select_mode'), choices=[str(i) for i in range(5)], default="0")
                choice_int = int(choice)
                
                if choice_int == 0:
                    break
                
                mode_keys = list(modes.keys())
                selected_mode = mode_keys[choice_int - 1]
                
                # Special تحذير for ultra وضع
                if selected_mode == 'ultra':
                    if not Confirm.ask(i18n.get('scan_modes.warning_ultra')):
                        continue
                
                # التحقق من صحة وضع for نظام
                if scan_mode_manager.validate_mode_for_system(selected_mode):
                    scan_mode_manager.set_mode(selected_mode)
                    mode_name = modes[selected_mode]['name']
                    self.console.print(f"[green]{i18n.get('scan_modes.mode_selected').format(mode_name)}[/green]")
                    input(i18n.get('common.press_any_key'))
                    break
                else:
                    self.console.print("[red]⚠️ Your system doesn't meet the requirements for this mode![/red]")
                    input(i18n.get('common.press_any_key'))
                    
            except KeyboardInterrupt:
                break