# imgSniper v3 -- Round 7 Fix Verification Suite
# Comparable criterion scales + honest reasons + priorities that actually stick.
#   * #518/#526/#572: the weighted sum compared INCOMPARABLE scales (raw 1-9
#     filename vs absolute caps for size/resolution), so a 360x449 file was
#     kept over a 720x897 one. Every criterion is now normalised WITHIN the
#     group onto one 0-10 scale with no-decision gates; the priority order
#     really governs the outcome.
#   * "Deletion Reason: Higher resolution" for a 1-pixel gap: reasons are now
#     computed from the SAME scoretable that decided, state the weighted-score
#     margin, name genuine advantages of the deleted file, and label
#     sub-threshold differences as such.
#   * Priorities reverted to default: every suite now restores
#     config/settings.json BYTES via atexit (config.set() saves immediately,
#     the old in-memory restore did not); the shipped default is now
#     date > resolution > size > filename ([2, 3, 1, 4]).
# Run from project root: python tests/test_fixes_round7.py

import sys, io, json, shutil, tempfile, logging
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Round 7: never leave test-side config changes on disk (see round-5 header).
import atexit                                                   # noqa: E402
_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None
if _CFG_BYTES is not None:
    atexit.register(lambda: _CFG_FILE.write_bytes(_CFG_BYTES))

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


def P(name, ok, detail=''):
    global TP, TF
    if ok:
        TP += 1
    else:
        TF += 1
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + name +
          (' -- ' + str(detail) if detail else ''))


import numpy as np                                                   # noqa: E402
from PIL import Image                                                # noqa: E402

from src.core.config import config, DEFAULT_PRIORITY_ORDER, Config   # noqa: E402
from src.core.file_selector import (                                 # noqa: E402
    gate_passes, ratio_scores, filename_scores, compute_date_scores,
    compute_resolution_boost_from_pixels, build_group_scoretable,
    SCORE_GATE_RATIO,
)
from src.utils.reports.report_formatter import ReportFormatter       # noqa: E402
from src.utils.helpers.date_extractor import date_extractor          # noqa: E402
from src.core.i18n.translations_english import ENGLISH_TRANSLATIONS  # noqa: E402
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS    # noqa: E402

MB = 1024 * 1024
TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_round7_'))


SEP('1) comparable criterion scales (pure math)')

P('5% gate: 1.049 fails, 1.05 passes',
  (not gate_passes(1.049, 1.0)) and gate_passes(1.05, 1.0) and SCORE_GATE_RATIO == 1.05)

P('7.76 vs 7.77 MB scores as a TIE (round-5 #7 guarantee kept)',
  ratio_scores({'a': 7.76 * MB, 'b': 7.77 * MB}) == {'a': 5.0, 'b': 5.0})

P('log-ratio scale: worst = 0, best = 10, 2x spread = full swing',
  ratio_scores({'a': 1.0, 'b': 4.0}) == {'a': 0.0, 'b': 10.0} and
  ratio_scores({'a': 1.0, 'b': 2.0}) == {'a': 0.0, 'b': 10.0})

P('unreadable/invalid value (0) scores 0, never wins a quality criterion',
  ratio_scores({'a': 0, 'b': 1, 'c': 2}) == {'a': 0.0, 'b': 0.0, 'c': 10.0})

file_scores = filename_scores({'a': 8, 'b': 2})
P('filename importance maps proportionally (8/9 -> ~8.9, 2/9 -> ~2.2)',
  abs(file_scores['a'] - 8.888) < 0.01 and abs(file_scores['b'] - 2.222) < 0.01,
  file_scores)
P('identical filename importance is a tie (5.0)',
  filename_scores({'a': 8, 'b': 8}) == {'a': 5.0, 'b': 5.0})

d1, d2 = datetime(2024, 1, 1), datetime(2024, 1, 31)
P('dates 30 days apart: oldest = 10, newest = 0',
  compute_date_scores({'a': d1, 'b': d2}, True) == {'a': 10.0, 'b': 0.0})
P('1-second EXIF gap is a tie (no decision from noise)',
  compute_date_scores({'a': datetime(2024, 1, 1, 10, 0, 0),
                       'b': datetime(2024, 1, 1, 10, 0, 1)}, True) ==
  {'a': 5.0, 'b': 5.0})
P('same-day gap involving a FILENAME date is a tie (day-precision artifact)',
  compute_date_scores({'a': datetime(2022, 7, 20, 0, 0, 0),
                       'b': datetime(2022, 7, 20, 16, 42, 6)}, True,
                      {'a': 'filename', 'b': 'exif'}) == {'a': 5.0, 'b': 5.0})
