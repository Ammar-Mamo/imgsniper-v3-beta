# imgSniper v3 -- Round 5 Fix Verification Suite
# Covers the errors&comments.txt findings:
#   * #1126  dHash secondary guard: identical UI/screenshot templates with
#            different content must NOT group as similar (phash8 distance
#            0-8 was accepted alone); true duplicates must still group.
#   * #7/#15 score-capped reasons: 7.76 vs 7.77 MB (both at the 5MB cap)
#            must not report "Larger/Smaller file size"; a real sub-cap
#            difference must still report it.
#   * #18/#25/#535 honest tie labels: no invented "shorter filename" /
#            "alphabetical order" / false "Recovered/backup image".
#   * #14/#239 filename dates are day-precision: same-day gaps against EXIF
#            must not report "older extracted date"; reports annotate
#            "(date only)".
#   * #1124 deletion reason uses the merged dates (was filename-only).
#   * PIL "Corrupt EXIF data" warnings are routed to logging, not stderr.
# Run from project root: python tests/test_fixes_round5.py

import sys, io, json, tempfile, shutil, logging, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass

TP = TF = 0


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


from src.core.config import config                                   # noqa: E402
from src.core.i18n.i18n import i18n                                  # noqa: E402
from src.core.file_selector import (                                 # noqa: E402
    compute_size_score, compute_resolution_score,
)
from src.core.detectors.similarity_group_finder import (             # noqa: E402
    SimilarityGroupFinder, _compare_hash_batch_worker,
)
from src.core.detectors.similarity_hash_calculator import (          # noqa: E402
    SimilarityHashCalculator, _calculate_perceptual_hash_worker,
)
from src.utils.reports.report_formatter import ReportFormatter       # noqa: E402
from src.utils.reports.image_info_extractor import (                 # noqa: E402
    ImageInfoExtractor, format_extracted_date,
)
import imagehash                                                     # noqa: E402
import numpy                                                         # noqa: E402
from PIL import Image                                                # noqa: E402
from rich.console import Console                                     # noqa: E402

_cfg_backup = json.loads(json.dumps(config.config))
_lang_backup = i18n.current_language

# Deterministic environment for the assertions below.
config.config.setdefault('priorities', {})
config.config['priorities']['order'] = [1, 2, 3, 4]
config.config['priorities']['date_priority'] = 'oldest'
# NOTE: 'date' deliberately excluded -- priorities.date_priority holds the
# STRING 'oldest'/'newest' (it doubles as the date enable flag); setting it
# to True here would silently disable the date criterion.
for _crit in ('resolution', 'size', 'filename'):
    config.config['priorities'][f'{_crit}_priority'] = True
config.config.setdefault('processing', {})['phash_threshold'] = 5
i18n.set_language('en')

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_r5_'))
print('Test dir: ' + str(TEST_DIR))

SEP('1) dHash secondary guard -- synthetic hashes (#1126)')


def H(hexstr):
    # Build a REAL ImageHash: this imagehash version stores whatever it is
    # given, and its arithmetic needs a (hash_size, hash_size) bit array --
    # exactly what phash()/dhash() pass internally.
    bits = numpy.unpackbits(numpy.frombuffer(bytes.fromhex(hexstr), dtype=numpy.uint8))
    return imagehash.ImageHash(bits.reshape((8, 8)))


# phash distance 4 (<= threshold 5): the pre-fix pipeline grouped this pair.
ph_a, ph_b = H('0000000000000000'), H('000000000000000f')
# dhash distance 11 (> 5): different local structure (different text).
dh_a, dh_b = H('0000000000000000'), H('00000000000007ff')
# dhash distance 1: a genuine duplicate.
dh_dup = H('0000000000000001')

finder = SimilarityGroupFinder()
hashes = {'a.jpg': ph_a, 'b.jpg': ph_b}

groups_old = finder.find_similar_groups(dict(hashes), None)
P('template-like pair still groups WITHOUT secondary (old behaviour kept)',
  len(groups_old) == 1, groups_old)

groups_new = finder.find_similar_groups(
    dict(hashes), None, secondary_hashes={'a.jpg': dh_a, 'b.jpg': dh_b})
P('template-like pair NOT grouped WITH dHash guard (#1126 fixed)',
  groups_new == [], groups_new)

groups_dup = finder.find_similar_groups(
    dict(hashes), None, secondary_hashes={'a.jpg': dh_a, 'b.jpg': dh_dup})
P('true duplicate still grouped with dHash guard',
  len(groups_dup) == 1 and sorted(groups_dup[0]) == ['a.jpg', 'b.jpg'], groups_dup)

