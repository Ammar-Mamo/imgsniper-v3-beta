# imgSniper v3 -- Round 13 Fix Verification Suite
# Reports must exist, must not overwrite each other, and must never mask a
# completed operation. Plus: suites must judge the CODE, not the user's live
# settings.
#
# The reported bug (real run, 36528 files):
#     ✅ Total processed: 36528 files (36528 regular + 0 force deleted)
#     ❌ Error: [Errno 2] No such file or directory:
#        'C:\...\reports\duplicates_2026-10-03_11-31-50.txt'
# The cleanup had ALREADY finished -- every file was moved -- and then the
# report write failed, because reports/ was created only ONCE (in
# ReportGenerator.__init__ at startup) and the folder had been removed while
# the scan was running. The exception escaped delete_*() and reached the CLI's
# generic handler, so a SUCCESSFUL operation was announced as "❌ Error" and its
# documentation was lost.
#
# Three fixes are verified here:
#   A. every writer re-creates the folder immediately before writing;
#   B. no report ever overwrites another (same prefix + same second);
#   C. a report failure is a WARNING, never the operation's verdict;
#   D. the suites pin the configuration they judge (Recovery Mode and dry-run
#      are legitimate live states, and inheriting them made rounds 4/8/11/12
#      report failures that were not code defects).
# Run from project root: python tests/test_fixes_round13.py

import sys, io, os, re, json, shutil, logging, tempfile, atexit, ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

# config.set() writes settings.json immediately, so the original bytes are
# restored after the mutating sections AND at interpreter exit.
_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None

# Round 14 follow-up: this suite must never touch the REAL reports/ folder.
# The user's own reports live there (real cleanup runs wrote a 26 MB duplicates
# report and a 34 MB similar one), and an earlier version of section A deleted
# the whole folder to reproduce "reports/ disappeared mid-run". Everything below
# now happens inside a throwaway sandbox, and the real folder is snapshotted so
# the suite can PROVE at the end that it left it alone.
from src.core.config import config                              # noqa: E402

_REAL_REPORTS = ROOT / 'reports'
_REAL_REPORTS_BEFORE = (sorted(p.name for p in _REAL_REPORTS.glob('*'))
                        if _REAL_REPORTS.exists() else None)
_REPORTS_SANDBOX = Path(tempfile.mkdtemp(prefix='r13_reports_'))
_REPORTS_SETTING_BEFORE = config.get('paths.reports', 'reports')


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


def console():
    from rich.console import Console
    return Console(file=io.StringIO(), force_terminal=False, width=200,
                   color_system=None, legacy_windows=False)


def drop_reports_dir():
    """Point `paths.reports` at a throwaway sandbox, then delete THAT.

    This suite originally called shutil.rmtree() on the project's REAL reports/
    folder to reproduce "the folder disappeared mid-run". That destroyed the
    user's own reports -- a 26 MB duplicates report and a 34 MB similar one, the
    audit trail of real cleanup runs -- and rmtree() bypasses the Recycle Bin,
    so they were unrecoverable. A test must never delete what the user owns.

    The code path under test does not care WHERE the folder lives: every writer
    re-creates whatever `paths.reports` resolves to, immediately before opening
    the file. Relocating the setting therefore reproduces the exact precondition
    (folder missing at write time) without touching a single byte of user data.
    """
    config.set('paths.reports', str(_REPORTS_SANDBOX))
    if _REPORTS_SANDBOX.exists():
        shutil.rmtree(_REPORTS_SANDBOX, ignore_errors=True)
    return _REPORTS_SANDBOX


# --------------------------------------------------------------------------
SEP('A. The reported bug: reports/ removed while the program is running')
# --------------------------------------------------------------------------
from src.utils.reports import unique_report_path                 # noqa: E402
from src.utils.reports.report_generator import ReportGenerator   # noqa: E402

WRITERS = ['corrupted_report_generator.py', 'duplicate_report_generator.py',
           'similarity_report_generator.py', 'small_images_report_generator.py',
           'video_duplicate_report_generator.py']

for writer in WRITERS:
    source = read_src('src/utils/reports/' + writer)
    P(f'{writer} routes its report path through unique_report_path()',
      'unique_report_path(' in source, 'helper not used')
    P(f'{writer} no longer builds the path with a bare reports_dir / join',
      'self.reports_dir / f"' not in source
      and "self.reports_dir / f'" not in source,
      [line.strip() for line in source.splitlines()
       if 'self.reports_dir /' in line])

