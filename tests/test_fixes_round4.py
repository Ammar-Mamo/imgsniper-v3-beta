# imgSniper v3 -- Round 4 Fix Verification Suite
# Covers P2-20 (logging actually configured from settings.json),
# P2-22 (save_config no-op guard + line-ending preservation)
# and re-asserts the P2-21 bare-except regression.
# Run from project root: python tests/test_fixes_round4.py

import sys, os, re, io, json, tempfile, shutil, logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / 'test_run_round4.log'

# Same safety net main.py applies: this console is cp1256 and the suite logs
# emoji, so without errors='replace' the handler itself would raise.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass

# This suite deliberately does NOT use logging.basicConfig(): P2-20 is about
# setup_logging() owning the ROOT logger, and this suite must keep reporting
# after root has been reconfigured a dozen times over. So `log` gets its own
# handlers plus propagate=False, which makes its output completely immune to
# every setup_logging() call below (and keeps suite records out of the temp
# log files whose contents are being asserted on).
_FMT = logging.Formatter('%(asctime)s [%(levelname)-8s] %(name)s: %(message)s')


class _ResilientFileHandler(logging.Handler):
    """
    A file handler that survives setup_logging() closing every handler.

    logging.config.dictConfig() calls _clearExistingHandlers(), which runs
    logging.shutdown() and CLOSES every registered handler - including this
    suite's own log file. A plain FileHandler therefore silently stopped
    writing from the first setup_logging() call onwards, leaving
    test_run_round4.log truncated at exactly the point where the interesting
    output begins. That matters because run_all.py tells the user to inspect
    these logs when a suite fails. Reopening on demand keeps the log complete.

    (The console StreamHandler needs no such guard: StreamHandler.close() does
    not close the underlying stream, so stdout output was never affected.)
    """

    def __init__(self, path, formatter):
        super().__init__()
        self._path = path
        self.setFormatter(formatter)
        io.open(path, 'w', encoding='utf-8').close()   # truncate once, up front
        self._stream = None

    def _ensure_stream(self):
        if self._stream is None or self._stream.closed:
            self._stream = io.open(self._path, 'a', encoding='utf-8')
        return self._stream

    def emit(self, record):
        try:
            stream = self._ensure_stream()
            stream.write(self.format(record) + '\n')
            stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        try:
            if self._stream is not None and not self._stream.closed:
                self._stream.close()
        except Exception:
            pass
        super().close()


log = logging.getLogger('FIX4')
log.setLevel(logging.INFO)
log.propagate = False
_file_out = _ResilientFileHandler(LOG_FILE, _FMT)
_stream_out = logging.StreamHandler(sys.stdout)
_stream_out.setFormatter(_FMT)
log.addHandler(_file_out)
log.addHandler(_stream_out)

TP = 0
TF = 0


def SEP(title=''):
    log.info('')
    log.info('=' * 70)
    if title:
        log.info('  ' + title)
    log.info('=' * 70)


def P(name, ok, detail=''):
    global TP, TF
    if ok:
        TP += 1
    else:
        TF += 1
    log.info('  [' + ('PASS' if ok else 'FAIL') + '] ' + name +
             (' -- ' + detail if detail else ''))


def read_src(rel):
    with io.open(ROOT / rel, encoding='utf-8', newline='') as f:
        return f.read()


TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_r4_'))
log.info('Test dir: ' + str(TEST_DIR))

from src.core.config import config, DEFAULT_PRIORITY_ORDER          # noqa: E402
from src.utils.helpers.logging_setup import (                        # noqa: E402
    setup_logging, get_log_file_path, DEFAULTS as LOG_DEFAULTS,
    PROJECT_ROOT as LOG_PROJECT_ROOT,
)
from src.utils.helpers.date_extractor import date_extractor          # noqa: E402
from src.core.file_selector import FileSelector                      # noqa: E402

_cfg_backup = json.loads(json.dumps(config.config))
_settings_bytes = (ROOT / 'config' / 'settings.json').read_bytes()
_settings_mtime = (ROOT / 'config' / 'settings.json').stat().st_mtime_ns


def flush_root():
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def read_log(path):
    flush_root()
    try:
        return io.open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