groups_missing = finder.find_similar_groups(
    dict(hashes), None, secondary_hashes={'a.jpg': dh_a})
P('file missing its dHash is excluded (conservative, never deleted)',
  groups_missing == [], groups_missing)

m_old = _compare_hash_batch_worker(
    ([('a.jpg', ph_a)], [('a.jpg', ph_a), ('b.jpg', ph_b)], 5, 0))
P('parallel worker unchanged for 2-tuples', m_old == [('a.jpg', 'b.jpg')], m_old)

m_guard = _compare_hash_batch_worker(
    ([('a.jpg', ph_a, dh_a)], [('a.jpg', ph_a, dh_a), ('b.jpg', ph_b, dh_b)], 5, 0))
P('parallel worker applies AND guard', m_guard == [], m_guard)

m_dup = _compare_hash_batch_worker(
    ([('a.jpg', ph_a, dh_a)], [('a.jpg', ph_a, dh_a), ('b.jpg', ph_b, dh_dup)], 5, 0))
P('parallel worker accepts agreeing pair', m_dup == [('a.jpg', 'b.jpg')], m_dup)

seq = finder._find_similar_groups_sequential(
    [('a.jpg', ph_a, dh_a), ('b.jpg', ph_b, dh_b)], 5, None)
P('sequential path applies AND guard', seq == [], seq)

seq2 = finder._find_similar_groups_sequential(
    [('a.jpg', ph_a), ('b.jpg', ph_b)], 5, None)
P('sequential path backwards compatible (2-tuples)', len(seq2) == 1, seq2)

SEP('2) dual hash calculation on real images')

img1 = Image.new('RGB', (64, 64), (200, 30, 30))
p1 = str(TEST_DIR / 'solid1.jpg')
p2 = str(TEST_DIR / 'solid2.jpg')
p3 = str(TEST_DIR / 'noise.jpg')
img1.save(p1, 'JPEG')
img1.save(p2, 'JPEG', quality=80)
Image.effect_noise((64, 64), 96).convert('RGB').save(p3, 'JPEG')

w_path, w_ph, w_dh = _calculate_perceptual_hash_worker(p1)
P('worker returns (path, phash, dhash)',
  w_path == p1 and w_ph is not None and w_dh is not None)

missing = str(TEST_DIR / 'missing.jpg')
P('worker failure returns 3-tuple with Nones',
  _calculate_perceptual_hash_worker(missing) == (missing, None, None))

console = Console(file=io.StringIO(), width=80, force_terminal=False)
calc = SimilarityHashCalculator()
phashes, dhashes = calc.calculate_image_hashes_dual([p1, p2, p3], console)
P('dual dicts aligned', set(phashes) == set(dhashes) == {p1, p2, p3},
  (sorted(phashes), sorted(dhashes)))
P('identical images: both distances small',
  (phashes[p1] - phashes[p2]) <= 2 and (dhashes[p1] - dhashes[p2]) <= 2,
  (phashes[p1] - phashes[p2], dhashes[p1] - dhashes[p2]))
P('different images: dhash separates', (dhashes[p1] - dhashes[p3]) > 5,
  dhashes[p1] - dhashes[p3])

wrapper = calc.calculate_image_hashes([p1], console)
P('calculate_image_hashes wrapper still returns phash-only dict',
  set(wrapper) == {p1} and all(not isinstance(v, tuple) for v in wrapper.values()))

SEP('3) score caps and capped-tie reasons (#7/#15)')

P('size score caps at 5MB', compute_size_score(7.76) == 10.0 == compute_size_score(7.77))
P('size score differs below cap', compute_size_score(4.63) != compute_size_score(4.31))
P('resolution score caps at 10MP', compute_resolution_score(6240 * 4160) == 10.0)

fmt = ReportFormatter()
MB = 1024 * 1024


def info(size_mb, res, w, h, date, source, imp, extra_bytes=0):
    return {
        'size_bytes': int(size_mb * MB) + extra_bytes,
        'size_mb': size_mb,
        'resolution': res, 'width': w, 'height': h,
        'extracted_date': date, 'date_source': source,
        'filename_importance': imp,
    }


# #7: 7.76 vs 7.77 MB, same 25.9MP resolution, identical EXIF second.
k7 = info(7.76, 6240 * 4160, 6240, 4160, '2024-07-04 21:50:51', 'exif', 2)
d7 = info(7.77, 6240 * 4160, 6240, 4160, '2024-07-04 21:50:51', 'exif', 2, extra_bytes=10240)
infos7 = {'k.jpg': k7, 'd.jpg': d7}

P('_check_size_reason suppressed on capped tie',
  fmt._check_size_reason('k.jpg', ['d.jpg'], k7, infos7) is None)

