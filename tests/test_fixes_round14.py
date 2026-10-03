# imgSniper v3 -- Round 14 Fix Verification Suite
# Long phases must be VISIBLE, and a keystroke typed while the program was busy
# must never answer a later prompt.
#
# The reported bug (real run: 75581 images, two folders, USB hard disk):
#
#     Do you want to confirm deletion? [y/n]: y
#     <nothing at all -- 0% CPU, flat memory, console dead -- for minutes>
#     🔍 Checking file permissions...
#     ...
#     ✅ Total processed: 50437 files (50437 regular + 0 force deleted)
#     <dead again>
#     [menu]  [0/1/2/3/4/5/6/7] (0):
#     PS C:\...>   (the program had exited)
#
# Two silent phases did honest, necessary work with zero feedback:
#   1) select_best_file() over 23666 groups -- every image opened THREE times
#      (read_dimensions, _group_pixel_counts, then the EXIF date);
#   2) report writing after "Total processed".
# The directory walk and the protected-file classification were silent too.
#
# The user pressed Enter several times at the frozen screen. The Windows console
# QUEUES keys pressed while the process is busy and hands the whole queue to the
# next read, so after the work resumed:
#     input("Press any key to continue...")  -> swallowed one Enter, never waited
#     IntPrompt.ask(default="0")             -> swallowed another -> "0" -> EXIT
# and the leftover Enters were echoed by PowerShell. A 55-minute scan ended with
# the tool closing "by itself". The same queue could answer a DELETION prompt.
#
# Verified here:
#   A. every long phase that used to print nothing now shows a live counter;
#   B. the helpers degrade to no-ops without a console, so nothing else changes;
#   C. the new wiring cannot change WHICH files are found, classified or kept;
#   D. no bare input() is left and every prompt drains the pending-key queue;
#   E. the machine is left exactly as it was found.
#
# Deliberately NOT changed by round 14, and asserted untouched where possible:
# selection logic, scoring, thresholds, dry-run behaviour, deletion behaviour,
# and report CONTENT. No cache was added (the user asked for none: a cache costs
# disk space on the very machines this tool cleans).
# Run from project root: python tests/test_fixes_round14.py

import sys, io, os, ast, shutil, logging, tempfile, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None

# The reports folder holds the USER's real reports (a run today wrote a 26 MB
# duplicates report and a 34 MB similar one). "Did this suite write a report?"
# can therefore only be answered by comparing a BEFORE snapshot with the state
# at the end -- never by looking at what the folder happens to contain.
_REPORTS_DIR = ROOT / 'reports'
_REPORTS_BEFORE = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                   if _REPORTS_DIR.exists() else [])


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


def P(label, ok, extra=''):
    global TP, TF
    TP += 1
    if ok:
        print(f'  [PASS] {label}')
    else:
        TF += 1
        print(f'  [FAIL] {label} -- {extra}')


def read_src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def console(live=False):
    from rich.console import Console
    return Console(file=io.StringIO(), force_terminal=live, width=200,
                   color_system=None, legacy_windows=False)




# --------------------------------------------------------------------------
SEP('A. The two new helpers exist and are wired into every silent phase')
# --------------------------------------------------------------------------
from src.utils.helpers.progress_ui import (track, live_counter,          # noqa: E402
                                          standard_progress)
from src.utils.helpers.console_input import (flush_pending_input,       # noqa: E402
                                            ask_line, pause)

P('src/utils/helpers/progress_ui.py exists', (ROOT / 'src/utils/helpers/progress_ui.py').exists())
P('src/utils/helpers/console_input.py exists', (ROOT / 'src/utils/helpers/console_input.py').exists())

prog_src = read_src('src/utils/helpers/progress_ui.py')
P('progress_ui reuses the project progress style (spinner + bar + % + count + time)',
  all(col in prog_src for col in
      ('SpinnerColumn', 'BarColumn', 'TimeElapsedColumn', '{task.completed}/{task.total}')))
P('progress_ui offers a no-Progress stand-in so console=None needs no branching',
  '_NullProgress' in prog_src and '_NullTask' in prog_src)
P('live_counter reports a count with NO total (a walk cannot know its total)',
  'total=None' in prog_src)