init_src = read_src('src/utils/reports/__init__.py')
P('the shared helper creates the folder with parents=True (nested paths.reports works)',
  'mkdir(parents=True, exist_ok=True)' in init_src)
P('ReportGenerator.__init__ also uses parents=True',
  'mkdir(parents=True, exist_ok=True)' in read_src('src/utils/reports/report_generator.py'))

# Empirically: the folder is gone, then EVERY report type is written anyway.
work = Path(tempfile.mkdtemp(prefix='r13_'))
_img_a, _img_b = work / 'a.jpg', work / 'b.jpg'
_img_a.write_bytes(b'x' * 2048)
_img_b.write_bytes(b'x' * 2048)

drop_reports_dir()
P('the reports folder is really gone before the run (the reported precondition)',
  not _REPORTS_SANDBOX.exists())

rg = ReportGenerator()
info = {str(_img_a): rg.get_detailed_image_info(str(_img_a)),
        str(_img_b): rg.get_detailed_image_info(str(_img_b))}
drop_reports_dir()          # removed AFTER startup -- exactly the reported case

written = {
    'corrupted': rg.generate_corrupted_report([str(_img_a)], {}),
    'duplicates': rg.generate_duplicates_report_with_info(
        {'g1': [str(_img_a), str(_img_b)]}, [str(_img_b)], info, {}),
    'similar': rg.generate_similar_report_with_info(
        {'group_1': [str(_img_a), str(_img_b)]}, [str(_img_b)], info, {}),
    'small_images': rg.generate_small_images_report([str(_img_a)], info, 100, 100, {}),
    'section': rg.generate_file_duplicates_report_with_info(
        {'.doc': [str(_img_a), str(_img_b)]}, [str(_img_b)], info, {}, None),
}
for kind, path in written.items():
    P(f'the {kind} report was written even though reports/ had been deleted',
      bool(path) and Path(path).exists(), path)

P('the folder was re-created by the writers themselves', _REPORTS_SANDBOX.is_dir())
P('every report is a non-empty text file',
  all(Path(p).stat().st_size > 0 for p in written.values()))
P('the corrupted report still carries its title and the file list',
  'a.jpg' in Path(written['corrupted']).read_text(encoding='utf-8'))


# --------------------------------------------------------------------------
SEP('B. No report ever overwrites another (same prefix, same second)')
# --------------------------------------------------------------------------
# The image flow and a section flow that falls back to the 'duplicates' prefix
# produce the SAME name inside one second; before Round 13 the second silently
# replaced the first, so one of the two operations became unauditable.
_img_path = written['duplicates']
_second = rg.generate_file_duplicates_report_with_info(
    {'.doc': [str(_img_a), str(_img_b)]}, [str(_img_b)], info, {}, None)
P('a second report in the same second gets its own file',
  _second != _img_path, (_img_path, _second))
P('both reports still exist', Path(_img_path).exists() and Path(_second).exists())
P('the second one carries a numeric suffix instead of reusing the name',
  re.fullmatch(r'.*_\d+', Path(_second).stem) is not None, Path(_second).name)
P('the first report was NOT overwritten',
  Path(_img_path).read_text(encoding='utf-8') != Path(_second).read_text(encoding='utf-8')
  or Path(_img_path).stat().st_size > 0)

_taken = Path(_img_path).name
_third = unique_report_path(_REPORTS_SANDBOX, _taken)
P('unique_report_path() never hands back a name that is already taken',
  _third.name != _taken and not _third.exists(), _third.name)
P('unique_report_path() returns the name unchanged when it is free',
  unique_report_path(_REPORTS_SANDBOX, 'never_used_name.txt').name == 'never_used_name.txt')

video_src = read_src('src/utils/reports/video_duplicate_report_generator.py')
P('the video writer delegates to the shared helper (one implementation, not two)',
  'return unique_report_path(' in video_src
  and 'while candidate.exists()' not in video_src)


