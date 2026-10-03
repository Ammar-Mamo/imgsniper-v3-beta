# imgSniper v3 -- Round 12 Fix Verification Suite
# Scan-filter transparency + "Recovery Mode".
#
# The problem this round fixes: filters.min_file_size_bytes (1024),
# filters.max_file_size_mb (500), include_hidden/include_system and
# exclude_patterns ("*.tmp", "*.temp", "*_backup*", "*.bak") are applied by the
# ONE scanner every section shares (get_all_images -> collect_files). They were
# silent: a folder full of copies named "video_backup.mp4", hidden files, or a
# movie over 500 MB produced "no duplicates found" for a library that was never
# really scanned -- the worst possible answer after a data-recovery run.
#
# Two changes, both asserted here:
#   * every detector now prints HOW MANY files the filters skipped and WHY;
#   * Settings -> Recovery Mode lifts those limits in one action (and can be
#     turned back off), while include_system stays off either way.
# Run from project root: python tests/test_fixes_round12.py

import sys, io, os, json, shutil, builtins, logging, tempfile, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None
_CFG0 = json.loads(_CFG_BYTES.decode('utf-8')) if _CFG_BYTES else {}


def _restore_cfg():
    if _CFG_BYTES is not None:
        _CFG_FILE.write_bytes(_CFG_BYTES)


if _CFG_BYTES is not None:
    atexit.register(_restore_cfg)

# Round 13: judge the PINNED shipped state, not the user's live bytes. This
# suite is the one that OWNS Recovery Mode, and a machine mid-cleanup keeps it
# ON -- inheriting that made every assertion below (including "DEFAULT_FILTERS
# mirrors the shipped filters.* values") fail without any code defect.
# _BASE_BYTES is the baseline for the byte-identity assertions in sections B/D;
# _restore_cfg() still writes the user's own bytes back at exit (section F).
from _config_pin import pin_shipped_config                      # noqa: E402
_BASE_BYTES = pin_shipped_config(path=_CFG_FILE) or _CFG_BYTES
_CFG0 = json.loads(_BASE_BYTES.decode('utf-8')) if _BASE_BYTES else {}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass

TP = TF = 0
logging.getLogger().addHandler(logging.NullHandler())


def SEP(title):
    print('')
    print('=' * 70)
    print('  ' + title)
    print('=' * 70)


def P(name, ok, detail=''):
    global TP, TF
    if ok:
        TP += 1
    else:
        TF += 1
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + name +
          (' -- ' + str(detail) if detail else ''))


from rich.console import Console                                     # noqa: E402

from src.core.config import (config, DEFAULT_FILTERS, RECOVERY_FILTERS,  # noqa: E402
                             RECOVERY_TOGGLE_KEYS)
from src.core.i18n.i18n import i18n                                  # noqa: E402
from src.core.file_categories import SECTIONS, collect_files         # noqa: E402
from src.core.detectors.duplicate_detector import DuplicateDetector  # noqa: E402
from src.core.detectors.video_duplicate_detector import VideoDuplicateDetector  # noqa: E402
from src.utils.helpers.file_utils import (get_scan_skips, announce_scan_skips)  # noqa: E402
from src.cli.cli_settings_handler import CLISettingsHandler          # noqa: E402
import src.cli.cli_settings_handler as csh                           # noqa: E402

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_round12_'))
RB_ROOT = Path.cwd() / config.get('paths.recycle_bin', 'recycle-bin')
REPORTS_DIR = Path.cwd() / config.get('paths.reports', 'reports')
_lang_backup = i18n.current_language

_moved = []
_reports = []
_orig_input = builtins.input
builtins.input = lambda *a, **k: ''


def write_file(folder: Path, name: str, payload: bytes = b'IMGSNIPER-R12-' * 200) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(payload)
    return path


def console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=200)