_prog_imports = sorted({(node.module or '') for node in ast.walk(ast.parse(prog_src))
                        if isinstance(node, ast.ImportFrom)} |
                       {alias.name for node in ast.walk(ast.parse(prog_src))
                        if isinstance(node, ast.Import) for alias in node.names})
P('progress_ui changes no decision: it imports nothing but rich/stdlib',
  all(mod.split('.')[0] in ('rich', 'contextlib') for mod in _prog_imports),
  _prog_imports)

# ---- the phases that were silent, file by file ---------------------------
# (source, symbol that must be present, what it makes visible)
SILENT_PHASES = [
    ('src/core/processors/similarity_processor.py', 'track(',
     'the 23666-group best-file choice + the per-file info collection'),
    ('src/core/detectors/duplicate_detector.py', 'track(',
     'the keeper choice and _collect_group_info (images AND sections)'),
    ('src/core/detectors/video_duplicate_detector.py', 'track(',
     'the video keeper choice + its info collection'),
    ('src/utils/helpers/file_utils.py', 'track(',
     'the protected-file classification'),
    ('src/core/file_categories.py', 'live_counter(',
     'the section directory walk'),
    ('src/core/detectors/corruption_detector.py', 'live_counter(', 'the corrupted scan walk'),
    ('src/core/detectors/duplicate_detector.py', 'live_counter(', 'the duplicate scan walk'),
    ('src/core/detectors/similarity_detector.py', 'live_counter(', 'the similarity scan walk'),
    ('src/core/image_analyzer.py', 'live_counter(', 'the small-images scan walk'),
]
for rel, symbol, what in SILENT_PHASES:
    source = read_src(rel)
    P(f'{Path(rel).name} shows progress for {what}', symbol in source,
      f'{symbol} not found')

# Report writing: the second dead window of a real run, now a live spinner.
REPORT_SITES = ['src/core/detectors/corruption_detector.py',
                'src/core/detectors/duplicate_detector.py',
                'src/core/detectors/video_duplicate_detector.py',
                'src/core/processors/similarity_processor.py',
                'src/core/image_analyzer.py']
for rel in REPORT_SITES:
    source = read_src(rel)
    expected = 2 if Path(rel).name == 'duplicate_detector.py' else 1
    found = source.count("console.status(i18n.get('common.report_writing'))")
    P(f'{Path(rel).name} announces report writing with a live status ({found}/{expected})',
      found >= expected, f'found {found}')

# The hardcoded English lines became translatable, so an Arabic user sees Arabic.
for rel in REPORT_SITES + ['src/core/detectors/video_duplicate_detector.py']:
    source = read_src(rel)
    P(f'{Path(rel).name} no longer hardcodes "Checking file permissions..."',
      'Checking file permissions' not in source,
      [line.strip() for line in source.splitlines()
       if 'Checking file permissions' in line])

# Every new user-visible string exists in BOTH languages (never "[Missing: ...]").
from src.core.i18n.i18n import i18n                                # noqa: E402
from src.core.i18n.translations_english import ENGLISH_TRANSLATIONS as EN  # noqa: E402
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS as AR    # noqa: E402

NEW_KEYS = ['report_writing', 'selecting_best', 'collecting_info',
            'checking_permissions', 'scanning_files', 'classifying_files']
for key in NEW_KEYS:
    P(f'common.{key} exists in English', key in EN.get('common', {}))
    P(f'common.{key} exists in Arabic', key in AR.get('common', {}))
    P(f'common.{key} carries no untranslated placeholder',
      bool(EN['common'][key].strip()) and bool(AR['common'][key].strip()))
P('the English and Arabic "common" sections still hold the same key set',
  set(EN['common']) == set(AR['common']),
  set(EN['common']) ^ set(AR['common']))


# --------------------------------------------------------------------------
SEP('B. The helpers really draw, and really degrade to nothing')
# --------------------------------------------------------------------------
# With a console: the description is rendered and the counter advances.
_c = console(live=True)
with track(_c, 'TESTPHASE-A', 4) as (_p, _t):
    for _ in range(4):
        _p.advance(_t)
_drawn = _c.file.getvalue()
P('track() draws its description on a live console', 'TESTPHASE-A' in _drawn,
  _drawn[:120])
P('track() shows the completed/total pair the rest of the tool shows',
  '4/4' in _drawn, _drawn[-160:])

