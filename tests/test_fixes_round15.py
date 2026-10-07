# imgSniper v3 -- Round 15 Fix Verification Suite
# Two defects in the FILENAME IMPORTANCE input -- not in the selection mechanism.
#
# What the forensic review of the user's real reports (68 MB: a 34 MB similar
# report and a 26 MB duplicates report, 24 517 + 23 666 groups) proved:
#
#   * 12 645 deletions in the similar report shared ONE decision shape:
#         KEPT  img_1080x2340x24_020414.jpg        importance 8/9
#         DEL   Screenshot_<date>_<app>.jpg        importance 7/9
#         reason: "filename importance (kept: 8/9 - this file: 7/9)"
#     The kept file is R-Studio's RAW-CARVED placeholder name -- machine
#     generated, carrying no information at all. The deleted file was a real
#     user name whose Arabic-Indic digits encode the true capture date
#     (extracted correctly: 2025-06-26). The tool kept the nameless carve.
#
#   * the office report showed a group decided "kept 6/9 - this file 4/9" where
#     the 4/9 side lost purely because its name contained " (USA)".
#
# Both trace to get_filename_importance_score(), and NEITHER is a mechanism
# problem. The user's priority order (date > resolution > size > filename,
# weights 4/3/2/1) was honoured exactly: filename decided only because date was
# neutralised by the round-7 filename-precision gate, resolution was equal and
# size was inside the no-decision threshold. Filename was simply the last
# criterion still able to speak -- and its INPUT VALUES were wrong.
#
# Verified here:
#   A. a parenthesised WORD is no longer punished as a numbered copy;
#   B. a carved machine name earns no keyword reward (neutral, not punitive);
#   C. every other filename keeps the EXACT score it had before (frozen table);
#   D. the mechanism is untouched -- order, weights, gates, pattern table;
#   E. the decision this actually changes, end to end through the score table;
#   F. the machine is left exactly as it was found.
#
# Deliberately NOT changed by round 15: the priority order, the criterion
# weights, the date gates, the filename_importance pattern table, the selection
# engine, thresholds, dry-run behaviour, deletion behaviour and report content.
# Run from project root: python tests/test_fixes_round15.py

import sys, logging, atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None

# The reports folder holds the USER's real reports. "Did this suite write one?"
# can only be answered by comparing a BEFORE snapshot with the state at the end
# -- never by looking at what the folder happens to contain (round 15 also fixed
# exactly that mistake in round 13's leftover assertion).
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
    # Each counter owns exactly one outcome, so Total = TP + TF is the true
    # assertion count and PASS never silently includes a failure.
    if ok:
        TP += 1
        print(f'  [PASS] {label}')
    else:
        TF += 1
        print(f'  [FAIL] {label} -- {extra}')


def read_src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


from src.utils.helpers.date_extractor import date_extractor as DX        # noqa: E402
from src.core.config import DEFAULT_PRIORITY_ORDER, config               # noqa: E402
from src.core.file_selector import (                                     # noqa: E402
    build_group_scoretable, compute_date_scores, filename_scores)

_score = DX.get_filename_importance_score

# =====================================================================
SEP('A.  defect 1 -- a parenthesised WORD is not a numbered copy')
# =====================================================================
# The marker used to be the bare ' (' substring, so ANY parenthesised qualifier
# was capped to 3 and then bonus'd back to 4. The PENALTY was broad while the
# bonus EXEMPTION was narrow (' (1)'..' (9)'), so such a name was punished as a
# copy yet still rewarded as clean -- the drift was the defect.

for name, expected in [('dsc (Final).jpg', 9), ('photo (USA).jpg', 8),
                       ('2605202413312833 (USA).pdf', 6)]:
    got = _score(name)
    P(f'{name} keeps its own weight (={expected})', got == expected,
      f'got {got}')

# NOTE: 'report (2026).docx' was asserted here as 6 in round 15. Round 16
# deliberately reversed that -- the user asked for EVERY number in parentheses
# to count as a copy number, so a bare '(2026)' now reads as one and scores 3.
# The case lives in test_fixes_round16.py, where the trade-off is stated openly.

_markers_line = read_src('src/utils/helpers/date_extractor.py') \
    .split('copy_markers = [')[1].split(']')[0]
P("' (' is gone from the copy-marker list", "' ('" not in _markers_line,
  _markers_line)

# Genuine numbered copies MUST stay penalised -- this is the user requirement
# round 3 locked in, and it is the reason the fix is safe.
for name in ['photo (1).jpg', 'photo (2).jpg', 'photo (9).jpg']:
    got = _score(name)
    P(f'genuine numbered copy {name} still capped (={3})', got == 3, f'got {got}')

