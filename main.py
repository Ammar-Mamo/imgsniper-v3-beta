
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
import logging
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
from src.core.config import config
from src.core.i18n.i18n import get_text
from src.utils.helpers.logging_setup import setup_logging
# Round 6: importing image_codec registers pillow-heif's HEIC/HEIF opener
# (when installed) as a Pillow plugin for the whole process.
from src.utils.helpers.image_codec import codec_status

def main():
    """Main entry point for the application."""
    # Audit finding P2-20: configure logging ONCE at boot from the "logging"
    # section of config/settings.json. Until now nothing in the project ever
    # attached a handler, so the logging.warning() calls in the parallel
    # similarity path only reached the root logger's lastResort handler (bare
    # unformatted stderr text) and imgsniper.log was never written at all.
    # setup_logging() is side-effect safe: it never raises.
    setup_logging()

    # Round 6: log codec availability once per run. RAW (cr2/nef/...) and
    # HEIC/HEIF decode through rawpy / pillow-heif when installed; otherwise
    # such files are counted and announced as excluded (see the detectors)
    # instead of being silently ignored.
    _codecs = codec_status()
    logging.getLogger('imgsniper.main').info(
        'Optional image codecs: HEIF=%s RAW=%s', _codecs['heif'], _codecs['raw'])

    # Round 7: log the priority order actually loaded, so any unexpected
    # "revert to default" is visible in imgsniper.log instead of a mystery.
    logging.getLogger('imgsniper.main').info(
        'Loaded priority order: %s date_priority=%s',
        config.get('priorities.order'), config.get('priorities.date_priority'))

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