dr7 = fmt.get_deletion_reason('d.jpg', 'k.jpg', infos7)
P('#7 deletion reason no longer claims Larger/Smaller file size',
  'Larger' not in dr7 and 'Smaller' not in dr7, dr7)
P('#7 deletion reason is the honest tie label',
  'No decisive difference' in dr7, dr7)

sr7 = fmt.get_detailed_selection_reason('k.jpg', ['k.jpg', 'd.jpg'], infos7)
P('#7 selection reason is honest too (no invented size story)',
  'No decisive difference' in sr7 and 'alphabetical' not in sr7, sr7.splitlines()[0])

# #15: 4.63 vs 4.31 MB below the cap -- the size label MUST remain.
k15 = info(4.63, 4000 * 3000, 4000, 3000, '2023-05-21 19:30:28', 'exif', 2)
d15 = info(4.31, 4000 * 3000, 4000, 3000, '2023-05-21 19:30:29', 'exif', 2)
infos15 = {'k.jpg': k15, 'd.jpg': d15}
dr15 = fmt.get_deletion_reason('d.jpg', 'k.jpg', infos15)
P('#15 real sub-cap difference still reports Smaller file size',
  dr15 == 'Smaller file size', dr15)
sr15 = fmt.get_detailed_selection_reason('k.jpg', ['k.jpg', 'd.jpg'], infos15)
P('#15 selection reason still reports larger file size',
  'larger file size' in sr15, sr15.splitlines()[0])

SEP('4) honest tie labels (#18/#25/#535)')

# #535: img_* names, identical metrics, no dates -> deletion fallback.
k535 = info(0.04, 471 * 1020, 471, 1020, 'Unknown', 'none', 8)
d535 = info(0.04, 471 * 1020, 471, 1020, 'Unknown', 'none', 8)
infos535 = {'img_471x1020x24_029100.jpg': k535, 'img_471x1020x24_029122.jpg': d535}
dr535 = fmt.get_deletion_reason(
    'img_471x1020x24_029122.jpg', 'img_471x1020x24_029100.jpg', infos535)
P('#535 deletion reason no longer claims Recovered/backup',
  'Recovered' not in dr535 and 'No decisive difference' in dr535, dr535)

# #18: identical pair -> selection fallback.
k18 = info(0.09, 810 * 1080, 810, 1080, 'Unknown', 'none', 2)
d18 = info(0.09, 810 * 1080, 810, 1080, 'Unknown', 'none', 2)
infos18 = {'Recovered_jpg_file(168).jpg': k18, 'Recovered_jpg_file(4872).jpg': d18}
sr18 = fmt.get_detailed_selection_reason(
    'Recovered_jpg_file(168).jpg',
    ['Recovered_jpg_file(168).jpg', 'Recovered_jpg_file(4872).jpg'], infos18)
P('#18 selection reason no longer invents shorter filename/alphabetical',
  'shorter filename' not in sr18 and 'alphabetical' not in sr18
  and 'No decisive difference' in sr18, sr18.splitlines()[0])

err_reason = fmt.get_deletion_reason('x.jpg', 'k.jpg', {'x.jpg': {'error': 'boom'}})
P('unreadable file reports undetermined, not Recovered/backup',
  'Could not determine reason' in err_reason and 'Recovered' not in err_reason,
  err_reason)

# A genuine "recovered" name still gets the keyword label (kept behaviour).
infos_kw = {'k.jpg': k535, 'Recovered_jpg_file(979).jpg': d535}
dr_kw = fmt.get_deletion_reason('Recovered_jpg_file(979).jpg', 'k.jpg', infos_kw)
P('recovered-named file still labelled Recovered/backup image',
  dr_kw == 'Recovered/backup image', dr_kw)

SEP('5) day-precision filename dates (#14/#239/#1124)')

k14 = info(0.9, 2560 * 1536, 2560, 1536, '2022-07-20 00:00:00', 'filename', 6)
d14 = info(0.9, 2560 * 1536, 2560, 1536, '2022-07-20 16:42:06', 'exif', 2)
infos14 = {'samsung.jpg': k14, 'Recovered_jpg_file(979).jpg': d14}
sr14 = fmt.get_detailed_selection_reason(
    'samsung.jpg', ['samsung.jpg', 'Recovered_jpg_file(979).jpg'], infos14)
P('#14 same-day filename-vs-EXIF no longer reports older extracted date',
  'older extracted date' not in sr14, sr14.splitlines()[0])
P('#14 falls through to filename importance (the honest criterion)',
  'better filename importance' in sr14, sr14.splitlines()[0])

