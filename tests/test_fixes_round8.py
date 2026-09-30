# imgSniper v3 -- Round 8 Fix Verification Suite
# Deterministic tie-break + simple reasons + full paths + calm dry-run + settings on the main menu.
#   * selection ties: a full-score tie is broken ALPHABETICALLY (case-insensitive
#     filename), so the same folder keeps the same winner on every run; the
#     old "first in scan order" rule picked a different file between runs.
#   * reasons: the verbose "kept file has a higher weighted score (+4.4 pts;
#     main advantage: ...)" sentences were replaced by the plain deciding fact
#     ("filename importance (6/9 vs 2/9)" / "(kept: 6/9 -- this file: 2/9)").
#   * reports: every group shows the FULL original path, and outside dry-run
#     each deleted file also shows the recycle-bin path it was moved to.
#   * dry-run: the per-file "would move" lines go to imgsniper.log only; the
#     console keeps one banner + one summary line (they used to flood the UI).
#   * settings: moved from the image menu to the MAIN menu (option 6) and
#     safety toggles (dry-run / confirm / max files) are now reachable.
# Run from project root: python tests/test_fixes_round8.py

import sys, io, os, json, shutil, builtins, logging, itertools, inspect, contextlib, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Round 8 inherits the round-7 guard: config.set() saves to disk immediately,
# so the original settings.json bytes are restored both after the mutating
# sections and at interpreter exit.
_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None


def _restore_cfg():
    if _CFG_BYTES is not None:
        _CFG_FILE.write_bytes(_CFG_BYTES)


if _CFG_BYTES is not None:
    atexit.register(_restore_cfg)

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


from PIL import Image                                                # noqa: E402

from src.core.config import config, DEFAULT_PRIORITY_ORDER           # noqa: E402
from src.core.file_selector import FileSelector                      # noqa: E402
from src.core.i18n.i18n import i18n                                  # noqa: E402
from src.core.i18n.translations_english import ENGLISH_TRANSLATIONS  # noqa: E402
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS    # noqa: E402
from src.utils.helpers import file_utils as fu                       # noqa: E402
from src.utils.reports.report_formatter import ReportFormatter       # noqa: E402
from src.utils.reports.duplicate_report_generator import (           # noqa: E402
    DuplicateReportGenerator)
from src.utils.reports.small_images_report_generator import (        # noqa: E402
    SmallImagesReportGenerator)
from src.utils.reports.corrupted_report_generator import (           # noqa: E402
    CorruptedReportGenerator)
from src.utils.reports.report_generator import ReportGenerator       # noqa: E402
import src.cli.cli_settings_handler as csh                           # noqa: E402

MB = 1024 * 1024
TEST_DIR = Path(__import__('tempfile').mkdtemp(prefix='imgsniper_round8_'))

# Original safety/paths values (settings.json bytes are the source of truth).
_CFG0 = json.loads(_CFG_BYTES.decode('utf-8')) if _CFG_BYTES else {}
DR0 = _CFG0.get('safety', {}).get('dry_run_mode', False)
MAXF0 = _CFG0.get('safety', {}).get('max_files_per_operation', 0)
RBIN0 = _CFG0.get('paths', {}).get('recycle_bin', 'recycle-bin')
_lang_backup = i18n.current_language


def make_info(name, importance, size_mb=1.0, width=1000, height=1000,
              date='Unknown', source='none'):
    """Same shape the extractors feed the formatters."""
    return {
        'name': name,
        'size_mb': size_mb,
        'size_bytes': int(round(size_mb * MB)),
        'resolution': width * height,
        'width': width,
        'height': height,
        'extracted_date': date,
        'date_source': source,
        'filename_importance': importance,
        'modified_time': '2024-01-01 10:00:00',
    }



# --------------------------------------------------------------------------
SEP('A. Simple, direct reason wording (EN + AR)')
# --------------------------------------------------------------------------
rf = ReportFormatter()

infos_file = {
    'kept.jpg': make_info('kept.jpg', 6),
    'del.jpg': make_info('del.jpg', 2),
}
sel_line = rf.get_detailed_selection_reason(
    'kept.jpg', ['kept.jpg', 'del.jpg'], infos_file).splitlines()[0]
P('selection reason = criterion + compared values',
  sel_line == 'filename importance (6/9 vs 2/9)', sel_line)
del_line = rf.get_deletion_reason(
    'del.jpg', 'kept.jpg', infos_file).splitlines()[0]