def silent_pass_sites():
    """Return 'file:line' for every `except Exception:` whose body is just pass."""
    found = []
    for f in sorted((ROOT / 'src').rglob('*.py')):
        lines = io.open(f, encoding='utf-8', errors='replace').read().split('\n')
        for i, line in enumerate(lines):
            if re.match(r'^\s*except Exception[^:]*:\s*$', line):
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].strip() == 'pass':
                    found.append('%s:%d' % (f.relative_to(ROOT).as_posix(), i + 1))
    return found


# =====================================================================
SEP('P2-20  logging section of settings.json is actually applied')
# =====================================================================
sub_dir = TEST_DIR / 'logs' / 'nested'
log_a = sub_dir / 'app.log'
settings_a = {
    'level': 'DEBUG',
    'file': str(log_a),
    'max_size_mb': 2,
    'backup_count': 3,
    'format': '%(levelname)s|%(name)s|%(message)s',
}
res_a = setup_logging(settings_a, force=True)
root = logging.getLogger()
h_a = root.handlers[0] if root.handlers else None

P('setup_logging() reports success', res_a is True)
P('get_log_file_path() returns the configured path',
  get_log_file_path() == log_a, str(get_log_file_path()))
P('exactly one root handler attached (no stacking)', len(root.handlers) == 1,
  str(root.handlers))
P('handler is a RotatingFileHandler',
  h_a is not None and type(h_a).__name__ == 'RotatingFileHandler',
  type(h_a).__name__ if h_a else 'none')
P('max_size_mb honored (2 MB -> bytes)',
  h_a is not None and h_a.maxBytes == 2 * 1024 * 1024, str(getattr(h_a, 'maxBytes', None)))
P('backup_count honored', h_a is not None and h_a.backupCount == 3,
  str(getattr(h_a, 'backupCount', None)))
P('file handler forces utf-8 encoding',
  h_a is not None and (h_a.encoding or '').lower() == 'utf-8', str(getattr(h_a, 'encoding', None)))
P('logging.level honored (DEBUG)', root.level == logging.DEBUG,
  logging.getLevelName(root.level))
P('nested log directory created (mkdir parents=True)', sub_dir.is_dir())
P('logging.format honored',
  h_a is not None and getattr(h_a.formatter, '_fmt', None) == settings_a['format'])
P('third-party loggers are NOT disabled (disable_existing_loggers=False)',
  logging.getLogger('PIL').disabled is False)

# ---------------------------------------------------------------------
SEP('P2-20  the core bug: records now REACH the file')
# =====================================================================
logging.getLogger('imgsniper.probe').warning('probe-warning-ascii')
content_a = read_log(log_a)
P('WARNING is written to the log file (previously never happened)',
  'probe-warning-ascii' in content_a)
P('configured format string is applied to the record',
  'WARNING|imgsniper.probe|probe-warning-ascii' in content_a)

logging.debug('probe-debug-at-debug-level')
P('DEBUG is written when level=DEBUG',
  'probe-debug-at-debug-level' in read_log(log_a))

logging.getLogger('imgsniper.probe').error('رسالة عربية مع emoji 🖼️')
content_a2 = read_log(log_a)
P('Arabic text survives (utf-8 file, cp1256 console safe)',
  'رسالة عربية' in content_a2)
P('emoji survives in the log file', '🖼️' in content_a2)

# ---------------------------------------------------------------------
SEP('P2-20  level filtering at the shipped INFO level')
# =====================================================================
log_b = TEST_DIR / 'info.log'
setup_logging({'level': 'INFO', 'file': str(log_b),
               'format': '%(levelname)s|%(message)s'}, force=True)
logging.debug('must-not-appear-debug')
logging.info('must-appear-info')
logging.warning('must-appear-warning')
content_b = read_log(log_b)
P('DEBUG is filtered out at INFO', 'must-not-appear-debug' not in content_b)
P('INFO is written at INFO', 'must-appear-info' in content_b)
P('WARNING is written at INFO', 'must-appear-warning' in content_b)

# ---------------------------------------------------------------------
SEP('P2-20  robustness: bad settings must never break ImgSniper')
# =====================================================================
log_c = TEST_DIR / 'bogus_level.log'
setup_logging({'level': 'NOT_A_LEVEL', 'file': str(log_c)}, force=True)
P('unknown level name falls back to INFO',
  logging.getLogger().level == logging.INFO,
  logging.getLevelName(logging.getLogger().level))
