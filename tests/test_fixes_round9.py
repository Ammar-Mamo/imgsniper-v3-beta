# imgSniper v3 -- Round 9 Fix Verification Suite
# Office / Archives / Other sections: SHA-256 duplicate detection with a size
# pre-filter, matched PER EXTENSION, one shared report writer.
#   * registry (file_categories): one descriptor per section drives the menu,
#     the recycle-bin subfolder and the report prefix.
#   * scanning: size pre-filter (stat only) -> SHA-256 on same-size candidates
#     only -> match on (extension, sha256). A .doc never matches a .docx, even
#     in the combined "all types" scan.
#   * deletion: the kept copy is chosen with fallback_mtime=True (no EXIF in
#     these files, so the OLDEST modification time wins) and every removed file
#     lands in the section's own recycle-bin subfolder.
#   * reports: ONE writer for images and sections -- spec=None reproduces the
#     image report exactly; sections get their own title/labels/prefix and no
#     meaningless "Dimensions: 0x0" line.
#   * "Other Files": a generic entry that scans the extensions the user types.
# Run from project root: python tests/test_fixes_round9.py

import sys, io, os, json, shutil, builtins, logging, tempfile, atexit
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


from PIL import Image                                                # noqa: E402
from rich.console import Console                                     # noqa: E402

from src.core.config import config                                   # noqa: E402
from src.core.i18n.i18n import i18n                                  # noqa: E402
from src.core.file_categories import (                               # noqa: E402
    SECTIONS, OFFICE_TYPES, ARCHIVE_TYPES, OFFICE_EXTENSIONS,
    ARCHIVE_EXTENSIONS, normalize_extensions, collect_files, all_extensions,
    WORD_EXTENSIONS, EXCEL_EXTENSIONS, POWERPOINT_EXTENSIONS,
    PDF_EXTENSIONS, OTHER_OFFICE_EXTENSIONS)
from src.core.detectors.duplicate_detector import DuplicateDetector  # noqa: E402
from src.core.file_selector import FileSelector                      # noqa: E402
from src.utils.helpers.date_extractor import date_extractor          # noqa: E402
from src.utils.reports.image_info_extractor import ImageInfoExtractor  # noqa: E402
from src.utils.reports.report_generator import ReportGenerator       # noqa: E402
import src.cli.cli_menu_handler as cmh                               # noqa: E402
import src.cli.cli_operation_handler as coh                          # noqa: E402
import src.cli.main_cli as mcli                                      # noqa: E402

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_round9_'))
RB_ROOT = Path.cwd() / config.get('paths.recycle_bin', 'recycle-bin')
REPORTS_DIR = Path.cwd() / config.get('paths.reports', 'reports')

DR0 = _CFG0.get('safety', {}).get('dry_run_mode', False)
CONFIRM0 = _CFG0.get('safety', {}).get('confirm_before_delete', True)
RBIN0 = _CFG0.get('paths', {}).get('recycle_bin', 'recycle-bin')
_lang_backup = i18n.current_language

# Everything this suite moves/creates outside its temp tree, so section I can
# put the machine back exactly as it was.
_moved = []
_reports = []
_orig_input = builtins.input
builtins.input = lambda *a, **k: ''


def _patch_ask(cls, answer):
    """Make cls.ask(...) return `answer` without touching stdin."""
    original = cls.ask

    def _ask(*args, **kwargs):
        return answer

    cls.ask = staticmethod(_ask)
    return lambda: setattr(cls, 'ask', original)


