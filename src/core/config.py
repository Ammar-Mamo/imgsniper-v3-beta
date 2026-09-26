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
# [1, 2, 3, 4] => resolution first, then size, then date, then filename.
DEFAULT_PRIORITY_ORDER = [1, 2, 3, 4]

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
            "language": "ar",
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
        """
        tmp_path = self.config_path.with_suffix(self.config_path.suffix + '.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
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