logging.warning('after-bogus-level')
P('logging still works after the level fallback',
  'after-bogus-level' in read_log(log_c))

log_d = TEST_DIR / 'bogus_format.log'
setup_logging({'level': 'INFO', 'file': str(log_d),
               'format': '%(no_such_key)s'}, force=True)
h_d = logging.getLogger().handlers[0]
P('invalid format string falls back to the default (validated at BOOT)',
  getattr(h_d.formatter, '_fmt', None) == LOG_DEFAULTS['format'],
  str(getattr(h_d.formatter, '_fmt', None)))

# logging validates format strings lazily, so without the boot-time probe a
# typo would print "--- Logging error ---" to stderr on EVERY record.
_saved_stderr = sys.stderr
sys.stderr = io.StringIO()
try:
    logging.raiseExceptions = True
    logging.warning('stderr-probe-after-bogus-format')
    stderr_text = sys.stderr.getvalue()
finally:
    sys.stderr = _saved_stderr
P('no logging-internal error leaked to stderr',
  '--- Logging error ---' not in stderr_text, stderr_text[:120])
P('record still written using the fallback format',
  'stderr-probe-after-bogus-format' in read_log(log_d))

# A path that cannot be created (a FILE sitting where a directory is needed).
blocker = TEST_DIR / 'blocker'
blocker.write_text('i am a file, not a directory')
res_e = setup_logging({'file': str(blocker / 'sub' / 'x.log')}, force=True)
P('unwritable log location returns False instead of raising', res_e is False)
P('get_log_file_path() is None in that fallback', get_log_file_path() is None)
P('NullHandler attached so logging stays cheap and silent',
  type(logging.getLogger().handlers[0]).__name__ == 'NullHandler',
  str(logging.getLogger().handlers))
logging.warning('must-not-raise-under-null-handler')
P('logging calls remain safe under the NullHandler fallback', True)

log_f = TEST_DIR / 'idem.log'
for _ in range(3):
    setup_logging({'file': str(log_f)}, force=True)
P('repeated forced calls never stack handlers',
  len(logging.getLogger().handlers) == 1, str(logging.getLogger().handlers))
_current_handler = logging.getLogger().handlers[0]
setup_logging({'file': str(TEST_DIR / 'should_not_be_used.log')})   # force=False
P('non-forced repeat is a no-op (the first config wins)',
  logging.getLogger().handlers[0] is _current_handler)

# ---------------------------------------------------------------------
SEP('P2-20  previously-silent failure paths now leave a trace')
# =====================================================================
log_g = TEST_DIR / 'silent.log'
setup_logging({'level': 'DEBUG', 'file': str(log_g),
               'format': '%(levelname)s|%(message)s'}, force=True)


class _BrokenExifImage:
    """Stands in for an image whose EXIF accessors both throw."""

    def _getexif(self):
        raise RuntimeError('getexif-boom')

    def getexif(self):
        raise RuntimeError('subifd-boom')


tags = date_extractor._read_exif_tag_values(_BrokenExifImage())
P('_read_exif_tag_values still returns a dict (no exception escapes)',
  isinstance(tags, dict) and tags == {}, repr(tags))
P('EXIF read failure is now logged (was a silent pass)',
  'EXIF unreadable' in read_log(log_g))

sel = FileSelector()
pixels = sel._group_pixel_counts([str(TEST_DIR / 'does_not_exist.jpg')])
P('_group_pixel_counts still tolerates an unreadable file', pixels == [], repr(pixels))
P('pixel-count failure is now logged (was a silent pass)',
  'Pixel count unreadable' in read_log(log_g))

corrupt = TEST_DIR / 'corrupt.jpg'
corrupt.write_bytes(b'this is definitely not a jpeg')
P('extract_date_from_exif returns None on a corrupt file (no crash)',
  date_extractor.extract_date_from_exif(str(corrupt)) is None)

# ---------------------------------------------------------------------
SEP('P2-20  wired to the REAL config/settings.json')
# =====================================================================
main_src = read_src('main.py')
P('main.py imports setup_logging',
  'from src.utils.helpers.logging_setup import setup_logging' in main_src)