def newest_report(prefix):
    """Most recent report file for a given prefix (None when there is none)."""
    matches = sorted(REPORTS_DIR.glob(prefix + '_*.txt'), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None





# --------------------------------------------------------------------------
SEP('A. Section registry: office / archives / other')
# --------------------------------------------------------------------------
P('every CLI section is registered',
  set(SECTIONS) == {'office', 'archives', 'other'}, sorted(SECTIONS))

office_ids = [option[0] for option in SECTIONS['office']['options']]
# Round 10 expanded the office families and added the "office_other" entry.
P('office menu offers every type plus one combined entry',
  office_ids == ['word', 'excel', 'powerpoint', 'pdf', 'office_other', 'all'], office_ids)
P('Word is ONE option covering the whole Word family (doc/docx/docm/dotx/rtf/odt/wps)',
  SECTIONS['office']['options'][0][1] == WORD_EXTENSIONS
  and {'.doc', '.docx', '.docm', '.dotx', '.rtf', '.odt', '.wps'} <= set(WORD_EXTENSIONS),
  SECTIONS['office']['options'][0][1])
P('Excel and PowerPoint group their own families the same way',
  SECTIONS['office']['options'][1][1] == EXCEL_EXTENSIONS
  and SECTIONS['office']['options'][2][1] == POWERPOINT_EXTENSIONS
  and {'.xlsx', '.xlsm', '.ods', '.csv'} <= set(EXCEL_EXTENSIONS)
  and {'.pptx', '.pptm', '.pps', '.odp'} <= set(POWERPOINT_EXTENSIONS))
P('fixed-layout documents (PDF + XPS) live inside the office section',
  PDF_EXTENSIONS in [option[1] for option in SECTIONS['office']['options']]
  and SECTIONS['office']['options'][3][1] == PDF_EXTENSIONS)
P('the remaining office formats (Visio/Publisher/OneNote/Access/iWork/...) have their own entry',
  SECTIONS['office']['options'][4][1] == OTHER_OFFICE_EXTENSIONS
  and {'.vsdx', '.pub', '.one', '.accdb', '.mpp', '.pages', '.key'} <= set(OTHER_OFFICE_EXTENSIONS))
P('the combined office entry covers every office extension',
  sorted(SECTIONS['office']['options'][-1][1]) == sorted(OFFICE_EXTENSIONS),
  SECTIONS['office']['options'][-1][1])
P('office extensions are the full set, de-duplicated',
  OFFICE_EXTENSIONS == all_extensions(OFFICE_TYPES)
  and len(OFFICE_EXTENSIONS) == len(set(OFFICE_EXTENSIONS))
  and sorted(OFFICE_EXTENSIONS) == sorted(set(WORD_EXTENSIONS) | set(EXCEL_EXTENSIONS)
                                          | set(POWERPOINT_EXTENSIONS) | set(PDF_EXTENSIONS)
                                          | set(OTHER_OFFICE_EXTENSIONS)),
  (len(OFFICE_EXTENSIONS), OFFICE_EXTENSIONS))

archive_ids = [option[0] for option in SECTIONS['archives']['options']]
P('archives menu offers each extension plus a combined entry',
  archive_ids == ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'all'], archive_ids)
P('the combined archive entry covers every archive extension',
  sorted(SECTIONS['archives']['options'][-1][1]) == sorted(ARCHIVE_EXTENSIONS),
  ARCHIVE_EXTENSIONS)

P('"Other Files" is a generic entry that asks for extensions',
  [option[0] for option in SECTIONS['other']['options']] == ['custom'],
  SECTIONS['other']['options'])

P('each section has its OWN recycle-bin subfolder',
  (SECTIONS['office']['recycle_subfolder'], SECTIONS['archives']['recycle_subfolder'],
   SECTIONS['other']['recycle_subfolder'])
  == ('duplicates-office', 'duplicates-archives', 'duplicates-other'))
P('each section has its own report prefix (images keep "duplicates")',
  (SECTIONS['office']['report_prefix'], SECTIONS['archives']['report_prefix'],
   SECTIONS['other']['report_prefix'])
  == ('duplicate_office', 'duplicate_archives', 'duplicate_other'))

missing = []
for section_key, spec in SECTIONS.items():
    for key in ('label_key', 'report_title_key', 'found_key', 'no_duplicates_key'):
        if i18n.get(spec[key]).startswith('[Missing'):
            missing.append(spec[key])
    for _option, _exts, label_key in spec['options']:
        if i18n.get(label_key).startswith('[Missing'):
            missing.append(label_key)
P('every section/option label exists in English', not missing, missing)

i18n.set_language('ar')
arabic_missing = []
for section_key, spec in SECTIONS.items():
    for key in ('label_key', 'report_title_key', 'found_key', 'no_duplicates_key'):
        if i18n.get(spec[key]).startswith('[Missing'):
            arabic_missing.append(spec[key])
    for _option, _exts, label_key in spec['options']:
        if i18n.get(label_key).startswith('[Missing'):
            arabic_missing.append(label_key)
P('the same labels exist in Arabic', not arabic_missing, arabic_missing)
P('the Arabic settings entry matches the other sections (no gear emoji)',
  i18n.get('categories.settings') == 'الإعدادات', i18n.get('categories.settings'))
