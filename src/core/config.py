"""
Configuration management for ImgSniper
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

# Canonical factory default for the priority order. Defined ONCE here and
# reused by the default config, the "Reset to Defaults" action and the
# shipped settings.json so they can never drift apart again.
# Positional meaning: [resolution, size, date, filename]; the value at each
# position is that criterion's RANK (1 = highest priority).
# Round 7: changed from [1, 2, 3, 4] to the order the user asked for --
# date first, then resolution, then size, then filename:
# [2, 3, 1, 4] => date(1) > resolution(2) > size(3) > filename(4).
DEFAULT_PRIORITY_ORDER = [2, 3, 1, 4]

# ---------------------------------------------------------------------------
# Round 12: canonical filter values, defined ONCE here (same reasoning as
# DEFAULT_PRIORITY_ORDER) so the "Recovery Mode" toggle and the shipped
# settings.json can never drift apart.
#
# DEFAULT_FILTERS mirrors the filters.* section of config/settings.json exactly.
# RECOVERY_FILTERS is what the toggle writes: every limit that silently hid a
# file from a scan is lifted, because after a data-recovery run the user's whole
# point is to see EVERYTHING -- a 4 GB movie, a "video_backup.mp4", a file in a
# hidden folder. include_system deliberately stays False: "System Volume
# Information" and "$RECYCLE.BIN" are not user data, and a tool that moves files
# must never wander into them.
# ---------------------------------------------------------------------------
DEFAULT_FILTERS = {
    'min_file_size_bytes': 1024,
    'max_file_size_mb': 500,
    'exclude_patterns': ['*.tmp', '*.temp', '*_backup*', '*.bak'],
    'include_hidden': False,
    'include_system': False,
}

RECOVERY_FILTERS = {
    'min_file_size_bytes': 1024,      # sub-KB stubs are noise, not media
    'max_file_size_mb': 0,            # 0 = no upper limit at all
    'exclude_patterns': [],           # never hide a file because of its name
    'include_hidden': True,           # recovery tools write into hidden folders
    'include_system': False,          # ...but system areas stay off limits
}

# The filters Recovery Mode actually changes, in menu-display order.
RECOVERY_TOGGLE_KEYS = ('max_file_size_mb', 'exclude_patterns', 'include_hidden')

class Config:
    """Configuration manager for the application."""
    
    def __init__(self, config_path: str = "config/settings.json"):
        # الحصول على مجلد المشروع الجذر (مستويان للأعلى من هذا الملف)
        project_root = Path(__file__).parent.parent.parent
        self.config_path = project_root / config_path
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        if not self.config_path.exists():
            return self._get_default_config()
            
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"تحذير: خطأ في قراءة ملف الإعدادات، استخدام الإعدادات الافتراضية: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            # Audit finding P2-18: this said "ar" while config/settings.json
            # shipped "en" and main_cli.py fell back to "ar", so the effective
            # language depended on which of the three happened to win. All
            # three now agree on English.
            "language": "en",
            "priorities": {
                "order": DEFAULT_PRIORITY_ORDER,
                "resolution_priority": True,
                "size_priority": True,
                "date_priority": "oldest",
                "exif_priority": "oldest",
                "modified_name_priority": "original"
            },
            "processing": {
                "use_gpu": False,
                "phash_threshold": 5,
                "batch_size": 1000,
                "max_workers": 4
            },
            "paths": {
                "recycle_bin": "recycle-bin",
                "reports": "reports"
            },
            "models": {
                "auto_download": True,
                "cache_models_locally": True,
                "models_directory": "models",
                "cleanup_on_exit": False,
                "validate_integrity": True,
                "max_download_retries": 3,
                "download_timeout_seconds": 300,
                "easyocr": {
                    "languages": ["en", "ar"],
                    "gpu_acceleration": False,
                    "detection_model": "craft_mlt_25k.pth",
                    "recognition_models": {
                        "latin": "latin_g2.pth",
                        "arabic": "arabic_g2.pth"
                    }
                }
            }
        }
    
    def save_config(self):
        """
        Save the current configuration atomically.

        Writes to a temporary file in the SAME directory first, flushes and
        fsyncs it, then uses os.replace() to atomically swap it into place.
        os.replace() is atomic on both Windows and Linux, so the settings
        file is never left half-written (which would corrupt it) if the
        process is killed or the power fails mid-write.

        Two guards keep this side-effect free:

        * No-op writes are skipped. set() can be called many times in a row
          (settings menu, batch updates, test suites); rewriting all 240+
          lines plus an fsync each time is pure overhead, and it also bumps
          the file mtime for a file whose content did not change.
        * The file's existing line-ending style is preserved. A plain
          text-mode open() on Windows translates every '\\n' into '\\r\\n',
          which rewrote the WHOLE file as CRLF while git stores LF
          (core.autocrlf=true). The result was a spurious "every line
          changed" diff on settings.json after a single tiny edit, which
          makes it very hard to review what actually changed.
        """
        payload = json.dumps(self.config, indent=4, ensure_ascii=False)

        # Read what is already on disk so we can (a) skip identical writes and
        # (b) match its line-ending style. A missing/unreadable file is not an
        # error here - we simply fall through and write it fresh with '\n'.
        existing = None
        try:
            with open(self.config_path, 'r', encoding='utf-8', newline='') as f:
                existing = f.read()
        except (IOError, OSError):
            existing = None

        def _normalized(text):
            return text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')

        if existing is not None:
            if _normalized(existing) == _normalized(payload):
                return  # content identical -> leave the file completely alone
            if '\r\n' in existing:
                payload = payload.replace('\n', '\r\n')

        tmp_path = self.config_path.with_suffix(self.config_path.suffix + '.tmp')
        try:
            # newline='' disables Python's newline translation so the payload
            # above lands on disk byte-for-byte as prepared.
            with open(tmp_path, 'w', encoding='utf-8', newline='') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            # Atomic swap into place
            os.replace(tmp_path, self.config_path)
        except (IOError, OSError) as e:
            print(f"خطأ في حفظ ملف الإعدادات: {e}")
            # Clean up the temp file if it was created
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
    
    def get(self, key: str, default=None):
        """Get configuration value by key."""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
                
        return value
    
    def set(self, key: str, value: Any):
        """Set configuration value by key."""
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
            
        config[keys[-1]] = value
        self.save_config()

# مثيل الإعدادات العام
config = Config()