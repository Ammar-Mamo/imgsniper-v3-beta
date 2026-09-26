# imgSniper v3 -- Round 3 Fix Verification Suite
# Covers P0-4, P0-8, P2-13, P2-14, P2-18 and P3-6, plus a P0-1 regression
# sweep across every priority permutation.
# Run from project root: python tests/test_fixes_round3.py

import sys, os, re, io, json, tempfile, shutil, logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / 'test_run_round3.log'

# Same safety net main.py applies: this console is cp1256 and the suite logs
# emoji, so without errors='replace' the handler itself would raise.
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
log = logging.getLogger('FIX3')

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


def make_img(path, w, h, exif_datetime=None):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (w, h), (w % 256, h % 256, 120))
    ImageDraw.Draw(img).text((8, h // 2), Path(path).stem[:18], fill=(255, 255, 255))
    if exif_datetime:
        ex = img.getexif()
        ex[306] = exif_datetime          # 306 = DateTime
        img.save(path, 'JPEG', quality=88, exif=ex)
    else:
        img.save(path, 'JPEG', quality=88)


TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_r3_'))
log.info('Test dir: ' + str(TEST_DIR))

from src.core.config import config, DEFAULT_PRIORITY_ORDER
from src.core.file_selector import FileSelector
from src.utils.helpers.date_extractor import date_extractor
from src.core.detectors.similarity_group_finder import SimilarityGroupFinder
from src.utils.reports.image_info_extractor import ImageInfoExtractor
from src.utils.reports.duplicate_report_generator import DuplicateReportGenerator

_cfg_backup = json.loads(json.dumps(config.config))


def restore_cfg():
    config.config = json.loads(json.dumps(_cfg_backup))


# =====================================================================
SEP('P0-8  filename-score outliers removed')
# =====================================================================
score = date_extractor.get_filename_importance_score

a, b, c = score('original.jpg'), score('camera.jpg'), score('dsc_1234.jpg')
P('original / camera / dsc are tied (no semantic inversion)',
  a == b == c, 'original=%d camera=%d dsc=%d' % (a, b, c))

P('no filename score exceeds 9', max(score(n) for n in
  ['original.jpg', 'camera.jpg', 'dsc_1234.jpg', 'photo.jpg', 'IMG_0001.jpg',
   'pic.jpg', 'video.mov', 'screenshot.png']) <= 9,
  'max=%d' % max(score(n) for n in ['original.jpg', 'dsc_1234.jpg', 'video.mov']))

fi = date_extractor.filename_importance
P("no weight in the pattern table exceeds 8", max(fi.values()) <= 8,
  'max weight=%d' % max(fi.values()))
P("'original' weight lowered from 10 to 8", fi['original'] == 8, str(fi['original']))
P("'camera' weight lowered from 9 to 8", fi['camera'] == 8, str(fi['camera']))

P('copy markers are still penalised (user requirement)',
  score('copy.jpg') <= 3 and score('copy (1).jpg') <= 3,
  'copy=%d  copy (1)=%d' % (score('copy.jpg'), score('copy (1).jpg')))
P('word boundaries intact: epic/attempt not penalised',
  score('epic.jpg') == score('mydoc.jpg') and score('attempt.jpg') == score('mydoc.jpg'),
  'epic=%d attempt=%d plain=%d' % (score('epic.jpg'), score('attempt.jpg'), score('mydoc.jpg')))

P('the original/camera bonus exemption is gone from the source',
  "_pattern_matches(filename_lower, 'original')" not in
  read_src('src/utils/helpers/date_extractor.py').split('def get_filename_importance_score')[1].split('def _pattern_matches')[0])

# =====================================================================
SEP('P0-4  phash_threshold scaled by hash_size')
# =====================================================================
F = SimilarityGroupFinder()
sc = SimilarityGroupFinder._scale_threshold

P('reference size 8 keeps the configured value unchanged', sc(5, 8) == 5, str(sc(5, 8)))

ratios = {}
for hs in (8, 10, 12, 16):
    t = sc(5, hs)
    ratios[hs] = 100.0 * (1 - t / float(hs * hs))
    log.info('      hash_size=%2d -> threshold=%2d  similarity=%.1f%%' % (hs, t, ratios[hs]))
spread = max(ratios.values()) - min(ratios.values())
P('similarity ratio is unified across all four scan modes (spread < 1%)',
  spread < 1.0, 'spread=%.2f%%' % spread)
P('Ultra mode is no longer silently stricter than Normal',
  abs(ratios[16] - ratios[8]) < 1.0,
  'Normal=%.1f%% Ultra=%.1f%%' % (ratios[8], ratios[16]))

import numpy as np, imagehash
det_ok = True
for hs in (8, 10, 12, 16):
    h = imagehash.ImageHash(np.zeros((hs, hs), dtype=bool))
    got = SimilarityGroupFinder._detect_hash_size({'x.jpg': h})
    if got != hs:
        det_ok = False
P('_detect_hash_size reads the real size off imagehash objects', det_ok)

P('degenerate input falls back safely instead of crashing',
  F._resolve_threshold({}) == 5 and
  F._resolve_threshold({'a': object()}) == 5 and
  F._resolve_threshold({'a': None}) == 5)

P('threshold scaling is actually wired into find_similar_groups',
  '_resolve_threshold(image_hashes)' in
  read_src('src/core/detectors/similarity_group_finder.py'))


# =====================================================================
SEP('P2-14  compare_images_by_date is date-only')
# =====================================================================
p_na = TEST_DIR / 'aaa.jpg'
p_nb = TEST_DIR / 'original.jpg'
make_img(p_na, 60, 60)
make_img(p_nb, 60, 60)
r = date_extractor.compare_images_by_date(str(p_na), str(p_nb))
P('no date on either side -> equal (used to be -1 because original won)',
  r == 0, 'got %d' % r)

p_e1 = TEST_DIR / 'x_20200101.jpg'
p_e2 = TEST_DIR / 'original_20200101.jpg'
make_img(p_e1, 60, 60)
make_img(p_e2, 60, 60)
P('equal dates -> equal (no filename tiebreak)',
  date_extractor.compare_images_by_date(str(p_e1), str(p_e2)) == 0)

p_old = TEST_DIR / 'old_20010101.jpg'
p_new = TEST_DIR / 'new_20200101.jpg'
make_img(p_old, 60, 60)
make_img(p_new, 60, 60)
P('oldest priority still prefers the older image',
  date_extractor.compare_images_by_date(str(p_old), str(p_new), 'oldest') == -1)
P('newest priority still prefers the newer image',
  date_extractor.compare_images_by_date(str(p_old), str(p_new), 'newest') == 1)

_cibd = read_src('src/utils/helpers/date_extractor.py').split('def compare_images_by_date')[1]
P('compare_images_by_date body contains no filename scoring',
  'get_filename_importance_score' not in _cibd)


# =====================================================================
SEP('P2-13  reports read the merged EXIF+filename date')
# =====================================================================
E = ImageInfoExtractor()

p_exif = TEST_DIR / 'IMG_0001.jpg'
make_img(p_exif, 400, 300, exif_datetime='2001:05:04 10:20:30')
i1 = E.get_detailed_image_info(str(p_exif))
P('EXIF-only image no longer reports Unknown',
  str(i1.get('extracted_date', '')).startswith('2001'), str(i1.get('extracted_date')))
P("EXIF-only image reports source 'exif'",
  i1.get('date_source') == 'exif', str(i1.get('date_source')))

p_name = TEST_DIR / 'screenshot_20150601.png'
from PIL import Image as _PILImage
_PILImage.new('RGB', (400, 300), (200, 40, 40)).save(str(p_name))
i2 = E.get_detailed_image_info(str(p_name))
P("filename-only image reports source 'filename'",
  i2.get('date_source') == 'filename', str(i2.get('date_source')))
P('filename-only date is still extracted',
  str(i2.get('extracted_date', '')).startswith('2015'), str(i2.get('extracted_date')))

p_both = TEST_DIR / 'photo_20200101.jpg'
make_img(p_both, 400, 300, exif_datetime='1999:12:31 23:59:59')
config.set('priorities.date_priority', 'oldest')
i3 = E.get_detailed_image_info(str(p_both))
P('both sources + oldest -> EXIF date wins',
  str(i3.get('extracted_date', '')).startswith('1999') and i3.get('date_source') == 'exif',
  '%s / %s' % (i3.get('extracted_date'), i3.get('date_source')))
config.set('priorities.date_priority', 'newest')
i4 = E.get_detailed_image_info(str(p_both))
P('both sources + newest -> filename date wins',
  str(i4.get('extracted_date', '')).startswith('2020') and i4.get('date_source') == 'filename',
  '%s / %s' % (i4.get('extracted_date'), i4.get('date_source')))
config.set('priorities.date_priority', 'oldest')

rep_dir = TEST_DIR / 'reports'
rep_dir.mkdir()
kept = str(p_exif)
dele = str(TEST_DIR / 'photo_20200101_copy.jpg')
make_img(Path(dele), 400, 300)
infos = {kept: E.get_detailed_image_info(kept),
         dele: E.get_detailed_image_info(dele)}
out = DuplicateReportGenerator(rep_dir).generate_duplicates_report_with_info(
    {kept: [kept, dele]}, [dele], infos)
txt = Path(out).read_text(encoding='utf-8', errors='replace')

P('the generated report renders a Date Source line', 'Date Source' in txt)
_ds_lines = [l.strip() for l in txt.splitlines() if 'Date Source' in l]
P('Date Source shows the VALUE, not literal f-string braces',
  bool(_ds_lines) and all('{' not in l and '}' not in l for l in _ds_lines),
  str(_ds_lines[:1]))
P("kept image's Date Source is exif in the real report",
  any(l.endswith('exif') for l in _ds_lines), str(_ds_lines))
P('the EXIF date itself appears in the report', '2001-05-04' in txt)
P('filename-importance denominator corrected to /9', '/9' in txt and '/10' not in txt)

_gens = ['src/utils/reports/duplicate_report_generator.py',
         'src/utils/reports/similarity_report_generator.py',
         'src/utils/reports/small_images_report_generator.py',
         'src/utils/reports/report_formatter.py']
_stale = [g for g in _gens if '/10' in read_src(g)]
P('no report module still prints the stale /10 denominator', not _stale, str(_stale))
P('image_info_extractor no longer calls extract_date_from_filename directly',
  'extract_date_from_filename' not in read_src('src/utils/reports/image_info_extractor.py'))


# =====================================================================
SEP('P2-18  one language default in every source')
# =====================================================================
P('config.py default is en', '"language": "en"' in read_src('src/core/config.py'))
P('config/settings.json is en',
  json.loads(read_src('config/settings.json'))['language'] == 'en')
P("main_cli.py fallback is en",
  "config.get('language', 'en')" in read_src('src/cli/main_cli.py'))
P('i18n_manager constructor default is en (the 4th source)',
  'self.current_language = "en"' in read_src('src/core/i18n/i18n_manager.py'))
P('no stale "ar" default remains in any of the four places',
  '"language": "ar"' not in read_src('src/core/config.py') and
  "config.get('language', 'ar')" not in read_src('src/cli/main_cli.py') and
  'self.current_language = "ar"' not in read_src('src/core/i18n/i18n_manager.py'))
P('a freshly rendered report comes out in English',
  'Duplicate Images Deletion Report' in txt)


# =====================================================================
SEP('P3-6  run.bat typos')
# =====================================================================
_bat = read_src('scripts/run.bat')
P("'newr' corrected to 'newer'", 'newr' not in _bat and 'newer' in _bat)
P("'runnig' corrected to 'running'", 'runnig' not in _bat and 'running' in _bat)


# =====================================================================
SEP('P0-1 regression  every priority permutation keeps the high-res image')
# =====================================================================
sel = FileSelector()
fx = TEST_DIR / 'p01'
fx.mkdir()
p_big = fx / 'IMG_0001.jpg'
p_mid = fx / 'photo.jpg'
p_tiny = fx / 'original.jpg'
make_img(p_big, 1200, 1200)
make_img(p_mid, 800, 800)
make_img(p_tiny, 100, 100)
files = [str(p_big), str(p_mid), str(p_tiny)]
BIGPX = 1200 * 1200


def _px(p):
    from PIL import Image
    with Image.open(p) as im:
        return im.width * im.height


PERMS = [[1, 2, 3, 4], [2, 3, 4, 1], [3, 4, 2, 1], [4, 3, 2, 1],
         [1, 1, 2, 1], [3, 4, 2, 2]]
results = []
for order in PERMS:
    config.set('priorities.order', order)
    try:
        k = sel.select_best_file(files)
    except Exception as e:
        k = 'RAISED ' + type(e).__name__
    ok_file = Path(k).exists()
    kpx = _px(k) if ok_file else -1
    results.append((order, Path(k).name if ok_file else k, kpx))
    log.info('      order=%-12s -> %-16s %8d px%s' %
             (str(order), Path(k).name if ok_file else k, kpx,
              '   HIGH-RES' if kpx == BIGPX else '   lower-res'))

bad = [r for r in results if r[2] != BIGPX]
P('all six permutations keep the high-resolution image', not bad,
  'offenders=' + str(bad) if bad else '6/6 kept 1200x1200')

unwarned = []
for order, name, kpx in results:
    if kpx != BIGPX:
        config.set('priorities.order', order)
        kf = [f for f in files if Path(f).name == name][0]
        if sel.detect_resolution_sacrifice(kf, files) is None:
            unwarned.append(order)
P('any lower-res keep would still be flagged as a sacrifice in the report',
  not unwarned, 'unwarned orders=' + str(unwarned))

P('duplicate ranks still fall back to the safe default',
  [r for r in results if r[0] in ([1, 1, 2, 1], [3, 4, 2, 2]) and r[2] != BIGPX] == [])

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
log.info('  Score: ' + ('%.1f%%' % pct) +
         ('  ALL PASS' if TF == 0 else '  >>> ' + str(TF) + ' need fixing <<<'))
log.info('')
log.info('Log: ' + str(LOG_FILE))

if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR, ignore_errors=True)

sys.exit(0 if TF == 0 else 1)