i18n.set_language('en')
P('the English settings entry matches the other sections (no gear emoji)',
  i18n.get('categories.settings') == 'Settings', i18n.get('categories.settings'))


# --------------------------------------------------------------------------
SEP('B. Extension normalisation for the "Other Files" prompt')
# --------------------------------------------------------------------------
P('plain names are turned into dot-extensions',
  normalize_extensions('iso, apk') == ['.iso', '.apk'], normalize_extensions('iso, apk'))
P('a leading dot and mixed case are normalised',
  normalize_extensions('.PNG, Zip') == ['.png', '.zip'], normalize_extensions('.PNG, Zip'))
P('spaces, semicolons and pipes all separate answers',
  normalize_extensions('iso apk; mobi|bin') == ['.iso', '.apk', '.mobi', '.bin'],
  normalize_extensions('iso apk; mobi|bin'))
P('duplicates are collapsed',
  normalize_extensions('iso, ISO, .iso') == ['.iso'], normalize_extensions('iso, ISO, .iso'))
P('junk tokens are dropped, real ones survive',
  normalize_extensions('ok, this-is-way-too-long, ., , 7z') == ['.ok', '.7z'],
  normalize_extensions('ok, this-is-way-too-long, ., , 7z'))
P('empty input yields an empty list (the caller shows an error)',
  normalize_extensions('') == [] and normalize_extensions('   ,; ') == [])


# --------------------------------------------------------------------------
SEP('C. SHA-256 scan: size pre-filter + per-extension grouping')
# --------------------------------------------------------------------------
SCAN_DIR = TEST_DIR / 'scan'
SCAN_DIR.mkdir(parents=True, exist_ok=True)

PAYLOAD_A = (b'IMGS-ROUND9-PAYLOAD-A' * 200)[:4096]   # .docx twins + .doc twins
PAYLOAD_B = (b'IMGS-ROUND9-PAYLOAD-B' * 200)[:4096]   # same size, other bytes
PAYLOAD_D = (b'IMGS-ROUND9-PAYLOAD-D' * 400)[:8192]   # unique size

(SCAN_DIR / 'report.docx').write_bytes(PAYLOAD_A)
(SCAN_DIR / 'report_copy.docx').write_bytes(PAYLOAD_A)
(SCAN_DIR / 'same_size_other.docx').write_bytes(PAYLOAD_B)
(SCAN_DIR / 'legacy.doc').write_bytes(PAYLOAD_A)
(SCAN_DIR / 'legacy_copy.doc').write_bytes(PAYLOAD_A)
(SCAN_DIR / 'unique.docx').write_bytes(PAYLOAD_D)
(SCAN_DIR / 'notes.txt').write_bytes(PAYLOAD_A)      # same bytes, wrong extension

WORD_EXTS = SECTIONS['office']['options'][0][1]
scan_console = Console(file=io.StringIO(), force_terminal=False, width=110)
detector = DuplicateDetector()
found = detector.find_duplicate_files([str(SCAN_DIR)], scan_console, WORD_EXTS, SECTIONS['office'])
scan_out = scan_console.file.getvalue()

P('the Word option scans .doc and .docx only (a .txt twin is ignored)',
  found['total_scanned'] == 6, found['total_scanned'])
P('both formats produce their own group',
  len(found['duplicates']) == 2, list(found['duplicates']))
P('group keys are (extension, sha256)',
  all(isinstance(key, tuple) and len(key) == 2 for key in found['duplicates']),
  list(found['duplicates']))
docx_group = sorted(Path(p).name for key, files in found['duplicates'].items()
                    if key[0] == '.docx' for p in files)
P('the .docx twins are one group of two files',
  docx_group == ['report.docx', 'report_copy.docx'], docx_group)
P('the .doc twins are another group (same bytes as the .docx pair)',
  sorted(Path(p).name for key, files in found['duplicates'].items() if key[0] == '.doc'
         for p in files) == ['legacy.doc', 'legacy_copy.doc'])
P('the same-size file with different bytes is NOT a duplicate',
  'same_size_other.docx' not in [Path(p).name for files in found['duplicates'].values() for p in files])
P('a file with a unique size is never read (size pre-filter)',
  'unique.docx' not in [Path(p).name for files in found['duplicates'].values() for p in files])
P('the pre-filter reports how many files were actually read',
  i18n.get('common.size_prefilter').format(5, 6, 1) in scan_out,
  i18n.get('common.size_prefilter').format(5, 6, 1))
