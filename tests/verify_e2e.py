# imgSniper v3 -- END-TO-END verification on REAL code paths and REAL images.
# Run: python src/verify_e2e.py
# Exercises the actual FileSelector / DateExtractor / SimilarityGroupFinder /
# Config classes (not mocks) to prove the critical fixes work in practice.

import sys, os, tempfile, shutil, logging, json
from pathlib import Path

ROOT = Path(r'c:\Users\MamoTech\Desktop\imgsniper-v3-beta')
sys.path.insert(0, str(ROOT))
os.environ['PYTHONIOENCODING'] = 'utf-8'

LOG = ROOT / 'verify_e2e.log'
logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG, encoding='utf-8', mode='w'),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger('E2E')

PASS = 0
FAIL = 0

def check(name, ok, detail=''):
    global PASS, FAIL
    if ok:
        PASS += 1
        log.info('  [PASS] ' + name + (' -- ' + detail if detail else ''))
    else:
        FAIL += 1
        log.error('  [FAIL] ' + name + (' -- ' + detail if detail else ''))

def section(t):
    log.info('')
    log.info('=' * 72)
    log.info('  ' + t)
    log.info('=' * 72)

WORK = Path(tempfile.mkdtemp(prefix='imgsniper_e2e_'))
log.info('Work dir: ' + str(WORK))