k1124 = info(1.36, 1080 * 2340, 1080, 2340, '2025-04-25 04:21:34', 'exif', 8)
d1124 = info(1.36, 1080 * 2340, 1080, 2340, '2025-05-25 23:32:21', 'exif', 8)
infos1124 = {'k.jpg': k1124, 'd.jpg': d1124}
sr1124 = fmt.get_detailed_selection_reason('k.jpg', ['k.jpg', 'd.jpg'], infos1124)
P('#1124 genuine month-apart EXIF dates still report older extracted date',
  'older extracted date' in sr1124, sr1124.splitlines()[0])
dr1124 = fmt.get_deletion_reason('d.jpg', 'k.jpg', infos1124)
P('#1124 deletion reason now uses merged dates -> Newer date',
  dr1124 == 'Newer date', dr1124)

# Same-day gap between two EXIF timestamps stays reportable (real difference).
k_ex = info(1.0, 1000 * 1000, 1000, 1000, '2023-05-21 19:30:28', 'exif', 5)
d_ex = info(1.0, 1000 * 1000, 1000, 1000, '2023-05-21 19:30:29', 'exif', 5)
infos_ex = {'k.jpg': k_ex, 'd.jpg': d_ex}
dr_ex = fmt.get_deletion_reason('d.jpg', 'k.jpg', infos_ex)
P('same-day EXIF-vs-EXIF gap still reportable as Newer date',
  dr_ex == 'Newer date', dr_ex)

SEP('6) date-only annotation in image info (#14)')

named = str(TEST_DIR / 'photo_20220720.jpg')
Image.new('RGB', (32, 32), (10, 120, 200)).save(named, 'JPEG')
plain = str(TEST_DIR / 'plain.jpg')
Image.new('RGB', (32, 32), (10, 120, 200)).save(plain, 'JPEG')

extractor = ImageInfoExtractor()
info_named = extractor.get_detailed_image_info(named)
info_plain = extractor.get_detailed_image_info(plain)
P('filename date flagged date_only',
  info_named.get('date_only') is True and
  info_named.get('extracted_date') == '2022-07-20 00:00:00',
  info_named.get('extracted_date'))
P('format_extracted_date annotates day precision',
  '(date only' in format_extracted_date(info_named),
  format_extracted_date(info_named))
P('no annotation without a filename date',
  info_plain.get('date_only') is False and
  format_extracted_date(info_plain) == 'Unknown')

SEP('7) PIL corrupt-EXIF warnings routed to logging')

from src.utils.helpers.logging_setup import setup_logging             # noqa: E402

setup_logging()
P('captureWarnings active after setup_logging',
  getattr(warnings.showwarning, '__module__', '') == 'logging',
  warnings.showwarning)

_captured = []


class _Cap(logging.Handler):
    def emit(self, record):
        _captured.append(record.getMessage())


_pyw = logging.getLogger('py.warnings')
_h = _Cap()
_pyw.addHandler(_h)
try:
    with warnings.catch_warnings():
        warnings.simplefilter('always')
        warnings.warn('Corrupt EXIF data.  Expecting to read 12 bytes but only got 3.')
finally:
    _pyw.removeHandler(_h)
P('corrupt-EXIF warning lands in logging instead of stderr',
  any('Corrupt EXIF data' in m for m in _captured), _captured)

SEP('8) i18n keys present in both languages')

i18n.set_language('en')
P('EN reason_no_difference', i18n.get('reports.reason_no_difference') ==
  'No decisive difference in weighted criteria (tie broken by scan order)')
P('EN reason_undetermined',
  not str(i18n.get('reports.reason_undetermined')).startswith('[Missing'))
P('EN date_only_suffix',
  not str(i18n.get('reports.date_only_suffix')).startswith('[Missing'))
i18n.set_language('ar')
P('AR reason_no_difference',
  'لا فرق حاسم' in i18n.get('reports.reason_no_difference'))
P('AR reason_undetermined',
  'تعذر تحديد السبب' in i18n.get('reports.reason_undetermined'))
P('AR date_only_suffix', 'اليوم فقط' in i18n.get('reports.date_only_suffix'))

# ---- restore ---------------------------------------------------------------
i18n.set_language(_lang_backup)
config.config = json.loads(json.dumps(_cfg_backup))
shutil.rmtree(TEST_DIR, ignore_errors=True)

SEP('ROUND 5 SUMMARY')
print('  passed: %d' % TP)
print('  failed: %d' % TF)
print('  total : %d' % (TP + TF))
print('')
print('  RESULT: ' + ('FAIL' if TF else 'ALL PASS'))
sys.exit(1 if TF else 0)