P('the duplicate count is reported honestly (one extra copy per group)',
  found['total_duplicates'] == 2, found['total_duplicates'])
P('the found-files line comes from the section labels',
  i18n.get('office_operations.found_files').format(6) in scan_out)

# The combined "all types" scan must not merge different extensions.
(SCAN_DIR / 'doc.pdf').write_bytes(PAYLOAD_A)
(SCAN_DIR / 'doc_copy.pdf').write_bytes(PAYLOAD_A)
all_console = Console(file=io.StringIO(), force_terminal=False, width=110)
found_all = detector.find_duplicate_files(
    [str(SCAN_DIR)], all_console, OFFICE_EXTENSIONS, SECTIONS['office'])
P('the combined scan finds all three extension groups',
  len(found_all['duplicates']) == 3, sorted(key[0] for key in found_all['duplicates']))
P('NO group ever mixes extensions',
  all(Path(p).suffix.lower() == key[0]
      for key, files in found_all['duplicates'].items() for p in files),
  {key[0]: [Path(p).suffix for p in files] for key, files in found_all['duplicates'].items()})
P('the PDF twins form their own group, byte-identical to the Word pair',
  sorted(Path(p).name for key, files in found_all['duplicates'].items() if key[0] == '.pdf'
         for p in files) == ['doc.pdf', 'doc_copy.pdf'])
P('the combined scan also keeps the Word groups intact',
  len([key for key in found_all['duplicates'] if key[0] in ('.doc', '.docx')]) == 2)

# Files already moved to the recycle bin must never come back.
BIN_DIR = SCAN_DIR / 'bin'
BIN_DIR.mkdir(exist_ok=True)
(BIN_DIR / 'report.docx').write_bytes(PAYLOAD_A)
config.set('paths.recycle_bin', str(BIN_DIR))
bin_console = Console(file=io.StringIO(), force_terminal=False, width=110)
found_bin = detector.find_duplicate_files(
    [str(SCAN_DIR)], bin_console, WORD_EXTS, SECTIONS['office'])
P('a copy inside the recycle bin is excluded from the scan',
  found_bin['total_scanned'] == 6
  and 'report.docx' in [Path(p).name for files in found_bin['duplicates'].values() for p in files]
  and len([p for files in found_bin['duplicates'].values() for p in files
           if str(BIN_DIR) in str(p)]) == 0,
  found_bin['total_scanned'])
config.set('paths.recycle_bin', RBIN0)
P('collect_files() with no extensions scans nothing (no accidental full walk)',
  collect_files([str(SCAN_DIR)], []) == [])


# --------------------------------------------------------------------------
SEP('D. Dry-run deletion: nothing moves, the report documents the decision')
# --------------------------------------------------------------------------
DRY_DIR = TEST_DIR / 'dry'
DRY_DIR.mkdir(parents=True, exist_ok=True)
(DRY_DIR / 'budget.xlsx').write_bytes(PAYLOAD_A)
(DRY_DIR / 'budget_copy.xlsx').write_bytes(PAYLOAD_A)
Image.new('RGB', (8, 8), (10, 20, 30)).save(DRY_DIR / 'photo.png')

config.set('safety.dry_run_mode', True)
dry_console = Console(file=io.StringIO(), force_terminal=False, width=110)
dry_found = detector.find_duplicate_files(
    [str(DRY_DIR)], dry_console, OFFICE_TYPES['excel'], SECTIONS['office'])
dry_shots = [(DRY_DIR / 'budget.xlsx').exists(), (DRY_DIR / 'budget_copy.xlsx').exists()]
_ = detector.delete_duplicate_files(dry_found, dry_console, FileSelector(), SECTIONS['office'])
dry_out = dry_console.file.getvalue()

P('an image in the folder is not part of an office scan',
  dry_found['total_scanned'] == 2, dry_found['total_scanned'])
P('dry-run touches nothing on disk',
  dry_shots == [True, True]
  and (DRY_DIR / 'budget.xlsx').exists()
  and (DRY_DIR / 'budget_copy.xlsx').exists())
P('dry-run announces itself once, with the count',
  i18n.get('safety.dry_run_summary').format(1) in dry_out,
  i18n.get('safety.dry_run_summary').format(1))