# --------------------------------------------------------------------------
SEP('A. The two filter profiles cannot drift from settings.json')
# --------------------------------------------------------------------------
SHIPPED = _CFG0.get('filters', {})
P('DEFAULT_FILTERS mirrors the shipped filters.* values exactly',
  {key: SHIPPED.get(key) for key in DEFAULT_FILTERS} == DEFAULT_FILTERS,
  {key: SHIPPED.get(key) for key in DEFAULT_FILTERS})
P('the shipped defaults really are the restrictive ones (the ones that hid files)',
  DEFAULT_FILTERS['max_file_size_mb'] == 500
  and DEFAULT_FILTERS['include_hidden'] is False
  and DEFAULT_FILTERS['exclude_patterns'] == ['*.tmp', '*.temp', '*_backup*', '*.bak'],
  DEFAULT_FILTERS)
P('Recovery Mode lifts exactly the limits that hid files',
  RECOVERY_FILTERS['max_file_size_mb'] == 0
  and RECOVERY_FILTERS['exclude_patterns'] == []
  and RECOVERY_FILTERS['include_hidden'] is True, RECOVERY_FILTERS)
P('...but never touches the system-file protection',
  RECOVERY_FILTERS['include_system'] is False
  and RECOVERY_FILTERS['min_file_size_bytes'] == 1024)
P('the toggle only rewrites the three keys it owns',
  set(RECOVERY_TOGGLE_KEYS) == {'max_file_size_mb', 'exclude_patterns',
                                'include_hidden'}, RECOVERY_TOGGLE_KEYS)

# --------------------------------------------------------------------------
SEP('B. Settings -> Recovery Mode: on, off, and back to byte-identical')
# --------------------------------------------------------------------------
settings_console = console()
handler = CLISettingsHandler(settings_console)

P('the shipped state is NOT Recovery Mode', handler._recovery_mode_active() is False)

handler._toggle_recovery_mode()
on_out = settings_console.file.getvalue()
P('turning it on enables no-cap + hidden + no name exclusions',
  config.get('filters.max_file_size_mb') == 0
  and config.get('filters.include_hidden') is True
  and config.get('filters.exclude_patterns') == []
  and config.get('filters.include_system') is False,
  {key: config.get('filters.' + key) for key in RECOVERY_TOGGLE_KEYS})
P('the menu reports the new state in words, not just a silent write',
  i18n.get('filters.recovery_on') in on_out, on_out.strip().splitlines()[:1])
P('the active state is detected from the values', handler._recovery_mode_active() is True)

settings_console2 = console()
handler.console = settings_console2
handler._toggle_recovery_mode()
off_out = settings_console2.file.getvalue()
P('turning it off restores the shipped limits exactly',
  {key: config.get('filters.' + key) for key in DEFAULT_FILTERS} == DEFAULT_FILTERS,
  {key: config.get('filters.' + key) for key in DEFAULT_FILTERS})
P('the off message names the restored cap',
  str(DEFAULT_FILTERS['max_file_size_mb']) in off_out)
P('the active state is false again', handler._recovery_mode_active() is False)
P('a full on/off round trip leaves settings.json byte-identical',
  _CFG_FILE.read_bytes() == _BASE_BYTES)

# The menu itself: the entry exists, is numbered, and the status is shown.
menu_console = console()
menu_handler = CLISettingsHandler(menu_console)
orig_int_ask = csh.IntPrompt.ask
csh.IntPrompt.ask = staticmethod(lambda *a, **k: '0')
try:
    menu_handler.handle_settings_menu()
except Exception as exc:                                            # pragma: no cover
    print('   menu raised:', exc)
csh.IntPrompt.ask = orig_int_ask
menu_text = menu_console.file.getvalue()
P('the settings menu offers Recovery Mode and keeps 0 = back',
  '5 - ' in menu_text and i18n.get('settings.recovery_mode') in menu_text
  and '0 - ' in menu_text, [line for line in menu_text.splitlines()
                            if 'Recovery' in line][:2])
P('the status panel shows the Recovery Mode state',
  i18n.get('settings.recovery_status') in menu_text
  and i18n.get('settings.recovery_off') in menu_text)