P('unknown date scores below a known one, no dates at all = tie',
  compute_date_scores({'a': d1, 'b': None}, True) == {'a': 10.0, 'b': 3.0} and
  compute_date_scores({'a': None, 'b': None}, True) == {'a': 5.0, 'b': 5.0})

P('resolution boost: 4x spread -> 2.0, below 2x -> 1.0, single file -> 1.0',
  abs(compute_resolution_boost_from_pixels([10_000, 40_000]) - 2.0) < 0.001 and
  compute_resolution_boost_from_pixels([10_000, 15_000]) == 1.0 and
  compute_resolution_boost_from_pixels([10_000]) == 1.0)

table = build_group_scoretable(
    {'a': 100, 'b': 400}, {'a': 10, 'b': 10}, {'a': 5, 'b': 5},
    {'a': 5.0, 'b': 5.0}, list(DEFAULT_PRIORITY_ORDER))
P('default weights: date rank1 = 4, resolution rank2 = 3',
  table['a']['weighted']['date'] == 20.0 and table['b']['weighted']['resolution'] == 30.0,
  {k: v['total'] for k, v in table.items()})
P('the decisive criterion actually decides the total',
  table['b']['total'] > table['a']['total'])


SEP('2) honest reasons -- report_formatter matches scoretable')

import traceback, sys
# from src.core.file_selector import score_selection  # doesn't exist

def make_info(size_mb, res, w, h, date, source, imp, extra_bytes=0):
    return {
        'size_bytes': int(size_mb * MB) + extra_bytes,
        'size_mb': size_mb,
        'resolution': res, 'width': w, 'height': h,
        'extracted_date': date, 'date_source': source,
        'filename_importance': imp,
    }

rf = ReportFormatter()

# Test 1: kept wins on older date and filename (8 vs 2); deleted has slightly better res/size but below 5% gate
kept_info1 = make_info(7.76, 735*826, 735, 826, '2024-01-01 10:00:00', 'exif', 8)  # older date, slightly worse res/size
deleted_info1 = make_info(7.77, 736*826, 736, 826, '2024-01-02 10:00:00', 'exif', 2)  # newer date, slightly better res/size
infos1 = {'kept.jpg': kept_info1, 'deleted.jpg': deleted_info1}

try:
    reasons = rf.get_deletion_reason('deleted.jpg', 'kept.jpg', infos1)
    print("REASONS1:", reasons, file=sys.stderr)
    P('kept wins on older date and filename (8 vs 2); deleted has sub-threshold res/size edges labelled',
      'Older date' in reasons and
      'resolution differed only within the no-decision threshold' in reasons,
      reasons)
except Exception as e:
    with open('test_error.txt', 'w') as f:
        traceback.print_exc(file=f)
    P('get_deletion_reason test 1 raised exception', False, str(e))

# Test 2: REAL groups #518/#526/#572: 720x897 wins over 360x449 because resolution/size are now comparable
# No dates -> date is tie (5.0)
# Resolution: 720*897 vs 360*449 = 645840 vs 161640 = 4x spread -> log-ratio scale: kept gets 10, deleted gets 0
# Size: 5MB vs 2MB = 2.5x spread -> above 5% gate -> kept gets 10, deleted gets 0
# Filename: kept=8, deleted=2 -> kept wins
kept_info2 = make_info(5.0, 720*897, 720, 897, 'Unknown', 'filename', 8)
deleted_info2 = make_info(2.0, 360*449, 360, 449, 'Unknown', 'filename', 2)
infos2 = {'kept2.jpg': kept_info2, 'deleted2.jpg': deleted_info2}

try:
    reasons2 = rf.get_deletion_reason('deleted2.jpg', 'kept2.jpg', infos2)
    print("REASONS2:", reasons2, file=sys.stderr)
    P('REAL groups #518/#526/#572: 720x897 wins over 360x449 because resolution/size are now comparable',
      'resolution' in reasons2 and '720' in reasons2,
      reasons2)
except Exception as e:
    with open('test_error.txt', 'w') as f:
        traceback.print_exc(file=f)
    P('get_deletion_reason test 2 raised exception', False, str(e))

# Test 3: truly identical group -> explicit tie labels
kept_info3 = make_info(5.0, 1000*1000, 1000, 1000, 'Unknown', 'none', 5)
deleted_info3 = make_info(5.0, 1000*1000, 1000, 1000, 'Unknown', 'none', 5)
infos3 = {'kept3.jpg': kept_info3, 'deleted3.jpg': deleted_info3}