dry_report = newest_report('duplicate_office')
_reports.append(dry_report)
dry_text = dry_report.read_text(encoding='utf-8') if dry_report else ''
P('the dry-run report exists and names both files',
  bool(dry_report) and 'budget.xlsx' in dry_text and 'budget_copy.xlsx' in dry_text,
  str(dry_report))
P('the dry-run report claims NO move (no "Moved to" line)',
  'Moved to' not in dry_text and 'نُقل إلى' not in dry_text)
P('no spreadsheet reached the recycle bin',
  not list((RB_ROOT / 'duplicates-office').rglob('*.xlsx'))
  if (RB_ROOT / 'duplicates-office').exists() else True)


# --------------------------------------------------------------------------
SEP('E. Real deletion: files move into the section recycle bin')
# --------------------------------------------------------------------------
REAL_DIR = TEST_DIR / 'real'
REAL_DIR.mkdir(parents=True, exist_ok=True)
(REAL_DIR / 'bundle.zip').write_bytes(PAYLOAD_A)
(REAL_DIR / 'bundle_copy.zip').write_bytes(PAYLOAD_A)

config.set('safety.dry_run_mode', False)
config.set('safety.confirm_before_delete', False)
real_console = Console(file=io.StringIO(), force_terminal=False, width=200)
real_found = detector.find_duplicate_files(
    [str(REAL_DIR)], real_console, ARCHIVE_TYPES['zip'], SECTIONS['archives'])
detector.delete_duplicate_files(real_found, real_console, FileSelector(), SECTIONS['archives'])
real_out = real_console.file.getvalue()

survivors = [p.name for p in REAL_DIR.iterdir() if p.suffix == '.zip']
P('exactly one of the two identical archives survives',
  len(survivors) == 1, survivors)
moved_files = list((RB_ROOT / 'duplicates-archives').rglob('*.zip'))
_moved.extend(moved_files)
P('the removed archive landed in the ARCHIVE recycle-bin subfolder',
  len(moved_files) == 1 and moved_files[0].name.startswith('bundle'),
  [str(p) for p in moved_files])
P('the survivor is byte-identical to what was moved',
  moved_files and moved_files[0].read_bytes() == PAYLOAD_A)
expected_rb_line = i18n.get('common.files_moved_to_recycle').format(
    1, RB_ROOT / 'duplicates-archives')
P('the console names the section recycle-bin folder',
  expected_rb_line in real_out,
  [line for line in real_out.splitlines() if 'duplicates-archives' in line])
real_report = newest_report('duplicate_archives')
_reports.append(real_report)
real_text = real_report.read_text(encoding='utf-8') if real_report else ''
P('the section report goes to its own prefix (duplicate_archives_...)',
  bool(real_report) and real_report.name.startswith('duplicate_archives_'),
  str(real_report))
P('the real-move report records where the file went',
  'Moved to' in real_text or 'نُقل إلى' in real_text)


# --------------------------------------------------------------------------
SEP('F. One report writer for every section (image output unchanged)')
# --------------------------------------------------------------------------
IMAGE_DIR = TEST_DIR / 'images'
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
img_a = IMAGE_DIR / 'shot.jpg'
img_b = IMAGE_DIR / 'shot_copy.jpg'
Image.new('RGB', (16, 12), (200, 100, 50)).save(img_a)
img_b.write_bytes(img_a.read_bytes())

report_gen = ReportGenerator()
info_extractor = ImageInfoExtractor()

# --- image report (spec=None, pre-collected info): unchanged behaviour -----
image_info = {str(img_a): report_gen.get_detailed_image_info(str(img_a)),
              str(img_b): report_gen.get_detailed_image_info(str(img_b))}
image_groups = {'image-sha': [str(img_a), str(img_b)]}
image_report = Path(report_gen.generate_duplicates_report_with_info(
    image_groups, [str(img_b)], image_info, {}))
_reports.append(image_report)
image_text = image_report.read_text(encoding='utf-8')

P('the image report keeps its historic file name',
  image_report.name.startswith('duplicates_'), image_report.name)
P('the image report keeps its title',
  i18n.get('reports.duplicates_title') in image_text)
P('the image report keeps its kept/deleted labels',
  i18n.get('reports.kept_image') in image_text
  and i18n.get('reports.deleted_images') in image_text)
P('an image report still prints the Dimensions line',
  'Dimensions: 16x12' in image_text)

