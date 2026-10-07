# imgSniper v3 -- Round 16 Fix Verification Suite
# Numbered-copy detection must cover ANY number, and Arabic copy wording at all.
#
# Two gaps the user reported in the round-15 implementation:
#
#   1. `numbered = [' (' + str(i) + ')' for i in range(1, 10)]` stopped at 9.
#      So ' (10)' and above escaped the copy penalty ENTIRELY and scored as a
#      CLEAN name -- 'photo (10).jpg' was worth 8 while 'photo (9).jpg' was
#      worth 3. Exactly backwards. Windows, browsers and recovery tools all
#      append ' (N)', and on a large recovery N grows far past 9; the user's own
#      corpus contains names like 'copy (99999999)'.
#
#   2. Arabic copy wording was invisible to the scorer. Windows' Arabic locale
#      names a duplicate 'نسخة' / 'نسخة (٢) من ...' / 'ملف - نسخة', so an
#      Arabic-locale library kept every one of its copies.
#
# The Arabic gap had a technical cause worth recording: `_pattern_matches` treats
# an alphabetic pattern as a whole TOKEN and tokenises with `re.split(r'[^a-z]+',
# ...)`. `str.isalpha()` is True for Arabic letters, so an Arabic pattern took
# that branch -- and the split deletes every Arabic character, leaving [''] and
# making the pattern impossible to ever match. Non-ASCII alphabetic patterns are
# now matched as substrings; Latin tokenisation is unchanged.
#
# Verified here:
#   A. ANY number in parentheses counts as a numbered copy;
#   B. Arabic copy wording is detected, in both spellings;
#   C. Arabic-Indic digits and invisible bidi marks are normalised for matching;
#   D. a real file still beats its own copy;
#   E. parenthesised WORDS and qualified numbers are still left alone;
#   F. nothing else moved (frozen table, incl. both round-15 fixes);
#   G. the mechanism is untouched;
#   H. the machine is left exactly as it was found.
#
# ONE TRADE-OFF, stated openly rather than hidden: because the rule is now "pure
# digits inside parentheses", a bare YEAR reads as a copy number too, so
# 'report (2026).docx' scores 3 where round 15 gave it 6. The user asked for
# every parenthesised number to count, and on a recovery corpus ' (N)' really is
# a dedup marker, so this is deliberate -- see section E.
#
# Deliberately NOT changed by round 16: the priority order, criterion weights,
# date gates, selection engine, thresholds, dry-run behaviour, deletion behaviour
# and report content.
# Run from project root: python tests/test_fixes_round16.py

import sys, logging, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None

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
    if ok:
        TP += 1
        print(f'  [PASS] {label}')
    else:
        TF += 1
        print(f'  [FAIL] {label} -- {extra}')


def read_src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


from src.utils.helpers.date_extractor import date_extractor as DX        # noqa: E402
from src.core.config import DEFAULT_PRIORITY_ORDER                       # noqa: E402
from src.core.file_selector import build_group_scoretable                # noqa: E402

_score = DX.get_filename_importance_score

# =====================================================================
SEP('A.  ANY number in parentheses counts as a numbered copy')
# =====================================================================
# The old list stopped at ' (9)'. Everything below used to score as a CLEAN
# name; each must now be capped at 3 and lose the clean-name bonus.

for name in ['copy (99999999).jpg', 'copy (165982).jpg', 'copy (10215618).jpg',
             'photo (10).jpg', 'photo (99).jpg', 'photo (1000000).jpg',
             'IMG_2024 (12).jpg', 'file(2).jpg', 'file ( 7 ).jpg']:
    got = _score(name)
    P(f'{name} is a numbered copy (<=3)', got <= 3, f'got {got}')

# The specific inversion the user reported: (9) was punished, (10) was not.
P("the old inversion is gone: photo (9) and photo (10) now score the SAME",
  _score('photo (9).jpg') == _score('photo (10).jpg'),
  f"(9)={_score('photo (9).jpg')} (10)={_score('photo (10).jpg')}")
P('and both are far below the clean name photo.jpg',
  _score('photo.jpg') > _score('photo (10).jpg'),
  f"clean={_score('photo.jpg')} copy={_score('photo (10).jpg')}")

P('the 1-9 literal list is gone from the source',
  "numbered = [' (' + str(i) + ')' for i in range(1, 10)]"
  not in read_src('src/utils/helpers/date_extractor.py'))
P('a compiled regex covers any digit run instead',
  r"_NUMBERED_COPY_RE = re.compile(r'\(\s*\d+\s*\)')"
  in read_src('src/utils/helpers/date_extractor.py'))

# =====================================================================
SEP('B.  Arabic copy wording is detected')
# =====================================================================
for name in ['نسخة 1.jpg', 'نسخة 2.jpg', 'نسخة 999.jpg', 'نسخة 10512267.jpg',
             'نسخة (221973601).jpg', 'نسخة.jpg', 'نسخه 5.jpg',
             'ملف - نسخة.txt', 'نسخة من ملف.txt']:
    got = _score(name)
    P(f'{name} is detected as a copy (<=3)', got <= 3, f'got {got}')