_c2 = console(live=True)
with live_counter(_c2, 'TESTPHASE-B') as _counter:
    for _ in range(6):
        _counter.bump(500)
P('live_counter() draws its description', 'TESTPHASE-B' in _c2.file.getvalue())
P('live_counter() shows the running count (3000 entries so far)',
  '3000' in _c2.file.getvalue() and _counter.count == 3000, _counter.count)

# Without a console: nothing raises, nothing prints, the loop still runs.
_seen = []
with track(None, 'INVISIBLE', 3) as (_np, _nt):
    for _i in range(3):
        _np.advance(_nt)
        _seen.append(_i)
P('track(None, ...) is a silent no-op that still runs the loop', _seen == [0, 1, 2])
with live_counter(None, 'INVISIBLE') as _nc:
    _nc.bump(10)
    _nc.bump()
P('live_counter(None, ...) is a silent no-op that still counts', _nc.count == 11, _nc.count)
P('standard_progress() returns a real rich Progress for the given console',
  standard_progress(console()).__class__.__name__ == 'Progress')

# A missing/bogus total must not crash a phase that is otherwise working.
try:
    with track(console(), 'X', None) as (_bp, _bt):
        _bp.advance(_bt)
    _coerce_ok = True
except Exception as exc:                                  # pragma: no cover
    _coerce_ok = False
    _coerce_err = exc
P('a missing total cannot crash the bar (defensive coercion to 0)', _coerce_ok,
  '' if _coerce_ok else repr(_coerce_err))


# --------------------------------------------------------------------------
SEP('C. The new wiring cannot change WHICH files are found, kept or classified')
# --------------------------------------------------------------------------
# This is the whole point of "feedback only": identical results, byte for byte.
from _config_pin import pin_shipped_config                       # noqa: E402
from src.core.config import config                               # noqa: E402
from src.utils.helpers.file_utils import (get_all_images,        # noqa: E402
                                         filter_protected_files)

_BASE_BYTES = pin_shipped_config(dry_run=True)

walk = Path(tempfile.mkdtemp(prefix='r14_'))
(walk / 'sub').mkdir()
(walk / 'sub' / 'deep').mkdir()
# A mix that exercises several filters at once: big/small, image/non-image,
# a hidden name and a nested folder.
for name, size in [('a.jpg', 4096), ('b.png', 4096), ('sub/c.jpg', 4096),
                   ('sub/deep/d.jpeg', 2048), ('tiny.jpg', 10),
                   ('notes.txt', 4096), ('.hidden.jpg', 4096)]:
    target = walk / name
    target.write_bytes(b'x' * size)

FORMATS = {'.jpg', '.jpeg', '.png'}

_plain = get_all_images(str(walk), FORMATS)
_ticks = []
_cb = get_all_images(str(walk), FORMATS, progress_cb=_ticks.append)
P('get_all_images() returns EXACTLY the same list with and without the counter',
  _plain == _cb, (sorted(_plain), sorted(_cb)))
P('the counter is purely additive: it never filters, reorders or duplicates',
  len(_plain) == len(_cb) and set(_plain) == set(_cb))
P('the counter really was driven (the walk reported its progress)',
  len(_ticks) > 0 and sum(_ticks) > 0, _ticks)
P('a folder without a trailing 500-boundary still reports its remainder',
  sum(_ticks) >= len(list(walk.rglob('*'))), (sum(_ticks), len(list(walk.rglob('*')))))
P('the accepted files are the ones the shipped filters allow '
  '(tiny.jpg and .hidden.jpg dropped, notes.txt not an image)',
  {Path(p).name for p in _plain} == {'a.jpg', 'b.png', 'c.jpg', 'd.jpeg'},
  sorted(Path(p).name for p in _plain))

# The classification must not depend on whether a console was supplied.
from src.core.detectors.duplicate_detector import DuplicateDetector  # noqa: E402

_files = [str(walk / 'a.jpg'), str(walk / 'b.png'), str(walk / 'sub' / 'c.jpg')]
_a = filter_protected_files(_files, force_delete=True)
_b = filter_protected_files(_files, force_delete=True, console=console())
P('filter_protected_files() classifies identically with and without a console',
  _a == _b, (_a, _b))