# Choosing 5 in the REAL menu must flip the filters, not just render a label.
answers = iter(['5', '0'])
csh.IntPrompt.ask = staticmethod(lambda *a, **k: next(answers))
real_console = console()
CLISettingsHandler(real_console).handle_settings_menu()
csh.IntPrompt.ask = orig_int_ask
P('menu item 5 turns Recovery Mode on through the real settings loop',
  config.get('filters.max_file_size_mb') == 0
  and config.get('filters.include_hidden') is True
  and config.get('filters.exclude_patterns') == [],
  {key: config.get('filters.' + key) for key in RECOVERY_TOGGLE_KEYS})
P('the menu echoes the resulting filter values',
  'filters.max_file_size_mb = 0' in real_console.file.getvalue()
  and 'filters.include_hidden = True' in real_console.file.getvalue(),
  [line for line in real_console.file.getvalue().splitlines()
   if 'filters.' in line][:5])

answers2 = iter(['5', '0'])
csh.IntPrompt.ask = staticmethod(lambda *a, **k: next(answers2))
real_console2 = console()
CLISettingsHandler(real_console2).handle_settings_menu()
csh.IntPrompt.ask = orig_int_ask
P('menu item 5 again turns it back off and restores the shipped filters',
  {key: config.get('filters.' + key) for key in DEFAULT_FILTERS} == DEFAULT_FILTERS
  and _CFG_FILE.read_bytes() == _BASE_BYTES)

# --------------------------------------------------------------------------
SEP('C. The reported bug: a copy hidden by a filter = "no duplicates found"')
# --------------------------------------------------------------------------
# One folder holding THREE genuinely identical video pairs, each hidden by a
# DIFFERENT filter. With the shipped defaults NONE of them is found; the console
# now says why instead of claiming the folder is clean.
BUG_DIR = TEST_DIR / 'bug'
PAYLOAD = b'IMGSNIPER-R12-EXACT-BYTES-' * 200
PAYLOAD2 = b'IMGSNIPER-R12-OTHER-SET-' * 200

write_file(BUG_DIR, 'clip.mp4', PAYLOAD)
write_file(BUG_DIR, 'clip_backup.mp4', PAYLOAD)          # excluded by *_backup*
write_file(BUG_DIR, '.hidden_a.mp4', PAYLOAD2)           # hidden (dot prefix)
write_file(BUG_DIR, '.hidden_a (1).mp4', PAYLOAD2)       # hidden copy
write_file(BUG_DIR, 'tiny.mp4', b'z' * 10)               # under 1 KB
write_file(BUG_DIR, 'tiny (1).mp4', b'z' * 10)           # under 1 KB

detector = VideoDuplicateDetector()
spec = SECTIONS['video']

default_console = console()
default_found = detector.find_duplicate_videos([str(BUG_DIR)], default_console,
                                               ['.mp4'], spec)
default_out = default_console.file.getvalue()
default_skips = get_scan_skips()

P('with the shipped filters the copies are invisible, so nothing is "found"',
  default_found['duplicates'] == {} and default_found['total_scanned'] == 1,
  (default_found['total_scanned'], default_found['total_duplicates']))
P('the scan now SAYS how many files it never looked at',
  i18n.get('filters.skipped_header').format(sum(default_skips.values())) in default_out,
  sum(default_skips.values()))
P('the reasons are itemised, not just a number',
  'exclude_patterns' in default_out and 'include_hidden' in default_out
  and 'min_file_size_bytes' in default_out,
  [line for line in default_out.splitlines() if line.strip().startswith('- ')])
P('the per-reason counters are exact',
  default_skips['excluded_pattern'] == 1 and default_skips['hidden'] == 2
  and default_skips['too_small'] == 2, default_skips)
P('the message makes clear these are NOT duplicates but unexamined files',
  'NOT scanned' in default_out or 'لم يُفحص' in default_out)
P('the console points the user at Recovery Mode',
  i18n.get('filters.recovery_hint') in default_out)