P('deletion reason = criterion + kept vs this file',
  del_line == 'filename importance (kept: 6/9 — this file: 2/9)', del_line)

infos_tie = {
    'zzz.jpg': make_info('zzz.jpg', 6),
    'aaa.jpg': make_info('aaa.jpg', 6),
}
tie_line = rf.get_deletion_reason(
    'zzz.jpg', 'aaa.jpg', infos_tie).splitlines()[0]
P('full tie with different names -> alphabetical rule named',
  tie_line == 'Tie in weighted criteria — kept the alphabetically first filename',
  tie_line)

infos_same = {
    'x/same.jpg': make_info('same.jpg', 6),
    'y/same.jpg': make_info('same.jpg', 6),
}
same_line = rf.get_deletion_reason(
    'x/same.jpg', 'y/same.jpg', infos_same).splitlines()[0]
P('full tie with identical names -> identical-criteria label',
  same_line == 'Tie — identical criteria and filename', same_line)

sel_tie = rf.get_detailed_selection_reason(
    'aaa.jpg', ['aaa.jpg', 'zzz.jpg'], infos_tie).splitlines()[0]
P('selection reason uses the same tie wording',
  sel_tie == 'Tie in weighted criteria — kept the alphabetically first filename',
  sel_tie)

i18n.set_language('ar')
ar_del = rf.get_deletion_reason('del.jpg', 'kept.jpg', infos_file).splitlines()[0]
P('AR deletion reason uses (المُبقى / هذا الملف)',
  'المُبقى' in ar_del and 'هذا الملف' in ar_del, ar_del)
ar_sel = rf.get_detailed_selection_reason(
    'kept.jpg', ['kept.jpg', 'del.jpg'], infos_file).splitlines()[0]
P('AR selection reason = criterion مقابل values',
  'مقابل' in ar_sel and '6/9' in ar_sel, ar_sel)
ar_tie = rf.get_deletion_reason('zzz.jpg', 'aaa.jpg', infos_tie).splitlines()[0]
P('AR tie label names the alphabetical rule',
  'تعادل' in ar_tie and 'الأسبق' in ar_tie, ar_tie)
ar_same = rf.get_deletion_reason(
    'x/same.jpg', 'y/same.jpg', infos_same).splitlines()[0]
P('AR identical-names tie label',
  ar_same.startswith('تعادل') and 'تطابقت' in ar_same, ar_same)
i18n.set_language('en')



# --------------------------------------------------------------------------
SEP('B. Deterministic alphabetical tie-break (real images, real FileSelector)')
# --------------------------------------------------------------------------
i18n.set_language('en')

src_img = TEST_DIR / '_base.jpg'
Image.new('RGB', (60, 40), (10, 20, 30)).save(str(src_img))
STAMP = 1700000000
os.utime(str(src_img), (STAMP, STAMP))

tie_dir = TEST_DIR / 'tie'
tie_dir.mkdir(parents=True, exist_ok=True)
tie_names = ['img_b.jpg', 'img_a.jpg', 'img_c.jpg']
for _n in tie_names:
    shutil.copy(str(src_img), str(tie_dir / _n))
    os.utime(str(tie_dir / _n), (STAMP, STAMP))
tie_paths = [str(tie_dir / n) for n in tie_names]

sel = FileSelector()
winners = {Path(sel.select_best_file(list(order))).name
           for order in itertools.permutations(tie_paths)}
alpha_first = min(tie_names, key=lambda n: n.lower())
P('3 identical files, all 6 scan orders -> one single winner',
  len(winners) == 1, sorted(winners))
P('the winner is the alphabetically first filename',
  winners == {alpha_first}, f'{sorted(winners)} vs {alpha_first}')

case_dir = TEST_DIR / 'case'
case_dir.mkdir(parents=True, exist_ok=True)
for _n in ('B_upper.jpg', 'a_lower.jpg'):
    shutil.copy(str(src_img), str(case_dir / _n))
    os.utime(str(case_dir / _n), (STAMP, STAMP))
w_case1 = Path(sel.select_best_file([str(case_dir / 'B_upper.jpg'),
                                     str(case_dir / 'a_lower.jpg')])).name
w_case2 = Path(sel.select_best_file([str(case_dir / 'a_lower.jpg'),
                                     str(case_dir / 'B_upper.jpg')])).name
