
# ══════════════════════════════════════════════════════════════════════════════
# 🖼️ ImgSniper v3 - أداة معالجة الصور المتقدمة
# ══════════════════════════════════════════════════════════════════════════════
# الوصف: برنامج شامل لتنظيف وتحليل مجموعات الصور الكبيرة
# المميزات: 
#   • كشف الصور المكررة والمتشابهة
#   • إزالة العلامات المائية
#   • كشف الصور التالفة والصغيرة
#   • تقارير تفصيلية وإحصائيات
#   • واجهة سطر أوامر بلغات متعددة
# ══════════════════════════════════════════════════════════════════════════════

#!/usr/bin/env python3
"""
ImgSniper - Advanced Image Processing Tool
A powerful tool for batch processing millions of images across all operating systems.
"""

import sys
import os
from pathlib import Path

# Safety net: never crash on Unicode output (emoji/Arabic) when the console
# code page is limited (e.g. Windows cp1256/cp1252) or output is redirected.
# Keeps the native encoding but replaces unencodable chars instead of raising
# UnicodeEncodeError, which previously aborted file operations mid-run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.cli.main_cli import MainCLI
from src.core.i18n.i18n import get_text

def main():
    """Main entry point for the application."""
    try:
        cli = MainCLI()
        cli.run()
    except KeyboardInterrupt:
        print(get_text('program_terminated'))
        sys.exit(0)
    except Exception as e:
        print(get_text('unexpected_error').format(e))
        sys.exit(1)

if __name__ == "__main__":
    main()