P("copy (1).jpg still scores 2", _score('copy (1).jpg') == 2, _score('copy (1).jpg'))

# The penalty and the bonus exemption now share ONE computation, so they can
# never drift apart again.
_src_score_fn = read_src('src/utils/helpers/date_extractor.py') \
    .split('def get_filename_importance_score')[1].split('def _pattern_matches')[0]
P('the penalty and the bonus exemption share one is_numbered_copy computation',
  _src_score_fn.count('is_numbered_copy = ') == 1
  and 'if not is_numbered_copy:' in _src_score_fn,
  f"is_numbered_copy assigned {_src_score_fn.count('is_numbered_copy = ')} time(s)")

# =====================================================================
SEP('B.  defect 2 -- a carved machine name earns no keyword reward')
# =====================================================================
# R-Studio writes raw-carved files as <word>_<W>x<H>x<bitdepth>_<index>. Its
# literal 'img'/'vid' token matched the photo/video keyword and then took the
# clean bonus, so a nameless carve outscored a real dated user file.

for name in ['img_1080x2340x24_020414.jpg', 'img_735x715x24_001903.jpg',
             'img_236x512x24_000534.jpg', 'img_720x1280x24_000311.jpg',
             'vid_1920x1080x24_000123.mp4']:
    got = _score(name)
    P(f'carved name {name} is NEUTRAL (=6), not rewarded', got == 6, f'got {got}')

P('neutral means the ordinary default (5) plus the clean bonus -- not a penalty',
  _score('img_1080x2340x24_020414.jpg') == _score('wallpaper.jpg'),
  f"carve={_score('img_1080x2340x24_020414.jpg')} plain={_score('wallpaper.jpg')}")

# Real camera names do NOT match the carve shape and must be untouched.
for name, expected in [('IMG_1234_WA0001.jpg', 8), ('IMG_0001.jpg', 8),
                       ('DSC_0453.jpg', 9), ('VID_20240101_120000.mp4', 9),
                       ('IMG_20100101_original.jpg', 9)]:
    got = _score(name)
    P(f'real camera name {name} untouched (={expected})', got == expected, f'got {got}')

P('the guard matches the SHAPE, not the prefix',
  r"re.fullmatch(r'[a-z]+_\d+x\d+x\d+_\d+', stem_lower)" in _src_score_fn)


# =====================================================================
SEP('C.  nothing else moved -- frozen reference table')
# =====================================================================
# Every score below was measured on the code BEFORE round 15 and is unchanged
# after it. This is the regression lock: the two fixes are surgical, so any
# other filename must score exactly as it always did.

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
}

_drift = [(n, exp, _score(n)) for n, exp in FROZEN.items() if _score(n) != exp]
P(f'all {len(FROZEN)} frozen filenames score exactly as before round 15',
  not _drift, _drift)

# The binding assertions the OTHER suites make about this function, restated so
# a round-15 regression cannot hide behind an unrelated suite.
P('round 1/3/e2e: no score exceeds 9',
  max(_score(n) for n in FROZEN) <= 9, max(_score(n) for n in FROZEN))
P('round 3: no weight in the pattern table exceeds 8',
  max(DX.filename_importance.values()) <= 8, max(DX.filename_importance.values()))
P('round 3: original / camera / dsc stay tied (no semantic inversion)',
  _score('original.jpg') == _score('camera.jpg') == _score('dsc_1234.jpg'))
P('round 3/e2e: word boundaries intact (epic/attempt/Temple not penalised)',
  _score('epic.jpg') == _score('attempt.jpg') == _score('Temple_run.jpg')
  == _score('mydoc.jpg'))

# =====================================================================
SEP('D.  the MECHANISM is untouched')
# =====================================================================
# The user asked for no change to how the tool decides. Round 15 changed only
# the INPUT VALUES of one criterion, so every part of the decision machinery
# must be provably identical.

P('DEFAULT_PRIORITY_ORDER is still [2, 3, 1, 4] (date > resolution > size > filename)',
  DEFAULT_PRIORITY_ORDER == [2, 3, 1, 4], DEFAULT_PRIORITY_ORDER)

_table = build_group_scoretable(
    pixels={'a': 100, 'b': 100}, size_bytes={'a': 1000, 'b': 1000},
    filename_importance={'a': 7, 'b': 6}, date_scores={'a': 5.0, 'b': 5.0},
    priority_order=list(DEFAULT_PRIORITY_ORDER))
_w = {c: _table['a']['weighted'][c] / _table['a']['scores'][c]
      for c in ('resolution', 'size', 'date', 'filename')}