# The no-info variant keeps the same layout AND now survives an unreadable
# file (it used to build its info dict late and raise NameError instead).
noinfo_report = Path(report_gen.generate_duplicates_report(image_groups, [str(img_b)], {}))
_reports.append(noinfo_report)
noinfo_text = noinfo_report.read_text(encoding='utf-8')
P('the no-info image variant writes the same sections',
  i18n.get('reports.kept_image') in noinfo_text
  and i18n.get('reports.deleted_images') in noinfo_text
  and 'Dimensions: 16x12' in noinfo_text)

# --- section report --------------------------------------------------------
kept_doc = str(SCAN_DIR / 'report.docx')
deleted_doc = str(SCAN_DIR / 'report_copy.docx')
office_info = {kept_doc: info_extractor.get_detailed_file_info(kept_doc),
               deleted_doc: info_extractor.get_detailed_file_info(deleted_doc)}
office_groups = {('.docx', 'sha-x'): [kept_doc, deleted_doc]}
office_report = Path(report_gen.generate_file_duplicates_report_with_info(
    office_groups, [deleted_doc], office_info, {}, SECTIONS['office']))
_reports.append(office_report)
office_text = office_report.read_text(encoding='utf-8')

P('the section report is written with the section prefix',
  office_report.name.startswith('duplicate_office_'), office_report.name)
P('the section report uses the office title',
  i18n.get('reports.office_duplicates_title') in office_text)
P('the section report uses file labels, not image labels',
  i18n.get('reports.kept_file') in office_text
  and i18n.get('reports.deleted_files') in office_text
  and i18n.get('reports.kept_image') not in office_text)
P('no meaningless "Dimensions: 0x0" line for a Word document',
  'Dimensions' not in office_text)
P('the section report shows the FULL original paths',
  kept_doc in office_text and deleted_doc in office_text)
P('the section report keeps the shared context lines',
  'Filename Importance' in office_text and 'Date Source' in office_text)
P('the date fallback is reported honestly as "modified", not as EXIF',
  'Date Source:    modified' in office_text, [l for l in office_text.splitlines() if 'Date Source' in l])


# --------------------------------------------------------------------------
SEP('G. File information: images keep dimensions, other files get mtime')
# --------------------------------------------------------------------------
doc_info = info_extractor.get_detailed_file_info(str(SCAN_DIR / 'report.docx'))
img_info = info_extractor.get_detailed_file_info(str(img_a))

P('a non-image file is marked kind="file" with no fake resolution',
  doc_info.get('kind') == 'file' and doc_info['width'] == 0 and doc_info['height'] == 0,
  {k: doc_info.get(k) for k in ('kind', 'width', 'height', 'format')})
P('a non-image file still reports name, size and modified time',
  doc_info['name'] == 'report.docx' and doc_info['size_bytes'] == len(PAYLOAD_A)
  and len(doc_info['modified_time']) == 19,
  (doc_info['name'], doc_info['size_bytes']))
P('its date falls back to the modification time (source "modified")',
  doc_info['date_source'] == 'modified' and doc_info['extracted_date'] != 'Unknown',
  (doc_info['date_source'], doc_info['extracted_date']))
P('an image is still kind="image" with its real dimensions',
  img_info.get('kind') == 'image' and (img_info['width'], img_info['height']) == (16, 12),
  {k: img_info.get(k) for k in ('kind', 'width', 'height')})
P('an image keeps the historic info shape',
  img_info['resolution'] == 16 * 12 and img_info['date_source'] != 'modified')

P('a missing file returns an error dict instead of raising',
  'error' in info_extractor.get_detailed_file_info(str(TEST_DIR / 'nope.docx')))

d_none = date_extractor.get_best_date(str(SCAN_DIR / 'report.docx'))
d_mtime = date_extractor.get_best_date(str(SCAN_DIR / 'report.docx'), 'oldest', True)
P('without the flag a dateless file stays dateless (images unaffected)',
  d_none == (None, 'none'), d_none)
P('with the flag the modification time is used and labelled "modified"',
  d_mtime[1] == 'modified' and d_mtime[0] is not None, d_mtime)
named_doc = SCAN_DIR / 'report_2022-07-20.docx'
named_doc.write_bytes(PAYLOAD_B)
P('a filename date still wins over the mtime fallback',
  date_extractor.get_best_date(str(named_doc), 'oldest', True)[1] == 'filename',
  date_extractor.get_best_date(str(named_doc), 'oldest', True))


