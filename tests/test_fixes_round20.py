# imgSniper v3 -- Round 20 Fix Verification Suite
# THREE chained defects in the DATE input and the NAME evidence -- the reason
# every report said "filename importance" while the user had put DATE first.
#
# What the forensic review of the shipped reports proved
# (reports/similar_2026-10-10_03-42-17.txt, 15 519 groups, and
#  reports/duplicates_2026-10-09_13-39-01.txt, 50 099 groups):
#
#   * 13 601 of 15 519 similar groups (87.6 %) and 10 515 of 50 099 duplicate
#     groups (21.0 %) printed "filename importance" as the selection reason,
#     while "Older date" appeared in only 466 and 18 492 respectively -- even
#     though priorities.order was [2, 3, 1, 4], i.e. DATE FIRST (weight 4) and
#     filename LAST (weight 1).
#
#   * Replaying compute_date_scores() over those groups showed WHY: the date
#     criterion scored 5.0 for EVERY file -- it was neutralised, not lost.
#     13 817 similar groups and 2 843 duplicate groups were affected.
#
#   * 13 704 of those similar groups had a kept file whose FILENAME carried a
#     real time that had been thrown away. In 258 of them a deleted file was
#     genuinely older by more than DATE_GATE_SECONDS (237 by more than an hour),
#     so the decision itself was wrong, not only its wording.
#
# The three defects, in the order they chained:
#
#   1. date_extractor.extract_date_from_filename() returned datetime(y, m, d)
#      UNCONDITIONALLY -- always midnight. self.time_patterns was defined in
#      __init__ and never called by anything in the project. So
#      '20131213_161353.jpg' lost its 16:13:53 and EVERY filename date looked
#      day-level.
#
#   2. Because of (1), image_info_extractor flagged every filename date
#      date_only=True, and reports printed "(date only - no time in filename)"
#      for names that plainly carried the time.
#
#   3. compute_date_scores() then applied
#          any(source == 'filename') and span < 86400 -> everyone scores 5.0
#      which threw the DATE criterion away wholesale: it ignored how big the gap
#      was (a real 23-hour difference was discarded as an "artifact") and it
#      ignored WHO was day-level (one filename date anywhere blinded the
#      comparison between two precise EXIF timestamps). With (1) making every
#      filename date day-level, this fired constantly -- so the user's #1
#      priority was replaced by the #4 one.
#
#   Plus a fourth finding the user raised directly: EXIF alone does not prove a
#   file is the ORIGINAL. A recovery tool carves a JPEG off the disk with its
#   EXIF intact and that carve often carries an OLDER timestamp than the
#   survivor. 174 similar groups and 172 duplicate groups kept a penalised name
#   (recovered / copy / a "(N)" counter); in 38 of those a CLEAN-named file was
#   deleted instead, 37 of them explicitly "because of its older date".
#
# Verified here:
#   A. the TIME is read from the filename -- strictly anchored and validated;
#   B. the day gate is precision-aware: same day ties, different days DECIDE;
#   C. name provenance classes (original > neutral > weak > copy > recovered);
#   D. the engine: a derived name never survives a more original one, and among
#      equally original names the older date decides;
#   E. the reports say what the engine actually did, and EXPLAIN a date that was
#      neutralised instead of silently naming another criterion;
#   F. every sector inherits the fix (video / office / archives / other);
#   G. round 21 -- the gate is CONDITIONAL, so a copy marker no longer inverts
#      the user's #1 priority (date) in ANY sector;
#   H. the four DEAD settings (exif_priority, modified_name_priority,
#      quality_priority, format_priority) are removed -- and proven inert, so
#      removing them changed no decision anywhere;
#   I. the machine is left exactly as it was found.
#
# Deliberately NOT changed by round 20: the priority order, the criterion
# weights, DATE_GATE_SECONDS, SCORE_GATE_RATIO, the filename_importance pattern
# table, the resolution boost, the tie-breaks, dry-run and deletion behaviour,
# and the video engine (which keeps its own selector, as the user asked).
# Run from project root: python tests/test_fixes_round20.py

import sys, json, logging, atexit, tempfile, shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None

# The reports folder holds the USER's real reports, and the recycle bin holds
# their real files. "Did this suite touch them?" can only be answered by
# comparing a BEFORE snapshot with the state at the end.
_REPORTS_DIR = ROOT / 'reports'
_REPORTS_BEFORE = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                   if _REPORTS_DIR.exists() else [])
_BIN_DIR = ROOT / 'recycle-bin'


def _count_files(root):
    if not root.exists():
        return 0
    return sum(1 for p in root.rglob('*') if p.is_file())


_BIN_BEFORE = _count_files(_BIN_DIR)


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
from src.core.config import DEFAULT_PRIORITY_ORDER, config               # noqa: E402
from src.core.file_selector import (                                     # noqa: E402
    FileSelector, build_group_scoretable, compute_date_scores,
    is_day_level_date, relative_date_scores, DATE_GATE_SECONDS)
from src.core import name_provenance as NP                              # noqa: E402
from src.utils.reports.report_formatter import ReportFormatter           # noqa: E402
from src.utils.reports.image_info_extractor import (                     # noqa: E402
    ImageInfoExtractor, format_extracted_date)

# =====================================================================
SEP('A.  defect 1 -- the TIME is read from the filename')
# =====================================================================
# extract_date_from_filename() used to return midnight for EVERY name. These are
# real filenames taken from the user's own reports.

TIME_CASES = [
    ('20131213_161353 (1).jpg',        datetime(2013, 12, 13, 16, 13, 53)),
    ('IMG_20181117_142355.jpg',        datetime(2018, 11, 17, 14, 23, 55)),
    ('IMG_20231004_104853_036.jpg',    datetime(2023, 10, 4, 10, 48, 53)),
    ('20230521_142629-1.jpg',          datetime(2023, 5, 21, 14, 26, 29)),
    ('Screenshot_20220712-214909.png', datetime(2022, 7, 12, 21, 49, 9)),
    ('VID_20200101_143022.mp4',        datetime(2020, 1, 1, 14, 30, 22)),
    ('2022-07-12_21-49-09.png',        datetime(2022, 7, 12, 21, 49, 9)),
    ('20131213161353.jpg',             datetime(2013, 12, 13, 16, 13, 53)),
    # Arabic-Indic digits: the true capture time is written in the name
    ('\u0662\u0660\u0661\u0666\u0660\u0669\u0661\u0665_\u0661\u0668\u0664\u0664\u0660\u0666.jpg',
     datetime(2016, 9, 15, 18, 44, 6)),
    ('CYMERA_\u0662\u0660\u0661\u0667\u0660\u0662\u0662\u0667_\u0661\u0669\u0663\u0662\u0665\u0661.jpg',
     datetime(2017, 2, 27, 19, 32, 51)),
    ('IMG_\u0662\u0660\u0662\u0662\u0660\u0667\u0660\u0666_\u0661\u0664\u0665\u0663\u0664\u0667.jpg',
     datetime(2022, 7, 6, 14, 53, 47)),
]
for name, expected in TIME_CASES:
    got = DX.extract_date_from_filename(name)
    P(f'time read: {name[:38]:40} -> {got}', got == expected, f'expected {expected}')

# A name that genuinely carries NO time must stay day-level. Inventing a time
# here would be worse than having none: 'WA0058' is a WhatsApp counter, and
# reading it as 00:58:00 would fabricate a comparison the file never contained.
NO_TIME_CASES = [
    ('IMG-20181019-WA0058.jpg', datetime(2018, 10, 19)),
    ('IMG-20220712-WA0013.jpg', datetime(2022, 7, 12)),
    ('photo_20150601.jpg',      datetime(2015, 6, 1)),
    ('20180817.mp4',            datetime(2018, 8, 17)),
]
for name, expected in NO_TIME_CASES:
    got = DX.extract_date_from_filename(name)
    P(f'no time invented: {name[:34]:36} -> {got}', got == expected, f'expected {expected}')