P('main.py calls setup_logging() at boot',
  re.search(r'^[ \t]+setup_logging\(\)[ \t]*\r?$', main_src, re.M) is not None)
P('setup_logging() runs BEFORE the CLI is constructed',
  0 <= main_src.find('setup_logging()') < main_src.find('MainCLI()'))

res_real = setup_logging(force=True)          # settings=None -> live config
P('setup_logging() succeeds with the shipped settings.json', res_real is True)
real_path = get_log_file_path()
expected_path = ROOT / str(config.get('logging.file'))
P('logging.file from settings.json is honored', real_path == expected_path,
  str(real_path))
P('log path resolves under the project root', LOG_PROJECT_ROOT == ROOT,
  str(LOG_PROJECT_ROOT))
h_real = logging.getLogger().handlers[0]
P('logging.max_size_mb from settings.json is honored',
  h_real.maxBytes == int(config.get('logging.max_size_mb')) * 1024 * 1024,
  str(h_real.maxBytes))
P('logging.backup_count from settings.json is honored',
  h_real.backupCount == int(config.get('logging.backup_count')),
  str(h_real.backupCount))
P('logging.level from settings.json is honored',
  logging.getLogger().level == logging.getLevelName(
      str(config.get('logging.level')).upper()),
  logging.getLevelName(logging.getLogger().level))
P('logging.format from settings.json is honored',
  getattr(h_real.formatter, '_fmt', None) == config.get('logging.format'))
logging.getLogger('imgsniper.round4').warning('round4-real-config-probe')
P('record lands in the real imgsniper.log',
  'round4-real-config-probe' in read_log(real_path))
P('imgsniper.log is git-ignored (*.log rule present)',
  '*.log' in read_src('.gitignore'))

# ---------------------------------------------------------------------
SEP('P2-20  silent-pass sites: converted vs intentionally kept')
# =====================================================================
silent = silent_pass_sites()
JUSTIFIED = {
    'src/core/processors/image_processor.py',   # __del__ during interpreter shutdown
    'src/utils/helpers/file_utils.py',          # _safe_print last resort (would recurse)
    'src/utils/helpers/logging_setup.py',       # the NullHandler fallback itself
    'src/utils/reports/report_formatter.py',    # i18n fallback = normal control flow
}
P('exactly %d intentionally-silent sites remain' % len(JUSTIFIED),
  len(silent) == len(JUSTIFIED), '; '.join(silent))
P('the remaining ones are only the justified files',
  set(p.split(':')[0] for p in silent) == JUSTIFIED, '; '.join(silent))
for probe in ('src/core/detectors/duplicate_detector.py',
              'src/core/detectors/similarity_group_finder.py',
              'src/core/detectors/similarity_hash_calculator.py',
              'src/core/file_selector.py',
              'src/utils/helpers/date_extractor.py'):
    P('no silent pass left in ' + probe,
      not any(p.startswith(probe + ':') for p in silent))

# ---------------------------------------------------------------------
SEP('P2-21  regression: no bare except: anywhere in src/')
# =====================================================================
bare = []
for f in sorted((ROOT / 'src').rglob('*.py')):
    s = io.open(f, encoding='utf-8', errors='replace').read()
    for m in re.finditer(r'^[ \t]*except[ \t]*:', s, re.M):
        bare.append('%s:%d' % (f.relative_to(ROOT).as_posix(),
                               s[:m.start()].count('\n') + 1))
P('zero bare except: clauses remain in src/', not bare, '; '.join(bare))

# =====================================================================
SEP('P2-7  get_all_images applies filters.* (was completely inert)')
# =====================================================================
from src.utils.helpers.file_utils import get_all_images             # noqa: E402

FORMATS = {'.jpg', '.jpeg', '.png'}
scan_root = TEST_DIR / 'scan'
(scan_root / 'sub').mkdir(parents=True)
(scan_root / '.hiddendir').mkdir()

_filters_backup = json.loads(json.dumps(config.get('filters', {})))


def w(rel, size=4096):
    """get_all_images only stats files, so plain bytes are enough (and fast)."""
    p = scan_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'\x00' * size)
    return p