# --------------------------------------------------------------------------
SEP('H. CLI wiring: section menus, main-menu routing, custom extensions')
# --------------------------------------------------------------------------
menu_console = Console(file=io.StringIO(), force_terminal=False, width=110)
menu_handler = cmh.CLIMenuHandler(menu_console)
orig_int_ask = cmh.IntPrompt.ask


def _patch_int(answer):
    cmh.IntPrompt.ask = staticmethod(lambda *a, **k: answer)


def _unpatch_int():
    cmh.IntPrompt.ask = orig_int_ask


def _patch_int_seq(answers):
    cmh.IntPrompt.ask = staticmethod(lambda *a, **k: next(answers))


_patch_int('0')
result_back = menu_handler.show_section_menu('office')
_unpatch_int()
menu_text = menu_console.file.getvalue()

P('the office menu lists every option plus Back',
  all(i18n.get(label) in menu_text for _o, _e, label in SECTIONS['office']['options'])
  and i18n.get('common.back') in menu_text)
P('choosing 0 leaves the section', result_back is None, result_back)

_patch_int('6')
result_pick = menu_handler.show_section_menu('office')
_unpatch_int()
P('choosing a number returns that option id', result_pick == 'all', result_pick)

_patch_int('5')
result_other = menu_handler.show_section_menu('office')
_unpatch_int()
P('the new "other office formats" entry is reachable (round 10)',
  result_other == 'office_other', result_other)

_patch_int('1')
result_word = menu_handler.show_section_menu('office')
_unpatch_int()
P('the first office entry is the Word option', result_word == 'word', result_word)

archive_console = Console(file=io.StringIO(), force_terminal=False, width=110)
archive_menu = cmh.CLIMenuHandler(archive_console)
_patch_int('8')
archive_pick = archive_menu.show_section_menu('archives')
_unpatch_int()
P('the archives menu maps its last entry to the combined option',
  archive_pick == 'all'
  and all(i18n.get(label) in archive_console.file.getvalue()
          for _o, _e, label in SECTIONS['archives']['options']),
  archive_pick)

# main menu: 3/4/5 open the sections, 2 is still the postponed video category
section_calls = []
coming_soon_calls = []
orig_run_section = mcli.MainCLI._run_section
orig_coming_soon = mcli.MainCLI._show_coming_soon
mcli.MainCLI._run_section = lambda self, key: section_calls.append(key)
mcli.MainCLI._show_coming_soon = lambda self: coming_soon_calls.append(True)

main_cli = mcli.MainCLI()
_patch_int_seq(iter(['3', '4', '5', '2', '7']))
main_cli._show_category_menu()
_unpatch_int()

mcli.MainCLI._run_section = orig_run_section
mcli.MainCLI._show_coming_soon = orig_coming_soon

P('main-menu entries 3/4/5 open office / archives / other',
  section_calls == ['office', 'archives', 'other'], section_calls)
P('video (2) is the only section still "coming soon"',
  len(coming_soon_calls) == 1, len(coming_soon_calls))

# --- "Other Files": the extensions are typed by the user -------------------
other_console = Console(file=io.StringIO(), force_terminal=False, width=110)
other_handler = coh.CLIOperationHandler(other_console, menu_handler)
other_handler.menu_handler.get_folders = lambda: [str(DRY_DIR)]
scan_calls = []


def _record_scan(folders, console, extensions, spec):
    scan_calls.append(list(extensions or []))
    return {'duplicates': {}, 'total_scanned': 0, 'total_duplicates': 0}


other_handler.processor.find_duplicate_files = _record_scan
_restore_prompt = _patch_ask(coh.Prompt, 'iso, .PNG')
other_handler.handle_duplicate_files('other', None, 'custom')
_restore_prompt()
other_out = other_console.file.getvalue()

P('a custom answer is normalised and echoed back to the user',
  i18n.get('other_operations.accepted').format('.iso, .png') in other_out,
  [line for line in other_out.splitlines() if 'iso' in line.lower()])
P('the scan receives exactly the extensions the user typed',
  scan_calls == [['.iso', '.png']], scan_calls)
P('"no duplicates" uses the other-files wording',
  i18n.get('other_operations.no_duplicates_found') in other_out)

