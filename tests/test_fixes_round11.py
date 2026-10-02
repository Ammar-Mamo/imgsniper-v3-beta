# imgSniper v3 -- Round 11 Fix Verification Suite
# Video section: EXACT duplicate detection (byte-for-byte), per extension.
#   * a video registry (8 families, 24 extensions) + a 'video' section with its
#     own recycle bin (duplicates-video) and report prefix (duplicate_video);
#   * three-stage detection: size pre-filter -> first+last SAMPLE pre-filter ->
#     FULL-FILE SHA-256 as the only verdict, keyed (extension, sha256);
#   * video-specific canonical selection: original-looking names beat copy /
#     recovery names, then the OLDER valid date decides, deterministically, and
#     every decision carries readable reasons;
#   * NO content similarity of any kind, and NO new dependency (no ffmpeg,
#     ffprobe, OpenCV, PyAV or moviepy anywhere in the project).
# The image / office / archive / other flows must be untouched: section F
# asserts exactly that.
# Run from project root: python tests/test_fixes_round11.py

import sys, io, os, re, json, shutil, builtins, logging, tempfile, atexit, hashlib, itertools
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# config.set() writes settings.json immediately, so the original bytes are
# restored after the mutating sections AND at interpreter exit (round-7 guard).
_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None
_CFG0 = json.loads(_CFG_BYTES.decode('utf-8')) if _CFG_BYTES else {}


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


def P(name, ok, detail=''):
    global TP, TF
    if ok:
        TP += 1
    else:
        TF += 1
    print('  [' + ('PASS' if ok else 'FAIL') + '] ' + name +
          (' -- ' + str(detail) if detail else ''))


from rich.console import Console                                     # noqa: E402

from src.core.config import config                                   # noqa: E402
from src.core.i18n.i18n import i18n                                  # noqa: E402
from src.core.file_categories import (                               # noqa: E402
    SECTIONS, VIDEO_TYPES, VIDEO_EXTENSIONS, MP4_EXTENSIONS, MOV_EXTENSIONS,
    MKV_EXTENSIONS, AVI_EXTENSIONS, WMV_EXTENSIONS, MPEG_EXTENSIONS,
    WEB_VIDEO_EXTENSIONS, OTHER_VIDEO_EXTENSIONS)
from src.core.video_file_selector import (                           # noqa: E402
    VideoFileSelector, analyze_video_filename, get_video_date,
    video_criterion_weights, CLASS_ORIGINAL, CLASS_NEUTRAL, CLASS_COPY,
    CLASS_RECOVERED, CLASS_WEAK)
from src.core.detectors.video_duplicate_detector import (            # noqa: E402
    VideoDuplicateDetector, calculate_sample_hash, VIDEO_SAMPLE_BYTES,
    VIDEO_MAX_HASH_WORKERS)
from src.core.detectors.duplicate_detector import DuplicateDetector  # noqa: E402
from src.core.file_selector import FileSelector                      # noqa: E402
from src.utils.helpers.date_extractor import date_extractor          # noqa: E402
import src.cli.cli_menu_handler as cmh                               # noqa: E402
import src.cli.cli_operation_handler as coh                          # noqa: E402
import src.cli.main_cli as mcli                                      # noqa: E402

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_round11_'))
RB_ROOT = Path.cwd() / config.get('paths.recycle_bin', 'recycle-bin')
REPORTS_DIR = Path.cwd() / config.get('paths.reports', 'reports')

CONFIRM0 = _CFG0.get('safety', {}).get('confirm_before_delete', True)
DR0 = _CFG0.get('safety', {}).get('dry_run_mode', False)
_lang_backup = i18n.current_language

_moved = []
_reports = []
_orig_input = builtins.input
builtins.input = lambda *a, **k: ''