def names_of(root=None):
    return sorted(Path(p).name for p in get_all_images(str(root or scan_root), FORMATS))


def restore_filters():
    config.config['filters'] = json.loads(json.dumps(_filters_backup))


w('good.jpg')
w('sub/good2.jpg')
w('tiny.jpg', 100)                 # below filters.min_file_size_bytes (1024)
w('photo_backup_1.jpg')            # matches filters.exclude_patterns *_backup*
w('.dotfile.jpg')                  # hidden via the dot-prefix convention
w('.hiddendir/inside.jpg')         # inside a hidden directory
w('notes.txt')                     # unsupported extension

base_names = names_of()
P('plain images are found, including subfolders',
  'good.jpg' in base_names and 'good2.jpg' in base_names, str(base_names))
P('min_file_size_bytes excludes the 100-byte file', 'tiny.jpg' not in base_names)
P('exclude_patterns "*_backup*" is applied', 'photo_backup_1.jpg' not in base_names)
P('dot-prefixed file excluded while include_hidden=false',
  '.dotfile.jpg' not in base_names)
P('file inside a hidden directory excluded while include_hidden=false',
  'inside.jpg' not in base_names)
P('unsupported extension is still ignored', 'notes.txt' not in base_names)

config.config['filters']['include_hidden'] = True
hidden_names = names_of()
P('include_hidden=true admits the dot-prefixed file', '.dotfile.jpg' in hidden_names)
P('include_hidden=true admits files inside a hidden directory',
  'inside.jpg' in hidden_names)
restore_filters()

config.config['filters']['min_file_size_bytes'] = 0
P('min_file_size_bytes=0 disables the size floor', 'tiny.jpg' in names_of())
restore_filters()

w('huge.jpg', 3 * 1024 * 1024)     # 3 MB
config.config['filters']['max_file_size_mb'] = 1
capped = names_of()
P('max_file_size_mb excludes files above the limit', 'huge.jpg' not in capped)
P('max_file_size_mb keeps files below the limit', 'good.jpg' in capped)
config.config['filters']['max_file_size_mb'] = 0
P('max_file_size_mb=0 disables the ceiling', 'huge.jpg' in names_of())
restore_filters()

w('skipme_now.jpg')
w('SKIPME_upper.jpg')
w('keepme.jpg')
config.config['filters']['exclude_patterns'] = ['skipme*.jpg']
custom = names_of()
P('custom exclude_patterns are honored', 'skipme_now.jpg' not in custom)
P('exclude_patterns matching is case-insensitive on every platform',
  'SKIPME_upper.jpg' not in custom)
P('non-matching files survive a custom pattern', 'keepme.jpg' in custom)
P('the shipped *_backup* rule is gone once patterns are replaced',
  'photo_backup_1.jpg' in custom)
restore_filters()

config.config['filters'] = {'exclude_patterns': [], 'include_hidden': True,
                            'include_system': True, 'min_file_size_bytes': 0,
                            'max_file_size_mb': 0}
P('an all-permissive filters section admits everything',
  {'good.jpg', 'tiny.jpg', 'huge.jpg', '.dotfile.jpg', 'inside.jpg',
   'photo_backup_1.jpg'} <= set(names_of()))
restore_filters()

# =====================================================================
SEP('P2-7  ImgSniper output dirs are never rescanned')
# =====================================================================
_paths_backup = json.loads(json.dumps(config.get('paths', {})))

bin_dir = scan_root / 'my-bin'
(bin_dir / 'nested').mkdir(parents=True)
(bin_dir / 'nested' / 'deleted.jpg').write_bytes(b'\x00' * 4096)
rep_dir = scan_root / 'my-reports'
rep_dir.mkdir()
(rep_dir / 'thumb.jpg').write_bytes(b'\x00' * 4096)
# A sibling whose name merely STARTS with the excluded name must survive,
# otherwise the prefix test would silently hide real photos.
sib_dir = scan_root / 'my-reports-old'
sib_dir.mkdir()
(sib_dir / 'legit.jpg').write_bytes(b'\x00' * 4096)