# Anchoring and validation: a time must never be carved out of a longer digit
# run, and an out-of-range time must be discarded (the DATE is still kept).
GUARD_CASES = [
    ('-5868218734718597913_121.jpg', None),
    ('20189999_123456.jpg',          None),
    ('12345678.jpg',                 None),
    ('20180817_996060.jpg',          datetime(2018, 8, 17)),
]
for name, expected in GUARD_CASES:
    got = DX.extract_date_from_filename(name)
    P(f'guard: {name[:38]:40} -> {got}', got == expected, f'expected {expected}')

P('time_patterns is no longer dead code (it mirrors the anchored patterns)',
  'FILENAME_DATETIME_PATTERNS' in read_src('src/utils/helpers/date_extractor.py')
  and len(DX.time_patterns) == 4, str(DX.time_patterns))

# The date_only flag now tells the truth, so a report only annotates a name that
# really has no time in it.
_extractor = ImageInfoExtractor()
WORK = Path(tempfile.mkdtemp(prefix='imgsniper_r20_'))
atexit.register(shutil.rmtree, str(WORK), True)


def make_img(path, w, h):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (w, h), color=(w % 256, h % 256, 120))
    ImageDraw.Draw(img).rectangle([w // 4, h // 4, w // 2, h // 2], fill=(255, 255, 255))
    img.save(path, 'JPEG', quality=88)
    return str(path)


timed = make_img(WORK / 'IMG_20181117_142355.jpg', 64, 48)
dayonly = make_img(WORK / 'IMG-20181019-WA0058.jpg', 64, 48)
info_timed = _extractor.get_detailed_image_info(timed)
info_day = _extractor.get_detailed_image_info(dayonly)
P('a name WITH a time is no longer flagged date_only',
  info_timed.get('date_only') is False, str(info_timed.get('extracted_date')))
P('its report line carries the real seconds',
  info_timed.get('extracted_date') == '2018-11-17 14:23:55'
  and 'date only' not in format_extracted_date(info_timed),
  format_extracted_date(info_timed))
P('a name WITHOUT a time is still flagged date_only (honest annotation)',
  info_day.get('date_only') is True
  and 'date only' in format_extracted_date(info_day),
  format_extracted_date(info_day))

# =====================================================================
SEP('B.  defect 3 -- the day gate is precision-aware')
# =====================================================================
A, B, C = 'a', 'b', 'c'

# The old rule: any filename date + span < 86400 -> EVERY file scores 5.0.
# Checked against the EXECUTABLE code only -- the docstring quotes the old rule
# on purpose, to explain why it was replaced.
_fn_src = read_src('src/core/file_selector.py') \
    .split('def compute_date_scores')[1].split('\ndef ')[0]
_fn_code = _fn_src.split('"""')[-1]
P("the blunt 'span < 86400' rule is gone from the executable code",
  '86400' not in _fn_code and 'is_day_level_date' in _fn_code, _fn_code[:160])

# B1 same day, one side day-level -> a tie. The midnight artifact cannot decide.
s = compute_date_scores({A: datetime(2016, 9, 15), B: datetime(2016, 9, 15, 18, 44, 5)},
                        True, {A: 'filename', B: 'exif'})
P('same day + a day-level filename date -> TIE', len(set(s.values())) == 1, str(s))

# B2 DIFFERENT days -> the date DECIDES. This is the fix: before, a group whose
# span was under a day was declared a tie even when the days differed.
s = compute_date_scores({A: datetime(2018, 10, 19), B: datetime(2018, 11, 17)},
                        True, {A: 'filename', B: 'filename'})
P('different days -> date DECIDES and the oldest wins',
  s[A] == 10.0 and s[B] == 0.0, str(s))

# B3 one day-level member no longer blinds two PRECISE dates on different days.
s = compute_date_scores({A: datetime(2018, 10, 19, 8, 0),
                         B: datetime(2018, 11, 17, 9, 0),
                         C: datetime(2018, 11, 17)},
                        True, {A: 'exif', B: 'exif', C: 'filename'})
P('a day-level member does not blind two precise EXIF dates',
  s[A] == 10.0 and s[B] == 0.0 and s[C] == 0.0, str(s))

# B4 a filename TIME now really competes with an EXIF time -- and the OLDER one
# wins, which is the user's explicit decision ("we take the older").
s = compute_date_scores({A: datetime(2022, 7, 6, 14, 53, 47),
                         B: datetime(2022, 7, 6, 14, 2, 44)},
                        True, {A: 'filename', B: 'exif'})
P('filename TIME vs EXIF time -> the OLDER wins',
  s[B] == 10.0 and s[A] == 0.0, str(s))

# B5 a sub-minute gap is still noise (DATE_GATE_SECONDS untouched).
s = compute_date_scores({A: datetime(2016, 9, 15, 18, 44, 6),
                         B: datetime(2016, 9, 15, 18, 44, 5)},
                        True, {A: 'filename', B: 'exif'})
P(f'a 1-second gap is still a tie (DATE_GATE_SECONDS={DATE_GATE_SECONDS:g})',
  len(set(s.values())) == 1, str(s))

# B6 'newest' is still honoured, and an unknown date still loses.
s = compute_date_scores({A: datetime(2018, 10, 19), B: datetime(2018, 11, 17)},
                        False, {A: 'filename', B: 'filename'})
P("'newest' priority still honoured", s[B] == 10.0 and s[A] == 0.0, str(s))
s = compute_date_scores({A: datetime(2018, 10, 19), B: None}, True,
                        {A: 'filename', B: 'none'})
P('a known date still beats an unknown one (10 vs 3)',
  s[A] == 10.0 and s[B] == 3.0, str(s))
s = compute_date_scores({A: None, B: None}, True, {A: 'none', B: 'none'})
P('no dates at all is still a tie', len(set(s.values())) == 1, str(s))

# B7 is_day_level_date itself
P('is_day_level_date: filename midnight -> True',
  is_day_level_date(datetime(2018, 10, 19), 'filename') is True)
P('is_day_level_date: filename WITH a time -> False',
  is_day_level_date(datetime(2018, 10, 19, 14, 23), 'filename') is False)
P('is_day_level_date: EXIF midnight -> False (a real clock reading)',
  is_day_level_date(datetime(2018, 10, 19), 'exif') is False)
P('is_day_level_date: a modification time -> False',
  is_day_level_date(datetime(2018, 10, 19), 'modified') is False)
P('is_day_level_date: no date at all -> False', is_day_level_date(None, 'filename') is False)
P('relative_date_scores is exported for the reports to reuse',
  callable(relative_date_scores))

# =====================================================================
SEP('C.  finding 4 -- name provenance classes')
# =====================================================================
# EXIF alone does not prove a file is the original. The NAME is evidence about
# WHERE a file came from, which is stronger than any score.

CLASS_CASES = [
    # original-looking
    ('IMG_20181117_142355.jpg',   NP.CLASS_ORIGINAL),
    ('photo_20150601.jpg',        NP.CLASS_ORIGINAL),
    ('CAMERA_0001.jpg',           NP.CLASS_ORIGINAL),
    ('Screenshot_20220712.png',   NP.CLASS_ORIGINAL),
    # neutral: a bare date name carries no marker either way
    ('\u0662\u0660\u0661\u0666\u0660\u0669\u0661\u0665_\u0661\u0668\u0664\u0664\u0660\u0666.jpg',
     NP.CLASS_NEUTRAL),
    ('20131213_161353.jpg',       NP.CLASS_NEUTRAL),
    # copy
    ('20131213_161353 (1).jpg',   NP.CLASS_COPY),
    ('photo (99999999).jpg',      NP.CLASS_COPY),
    ('my copy.jpg',               NP.CLASS_COPY),
    ('\u0646\u0633\u062e\u0629 10512267.jpg', NP.CLASS_COPY),
    # a counter GLUED onto the marker word is still that marker
    ('file \u0646\u0633\u062e\u0629\u0663.mp4', NP.CLASS_COPY),
    ('copy2.jpg',                 NP.CLASS_COPY),
    # weak
    ('video_backup.mp4',          NP.CLASS_WEAK),
    ('edited_final.jpg',          NP.CLASS_WEAK),
    # recovered
    ('Recovered_jpg_file(1082).jpg', NP.CLASS_RECOVERED),
    ('restored_photo.jpg',        NP.CLASS_RECOVERED),
    ('\u0645\u0633\u062a\u0631\u062f\u0629.jpg', NP.CLASS_RECOVERED),
    # a machine-carved name IS recovery output -- the user never wrote it
    ('img_1280x853x24_001092.jpg', NP.CLASS_RECOVERED),
    ('img_1234x5678x24_0001.jpg', NP.CLASS_RECOVERED),
]
for name, expected in CLASS_CASES:
    got = NP.provenance_of(name)
    P(f'class {expected}: {name[:36]:38}', got == expected, f'got {got}')

# Word-boundary matching: a marker only counts as a whole token, so an ordinary
# name is never downgraded by a substring.
for name in ['David.jpg', 'attempt_fix.jpg', 'epic_sunset.jpg', 'Temple_run.jpg',
             'cachet_logo.png', 'picturesque.jpg']:
    P(f'no false marker in {name:24} (stays neutral)',
      NP.provenance_of(name) == NP.CLASS_NEUTRAL, str(NP.provenance_of(name)))

# A parenthesised YEAR is not a copy counter, and a machine-carved shape is
# recovery output -- it must never earn the camera reward NOR outrank a user name
# (R-Studio writes img_<w>x<h>x<bitdepth>_<index>.jpg).
P('a parenthesised YEAR is not a copy counter',
  NP.provenance_of('Movie (2018).jpg') == NP.CLASS_NEUTRAL,
  str(NP.provenance_of('Movie (2018).jpg')))
P('a carved machine name earns no camera/original class',
  NP.provenance_of('img_1234x5678x24_0001.jpg') != NP.CLASS_ORIGINAL,
  str(NP.provenance_of('img_1234x5678x24_0001.jpg')))
P('a genuine camera name is untouched by the carved-shape guard',
  NP.provenance_of('IMG_1234_WA0001.jpg') == NP.CLASS_ORIGINAL,
  str(NP.provenance_of('IMG_1234_WA0001.jpg')))
# The real regression this caught: a carve scored "neutral" and therefore beat a
# numbered WhatsApp copy whose name still carries a real capture date.
P('a carve ranks BELOW a numbered copy of a real WhatsApp name',
  NP.gate_tier_of('img_1280x853x24_001092.jpg')
  < NP.gate_tier_of('IMG-20240824-WA0015(1).jpg'),
  f'{NP.gate_tier_of("img_1280x853x24_001092.jpg")} vs '
  f'{NP.gate_tier_of("IMG-20240824-WA0015(1).jpg")}')

# Every class has a localized label that can never print "[Missing: ...]".
from src.core.i18n.i18n import i18n                                    # noqa: E402
for lang in ('en', 'ar'):
    i18n.set_language(lang)
    for cls in (NP.CLASS_ORIGINAL, NP.CLASS_NEUTRAL, NP.CLASS_WEAK,
                NP.CLASS_COPY, NP.CLASS_RECOVERED):
        label = NP.class_label(cls)
        P(f'[{lang}] class {cls} has a real label',
          bool(label) and not label.startswith('[Missing'), label)
i18n.set_language('en')

P('the analysis is explainable (reasons are recorded, not just a number)',
  len(NP.analyze_name('Recovered_jpg_file(1082).jpg')['reasons']) >= 1,
  str(NP.analyze_name('Recovered_jpg_file(1082).jpg')['reasons']))

# =====================================================================
SEP('D.  the engine -- gate first, then the user\'s own priorities')
# =====================================================================
sel = FileSelector()
config.set('priorities.date_priority', 'oldest')
config.set('priorities.order', list(DEFAULT_PRIORITY_ORDER))

# D1 THE case from the user's reports: a name-dated original next to a recovered
# carve whose EXIF is one second OLDER. Same dimensions, same bytes.
d1 = WORK / 'd1'
d1.mkdir()
original = make_img(d1 / 'IMG_20220706_145347.jpg', 320, 240)
carve = d1 / 'Recovered_jpg_file(1385).jpg'
shutil.copyfile(original, str(carve))
kept = sel.select_best_file([original, str(carve)])
P('D1 the named original survives the recovered carve',
  Path(kept).name == 'IMG_20220706_145347.jpg', Path(kept).name)

# D2 ...and it survives even when the carve carries a genuinely OLDER EXIF date
# and a HIGHER resolution -- the user's explicit decision: the clean name wins.
import os                                                            # noqa: E402
d2 = WORK / 'd2'
d2.mkdir()
small_clean = make_img(d2 / 'photo_20200101.jpg', 100, 100)
big_carve = make_img(d2 / 'Recovered_jpg_file(9).jpg', 400, 400)
kept = sel.select_best_file([small_clean, big_carve])
P('D2 a recovered name loses even at 4x the resolution',
  Path(kept).name == 'photo_20200101.jpg', Path(kept).name)
P('D2 ...and the quality it carried away IS reported as a sacrifice',
  sel.detect_resolution_sacrifice(kept, [small_clean, big_carve]) is not None,
  'no warning')

# D3 among EQUALLY original names the OLDER date still decides -- the gate must
# not swallow the user's #1 priority.
d3 = WORK / 'd3'
d3.mkdir()
newer = make_img(d3 / 'IMG_20200101_120000.jpg', 200, 200)
older = make_img(d3 / 'IMG_20100101_120000.jpg', 200, 200)
kept = sel.select_best_file([newer, older])
P('D3 same class -> the OLDER filename date wins (priority #1 honoured)',
  Path(kept).name == 'IMG_20100101_120000.jpg', Path(kept).name)

# D4 a numbered copy loses to a clean name, and a copy loses to a recovered name
# only in that order: recovered < copy < weak < neutral < original.
d4 = WORK / 'd4'
d4.mkdir()
f_copy = make_img(d4 / 'holiday (2).jpg', 200, 200)
f_neutral = make_img(d4 / 'holiday.jpg', 200, 200)
kept = sel.select_best_file([str(f_copy), str(f_neutral)])
P('D4 a "(2)" numbered copy loses to the clean name',
  Path(kept).name == 'holiday.jpg', Path(kept).name)

# D5 determinism: the winner must not depend on the scan order.
group5 = [original, str(carve), small_clean, big_carve]
P('D5 the winner is input-order independent',
  sel.select_best_file(group5) == sel.select_best_file(list(reversed(group5))),
  f'{Path(sel.select_best_file(group5)).name} vs '
  f'{Path(sel.select_best_file(list(reversed(group5)))).name}')

# D6 a single file is returned untouched, and an empty group cannot crash.
P('D6 a lone file is returned as-is',
  sel.select_best_file([original]) == original)

# D7 THE guard against an over-reaching gate. A bare date name is a camera
# default (Samsung writes exactly this) and is every bit as original as an
# IMG_ name, so a camera prefix must NOT outrank it absolutely -- the older of
# two clean originals has to survive, whatever prefix the newer one carries.
d7 = WORK / 'd7'
d7.mkdir()
newer_cam = make_img(d7 / 'IMG_20200101_120000.jpg', 200, 200)
older_bare = make_img(d7 / '\u0662\u0660\u0661\u0660\u0660\u0661\u0660\u0661_'
                           '\u0661\u0662\u0660\u0660\u0660\u0660.jpg', 200, 200)
P('D7 the two clean names share ONE gate tier (no absolute camera veto)',
  NP.gate_tier_of('IMG_20200101_120000.jpg')
  == NP.gate_tier_of('\u0662\u0660\u0661\u0660\u0660\u0661\u0660\u0661_'
                     '\u0661\u0662\u0660\u0660\u0660\u0660.jpg'),
  f'{NP.gate_tier_of("IMG_20200101_120000.jpg")} vs '
  f'{NP.gate_tier_of(chr(0x662) + chr(0x660) + chr(0x661) + chr(0x660) + chr(0x660) + chr(0x661) + chr(0x660) + chr(0x661))}')
kept = sel.select_best_file([newer_cam, older_bare])
P('D7 the OLDER bare-date original survives the newer IMG_ name',
  Path(kept).name.startswith('\u0662\u0660\u0661\u0660\u0660\u0661\u0660\u0661'),
  Path(kept).name)

# D8 the gate tiers themselves: derived names below, both clean classes equal.
P('D8 gate tiers keep the derived classes strictly ordered',
  (NP.gate_tier(NP.CLASS_RECOVERED), NP.gate_tier(NP.CLASS_COPY),
   NP.gate_tier(NP.CLASS_WEAK)) == (0, 1, 2),
  str([NP.gate_tier(c) for c in (NP.CLASS_RECOVERED, NP.CLASS_COPY, NP.CLASS_WEAK)]))
P('D8 gate tiers collapse ORIGINAL and NEUTRAL into one clean tier',
  NP.gate_tier(NP.CLASS_ORIGINAL) == NP.gate_tier(NP.CLASS_NEUTRAL) == 3,
  f'{NP.gate_tier(NP.CLASS_ORIGINAL)} / {NP.gate_tier(NP.CLASS_NEUTRAL)}')
P('D8 the full five-class taxonomy is still available for the report wording',
  len({NP.class_label(c) for c in (NP.CLASS_ORIGINAL, NP.CLASS_NEUTRAL,
                                   NP.CLASS_WEAK, NP.CLASS_COPY,
                                   NP.CLASS_RECOVERED)}) == 5)

# =====================================================================
SEP('E.  the reports say what the engine actually did')
# =====================================================================
rf = ReportFormatter()


def info(size_mb, resolution, width, height, date, source, importance, name=None):
    return {'name': name, 'size_mb': size_mb, 'size_bytes': int(size_mb * 1024 * 1024),
            'resolution': resolution, 'width': width, 'height': height,
            'extracted_date': date, 'date_source': source,
            'filename_importance': importance}


for lang in ('en', 'ar'):
    i18n.set_language(lang)

    # E1 THE complaint: a recovered carve whose EXIF is older used to be reported
    # as kept "because of its older date". The gate now decides, and says so.
    k = info(2.87, 3264 * 2448, 3264, 2448, '2022-07-06 14:53:47', 'filename', 8)
    d = info(2.87, 3264 * 2448, 3264, 2448, '2022-07-06 14:02:44', 'exif', 1)
    infos = {'IMG_20220706_145347.jpg': k, 'Recovered_jpg_file(1385).jpg': d}
    sr = rf.get_detailed_selection_reason(
        'IMG_20220706_145347.jpg',
        ['IMG_20220706_145347.jpg', 'Recovered_jpg_file(1385).jpg'], infos)
    dr = rf.get_deletion_reason('Recovered_jpg_file(1385).jpg',
                                'IMG_20220706_145347.jpg', infos)
    P(f'[{lang}] E1 selection reason names the name-originality gate',
      ('name originality' in sr) or ('\u0623\u0635\u0627\u0644\u0629 \u0627\u0644\u0627\u0633\u0645' in sr),
      sr.splitlines()[0])
    P(f'[{lang}] E1 deletion reason does the same',
      ('name originality' in dr) or ('\u0623\u0635\u0627\u0644\u0629 \u0627\u0644\u0627\u0633\u0645' in dr),
      dr.splitlines()[0])
    P(f'[{lang}] E1 it still names the advantage the deleted file really had',
      ('older' in dr.lower() or 'date' in dr.lower()
       or '\u062a\u0627\u0631\u064a\u062e' in dr), dr)

    # E2 the note whose ABSENCE made the reports unreadable: two different dates
    # printed side by side, the date criterion neutralised, and no explanation.
    k2 = info(0.9, 2560 * 1536, 2560, 1536, '2022-07-20 00:00:00', 'filename', 6)
    d2i = info(0.9, 2560 * 1536, 2560, 1536, '2022-07-20 16:42:06', 'exif', 6)
    infos2 = {'samsung.jpg': k2, '20220720_gallery.jpg': d2i}
    sr2 = rf.get_detailed_selection_reason(
        'samsung.jpg', ['samsung.jpg', '20220720_gallery.jpg'], infos2)
    P(f'[{lang}] E2 a neutralised date criterion is EXPLAINED by the day-level note',
      ('day-level precision' in sr2) or ('\u062f\u0642\u064a\u0642\u062a\u0647 \u0627\u0644\u064a\u0648\u0645' in sr2),
      sr2)

    # E3 a genuine multi-day gap still wins on the DATE criterion and says so.
    k3 = info(1.36, 1080 * 2340, 1080, 2340, '2025-04-25 04:21:34', 'exif', 8)
    d3i = info(1.36, 1080 * 2340, 1080, 2340, '2025-05-25 23:32:21', 'exif', 8)
    infos3 = {'a.jpg': k3, 'b.jpg': d3i}
    sr3 = rf.get_detailed_selection_reason('a.jpg', ['a.jpg', 'b.jpg'], infos3)
    P(f'[{lang}] E3 a real month-apart gap still reports the DATE',
      ('older date' in sr3.lower()) or ('\u062a\u0627\u0631\u064a\u062e \u0623\u0642\u062f\u0645' in sr3),
      sr3.splitlines()[0])

    # E3b THE user's exact request: when the DATE decides, the report must show
    # that it was the date AND where each date came from -- so a photo whose date
    # lives in its own name can never again be reported as kept for "filename
    # importance".
    k3b = info(1.36, 1080 * 2340, 1080, 2340, '2025-04-25 04:21:34', 'filename', 8)
    d3b = info(1.36, 1080 * 2340, 1080, 2340, '2025-05-25 23:32:21', 'exif', 8)
    infos3b = {'a.jpg': k3b, 'b.jpg': d3b}
    sr3b = rf.get_detailed_selection_reason('a.jpg', ['a.jpg', 'b.jpg'], infos3b)
    dr3b = rf.get_deletion_reason('b.jpg', 'a.jpg', infos3b)
    P(f'[{lang}] E3b a date read from the NAME is labelled as coming from the name',
      ('from filename' in sr3b) or ('\u0645\u0646 \u0627\u0633\u0645 \u0627\u0644\u0645\u0644\u0641' in sr3b),
      sr3b.splitlines()[0])
    P(f'[{lang}] E3b the competing EXIF date is labelled as coming from EXIF',
      ('from EXIF' in sr3b) or ('\u0645\u0646 EXIF' in sr3b), sr3b.splitlines()[0])
    P(f'[{lang}] E3b the deletion reason carries the same provenance',
      ('from filename' in dr3b or '\u0645\u0646 \u0627\u0633\u0645 \u0627\u0644\u0645\u0644\u0641' in dr3b)
      and ('from EXIF' in dr3b or '\u0645\u0646 EXIF' in dr3b), dr3b.splitlines()[0])

    # E4 no reason line may ever print a missing-translation placeholder.
    for reason in (sr, dr, sr2, sr3, sr3b, dr3b):
        P(f'[{lang}] E4 no "[Missing:" leaks into a reason line',
          '[Missing' not in reason, reason[:90])

    # E6 the gate must not SWALLOW the other evidence. This is the shape of the
    # 12 645 groups round 15 found: a real named photo next to a machine carve
    # that carries no date at all.
    #
    # Round 21 improved on what this originally asserted. The gate outranks the
    # weighted sum when RANKING, but it is only the HEADLINE when it is what made
    # the difference. Here the date genuinely favoured the kept file (the carve
    # has none), so the honest headline is the DATE -- the user's priority #1 --
    # and the name class is reported as a note. That is exactly the inversion the
    # user complained about, now fixed in both directions: a date-based choice is
    # never again reported as a name-based one, and vice versa.
    k6 = info(2.05, 1080 * 2340, 1080, 2340, '2025-06-26 14:08:22', 'filename', 7)
    d6 = info(2.05, 1080 * 2340, 1080, 2340, 'Unknown', 'none', 6)
    infos6 = {'Screenshot_20250626_140822_Gallery.jpg': k6,
              'img_1080x2340x24_020414.jpg': d6}
    sr6 = rf.get_detailed_selection_reason(
        'Screenshot_20250626_140822_Gallery.jpg',
        ['Screenshot_20250626_140822_Gallery.jpg', 'img_1080x2340x24_020414.jpg'],
        infos6)
    sr6_head = sr6.splitlines()[0]
    P(f'[{lang}] E6 the DATE that really won is the headline, not the name',
      ('older date' in sr6_head.lower()) or ('\u062a\u0627\u0631\u064a\u062e \u0623\u0642\u062f\u0645' in sr6_head),
      sr6_head)
    P(f'[{lang}] E6 ...and it shows the date came FROM THE NAME',
      ('from filename' in sr6_head) or ('\u0645\u0646 \u0627\u0633\u0645 \u0627\u0644\u0645\u0644\u0641' in sr6_head),
      sr6_head)
    P(f'[{lang}] E6 ...while the name originality stays visible as a note',
      ('name originality' in sr6) or ('\u0623\u0635\u0627\u0644\u0629 \u0627\u0644\u0627\u0633\u0645' in sr6),
      sr6)

i18n.set_language('en')

# E5 the report rebuilds the SAME scoretable the engine used, so a reason can
# never describe a decision the engine did not make.
table = rf._score_table_for_group(['a.jpg', 'b.jpg'],
                                  {'a.jpg': info(1.0, 100, 10, 10, '2020-01-01 00:00:00',
                                                 'filename', 6),
                                   'b.jpg': info(1.0, 100, 10, 10, '2020-01-01 00:00:00',
                                                 'filename', 6)})
P('E5 the report score table is rebuilt and comparable',
  table is not None and set(table) == {'a.jpg', 'b.jpg'}, str(table))
P('E5 the report knows the provenance class of a file',
  rf._provenance_of('Recovered_jpg_file(1).jpg') == NP.CLASS_RECOVERED
  and rf._provenance_of('IMG_0001.jpg') == NP.CLASS_ORIGINAL)

# =====================================================================
SEP('F.  every sector inherits the fix')
# =====================================================================
# All sectors drink from the same two sources: extract_date_from_filename() and
# compute_date_scores(). Both are fixed, so video / office / archives / other all
# benefit -- without merging the engines.

from src.core.video_file_selector import (                            # noqa: E402
    VideoFileSelector, get_video_date)

# F1 video: the time in the name is now read, so two clean camera names 40
# minutes apart are decided by the DATE instead of "every criterion tied".
v1 = WORK / 'v1'
v1.mkdir()
vid_new = v1 / 'CAM_20200101_143022.mp4'
vid_old = v1 / 'CAM_20200101_135000.mp4'
vid_new.write_bytes(b'\x00' * 2048)
vid_old.write_bytes(b'\x00' * 2048)
stamp = datetime(2020, 1, 1, 15, 10, 0).timestamp()
os.utime(str(vid_new), (stamp, stamp))
os.utime(str(vid_old), (stamp, stamp))
vd, vsrc = get_video_date(str(vid_new))
P('F1 video date now carries the time from the name',
  vd == datetime(2020, 1, 1, 14, 30, 22) and vsrc == 'filename', f'{vd} / {vsrc}')
vkept, vdec = VideoFileSelector().select_best_file([str(vid_new), str(vid_old)])
P('F1 the OLDER video now wins on the date (was a tie decided by path)',
  Path(vkept).name == 'CAM_20200101_135000.mp4', Path(vkept).name)
_reasons = ' '.join(vdec[str(vkept)]['reasons'])
P('F1 the video report says it was decided BY THE DATE',
  'decided by the older date' in _reasons, _reasons)

# F2 office / archives / other: FileSelector with fallback_mtime=True. A filename
# date at midnight next to an older modification time on the SAME day is a tie
# (honest), but on a DIFFERENT day the date decides.
o1 = WORK / 'o1'
o1.mkdir()
doc_named = o1 / 'report_20240115.docx'
doc_plain = o1 / 'report.docx'
doc_named.write_bytes(b'payload')
doc_plain.write_bytes(b'payload')
os.utime(str(doc_named), (datetime(2024, 1, 15, 9, 30).timestamp(),) * 2)
os.utime(str(doc_plain), (datetime(2024, 1, 14, 8, 0).timestamp(),) * 2)
okept = sel.select_best_file([str(doc_named), str(doc_plain)], fallback_mtime=True)
P('F2 office: a DIFFERENT day is decided by the date (older mtime wins)',
  Path(okept).name == 'report.docx', Path(okept).name)

o2 = WORK / 'o2'
o2.mkdir()
same_a = o2 / 'report_20240115.docx'
same_b = o2 / 'report.docx'
same_a.write_bytes(b'payload')
same_b.write_bytes(b'payload')
os.utime(str(same_a), (datetime(2024, 1, 15, 9, 30).timestamp(),) * 2)
os.utime(str(same_b), (datetime(2024, 1, 15, 8, 0).timestamp(),) * 2)
dsame = compute_date_scores(
    {'a': datetime(2024, 1, 15), 'b': datetime(2024, 1, 15, 8, 0)},
    True, {'a': 'filename', 'b': 'modified'})
P('F2 office: the SAME day with a day-level name stays an honest tie',
  len(set(dsame.values())) == 1, str(dsame))

# F3 a recovered-named office document loses to a clean one too (shared engine).
o3 = WORK / 'o3'
o3.mkdir()
clean_doc = o3 / 'contract_20240115.docx'
rec_doc = o3 / 'Recovered_contract(3).docx'
clean_doc.write_bytes(b'payload')
rec_doc.write_bytes(b'payload')
okept3 = sel.select_best_file([str(clean_doc), str(rec_doc)], fallback_mtime=True)
P('F3 office: a recovered name loses to a clean one',
  Path(okept3).name == 'contract_20240115.docx', Path(okept3).name)

# F4 the video engine was NOT touched: it keeps its own selector and its own
# provenance classes, exactly as the user asked (no engine merging in this round).
P('F4 the image selector still knows nothing about the video engine',
  'video' not in read_src('src/core/file_selector.py').lower())
P('F4 the video selector keeps its own provenance taxonomy',
  'CLASS_RECOVERED' in read_src('src/core/video_file_selector.py'))

# F5 the two sectors nobody had exercised: ARCHIVES and OTHER. They reach the
# engine through the very same call the office files use --
# duplicate_detector.delete_duplicate_files() ->
#     file_selector.select_best_file(files, fallback_mtime=True)
# -- so they inherit every fix without a line of their own.
a1 = WORK / 'a1'
a1.mkdir()
zip_clean = a1 / 'backup_20240115.zip'
zip_rec = a1 / 'Recovered_backup(7).zip'
zip_clean.write_bytes(b'PK\x03\x04payload')
zip_rec.write_bytes(b'PK\x03\x04payload')
os.utime(str(zip_clean), (datetime(2024, 1, 15, 9, 30).timestamp(),) * 2)
os.utime(str(zip_rec), (datetime(2024, 1, 15, 9, 30).timestamp(),) * 2)
P('F5 archives: a recovered name loses to a clean one (shared engine)',
  Path(sel.select_best_file([str(zip_clean), str(zip_rec)],
                            fallback_mtime=True)).name == 'backup_20240115.zip',
  Path(sel.select_best_file([str(zip_clean), str(zip_rec)],
                            fallback_mtime=True)).name)

t1 = WORK / 't1'
t1.mkdir()
txt_new = t1 / 'notes_20240315.txt'
txt_old = t1 / 'notes.txt'
txt_new.write_bytes(b'payload')
txt_old.write_bytes(b'payload')
os.utime(str(txt_new), (datetime(2024, 3, 15, 9, 0).timestamp(),) * 2)
os.utime(str(txt_old), (datetime(2024, 3, 14, 9, 0).timestamp(),) * 2)
P('F5 other: a different DAY is decided by the date, not by the name',
  Path(sel.select_best_file([str(txt_new), str(txt_old)],
                            fallback_mtime=True)).name == 'notes.txt',
  Path(sel.select_best_file([str(txt_new), str(txt_old)],
                            fallback_mtime=True)).name)

# F6 THE question the user asked outright: is round 21's CONDITIONAL gate only
# an image thing? No. It lives in date_criterion_decides(), which the image
# engine and the video engine BOTH call, so an older '(N)' copy survives on a
# real multi-day gap in EVERY sector -- the user's #1 priority is honoured
# everywhere, and a seconds/hours gap still lets the clean name win everywhere.
o6 = WORK / 'o6'
o6.mkdir()
off_old_copy = o6 / 'report (96).docx'
off_new_clean = o6 / 'report.docx'
off_old_copy.write_bytes(b'payload')
off_new_clean.write_bytes(b'payload')
os.utime(str(off_old_copy), (datetime(2024, 1, 10, 9, 0).timestamp(),) * 2)
os.utime(str(off_new_clean), (datetime(2024, 2, 20, 9, 0).timestamp(),) * 2)
P('F6 office: an older "(96)" copy SURVIVES a 41-day gap (date outranks the gate)',
  Path(sel.select_best_file([str(off_old_copy), str(off_new_clean)],
                            fallback_mtime=True)).name == 'report (96).docx',
  Path(sel.select_best_file([str(off_old_copy), str(off_new_clean)],
                            fallback_mtime=True)).name)

o7 = WORK / 'o7'
o7.mkdir()
off_same_copy = o7 / 'report (96).docx'
off_same_clean = o7 / 'report.docx'
off_same_copy.write_bytes(b'payload')
off_same_clean.write_bytes(b'payload')
os.utime(str(off_same_copy), (datetime(2024, 1, 10, 9, 0).timestamp(),) * 2)
os.utime(str(off_same_clean), (datetime(2024, 1, 10, 14, 0).timestamp(),) * 2)
P('F6 office: a 5-HOUR gap is not a real difference -> the clean name wins',
  Path(sel.select_best_file([str(off_same_copy), str(off_same_clean)],
                            fallback_mtime=True)).name == 'report.docx',
  Path(sel.select_best_file([str(off_same_copy), str(off_same_clean)],
                            fallback_mtime=True)).name)

v6 = WORK / 'v6'
v6.mkdir()
vid_old_copy = v6 / 'VID_20200101_120000 (2).mp4'
vid_new_clean = v6 / 'VID_20200201_120000.mp4'
vid_old_copy.write_bytes(b'\x00' * 2048)
vid_new_clean.write_bytes(b'\x00' * 2048)
_vstamp = datetime(2020, 3, 1, 10, 0, 0).timestamp()
os.utime(str(vid_old_copy), (_vstamp, _vstamp))
os.utime(str(vid_new_clean), (_vstamp, _vstamp))
_vkept6, _ = VideoFileSelector().select_best_file(
    [str(vid_old_copy), str(vid_new_clean)])
P('F6 video: an older "(2)" clip SURVIVES a 31-day gap (same conditional gate)',
  Path(_vkept6).name == 'VID_20200101_120000 (2).mp4', Path(_vkept6).name)

v7 = WORK / 'v7'
v7.mkdir()
vid_same_copy = v7 / 'VID_20200101_120000 (2).mp4'
vid_same_clean = v7 / 'VID_20200101_120000.mp4'
vid_same_copy.write_bytes(b'\x00' * 2048)
vid_same_clean.write_bytes(b'\x00' * 2048)
os.utime(str(vid_same_copy), (_vstamp, _vstamp))
os.utime(str(vid_same_clean), (_vstamp, _vstamp))
_vkept7, _ = VideoFileSelector().select_best_file(
    [str(vid_same_copy), str(vid_same_clean)])
P('F6 video: identical timestamps -> the clean name wins (gate applies)',
  Path(_vkept7).name == 'VID_20200101_120000.mp4', Path(_vkept7).name)

v8 = WORK / 'v8'
v8.mkdir()
vid_rec = v8 / 'Recovered_video(4).mp4'
vid_real = v8 / 'VID_20200101_120000.mp4'
vid_rec.write_bytes(b'\x00' * 2048)
vid_real.write_bytes(b'\x00' * 2048)
os.utime(str(vid_rec), (datetime(2019, 1, 1, 10, 0).timestamp(),) * 2)
os.utime(str(vid_real), (datetime(2020, 1, 1, 10, 0).timestamp(),) * 2)
_vkept8, _ = VideoFileSelector().select_best_file([str(vid_rec), str(vid_real)])
P('F6 video: a RECOVERY name stays banned absolutely, even a year older',
  Path(_vkept8).name == 'VID_20200101_120000.mp4', Path(_vkept8).name)

# =====================================================================
SEP('G.  round 21 -- the gate is CONDITIONAL: date first, as configured')
# =====================================================================
# An absolute gate silently inverted the user's priority order, in which DATE
# ranks #1. Measured on the shipped reports it deleted
# 'IMG-20180617-WA0051 (2).jpg' (2018-06-17) in favour of
# 'IMG-20180707-WA0042.jpg' (2018-07-07) purely because of the '(2)' -- a
# WhatsApp DOWNLOAD counter on a different message, which says nothing at all
# about that competitor. The user's ruling:
#   * a copy/'(N)' name that is older by DAYS/months/years SURVIVES (date first);
#   * a seconds/minutes/HOURS gap is not a real difference -> the clean name wins;
#   * a RECOVERY TOOL's name never beats a real user/camera name, whatever the
#     date says -- the program invented that name, so it carries no identity.

_GAP_KEY = 'priorities.name_gate_date_gap_hours'
_saved_gap = config.get(_GAP_KEY, 24)

h1 = WORK / 'h1'
h1.mkdir()
# H1 the real regression: 20 days apart, the copy-named file is the older one.
older_copy = make_img(h1 / 'IMG-20180617-WA0051 (2).jpg', 200, 200)
newer_clean = make_img(h1 / 'IMG-20180707-WA0042.jpg', 200, 200)
kept = sel.select_best_file([str(newer_clean), str(older_copy)])
P('H1 a copy name 20 DAYS older SURVIVES (date is priority #1)',
  Path(kept).name == 'IMG-20180617-WA0051 (2).jpg', Path(kept).name)

# H2 the same shape, only 2 hours apart -> not a real difference.
h2 = WORK / 'h2'
h2.mkdir()
copy_2h = make_img(h2 / '20131213_161353 (1).jpg', 200, 200)
clean_2h = make_img(h2 / '20131213_181353.jpg', 200, 200)
kept = sel.select_best_file([str(copy_2h), str(clean_2h)])
P('H2 a 2-hour gap is NOT a difference -- the clean name wins',
  Path(kept).name == '20131213_181353.jpg', Path(kept).name)

# H3 minutes apart -> same ruling.
h3 = WORK / 'h3'
h3.mkdir()
copy_min = make_img(h3 / '20131213_161353 (1).jpg', 200, 200)
clean_min = make_img(h3 / '20131213_161853.jpg', 200, 200)
kept = sel.select_best_file([str(copy_min), str(clean_min)])
P('H3 a 5-minute gap is NOT a difference -- the clean name wins',
  Path(kept).name == '20131213_161853.jpg', Path(kept).name)

# H4 THE user's explicit ruling: a recovery tool's name never wins, even when its
# date is years older. 'recovered_20100101' carries a real 2010 date AND the
# recovery marker, so this isolates the absolute ban from the threshold.
h4 = WORK / 'h4'
h4.mkdir()
old_recovered = make_img(h4 / 'recovered_20100101.jpg', 200, 200)
new_real = make_img(h4 / 'IMG-20190815-WA0136.jpg', 200, 200)
kept = sel.select_best_file([str(old_recovered), str(new_real)])
P('H4 a recovered name 9 YEARS older still LOSES to a real camera name',
  Path(kept).name == 'IMG-20190815-WA0136.jpg', Path(kept).name)
P('H4 ...and the machine carve is banned absolutely, not by the threshold',
  NP.is_machine_output(NP.provenance_of('recovered_20100101.jpg')) is True
  and NP.is_machine_output(NP.provenance_of('IMG-20180617-WA0051 (2).jpg')) is False)

# H5 no date contest at all -> the name is the only evidence, so the gate stands.
h5 = WORK / 'h5'
h5.mkdir()
copy_nodate = make_img(h5 / 'Coffee copy.jpg', 200, 200)
clean_nodate = make_img(h5 / 'Coffee.jpg', 200, 200)
kept = sel.select_best_file([str(copy_nodate), str(clean_nodate)])
P('H5 with no date to compare, the clean name wins',
  Path(kept).name == 'Coffee.jpg', Path(kept).name)

# H6 the threshold is a real setting, not a hard-coded number.
config.set(_GAP_KEY, 100000)          # never big enough -> the gate is absolute
kept = sel.select_best_file([str(newer_clean), str(older_copy)])
P('H6 a huge threshold makes the gate absolute again (clean name wins)',
  Path(kept).name == 'IMG-20180707-WA0042.jpg', Path(kept).name)
config.set(_GAP_KEY, 0)               # any real gap overrules -> date always wins
kept = sel.select_best_file([str(copy_2h), str(clean_2h)])
P('H7 a zero threshold lets the date decide even a 2-hour gap',
  Path(kept).name == '20131213_161353 (1).jpg', Path(kept).name)
config.set(_GAP_KEY, _saved_gap)

# H8 the helper itself, on the same basis the scores use.
from src.core.file_selector import date_span_seconds                # noqa: E402
P('H8 span is None when only one date is known (no contest)',
  date_span_seconds({'a': datetime(2020, 1, 1), 'b': None},
                    {'a': 'filename', 'b': 'none'}) is None)
P('H8 span is None when a sub-day gap involves a day-level name',
  date_span_seconds({'a': datetime(2020, 1, 1), 'b': datetime(2020, 1, 1, 8, 0)},
                    {'a': 'filename', 'b': 'exif'}) is None)
P('H8 span measures DAYS when the days differ',
  date_span_seconds({'a': datetime(2018, 6, 17), 'b': datetime(2018, 7, 7)},
                    {'a': 'filename', 'b': 'filename'}) == 20 * 86400,
  str(date_span_seconds({'a': datetime(2018, 6, 17), 'b': datetime(2018, 7, 7)},
                        {'a': 'filename', 'b': 'filename'})))

# H9 the report must describe the SAME ruling, and flag the borderline case.
for lang in ('en', 'ar'):
    i18n.set_language(lang)
    k9 = info(0.05, 607 * 1080, 607, 1080, '2018-06-17 00:00:00', 'filename', 2)
    d9 = info(0.05, 607 * 1080, 607, 1080, '2018-07-07 00:00:00', 'filename', 8)
    infos9 = {'IMG-20180617-WA0051 (2).jpg': k9, 'IMG-20180707-WA0042.jpg': d9}
    sr9 = rf.get_detailed_selection_reason(
        'IMG-20180617-WA0051 (2).jpg',
        ['IMG-20180617-WA0051 (2).jpg', 'IMG-20180707-WA0042.jpg'], infos9)
    P(f'[{lang}] H9 the report names the DATE, not the name, for a 20-day gap',
      ('older date' in sr9.lower()) or ('\u062a\u0627\u0631\u064a\u062e \u0623\u0642\u062f\u0645' in sr9),
      sr9.splitlines()[0])
    P(f'[{lang}] H9 ...and does NOT claim name originality decided',
      'name originality' not in sr9 and '\u0623\u0635\u0627\u0644\u0629 \u0627\u0644\u0627\u0633\u0645' not in sr9,
      sr9.splitlines()[0])

    # The borderline case: the gate won although the dates differed by hours.
    k9b = info(0.9, 100, 10, 10, '2013-12-13 18:13:53', 'filename', 6)
    d9b = info(0.9, 100, 10, 10, '2013-12-13 16:13:53', 'filename', 2)
    infos9b = {'20131213_181353.jpg': k9b, '20131213_161353 (1).jpg': d9b}
    sr9b = rf.get_detailed_selection_reason(
        '20131213_181353.jpg', ['20131213_181353.jpg', '20131213_161353 (1).jpg'],
        infos9b)
    P(f'[{lang}] H9 the borderline gate decision carries a REVIEW flag',
      ('review:' in sr9b) or ('\u0645\u0631\u0627\u062c\u0639\u0629:' in sr9b), sr9b)
    P(f'[{lang}] H9 the review flag names the gap and the threshold',
      '24' in sr9b, sr9b)
i18n.set_language('en')

# H10 the video engine reaches the SAME verdicts (no engine merging -- just the
# same conditional rule, so one policy governs every sector).
h10 = WORK / 'h10'
h10.mkdir()
v_old_copy = h10 / 'VID-20180617-WA0051 (2).mp4'
v_new_clean = h10 / 'VID-20180707-WA0042.mp4'
v_old_copy.write_bytes(b'\x00' * 4096)
v_new_clean.write_bytes(b'\x00' * 4096)
vkept, _vdec = VideoFileSelector().select_best_file([str(v_new_clean), str(v_old_copy)])
P('H10 video: a copy name 20 DAYS older also survives there',
  Path(vkept).name == 'VID-20180617-WA0051 (2).mp4', Path(vkept).name)

h11 = WORK / 'h11'
h11.mkdir()
v_rec = h11 / 'recovered_20100101.mp4'
v_real = h11 / 'VID-20190815-WA0136.mp4'
v_rec.write_bytes(b'\x00' * 4096)
v_real.write_bytes(b'\x00' * 4096)
vkept2, _ = VideoFileSelector().select_best_file([str(v_rec), str(v_real)])
P('H10 video: a recovered name 9 YEARS older still loses to a real name',
  Path(vkept2).name == 'VID-20190815-WA0136.mp4', Path(vkept2).name)


# H11 HONESTY: when the DATE and the name both favour the kept file, the report
# must headline the DATE (priority #1) and mention the name only as a note. The
# user's original complaint was exactly this inverted wording.
for lang in ('en', 'ar'):
    i18n.set_language(lang)
    k11 = info(2.87, 3264 * 2448, 3264, 2448, '2019-01-01 09:00:00', 'filename', 8)
    d11 = info(2.87, 3264 * 2448, 3264, 2448, '2022-05-05 09:00:00', 'exif', 1)
    infos11 = {'IMG_20190101_090000.jpg': k11, 'Recovered_jpg_file(77).jpg': d11}
    sr11 = rf.get_detailed_selection_reason(
        'IMG_20190101_090000.jpg',
        ['IMG_20190101_090000.jpg', 'Recovered_jpg_file(77).jpg'], infos11)
    first_line = sr11.splitlines()[0]
    P(f'[{lang}] H11 when the date ALSO decided, the headline is the DATE',
      ('older date' in first_line.lower()) or ('\u062a\u0627\u0631\u064a\u062e \u0623\u0642\u062f\u0645' in first_line),
      first_line)
    P(f'[{lang}] H11 ...and the name originality is still visible, as a note',
      ('name originality' in sr11) or ('\u0623\u0635\u0627\u0644\u0629 \u0627\u0644\u0627\u0633\u0645' in sr11),
      sr11)
i18n.set_language('en')

# H12 ...but when ONLY the name decided, the headline stays the name.
# To isolate that, the weighted criteria must be IDENTICAL on both sides (same
# date, same dimensions, same size, same filename importance). Otherwise the
# weighted sum already favours the kept file and -- per the round 21 honesty rule
# -- the criterion that won is the headline while the name class is only a note.
# The earlier fixture used importance 8 vs 2, which let filename importance win
# the weighted sum and so never actually reached the gate-only case.
for lang in ('en', 'ar'):
    i18n.set_language(lang)
    k12 = info(0.9, 100, 10, 10, '2020-01-01 00:00:00', 'filename', 6)
    d12 = info(0.9, 100, 10, 10, '2020-01-01 00:00:00', 'filename', 6)
    infos12 = {'holiday.jpg': k12, 'Recovered_holiday(3).jpg': d12}
    sr12 = rf.get_detailed_selection_reason(
        'holiday.jpg', ['holiday.jpg', 'Recovered_holiday(3).jpg'], infos12)
    P(f'[{lang}] H12 when only the name decided, the headline is the NAME',
      ('name originality' in sr12.splitlines()[0])
      or ('\u0623\u0635\u0627\u0644\u0629 \u0627\u0644\u0627\u0633\u0645' in sr12.splitlines()[0]),
      sr12.splitlines()[0])
i18n.set_language('en')


# =====================================================================
SEP('H.  the four DEAD settings are gone and changed NOTHING')
# =====================================================================
# Four keys sat in the shipped settings.json and looked like controls:
#
#     exif_priority            modified_name_priority
#     quality_priority         format_priority
#
# Not ONE line of src/ ever read any of them -- verified by grepping every
# .py under src/, tests/, scripts/ and main.py. Editing format_priority to
# prefer PNG would have done nothing at all. That is a worse state than not
# having them: a setting that silently does nothing is a false guarantee,
# exactly what audit P3-8 said about create_backup / preserve_originals.
#
# Deleting them is therefore a pure documentation fix, and this section
# PROVES it: the same groups must yield the same winner with the keys
# present and with them absent.

_DEAD_KEYS = ('exif_priority', 'modified_name_priority',
              'quality_priority', 'format_priority')

_shipped = json.loads(_CFG_BYTES.decode('utf-8')) if _CFG_BYTES else {}
_shipped_prios = _shipped.get('priorities', {})
for _k in _DEAD_KEYS:
    P(f'H1 the dead setting "{_k}" is gone from config/settings.json',
      _k not in _shipped_prios, 'still present')

_cfg_src = read_src('src/core/config.py')
for _k in _DEAD_KEYS:
    _live = [ln for ln in _cfg_src.splitlines()
             if f'"{_k}"' in ln and not ln.strip().startswith('#')]
    P(f'H2 the dead setting "{_k}" is gone from the config.py defaults',
      not _live, _live[:1])

# Nothing anywhere in src/ may read them -- that is what made them dead, and
# it must stay true so nobody wires up a SECOND, conflicting selection path.
_reads = []
for _py in sorted((ROOT / 'src').rglob('*.py')):
    for _i, _ln in enumerate(_py.read_text(encoding='utf-8',
                                           errors='replace').splitlines(), 1):
        if _ln.strip().startswith('#'):
            continue
        if any(f"'{_k}'" in _ln or f'"{_k}"' in _ln for _k in _DEAD_KEYS):
            _reads.append(f'{_py.name}:{_i}')
P('H3 no file under src/ reads any of the four (no phantom control path)',
  not _reads, _reads)

# A missing key must not crash, and must not invent a value.
P('H4 reading a removed key returns the caller default, not a surprise',
  config.get('priorities.exif_priority', 'SENTINEL') == 'SENTINEL'
  and config.get('priorities.format_priority', []) == [],
  str(config.get('priorities.exif_priority', 'SENTINEL')))

# THE proof that this was documentation only: build representative groups
# spanning every gate outcome, decide them WITHOUT the keys, then put the
# keys back with deliberately WRONG values and decide again. Identical
# winners == the keys were inert == removing them changed no decision.
gd = WORK / 'gd'
gd.mkdir()
_GROUPS = [
    # (name, [filenames]) -- covers date-wins, gate-wins, tie-to-name, recovered
    ('older name-dated original vs newer clean',
     ['IMG_20200101_120000.jpg', 'IMG_20100101_120000.jpg']),
    ('recovered carve vs named original',
     ['IMG_20220706_145347.jpg', 'Recovered_jpg_file(1385).jpg']),
    ('numbered copy vs clean, same day',
     ['holiday (2).jpg', 'holiday.jpg']),
    ('older numbered copy vs newer clean, DAYS apart',
     ['photo (96).jpg', 'photo.jpg']),
    ('machine-extracted name vs a real WhatsApp name',
     ['img_1280x853x24_001092.jpg', 'IMG-20240824-WA0015.jpg']),
    ('bare arabic-digit date vs IMG_ (one clean tier)',
     ['\u0662\u0660\u0661\u0660\u0660\u0661\u0660\u0661_\u0661\u0662\u0660\u0660\u0660\u0660.jpg',
      'IMG_20200101_120000.jpg']),
]
_built = {}
for _label, _names in _GROUPS:
    _sub = gd / _names[0].replace(' ', '_').replace('(', '').replace(')', '')
    _sub.mkdir(exist_ok=True)
    _paths = [str(make_img(_sub / _n, 200, 200)) for _n in _names]
    _built[_label] = _paths

_BASELINE = {lbl: sel.select_best_file(paths) for lbl, paths in _built.items()}

# Put them back with values chosen to MAXIMISE any effect they could have.
config.set('priorities.exif_priority', 'newest')
config.set('priorities.modified_name_priority', 'modified')
config.set('priorities.quality_priority', False)
config.set('priorities.format_priority', ['gif', 'bmp'])
_WITH = {lbl: sel.select_best_file(paths) for lbl, paths in _built.items()}
for _k in _DEAD_KEYS:
    config.config.get('priorities', {}).pop(_k, None)

_diff = [lbl for lbl in _BASELINE if _BASELINE[lbl] != _WITH[lbl]]
P('H5 the winner is IDENTICAL with the dead keys present (wrong values!)',
  not _diff, [(lbl, Path(_BASELINE[lbl]).name, Path(_WITH[lbl]).name)
              for lbl in _diff])
P('H5 ...across every gate outcome (date-wins / gate-wins / tie / recovered)',
  len(_BASELINE) == len(_GROUPS) and all(_BASELINE.values()), str(len(_BASELINE)))
P('H5 the four keys are inert again after the experiment',
  not any(_k in config.config.get('priorities', {}) for _k in _DEAD_KEYS))

# What DOES govern the choice must still be there and still work.
P('H6 the real controls survived: order, the four toggles, date_priority, gap',
  config.get('priorities.order') == list(DEFAULT_PRIORITY_ORDER)
  and config.get('priorities.resolution_priority') is True
  and config.get('priorities.size_priority') is True
  and config.get('priorities.filename_priority') is True
  and str(config.get('priorities.date_priority', '')).lower() == 'oldest'
  and config.get('priorities.name_gate_date_gap_hours') is not None,
  str({k: config.get('priorities.' + k) for k in
       ('order', 'date_priority', 'name_gate_date_gap_hours')}))


# =====================================================================
SEP('I.  the machine is left exactly as it was found')
# =====================================================================
_reports_now = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                if _REPORTS_DIR.exists() else [])
P("the user's REAL reports/ folder was never touched by this suite",
  _reports_now == _REPORTS_BEFORE, (set(_reports_now) ^ set(_REPORTS_BEFORE)))

_bin_now = _count_files(_BIN_DIR)
P("not ONE file was removed from the user's recycle-bin",
  _bin_now >= _BIN_BEFORE, f'before={_BIN_BEFORE} now={_bin_now}')

_restore_cfg()
P('settings.json is byte-identical again',
  _CFG_BYTES is None or _CFG_FILE.read_bytes() == _CFG_BYTES)

P('the suite worked only inside its own temp folder',
  WORK.exists() and str(WORK).startswith(tempfile.gettempdir()), str(WORK))

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
