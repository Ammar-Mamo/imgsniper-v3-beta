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
# Round 21: how far apart two capture dates must be before the DATE criterion
# is allowed to overrule the name-originality gate.
#
# Defined ONCE here, next to DEFAULT_PRIORITY_ORDER, for the same reason: the
# default config, the "Reset to Defaults" action and the shipped settings.json
# must never drift apart.
#
# Why a threshold exists at all. The name gate says "a derived name (copy /
# a '(N)' counter / backup) must not survive against the user's own name". But
# the user's priority order puts DATE FIRST, and an absolute gate silently
# inverted that: measured on the shipped reports, 'IMG-20180617-WA0051 (2).jpg'
# was deleted in favour of 'IMG-20180707-WA0042.jpg' purely because of the '(2)'
# -- even though it was 20 DAYS older. The '(2)' there is a WhatsApp DOWNLOAD
# counter on a different message (WA0051 vs WA0042), not evidence about that
# competitor at all.
#
# So the gap decides which evidence is stronger:
#   * seconds / minutes / hours apart -> the same photo saved or re-downloaded
#     twice; the timestamp cannot say which came first, so the NAME decides;
#   * days / months / years apart -> two genuinely different capture events, and
#     the user's #1 priority (date) decides -- the older file survives even if
#     its name carries a copy marker.
#
# 24 hours is the natural boundary between those two readings, and it is a
# setting (priorities.name_gate_date_gap_hours) so it can be tuned without code.
# 0 lets ANY real gap overrule the gate (the date nearly always wins); a very
# large value means the gap is never big enough, so the gate stays absolute.
#
# NOTE: this threshold does NOT apply to machine-generated names (a recovery
# tool's carve, 'Recovered_jpg_file(N).jpg'). Those are banned absolutely from
# beating a real user/camera name, whatever their EXIF says -- a name the
# recovery program invented carries no identity at all.
# ---------------------------------------------------------------------------
DEFAULT_NAME_GATE_DATE_GAP_HOURS = 24

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

# Round 17: which SKIP REASONS Recovery Mode actually lifts.
#
# A real recovery scan reported "61 files were NOT scanned" and then advised
# "Settings -> Recovery Mode scans these files too" while Recovery Mode was
# ALREADY ON. Both halves were wrong: the advice named a mode the user had
# already enabled, and the 61 files were skipped by filters.min_file_size_bytes
# -- a floor Recovery Mode deliberately does NOT lift (a 3-byte Android cache
# stub is not a photo, and lowering the floor would drag 0-byte files into
# duplicate groups).
#
# So the advice is now conditional on this set: it is only printed when at least
# one skipped file was dropped by a limit Recovery Mode genuinely removes.
# 'system', 'unreadable', 'not_regular' and 'own_output' are absent by design --
# they are safety rules, not tunables, in both modes.
RECOVERY_LIFTABLE_REASONS = ('too_large', 'excluded_pattern', 'hidden')


def recovery_mode_active(filters=None) -> bool:
    """True when the scan filters are the relaxed Recovery Mode values.

    Detected from the VALUES, never from a separate flag: a menu cannot claim a
    state the filters do not have, and a user who edits settings.json by hand
    still sees the truth.

    Lives here rather than in the CLI because ``announce_scan_skips`` needs the
    same answer to stop advising a mode that is already enabled -- and both
    callers already import this module, so there is no duplication and no
    circular import.
    """
    if filters is None:
        filters = config.get('filters', {}) or {}
    if not isinstance(filters, dict):
        return False
    try:
        no_cap = int(filters.get('max_file_size_mb', 0) or 0) == 0
    except (TypeError, ValueError):
        no_cap = False
    return (no_cap
            and bool(filters.get('include_hidden', False))
            and not (filters.get('exclude_patterns') or []))


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
                # Round 21: removed "exif_priority" and "modified_name_priority".
                # Neither was read anywhere in src/ -- they were dead keys that
                # looked like controls. exif_priority was superseded by
                # date_priority (which now applies to BOTH filename and EXIF
                # dates), and modified_name_priority by the name-originality gate.
                # Round 21: how far apart two dates must be before the DATE is
                # allowed to overrule the name-originality gate. Below it, a
                # seconds/minutes/hours gap is treated as "the same photo saved
                # twice" and the cleaner name wins; at or above it the gap is a
                # real capture-time difference and the user's #1 priority (date)
                # decides -- so an older 'photo (96).jpg' survives against a
                # newer 'photo.jpg'. 0 lets any real gap overrule the gate.
                "name_gate_date_gap_hours": DEFAULT_NAME_GATE_DATE_GAP_HOURS
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