invalid_console = Console(file=io.StringIO(), force_terminal=False, width=110)
invalid_handler = coh.CLIOperationHandler(invalid_console, menu_handler)
invalid_handler.menu_handler.get_folders = lambda: [str(DRY_DIR)]
scan_calls.clear()
invalid_handler.processor.find_duplicate_files = _record_scan
_restore_prompt = _patch_ask(coh.Prompt, '!!! , ..')
invalid_handler.handle_duplicate_files('other', None, 'custom')
_restore_prompt()
P('an invalid answer refuses to scan and says why',
  scan_calls == []
  and i18n.get('other_operations.no_valid_extensions') in invalid_console.file.getvalue(),
  invalid_console.file.getvalue().strip().splitlines()[-2:])

# --- full office flow through the CLI handler -------------------------------
e2e_dir = TEST_DIR / 'e2e'
e2e_dir.mkdir(parents=True, exist_ok=True)
(e2e_dir / 'invoice.docx').write_bytes(PAYLOAD_A)
(e2e_dir / 'invoice_copy.docx').write_bytes(PAYLOAD_A)
(e2e_dir / 'only_one.pdf').write_bytes(PAYLOAD_D)

import time as _time                                              # noqa: E402
_time.sleep(1.05)   # keep this report's timestamp second distinct

e2e_console = Console(file=io.StringIO(), force_terminal=False, width=110)
e2e_handler = coh.CLIOperationHandler(e2e_console, menu_handler)
e2e_handler.menu_handler.get_folders = lambda: [str(e2e_dir)]
e2e_handler.handle_duplicate_files('office', OFFICE_TYPES['word'], 'word')
e2e_out = e2e_console.file.getvalue()

e2e_moved = list((RB_ROOT / 'duplicates-office').rglob('invoice_copy.docx'))
_moved.extend(e2e_moved)
P('the CLI flow moved the duplicate into the OFFICE recycle bin',
  not (e2e_dir / 'invoice_copy.docx').exists()
  and (e2e_dir / 'invoice.docx').exists()
  and len(e2e_moved) == 1,
  [str(p) for p in e2e_moved])
P('files outside the chosen type are untouched', (e2e_dir / 'only_one.pdf').exists())
e2e_report = newest_report('duplicate_office')
_reports.append(e2e_report)
P('the flow ends with a saved report naming the moved file',
  bool(e2e_report) and 'invoice_copy.docx' in e2e_report.read_text(encoding='utf-8'),
  str(e2e_report))
P('the console confirms the report path',
  e2e_report is not None and e2e_report.name in e2e_out)

clean_dir = TEST_DIR / 'clean'
clean_dir.mkdir(parents=True, exist_ok=True)
(clean_dir / 'solo.docx').write_bytes(PAYLOAD_D)
clean_console = Console(file=io.StringIO(), force_terminal=False, width=110)
clean_handler = coh.CLIOperationHandler(clean_console, menu_handler)
clean_handler.menu_handler.get_folders = lambda: [str(clean_dir)]
clean_handler.handle_duplicate_files('office', OFFICE_TYPES['word'], 'word')
P('a folder without duplicates says so (no report, no fake success)',
  i18n.get('office_operations.no_duplicates_found') in clean_console.file.getvalue())


# --------------------------------------------------------------------------
SEP('I. Leave the machine as we found it')
# --------------------------------------------------------------------------
config.set('safety.dry_run_mode', DR0)
config.set('safety.confirm_before_delete', CONFIRM0)
config.set('paths.recycle_bin', RBIN0)
_restore_cfg()

P('settings.json is byte-identical again',
  _CFG_FILE.read_bytes() == _CFG_BYTES)

for report in _reports:
    if report and Path(report).exists():
        Path(report).unlink()
for moved in _moved:
    try:
        Path(moved).unlink()
    except OSError:
        pass

leftovers = []
for sub in ('duplicates-office', 'duplicates-archives', 'duplicates-other'):
    base = RB_ROOT / sub
    if not base.exists():
        continue
    for path in sorted(base.rglob('*'), key=lambda p: len(str(p)), reverse=True):
        if path.is_file():
            if path.name in ('invoice_copy.docx', 'report_copy.docx', 'bundle.zip',
                             'bundle_copy.zip', 'budget_copy.xlsx', 'only_one.pdf'):
                leftovers.append(str(path))
        elif not any(path.iterdir()):
            path.rmdir()          # prune the session folders we created

P('no suite file is left behind in the section recycle bins', not leftovers, leftovers)
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