P('case-insensitive: a_lower.jpg beats B_upper.jpg in both scan orders',
  w_case1 == 'a_lower.jpg' and w_case2 == 'a_lower.jpg', f'{w_case1} / {w_case2}')

n1 = TEST_DIR / 'ns1'
n2 = TEST_DIR / 'ns2'
n1.mkdir(parents=True, exist_ok=True)
n2.mkdir(parents=True, exist_ok=True)
for _d in (n1, n2):
    shutil.copy(str(src_img), str(_d / 'same.jpg'))
    os.utime(str(_d / 'same.jpg'), (STAMP, STAMP))
k_same1 = sel.select_best_file([str(n1 / 'same.jpg'), str(n2 / 'same.jpg')])
k_same2 = sel.select_best_file([str(n2 / 'same.jpg'), str(n1 / 'same.jpg')])
P('identical names = interchangeable files (first in scan order kept)',
  k_same1 == str(n1 / 'same.jpg') and k_same2 == str(n2 / 'same.jpg'),
  f'{k_same1} / {k_same2}')


# --------------------------------------------------------------------------
SEP('C. A real quality gap still beats the alphabetical rule')
# --------------------------------------------------------------------------
qual_dir = TEST_DIR / 'quality'
qual_dir.mkdir(parents=True, exist_ok=True)
big = qual_dir / 'img_z.jpg'
small = qual_dir / 'img_a.jpg'
Image.new('RGB', (200, 200), (30, 60, 90)).save(str(big))
Image.new('RGB', (40, 40), (30, 60, 90)).save(str(small))
os.utime(str(big), (STAMP, STAMP))
os.utime(str(small), (STAMP, STAMP))
kw = Path(sel.select_best_file([str(small), str(big)])).name
kw_rev = Path(sel.select_best_file([str(big), str(small)])).name
P('200x200 img_z.jpg beats 40x40 img_a.jpg despite sorting later',
  kw == 'img_z.jpg' and kw_rev == 'img_z.jpg', f'{kw} / {kw_rev}')


# --------------------------------------------------------------------------
SEP('D. Full paths in reports (+ recycle-bin destination outside dry-run)')
# --------------------------------------------------------------------------
buf = io.StringIO()
rf.write_path_lines(buf, 'C:/pics/a.jpg')
P('dry-run line = original path only',
  buf.getvalue() == '  📁 Path: C:/pics/a.jpg\n', repr(buf.getvalue()))

buf = io.StringIO()
rf.write_path_lines(buf, 'C:/pics/a.jpg', {'C:/pics/a.jpg': 'C:/rb/dup/pics/a.jpg'})
P('real mode adds the moved-to destination',
  '  📁 Path: C:/pics/a.jpg\n' in buf.getvalue()
  and '  📥 Moved to: C:/rb/dup/pics/a.jpg\n' == buf.getvalue().splitlines(True)[-1],
  repr(buf.getvalue()))

buf = io.StringIO()
rf.write_path_lines(buf, 'C:/pics/other.jpg', {'C:/pics/a.jpg': 'C:/rb/x.jpg'})
P('no moved line when the file is not in moved_map',
  'Moved to' not in buf.getvalue(), repr(buf.getvalue()))

rep_dir = TEST_DIR / 'reports'
rep_dir.mkdir(parents=True, exist_ok=True)
dupgen = DuplicateReportGenerator(rep_dir)
groups = {'h1': ['C:/pics/kept.jpg', 'C:/pics/del1.jpg', 'C:/pics/del2.jpg']}
group_info = {
    'C:/pics/kept.jpg': make_info('kept.jpg', 9),
    'C:/pics/del1.jpg': make_info('del1.jpg', 2),
    'C:/pics/del2.jpg': make_info('del2.jpg', 1),
}
deleted = ['C:/pics/del1.jpg', 'C:/pics/del2.jpg']
moved = {d: f'C:/rb/duplicates{d}' for d in deleted}

dry_report = Path(dupgen.generate_duplicates_report_with_info(
    dict(groups), list(deleted), dict(group_info))).read_text(encoding='utf-8')
real_report = Path(dupgen.generate_duplicates_report_with_info(
    dict(groups), list(deleted), dict(group_info), dict(moved))).read_text(encoding='utf-8')
P('duplicates report lists every file path (dry-run)',
  dry_report.count('📁 Path:') == 3 and 'Moved to' not in dry_report,
  f"paths={dry_report.count('📁 Path:')}")
