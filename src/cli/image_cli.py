"""
Image processing CLI interface - Main coordinator class
"""
# واجهة سطر الأوامر - التفاعل مع المستخدم عبر Terminal


import sys
from rich.console import Console

from .cli_menu_handler import CLIMenuHandler
from .cli_operation_handler import CLIOperationHandler


class ImageCLI:
    """Main coordinator for image processing CLI interface."""
    
    def __init__(self, console: Console):
        self.console = console
        
        # تهيئة معالجات متخصصة
        self.menu_handler = CLIMenuHandler(console)
        self.operation_handler = CLIOperationHandler(console, self.menu_handler)
    
    def run(self):
        """Run the image processing menu."""
        while True:
            choice = self.menu_handler.show_image_menu()
            
            if choice == 0:
                sys.exit(0)
            elif choice == 1:
                self.operation_handler.handle_corrupted_images()
            elif choice == 2:
                self.operation_handler.handle_duplicate_images()
            elif choice == 3:
                self.operation_handler.handle_similar_images()
            elif choice == 4:
                self.operation_handler.handle_small_images()
            elif choice == 5:
                self.operation_handler.handle_watermark_removal()
            elif choice == 6:
                self.operation_handler.handle_face_detection_delete()
            elif choice == 7:
                # Round 18: undo the image deletions (corrupted / duplicates /
                # similar / small) and nothing else.
                self.operation_handler.handle_restore('images')
            elif choice == 8:
                # Round 8: settings moved to the MAIN menu -- this menu now
                # contains image operations only.
                break