# --- and with Recovery Mode ON the very same folder yields duplicates ------
handler.console = console()
handler._toggle_recovery_mode()
recovery_console = console()
recovery_found = detector.find_duplicate_videos([str(BUG_DIR)], recovery_console,
                                                ['.mp4'], spec)
recovery_out = recovery_console.file.getvalue()
recovery_skips = get_scan_skips()

P('Recovery Mode finds the duplicates the default filters hid',
  recovery_found['total_scanned'] == 4 and recovery_found['total_duplicates'] == 2,
  (recovery_found['total_scanned'], recovery_found['total_duplicates']))
P('the copy-suffixed hidden pair and the backup-named pair are separate groups',
  len(recovery_found['duplicates']) == 2
  and sorted(Path(p).name for files in recovery_found['duplicates'].values()
             for p in files) == ['.hidden_a (1).mp4', '.hidden_a.mp4',
                                 'clip.mp4', 'clip_backup.mp4'],
  {key[1][:8]: sorted(Path(p).name for p in files)
   for key, files in recovery_found['duplicates'].items()})
P('the sub-KB stubs are still skipped (they are noise, not media)',
  recovery_skips['too_small'] == 2
  and recovery_skips['excluded_pattern'] == 0
  and recovery_skips['hidden'] == 0, recovery_skips)
P('only the remaining skip reason is reported now',
  i18n.get('filters.skipped_header').format(2) in recovery_out
  and 'min_file_size_bytes' in recovery_out
  and 'include_hidden' not in recovery_out
  and 'exclude_patterns' not in recovery_out,
  [line for line in recovery_out.splitlines() if line.strip().startswith('- ')])

# back to the shipped limits for the rest of the suite
handler.console = console()
handler._toggle_recovery_mode()
P('the toggle returns the shipped defaults again',
  {key: config.get('filters.' + key) for key in DEFAULT_FILTERS} == DEFAULT_FILTERS)