P('duplicates report (real) adds one moved-to line per deleted file',
  real_report.count('📥 Moved to:') == 2
  and all(dest in real_report for dest in moved.values()),
  f"moved={real_report.count('📥 Moved to:')}")

smallgen = SmallImagesReportGenerator(rep_dir)
small_info = {'C:/pics/tiny.jpg': make_info('tiny.jpg', 6, width=80, height=60)}
small_moved = {'C:/pics/tiny.jpg': 'C:/rb/small/tiny.jpg'}
small_dry = Path(smallgen.generate_small_images_report(
    ['C:/pics/tiny.jpg'], dict(small_info), 200, 200)).read_text(encoding='utf-8')
small_real = Path(smallgen.generate_small_images_report(
    ['C:/pics/tiny.jpg'], dict(small_info), 200, 200, small_moved)).read_text(encoding='utf-8')
P('small-images report shows the path, and moved-to only in real mode',
  '📁 Path: C:/pics/tiny.jpg' in small_dry and 'Moved to' not in small_dry
  and '📥 Moved to: C:/rb/small/tiny.jpg' in small_real, '')

corrgen = CorruptedReportGenerator(rep_dir)
corr_moved = {'C:/pics/broken.jpg': 'C:/rb/corrupted/broken.jpg'}
corr_dry = Path(corrgen.generate_corrupted_report(
    ['C:/pics/broken.jpg'])).read_text(encoding='utf-8')
corr_real = Path(corrgen.generate_corrupted_report(
    ['C:/pics/broken.jpg'], corr_moved)).read_text(encoding='utf-8')
P('corrupted report shows the path, and moved-to only in real mode',
  '📁 Path: C:/pics/broken.jpg' in corr_dry and 'Moved to' not in corr_dry
  and '📥 Moved to: C:/rb/corrupted/broken.jpg' in corr_real, '')

wrapper_ok = all(
    'moved_map' in inspect.signature(getattr(ReportGenerator, m)).parameters
    for m in ('generate_corrupted_report', 'generate_duplicates_report',
              'generate_duplicates_report_with_info', 'generate_similar_report',
              'generate_similar_report_with_info', 'generate_small_images_report'))
P('ReportGenerator wrapper forwards moved_map in every entry point', wrapper_ok)




# --------------------------------------------------------------------------
SEP('E. move_to_recycle_bin: full-path return + calm dry-run')
# --------------------------------------------------------------------------
rb_root = TEST_DIR / 'rb_real'
config.set('paths.recycle_bin', str(rb_root))
victim = TEST_DIR / 'victim.txt'
victim.write_text('payload', encoding='utf-8')
real_dest = fu.move_to_recycle_bin(str(victim), 'round8')
P('real move returns the full destination FILE path',
  isinstance(real_dest, str) and Path(real_dest).is_file()
  and Path(real_dest).name == 'victim.txt', real_dest)
P('destination lives under <recycle_bin>/<subfolder>',
  isinstance(real_dest, str) and str(real_dest).startswith(str(rb_root))
  and 'round8' in Path(real_dest).parts, real_dest)
P('original file removed after the move', not victim.exists())

fake = TEST_DIR / 'dry_victim.txt'
fake.write_text('payload', encoding='utf-8')
rb_never = TEST_DIR / 'rb_never_created'
config.set('paths.recycle_bin', str(rb_never))
config.set('safety.dry_run_mode', True)

records = []


