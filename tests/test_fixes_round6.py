# imgSniper v3 -- Round 6 Fix Verification Suite
# RAW/HEIC codec round: files Pillow cannot decode are no longer excluded
# from the similarity scan SILENTLY, HEIC/HEIF works through pillow-heif,
# camera RAW through rawpy, and the corruption scan no longer brands
# undecodable-FORMAT files as "corrupted".
#   * central codec helper: open_image / open_image_with_reason /
#     read_dimensions / probe_image / can_decode_extension / codec_status
#   * similarity: RAW/HEIC hashed when the codec exists; excluded files are
#     counted, printed, logged by name and returned as 'total_excluded'
#   * corruption: decode without optional codec -> 'unsupported' (NOT
#     corrupted); with the codec -> strict verification as before
#   * .heic/.heif registered in every scanning format list
#   * i18n keys in both languages; requirements.txt/pyproject in sync
# Run from project root: python tests/test_fixes_round6.py

import sys, io, logging, shutil, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass

TP = TF = 0

# Expected log records (e.g. the corruption-scan 'unsupported' warning) must
# not hit stderr: without a handler the root logger's lastResort prints them
# raw, which a CI pipeline redirecting stderr would treat as an error.
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


import numpy as np                                                   # noqa: E402
import imagehash                                                     # noqa: E402
from PIL import Image                                                # noqa: E402
from rich.console import Console                                     # noqa: E402

from src.utils.helpers import image_codec                            # noqa: E402
from src.utils.helpers.image_codec import (                          # noqa: E402
    can_decode_extension, codec_status, open_image,
    open_image_with_reason, probe_image, read_dimensions,
)
from src.core.detectors.similarity_detector import SimilarityDetector          # noqa: E402
from src.core.detectors.duplicate_detector import DuplicateDetector            # noqa: E402
from src.core.detectors.corruption_detector import (                           # noqa: E402
    CorruptionDetector, _check_image_corruption_worker,
)
from src.core.detectors.similarity_hash_calculator import (                    # noqa: E402
    _calculate_perceptual_hash_worker,
)
from src.core.image_analyzer import (                                          # noqa: E402
    ImageAnalyzer, _analyze_image_dimensions_worker,
)
from src.utils.reports.image_info_extractor import ImageInfoExtractor          # noqa: E402
from src.utils.reports.report_formatter import ReportFormatter                 # noqa: E402
from src.core.i18n.i18n import i18n                                            # noqa: E402
from src.core.i18n.translations_english import ENGLISH_TRANSLATIONS            # noqa: E402
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS              # noqa: E402

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_round6_'))


def _write_png(path, seed):
    rng = np.random.RandomState(seed)
    Image.fromarray(rng.randint(0, 256, (64, 64, 3), dtype=np.uint8)).save(str(path))


def _save_heic(image, path):
    try:
        image.save(str(path), format='HEIF', quality=90)
        return True
    except Exception:
        pass
    try:
        import pillow_heif
        pillow_heif.from_pil(image).save(str(path), quality=90)
        return True
    except Exception:
        return False


def _console():
    return Console(file=io.StringIO(), force_terminal=False, width=120)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _capture_logging():
    handler = _Capture()
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    return handler, root, old_level


def _ascii(text):
    """Strip non-ASCII (emoji) so StringIO consoles (which render '??') match."""
    return ''.join(ch for ch in text if ord(ch) < 128)


def _flat(text):
    """Emoji-strip + whitespace-normalize (rich soft-wraps long console lines)."""
    return ' '.join(_ascii(text).split())


SEP('1) central codec helper (image_codec)')

status = codec_status()
P('codec_status returns {heif, raw} booleans',
  set(status) == {'heif', 'raw'} and all(isinstance(v, bool) for v in status.values()),
  status)

png = TEST_DIR / 'base.png'
_write_png(png, 1)