def make_img(path, w, h, color=None):
    from PIL import Image, ImageDraw
    c = color or (w % 256, h % 256, 120)
    img = Image.new('RGB', (w, h), color=c)
    d = ImageDraw.Draw(img)
    d.rectangle([w // 4, h // 4, w // 2, h // 2], fill=(255, 255, 255))
    d.text((8, 8), Path(path).stem[:18], fill=(0, 0, 0))
    img.save(path, 'JPEG', quality=88)
    return path

# =====================================================================
# SCENARIO 1: The ORIGINAL data-loss bug from the audit.
# Before the fix the 823-byte 100x100 "original" was KEPT and the 142KB
# 3000x3000 photo was DELETED. After the fix the high-res image wins.
# =====================================================================
section('SCENARIO 1 -- Original data-loss bug (high-res must survive)')
from src.core.file_selector import FileSelector
from src.core import config as cfg_mod

cfg = cfg_mod.config
saved = dict(cfg.config)
order = cfg.get('priorities.order', [1, 2, 3, 4])
log.info('  Active priorities.order = ' + str(order))

s1 = WORK / 's1'
s1.mkdir()
f_orig = make_img(s1 / 'IMG_20100101_original.jpg', 100, 100)
f_big  = make_img(s1 / 'IMG_20201231_wa0001 (1).jpg', 3000, 3000)
f_mid  = make_img(s1 / 'photo_20150601.jpg', 800, 800)
f_cam  = make_img(s1 / 'IMG_20240101_camera.jpg', 2000, 2000)

sel = FileSelector()
group = [str(f_orig), str(f_big), str(f_mid), str(f_cam)]
kept = sel.select_best_file(group)
kept_name = Path(kept).name
log.info('  KEPT     = ' + kept_name)
for f in group:
    if f != kept:
        log.info('  DELETED  = ' + Path(f).name)
for f in group:
    log.info('    ' + Path(f).name.ljust(32) + str(Path(f).stat().st_size).rjust(8) + ' bytes')

check('3000x3000 high-res image is KEPT (not the 100x100 "original")',
      kept == str(f_big), 'kept=' + kept_name)
check('100x100 low-res "original" is NOT kept', kept != str(f_orig),
      'low-res original wrongly kept!' if kept == str(f_orig) else 'ok')

# =====================================================================
# SCENARIO 2: filename false-positives must NOT penalize a good photo
# =====================================================================
section('SCENARIO 2 -- filename word-boundary (no false penalties)')
from src.utils.helpers.date_extractor import date_extractor as dx
for fname, kw in [('epic_sunset.jpg', 'pic'), ('attempt_fix.jpg', 'temp'),
                  ('Temple_run.jpg', 'temp'), ('cachet_logo.png', 'cache'),
                  ('picturesque.jpg', 'pic')]:
    score = dx.get_filename_importance_score(fname)
    check(fname + ' not penalized by substring "' + kw + '" (score=6)',
          score == 6, 'score=' + str(score))
for fname, exp in [('screenshot_2024.png', 7), ('photo_holiday.jpg', 8), ('DSC_0453.jpg', 9)]:
    score = dx.get_filename_importance_score(fname)
    check(fname + ' keyword recognized (score=' + str(exp) + ')', score == exp, 'score=' + str(score))

cfg.config = saved

# =====================================================================
# SCENARIO 3: grouping consistency (sequential == Union-Find)
# =====================================================================
section('SCENARIO 3 -- grouping identical regardless of dataset size')
import imagehash
import numpy as np
from src.core.detectors.similarity_group_finder import SimilarityGroupFinder

def mk_hash(bits, size=8):
    flat = np.zeros(size * size, dtype=bool)
    for b in bits:
        flat[b] = True
    return imagehash.ImageHash(flat.reshape((size, size)))

finder = SimilarityGroupFinder()
chain = [('c0.jpg', mk_hash([])), ('c1.jpg', mk_hash([0])),
         ('c2.jpg', mk_hash([0, 1])), ('c3.jpg', mk_hash([0, 1, 2]))]
seq_groups = finder._find_similar_groups_sequential(chain, 2, None)
seq_flat = sorted([img for g in seq_groups for img in g])
check('Sequential path groups all 4 transitively',
      seq_flat == ['c0.jpg', 'c1.jpg', 'c2.jpg', 'c3.jpg'], 'grouped=' + str(seq_flat))
matches = [('c0.jpg', 'c1.jpg'), ('c0.jpg', 'c2.jpg'), ('c1.jpg', 'c2.jpg'),
           ('c1.jpg', 'c3.jpg'), ('c2.jpg', 'c3.jpg')]
uf_groups = finder._build_groups_from_matches(matches, chain)
norm = lambda gs: sorted([sorted(g) for g in gs])
check('Sequential result == Union-Find result (no count-dependent drift)',
      norm(seq_groups) == norm(uf_groups),
      'seq=' + str(norm(seq_groups)) + ' uf=' + str(norm(uf_groups)))

# =====================================================================
# SCENARIO 4: similarity percentage correct per hash size
# =====================================================================
section('SCENARIO 4 -- similarity percent correct for every scan mode')
from src.core.detectors.similarity_hash_calculator import SimilarityHashCalculator
calc = SimilarityHashCalculator()
for size in [8, 10, 12, 16]:
    exp_max = size ** 2
    hk = mk_hash([], size)
    ho = mk_hash(list(range(5)), size)
    data = calc.calculate_real_similarities([['k.jpg', 'o.jpg']], {'k.jpg': hk, 'o.jpg': ho})
    got = data['k.jpg']['o.jpg']
    exp = round((exp_max - 5) / exp_max * 100, 1)
    check('hash_size=' + str(size) + ' similarity=' + str(got) + '% (expected ' + str(exp) + '%)',
          abs(got - exp) < 0.15, 'got=' + str(got))

# =====================================================================
# SCENARIO 5: atomic config write survives and reloads intact
# =====================================================================
section('SCENARIO 5 -- atomic config write + reload integrity')
from src.core.config import Config, DEFAULT_PRIORITY_ORDER
test_cfg_path = WORK / 'cfg_test.json'
c = Config.__new__(Config)
c.config_path = test_cfg_path
c.config = {'language': 'en', 'priorities': {'order': list(DEFAULT_PRIORITY_ORDER)},
            'processing': {'phash_threshold': 5}}
c.save_config()
check('Config file written', test_cfg_path.exists())
check('No leftover .tmp file (atomic replace completed)',
      not test_cfg_path.with_suffix('.json.tmp').exists())
reloaded = json.loads(test_cfg_path.read_text(encoding='utf-8'))
check('Reloaded config matches what was saved', reloaded == c.config,
      'reloaded order=' + str(reloaded.get('priorities', {}).get('order')))

# =====================================================================
# SCENARIO 6: EXIF priority -- DateTimeOriginal wins over DateTime
# (tests the priority logic directly; no external EXIF lib needed)
# =====================================================================
section('SCENARIO 6 -- EXIF DateTimeOriginal takes priority')
# A real camera file has DateTimeOriginal (true capture) in the Exif sub-IFD
# and DateTime (often a later edit) in the 0th IFD. The fix must prefer
# DateTimeOriginal regardless of dict ordering.
tags = {
    'DateTime': '2020:06:06 06:06:06',          # later edit -- must NOT win
    'DateTimeDigitized': '2010:10:10 10:10:10',
    'DateTimeOriginal': '2001:01:01 01:01:01',  # true capture -- must win
}
got_date = dx._pick_date_from_tags(tags)
check('EXIF picks DateTimeOriginal (2001) over DateTime (2020)',
      got_date is not None and got_date.year == 2001, 'got=' + str(got_date))
# When only DateTime exists, it is still used
only_dt = dx._pick_date_from_tags({'DateTime': '2020:06:06 06:06:06'})
check('Falls back to DateTime when no Original/Digitized',
      only_dt is not None and only_dt.year == 2020, 'got=' + str(only_dt))
# Digitized wins over plain DateTime
dig = dx._pick_date_from_tags({'DateTime': '2020:06:06 06:06:06',
                               'DateTimeDigitized': '2010:10:10 10:10:10'})
check('DateTimeDigitized beats plain DateTime',
      dig is not None and dig.year == 2010, 'got=' + str(dig))

# =====================================================================
# SUMMARY
# =====================================================================
section('E2E SUMMARY')
total = PASS + FAIL
log.info('  Checks: ' + str(total))
log.info('  Passed: ' + str(PASS))
log.info('  Failed: ' + str(FAIL))
log.info('  Result: ' + ('ALL PASS -- critical fixes verified on real code' if FAIL == 0
                         else str(FAIL) + ' FAILURE(S)'))
log.info('  Log: ' + str(LOG))
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if FAIL == 0 else 1)