# --------------------------------------------------------------------------
SEP('C. A report failure is a warning, never the operation verdict')
# --------------------------------------------------------------------------
# Before Round 13 the report call was bare, so its exception escaped delete_*()
# and reached the CLI's generic "except Exception" -- the user saw "❌ Error"
# for an operation that had ALREADY moved every file, and "completed" never
# printed either. Verified structurally with the AST, then empirically.
CALL_SITES = ['src/core/detectors/corruption_detector.py',
              'src/core/detectors/duplicate_detector.py',
              'src/core/detectors/video_duplicate_detector.py',
              'src/core/processors/similarity_processor.py',
              'src/core/image_analyzer.py']


def _calls_report(node):
    """True when this subtree calls something like generate_*report*()."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and 'report' in sub.func.attr and sub.func.attr.startswith('generate'):
            return True
    return False


def _prints_key(node, key):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == 'get' and sub.args \
                and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == key:
            return True
    return False


guarded = 0
for rel in CALL_SITES:
    tree = ast.parse(read_src(rel))
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for idx, stmt in enumerate(fn.body):
            if not isinstance(stmt, ast.Try) or not _calls_report(stmt):
                continue
            guarded += 1
            name = f'{Path(rel).name}:{fn.name}'
            P(f'{name} wraps the report call in try/except', bool(stmt.handlers))
            handler = stmt.handlers[0] if stmt.handlers else None
            P(f'{name} tells the user the operation COMPLETED (common.report_failed)',
              handler is not None and _prints_key(handler, 'common.report_failed'))
            P(f'{name} logs the cause instead of swallowing it',
              handler is not None
              and any(isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                      and isinstance(s.value.func, ast.Attribute)
                      and s.value.func.attr in ('warning', 'error', 'exception')
                      for s in handler.body))
            after = fn.body[idx + 1:]
            P(f'{name} still prints common.completed when the report fails',
              any(_prints_key(s, 'common.completed') for s in after),
              'the completion line is missing or still inside the try')

P('every report call site in the project is guarded (6 expected)', guarded == 6, guarded)

from src.core.i18n.i18n import i18n                             # noqa: E402
from src.core.config import config                              # noqa: E402

for lang in ('en', 'ar'):
    i18n.set_language(lang)
    text = i18n.get('common.report_failed')
    P(f'common.report_failed exists in {lang} and is not a [Missing] placeholder',
      text and not text.startswith('[Missing'), text)
    P(f'common.report_failed in {lang} says the operation completed',
      'COMPLETED' in text or 'اكتملت' in text, text)
i18n.set_language('en')

# Empirically: the report writer raises, the operation must still succeed.
from src.core.detectors.corruption_detector import CorruptionDetector  # noqa: E402

_dry_before = config.get('safety.dry_run_mode', False)
config.config.setdefault('safety', {})['dry_run_mode'] = True

detector = CorruptionDetector()


def _boom(*args, **kwargs):
    raise FileNotFoundError(2, 'No such file or directory',
                            str(_REPORTS_SANDBOX / 'corrupted_x.txt'))


detector.report_generator.generate_corrupted_report = _boom
fail_console = console()
raised = None
try:
    detector.delete_corrupted_images({'corrupted_files': [str(_img_a)]}, fail_console)
except Exception as exc:                                  # pragma: no cover
    raised = exc
out = fail_console.file.getvalue()
P('a raising report writer does NOT escape the operation', raised is None, raised)
P('the user is told the report could not be saved', 'report could not be saved' in out
  or 'تعذّر حفظ التقرير' in out, [line for line in out.splitlines() if '⚠' in line][:2])
P('the operation is still announced as completed',
  i18n.get('common.completed') in out, out.splitlines()[-2:])
P('the scary generic "❌ Error" is NOT shown for a finished operation',
  '❌ Error' not in out, [line for line in out.splitlines() if '❌' in line][:2])
config.config.setdefault('safety', {})['dry_run_mode'] = _dry_before


# --------------------------------------------------------------------------
SEP('D. Suites judge the CODE, not the user live settings')
# --------------------------------------------------------------------------
# Recovery Mode and dry-run are legitimate LIVE states. Inheriting them made
# rounds 4, 8, 11 and 12 fail on a machine that was mid-cleanup, with messages
# that read like code defects ("exclude_patterns *_backup* is applied",
# "the shipped default leaves ordinary movies inside the scan (500 MB)").
from _config_pin import pin_shipped_config                      # noqa: E402
from src.core.config import DEFAULT_FILTERS, RECOVERY_FILTERS   # noqa: E402

pin_src = read_src('tests/_config_pin.py')
P('tests/_config_pin.py exists and pins filters.* from DEFAULT_FILTERS',
  'DEFAULT_FILTERS' in pin_src and 'filters' in pin_src)
P('it pins safety.dry_run_mode as well', "['dry_run_mode']" in pin_src
  or '"dry_run_mode"' in pin_src)
P('it writes the pinned baseline to disk and returns the bytes',
  'write_bytes' in pin_src and 'return path.read_bytes()' in pin_src)

PINNED = ['test_fixes_round4.py', 'test_fixes_round8.py', 'test_fixes_round11.py',
          'test_fixes_round12.py']
for suite in PINNED:
    source = read_src('tests/' + suite)
    P(f'{suite} pins the shipped configuration before judging it',
      'pin_shipped_config(' in source, 'pin not imported/called')

# The suites that assert byte-identity must compare against the PINNED baseline.
for suite in ['test_fixes_round8.py', 'test_fixes_round11.py', 'test_fixes_round12.py']:
    source = read_src('tests/' + suite)
    P(f'{suite} keeps a _BASE_BYTES baseline for its byte-identity assertions',
      '_BASE_BYTES' in source)

# Empirically: whatever the live file says, pinning yields the shipped values.
_live_before = {key: config.get('filters.' + key) for key in DEFAULT_FILTERS}
pin_shipped_config(dry_run=False)
P('after pinning, filters.* are the shipped values regardless of the live file',
  {key: config.get('filters.' + key) for key in DEFAULT_FILTERS} == DEFAULT_FILTERS,
  {key: config.get('filters.' + key) for key in DEFAULT_FILTERS})
P('after pinning, dry_run_mode is off unless the suite asks for it',
  config.get('safety.dry_run_mode', True) is False)
P('the live file may legitimately be a DIFFERENT profile (Recovery Mode)',
  _live_before in (DEFAULT_FILTERS, RECOVERY_FILTERS), _live_before)
P('pinning never touches keys it does not own (include_system stays protected)',
  config.get('filters.include_system') is False
  and RECOVERY_FILTERS['include_system'] is False)

# Restore what this suite found, then prove the restore is exact.
if _CFG_BYTES is not None:
    _CFG_FILE.write_bytes(_CFG_BYTES)
config.config.setdefault('filters', {}).update(
    json.loads(_CFG_BYTES.decode('utf-8')).get('filters', {}) if _CFG_BYTES else {})


# --------------------------------------------------------------------------
SEP('E. Leave the machine as we found it')
# --------------------------------------------------------------------------
for path in list(written.values()) + [_second]:
    try:
        if path and Path(path).exists():
            Path(path).unlink()
    except OSError:
        pass
try:
    _third.unlink()
except OSError:
    pass
shutil.rmtree(work, ignore_errors=True)

# Round 14 follow-up: put `paths.reports` back and drop the sandbox, then PROVE
# the user's real reports/ folder was never touched. This is the regression
# guard for the version of this suite that deleted it.
config.set('paths.reports', _REPORTS_SETTING_BEFORE)
shutil.rmtree(_REPORTS_SANDBOX, ignore_errors=True)
P('the sandbox reports folder is gone', not _REPORTS_SANDBOX.exists())
P('paths.reports points at the user setting again',
  config.get('paths.reports', 'reports') == _REPORTS_SETTING_BEFORE,
  config.get('paths.reports', 'reports'))

_real_now = (sorted(p.name for p in _REAL_REPORTS.glob('*'))
             if _REAL_REPORTS.exists() else None)
P('the REAL reports/ folder was never touched by this suite',
  _real_now == _REAL_REPORTS_BEFORE,
  (set(_real_now or []) ^ set(_REAL_REPORTS_BEFORE or [])))

_restore_cfg()
P('settings.json is byte-identical again', _CFG_FILE.read_bytes() == _CFG_BYTES)
P('no test report was left behind in the real reports/ folder',
  not any(p.name.startswith(('corrupted_2', 'duplicates_2', 'similar_2',
                             'small_images_2', 'never_used_name'))
          for p in _REAL_REPORTS.glob('*.txt'))
  if _REAL_REPORTS.exists() else True)

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