img = open_image(png)
P('open_image() decodes a PNG fully',
  img is not None and img.size == (64, 64) and getattr(img, 'format', None) == 'PNG',
  None if img is None else (img.size, img.format))
if img is not None:
    img.close()

P('read_dimensions() reads the PNG header', read_dimensions(png) == (64, 64))
probed = probe_image(png)
P('probe_image() reports size/format/mode',
  probed == {'width': 64, 'height': 64, 'format': 'PNG', 'mode': 'RGB'}, probed)

missing = TEST_DIR / 'does_not_exist.png'
img, reason = open_image_with_reason(missing)
P('missing file -> (None, decode_error)',
  img is None and reason == 'decode_error', reason)

broken_png = TEST_DIR / 'broken.png'
broken_png.write_bytes(b'this is not an image at all, just bytes')
img, reason = open_image_with_reason(broken_png)
P('broken PNG -> (None, decode_error)',
  img is None and reason == 'decode_error', reason)

fake_raw = TEST_DIR / 'photo.cr2'
fake_raw.write_bytes(b'FAKE-RAW-' + b'x' * 2048)
expected_raw = 'decode_error' if status['raw'] else 'missing_codec'
img, reason = open_image_with_reason(fake_raw)
P('fake .cr2 -> (None, %s)' % expected_raw,
  img is None and reason == expected_raw, reason)
P('read_dimensions() on fake .cr2 -> None', read_dimensions(fake_raw) is None)
P('probe_image() on fake .cr2 -> None', probe_image(fake_raw) is None)

saved_raw = image_codec._RAWPY_AVAILABLE
image_codec._RAWPY_AVAILABLE = False
try:
    img, reason = open_image_with_reason(fake_raw)
finally:
    image_codec._RAWPY_AVAILABLE = saved_raw
P('fake .cr2 without rawpy -> missing_codec',
  img is None and reason == 'missing_codec', reason)

fake_heic = TEST_DIR / 'photo.heic'
fake_heic.write_bytes(b'FAKE-HEIC-' + b'y' * 2048)
expected_heic = 'decode_error' if status['heif'] else 'missing_codec'
img, reason = open_image_with_reason(fake_heic)
P('fake .heic -> (None, %s)' % expected_heic,
  img is None and reason == expected_heic, reason)

saved_heif = image_codec._HEIF_AVAILABLE
image_codec._HEIF_AVAILABLE = False
try:
    img, reason = open_image_with_reason(fake_heic)
finally:
    image_codec._HEIF_AVAILABLE = saved_heif
P('fake .heic without pillow-heif -> missing_codec',
  img is None and reason == 'missing_codec', reason)

P('can_decode_extension mirrors codec_status',
  can_decode_extension('.heic') == status['heif'] and
  can_decode_extension('.cr2') == status['raw'] and
  can_decode_extension('.jpg') is True)


SEP('2) HEIC support when pillow-heif is installed')

heic_path = TEST_DIR / 'real.heic'
heic_ok = False
if status['heif']:
    source = Image.fromarray(
        np.random.RandomState(5).randint(0, 256, (64, 64, 3), dtype=np.uint8))
    heic_ok = _save_heic(source, heic_path) and heic_path.exists()
if heic_ok:
    img = open_image(heic_path)
    P('open_image() decodes a real HEIC',
      img is not None and img.size == (64, 64),
      None if img is None else img.size)
    if img is not None:
        img.close()
    P('read_dimensions() reads the HEIC header', read_dimensions(heic_path) == (64, 64))
    probed = probe_image(heic_path)
    P('probe_image() labels the HEIC container',
      probed is not None and str(probed['format']).upper().startswith('HEIF'), probed)
    _, ph, dh = _calculate_perceptual_hash_worker(str(heic_path))
    P('HEIC is hashed by the similarity worker', ph is not None and dh is not None)
    _, dims = _analyze_image_dimensions_worker(str(heic_path), 300, 300)
    P('small-image scan reads HEIC dimensions', dims == (64, 64, True), dims)
    heic_info = ImageInfoExtractor().get_detailed_image_info(str(heic_path))
    P('report info extractor reads HEIC size/format',
      heic_info.get('width') == 64 and heic_info.get('height') == 64 and
      str(heic_info.get('format', '')).upper().startswith('HEIF'),
      (heic_info.get('width'), heic_info.get('format')))