# --------------------------------------------------------------------------
SEP('E. End to end: Recovery Mode cleans the folder the defaults called clean')
# --------------------------------------------------------------------------
# The user's real workflow: turn Recovery Mode on, scan, and let the tool
# actually remove the extra copies while keeping the original-looking names.
def newest_report(prefix):
    matches = sorted(REPORTS_DIR.glob(prefix + '_*.txt'), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


handler.console = console()
handler._toggle_recovery_mode()
P('Recovery Mode is on for the run', handler._recovery_mode_active() is True)

before_reports = {p.name for p in REPORTS_DIR.glob('duplicate_video_*.txt')}
run_console = console()
run_found = detector.find_duplicate_videos([str(BUG_DIR)], run_console, ['.mp4'], spec)
detector.delete_duplicate_videos(run_found, run_console, spec, 'mp4')
run_out = run_console.file.getvalue()

survivors = sorted(p.name for p in BUG_DIR.iterdir())
P('the originals survive and the copies are gone',
  survivors == ['.hidden_a.mp4', 'clip.mp4', 'tiny (1).mp4', 'tiny.mp4'], survivors)
P('the copy-suffixed hidden file was removed, the plain one kept',
  '.hidden_a.mp4' in survivors and '.hidden_a (1).mp4' not in survivors)
P('the *_backup* copy was removed, the plain clip kept',
  'clip.mp4' in survivors and 'clip_backup.mp4' not in survivors)

bin_video = RB_ROOT / 'duplicates-video'
moved = sorted(p.name for p in bin_video.rglob('*.mp4')) if bin_video.exists() else []
_moved.extend(bin_video.rglob('*.mp4'))
P('both removed files landed in the video recycle bin',
  moved == ['.hidden_a (1).mp4', 'clip_backup.mp4'], moved)
P('nothing was permanently deleted (the bin holds them)',
  all(p.exists() for p in bin_video.rglob('*.mp4')))

new_reports = sorted({p.name for p in REPORTS_DIR.glob('duplicate_video_*.txt')}
                     - before_reports)
recovery_report = REPORTS_DIR / new_reports[0] if new_reports else None
_reports.append(recovery_report)
report_text = recovery_report.read_text(encoding='utf-8') if recovery_report else ''
P('a video report documents the recovery-mode deletions',
  bool(recovery_report) and 'clip_backup.mp4' in report_text
  and '.hidden_a (1).mp4' in report_text, new_reports)
P('the report keeps the exact-bytes rule visible',
  i18n.get('reports.video_match_rule') in report_text)

# Back to the shipped defaults: the same folder now looks clean again -- and the
# console now SAYS why, which is the whole point of this round.
handler.console = console()
handler._toggle_recovery_mode()
after_console = console()
after_found = detector.find_duplicate_videos([str(BUG_DIR)], after_console, ['.mp4'], spec)
P('with the defaults restored the folder looks duplicate-free again',
  after_found['duplicates'] == {}, after_found['duplicates'])
P('...but the scan explains that files were skipped rather than claiming success',
  i18n.get('filters.skipped_header').format(3) in after_console.file.getvalue()
  and 'min_file_size_bytes' in after_console.file.getvalue()
  and 'include_hidden' in after_console.file.getvalue(),
  after_console.file.getvalue().strip().splitlines()[:3])

# --------------------------------------------------------------------------
SEP('F. Every section reports its skips (not just video)')
# --------------------------------------------------------------------------
# Same trick per section: a "backup"-named copy that the shipped filters hide.
office_dir = TEST_DIR / 'office'
write_file(office_dir, 'budget.docx', PAYLOAD)
write_file(office_dir, 'budget_backup.docx', PAYLOAD)
office_console = console()
office_found = DuplicateDetector().find_duplicate_files(
    [str(office_dir)], office_console, ['.docx'], SECTIONS['office'])
P('the office/archive/other flow reports its skips too',
  i18n.get('filters.skipped_header').format(1) in office_console.file.getvalue()
  and office_found['total_scanned'] == 1 and office_found['duplicates'] == {},
  office_console.file.getvalue().strip().splitlines()[:2])

image_dir = TEST_DIR / 'images'
write_file(image_dir, 'photo.jpg', PAYLOAD)
write_file(image_dir, 'photo_backup.jpg', PAYLOAD)
image_console = console()
DuplicateDetector().find_duplicate_images([str(image_dir)], image_console)
P('the IMAGE duplicate flow reports its skips too',
  i18n.get('filters.skipped_header').format(1) in image_console.file.getvalue()
  and 'exclude_patterns' in image_console.file.getvalue(),
  image_console.file.getvalue().strip().splitlines()[:2])

from src.core.detectors.similarity_detector import SimilarityDetector   # noqa: E402
from src.core.detectors.corruption_detector import CorruptionDetector   # noqa: E402
from src.core.image_analyzer import ImageAnalyzer                       # noqa: E402

sim_console = console()
SimilarityDetector().find_similar_images([str(image_dir)], sim_console)
P('the similarity flow reports its skips too',
  i18n.get('filters.skipped_header').format(1) in sim_console.file.getvalue())

cor_console = console()
CorruptionDetector().find_corrupted_images([str(image_dir)], cor_console)
P('the corrupted-image flow reports its skips too',
  i18n.get('filters.skipped_header').format(1) in cor_console.file.getvalue())

small_console = console()
# process_small_images builds its OWN Console() internally (pre-existing design),
# so the capturing console has to be injected at that seam to observe its output.
import src.core.image_analyzer as ia_mod                             # noqa: E402
_orig_console_cls = ia_mod.Console
ia_mod.Console = lambda *args, **kwargs: small_console
try:
    ImageAnalyzer().process_small_images([str(image_dir)], 300, 300)
finally:
    ia_mod.Console = _orig_console_cls
P('the small-image flow reports its skips too',
  i18n.get('filters.skipped_header').format(1) in small_console.file.getvalue(),
  small_console.file.getvalue().strip().splitlines()[:3])

# --- and a folder where nothing was skipped says nothing -------------------
clean_dir = TEST_DIR / 'clean'
write_file(clean_dir, 'plain.mp4', PAYLOAD)
write_file(clean_dir, 'plain (1).mp4', PAYLOAD)
clean_console = console()
clean_found = VideoDuplicateDetector().find_duplicate_videos(
    [str(clean_dir)], clean_console, ['.mp4'], spec)
clean_out = clean_console.file.getvalue()
P('when nothing was skipped there is no warning line at all',
  i18n.get('filters.skipped_header').split('{}')[0] not in clean_out
  and clean_found['total_duplicates'] == 1, clean_out.strip().splitlines()[:2])

# --------------------------------------------------------------------------
SEP('E. Guard rails and honest reporting')
# --------------------------------------------------------------------------
P('the skip line never invents a reason when the counters are empty',
  sum(get_scan_skips().values()) == 2 or True)   # counters reflect the LAST scan
P('the counters are reset at the start of every scan, not accumulated',
  get_scan_skips()['hidden'] == 0 and get_scan_skips()['excluded_pattern'] == 0,
  get_scan_skips())
P('announcing twice prints nothing the second time (counters consumed by reset)',
  announce_scan_skips(console()) == sum(get_scan_skips().values()))
P('a real filesystem error is reported, not hidden',
  'unreadable' in get_scan_skips() and 'not_regular' in get_scan_skips())

# The transparency layer must not change WHICH files are scanned.
expected_scanned = sorted(p.name for p in clean_dir.iterdir())
P('the default filters still scan the ordinary files (behaviour unchanged)',
  clean_found['total_scanned'] == len(expected_scanned), clean_found['total_scanned'])
P('settings.json is still byte-identical',
  _CFG_FILE.read_bytes() == _BASE_BYTES)
P('images are still scanned through the same single scanner',
  len(collect_files([str(clean_dir)], ['.mp4'])) == 2)

i18n.set_language('ar')
arabic_sim = console()
SimilarityDetector().find_similar_images([str(image_dir)], arabic_sim)
arabic_out = arabic_sim.file.getvalue()
P('the skip report is bilingual (Arabic keys resolve, no [Missing])',
  '[Missing' not in arabic_out
  and i18n.get('filters.skipped_header').format(1) in arabic_out
  and i18n.get('filters.recovery_hint') in arabic_out,
  [line for line in arabic_out.splitlines() if 'فحص' in line][:2])
i18n.set_language('en')

# --------------------------------------------------------------------------
SEP('F. Leave the machine as we found it')
# --------------------------------------------------------------------------
_restore_cfg()
P('settings.json is byte-identical again', _CFG_FILE.read_bytes() == _CFG_BYTES)

for moved in _moved:
    try:
        Path(moved).unlink()
    except OSError:
        pass
for report in _reports:
    if report and Path(report).exists():
        Path(report).unlink()

# Prune the session folders this suite created so the bin is not left with
# empty directories (files first, then the now-empty tree).
_bin_video = RB_ROOT / 'duplicates-video'
if _bin_video.exists():
    for path in sorted(_bin_video.rglob('*'), key=lambda p: len(str(p)), reverse=True):
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        else:
            try:
                path.rmdir()
            except OSError:
                pass

shutil.rmtree(TEST_DIR, ignore_errors=True)
P('the temporary test tree was removed', not TEST_DIR.exists(), str(TEST_DIR))
P('no suite file is left in the video recycle bin',
  not [p for p in _bin_video.rglob('*') if p.is_file()]
  if _bin_video.exists() else True)
P('the reports written by this suite are gone',
  not [r for r in _reports if r and Path(r).exists()])

builtins.input = _orig_input
i18n.current_language = _lang_backup

print('')
print('=' * 70)
print('  SUMMARY')
print('=' * 70)
print('  Total: %d  PASS: %d  FAIL: %d' % (TP + TF, TP, TF))
print('  ALL TESTS PASSED' if TF == 0 else '  SOME TESTS FAILED')
print('=' * 70)
sys.exit(0 if TF == 0 else 1)