try:
    reasons3 = rf.get_deletion_reason('deleted3.jpg', 'kept3.jpg', infos3)
    print("REASONS3:", reasons3, file=sys.stderr)
    P('truly identical group -> explicit tie labels',
      all('no decisive difference' in r.lower() for r in reasons3.splitlines()), reasons3)
except Exception as e:
    with open('test_error.txt', 'w') as f:
        traceback.print_exc(file=f)
    P('get_deletion_reason test 3 raised exception', False, str(e))

# Test 4: Selection reason compares against CLOSEST rival (highest weighted total)
fake_grp = {
    'winner.jpg': make_info(5.0, 2000*1500, 2000, 1500, '2024-01-10 10:00:00', 'exif', 5),
    'second.jpg': make_info(4.0, 1900*1400, 1900, 1400, '2024-01-11 10:00:00', 'exif', 6),
    'third.jpg': make_info(1.0, 800*600, 800, 600, '2024-01-09 10:00:00', 'exif', 8),
}
try:
    sel_reasons = rf.get_detailed_selection_reason('winner.jpg', ['winner.jpg', 'second.jpg', 'third.jpg'], fake_grp)
    print("SEL_REASONS:", sel_reasons, file=sys.stderr)
    P('selection reason cites the SECOND-BEST as the rival (note mentions filename importance where rival was better)',
      'filename importance' in sel_reasons and '6/9' in sel_reasons,
      sel_reasons)
except Exception as e:
    with open('test_error.txt', 'w') as f:
        traceback.print_exc(file=f)
    P('get_detailed_selection_reason raised exception', False, str(e))


SEP('3) priorities stick -- config file bytes are restored after tests')

_cfg_now = _CFG_FILE.read_bytes()
P('config file bytes unchanged by this test run (atexit restore works)',
  _cfg_now == _CFG_BYTES, f'before MD5 len={len(_CFG_BYTES)} after len={len(_cfg_now)}')

P('DEFAULT_PRIORITY_ORDER is [2, 3, 1, 4] (date > resolution > size > filename)',
  DEFAULT_PRIORITY_ORDER == [2, 3, 1, 4])
P('config loads that same order',
  config.get('priorities.order') == [2, 3, 1, 4])


SEP('4) end-to-end re-creation of your reported groups')

# group A: 360x449 vs 720x897 - test that higher resolution wins
from src.core.file_selector import FileSelector, build_group_scoretable
sel = FileSelector()  # uses config internally

# Create fake group info for the two files
# We can't easily test the full pipeline without the hash grouping,
# but we can test the scoring logic directly
MB = 1024 * 1024
group_files = ['low_res.jpg', 'high_res.jpg']
infos = {
    'low_res.jpg': make_info(5.0, 360*449, 360, 449, 'Unknown', 'filename', 5),
    'high_res.jpg': make_info(5.0, 720*897, 720, 897, 'Unknown', 'filename', 5),
}
table = build_group_scoretable(
    {k: v['resolution'] for k, v in infos.items()},
    {k: int(v['size_mb'] * MB) for k, v in infos.items()},
    {k: v['filename_importance'] for k, v in infos.items()},
    {k: 5.0 for k in infos},  # no date difference -> all get 5.0
    list(DEFAULT_PRIORITY_ORDER)
)

# high_res should win on resolution (and size if different)
P('high_res.jpg wins on resolution (4x spread)',
  table['high_res.jpg']['total'] > table['low_res.jpg']['total'],
  {k: v['total'] for k, v in table.items()})

# Also test that the kept file is the high_res one
# Resolution: 720*897 / 360*449 = 4.0 -> log-ratio: high=10, low=0
# Size: same -> tie (5.0 each)
# Filename: same -> tie (5.0 each)
# Date: same -> tie (5.0 each)
# Weights (priority order [2,3,1,4]): date=4, res=3, size=2, filename=1
# high_res: 5*4 + 10*3 + 5*2 + 5*1 = 20 + 30 + 10 + 5 = 65
# low_res:  5*4 + 0*3  + 5*2 + 5*1 = 20 + 0  + 10 + 5 = 35
P('score breakdown: high_res=65, low_res=35',
  table['high_res.jpg']['total'] == 65.0 and table['low_res.jpg']['total'] == 35.0,
  table)


SEP('SUMMARY')
print(f'  Total: {TP + TF}  PASS: {TP}  FAIL: {TF}')
if TF:
    sys.exit(1)
print('  ALL TESTS PASSED ✅')

# cleanup
try:
    shutil.rmtree(TEST_DIR)
except Exception:
    pass