else:
    print('  [SKIP] HEIC round-trip -- pillow-heif missing or cannot encode')

SEP('3) similarity hash worker: codec path + excluded failures')

_, ph, dh = _calculate_perceptual_hash_worker(str(png))
P('PNG still hashed (regression)', ph is not None and dh is not None)
_, ph, dh = _calculate_perceptual_hash_worker(str(fake_raw))
P('unreadable RAW yields no hashes (excluded, no crash)', ph is None and dh is None)
_, ph, dh = _calculate_perceptual_hash_worker(str(TEST_DIR / 'ghost.png'))
P('missing file yields no hashes (excluded, no crash)', ph is None and dh is None)

SEP('4) similarity scan: exclusions are printed and logged')

detector = SimilarityDetector()
console = _console()
good_hash = imagehash.phash(Image.open(str(png)))
handler, root, old_level = _capture_logging()
try:
    excluded = detector._report_unhashed_images(
        [str(png), str(fake_raw)], {str(png): good_hash}, console)
finally:
    root.removeHandler(handler)
    root.setLevel(old_level)
output = console.file.getvalue()
P('returns the excluded count', excluded == 1, excluded)
P('prints the skip warning',
  _flat(i18n.get('common.images_skipped_unreadable').format(1)) in _flat(output),
  output[:160])
P('logs the excluded file name by name',
  any('photo.cr2' in m for m in handler.messages), handler.messages)
P('no warning when nothing is excluded',
  detector._report_unhashed_images([str(png)], {str(png): good_hash}, _console()) == 0)

SEP('5) .heic/.heif registered in every scanning format list')

for cls in (SimilarityDetector, DuplicateDetector, CorruptionDetector, ImageAnalyzer):
    instance = cls()
    P('%s supports .heic/.heif' % cls.__name__,
      {'.heic', '.heif'} <= instance.supported_formats,
      sorted(instance.supported_formats & {'.heic', '.heif'}))

SEP('6) end-to-end similar scan: exclusion visible, PNGs still grouped')

folder = TEST_DIR / 'mix'
folder.mkdir()
a = folder / 'a.png'
b = folder / 'b.png'
c = folder / 'c.png'
_write_png(a, 11)
shutil.copyfile(str(a), str(b))
_write_png(c, 12)
raw_in_folder = folder / 'camera.cr2'
raw_in_folder.write_bytes(b'FAKE-RAW-' + b'z' * 2048)

console = _console()
handler, root, old_level = _capture_logging()
try:
    result = detector.find_similar_images([str(folder)], console)
finally:
    root.removeHandler(handler)
    root.setLevel(old_level)
output = console.file.getvalue()

P('scan sees all 4 candidates (RAW included, then excluded visibly)',
  result is not None and result['total_scanned'] == 4,
  None if result is None else result['total_scanned'])
P('exactly one excluded image is reported',
  result.get('total_excluded') == 1, result.get('total_excluded'))
P('identical PNGs form one group',
  result['total_groups'] == 1 and
  sorted(result['similar_groups'][0]) == sorted([str(a), str(b)]),
  result['similar_groups'])
P('exclusion warning visible in the scan output',
  _flat(i18n.get('common.images_skipped_unreadable').format(1)) in _flat(output))
P('excluded file logged by name', any('camera.cr2' in m for m in handler.messages))

SEP('7) corruption scan: a missing codec is NOT corruption')

empty = TEST_DIR / 'empty.png'
empty.write_bytes(b'')
tiny = TEST_DIR / 'tiny.png'
tiny.write_bytes(b'12345')