config.config['paths']['recycle_bin'] = str(bin_dir)
config.config['paths']['reports'] = str(rep_dir)
excl_names = names_of()
P('recycle-bin contents are never scanned (deep nesting too)',
  'deleted.jpg' not in excl_names, str(excl_names))
P('reports contents are never scanned', 'thumb.jpg' not in excl_names)
P('a sibling named "<reports>-old" is NOT wrongly excluded',
  'legit.jpg' in excl_names)
w('my-reports.jpg')                # same stem as the excluded dir, but a file
P('a FILE named "<reports>.jpg" is not caught by the dir exclusion',
  'my-reports.jpg' in names_of())
P('normal files are still scanned alongside the exclusions',
  'good.jpg' in excl_names)
config.config['paths'] = json.loads(json.dumps(_paths_backup))
P('exclusions disappear when paths.* is restored',
  'deleted.jpg' in names_of() and 'thumb.jpg' in names_of())

# move_to_recycle_bin() builds its target from Path.cwd(), so a CWD-relative
# name has to resolve correctly too.
cwd_root = TEST_DIR / 'cwdroot'
(cwd_root / 'recycle-bin' / 'deep').mkdir(parents=True)
(cwd_root / 'recycle-bin' / 'deep' / 'old.jpg').write_bytes(b'\x00' * 4096)
(cwd_root / 'live.jpg').write_bytes(b'\x00' * 4096)
_saved_cwd = os.getcwd()
try:
    os.chdir(str(cwd_root))
    config.config['paths']['recycle_bin'] = 'recycle-bin'
    cwd_names = names_of(cwd_root)
finally:
    os.chdir(_saved_cwd)
    config.config['paths'] = json.loads(json.dumps(_paths_backup))
P('CWD-relative recycle-bin is excluded (matches move_to_recycle_bin)',
  'old.jpg' not in cwd_names, str(cwd_names))
P('live file in that same root is still scanned', 'live.jpg' in cwd_names)

# ---------------------------------------------------------------------
SEP('P2-7  Windows hidden / system attributes')
# =====================================================================
if sys.platform == 'win32':
    import ctypes
    ATTR_HIDDEN = 0x2
    ATTR_SYSTEM = 0x4
    ATTR_NORMAL = 0x80

    def set_attrs(path, value):
        ctypes.windll.kernel32.SetFileAttributesW(str(path), value)

    hid_file = w('win_hidden.jpg')
    set_attrs(hid_file, ATTR_HIDDEN)
    P('FILE_ATTRIBUTE_HIDDEN file excluded while include_hidden=false',
      'win_hidden.jpg' not in names_of())
    config.config['filters']['include_hidden'] = True
    P('include_hidden=true admits the FILE_ATTRIBUTE_HIDDEN file',
      'win_hidden.jpg' in names_of())
    restore_filters()

    sys_file = w('win_system.jpg')
    set_attrs(sys_file, ATTR_SYSTEM)
    P('FILE_ATTRIBUTE_SYSTEM file excluded while include_system=false',
      'win_system.jpg' not in names_of())
    config.config['filters']['include_system'] = True
    P('include_system=true admits the FILE_ATTRIBUTE_SYSTEM file',
      'win_system.jpg' in names_of())
    restore_filters()

    # Reset to NORMAL so the temp tree can actually be deleted afterwards.
    set_attrs(hid_file, ATTR_NORMAL)
    set_attrs(sys_file, ATTR_NORMAL)
else:
    P('Windows attribute checks skipped on this platform (POSIX has neither)',
      True)
    P('POSIX hidden convention still works via the dot prefix',
      '.dotfile.jpg' not in names_of())

# ---------------------------------------------------------------------
SEP('P2-7  source-level guarantees and caller regressions')
# =====================================================================
fu_src = read_src('src/utils/helpers/file_utils.py')
P('get_all_images now consults the filters section',
  "config.get('filters'" in fu_src)
P('the old unfiltered one-liner is gone',
  'if file_path.is_file() and file_path.suffix.lower() in supported_formats:'
  not in fu_src)
P('all four paths.* keys participate in the exclusion',
  all(k in fu_src for k in ('paths.recycle_bin', 'paths.reports',
                            'paths.temp', 'paths.cache')))
P('resolution filters are deliberately documented as not applied here',
  'min_resolution / max_resolution are deliberately NOT applied' in fu_src)