P('ordinary files stay available and nothing was invented as protected',
  _a[0] == _files and _a[1] == [] and _a[2] == [], _a)

# The shared info collector: same dict, with or without a console.
_det = DuplicateDetector()
_groups = {'g1': [str(walk / 'a.jpg'), str(walk / 'b.png')],
           'g2': [str(walk / 'sub' / 'c.jpg')]}
_i1 = _det._collect_group_info(_groups, _det.report_generator.get_detailed_image_info)
_i2 = _det._collect_group_info(_groups, _det.report_generator.get_detailed_image_info,
                               console())
P('_collect_group_info() returns the SAME dict with and without a console',
  _i1 == _i2, (sorted(_i1), sorted(_i2)))
P('_collect_group_info() still covers every file of every group',
  set(_i1) == {str(walk / 'a.jpg'), str(walk / 'b.png'), str(walk / 'sub' / 'c.jpg')},
  sorted(_i1))

# The decision engine itself was NOT touched: no UI helper leaked into it.
UNTOUCHED = ['src/core/file_selector.py',
             'src/core/video_file_selector.py',
             'src/core/detectors/similarity_group_finder.py',
             'src/core/detectors/similarity_hash_calculator.py']
for rel in UNTOUCHED:
    source = read_src(rel)
    P(f'{Path(rel).name} (scoring/matching) stayed free of round-14 UI wiring',
      'progress_ui' not in source and 'console_input' not in source,
      [line.strip() for line in source.splitlines()
       if 'progress_ui' in line or 'console_input' in line])

# And the selector still decides the same way it always did.
from src.core.file_selector import FileSelector                  # noqa: E402

_sel = FileSelector()
_big = walk / 'big.jpg'
_big.write_bytes(b'y' * 4096)
P('select_best_file() still returns one of the group members (smoke)',
  _sel.select_best_file([str(_big), str(walk / 'a.jpg')]) in
  {str(_big), str(walk / 'a.jpg')})
P('a single-member group is returned unchanged',
  _sel.select_best_file([str(_big)]) == str(_big))


# --------------------------------------------------------------------------
SEP('D. A keystroke typed while the tool was busy can never answer a prompt')
# --------------------------------------------------------------------------
ci_src = read_src('src/utils/helpers/console_input.py')
P('flush_pending_input() drains the Windows console queue with msvcrt',
  'msvcrt' in ci_src and 'kbhit' in ci_src and 'getwch' in ci_src)
P('it has a POSIX branch too (select + non-blocking read)',
  'select.select' in ci_src and 'os.read' in ci_src)
P('it refuses to touch a redirected stdin (pipes and test harnesses)',
  'isatty()' in ci_src)
P('it can never raise into a prompt (fully guarded)',
  'except Exception' in ci_src)
P('ask_line() drains FIRST and then reads',
  ci_src.index('flush_pending_input()') < ci_src.index('return input(prompt)'))

# Empirically: with stdin redirected (as it is under run_all.py) it is a no-op
# that does not raise, does not block and does not swallow the real answer.
try:
    flush_pending_input()
    _flush_ok = True
except Exception as exc:                                       # pragma: no cover
    _flush_ok = False
    _flush_err = exc
P('flush_pending_input() is safe when stdin is not a terminal', _flush_ok,
  '' if _flush_ok else repr(_flush_err))

import builtins                                                # noqa: E402

_real_input = builtins.input
_order = []


def _fake_input(prompt=''):
    _order.append('input')
    return '42'


_mod = sys.modules['src.utils.helpers.console_input']
_real_flush = _mod.flush_pending_input


def _fake_flush():
    _order.append('flush')


builtins.input = _fake_input
_mod.flush_pending_input = _fake_flush
try:
    # ask_line/pause resolve flush_pending_input from their own module globals,
    # so patching the module is what proves the ORDER.
    _answer = _mod.ask_line('Q: ')
    _mod.pause('Q: ')
finally:
    _mod.flush_pending_input = _real_flush
    builtins.input = _real_input

P('ask_line() returns the user answer unchanged', _answer == '42', _answer)
P('every ask_line()/pause() drains the queue BEFORE reading',
  _order == ['flush', 'input', 'flush', 'input'], _order)