_, verdict = _check_image_corruption_worker(str(empty))
P('empty file -> corrupted', verdict is True, verdict)
_, verdict = _check_image_corruption_worker(str(tiny))
P('files under 50 bytes -> corrupted', verdict is True, verdict)
_, verdict = _check_image_corruption_worker(str(a))
P('healthy PNG -> not corrupted', verdict is False, verdict)

expected_garbage = True if status['raw'] else 'unsupported'
_, verdict = _check_image_corruption_worker(str(raw_in_folder))
P('garbage .cr2 with rawpy -> corrupted, without -> unsupported',
  verdict == expected_garbage, (verdict, expected_garbage))

saved_raw = image_codec._RAWPY_AVAILABLE
image_codec._RAWPY_AVAILABLE = False
try:
    _, verdict = _check_image_corruption_worker(str(raw_in_folder))
finally:
    image_codec._RAWPY_AVAILABLE = saved_raw
P('garbage .cr2 without rawpy -> unsupported (previously: corrupted!)',
  verdict == 'unsupported', verdict)

corruption_detector = CorruptionDetector()
console = _console()
saved_raw = image_codec._RAWPY_AVAILABLE
image_codec._RAWPY_AVAILABLE = False
try:
    corruption_result = corruption_detector.find_corrupted_images([str(folder)], console)
finally:
    image_codec._RAWPY_AVAILABLE = saved_raw
P('no healthy file is flagged as corrupted',
  corruption_result['corrupted_files'] == [], corruption_result['corrupted_files'])
P('the codec-less RAW lands in unsupported_files',
  str(raw_in_folder) in corruption_result['unsupported_files'],
  corruption_result['unsupported_files'])
P('unsupported notice printed instead of a false corrupted count',
  _flat(i18n.get('common.unsupported_codec_skipped').format(1)) in _flat(console.file.getvalue()))

SEP('8) reports: real similarity percentage for codec-decoded files')

percentage = ReportFormatter().calculate_similarity_percentage(str(a), str(b), None, None)
P('identical PNGs -> ~100% via the codec helper',
  isinstance(percentage, float) and percentage >= 99.0, percentage)

SEP('9) i18n keys, packaging sync, no direct Image.open left')

expected_placeholders = {
    'images_skipped_unreadable': 1,
    'install_codec_hint': 0,
    'unsupported_codec_skipped': 1,
}
for key, count in expected_placeholders.items():
    en = ENGLISH_TRANSLATIONS.get('common', {}).get(key, '')
    ar = ARABIC_TRANSLATIONS.get('common', {}).get(key, '')
    P('common.%s present in EN/AR with %d placeholder(s)' % (key, count),
      bool(en) and bool(ar) and en.count('{}') == count and ar.count('{}') == count,
      (en[:70], ar[:70]))

requirements_text = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
pyproject_text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
P('requirements.txt lists the optional codecs',
  'pillow-heif' in requirements_text and 'rawpy' in requirements_text)
P('pyproject.toml lists the optional codecs',
  'pillow-heif' in pyproject_text and 'rawpy' in pyproject_text)

for rel in ('src/core/detectors/similarity_hash_calculator.py',
            'src/core/detectors/corruption_detector.py',
            'src/core/file_selector.py',
            'src/core/image_analyzer.py',
            'src/utils/reports/image_info_extractor.py',
            'src/utils/reports/report_formatter.py'):
    text = (ROOT / rel).read_text(encoding='utf-8')
    P('%s no longer calls Image.open directly' % rel.split('/')[-1],
      'Image.open' not in text)

# ---- cleanup ---------------------------------------------------------------
shutil.rmtree(TEST_DIR, ignore_errors=True)

SEP('ROUND 6 SUMMARY')
print('  passed: %d' % TP)
print('  failed: %d' % TF)
print('  total : %d' % (TP + TF))
print('')
print('  RESULT: ' + ('FAIL' if TF else 'ALL PASS'))
sys.exit(1 if TF else 0)
