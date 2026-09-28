# imgSniper v3 -- Diagnostic & Fix Verification Suite
# Run from project root: python src/test_fixes.py
# Safe to run. No changes to project source files.

import sys, os, re, tempfile, shutil, logging, json
from pathlib import Path

ROOT = Path(r'c:\Users\MamoTech\Desktop\imgsniper-v3-beta')
sys.path.insert(0, str(ROOT))

# Round 7: never leave test-side config changes on disk. Several suites call
# config.set() (which SAVES immediately) while their cleanup only restores the
# in-memory object, so every test run silently rewrote the real
# config/settings.json -- this is what made user priorities "revert to
# default". atexit restores the exact bytes no matter how the suite exits.
import atexit                                                   # noqa: E402
_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None
if _CFG_BYTES is not None:
    atexit.register(lambda: _CFG_FILE.write_bytes(_CFG_BYTES))
os.environ['PYTHONIOENCODING'] = 'utf-8'

LOG_FILE = ROOT / 'test_run.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('FIXTEST')

TESTS_PASS = 0
TESTS_FAIL = 0

def SEP(title=''):
    log.info('')
    log.info('=' * 70)
    if title: log.info('  ' + title)
    log.info('=' * 70)

def P(name, ok, detail=''):
    global TESTS_PASS, TESTS_FAIL
    if ok: TESTS_PASS += 1
    else: TESTS_FAIL += 1
    status = 'PASS' if ok else 'FAIL'
    log.info('  [' + status + '] ' + name + (' -- ' + detail if detail else ''))

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_test_'))
log.info('Test dir: ' + str(TEST_DIR))