class _Cap(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


fu_logger = logging.getLogger('src.utils.helpers.file_utils')
old_level = fu_logger.level
fu_logger.setLevel(logging.INFO)
cap = _Cap()
fu_logger.addHandler(cap)
console_buf = io.StringIO()
try:
    with contextlib.redirect_stdout(console_buf), contextlib.redirect_stderr(console_buf):
        dry_res = fu.move_to_recycle_bin(str(fake), 'round8')
finally:
    fu_logger.removeHandler(cap)
    fu_logger.setLevel(old_level)

P('dry-run returns the "dry_run" sentinel (counters still work)',
  dry_res == 'dry_run', dry_res)
P('dry-run console is SILENT (no per-file line anymore)',
  console_buf.getvalue() == '', repr(console_buf.getvalue()))
P('dry-run per-file line is written to the log instead',
  any(str(fake) in msg for msg in records), records[:1])
P('dry-run touches nothing (no dirs, file intact)',
  (not rb_never.exists()) and fake.exists(), f'rb_exists={rb_never.exists()}')

config.set('safety.dry_run_mode', DR0)
config.set('paths.recycle_bin', RBIN0)


# --------------------------------------------------------------------------
SEP('F. One dry-run summary line (wiring) + i18n key')
# --------------------------------------------------------------------------
summary_en = i18n.get('safety.dry_run_summary').format(7)
P('EN dry-run summary names the file count',
  'DRY-RUN' in summary_en and '7' in summary_en and 'report' in summary_en,
  summary_en)
flows = [
    'src/core/detectors/duplicate_detector.py',
    'src/core/detectors/corruption_detector.py',
    'src/core/processors/similarity_processor.py',
    'src/core/image_analyzer.py',
]
wired = []
for rel in flows:
    text = (ROOT / rel).read_text(encoding='utf-8')
    wired.append("safety.dry_run_summary" in text
                 and "if config.get('safety.dry_run_mode', False):" in text)
P('all 4 deletion flows print one dry-run summary line via safety.dry_run_summary',
  all(wired), wired)


# --------------------------------------------------------------------------
SEP('G. Settings menu runs end-to-end (simulated keystrokes)')
# --------------------------------------------------------------------------
from rich.console import Console                                    # noqa: E402


def _patch_ask(cls, value):
    """Patch <cls>.ask for the duration of a block; returns a restorer."""
    had_own = 'ask' in cls.__dict__
    own = cls.__dict__.get('ask')
    cls.ask = value

    def restore():
        if had_own:
            cls.ask = own
        else:
            del cls.ask
    return restore


def _patch_ask_raise(cls):
    def _raise(*a, **k):
        raise KeyboardInterrupt()
    return _patch_ask(cls, _raise)


i18n.set_language('en')
menu_console = Console(file=io.StringIO(), width=110, force_terminal=False)
handler = csh.CLISettingsHandler(menu_console)

dry_before = bool(config.get('safety.dry_run_mode', False))
seq = iter([1, 1, 3, 55, 0, 0])   # settings -> safety -> toggle dry-run -> max=55 -> back -> exit
restore_ask = _patch_ask(csh.IntPrompt, lambda *a, **k: next(seq))
orig_input = builtins.input
builtins.input = lambda *a, **k: ''
menu_error = ''
try:
    handler.handle_settings_menu()
except Exception as exc:                                            # pragma: no cover
    menu_error = repr(exc)
finally:
    restore_ask()
    builtins.input = orig_input

P('settings menu walks through without error', menu_error == '', menu_error)
P('option 1 (safety) toggled dry-run',
  bool(config.get('safety.dry_run_mode', False)) is (not dry_before))
P('option 3 changed max files to 55',
  config.get('safety.max_files_per_operation') == 55,
  config.get('safety.max_files_per_operation'))
P('settings screens rendered (title + safety submenu)',
  'Settings' in menu_console.file.getvalue()
  and 'Dry-Run' in menu_console.file.getvalue(), '')

# Reset flow: canonical defaults, safety untouched.
config.set('priorities.order', [1, 2, 3, 4])
config.set('priorities.date_priority', 'newest')
config.set('processing.phash_threshold', 12)
dry_now = bool(config.get('safety.dry_run_mode', False))
restore_confirm = _patch_ask(csh.Confirm, lambda *a, **k: True)
try:
    handler._reset_priorities_to_defaults()
finally:
    restore_confirm()
P('reset restores the canonical DEFAULT_PRIORITY_ORDER',
  list(config.get('priorities.order')) == list(DEFAULT_PRIORITY_ORDER),
  config.get('priorities.order'))
P('reset restores oldest-date + phash threshold 5',
  config.get('priorities.date_priority') == 'oldest'
  and config.get('processing.phash_threshold') == 5)
P('reset leaves safety.dry_run_mode untouched',
  bool(config.get('safety.dry_run_mode', False)) is dry_now)

# Ctrl+C exits the settings menu cleanly instead of crashing.
restore_ki = _patch_ask_raise(csh.IntPrompt)
ki_ok = False
builtins.input = lambda *a, **k: ''
try:
    handler.handle_settings_menu()
    ki_ok = True
except KeyboardInterrupt:                                           # pragma: no cover
    ki_ok = False
finally:
    restore_ki()
    builtins.input = orig_input
P('Ctrl+C in the settings menu exits cleanly', ki_ok)



# --------------------------------------------------------------------------
SEP('H. Settings live on the MAIN menu + i18n completeness')
# --------------------------------------------------------------------------
main_src = (ROOT / 'src' / 'cli' / 'main_cli.py').read_text(encoding='utf-8')
img_src = (ROOT / 'src' / 'cli' / 'image_cli.py').read_text(encoding='utf-8')
hnd_src = (ROOT / 'src' / 'cli' / 'cli_settings_handler.py').read_text(encoding='utf-8')

P('main menu offers Settings (option 6) and calls the handler',
  'categories.settings' in main_src and 'handle_settings_menu()' in main_src, '')
P('image menu no longer hosts settings',
  'handle_settings_menu' not in img_src and 'categories.settings' not in img_src, '')
P('priorities menu no longer offers scan-modes/reset options',
  'priorities.reset_defaults' not in hnd_src and 'range(6)' in hnd_src, '')
P('CLISettingsHandler exposes the new menu methods',
  all(hasattr(csh.CLISettingsHandler, m) for m in (
      'handle_settings_menu', '_handle_safety_settings',
      '_reset_priorities_to_defaults', '_handle_scan_modes')),
  '')

new_keys = [
    'settings.title', 'settings.safety', 'settings.priorities',
    'settings.scan_modes', 'settings.reset_defaults', 'settings.dry_run',
    'settings.confirm_delete', 'settings.max_files', 'settings.unlimited',
    'settings.toggle_dry_run', 'settings.toggle_confirm',
    'settings.change_max_files', 'settings.enter_max_files',
    'settings.enabled', 'settings.disabled', 'settings.dry_run_updated',
    'settings.confirm_updated', 'settings.max_files_updated',
    'settings.current_status', 'categories.settings',
    'safety.dry_run_summary', 'reports.image_path', 'reports.moved_to',
    'reports.reason_criterion_decided', 'reports.reason_criterion_decided_deletion',
    'reports.reason_tie_full',
]


def lookup(dictionary, dotted):
    node = dictionary
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


missing_en = [k for k in new_keys if lookup(ENGLISH_TRANSLATIONS, k) is None]
missing_ar = [k for k in new_keys if lookup(ARABIC_TRANSLATIONS, k) is None]
P('every new i18n key exists in EN', not missing_en, missing_en)
P('every new i18n key exists in AR', not missing_ar, missing_ar)
P('EN/AR settings section key sets match',
  set(ENGLISH_TRANSLATIONS['settings']) == set(ARABIC_TRANSLATIONS['settings']),
  set(ENGLISH_TRANSLATIONS['settings']) ^ set(ARABIC_TRANSLATIONS['settings']))

empty_en = [k for k in new_keys if not str(lookup(ENGLISH_TRANSLATIONS, k)).strip()]
empty_ar = [k for k in new_keys if not str(lookup(ARABIC_TRANSLATIONS, k)).strip()]
P('no new key is left empty in either language',
  not empty_en and not empty_ar, empty_en + empty_ar)


# --------------------------------------------------------------------------
SEP('I. Leave the machine as we found it')
# --------------------------------------------------------------------------
config.set('safety.max_files_per_operation', MAXF0)
config.set('safety.dry_run_mode', DR0)
config.set('paths.recycle_bin', RBIN0)
config.set('priorities.order', list(_CFG0.get('priorities', {}).get(
    'order', list(DEFAULT_PRIORITY_ORDER))))
config.set('priorities.date_priority',
           _CFG0.get('priorities', {}).get('date_priority', 'oldest'))
config.set('processing.phash_threshold',
           _CFG0.get('processing', {}).get('phash_threshold', 5))
_restore_cfg()
P('config/settings.json is byte-identical to the pre-run file',
  _CFG_FILE.read_bytes() == _CFG_BYTES, '')
i18n.set_language(_lang_backup)
P('language restored', i18n.current_language == _lang_backup,
  i18n.current_language)

shutil.rmtree(TEST_DIR, ignore_errors=True)

print('')
print('=' * 70)
print('  SUMMARY')
print('=' * 70)
print(f'  Total: {TP + TF}  PASS: {TP}  FAIL: {TF}')
print('  ALL TESTS PASSED ✔' if TF == 0 else '  SOME TESTS FAILED ✘')
print('=' * 70)
sys.exit(0 if TF == 0 else 1)