P('criterion weights are still date=4, resolution=3, size=2, filename=1',
  (_w['date'], _w['resolution'], _w['size'], _w['filename']) == (4.0, 3.0, 2.0, 1.0), _w)
P('filename still carries the LOWEST weight of the four',
  _w['filename'] == min(_w.values()), _w)

P('the round-7 date gate still neutralises a filename-precision gap under a day',
  compute_date_scores({'a': __import__('datetime').datetime(2025, 6, 26, 0, 0, 0),
                       'b': __import__('datetime').datetime(2025, 6, 26, 14, 8, 22)},
                      True, {'a': 'filename', 'b': 'exif'}) == {'a': 5.0, 'b': 5.0})
P('identical filename importances are still a tie (5.0)',
  filename_scores({'a': 7, 'b': 7}) == {'a': 5.0, 'b': 5.0})

P('the filename_importance pattern table itself was not edited',
  (DX.filename_importance['img'] == 7 and DX.filename_importance['screenshot'] == 6
   and DX.filename_importance['dsc'] == 8 and DX.filename_importance['copy'] == 2
   and DX.filename_importance['recovered'] == 1),
  {k: DX.filename_importance[k] for k in ('img', 'screenshot', 'dsc', 'copy', 'recovered')})

P('round 15 touched ONLY get_filename_importance_score in that file',
  _src_score_fn.count('Round 15') == 3
  and 'Round 15' not in read_src('src/utils/helpers/date_extractor.py')
      .split('def get_filename_importance_score')[0],
  f"Round 15 markers in the scoring function: {_src_score_fn.count('Round 15')}")


# =====================================================================
SEP('E.  the decision this actually changes')
# =====================================================================
# This reproduces the exact shape of the 12 645 groups found in the user's
# similar report: equal dimensions, equal size, date neutralised by the gate --
# so filename is the only criterion still able to speak. Only the INPUT values
# differ between the two runs; the machinery is identical.

_REAL = 'Screenshot_\u0662\u0660\u0662\u0665\u0660\u0666\u0662\u0666_\u0661\u0664\u0660\u0668\u0662\u0662_Gallery.jpg'
_CARVE = 'img_1080x2340x24_020414.jpg'
_PX = 1080 * 2340


def _winner(importance_of_real, importance_of_carve):
    tbl = build_group_scoretable(
        pixels={_REAL: _PX, _CARVE: _PX},
        size_bytes={_REAL: 2_055_000, _CARVE: 2_055_000},
        filename_importance={_REAL: importance_of_real, _CARVE: importance_of_carve},
        date_scores={_REAL: 5.0, _CARVE: 5.0},
        priority_order=list(DEFAULT_PRIORITY_ORDER))
    return max(tbl, key=lambda f: tbl[f]['total'])


P('the real user file scores 7 and the carved placeholder scores 6',
  (_score(_REAL), _score(_CARVE)) == (7, 6), (_score(_REAL), _score(_CARVE)))

P('BEFORE round 15 (carve=8) the nameless carve won the group',
  _winner(7, 8) == _CARVE, _winner(7, 8))
P('AFTER round 15 (carve=6) the real dated user file wins the group',
  _winner(7, 6) == _REAL, _winner(7, 6))
P('the flip comes from the input values alone -- same table, same weights',
  _winner(7, 8) != _winner(7, 6))

# A real name must also beat the other machine-name shapes seen in the reports.
for other in ['0053881bb0cdfeb259e2b96e1d4a5cd8.jpg', '1000002192.jpg']:
    P(f'a real name outranks the machine name {other[:24]}...',
      _score(_REAL) > _score(other), f'{_score(_REAL)} vs {_score(other)}')

# Two machine names tie -- which is correct: neither carries information, so
# nothing about the name should decide between them.
P('two machine names tie, so no name signal decides between them',
  _score(_CARVE) == _score('0053881bb0cdfeb259e2b96e1d4a5cd8.jpg'),
  f'{_score(_CARVE)} vs {_score("0053881bb0cdfeb259e2b96e1d4a5cd8.jpg")}')

# =====================================================================
SEP('F.  the machine is left exactly as it was found')
# =====================================================================
_reports_now = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                if _REPORTS_DIR.exists() else [])
P('the REAL reports/ folder was never touched by this suite',
  _reports_now == _REPORTS_BEFORE,
  (set(_reports_now) ^ set(_REPORTS_BEFORE)))

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
if TF == 0:
    print('  ALL TESTS PASSED')
else:
    print('  SOME TESTS FAILED')
print('=' * 70)
sys.exit(0 if TF == 0 else 1)