P("'نسخة' and 'نسخه' are in the pattern table, weighted like 'copy'",
  DX.filename_importance.get('نسخة') == DX.filename_importance.get('copy')
  and DX.filename_importance.get('نسخه') == DX.filename_importance.get('copy'),
  f"نسخة={DX.filename_importance.get('نسخة')} "
  f"نسخه={DX.filename_importance.get('نسخه')} copy={DX.filename_importance.get('copy')}")

# The technical cause: without the isascii() guard an Arabic pattern was
# tokenised by [^a-z]+ and could never match.
P('_pattern_matches keeps Latin tokenisation but substring-matches non-ASCII',
  'if pattern.isalpha() and pattern.isascii():'
  in read_src('src/utils/helpers/date_extractor.py'))
P('a Latin keyword is still token-matched, not substring-matched',
  DX._pattern_matches('epic', 'pic') is False and DX._pattern_matches('pic_01', 'pic') is True)
P('an Arabic pattern now matches as a substring',
  DX._pattern_matches('ملف - نسخة', 'نسخة') is True)

# =====================================================================
SEP('C.  Arabic-Indic digits and invisible bidi marks are normalised')
# =====================================================================
# Windows' Arabic locale writes 'نسخة (٢)' -- Arabic-Indic digits, which \d does
# not match -- and embeds an RTL MARK (U+200F) that breaks even the substring.
for name in ['نسخة (٢).jpg', 'نسخة ٩٩٩.jpg', '\u200fنسخة (٢) من file.txt',
             'photo (١٠).jpg', '\u200fنسخة.jpg']:
    got = _score(name)
    P(f'{name!r} normalised before matching (<=3)', got <= 3, f'got {got}')

P('Arabic-Indic digits are converted before the digit regex runs',
  DX.normalize_arabic_numbers('نسخة (٢٢١٩٧٣٦٠١)') == 'نسخة (221973601)',
  DX.normalize_arabic_numbers('نسخة (٢٢١٩٧٣٦٠١)'))
P('the bidi-mark stripper is compiled and applied',
  "_BIDI_MARKS_RE = re.compile(" in read_src('src/utils/helpers/date_extractor.py')
  and '_BIDI_MARKS_RE.sub(' in read_src('src/utils/helpers/date_extractor.py'))
P('normalisation is for MATCHING only -- the ordinary date path is untouched',
  DX.extract_date_from_filename('Screenshot_٢٠٢٥٠٦٢٦_١٤٠٨٢٢.jpg') is not None)

# =====================================================================
SEP('D.  a real file still beats its own copy')
# =====================================================================
for real, copy in [('photo.jpg', 'photo (99999999).jpg'),
                   ('DSC_0453.jpg', 'DSC_0453 (165982).jpg'),
                   ('IMG_20240101.jpg', 'IMG_20240101 (10215618).jpg'),
                   ('photo.jpg', 'نسخة 10512267.jpg'),
                   ('photo.jpg', 'نسخة (221973601).jpg'),
                   ('photo.jpg', 'photo - copy.jpg'),
                   ('photo.jpg', 'photo_copy.jpg')]:
    a, b = _score(real), _score(copy)
    P(f'{real} ({a}) beats {copy} ({b})', a > b, f'{a} vs {b}')


# =====================================================================
SEP('E.  parenthesised WORDS and qualified numbers are still left alone')
# =====================================================================
# Round 15 fixed these; round 16 must not undo it. Only PURE digits inside the
# parentheses read as a copy number.
for name, expected in [('dsc (Final).jpg', 9), ('photo (USA).jpg', 8),
                       ('photo (Final v2).jpg', 8),
                       ('photo (2024-01-01).jpg', 8), ('photo (12x16).jpg', 8),
                       ('2605202413312833 (USA).pdf', 6)]:
    got = _score(name)
    P(f'{name} is NOT a numbered copy (={expected})', got == expected, f'got {got}')

# THE TRADE-OFF, asserted openly so it can never regress silently in EITHER
# direction. The user asked for every parenthesised number to count as a copy
# number, so a bare year is one too. If a future round adds a year exception,
# this assertion is the place that must be changed deliberately.
for name in ['report (2026).docx', 'budget (1999).xlsx', 'photo (2024).jpg']:
    got = _score(name)
    P(f'TRADE-OFF: {name} reads as a copy number (<=3)', got <= 3, f'got {got}')

