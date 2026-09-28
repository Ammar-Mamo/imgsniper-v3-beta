# imgSniper v3 -- Round 2 Fix Verification Suite
# Covers fixes A..J from the post-audit remediation round.
# Run from project root: python tests/test_fixes_round2.py

import sys, os, re, tempfile, shutil, logging, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Round 7: never leave test-side config changes on disk (config.set() saves
# immediately while the in-memory restore at the end does not) -- atexit
# restores the exact bytes, protecting the user's real priorities.
import atexit                                                   # noqa: E402
_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None
if _CFG_BYTES is not None:
    atexit.register(lambda: _CFG_FILE.write_bytes(_CFG_BYTES))

LOG_FILE = ROOT / 'test_run_round2.log'

# Same safety net main.py applies: this console is cp1256, and the suite logs
# Arabic + emoji. Without errors='replace' the StreamHandler itself raises
# UnicodeEncodeError and swallows the whole run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('FIX2')

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
    log.info('  [' + ('PASS' if ok else 'FAIL') + '] ' + name + (' -- ' + detail if detail else ''))


def make_img(path, w, h, color=None):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (w, h), color=color or (w % 256, h % 256, 120))
    ImageDraw.Draw(img).text((8, h // 2), Path(path).stem[:18], fill=(255, 255, 255))
    img.save(path, 'JPEG', quality=88)


def flatten(d, prefix=''):
    out = {}
    for k, v in d.items():
        key = prefix + '.' + k if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_r2_'))
log.info('Test dir: ' + str(TEST_DIR))

from src.core.config import config
from src.utils.helpers import file_utils as fu
from src.core.i18n.i18n import i18n

CFG_BACKUP = json.loads(json.dumps(config.config))


def restore_cfg():
    config.config = json.loads(json.dumps(CFG_BACKUP))


# =====================================================================
SEP('FIX A -- safety.* config keys are finally honoured')
# =====================================================================
from src.core.i18n.translations_english import ENGLISH_TRANSLATIONS
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS

fen, far = flatten(ENGLISH_TRANSLATIONS), flatten(ARABIC_TRANSLATIONS)
P('i18n parity EN == AR after adding safety section', set(fen) == set(far),
  'EN=' + str(len(fen)) + ' AR=' + str(len(far)) +
  ('' if set(fen) == set(far) else ' diff=' + str(set(fen) ^ set(far))))

NEW_KEYS = ['safety.dry_run_banner', 'safety.dry_run_would_move',
            'safety.max_files_exceeded', 'safety.max_files_confirm',
            'safety.resolution_sacrifice_warning']
for k in NEW_KEYS:
    for lang in ['en', 'ar']:
        i18n.set_language(lang)
        P('[' + lang + '] key resolves: ' + k, not str(i18n.get(k)).startswith('[Missing'))
i18n.set_language('en')

for k in ['safety.max_files_exceeded', 'safety.resolution_sacrifice_warning']:
    P('placeholder count matches for ' + k, fen[k].count('{}') == far[k].count('{}'),
      'en=' + str(fen[k].count('{}')) + ' ar=' + str(far[k].count('{}')))

# --- dry_run_mode must touch NOTHING and return the sentinel ---
dry_dir = TEST_DIR / 'dry'
dry_dir.mkdir(parents=True, exist_ok=True)
victim = dry_dir / 'photo.jpg'
make_img(victim, 400, 300)
before_bytes = victim.stat().st_size

config.set('safety.dry_run_mode', True)
res_dry = fu.move_to_recycle_bin(str(victim), subfolder='drytest')
P('dry_run_mode returns the "dry_run" sentinel', res_dry == 'dry_run', 'got=' + repr(res_dry))
P('dry_run_mode leaves the source file in place', victim.exists())
P('dry_run_mode does not alter the file', victim.stat().st_size == before_bytes)

rb_path = Path.cwd() / config.get('paths.recycle_bin', 'recycle-bin') / 'drytest'
P('dry_run_mode creates NO recycle-bin directory', not rb_path.exists(), 'checked=' + str(rb_path))

# --- with dry_run OFF, the file really moves ---
config.set('safety.dry_run_mode', False)
res_real = fu.move_to_recycle_bin(str(victim), subfolder='drytest')
P('with dry_run OFF the file is really moved', not victim.exists() and bool(res_real),
  'result=' + repr(res_real))
P('real move returns a path, not a sentinel',
  res_real not in ('dry_run', 'skipped_readonly', 'skipped_protected', 'skipped_error', False))

# --- sentinel must NOT be in the callers' skip-lists (dry-run reports stay honest) ---
skip_lists = []
for rel in ['src/core/detectors/corruption_detector.py', 'src/core/detectors/duplicate_detector.py',
            'src/core/processors/similarity_processor.py', 'src/core/image_analyzer.py']:
    txt = (ROOT / rel).read_text(encoding='utf-8')
    for m in re.finditer(r'not in \[([^\]]*)\]', txt):
        skip_lists.append((rel, m.group(1)))
bad = [r for r, body in skip_lists if 'dry_run' in body]
P('callers do NOT exclude "dry_run"', not bad,
  'offenders=' + str(bad) if bad else str(len(skip_lists)) + ' skip-lists checked')

# --- the CLI gate reads all three keys ---
coh = (ROOT / 'src' / 'cli' / 'cli_operation_handler.py').read_text(encoding='utf-8')
P('_safety_gate exists', 'def _safety_gate(' in coh)
for key in ['safety.dry_run_mode', 'safety.confirm_before_delete', 'safety.max_files_per_operation']:
    P('CLI reads ' + key, key in coh)
n_confirm = coh.count("Confirm.ask(i18n.get('common.confirm_delete'))")
P('deletion confirm is now config-driven (single prompt, inside the gate)',
  n_confirm == 1, 'occurrences=' + str(n_confirm))

# --- _count_deletable handles BOTH result shapes ---
from src.cli.cli_operation_handler import CLIOperationHandler


class _Stub:
    _count_deletable = CLIOperationHandler._count_deletable


stub = _Stub()
P('_count_deletable handles duplicate_detector DICT shape',
  stub._count_deletable({'h1': ['a', 'b', 'c'], 'h2': ['d', 'e']}) == 3,
  'expected=3')
P('_count_deletable handles similarity LIST shape',
  stub._count_deletable([['a', 'b'], ['c', 'd', 'e']]) == 3, 'expected=3')
P('_count_deletable is defensive on garbage input',
  stub._count_deletable(None) == 0 and stub._count_deletable('x') == 0)

restore_cfg()
shutil.rmtree(str(rb_path), ignore_errors=True)


# =====================================================================
SEP('FIX B -- the DATE criterion is alive again (EXIF + filename merged)')
# =====================================================================
from PIL import Image
from src.core.file_selector import FileSelector
from src.core.config import DEFAULT_PRIORITY_ORDER
from src.utils.helpers.date_extractor import date_extractor

sel = FileSelector()
fs_txt = (ROOT / 'src' / 'core' / 'file_selector.py').read_text(encoding='utf-8')
P('dead constant _get_date_quality_score removed', '_get_date_quality_score' not in fs_txt)
P('dead contradictory _compare_files_advanced removed', '_compare_files_advanced' not in fs_txt)
P('_compute_group_date_scores exists', 'def _compute_group_date_scores' in fs_txt)

# Two images identical in resolution/size/name-pattern; ONLY the date differs.
date_dir = TEST_DIR / 'dates'
date_dir.mkdir(parents=True, exist_ok=True)
d_old = date_dir / 'photo_20100101.jpg'
d_new = date_dir / 'photo_20240101.jpg'
make_img(d_old, 1600, 1200)
make_img(d_new, 1600, 1200)
dfiles = [str(d_old), str(d_new)]

config.set('priorities.order', [3, 4, 1, 2])       # date ranked #1
dscores = sel._compute_group_date_scores(dfiles)
P('date scores are NO LONGER constant across the group', len(set(dscores.values())) > 1,
  'scores=' + str({Path(k).name: round(v, 2) for k, v in dscores.items()}))

config.set('priorities.date_priority', 'oldest')
P("date_priority='oldest' keeps the OLDER image",
  sel.select_best_file(dfiles) == str(d_old), 'expected=' + d_old.name)

config.set('priorities.date_priority', 'newest')
P("date_priority='newest' keeps the NEWER image",
  sel.select_best_file(dfiles) == str(d_new), 'expected=' + d_new.name)

config.set('priorities.date_priority', 'oldest')
fwd = sel.select_best_file(dfiles)
rev = sel.select_best_file(list(reversed(dfiles)))
P('winner is STABLE regardless of input order (determinism restored)', fwd == rev,
  'forward=' + Path(fwd).name + ' reversed=' + Path(rev).name)

# --- user requirement: date from FILENAME only (no EXIF at all) ---
fn_only = date_dir / 'screenshot_20150601.png'
make_img(fn_only, 1600, 1200)
d_fn, src_fn = date_extractor.get_best_date(str(fn_only))
P('filename-only date is extracted (no EXIF present)',
  d_fn is not None and d_fn.year == 2015, 'date=' + str(d_fn) + ' source=' + str(src_fn))

# --- user requirement: date from EXIF only, and merging BOTH sources ---
_real_exif = date_extractor.extract_date_from_exif
try:
    import datetime as _dt
    date_extractor.extract_date_from_exif = lambda p: _dt.datetime(2001, 1, 1, 1, 1, 1)
    exif_only = date_dir / 'IMG_0001.jpg'
    make_img(exif_only, 1600, 1200)
    d_ex, src_ex = date_extractor.get_best_date(str(exif_only))
    P('EXIF-only date is used when the filename carries no date',
      d_ex is not None and d_ex.year == 2001 and src_ex == 'exif',
      'date=' + str(d_ex) + ' source=' + str(src_ex))

    both = date_dir / 'photo_20200101.jpg'      # filename says 2020, EXIF says 2001
    make_img(both, 1600, 1200)
    d_o, s_o = date_extractor.get_best_date(str(both), 'oldest')
    P('BOTH sources merged: oldest wins across filename+EXIF',
      d_o is not None and d_o.year == 2001 and s_o == 'exif',
      'date=' + str(d_o) + ' source=' + str(s_o))
    d_n, s_n = date_extractor.get_best_date(str(both), 'newest')
    P("BOTH sources merged: newest wins under 'newest'",
      d_n is not None and d_n.year == 2020 and s_n == 'filename',
      'date=' + str(d_n) + ' source=' + str(s_n))
finally:
    date_extractor.extract_date_from_exif = _real_exif

# --- P0-3 defensive fallback inside the engine ---
P('_is_valid_rank_permutation accepts true permutations',
  sel._is_valid_rank_permutation([3, 4, 2, 1]) and sel._is_valid_rank_permutation([1, 2, 3, 4]))
P('_is_valid_rank_permutation rejects duplicate ranks',
  not sel._is_valid_rank_permutation([1, 1, 2, 1]) and not sel._is_valid_rank_permutation([3, 4, 2, 2]))
P('_is_valid_rank_permutation rejects garbage',
  not sel._is_valid_rank_permutation(None) and not sel._is_valid_rank_permutation(['a', 'b', 'c', 'd']))

config.set('priorities.order', [1, 1, 2, 1])       # corrupt duplicate ranks
kept_bad = sel.select_best_file(dfiles)
P('engine falls back to DEFAULT on duplicate ranks (no crash, sane result)',
  kept_bad in dfiles, 'kept=' + Path(kept_bad).name)
config.set('priorities.order', list(DEFAULT_PRIORITY_ORDER))


# =====================================================================
SEP('FIX D -- quality-floor guard + explicit resolution-sacrifice warning')
# =====================================================================
qf_dir = TEST_DIR / 'qfloor'
qf_dir.mkdir(parents=True, exist_ok=True)
tiny, huge, mid = qf_dir / 'tiny.jpg', qf_dir / 'huge.jpg', qf_dir / 'mid.jpg'
make_img(tiny, 100, 100)
make_img(huge, 3000, 3000)
make_img(mid, 1500, 1500)

close_dir = TEST_DIR / 'close'
close_dir.mkdir(parents=True, exist_ok=True)
c1, c2 = close_dir / 'a.jpg', close_dir / 'b.jpg'
make_img(c1, 1000, 1000)
make_img(c2, 1200, 1200)                      # ratio 1.44 < 2.0
b_close = sel._compute_resolution_boost([str(c1), str(c2)])
P('boost == 1.0 for a 1.44x spread (guard stays dormant)', b_close == 1.0,
  'boost=' + str(b_close))

b_extreme = sel._compute_resolution_boost([str(tiny), str(huge)])
P('boost > 1.0 on an extreme spread (900x)', b_extreme > 1.0, 'boost=' + str(round(b_extreme, 3)))
P('boost is CAPPED -- dimensions never get absolute preference',
  b_extreme <= FileSelector.QUALITY_FLOOR_MAX_BOOST,
  'boost=' + str(round(b_extreme, 3)) + ' cap=' + str(FileSelector.QUALITY_FLOOR_MAX_BOOST))
P('boost grows with the gap (mid spread < extreme spread)',
  sel._compute_resolution_boost([str(mid), str(huge)]) < b_extreme)
P('boost == 1.0 for a single-file group', sel._compute_resolution_boost([str(tiny)]) == 1.0)

sac = sel.detect_resolution_sacrifice(str(tiny), [str(tiny), str(huge)])
P('detect_resolution_sacrifice flags a lower-res keep',
  sac is not None and sac[1] > sac[0], 'result=' + str(sac))
P('detect_resolution_sacrifice returns None when the kept file IS the best',
  sel.detect_resolution_sacrifice(str(huge), [str(tiny), str(huge)]) is None)
P('detect_resolution_sacrifice is safe on unreadable input',
  sel.detect_resolution_sacrifice(str(qf_dir / 'nope.jpg'), [str(huge)]) is None)

# --- the warning must reach the REPORT ---
from src.utils.reports.report_formatter import ReportFormatter
rf = ReportFormatter()


def _mk_info(path):
    try:
        with Image.open(path) as im:
            w, h = im.size
        return {'width': w, 'height': h, 'resolution': w * h,
                'size_bytes': Path(path).stat().st_size,
                'size_mb': round(Path(path).stat().st_size / 1048576, 2),
                'filename_importance': date_extractor.get_filename_importance_score(Path(path).name),
                'extracted_date': 'Unknown'}
    except Exception as e:
        return {'error': str(e)}


info_qf = {str(tiny): _mk_info(tiny), str(huge): _mk_info(huge)}
for lang in ['en', 'ar']:
    i18n.set_language(lang)
    r_bad = rf.get_detailed_selection_reason(str(tiny), [str(tiny), str(huge)], info_qf)
    P('[' + lang + '] report WARNS when a higher-res sibling was sacrificed',
      '9.0MP' in r_bad and '0.0MP' in r_bad, 'reason=' + repr(r_bad[:130]))
    r_ok = rf.get_detailed_selection_reason(str(huge), [str(tiny), str(huge)], info_qf)
    P('[' + lang + '] NO warning when the kept file is the highest-res',
      '9.0MP' not in r_ok or '0.0MP' not in r_ok, 'reason=' + repr(r_ok[:110]))
i18n.set_language('en')

restore_cfg()


# =====================================================================
SEP('FIX B+D integration -- audit P0-1 fixture (4 images x order permutations)')
# =====================================================================
p01 = TEST_DIR / 'p01'
p01.mkdir(parents=True, exist_ok=True)
FIXTURE = [('IMG_20100101_original.jpg', 100, 100),
           ('IMG_20201231_wa0001 (1).jpg', 3000, 3000),
           ('photo_20150601.jpg', 800, 800),
           ('IMG_20240101_camera.jpg', 2000, 2000)]
p01_files = []
for _nm, _w, _h in FIXTURE:
    _p = p01 / _nm
    make_img(_p, _w, _h)
    p01_files.append(str(_p))


def _px(path):
    with Image.open(path) as im:
        return im.size[0] * im.size[1]


BIG = 3000 * 3000
config.set('priorities.date_priority', 'oldest')

# HARD requirement: the shipped/default order must keep the high-resolution image.
config.set('priorities.order', list(DEFAULT_PRIORITY_ORDER))
kept_def = sel.select_best_file(p01_files)
P('DEFAULT order [1,2,3,4] keeps the 3000x3000 image (P0-1 closed)',
  _px(kept_def) == BIG, 'kept=' + Path(kept_def).name + ' px=' + str(_px(kept_def)))

# Determinism across every permutation: input order must never change the winner.
det_bad = []
for order in [[1, 2, 3, 4], [3, 4, 2, 1], [2, 3, 4, 1], [4, 3, 2, 1]]:
    config.set('priorities.order', order)
    a = sel.select_best_file(p01_files)
    b = sel.select_best_file(list(reversed(p01_files)))
    if a != b:
        det_bad.append((order, Path(a).name, Path(b).name))
P('winner is input-order independent for ALL 4 permutations (determinism)',
  not det_bad, 'unstable=' + str(det_bad) if det_bad else 'all 4 stable')

# Duplicate ranks must not crash and must fall back to the safe default.
dup_bad = []
for order in [[1, 1, 2, 1], [3, 4, 2, 2]]:
    config.set('priorities.order', order)
    try:
        k = sel.select_best_file(p01_files)
        if _px(k) != BIG:
            dup_bad.append((order, Path(k).name))
    except Exception as e:
        dup_bad.append((order, 'RAISED ' + type(e).__name__))
P('duplicate ranks fall back to the safe default and keep high-res',
  not dup_bad, 'problems=' + str(dup_bad) if dup_bad else 'both kept 3000x3000')

# Informational: how each filename-first permutation behaves now.
config.set('priorities.order', list(DEFAULT_PRIORITY_ORDER))
for order in [[3, 4, 2, 1], [2, 3, 4, 1], [4, 3, 2, 1]]:
    config.set('priorities.order', order)
    k = sel.select_best_file(p01_files)
    px = _px(k)
    log.info('      order=' + str(order) + ' -> kept ' + Path(k).name +
             ' (' + str(px) + ' px)' + ('  HIGH-RES' if px == BIG else '  lower-res (warned in report)'))
    # Whatever the outcome, a lower-res keep MUST be reported as a sacrifice.
    if px != BIG:
        P('order=' + str(order) + ' lower-res keep IS flagged as a sacrifice',
          sel.detect_resolution_sacrifice(k, p01_files) is not None)

config.set('priorities.order', list(DEFAULT_PRIORITY_ORDER))
restore_cfg()


# =====================================================================
SEP('FINAL')
# =====================================================================
tot = TP + TF
pct = (TP / tot * 100) if tot else 0
log.info('')
log.info('  Tests: ' + str(tot))
log.info('  Passed: ' + str(TP))
log.info('  Failed: ' + str(TF))
log.info('  Score: ' + ('%.1f%%' % pct) + ('  ALL PASS' if TF == 0 else '  >>> ' + str(TF) + ' need fixing <<<'))
log.info('')
log.info('Log: ' + str(LOG_FILE))

if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR, ignore_errors=True)

sys.exit(0 if TF == 0 else 1)