for det in ('corruption_detector', 'duplicate_detector', 'similarity_detector'):
    P(det + ' still scans through get_all_images',
      'get_all_images(' in read_src('src/core/detectors/%s.py' % det))
P('image_analyzer still scans through get_all_images',
  'get_all_images(' in read_src('src/core/image_analyzer.py'))

# =====================================================================
SEP('P3-8  inert safety keys removed; recycle-bin IS the recovery path')
# =====================================================================
from src.utils.helpers.file_utils import (                          # noqa: E402
    move_to_recycle_bin, reset_session_folder,
)

settings_json = json.loads(read_src('config/settings.json'))
P('settings.json is still valid JSON after the removal',
  isinstance(settings_json, dict))
safety_section = settings_json.get('safety', {})
P('safety.preserve_originals removed', 'preserve_originals' not in safety_section)
P('safety.create_backup removed', 'create_backup' not in safety_section)
P('the removal is documented inside settings.json itself',
  'P3-8' in str(safety_section.get('_note', ''))
  and 'preserve_originals' in str(safety_section.get('_note', '')))
remaining_safety = sorted(k for k in safety_section if not k.startswith('_'))
P('exactly the three functional safety keys remain',
  remaining_safety == ['confirm_before_delete', 'dry_run_mode',
                       'max_files_per_operation'], str(remaining_safety))

src_blob = '\n'.join(io.open(f, encoding='utf-8', errors='replace').read()
                     for f in sorted((ROOT / 'src').rglob('*.py')))
for key in remaining_safety:
    P('safety.%s is genuinely read by code (not inert)' % key,
      ('safety.%s' % key) in src_blob)
removed_reads = re.findall(
    r"config\.get\(\s*['\"]safety\.(preserve_originals|create_backup)", src_blob)
P('no code READS either removed key via config.get()',
  not removed_reads, str(removed_reads))
_mentioning = [f.name for f in sorted((ROOT / 'src').rglob('*.py'))
               if 'preserve_originals' in
               io.open(f, encoding='utf-8', errors='replace').read()]
P('the only remaining mention is the explanatory docstring in file_utils.py',
  _mentioning == ['file_utils.py'], str(_mentioning))
P('move_to_recycle_bin documents that it IS the recovery mechanism',
  'this function IS the recovery mechanism'
  in read_src('src/utils/helpers/file_utils.py'))

# Functional proof of the claim the removed keys used to make: a "deleted"
# file is never destroyed, it is moved and stays byte-for-byte recoverable.
bin_root = TEST_DIR / 'binroot'
(bin_root / 'photos' / 'nested').mkdir(parents=True)
victim = bin_root / 'photos' / 'nested' / 'dup.jpg'
victim.write_bytes(b'\xAB' * 4096)
_victim_bytes = victim.read_bytes()
_cwd3 = os.getcwd()
_paths3 = json.loads(json.dumps(config.get('paths', {})))
_safety3 = json.loads(json.dumps(config.get('safety', {})))
try:
    os.chdir(str(bin_root))
    config.config['paths']['recycle_bin'] = 'recycle-bin'
    config.config['safety']['dry_run_mode'] = False
    reset_session_folder()
    move_to_recycle_bin(str(victim), subfolder='duplicates')
    recovered = list((bin_root / 'recycle-bin').rglob('dup.jpg'))
finally:
    os.chdir(_cwd3)
    config.config['paths'] = json.loads(json.dumps(_paths3))
    config.config['safety'] = json.loads(json.dumps(_safety3))
    reset_session_folder()
P('the file is gone from its original location', not victim.exists())
P('the file still exists inside the recycle bin (nothing was destroyed)',
  len(recovered) == 1, str(recovered))
P('the moved file is byte-for-byte identical (fully recoverable)',
  bool(recovered) and recovered[0].read_bytes() == _victim_bytes)

# =====================================================================
SEP('P2-22  save_config: no-op guard + line-ending preservation')
# =====================================================================
from src.core.config import Config                                  # noqa: E402


def make_cfg(path, cfg):
    """Config.__init__ takes a project-root-relative string, so build a normal
    instance and then point it at the temp file under test."""
    c = Config()
    c.config_path = Path(path)
    c.config = json.loads(json.dumps(cfg))
    return c