def newest_report(prefix):
    """Most recent report file for a prefix (None when there is none)."""
    matches = sorted(REPORTS_DIR.glob(prefix + '_*.txt'), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


# One payload for every "identical" file: 4800 bytes, comfortably over
# filters.min_file_size_bytes (1024), so the scan filters never hide it.
PAYLOAD = b'IMGSNIPER-ROUND11-VIDEO-' * 200


def write_video(folder: Path, name: str, payload: bytes = PAYLOAD,
                stamp=(2020, 1, 1)) -> Path:
    """Create a fake video file with a fixed size and modification time."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(payload)
    when = datetime(*stamp).timestamp()
    os.utime(path, (when, when))
    return path


detector = VideoDuplicateDetector()
VIDEO_SPEC = SECTIONS['video']

# --------------------------------------------------------------------------
SEP('A. Registry: one video table, one section descriptor, one generated menu')
# --------------------------------------------------------------------------
EXPECTED_MP4 = ['.mp4', '.m4v']
EXPECTED_MOV = ['.mov']
EXPECTED_MKV = ['.mkv']
EXPECTED_AVI = ['.avi']
EXPECTED_WMV = ['.wmv', '.asf']
EXPECTED_MPEG = ['.mpg', '.mpeg', '.m2v', '.m2ts', '.mts', '.vob']
EXPECTED_WEB = ['.webm', '.ogv']
EXPECTED_OTHER_VIDEO = ['.flv', '.f4v', '.3gp', '.3g2', '.rm', '.rmvb',
                        '.divx', '.mxf', '.insv']

P('MP4 covers the ISO-BMFF family (mp4 + the Apple m4v variant)',
  MP4_EXTENSIONS == EXPECTED_MP4, MP4_EXTENSIONS)
P('MOV / MKV / AVI are one container each',
  MOV_EXTENSIONS == EXPECTED_MOV and MKV_EXTENSIONS == EXPECTED_MKV
  and AVI_EXTENSIONS == EXPECTED_AVI,
  (MOV_EXTENSIONS, MKV_EXTENSIONS, AVI_EXTENSIONS))
P('WMV carries the Windows Media pair (wmv + asf)',
  WMV_EXTENSIONS == EXPECTED_WMV, WMV_EXTENSIONS)
P('MPEG covers the programme / transport-stream family',
  MPEG_EXTENSIONS == EXPECTED_MPEG, MPEG_EXTENSIONS)
P('web video and the remaining containers have their own entries',
  WEB_VIDEO_EXTENSIONS == EXPECTED_WEB
  and OTHER_VIDEO_EXTENSIONS == EXPECTED_OTHER_VIDEO,
  (WEB_VIDEO_EXTENSIONS, OTHER_VIDEO_EXTENSIONS))

video_ids = [option[0] for option in VIDEO_SPEC['options']]
P('the video menu offers eight families plus the combined entry',
  video_ids == ['mp4', 'mov', 'mkv', 'avi', 'wmv', 'mpeg', 'web',
                'video_other', 'all'], video_ids)
P('the combined entry is the union of every family (24 extensions)',
  VIDEO_SPEC['options'][-1][1] == VIDEO_EXTENSIONS
  and len(VIDEO_EXTENSIONS) == 24, len(VIDEO_EXTENSIONS))
P('every video extension is well-formed, lowercase and unique',
  len(set(VIDEO_EXTENSIONS)) == len(VIDEO_EXTENSIONS)
  and all(ext.startswith('.') and ext == ext.lower() and ext[1:].isalnum()
          for ext in VIDEO_EXTENSIONS), VIDEO_EXTENSIONS)

overlaps = [(a, b) for a, b in itertools.combinations(VIDEO_TYPES.values(), 2)
            if set(a) & set(b)]
P('no extension is claimed by two different video options', not overlaps, overlaps)

P('the section descriptor points at its own bin, report prefix and labels',
  VIDEO_SPEC['engine'] == 'video'
  and VIDEO_SPEC['recycle_subfolder'] == 'duplicates-video'
  and VIDEO_SPEC['report_prefix'] == 'duplicate_video'
  and VIDEO_SPEC['report_title_key'] == 'reports.video_duplicates_title'
  and VIDEO_SPEC['found_key'] == 'video_operations.found_files'
  and VIDEO_SPEC['no_duplicates_key'] == 'video_operations.no_duplicates_found',
  {key: value for key, value in VIDEO_SPEC.items() if key != 'options'})

P('the other sections kept their descriptors untouched (no engine key)',
  all(SECTIONS[key].get('engine') is None for key in ('office', 'archives', 'other'))
  and SECTIONS['office']['recycle_subfolder'] == 'duplicates-office'
  and SECTIONS['archives']['report_prefix'] == 'duplicate_archives'
  and SECTIONS['other']['report_prefix'] == 'duplicate_other')

# --- labels: every option must say EXACT and name its extensions ------------
missing_en = [label for _o, _e, label in VIDEO_SPEC['options']
              if i18n.get(label).startswith('[Missing')]
P('every video option label exists in English', not missing_en, missing_en)
P('the English labels say EXACT and name the extensions they cover',
  'Exact' in i18n.get('video_operations.mp4')
  and 'm4v' in i18n.get('video_operations.mp4')
  and 'asf' in i18n.get('video_operations.wmv')
  and 'vob' in i18n.get('video_operations.mpeg')
  and 'insv' in i18n.get('video_operations.other_formats'),
  i18n.get('video_operations.all'))
P('no label promises similarity -- this phase is exact-only',
  not any('imilar' in i18n.get(label) for _o, _e, label in VIDEO_SPEC['options']))

i18n.set_language('ar')
missing_ar = [label for _o, _e, label in VIDEO_SPEC['options']
              if i18n.get(label).startswith('[Missing')]
P('the same video labels exist in Arabic', not missing_ar, missing_ar)
P('the Arabic labels name the extensions they cover',
  'm4v' in i18n.get('video_operations.mp4')
  and 'webm' in i18n.get('video_operations.web')
  and 'divx' in i18n.get('video_operations.other_formats'))
P('the sample pre-filter line, the exact-only note and the report title exist',
  not i18n.get('common.sample_prefilter').startswith('[Missing')
  and not i18n.get('common.video_exact_only').startswith('[Missing')
  and not i18n.get('reports.video_duplicates_title').startswith('[Missing'))
i18n.set_language('en')

# --- menu: generated from the registry, numbered, Back works ----------------
menu_console = Console(file=io.StringIO(), force_terminal=False, width=200)
menu_handler = cmh.CLIMenuHandler(menu_console)
orig_int_ask = cmh.IntPrompt.ask


def _patch_int(answer):
    cmh.IntPrompt.ask = staticmethod(lambda *a, **k: answer)


def _unpatch_int():
    cmh.IntPrompt.ask = orig_int_ask


def _patch_int_seq(answers):
    cmh.IntPrompt.ask = staticmethod(lambda *a, **k: next(answers))


_patch_int('0')
back_pick = menu_handler.show_section_menu('video')
_unpatch_int()
menu_text = menu_console.file.getvalue()

P('the video menu lists every option plus Back', back_pick is None
  and all(i18n.get(label) in menu_text for _o, _e, label in VIDEO_SPEC['options'])
  and i18n.get('common.back') in menu_text)
P('the menu lines are numbered 1..9, and 0 leaves the section',
  all((str(i) + ' - ') in menu_text for i in range(1, 10)) and back_pick is None,
  back_pick)

_patch_int('5')
wmv_pick = menu_handler.show_section_menu('video')
_unpatch_int()
P('entry 5 selects the WMV family', wmv_pick == 'wmv', wmv_pick)
_patch_int('6')
mpeg_pick = menu_handler.show_section_menu('video')
_unpatch_int()
P('entry 6 selects the MPEG family', mpeg_pick == 'mpeg', mpeg_pick)
_patch_int('9')
all_pick = menu_handler.show_section_menu('video')
_unpatch_int()
P('the combined entry is still last (9)', all_pick == 'all', all_pick)

# --- main menu: entry 2 now opens the video section ------------------------
section_calls = []
coming_soon_calls = []
orig_run_section = mcli.MainCLI._run_section
orig_coming_soon = mcli.MainCLI._show_coming_soon
mcli.MainCLI._run_section = lambda self, key: section_calls.append(key)
mcli.MainCLI._show_coming_soon = lambda self: coming_soon_calls.append(True)

main_cli = mcli.MainCLI()
_patch_int_seq(iter(['2', '3', '4', '5', '7']))
main_cli._show_category_menu()
_unpatch_int()

mcli.MainCLI._run_section = orig_run_section
mcli.MainCLI._show_coming_soon = orig_coming_soon

P('main-menu entry 2 opens the VIDEO section (no longer "coming soon")',
  section_calls[0] == 'video' and not coming_soon_calls, section_calls)
P('entries 3/4/5 still open office / archives / other',
  section_calls[1:4] == ['office', 'archives', 'other'], section_calls)

# --------------------------------------------------------------------------
SEP('B. Filename heuristics: copy / recovery penalties, real dates only')
# --------------------------------------------------------------------------
# --- copy counters: ANY number in parentheses at the end of the stem --------
for name, suffix in (('file (1).mp4', '(1)'), ('file (2).mp4', '(2)'),
                     ('file (15).mp4', '(15)'), ('20180817 (3).mp4', '(3)')):
    analysis = analyze_video_filename(name)
    P('"%s" is a copy counter, not an ordinary number' % name,
      analysis['provenance'] == CLASS_COPY and analysis['copy_suffix'] == suffix,
      (analysis['provenance'], analysis['copy_suffix']))

# --- copy naming, in English and in Arabic ---------------------------------
for name in ('file - Copy.mp4', 'file Copy.mp4', 'file_copy.mp4',
             'file Clone.mp4', 'file duplicate.mp4'):
    analysis = analyze_video_filename(name)
    P('"%s" is treated as a copy' % name,
      analysis['provenance'] == CLASS_COPY, analysis['provenance'])
P('"file - Copy (2).mp4" is a copy AND reports its counter',
  analyze_video_filename('file - Copy (2).mp4')['provenance'] == CLASS_COPY
  and analyze_video_filename('file - Copy (2).mp4')['copy_suffix'] == '(2)')

ARABIC_COPIES = ('file نسخة.mp4', 'file نسخة 1.mp4', 'file نسخة (1).mp4',
                 'file نسخة (2).mp4', 'file مكرر.mp4', 'file نسخة٣.mp4')
for name in ARABIC_COPIES:
    analysis = analyze_video_filename(name)
    P('the Arabic copy pattern "%s" is detected too' % name,
      analysis['provenance'] == CLASS_COPY, analysis['provenance'])

# --- recovery-style names get the lowest class -----------------------------
for name in ('Recovered.mp4', 'recovered.mp4', 'Recovery.mp4',
             'Recovered Video.mp4', 'restored clip.mp4', 'مسترد.mp4',
             'استرداد.mp4'):
    analysis = analyze_video_filename(name)
    P('"%s" is a recovery-style name (lowest priority)' % name,
      analysis['provenance'] == CLASS_RECOVERED, analysis['provenance'])

# --- numbers that are NOT copy suffixes ------------------------------------
for name in ('20180817.mp4', 'VID_20180817_143522.mp4', 'Episode 2.mp4',
             'Video 01.mp4', 'Camera 02.mp4', 'IMG_0001.mp4', 'part 12.mp4',
             'Movie (2018).mp4', '1080p.mp4'):
    analysis = analyze_video_filename(name)
    P('"%s" is NOT penalised just for containing a number' % name,
      analysis['copy_suffix'] is None and analysis['provenance'] >= CLASS_NEUTRAL,
      (analysis['copy_suffix'], analysis['provenance']))

P('a year in parentheses is reported as a year, not as a copy number',
  any('year' in reason or 'سنة' in reason
      for reason in analyze_video_filename('Movie (2018).mp4')['reasons']),
  analyze_video_filename('Movie (2018).mp4')['reasons'])

# --- camera / original-looking names are REWARDED, not punished ------------
for name in ('VID_20180817_143522.mp4', 'Camera 02.mp4', 'Video 01.mp4',
             'original clip.mp4', 'DCIM clip.mp4'):
    analysis = analyze_video_filename(name)
    P('"%s" looks original (camera-style naming)' % name,
      analysis['provenance'] == CLASS_ORIGINAL, analysis['provenance'])
P('a pure-date name is a camera-style original',
  analyze_video_filename('20180817.mp4')['provenance'] == CLASS_ORIGINAL)
P('an original marker never rescues a copy: "Camera Copy.mp4" stays a copy',
  analyze_video_filename('Camera Copy.mp4')['provenance'] == CLASS_COPY)
P('a copy marker never rescues a recovery: "Recovered Copy.mp4" stays recovered',
  analyze_video_filename('Recovered Copy.mp4')['provenance'] == CLASS_RECOVERED)

# --- weak markers sit between a copy and a neutral name --------------------
for name in ('clip backup.mp4', 'clip temp.mp4', 'clip edited.mp4'):
    P('"%s" is a weak marker (below neutral, above a copy)' % name,
      analyze_video_filename(name)['provenance'] == CLASS_WEAK)

# --- the importance scale stays inside the project's 1-9 range --------------
importances = {analyze_video_filename(name)['importance'] for name in (
    'Recovered.mp4', 'file (1).mp4', 'clip backup.mp4', 'Episode 2.mp4',
    '20180817.mp4')}
P('the video importance scale is the same 1-9 range the image engine uses',
  importances == {1, 2, 3, 5, 9}, sorted(importances))
P('the classes are strictly ordered: recovered < copy < weak < neutral < original',
  CLASS_RECOVERED < CLASS_COPY < CLASS_WEAK < CLASS_NEUTRAL < CLASS_ORIGINAL)

# --- dates: validated, never "any long number" -----------------------------
for name, expected in (('20180817.mp4', '2018-08-17'), ('2018-08-17.mp4', '2018-08-17'),
                       ('2018_08_17.mp4', '2018-08-17'),
                       ('VID_20180817_143522.mp4', '2018-08-17'),
                       ('20190920.mp4', '2019-09-20'), ('20210105.mp4', '2021-01-05')):
    found = analyze_video_filename(name)['filename_date']
    P('"%s" yields the valid date %s' % (name, expected),
      bool(found) and found.strftime('%Y-%m-%d') == expected, found)

for name in ('20189999.mp4', '12345678.mp4', '99999999.mp4'):
    analysis = analyze_video_filename(name)
    P('"%s" is NOT a date, and the reasons say it was ignored' % name,
      analysis['filename_date'] is None
      and any('ignored' in reason or 'تجاهل' in reason for reason in analysis['reasons']),
      analysis['reasons'])

# --- detection does not depend on the OS / UI language ---------------------
PROBE_NAMES = ('20180817 (1).mp4', 'file نسخة (2).mp4', 'Recovered.mp4',
               'VID_20180817_143522.mp4', 'Episode 2.mp4')


def probe():
    return [(analyze_video_filename(n)['provenance'],
             analyze_video_filename(n)['copy_suffix'],
             analyze_video_filename(n)['filename_date'],
             len(analyze_video_filename(n)['reasons'])) for n in PROBE_NAMES]


english_probe = probe()
english_reasons = analyze_video_filename('Recovered.mp4')['reasons']
i18n.set_language('ar')
arabic_probe = probe()
arabic_reasons = analyze_video_filename('Recovered.mp4')['reasons']
i18n.set_language('en')

P('the classification is identical in English and Arabic (no locale dependency)',
  english_probe == arabic_probe, (english_probe, arabic_probe))
P('the reasons themselves ARE localized (same count, different wording)',
  len(english_reasons) == len(arabic_reasons) and english_reasons != arabic_reasons,
  (english_reasons[0], arabic_reasons[0]))

# --- get_video_date: filename date first, mtime second, never EXIF ----------
DATE_DIR = TEST_DIR / 'dates'
dated = write_video(DATE_DIR, '20180817.mp4', stamp=(2025, 6, 1))
undated = write_video(DATE_DIR, 'plain clip.mp4', stamp=(2019, 3, 4))
value, source = get_video_date(str(dated))
P('a dated video name wins over the modification time',
  source == 'filename' and value.strftime('%Y-%m-%d') == '2018-08-17', (value, source))
value, source = get_video_date(str(undated))
P('an undated video falls back to its modification time, and says so',
  source == 'modified' and value.year == 2019, (value, source))
value, source = get_video_date(str(TEST_DIR / 'does-not-exist.mp4'))
P('a missing file has no date at all (it can never win on a date)',
  value is None and source == 'none', (value, source))

# --- weights: the user's priority order, minus the unmeasurable criterion ---
weights = video_criterion_weights()
P('a video group is scored on exactly three criteria (no resolution here)',
  set(weights) == {'filename', 'date', 'size'}, weights)
P('the weights keep the configured order on a 3/2/1 scale',
  sorted(weights.values(), reverse=True) == [3.0, 2.0, 1.0]
  and weights['date'] == 3.0, weights)
P('an invalid priority order falls back to the project default',
  video_criterion_weights([9, 9, 9, 9]) == video_criterion_weights(), 
  video_criterion_weights([9, 9, 9, 9]))

# --------------------------------------------------------------------------
SEP('C. Detection: exact bytes only, per extension, three honest stages')
# --------------------------------------------------------------------------
FULL_DIGEST = hashlib.sha256(PAYLOAD).hexdigest()

EXACT_DIR = TEST_DIR / 'exact'
write_video(EXACT_DIR, '20180817.mp4', stamp=(2021, 1, 1))
write_video(EXACT_DIR, '20180817 (1).mp4', stamp=(2020, 1, 1))
write_video(EXACT_DIR, '20180817 (2).mp4', stamp=(2019, 1, 1))
write_video(EXACT_DIR, 'Recovered.mp4', stamp=(2018, 1, 1))
write_video(EXACT_DIR, 'VID_20190101_120000.mp4', stamp=(2024, 1, 1))

CROSS_DIR = TEST_DIR / 'cross'
for name in ('a.mp4', 'a_copy.mp4', 'a.mov', 'a_copy.mov', 'a.mkv', 'a_copy.mkv'):
    write_video(CROSS_DIR, name, stamp=(2022, 5, 5))

scan_console = Console(file=io.StringIO(), force_terminal=False, width=200)
found = detector.find_duplicate_videos([str(EXACT_DIR)], scan_console,
                                       MP4_EXTENSIONS, VIDEO_SPEC)
scan_out = scan_console.file.getvalue()

P('an exact-duplicate group is found (5 identical .mp4 files)',
  found is not None and len(found['duplicates']) == 1
  and len(next(iter(found['duplicates'].values()))) == 5,
  {key[0]: len(files) for key, files in (found or {}).get('duplicates', {}).items()})
group_key = next(iter(found['duplicates']))
P('the group key is (extension, sha256)',
  isinstance(group_key, tuple) and group_key[0] == '.mp4', group_key[0])
P('the verdict is the FULL-FILE SHA-256, not a sample hash',
  group_key[1] == FULL_DIGEST, group_key[1][:16])
P('the reported totals count the copies, not the kept file',
  found['total_scanned'] == 5 and found['total_duplicates'] == 4,
  (found['total_scanned'], found['total_duplicates']))
P('the scan says out loud that it matches exact bytes only',
  i18n.get('video_operations.found_files').format(5) in scan_out
  and i18n.get('common.video_exact_only') in scan_out,
  [line for line in scan_out.splitlines() if 'Exact' in line][:1])
P('the size pre-filter is reported (all five share one size)',
  i18n.get('common.size_prefilter').format(5, 5, 0) in scan_out)
P('the sample pre-filter is reported too',
  i18n.get('common.sample_prefilter').split(' (')[0] in scan_out,
  [line for line in scan_out.splitlines() if 'Sample' in line][:1])

# --- per-extension isolation, also inside the combined "all" scan ----------
cross_console = Console(file=io.StringIO(), force_terminal=False, width=200)
cross_all = detector.find_duplicate_videos([str(CROSS_DIR)], cross_console,
                                           VIDEO_EXTENSIONS, VIDEO_SPEC)
cross_extensions = sorted(key[0] for key in cross_all['duplicates'])
P('identical bytes in three containers give THREE groups, never one',
  cross_extensions == ['.mkv', '.mov', '.mp4'], cross_extensions)
P('no group mixes extensions, even in the combined scan',
  all(len({Path(p).suffix.lower() for p in files}) == 1
      for files in cross_all['duplicates'].values()),
  {key[0]: [Path(p).name for p in files] for key, files in cross_all['duplicates'].items()})
P('all three groups share ONE SHA-256 -- and still stay apart',
  len({key[1] for key in cross_all['duplicates']}) == 1
  and len(cross_all['duplicates']) == 3,
  {key[1][:12] for key in cross_all['duplicates']})
P('the combined scan counts every file it saw',
  cross_all['total_scanned'] == 6 and cross_all['total_duplicates'] == 3,
  (cross_all['total_scanned'], cross_all['total_duplicates']))

mp4_only_console = Console(file=io.StringIO(), force_terminal=False, width=200)
mp4_only = detector.find_duplicate_videos([str(CROSS_DIR)], mp4_only_console,
                                          MP4_EXTENSIONS, VIDEO_SPEC)
P('scanning one family only sees that family (.mp4 here)',
  mp4_only['total_scanned'] == 2
  and sorted(key[0] for key in mp4_only['duplicates']) == ['.mp4'],
  (mp4_only['total_scanned'], [key[0] for key in mp4_only['duplicates']]))

# --- the sample pre-filter: same size, different bytes ---------------------
# Three payloads of the SAME length: diff_a/diff_b share a size but not a byte
# (the sample stage must drop them), same_a/same_b are identical (must survive).
BIG_A = b'A' * (3 * 1024 * 1024)
BIG_B = b'B' * (3 * 1024 * 1024)
BIG_C = b'C' * (3 * 1024 * 1024)
BYTES_DIR = TEST_DIR / 'bytes'
write_video(BYTES_DIR, 'diff_a.mp4', payload=BIG_A)
write_video(BYTES_DIR, 'diff_b.mp4', payload=BIG_B)
write_video(BYTES_DIR, 'same_a.mp4', payload=BIG_C)
write_video(BYTES_DIR, 'same_b.mp4', payload=BIG_C)

bytes_console = Console(file=io.StringIO(), force_terminal=False, width=200)
bytes_found = detector.find_duplicate_videos([str(BYTES_DIR)], bytes_console,
                                             MP4_EXTENSIONS, VIDEO_SPEC)
bytes_out = bytes_console.file.getvalue()
stats = bytes_found['sample_stats']

P('same size but different bytes is NOT a duplicate',
  len(bytes_found['duplicates']) == 1
  and sorted(Path(p).name for p in next(iter(bytes_found['duplicates'].values())))
  == ['same_a.mp4', 'same_b.mp4'],
  {key[0]: sorted(Path(p).name for p in files)
   for key, files in bytes_found['duplicates'].items()})
P('the sample stage dropped the different pair BEFORE any full hash',
  stats['size_candidates'] == 4 and stats['sample_candidates'] == 2, stats)
P('only the surviving pair was fully hashed (6 MiB, not 12 MiB)',
  stats['full_hash_bytes'] == 2 * len(BIG_A)
  and stats['naive_full_bytes'] == 4 * len(BIG_A),
  (stats['full_hash_bytes'], stats['naive_full_bytes']))
P('the sample stage itself read 2 MiB per candidate',
  stats['sampled_bytes'] == 4 * 2 * VIDEO_SAMPLE_BYTES, stats['sampled_bytes'])
P('the console states the saving honestly',
  '8.0 MiB read instead of 12.0 MiB' in bytes_out,
  [line for line in bytes_out.splitlines() if 'Sample' in line][:1])

# --- calculate_sample_hash on its own -------------------------------------
P('identical files share one sample hash',
  calculate_sample_hash(str(BYTES_DIR / 'same_a.mp4'))
  == calculate_sample_hash(str(BYTES_DIR / 'same_b.mp4')))
P('same size but different content gives a DIFFERENT sample hash',
  calculate_sample_hash(str(BYTES_DIR / 'diff_a.mp4'))
  != calculate_sample_hash(str(BYTES_DIR / 'diff_b.mp4')))
P('a sample hash is NOT the full-file hash (so it cannot be a verdict)',
  calculate_sample_hash(str(BYTES_DIR / 'same_a.mp4'))
  != hashlib.sha256(BIG_C).hexdigest())

# A sample that MATCHES proves nothing: two files identical in the first and
# last MiB but different in the middle must survive the sample stage and then be
# separated by the full-file hash. This is the safety property of the stage --
# a sample may only rule files OUT, never mark them duplicates.
MID_DIR = TEST_DIR / 'middle'
HEAD = b'H' * VIDEO_SAMPLE_BYTES
TAIL = b'T' * VIDEO_SAMPLE_BYTES
write_video(MID_DIR, 'mid_a.mp4', payload=HEAD + b'M' * (2 * VIDEO_SAMPLE_BYTES) + TAIL)
write_video(MID_DIR, 'mid_b.mp4', payload=HEAD + b'N' * (2 * VIDEO_SAMPLE_BYTES) + TAIL)

P('two files identical at both ends share one sample hash',
  calculate_sample_hash(str(MID_DIR / 'mid_a.mp4'))
  == calculate_sample_hash(str(MID_DIR / 'mid_b.mp4')))
P('...yet their FULL hashes differ, so they are not duplicates',
  hashlib.sha256((MID_DIR / 'mid_a.mp4').read_bytes()).hexdigest()
  != hashlib.sha256((MID_DIR / 'mid_b.mp4').read_bytes()).hexdigest())

mid_console = Console(file=io.StringIO(), force_terminal=False, width=200)
mid_found = detector.find_duplicate_videos([str(MID_DIR)], mid_console,
                                           MP4_EXTENSIONS, VIDEO_SPEC)
P('a matching sample keeps the pair as candidates (no false drop)',
  mid_found['sample_stats']['sample_candidates'] == 2,
  mid_found['sample_stats'])
P('and the full-file hash then finds no duplicate at all',
  mid_found['duplicates'] == {} and mid_found['total_duplicates'] == 0,
  mid_found['duplicates'])
P('a file smaller than the sample still hashes (whole file is the sample)',
  calculate_sample_hash(str(EXACT_DIR / '20180817.mp4'))
  == calculate_sample_hash(str(EXACT_DIR / '20180817 (1).mp4')))
P('a missing file returns None instead of raising',
  calculate_sample_hash(str(TEST_DIR / 'nope.mp4')) is None)

# --- empty and single-file folders stay honest ----------------------------
EMPTY_DIR = TEST_DIR / 'empty'
EMPTY_DIR.mkdir(parents=True, exist_ok=True)
empty_console = Console(file=io.StringIO(), force_terminal=False, width=200)
empty_found = detector.find_duplicate_videos([str(EMPTY_DIR)], empty_console,
                                             VIDEO_EXTENSIONS, VIDEO_SPEC)
P('a folder with no video at all returns None (not a fake "no duplicates")',
  empty_found is None
  and i18n.get('video_operations.found_files').format(0) in empty_console.file.getvalue(),
  empty_found)

UNIQUE_DIR = TEST_DIR / 'unique'
write_video(UNIQUE_DIR, 'lonely.mp4', stamp=(2023, 2, 2))
write_video(UNIQUE_DIR, 'other-size.mp4', payload=b'Z' * 8000, stamp=(2023, 2, 3))
unique_console = Console(file=io.StringIO(), force_terminal=False, width=200)
unique_found = detector.find_duplicate_videos([str(UNIQUE_DIR)], unique_console,
                                              MP4_EXTENSIONS, VIDEO_SPEC)
unique_out = unique_console.file.getvalue()
P('a unique size is dropped by the pre-filter without reading one byte',
  unique_found['duplicates'] == {} and unique_found['total_scanned'] == 2
  and unique_found['sample_stats'] is None,
  (unique_found['total_scanned'], unique_found['sample_stats']))
P('the user is told that nothing was read and nothing was found',
  i18n.get('common.size_prefilter').format(0, 2, 2) in unique_out
  and i18n.get('common.duplicates_found_generic').format(0) in unique_out)

# --- the SHARED scan filters apply to video too (inherited, not invented) ---
# filters.min_file_size_bytes / max_file_size_mb are read by collect_files()
# for every section, so a video above max_file_size_mb (500 MB by default) is
# skipped by the scan itself -- exactly like a huge archive would be. This is
# asserted here so the behaviour is documented and can never change silently.
LIMIT_DIR = TEST_DIR / 'limit'
write_video(LIMIT_DIR, 'normal.mp4', stamp=(2024, 1, 1))
write_video(LIMIT_DIR, 'normal (1).mp4', stamp=(2023, 1, 1))
max_mb0 = config.get('filters.max_file_size_mb', 500)
config.set('filters.max_file_size_mb', 0.001)      # ~1 KiB: below every test file
limit_console = Console(file=io.StringIO(), force_terminal=False, width=200)
limit_found = detector.find_duplicate_videos([str(LIMIT_DIR)], limit_console,
                                             MP4_EXTENSIONS, VIDEO_SPEC)
config.set('filters.max_file_size_mb', max_mb0)
P('a video above filters.max_file_size_mb is skipped by the shared filter',
  limit_found is None
  and i18n.get('video_operations.found_files').format(0) in limit_console.file.getvalue(),
  limit_found)
P('the same two files are found again once the limit is restored',
  detector.find_duplicate_videos(
      [str(LIMIT_DIR)], Console(file=io.StringIO(), force_terminal=False, width=200),
      MP4_EXTENSIONS, VIDEO_SPEC)['total_duplicates'] == 1)
P('the shipped default leaves ordinary movies inside the scan (500 MB)',
  max_mb0 == 500, max_mb0)

# --------------------------------------------------------------------------
SEP('D. Canonical selection: original names first, then the OLDER date')
# --------------------------------------------------------------------------
selector = VideoFileSelector()

# The exact group the user described: same bytes, most times named by a copy
# suffix, one recovery-style name, and the oldest copy carries a suffix.
KEEP_DIR = TEST_DIR / 'keep'
KEEP_NAMES = {
    '20180817.mp4': (2021, 1, 1),
    '20180817 (1).mp4': (2020, 1, 1),
    '20180817 (2).mp4': (2019, 1, 1),
    'Recovered.mp4': (2018, 1, 1),
    'Movie - Copy.mp4': (2016, 1, 1),
}
for name, stamp in KEEP_NAMES.items():
    write_video(KEEP_DIR, name, stamp=stamp)

keep_mp4 = [str(KEEP_DIR / name) for name in KEEP_NAMES if name.endswith('.mp4')]
kept, decisions = selector.select_best_file(keep_mp4)
P('the original-looking name survives, not the oldest copy-suffixed one',
  Path(kept).name == '20180817.mp4', Path(kept).name)
P('the copy-suffixed file lost even though its date is OLDER in one case',
  not decisions[str(KEEP_DIR / '20180817 (1).mp4')]['is_kept']
  or Path(kept).name != '20180817 (1).mp4')
P('the recovery-style file lost to every clean name',
  not decisions[str(KEEP_DIR / 'Recovered.mp4')]['is_kept'])
P('the copy-named file lost too',
  not decisions[str(KEEP_DIR / 'Movie - Copy.mp4')]['is_kept'])
P('every file in the group gets a decision record',
  set(decisions) == set(keep_mp4), len(decisions))
P('exactly one file per group is marked as kept',
  sum(1 for row in decisions.values() if row['is_kept']) == 1)
P('the decision carries the provenance class, the date and its source',
  decisions[kept]['provenance'] == CLASS_ORIGINAL
  and decisions[kept]['provenance_label']
  and decisions[kept]['date_source'] == 'filename',
  (decisions[kept]['provenance'], decisions[kept]['date_source']))
P('the decision carries per-criterion scores, weights and a total',
  set(decisions[kept]['scores']) == {'filename', 'date', 'size'}
  and set(decisions[kept]['weights']) == {'filename', 'date', 'size'}
  and isinstance(decisions[kept]['total'], float),
  decisions[kept]['scores'])

REASONS = '\n'.join(decisions[kept]['reasons'])
P('the kept file explains itself: original name + its valid date',
  ('original' in REASONS or 'أصلي' in REASONS) and '2018-08-17' in REASONS,
  decisions[kept]['reasons'])
P('the kept file wins on provenance, so no date argument is invented',
  ('provenance' in REASONS or 'أصالة' in REASONS)
  and ('older valid date' not in REASONS and 'newer valid date' not in REASONS),
  decisions[kept]['reasons'])
DELETED_REASONS = '\n'.join(decisions[str(KEEP_DIR / '20180817 (1).mp4')]['reasons'])
P('a deleted file explains ITSELF: the copy suffix is named, and who won',
  '(1)' in DELETED_REASONS and '20180817.mp4' in DELETED_REASONS,
  decisions[str(KEEP_DIR / '20180817 (1).mp4')]['reasons'])
P('the reason engine blames the real criterion (provenance here)',
  'provenance' in DELETED_REASONS or 'أصالة' in DELETED_REASONS,
  decisions[str(KEEP_DIR / '20180817 (1).mp4')]['reasons'])

# --- among equally original names, the OLDER date wins ---------------------
DATES_DIR = TEST_DIR / 'dated'
for name, stamp in (('20180817.mp4', (2024, 1, 1)),
                    ('20190920.mp4', (2023, 1, 1)),
                    ('20210105.mp4', (2022, 1, 1))):
    write_video(DATES_DIR, name, stamp=stamp)
date_paths = [str(DATES_DIR / name) for name in
              ('20180817.mp4', '20190920.mp4', '20210105.mp4')]
kept_dates, date_decisions = selector.select_best_file(date_paths)
P('among equally original names the OLDEST valid date wins (not the newest mtime)',
  Path(kept_dates).name == '20180817.mp4', Path(kept_dates).name)
P('the losing names each say which file won and why',
  all(('20180817.mp4' in '\n'.join(date_decisions[path]['reasons']))
      for path in date_paths if path != kept_dates))
P('the date criterion genuinely decided it (not the provenance tie-break)',
  'date' in '\n'.join(date_decisions[kept_dates]['reasons']),
  date_decisions[kept_dates]['reasons'])

# --- "newest" priority is honoured too ------------------------------------
config.set('priorities.date_priority', 'newest')
kept_newest, _ = selector.select_best_file(date_paths)
config.set('priorities.date_priority', 'oldest')
P('flipping priorities.date_priority to "newest" flips the winner',
  Path(kept_newest).name == '20210105.mp4', Path(kept_newest).name)

# --- determinism: input order must not matter ----------------------------
kept_forward, _ = selector.select_best_file(keep_mp4)
kept_reverse, _ = selector.select_best_file(list(reversed(keep_mp4)))
kept_shuffled, _ = selector.select_best_file(
    keep_mp4[3:] + keep_mp4[:3])
P('the pick is deterministic: reversed input chooses the same file',
  kept_forward == kept_reverse == kept_shuffled, kept_forward)
P('the empty group is handled without raising', selector.select_best_file([]) == (None, {}))

# --- ties are broken deterministically, and the reason says so ------------
TIE_DIR = TEST_DIR / 'tie'
write_video(TIE_DIR, 'alpha.mp4', stamp=(2024, 1, 1))
write_video(TIE_DIR, 'bravo.mp4', stamp=(2024, 1, 1))
tie_paths = [str(TIE_DIR / 'bravo.mp4'), str(TIE_DIR / 'alpha.mp4')]
kept_tie, tie_decisions = selector.select_best_file(tie_paths)
P('a full tie is resolved deterministically (mtime, then path)',
  Path(kept_tie).name == 'alpha.mp4', Path(kept_tie).name)
P('the tie is reported as a tie, never as an invented advantage',
  any('tie' in reason or 'تعدا' in reason or 'تساو' in reason
      for reason in tie_decisions[kept_tie]['reasons']),
  tie_decisions[kept_tie]['reasons'])

# --------------------------------------------------------------------------
SEP('E. Deletion + report: own recycle bin, full reasons, dry-run respected')
# --------------------------------------------------------------------------
RUN_DIR = TEST_DIR / 'run'
# Clean slate for this suite: a previous interrupted run (or an earlier run of
# this same suite) may have left files in the video bin, and the assertions
# below must describe THIS run only. The bin is this project's own output
# directory, so nothing of the user's is ever touched here.
bin_video = RB_ROOT / 'duplicates-video'
if bin_video.exists():
    for leftover in bin_video.rglob('*'):
        if leftover.is_file():
            leftover.unlink()
for name, stamp in KEEP_NAMES.items():
    write_video(RUN_DIR, name, stamp=stamp)

run_console = Console(file=io.StringIO(), force_terminal=False, width=200)
run_found = detector.find_duplicate_videos([str(RUN_DIR)], run_console,
                                           MP4_EXTENSIONS, VIDEO_SPEC)
del_console = Console(file=io.StringIO(), force_terminal=False, width=200)
detector.delete_duplicate_videos(run_found, del_console, VIDEO_SPEC, 'mp4')
del_out = del_console.file.getvalue()

survivors = sorted(p.name for p in RUN_DIR.iterdir())
P('exactly one file survives the group, and it is the original-looking one',
  survivors == ['20180817.mp4'], survivors)

moved = sorted(p.name for p in bin_video.rglob('*.mp4')) if bin_video.exists() else []
_moved.extend(bin_video.rglob('*.mp4'))
P('every removed copy landed in the VIDEO recycle bin',
  moved == ['20180817 (1).mp4', '20180817 (2).mp4', 'Movie - Copy.mp4',
            'Recovered.mp4'], moved)
P('the console points the user at the video recycle bin',
  str(bin_video) in del_out, [line for line in del_out.splitlines()
                              if 'duplicates-video' in line][:1])

run_report = newest_report('duplicate_video')
_reports.append(run_report)
P('the report name carries the prefix AND the scanned option',
  bool(run_report) and run_report.name.startswith('duplicate_video_mp4_'),
  str(run_report))
run_text = run_report.read_text(encoding='utf-8') if run_report else ''

P('the report title is the video one',
  i18n.get('reports.video_duplicates_title') in run_text)
P('the report states the match rule (same extension + size + full SHA-256)',
  i18n.get('reports.video_match_rule') in run_text)
P('the report carries the same system line as the image/office reports',
  'CPU' in run_text and 'Memory' in run_text,
  [line for line in run_text.splitlines() if 'CPU' in line][:1])
P('the report shows the extension, the GROUP SHA-256 and the shared size',
  i18n.get('reports.video_extension').format('.mp4') in run_text
  and hashlib.sha256(PAYLOAD).hexdigest() in run_text
  and str(len(PAYLOAD)) in run_text)
P('the report names the kept file, the removed files and the destination',
  '20180817.mp4' in run_text and '20180817 (1).mp4' in run_text
  and 'Recovered.mp4' in run_text
  and ('Moved to' in run_text or 'نُقل إلى' in run_text))
P('the report shows each name provenance',
  i18n.get('reports.video_provenance').split(':')[0] in run_text
  and (i18n.get('video_reasons.class_copy') in run_text
       or i18n.get('video_reasons.class_recovered') in run_text))
P('the report records the selection reason line by line',
  i18n.get('reports.video_selection_reason') in run_text
  and '(1)' in run_text)
P('the report explains each deletion',
  i18n.get('reports.video_deletion_reason') in run_text)
P('a video report has no meaningless image line (no dimensions / EXIF)',
  'Dimensions' not in run_text and 'x0' not in run_text)

# --- a group that was not deleted still produces a report -----------------
before_reports = {p.name for p in REPORTS_DIR.glob('duplicate_video_*.txt')}
NOOP_DIR = TEST_DIR / 'noop'
write_video(NOOP_DIR, 'a.mp4', stamp=(2024, 1, 1))
write_video(NOOP_DIR, 'b.mp4', stamp=(2023, 1, 1))
noop_console = Console(file=io.StringIO(), force_terminal=False, width=200)
noop_found = detector.find_duplicate_videos([str(NOOP_DIR)], noop_console,
                                            MP4_EXTENSIONS, VIDEO_SPEC)
noop_del_console = Console(file=io.StringIO(), force_terminal=False, width=200)
detector.delete_duplicate_videos(noop_found, noop_del_console, VIDEO_SPEC, 'mp4')
new_reports = sorted({p.name for p in REPORTS_DIR.glob('duplicate_video_*.txt')}
                     - before_reports)
noop_report = REPORTS_DIR / new_reports[0] if new_reports else None
_reports.append(noop_report)
P('a report is written for every video group, deleted or not',
  bool(noop_report), new_reports)
P('the no-duplicate-name group kept the older .mp4 and removed the newer one',
  sorted(p.name for p in NOOP_DIR.iterdir()) == ['b.mp4'],
  sorted(p.name for p in NOOP_DIR.iterdir()))

# --- dry run: nothing may move, and the report must not claim a move ------
config.set('safety.dry_run_mode', True)
DRY_DIR = TEST_DIR / 'dry'
write_video(DRY_DIR, 'clip.mp4', stamp=(2024, 1, 1))
write_video(DRY_DIR, 'clip (1).mp4', stamp=(2023, 1, 1))
dry_console = Console(file=io.StringIO(), force_terminal=False, width=200)
dry_found = detector.find_duplicate_videos([str(DRY_DIR)], dry_console,
                                           MP4_EXTENSIONS, VIDEO_SPEC)
dry_before = {p.name for p in REPORTS_DIR.glob('duplicate_video_*.txt')}
dry_del_console = Console(file=io.StringIO(), force_terminal=False, width=200)
detector.delete_duplicate_videos(dry_found, dry_del_console, VIDEO_SPEC, 'mp4')
dry_out = dry_del_console.file.getvalue()
dry_new = sorted({p.name for p in REPORTS_DIR.glob('duplicate_video_*.txt')}
                 - dry_before)
dry_report = REPORTS_DIR / dry_new[0] if dry_new else None
config.set('safety.dry_run_mode', DR0)
_reports.append(dry_report)

P('dry run leaves both files exactly where they were',
  sorted(p.name for p in DRY_DIR.iterdir()) == ['clip (1).mp4', 'clip.mp4'],
  sorted(p.name for p in DRY_DIR.iterdir()))
P('dry run announces itself and reports what WOULD have moved',
  (i18n.get('safety.dry_run_banner') in dry_out
   or i18n.get('safety.dry_run_summary').split('{')[0] in dry_out), dry_out[-200:])
dry_text = dry_report.read_text(encoding='utf-8') if dry_report and dry_report.exists() else ''
P('a dry-run report never claims a "Moved to" destination',
  'Moved to' not in dry_text and 'نُقل إلى' not in dry_text)
P('the dry-run report still names the file it would have removed',
  'clip (1).mp4' in dry_text)

# --------------------------------------------------------------------------
SEP('F. The whole flow through the CLI handler (menu -> scan -> gate -> bin)')
# --------------------------------------------------------------------------
CLI_DIR = TEST_DIR / 'cli'
write_video(CLI_DIR, '20180817.mp4', stamp=(2024, 1, 1))
write_video(CLI_DIR, '20180817 (1).mp4', stamp=(2023, 1, 1))
write_video(CLI_DIR, 'clip.mov', stamp=(2023, 1, 1))          # other family
write_video(CLI_DIR, 'notes.docx', stamp=(2023, 1, 1))        # not a video at all

config.set('safety.confirm_before_delete', False)
cli_console = Console(file=io.StringIO(), force_terminal=False, width=200)
cli_handler = coh.CLIOperationHandler(cli_console, menu_handler)
cli_handler.menu_handler.get_folders = lambda: [str(CLI_DIR)]
cli_handler.handle_duplicate_files('video', MP4_EXTENSIONS, 'mp4')
cli_out = cli_console.file.getvalue()
config.set('safety.confirm_before_delete', CONFIRM0)

P('the CLI routes the video section to the VIDEO engine (sample stage ran)',
  i18n.get('common.sample_prefilter').split(' (')[0] in cli_out,
  [line for line in cli_out.splitlines() if 'Sample' in line][:1])
cli_moved = [p for p in bin_video.rglob('20180817 (1).mp4')
             if p.parent.name == 'cli']
P('the CLI flow kept the original and moved the copy into duplicates-video',
  (CLI_DIR / '20180817.mp4').exists() and not (CLI_DIR / '20180817 (1).mp4').exists()
  and len(cli_moved) == 1, [str(p) for p in cli_moved])
_moved.extend(cli_moved)
P('another family and a non-video file in the same folder are untouched',
  (CLI_DIR / 'clip.mov').exists() and (CLI_DIR / 'notes.docx').exists())
cli_report = newest_report('duplicate_video_mp4')
_reports.append(cli_report)
P('the CLI flow ends with a duplicate_video_mp4_ report naming the moved file',
  bool(cli_report) and cli_report.name.startswith('duplicate_video_mp4_')
  and '20180817 (1).mp4' in cli_report.read_text(encoding='utf-8'), str(cli_report))
P('the console confirms the report path',
  cli_report is not None and cli_report.name in cli_out)

CLEAN_DIR = TEST_DIR / 'clean'
write_video(CLEAN_DIR, 'solo.mp4', stamp=(2024, 1, 1))
clean_console = Console(file=io.StringIO(), force_terminal=False, width=200)
clean_handler = coh.CLIOperationHandler(clean_console, menu_handler)
clean_handler.menu_handler.get_folders = lambda: [str(CLEAN_DIR)]
clean_handler.handle_duplicate_files('video', MP4_EXTENSIONS, 'mp4')
P('a folder without duplicates says so (no report, no fake success)',
  i18n.get('video_operations.no_duplicates_found') in clean_console.file.getvalue()
  and (CLEAN_DIR / 'solo.mp4').exists())

# --------------------------------------------------------------------------
SEP('G. Guard rails: the old flows, the shared heuristics, the footprint')
# --------------------------------------------------------------------------
# 1) The generic (office/archive/other) detector is NOT a video detector.
plain_detector = DuplicateDetector()
P('the shared detector has no video entry point (no cross-contamination)',
  not hasattr(plain_detector, 'find_duplicate_videos')
  and not hasattr(plain_detector, 'delete_duplicate_videos'))
P('the video detector inherits the shared deletion plumbing instead of copying it',
  isinstance(detector, DuplicateDetector)
  and detector._move_files_to_bin.__func__ is DuplicateDetector._move_files_to_bin
  and detector._collect_group_info.__func__ is DuplicateDetector._collect_group_info)

# 2) An office scan still behaves exactly as it did in round 9/10.
REG_DIR = TEST_DIR / 'regression'
write_video(REG_DIR, 'report.docx', stamp=(2024, 1, 1))
write_video(REG_DIR, 'report_copy.docx', stamp=(2023, 1, 1))
reg_console = Console(file=io.StringIO(), force_terminal=False, width=200)
reg_found = plain_detector.find_duplicate_files([str(REG_DIR)], reg_console,
                                                ['.docx'], SECTIONS['office'])
P('an office scan still groups (extension, sha256) and reports the same totals',
  len(reg_found['duplicates']) == 1 and reg_found['total_duplicates'] == 1
  and next(iter(reg_found['duplicates']))[0] == '.docx'
  and 'sample_stats' not in reg_found,
  {key[0]: len(files) for key, files in reg_found['duplicates'].items()})
P('the office scan never mentions the sample pre-filter',
  'Sample pre-filter' not in reg_console.file.getvalue())

# 3) The SHARED filename heuristics are untouched -- this is the rule that
#    keeps image selection exactly as it was in rounds 1-10. ('copy',
#    'recovered', 'duplicate' and ' (1)' were ALREADY in the map before this
#    round; the markers added for video must NOT be.)
importance = date_extractor.filename_importance
VIDEO_ONLY_MARKERS = ('نسخة', 'مكرر', 'تكرار', 'مسترد', 'استرداد', 'استعادة',
                      'احتياطي', 'مؤقت', 'clone', 'recovery', 'restored')
P('date_extractor.filename_importance gained no video-only marker',
  not any(marker in importance for marker in VIDEO_ONLY_MARKERS),
  [marker for marker in VIDEO_ONLY_MARKERS if marker in importance])
P('the markers that already existed are still there (behaviour preserved)',
  importance.get('copy') == 2 and importance.get('recovered') == 1
  and importance.get(' (1)') == 2, {k: importance.get(k) for k in ('copy', 'recovered', ' (1)')})
P('the shared image importance scale is unchanged (nothing above the 9 shown in reports)',
  max(importance.values()) <= 9 and min(importance.values()) >= 1,
  (min(importance.values()), max(importance.values())))

file_selector_source = (ROOT / 'src' / 'core' / 'file_selector.py').read_text(encoding='utf-8')
P('file_selector.py knows nothing about video (image selector untouched)',
  'video' not in file_selector_source.lower())

# 4) No new dependency, on purpose: this phase reads bytes, it never decodes.
#    Only real IMPORTS and declared DEPENDENCIES are inspected -- the video
#    detector's own documentation mentions ffmpeg/OpenCV precisely to say they
#    are not used, and a naive substring scan would flag that prose.
DECODER_MODULES = {'cv2', 'av', 'moviepy', 'imageio', 'ffmpeg', 'ffprobe',
                   'pymediainfo', 'opencv', 'skvideo'}
imported_decoders = []
for source_file in (ROOT / 'src').rglob('*.py'):
    text = source_file.read_text(encoding='utf-8', errors='replace')
    for module in re.findall(r'^\s*(?:import|from)\s+([A-Za-z0-9_\.]+)', text, re.M):
        if module.split('.')[0].lower() in DECODER_MODULES:
            imported_decoders.append((source_file.name, module))
P('no decoder module is imported anywhere in src/', not imported_decoders,
  imported_decoders)


def declared_packages(path):
    """Package names of a requirements/pyproject file, comments stripped."""
    names = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('['):
            continue
        match = re.match(r'["\']?([A-Za-z0-9_.\-]+)', line.strip('",\' '))
        if match:
            names.append(match.group(1).lower())
    return names


for manifest in ('requirements.txt', 'pyproject.toml'):
    packages = declared_packages(ROOT / manifest)
    offending = [name for name in packages
                 if name in DECODER_MODULES or name.startswith(('opencv', 'av-'))]
    P('%s declares no video/decoder package' % manifest, not offending,
      (offending, packages))

# 5) The video report writer never writes into another section's prefix.
report_source = (ROOT / 'src' / 'utils' / 'reports' /
                 'duplicate_report_generator.py').read_text(encoding='utf-8')
P('the shared report writer was not modified for video',
  'video' not in report_source.lower())

# --------------------------------------------------------------------------
SEP('H. Leave the machine as we found it')
# --------------------------------------------------------------------------
_restore_cfg()
P('settings.json is byte-identical again', _CFG_FILE.read_bytes() == _CFG_BYTES)

for report in _reports:
    if report and Path(report).exists():
        Path(report).unlink()

leftovers = []
if bin_video.exists():
    for path in sorted(bin_video.rglob('*'), key=lambda p: len(str(p)), reverse=True):
        if path.is_file():
            leftovers.append(str(path))
        else:
            try:
                path.rmdir()
            except OSError:
                pass

# The expected contents are exactly the files THIS suite moved: the four copies
# of the run group, the newer file of the noop group and the copy the CLI flow
# removed. A dry run leaves nothing behind, so nothing else may be there either.
expected_leftovers = sorted([
    str(path) for path in bin_video.rglob('*.mp4')
]) if bin_video.exists() else []
P('the video bin holds exactly what this suite moved (and only in this run)',
  len(expected_leftovers) == 6
  and all(str(TEST_DIR) not in name and 'imgsniper_round11_' in name
          for name in expected_leftovers), expected_leftovers)

for name in expected_leftovers:
    try:
        Path(name).unlink()
    except OSError:
        pass
if bin_video.exists():
    for path in sorted(bin_video.rglob('*'), key=lambda p: len(str(p)), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass

P('the video recycle bin is empty again',
  not list(bin_video.rglob('*')) if bin_video.exists() else True)
P('the reports written by this suite are gone',
  not [r for r in _reports if r and Path(r).exists()])
shutil.rmtree(TEST_DIR, ignore_errors=True)
P('the temporary test tree was removed', not TEST_DIR.exists(), str(TEST_DIR))

builtins.input = _orig_input
i18n.current_language = _lang_backup

print('')
print('=' * 70)
print('  SUMMARY')
print('=' * 70)
print('  Total: %d  PASS: %d  FAIL: %d' % (TP + TF, TP, TF))
print('  ALL TESTS PASSED' if TF == 0 else '  SOME TESTS FAILED')
print('=' * 70)
sys.exit(0 if TF == 0 else 1)
