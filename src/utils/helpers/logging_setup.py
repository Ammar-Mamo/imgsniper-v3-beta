"""
Central logging configuration for ImgSniper.

Audit finding P2-20: config/settings.json ships a complete "logging" section
(level, file, max_size_mb, backup_count, format) but NOTHING in the project
ever called logging.basicConfig() / logging.config.dictConfig() or attached a
handler. The only two logging.warning() calls in the codebase
(similarity_group_finder.py, batch + completed-future error paths) therefore
fell through to the root logger's ``lastResort`` handler - bare unformatted
text on stderr - and were NEVER written to imgsniper.log. Batch failures in
the parallel similarity path left no persistent trace, which is exactly the
moment a log is needed.

This module reads that settings section once at boot and attaches a rotating,
UTF-8 encoded file handler.

Design notes:
  * File handler ONLY, deliberately. The CLI is an interactive Rich UI with
    live progress bars; a StreamHandler would interleave log lines with the
    rendered layout and corrupt it. The settings section defines no console
    target either, so nothing is being ignored.
  * UTF-8 encoding is forced on the file handler. Log messages can contain
    Arabic text and emoji (paths, filenames, translated reasons). The Windows
    console code page (cp1256/cp1252) cannot encode those, which is why the
    file - not the console - is the log target.
  * setup_logging() NEVER raises. Logging is a convenience; a read-only
    install directory or a log file locked by another process must not be
    able to stop ImgSniper from running.
"""

import logging
import logging.config
from pathlib import Path

# src/utils/helpers/logging_setup.py -> helpers -> utils -> src -> project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Used for any key that is missing or unusable in settings.json.
DEFAULTS = {
    'level': 'INFO',
    'file': 'imgsniper.log',
    'max_size_mb': 10,
    'backup_count': 5,
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
}

# Minimal config used when the user's logging section cannot be applied. It
# installs a NullHandler so logging calls stay cheap and silent instead of
# degrading to lastResort stderr output.
_NULL_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'null': {'class': 'logging.NullHandler'}},
    'root': {'level': logging.INFO, 'handlers': ['null']},
}

_configured = False
_log_file_path = None


def _resolve_level(value):
    """Turn a settings value into a numeric logging level, defaulting to INFO."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    name = str(value if value is not None else DEFAULTS['level']).strip().upper()
    level = logging.getLevelName(name)
    # getLevelName() returns a string like "Level BOGUS" for unknown names.
    return level if isinstance(level, int) else logging.INFO


def _resolve_int(value, default, minimum=0):
    """Best-effort int conversion with a sane fallback and a floor."""
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    return result if result >= minimum else minimum


def _resolve_max_bytes(value):
    """Convert the max_size_mb setting into bytes. 0 means "do not rotate"."""
    try:
        mb = float(value)
    except (TypeError, ValueError):
        mb = float(DEFAULTS['max_size_mb'])
    if mb < 0:
        mb = 0.0
    return int(mb * 1024 * 1024)


def _resolve_format(value):
    """
    Validate the configured format string, falling back to the default.

    logging validates format strings LAZILY - at emit time, not at config
    time - so dictConfig() happily accepts "%(bogus)s". A typo in
    settings.json would then surface as an ugly "--- Logging error ---"
    traceback on stderr for every single record instead of failing once at
    boot. Probing a throwaway record here turns that into a silent fallback.
    """
    fmt = value or DEFAULTS['format']
    if not isinstance(fmt, str) or not fmt.strip():
        return DEFAULTS['format']
    try:
        probe = logging.LogRecord('imgsniper', logging.INFO, __file__, 1,
                                  'format probe', None, None)
        logging.Formatter(fmt).format(probe)
    except Exception:
        return DEFAULTS['format']
    return fmt


def get_log_file_path():
    """Absolute path of the attached log file, or None if logging is file-less."""
    return _log_file_path


def setup_logging(settings=None, force=False):
    """
    Configure the root logger from the "logging" section of settings.json.

    Args:
        settings: Optional dict to use instead of reading the live config.
            May be either the logging section itself ({"level": ..., "file":
            ...}) or a full settings dict containing a "logging" key.
        force: Re-apply the configuration even if it was already applied.
            dictConfig() replaces root handlers, so calling this repeatedly
            without force would be a no-op rather than stacking handlers.

    Returns:
        True if a log file was attached, False if logging had to fall back to
        a NullHandler. Never raises.
    """
    global _configured, _log_file_path

    if _configured and not force:
        return _log_file_path is not None

    # ---- resolve the settings section -------------------------------------
    if settings is None:
        settings = {}
        try:
            from src.core.config import config as _app_config
            settings = _app_config.get('logging', {}) or {}
        except Exception:
            settings = {}
    if isinstance(settings, dict) and isinstance(settings.get('logging'), dict):
        settings = settings['logging']
    if not isinstance(settings, dict):
        settings = {}

    level = _resolve_level(settings.get('level'))
    fmt = _resolve_format(settings.get('format'))
    max_bytes = _resolve_max_bytes(settings.get('max_size_mb'))
    backup_count = _resolve_int(settings.get('backup_count'),
                                DEFAULTS['backup_count'], minimum=0)

    raw_file = settings.get('file') or DEFAULTS['file']
    log_path = Path(str(raw_file))
    if not log_path.is_absolute():
        log_path = PROJECT_ROOT / log_path

    # ---- build the handler set --------------------------------------------
    handlers = {}
    root_handlers = []

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers['file'] = {
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': str(log_path),
            # maxBytes=0 disables rotation, which is what RotatingFileHandler
            # documents; useful if someone sets max_size_mb to 0.
            'maxBytes': max_bytes,
            'backupCount': backup_count,
            'encoding': 'utf-8',
        }
        root_handlers.append('file')
    except OSError:
        # Unwritable location - fall through to the null handler below.
        handlers = {}
        root_handlers = []

    if not root_handlers:
        handlers['null'] = {'class': 'logging.NullHandler'}
        root_handlers.append('null')

    dict_config = {
        'version': 1,
        # Keep third-party loggers (PIL, urllib3, ...) working; disabling them
        # would silently mute warnings such as PIL's "Corrupt EXIF data".
        'disable_existing_loggers': False,
        'formatters': {'standard': {'format': fmt}},
        'handlers': handlers,
        'root': {'level': level, 'handlers': root_handlers},
    }

    try:
        logging.config.dictConfig(dict_config)
    except Exception:
        # A malformed logging section (bad class name, bad format string, a
        # filename that is actually a directory, ...) must not stop ImgSniper.
        try:
            logging.config.dictConfig(_NULL_CONFIG)
        except Exception:
            pass
        _configured = True
        _log_file_path = None
        return False

    _configured = True
    _log_file_path = log_path if 'file' in handlers else None
    return _log_file_path is not None