cfg_dir = TEST_DIR / 'cfg'
cfg_dir.mkdir(parents=True, exist_ok=True)

p_same = cfg_dir / 'same.json'
payload_same = json.dumps({'language': 'en', 'priorities': {'order': [1, 2, 3, 4]}},
                          indent=4, ensure_ascii=False)
p_same.write_text(payload_same, encoding='utf-8', newline='\n')
bytes_before = p_same.read_bytes()
mtime_before = p_same.stat().st_mtime_ns
c_same = make_cfg(p_same, {'language': 'en', 'priorities': {'order': [1, 2, 3, 4]}})
c_same.save_config()
P('identical content: bytes untouched', p_same.read_bytes() == bytes_before)
P('identical content: mtime untouched (file was not rewritten at all)',
  p_same.stat().st_mtime_ns == mtime_before)
P('identical content: no .tmp leftover', not (cfg_dir / 'same.json.tmp').exists())

c_same.set('language', 'ar')
P('real change is still persisted',
  json.loads(p_same.read_text(encoding='utf-8'))['language'] == 'ar')
P('real change: no .tmp leftover', not (cfg_dir / 'same.json.tmp').exists())

p_crlf = cfg_dir / 'crlf.json'
crlf_body = json.dumps({'a': 1, 'b': {'c': 2}}, indent=4, ensure_ascii=False)
p_crlf.write_bytes(crlf_body.replace('\n', '\r\n').encode('utf-8'))
make_cfg(p_crlf, json.loads(crlf_body)).set('a', 99)
raw_crlf = p_crlf.read_bytes()
P('CRLF file stays CRLF (no whole-file line-ending flip)',
  b'\r\n' in raw_crlf and b'\n' not in raw_crlf.replace(b'\r\n', b''))
P('CRLF file: value persisted', json.loads(raw_crlf.decode('utf-8'))['a'] == 99)

p_lf = cfg_dir / 'lf.json'
p_lf.write_bytes(json.dumps({'a': 1}, indent=4).encode('utf-8'))
make_cfg(p_lf, {'a': 1}).set('a', 5)
raw_lf = p_lf.read_bytes()
P('LF file stays LF (no CR introduced on Windows)', b'\r' not in raw_lf)
P('LF file: value persisted', json.loads(raw_lf.decode('utf-8'))['a'] == 5)

p_new = cfg_dir / 'brand_new.json'
c_new = make_cfg(p_new, {'x': 1})
c_new.save_config()
P('missing file is still created fresh',
  p_new.exists() and json.loads(p_new.read_text(encoding='utf-8'))['x'] == 1)

p_ar = cfg_dir / 'arabic.json'
c_ar = make_cfg(p_ar, {'_comment': 'ملف الإعدادات', 'emoji': '🖼️'})
c_ar.save_config()
P('Arabic + emoji round-trip through save_config (ensure_ascii=False)',
  json.loads(p_ar.read_text(encoding='utf-8'))['_comment'] == 'ملف الإعدادات'
  and json.loads(p_ar.read_text(encoding='utf-8'))['emoji'] == '🖼️')

settings_path = ROOT / 'config' / 'settings.json'
P('this suite left config/settings.json bytes untouched',
  settings_path.read_bytes() == _settings_bytes)
P('this suite left config/settings.json mtime untouched',
  settings_path.stat().st_mtime_ns == _settings_mtime)

# =====================================================================
# Teardown: the RotatingFileHandler holds its file open, and Windows refuses
# to delete a tree containing open handles, so close every root handler first.
# =====================================================================
for _h in list(logging.getLogger().handlers):
    try:
        _h.close()
    except Exception:
        pass
    logging.getLogger().removeHandler(_h)
shutil.rmtree(TEST_DIR, ignore_errors=True)

config.config = json.loads(json.dumps(_cfg_backup))

SEP('ROUND 4 SUMMARY')
log.info('  passed: %d' % TP)
log.info('  failed: %d' % TF)
log.info('  total : %d' % (TP + TF))
log.info('')
log.info('  RESULT: ' + ('FAIL' if TF else 'ALL PASS'))
sys.exit(1 if TF else 0)