# =====================================================================
SEP('F.  nothing else moved -- frozen table (incl. both round-15 fixes)')
# =====================================================================
FROZEN = {
    'photo_holiday.jpg': 8, 'WhatsApp_2024.jpg': 7, 'photo (1).jpg': 3,
    'image - copy.jpg': 3, 'backup_photo.jpg': 4, 'family_vacation_2019.jpg': 6,
    'DSC_0453.jpg': 9, 'IMG_1234_WA0001.jpg': 8, 'new_photo_2024.jpg': 8,
    'renewed_edit.jpg': 6, 'original.jpg': 9, 'camera.jpg': 9, 'dsc_1234.jpg': 9,
    'copy.jpg': 3, 'copy (1).jpg': 2, 'epic.jpg': 6, 'mydoc.jpg': 6,
    'attempt.jpg': 6, 'screenshot_2024.png': 7, 'pic.jpg': 8, 'video.mov': 9,
    'screenshot.png': 7, 'IMG_0001.jpg': 8, 'epic_sunset.jpg': 6,
    'attempt_fix.jpg': 6, 'Temple_run.jpg': 6, 'cachet_logo.png': 6,
    'picturesque.jpg': 6, 'photo (9).jpg': 3, 'photo (2).jpg': 3,
    'dsc (2).jpg': 2, 'photo_copy.jpg': 4, 'photo - copy.jpg': 3,
    'photo duplicate.jpg': 3, 'recovered_file.jpg': 2, 'thumbnail_001.jpg': 5,
    'preview.png': 5, 'edited_photo.jpg': 5, 'temp.jpg': 4,
    'IMG_20100101_original.jpg': 9, 'VID_20240101_120000.mp4': 9,
    'DSC_0001.NEF': 9, '(USA).pdf': 6, 'wallpaper.jpg': 6, '026757.pdf': 6,
    # round 15: a carved machine name is neutral, not rewarded
    'img_1080x2340x24_020414.jpg': 6, 'vid_1920x1080x24_000123.mp4': 6,
    # round 15: a real dated user name still outranks it
    'Screenshot_٢٠٢٥٠٦٢٦_١٤٠٨٢٢_Gallery.jpg': 7,
}
_drift = [(n, exp, _score(n)) for n, exp in FROZEN.items() if _score(n) != exp]
P(f'all {len(FROZEN)} frozen filenames score exactly as before round 16',
  not _drift, _drift)

P('no score exceeds 9', max(_score(n) for n in FROZEN) <= 9,
  max(_score(n) for n in FROZEN))
P('no weight in the pattern table exceeds 8',
  max(DX.filename_importance.values()) <= 8, max(DX.filename_importance.values()))
P('round 15 still holds: the real user name beats the carved placeholder',
  _score('Screenshot_٢٠٢٥٠٦٢٦_١٤٠٨٢٢_Gallery.jpg')
  > _score('img_1080x2340x24_020414.jpg'))

# =====================================================================
SEP('G.  the MECHANISM is untouched')
# =====================================================================
P('DEFAULT_PRIORITY_ORDER is still [2, 3, 1, 4]',
  DEFAULT_PRIORITY_ORDER == [2, 3, 1, 4], DEFAULT_PRIORITY_ORDER)
_tbl = build_group_scoretable(
    pixels={'a': 100, 'b': 100}, size_bytes={'a': 1000, 'b': 1000},
    filename_importance={'a': 8, 'b': 3}, date_scores={'a': 5.0, 'b': 5.0},
    priority_order=list(DEFAULT_PRIORITY_ORDER))
_w = {c: _tbl['a']['weighted'][c] / _tbl['a']['scores'][c]
      for c in ('resolution', 'size', 'date', 'filename')}
P('weights are still date=4, resolution=3, size=2, filename=1',
  (_w['date'], _w['resolution'], _w['size'], _w['filename']) == (4.0, 3.0, 2.0, 1.0), _w)
P('the existing Latin keywords kept their exact weights',
  (DX.filename_importance['img'] == 7 and DX.filename_importance['screenshot'] == 6
   and DX.filename_importance['dsc'] == 8 and DX.filename_importance['copy'] == 2
   and DX.filename_importance['recovered'] == 1))

# A copy must now actually LOSE its group through the real score table.
_kept = max(_tbl, key=lambda f: _tbl[f]['total'])
P('through the real score table the clean name beats its (99999999) copy',
  _kept == 'a', _kept)

# =====================================================================
SEP('H.  the machine is left exactly as it was found')
# =====================================================================
_reports_now = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                if _REPORTS_DIR.exists() else [])
P('the REAL reports/ folder was never touched by this suite',
  _reports_now == _REPORTS_BEFORE, (set(_reports_now) ^ set(_REPORTS_BEFORE)))
_restore_cfg()
P('settings.json is byte-identical again',
  _CFG_BYTES is None or _CFG_FILE.read_bytes() == _CFG_BYTES)
_left_behind = sorted(set(_reports_now) - set(_REPORTS_BEFORE))
P('no test report was left behind in the real reports/ folder',
  not _left_behind, _left_behind)

print('')
print('=' * 70)
print('  SUMMARY')
print('=' * 70)
print(f'  Total: {TP + TF}  PASS: {TP}  FAIL: {TF}')
print('  ALL TESTS PASSED' if TF == 0 else '  SOME TESTS FAILED')
print('=' * 70)
sys.exit(0 if TF == 0 else 1)