# No bare input() may remain anywhere a user is asked something.
PROMPT_FILES = ['src/cli/cli_operation_handler.py', 'src/cli/cli_settings_handler.py',
                'src/cli/cli_menu_handler.py', 'src/cli/main_cli.py',
                'src/core/image_analyzer.py', 'src/utils/helpers/file_utils.py',
                'src/utils/helpers/dimension_input.py']
for rel in PROMPT_FILES:
    source = read_src(rel)
    bare = [line.strip() for line in source.splitlines()
            if 'input(' in line and 'flush_pending_input' not in line
            and 'ask_line(' not in line and 'pause(' not in line
            and not line.strip().startswith('#')
            and 'parse_dimension_input' not in line]
    P(f'{Path(rel).name} has no bare input() left', not bare, bare)

# Every Rich prompt must be preceded by a drain on the line above it.
RICH_FILES = ['src/cli/cli_menu_handler.py', 'src/cli/cli_operation_handler.py',
              'src/cli/cli_settings_handler.py', 'src/cli/main_cli.py']
RICH = ('IntPrompt.ask(', 'Confirm.ask(', 'Prompt.ask(')
for rel in RICH_FILES:
    lines = read_src(rel).splitlines()
    unguarded = []
    for idx, line in enumerate(lines):
        body = line.strip()
        if body.startswith('#') or not any(tok in body for tok in RICH):
            continue
        previous = lines[idx - 1].strip() if idx else ''
        if 'flush_pending_input()' not in previous:
            unguarded.append(body[:70])
    P(f'{Path(rel).name} drains the key queue before EVERY rich prompt',
      not unguarded, unguarded)

# The two prompts that can destroy data are explicitly drained.
P('the FORCE-DELETE confirmation goes through ask_line()',
  "ask_line(f\"{i18n.get('protected_files.force_delete_confirm')}"
  in read_src('src/utils/helpers/file_utils.py'))
P('the small-images confirmation goes through ask_line()',
  "ask_line(f\"{i18n.get('common.continue_prompt')}\")"
  in read_src('src/core/image_analyzer.py'))
P('the main menu can no longer be answered by a leftover Enter '
  '(a drain sits directly above each default-0 prompt)',
  read_src('src/cli/main_cli.py').count('flush_pending_input()') >= 2,
  read_src('src/cli/main_cli.py').count('flush_pending_input()'))

# The prompts, their wording and their defaults were NOT changed.
P('the menu default is still 0 (no behaviour change, only a deliberate keypress)',
  'default="0"' in read_src('src/cli/main_cli.py'))
P('the deletion confirmation still asks the same question',
  "Confirm.ask(i18n.get('common.confirm_delete'))"
  in read_src('src/cli/cli_operation_handler.py'))
P('press-any-key still uses the same message',
  "pause(i18n.get('common.press_any_key'))"
  in read_src('src/cli/cli_operation_handler.py'))


# --------------------------------------------------------------------------
SEP('E. Leave the machine as we found it')
# --------------------------------------------------------------------------
shutil.rmtree(walk, ignore_errors=True)
P('the temporary tree is gone', not walk.exists())
if _CFG_BYTES is not None:
    _CFG_FILE.write_bytes(_CFG_BYTES)
P('settings.json is byte-identical to what the user left',
  _CFG_BYTES is None or _CFG_FILE.read_bytes() == _CFG_BYTES)
P('no recycle-bin leftovers from this suite',
  not any((ROOT / 'recycle-bin').glob('**/a.jpg'))
  if (ROOT / 'recycle-bin').exists() else True)
P('no report was written by this suite (the user real reports are untouched)',
  (sorted(p.name for p in _REPORTS_DIR.glob('*'))
   if _REPORTS_DIR.exists() else []) == _REPORTS_BEFORE,
  set(sorted(p.name for p in _REPORTS_DIR.glob('*'))
      if _REPORTS_DIR.exists() else []) ^ set(_REPORTS_BEFORE))

print('')
print('=' * 70)
print('  SUMMARY')
print('=' * 70)
print(f'  Total: {TP + TF}  PASS: {TP}  FAIL: {TF}')
if TF == 0:
    print('  ALL TESTS PASSED')
else:
    print('  SOME TESTS FAILED')
print('=' * 70)
sys.exit(0 if TF == 0 else 1)