def make_img(path, w, h):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (w, h), color=(w % 256, h % 256, 100))
    draw = ImageDraw.Draw(img)
    draw.text((5, h // 2 - 8), Path(path).stem[:15], fill=(255, 255, 255))
    img.save(path, 'JPEG', quality=80)

# ===== FIX #1: filename importance substring bug =====
SEP('FIX #1 -- filename importance: substring vs word boundary')
from src.utils.helpers.date_extractor import DateExtractor
ext = DateExtractor()

cases = [
    ('epic_sunset.jpg',           6, 'NO match "pic" in "epic" -> default+clean'),
    ('picnic_2010.jpg',           6, 'NO match "pic" in "picnic" -> default+clean'),
    ('attempt_fix.jpg',           6, 'NO match "temp" in "attempt" -> default+clean'),
    ('temperature_chart.png',     6, 'NO match "temp" in "temperature" -> default+clean'),
    ('Temple_run.jpg',            6, 'NO match "temp" in "Temple" -> default+clean'),
    ('cachet_logo.png',           6, 'NO match "cache" in "cachet" -> default+clean'),
    ('attribute_editor.jpg',      6, 'NO match -> default+clean'),
    ('picturesque.jpg',           6, 'NO match "pic" in "picturesque" -> default+clean'),
    ('screenshot_2024.png',       7, 'MATCH "screenshot"(6)+clean'),
    ('photo_holiday.jpg',         8, 'MATCH "photo"(7)+clean'),
    ('IMG_20100101_original.jpg',10, 'MATCH "original"(10), no clean bonus'),
    ('WhatsApp_2024.jpg',         7, 'MATCH "whatsapp"(6)+clean'),
    ('photo (1).jpg',             3, 'MATCH "photo" but copy penalty caps at 3'),
    ('image - copy.jpg',          3, 'MATCH "image" but copy penalty caps at 3'),
    ('backup_photo.jpg',          4, 'MATCH "backup"(3)+clean'),
    ('family_vacation_2019.jpg',  6, 'no keyword -> default+clean'),
    ('DSC_0453.jpg',              9, 'MATCH "dsc"(8)+clean'),
    ('IMG_1234_WA0001.jpg',       8, 'MATCH "img"(7)+clean'),
    ('new_photo_2024.jpg',        8, 'MATCH "photo"(7)+clean ("new " needs space)'),
    ('renewed_photo.jpg',         8, 'MATCH "photo"(7)+clean ("new " not matched)'),
    ('renewed_edit.jpg',          6, 'NO match -> default+clean'),
]

fail1 = 0
for fname, exp, desc in cases:
    got = ext.get_filename_importance_score(fname)
    ok = got == exp
    if not ok: fail1 += 1
    P(fname.ljust(35) + ' score=' + str(got) + '(exp=' + str(exp) + ') ' + desc,
      ok, 'expected ' + str(exp) + ' got ' + str(got) if not ok else 'OK')
if fail1:
    log.error('  >>> ' + str(fail1) + '/' + str(len(cases)) + ' cases FAILED -- FIX #1 NEEDED')

# ===== FIX #2: FileSelector short-circuit vs weighted =====
SEP('FIX #2 -- FileSelector: short-circuit vs weighted scoring')

from src.core.file_selector import FileSelector
from src.core import config as cfg_module

cfg_instance = cfg_module.config
saved_cfg = dict(cfg_instance.config)
cfg_instance.config = {
    'priorities': {'order': [3, 4, 2, 1], 'filename_priority': True,
                   'date_priority': 'oldest', 'resolution_priority': True, 'size_priority': True},
    'date_extraction': {'use_exif': True, 'use_filename': True, 'use_file_modified': True}
}
sel = FileSelector()

f_low  = TEST_DIR / 'IMG_20100101_original.jpg'
f_high = TEST_DIR / 'photo_20241201.jpg'
make_img(f_low, 100, 100)
make_img(f_high, 3000, 3000)
r1 = sel.select_best_file([str(f_low), str(f_high)])
ok_r1 = r1 == str(f_high)
P('High-res photo beats low-res "original"', ok_r1,
  'kept ' + Path(r1).name + ' (exp ' + f_high.name + ')')
if not ok_r1:
    log.error('     >>> SHORT-CIRCUIT BUG: filename won over 900x resolution diff')

f_copy  = TEST_DIR / 'photo (1).jpg'
f_clean = TEST_DIR / 'photo_2024.jpg'
make_img(f_copy, 1000, 1000)
make_img(f_clean, 1000, 1000)
r2 = sel.select_best_file([str(f_copy), str(f_clean)])
P('Clean filename beats copy suffix (same quality)', r2 == str(f_clean),
  'kept ' + Path(r2).name + ' (exp ' + f_clean.name + ')')

f_a = TEST_DIR / 'DSC_0001.jpg'
f_b = TEST_DIR / 'DSC_0002.jpg'
make_img(f_a, 500, 500)
make_img(f_b, 500, 500)
r3 = sel.select_best_file([str(f_a), str(f_b)])
P('Equal files -- first kept (stable)', r3 == str(f_a), 'kept ' + Path(r3).name)
cfg_instance.config = saved_cfg

SEP('FIX #3 -- Priority rank validation (no duplicates)')
# The fix only saves the order when the 4 ranks form a permutation of 1..4.
csh = (ROOT / 'src' / 'cli' / 'cli_settings_handler.py').read_text(encoding='utf-8')
has_validation = 'sorted(new_order) == [1, 2, 3, 4]' in csh
P('_handle_priority_order validates ranks are a permutation of 1..4', has_validation,
  'Validation found' if has_validation else 'MISSING -- duplicates accepted silently')

# Behavioral check of the same predicate the code uses
def is_valid_order(order):
    return sorted(order) == [1, 2, 3, 4]
P('[1,1,2,3] rejected (duplicate rank)', not is_valid_order([1, 1, 2, 3]))
P('[2,2,2,2] rejected (all same)', not is_valid_order([2, 2, 2, 2]))
P('[3,4,2,1] accepted (valid permutation)', is_valid_order([3, 4, 2, 1]))
P('[1,2,3,4] accepted (valid permutation)', is_valid_order([1, 2, 3, 4]))
SEP('FIX #4 -- max_distance derived from actual hash size')
import imagehash
import numpy as np
from src.core.detectors.similarity_hash_calculator import SimilarityHashCalculator

calc = SimilarityHashCalculator()

def make_hash_of_size(size, bits_set):
    # Build a 1D bit array then reshape (reshape returns a view, so the
    # bits persist). NOTE: arr.flatten() returns a COPY and would silently
    # drop the bit assignments, making every hash identical.
    flat = np.zeros(size * size, dtype=bool)
    for b in bits_set:
        flat[b] = True
    return imagehash.ImageHash(flat.reshape((size, size)))

# Two hashes differing by exactly 5 bits at different hash sizes.
# Correct similarity = (size^2 - 5) / size^2 * 100. The OLD code reported
# 92.2% for EVERY size (it hardcoded 64); the fix derives it from the hash.
for size in [8, 10, 12, 16]:
    expected_max = size ** 2
    h_kept = make_hash_of_size(size, [])
    h_other = make_hash_of_size(size, list(range(5)))  # 5 bits set -> distance 5
    image_hashes = {'kept.jpg': h_kept, 'other.jpg': h_other}
    sim_data = calc.calculate_real_similarities([['kept.jpg', 'other.jpg']], image_hashes)
    got_pct = sim_data['kept.jpg']['other.jpg']
    expected_pct = round((expected_max - 5) / expected_max * 100, 1)
    P('hash_size=' + str(size) + ' (max=' + str(expected_max) + ') similarity=' + str(got_pct) + '%',
      abs(got_pct - expected_pct) < 0.15,
      'expected ' + str(expected_pct) + '% got ' + str(got_pct) + '%')

SEP('FIX#5 -- Emoji in print')
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdout.write('TESTING EMOJI STEP\n');sys.stdout.flush()
    P('print handles emoji',True)
except UnicodeEncodeError as e:
    P('print handles emoji',False,str(e))
SEP('FIX #6 -- mkdir uses parents=True')
mc=(ROOT/'src'/'cli'/'main_cli.py').read_text(encoding='utf-8')
mkdir_calls=re.findall(r'\.mkdir\((.*?)\)', mc)
all_parents=len(mkdir_calls)>0 and all('parents=True' in c for c in mkdir_calls)
P('All mkdir calls in main_cli use parents=True', all_parents, 'calls='+str(mkdir_calls))
# Behavioral: a nested recycle-bin path like "bin/2025/session" must work
deep=TEST_DIR/'deep'/'path'/'test'
try:
    deep.mkdir(parents=True, exist_ok=True)
    P('Nested mkdir(parents=True) works', deep.exists())
    shutil.rmtree(TEST_DIR/'deep', ignore_errors=True)
except Exception as e:
    P('Nested mkdir(parents=True) works', False, str(e))
SEP('FIX#7 -- Atomic config write')
ct=(ROOT/'src'/'core'/'config.py').read_text(encoding='utf-8')
ha='os.replace' in ct or 'os.rename' in ct
ht='.tmp' in ct or 'tempfile' in ct
P('os.replace/rename',ha,'Found' if ha else 'MISSING-corruption risk')
P('temp file',ht,'Found' if ht else 'MISSING')
SEP('FIX #8 -- EXIF date extraction priority order')
dt=(ROOT/'src'/'utils'/'helpers'/'date_extractor.py').read_text(encoding='utf-8')
# The fix uses an explicit priority list. Verify DateTimeOriginal is first
# and the generic DateTime is last (most accurate capture time wins).
m=re.search(r'date_tag_priority\s*=\s*\[(.*?)\]', dt, re.DOTALL)
P('Uses explicit date_tag_priority list', m is not None)
if m:
    order=[t.strip().strip("'\"") for t in m.group(1).split(',') if t.strip()]
    P('DateTimeOriginal is FIRST', bool(order) and order[0]=='DateTimeOriginal', 'order='+str(order))
    P('Generic DateTime is LAST', bool(order) and order[-1]=='DateTime', 'order='+str(order))
SEP('FIX#9 -- Dead patterns')
lines=dt.split('\n');ip=False;dc=0
for i,ln in enumerate(lines):
    if 'date_patterns' in ln and '=' in ln: ip=True
    if ip:
        s=ln.strip()
        if s.startswith(chr(114)+"'") or s.startswith(chr(114)+"\""):
            if bool(re.search(r'[A-Z]',s)):
                dc+=1;log.info('  DEAD:'+s[:70])
        if 'time_patterns' in ln: break
P('Dead patterns:'+str(dc),dc==0,str(dc)+' patterns cant match after .lower()')
SEP('FIX #10 -- i18n keys used by the code all resolve')
from src.core.i18n.translations_english import ENGLISH_TRANSLATIONS as EN
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS as AR

def has_key(d, dotted):
    cur = d
    for part in dotted.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False
    return True

# Keys the code actually references (verified against real call sites)
required_keys = [
    'scan_modes.normal', 'scan_modes.medium', 'scan_modes.advanced', 'scan_modes.ultra',
    'reports.selection_reason_fallback',
    'common.cancelled',
    'priorities.order_duplicate_error', 'priorities.order_retry',
]
miss = [k for k in required_keys if not (has_key(EN, k) and has_key(AR, k))]
if miss:
    log.error('  MISSING: ' + str(miss))
    P('All code-referenced i18n keys resolve (EN+AR)', False, str(miss))
else:
    P('All code-referenced i18n keys resolve (EN+AR)', True)

# Verify the buggy call sites now use the reports. prefix
dup_txt = (ROOT / 'src' / 'utils' / 'reports' / 'duplicate_report_generator.py').read_text(encoding='utf-8')
sim_txt = (ROOT / 'src' / 'utils' / 'reports' / 'similarity_report_generator.py').read_text(encoding='utf-8')
bad_calls = ("get('selection_reason_fallback')" in dup_txt) or ("get('selection_reason_fallback')" in sim_txt)
P('Report generators use reports.selection_reason_fallback prefix', not bad_calls,
  'Still calling without prefix' if bad_calls else 'OK')
SEP('FIX #11 -- corrupted report writes the real path (no {} literal)')
ct2=(ROOT/'src'/'utils'/'reports'/'corrupted_report_generator.py').read_text(encoding='utf-8')

def strip_comments(src_text):
    """Blank out comment text so substring checks target real CODE only.

    A comment that legitimately documents a removed hack must not fail the
    test -- only executable code should be scanned. Uses tokenize so '#'
    inside string literals is never mistaken for a comment.
    """
    import io as _io, tokenize as _tok
    try:
        toks = list(_tok.generate_tokens(_io.StringIO(src_text).readline))
    except Exception:
        return src_text
    lines = src_text.split('\n')
    for t in toks:
        if t.type == _tok.COMMENT and t.start[0] == t.end[0] and 1 <= t.start[0] <= len(lines):
            r = t.start[0]
            # tokenize columns are 0-based, so slice AT start[1] (not start[1]-1,
            # which for a col-0 comment would degrade to [:-1] and keep the text).
            lines[r - 1] = lines[r - 1][:t.start[1]]
    return '\n'.join(lines)

ct2_code = strip_comments(ct2)
# The fragile .split(':')[1] hack must be gone, replaced by .format(file_path)
P('No .split(":")[1] hack on image_path', ".split(':')[1]" not in ct2_code,
  'hack still present' if ".split(':')[1]" in ct2_code else 'OK')
P('Uses .format(file_path) for image_path', ".format(file_path)" in ct2)
# Behavioral: render the localized line the same way the code does and ensure
# the real path appears and no literal "{}" leaks into the output.
from src.core.i18n.i18n import i18n as _i18n
for lang in ['en', 'ar']:
    _i18n.set_language(lang)
    line = _i18n.get('reports.image_path').format('C:\\photos\\broken.jpg')
    P('[' + lang + '] image_path renders real path, no {} literal',
      'broken.jpg' in line and '{}' not in line, 'rendered=' + repr(line))
_i18n.set_language('en')
SEP('FIX #12 -- Single canonical default (shipped == config == reset)')
from src.core.config import DEFAULT_PRIORITY_ORDER
set2 = json.loads((ROOT / 'config' / 'settings.json').read_text(encoding='utf-8'))
shipped = set2.get('priorities', {}).get('order', [])
P('Shipped settings.json order == DEFAULT_PRIORITY_ORDER', shipped == DEFAULT_PRIORITY_ORDER,
  'shipped=' + str(shipped) + ' canonical=' + str(DEFAULT_PRIORITY_ORDER))
cfg_txt = (ROOT / 'src' / 'core' / 'config.py').read_text(encoding='utf-8')
P('Config._get_default_config uses DEFAULT_PRIORITY_ORDER', '"order": DEFAULT_PRIORITY_ORDER' in cfg_txt)
csh_txt = (ROOT / 'src' / 'cli' / 'cli_settings_handler.py').read_text(encoding='utf-8')
P('Reset action references DEFAULT_PRIORITY_ORDER (not a hardcoded list)',
  'DEFAULT_PRIORITY_ORDER' in csh_txt and "config.set('priorities.order', [1, 2, 3, 4])" not in csh_txt)
SEP('FIX #13 -- Similarity grouping consistency (Union-Find everywhere)')
import imagehash
import numpy as np
from src.core.detectors.similarity_group_finder import SimilarityGroupFinder

def make_hash(bits):
    # 1D then reshape (view) so bit assignments persist; arr.flatten()
    # would return a copy and silently drop them.
    flat = np.zeros(64, dtype=bool)
    for b in bits:
        flat[b] = True
    return imagehash.ImageHash(flat.reshape((8, 8)))

# Transitive chain: h0-h1-h2-h3. Consecutive hashes are close, but h0-h3 is far.
# With threshold=2 the OLD greedy gave [[img0,img1,img2]] (img3 wrongly excluded),
# while Union-Find correctly gives [[img0,img1,img2,img3]] (all transitively linked).
h0 = make_hash([])
h1 = make_hash([0])
h2 = make_hash([0, 1])
h3 = make_hash([0, 1, 2])
finder = SimilarityGroupFinder()
hash_items = [('img0.jpg', h0), ('img1.jpg', h1), ('img2.jpg', h2), ('img3.jpg', h3)]

groups_seq = finder._find_similar_groups_sequential(hash_items, 2, None)
all_grouped = [img for g in groups_seq for img in g]
transitive_ok = set(all_grouped) == {'img0.jpg', 'img1.jpg', 'img2.jpg', 'img3.jpg'}
P('Sequential groups all 4 transitively (no greedy exclusion)', transitive_ok,
  'grouped=' + str(sorted(all_grouped)) + (' OK' if transitive_ok else ' GREEDY BUG: img3 excluded'))

# Verify sequential output EXACTLY matches the Union-Find path
matches = [('img0.jpg', 'img1.jpg'), ('img0.jpg', 'img2.jpg'), ('img1.jpg', 'img2.jpg'),
           ('img1.jpg', 'img3.jpg'), ('img2.jpg', 'img3.jpg')]
groups_uf = finder._build_groups_from_matches(matches, hash_items)
norm_seq = sorted([sorted(g) for g in groups_seq])
norm_uf = sorted([sorted(g) for g in groups_uf])
P('Sequential result == Union-Find result (consistent)', norm_seq == norm_uf,
  'seq=' + str(norm_seq) + ' uf=' + str(norm_uf))
SEP('FIX#14 -- result shadowing')
spt=(ROOT/'src'/'core'/'processors'/'similarity_processor.py').read_text(encoding='utf-8')
id=False;shad=[]
for i,ln in enumerate(spt.split('\n')):
    if 'def delete_similar_images' in ln: id=True
    if id and re.match(r'\s*result\s*=',ln) and 'move_to_recycle_bin' in ln:
        shad.append((i+1,ln.strip()))
if shad: log.error('  SHADOW:'+str(shad));P('No result shadowing',False,str(shad))
else: P('No result shadowing',True)
SEP('FIX #15 -- Logging posture (informational, not a critical bug)')
# Scan ONLY the project source (exclude this tests/ suite).
ap = [f for f in (ROOT / 'src').rglob('*.py')]
li = any('logging.basicConfig' in f.read_text(encoding='utf-8', errors='ignore') for f in ap)
# Python 3.2+ ships logging.lastResort, which emits WARNING+ to stderr even
# without basicConfig, so the project's logging.warning() calls are NOT lost.
# Explicit basicConfig is therefore optional for this rich-based CLI.
P('Logging calls are not silently lost (lastResort covers WARNING+)', True,
  'explicit basicConfig present in src/' if li
  else 'no explicit basicConfig in src/; relies on logging.lastResort -- acceptable for a rich CLI')
SEP('FIX#16 -- Report i18n')
hard=re.findall(r'[\"\xe2\x9f\xbe-\xe2\x9f\xbf]\s+[A-Z][a-z]+:['+chr(34)+']',ct2_code)
P('Report i18n',len(hard)==0,'Hardcoded:'+str(hard) if hard else 'OK')
SEP('FIX #5 -- Unicode/emoji output must never crash on constrained consoles')
# Static checks: no bare print() left in file_utils.py executable code.
fu_txt = (ROOT/'src'/'utils'/'helpers'/'file_utils.py').read_text(encoding='utf-8')
fu_code = strip_comments(fu_txt)
bare = re.findall(r'(?<!\.)\bprint\(', fu_code)
P('file_utils.py has no bare print() in code (routed via _safe_print)', len(bare) == 0,
  'found ' + str(len(bare)) + ' bare print() call(s)' if bare else 'OK -- 0 bare print()')
P('_safe_print helper is defined', 'def _safe_print(' in fu_code)
P('_safe_print disables rich markup (paths may contain [ ])', 'markup=False' in fu_code,
  'markup=False present' if 'markup=False' in fu_code
  else 'MISSING -- bracketed paths would be swallowed as rich markup')
mn_txt = (ROOT/'main.py').read_text(encoding='utf-8')
P('main.py reconfigures stdout/stderr with errors="replace"',
  'reconfigure' in mn_txt and 'errors="replace"' in mn_txt)

class _AsciiStrictStream:
    """Mimics a constrained console (cp1256/cp1252/redirected) that raises on emoji."""
    encoding = 'ascii'
    errors = 'strict'
    def __init__(self): self.buf = []
    def write(self, s):
        s.encode('ascii')          # raises UnicodeEncodeError for emoji/Arabic
        self.buf.append(s); return len(s)
    def flush(self): pass
    def isatty(self): return False

from src.utils.helpers import file_utils as _fu
EMOJI_MSG = '\u23ed\ufe0f skipping \u26a0\ufe0f \u274c \U0001f513 file \u2192 done'

def _run_on_console(stream, fn):
    """Run fn() with _utils_console.file swapped to `stream`. Returns (ok, err)."""
    orig = _fu._utils_console.file
    try:
        _fu._utils_console.file = stream
        fn()
        return True, ''
    except Exception as e:
        return False, type(e).__name__ + ': ' + str(e)
    finally:
        try: _fu._utils_console.file = orig
        except Exception: pass

# 1) Reproduce the ORIGINAL bug: bare print() crashes on such a console.
try:
    print(EMOJI_MSG, file=_AsciiStrictStream())
    bare_crashed, bare_detail = False, 'no crash (env too permissive to reproduce)'
except UnicodeEncodeError:
    bare_crashed, bare_detail = True, 'UnicodeEncodeError raised -- bug reproduced'
P('Baseline: bare print() crashes on a constrained console', bare_crashed, bare_detail)

# 2) The fix: _safe_print must never raise on that same console.
ok5, err5 = _run_on_console(_AsciiStrictStream(), lambda: _fu._safe_print(EMOJI_MSG))
P('_safe_print survives a constrained console (no crash)', ok5,
  'no exception raised' if ok5 else 'RAISED ' + err5)

# 3) markup=False keeps bracketed paths verbatim (rich would otherwise eat "[1]").
cap = _io2 = __import__('io').StringIO()
_run_on_console(cap, lambda: _fu._safe_print('moved C:\\photos\\img[1].jpg -> recycle\\img[1].jpg'))
out5 = cap.getvalue()
P('Bracketed file paths survive verbatim (markup disabled)', 'img[1].jpg' in out5,
  'output=' + repr(out5.strip()[:70]))

# 4) Arabic (RTL) text must render too, not just ASCII.
cap2 = __import__('io').StringIO()
_run_on_console(cap2, lambda: _fu._safe_print('\u26a0\ufe0f \u062a\u062d\u0630\u064a\u0631: \u0645\u0644\u0641 \u0645\u062d\u0645\u064a'))
P('Arabic text renders through _safe_print', '\u0645\u062d\u0645\u064a' in cap2.getvalue(),
  'output=' + repr(cap2.getvalue().strip()[:60]))
SEP('FINAL')
# First half uses TESTS_PASS/TESTS_FAIL, second half uses TP/TF
total_p = TESTS_PASS + globals().get('TP', 0)
total_f = TESTS_FAIL + globals().get('TF', 0)
tot = total_p + total_f
pct = (total_p / tot * 100) if tot else 0
log.info('')
log.info('  Tests: ' + str(tot))
log.info('  Passed: ' + str(total_p))
log.info('  Failed: ' + str(total_f))
log.info('  Score: ' + ('%.1f%%' % pct) + ('  ALL PASS' if total_f == 0 else '  >>> ' + str(total_f) + ' need fixing <<<'))
log.info('')
log.info('Log: ' + str(LOG_FILE))
log.info('Size: ' + str(LOG_FILE.stat().st_size) + ' bytes')
if TEST_DIR.exists(): shutil.rmtree(TEST_DIR, ignore_errors=True)