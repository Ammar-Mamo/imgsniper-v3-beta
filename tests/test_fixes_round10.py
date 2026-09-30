# imgSniper v3 -- Round 10 Fix Verification Suite
# Office section: FULL format coverage.
#   * the office families now cover the whole family -- macro-enabled
#     (docm/xlsm/pptm), templates (dotx/xltx/potx), show/legacy variants
#     (pps/ppsx/dot/xlt), the WPS equivalents (wps/et/dps), RTF and the
#     OpenDocument trio (odt/ods/odp);
#   * PDF and XPS share one entry (both are fixed-layout documents);
#   * a FIFTH entry covers the rest (Visio, Publisher, OneNote, Access,
#     Project, Outlook items, OpenDocument graphics/formula/database, iWork).
# The matching rules themselves did NOT change: still size pre-filter -> SHA-256
# -> match on (extension, sha256), so .xls never matches .xlsx.
# Run from project root: python tests/test_fixes_round10.py

import sys, io, json, shutil, builtins, logging, tempfile, atexit
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
    SECTIONS, OFFICE_TYPES, OFFICE_EXTENSIONS, WORD_EXTENSIONS,
    EXCEL_EXTENSIONS, POWERPOINT_EXTENSIONS, PDF_EXTENSIONS,
    OTHER_OFFICE_EXTENSIONS, MAX_EXTENSION_LENGTH, all_extensions)
from src.core.detectors.duplicate_detector import DuplicateDetector  # noqa: E402
from src.core.file_selector import FileSelector                      # noqa: E402
import src.cli.cli_menu_handler as cmh                               # noqa: E402

TEST_DIR = Path(tempfile.mkdtemp(prefix='imgsniper_round10_'))
RB_ROOT = Path.cwd() / config.get('paths.recycle_bin', 'recycle-bin')
REPORTS_DIR = Path.cwd() / config.get('paths.reports', 'reports')

DR0 = _CFG0.get('safety', {}).get('dry_run_mode', False)
CONFIRM0 = _CFG0.get('safety', {}).get('confirm_before_delete', True)
_lang_backup = i18n.current_language

_moved = []
_reports = []
_orig_input = builtins.input
builtins.input = lambda *a, **k: ''


def newest_report(prefix):
    """Most recent report file for a given prefix (None when there is none)."""
    matches = sorted(REPORTS_DIR.glob(prefix + '_*.txt'), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


detector = DuplicateDetector()

# --------------------------------------------------------------------------
SEP('A. Office coverage: every family, not just the two modern extensions')
# --------------------------------------------------------------------------
EXPECTED_WORD = ['.doc', '.docx', '.docm', '.dot', '.dotx', '.dotm', '.rtf', '.odt', '.wps']
EXPECTED_EXCEL = ['.xls', '.xlsx', '.xlsm', '.xlt', '.xltx', '.ods', '.csv', '.tsv', '.et']
EXPECTED_PPT = ['.ppt', '.pptx', '.pptm', '.pps', '.ppsx', '.pot', '.potx', '.odp', '.dps']
EXPECTED_PDF = ['.pdf', '.xps', '.oxps']
EXPECTED_OTHER = ['.vsd', '.vsdx', '.pub', '.one', '.accdb', '.mdb', '.mpp', '.msg',
                  '.eml', '.odg', '.odf', '.odb', '.pages', '.numbers', '.key']

P('Word covers the whole family (legacy, macro, templates, RTF, OpenDocument, WPS)',
  WORD_EXTENSIONS == EXPECTED_WORD, WORD_EXTENSIONS)
P('Excel covers the whole family (macro, templates, OpenDocument, CSV/TSV, WPS)',
  EXCEL_EXTENSIONS == EXPECTED_EXCEL, EXCEL_EXTENSIONS)
P('PowerPoint covers the whole family (macro, slide shows, templates, OpenDocument, WPS)',
  POWERPOINT_EXTENSIONS == EXPECTED_PPT, POWERPOINT_EXTENSIONS)
P('PDF and XPS share one entry (both are fixed-layout documents)',
  PDF_EXTENSIONS == EXPECTED_PDF, PDF_EXTENSIONS)
P('the remaining office formats have one entry of their own',
  OTHER_OFFICE_EXTENSIONS == EXPECTED_OTHER, OTHER_OFFICE_EXTENSIONS)

office_ids = [option[0] for option in SECTIONS['office']['options']]
P('the office menu now offers five types plus the combined entry',
  office_ids == ['word', 'excel', 'powerpoint', 'pdf', 'office_other', 'all'], office_ids)
P('each option list is the very list the registry exposes',
  [option[1] for option in SECTIONS['office']['options']] ==
  [WORD_EXTENSIONS, EXCEL_EXTENSIONS, POWERPOINT_EXTENSIONS, PDF_EXTENSIONS,
   OTHER_OFFICE_EXTENSIONS, OFFICE_EXTENSIONS])

P('the combined office entry is the union of every family',
  OFFICE_EXTENSIONS == all_extensions(OFFICE_TYPES)
  and sorted(OFFICE_EXTENSIONS) ==
  sorted(set(WORD_EXTENSIONS) | set(EXCEL_EXTENSIONS) | set(POWERPOINT_EXTENSIONS)
         | set(PDF_EXTENSIONS) | set(OTHER_OFFICE_EXTENSIONS)),
  len(OFFICE_EXTENSIONS))
P('45 office extensions, no duplicates', len(OFFICE_EXTENSIONS) == 45
  and len(set(OFFICE_EXTENSIONS)) == 45, len(OFFICE_EXTENSIONS))

shapes = {'not dot-prefixed': [], 'not lowercase': [], 'too long': [], 'not alnum': []}
for ext in OFFICE_EXTENSIONS:
    if not ext.startswith('.'):
        shapes['not dot-prefixed'].append(ext)
    if ext != ext.lower():
        shapes['not lowercase'].append(ext)
    if len(ext) - 1 > MAX_EXTENSION_LENGTH:
        shapes['too long'].append(ext)
    if not ext[1:].isalnum():
        shapes['not alnum'].append(ext)
P('every office extension is a well-formed, lowercase, alnum extension',
  not any(shapes.values()), shapes)

# Two DIFFERENT menu entries must never claim the same extension: the user
# would otherwise scan (and delete) the same files twice under two labels.
overlap = {}
families = {'word': WORD_EXTENSIONS, 'excel': EXCEL_EXTENSIONS,
            'powerpoint': POWERPOINT_EXTENSIONS, 'pdf': PDF_EXTENSIONS,
            'office_other': OTHER_OFFICE_EXTENSIONS}
for name, extensions in families.items():
    for other_name, other_extensions in families.items():
        if name < other_name:
            shared = sorted(set(extensions) & set(other_extensions))
            if shared:
                overlap[f'{name}/{other_name}'] = shared
P('no extension is claimed by two different office options', not overlap, overlap)

P('OFFICE_TYPES exposes the new family too',
  OFFICE_TYPES.get('office_other') == OTHER_OFFICE_EXTENSIONS)

# i18n: the labels must exist in BOTH languages and document the family.
missing_en = [label for _o, _e, label in SECTIONS['office']['options']
              if i18n.get(label).startswith('[Missing')]
P('every office option label exists in English', not missing_en, missing_en)
P('the English labels name the extensions they cover',
  all(token in i18n.get('office_operations.word') for token in ('docx', 'rtf', 'odt', 'wps'))
  and 'xlsx' in i18n.get('office_operations.excel')
  and 'ods' in i18n.get('office_operations.excel')
  and 'pptx' in i18n.get('office_operations.powerpoint')
  and 'xps' in i18n.get('office_operations.pdf')
  and 'Visio' in i18n.get('office_operations.other_formats'),
  i18n.get('office_operations.other_formats'))

i18n.set_language('ar')
missing_ar = [label for _o, _e, label in SECTIONS['office']['options']
              if i18n.get(label).startswith('[Missing')]
P('the same office labels exist in Arabic', not missing_ar, missing_ar)
P('the Arabic labels name the extensions they cover',
  'odt' in i18n.get('office_operations.word')
  and 'ods' in i18n.get('office_operations.excel')
  and 'odp' in i18n.get('office_operations.powerpoint')
  and 'xps' in i18n.get('office_operations.pdf')
  and 'OneNote' in i18n.get('office_operations.other_formats'))
i18n.set_language('en')

# --------------------------------------------------------------------------
SEP('B. Scanning the new extensions (per-extension matching unchanged)')
# --------------------------------------------------------------------------
SCAN_DIR = TEST_DIR / 'scan'
SCAN_DIR.mkdir(parents=True, exist_ok=True)

PAYLOAD_A = (b'IMGS-ROUND10-WORD' * 300)[:4096]      # a.odt twins
PAYLOAD_B = (b'IMGS-ROUND10-CSV' * 300)[:4096]       # b.csv twins
PAYLOAD_C = (b'IMGS-ROUND10-XLTX' * 300)[:4096]      # c.xltx twins
PAYLOAD_D = (b'IMGS-ROUND10-ODP' * 300)[:4096]       # d.odp twins
PAYLOAD_X = (b'IMGS-ROUND10-SAME-SIZE' * 300)[:4096]  # .ods + .xls, same bytes

for name, payload in (('a.odt', PAYLOAD_A), ('a_copy.odt', PAYLOAD_A),
                      ('b.csv', PAYLOAD_B), ('b_copy.csv', PAYLOAD_B),
                      ('c.xltx', PAYLOAD_C), ('c_copy.xltx', PAYLOAD_C),
                      ('d.odp', PAYLOAD_D), ('d_copy.odp', PAYLOAD_D),
                      ('x.ods', PAYLOAD_X), ('x.xls', PAYLOAD_X)):
    (SCAN_DIR / name).write_bytes(payload)
(SCAN_DIR / 'solo.pub').write_bytes(b'IMGS-ROUND10-SOLO' * 70)   # unique size, over the filter
(SCAN_DIR / 'tiny.pub').write_bytes(b'x' * 10)                   # under filters.min_file_size_bytes


def scan(extensions):
    console = Console(file=io.StringIO(), force_terminal=False, width=200)
    result = detector.find_duplicate_files([str(SCAN_DIR)], console, extensions,
                                           SECTIONS['office'])
    return result, console.file.getvalue()


word_found, _word_out = scan(WORD_EXTENSIONS)
word_names = sorted(Path(p).name for files in word_found['duplicates'].values() for p in files)
P('an OpenDocument text pair is found by the Word option',
  word_names == ['a.odt', 'a_copy.odt'], word_names)
P('only the Word family is scanned (2 files, no spreadsheet in the count)',
  word_found['total_scanned'] == 2 and word_found['total_duplicates'] == 1,
  (word_found['total_scanned'], word_found['total_duplicates']))

excel_found, _excel_out = scan(EXCEL_EXTENSIONS)
excel_keys = sorted(key[0] for key in excel_found['duplicates'])
P('the Excel option finds the .csv and the template (.xltx) pairs',
  excel_keys == ['.csv', '.xltx'], excel_keys)
P('identical bytes in .ods and .xls are NOT a duplicate pair (per extension)',
  '.ods' not in excel_keys and '.xls' not in excel_keys, excel_keys)
P('the Excel option scanned exactly its own six files',
  excel_found['total_scanned'] == 6, excel_found['total_scanned'])

ppt_found, _ppt_out = scan(POWERPOINT_EXTENSIONS)
P('the PowerPoint option finds the .odp pair',
  [Path(p).name for files in ppt_found['duplicates'].values() for p in files]
  and sorted(key[0] for key in ppt_found['duplicates']) == ['.odp'])

pdf_found, _pdf_out = scan(PDF_EXTENSIONS)
P('PDF/XPS with no such files reports "nothing found" instead of a fake success',
  pdf_found is None
  and i18n.get('office_operations.found_files').format(0) in _pdf_out, pdf_found)

other_found, _other_out = scan(OTHER_OFFICE_EXTENSIONS)
P('the "other office formats" option now reaches .pub files',
  other_found is not None and other_found['total_scanned'] == 1
  and not other_found['duplicates'], other_found)

all_found, _all_out = scan(OFFICE_EXTENSIONS)
P('the combined scan covers every new family (odt/csv/xltx/odp)',
  sorted(key[0] for key in all_found['duplicates']) == ['.csv', '.odp', '.odt', '.xltx'],
  sorted(key[0] for key in all_found['duplicates']))
P('NO group mixes extensions, even with identical bytes across formats',
  all(Path(p).suffix.lower() == key[0]
      for key, files in all_found['duplicates'].items() for p in files))
P('the group key really is (extension, sha256), not just a hash',
  all(isinstance(key, tuple) and len(key) == 2 and len(key[1]) == 64
      for key in all_found['duplicates']), list(all_found['duplicates'])[:1])
P('the combined scan counts the 11 office files and finds 4 duplicate pairs',
  all_found['total_scanned'] == 11 and all_found['total_duplicates'] == 4,
  (all_found['total_scanned'], all_found['total_duplicates']))
on_disk = sorted(p.name for p in SCAN_DIR.iterdir()
                 if p.suffix.lower() in set(OFFICE_EXTENSIONS))
P('a file below filters.min_file_size_bytes is skipped, section scans included',
  len(on_disk) == 12 and all_found['total_scanned'] == 11 and 'tiny.pub' in on_disk,
  (len(on_disk), all_found['total_scanned']))

# --------------------------------------------------------------------------
SEP('C. Deleting with the new entry (shared report writer, own recycle bin)')
# --------------------------------------------------------------------------
REAL_DIR = TEST_DIR / 'real'
REAL_DIR.mkdir(parents=True, exist_ok=True)
PAGES = (b'IMGS-ROUND10-PAGES' * 300)[:4096]
VISIO = (b'IMGS-ROUND10-VISIO' * 300)[:4096]
for name, payload in (('templates.pages', PAGES), ('templates_copy.pages', PAGES),
                      ('design.vsd', VISIO), ('design.vsdx', VISIO)):
    (REAL_DIR / name).write_bytes(payload)

config.set('safety.dry_run_mode', False)
config.set('safety.confirm_before_delete', False)

real_console = Console(file=io.StringIO(), force_terminal=False, width=200)
real_found = detector.find_duplicate_files(
    [str(REAL_DIR)], real_console, OTHER_OFFICE_EXTENSIONS, SECTIONS['office'])
P('a .pages pair is a duplicate; the identical .vsd/.vsdx are not',
  [(key[0], len(files)) for key, files in real_found['duplicates'].items()] == [('.pages', 2)],
  {key[0]: len(files) for key, files in real_found['duplicates'].items()})

detector.delete_duplicate_files(real_found, real_console, FileSelector(), SECTIONS['office'])
real_out = real_console.file.getvalue()

survivors = sorted(p.name for p in REAL_DIR.iterdir())
P('only the copy was removed: one .pages survives, the Visio files untouched',
  survivors == ['design.vsd', 'design.vsdx', 'templates.pages'], survivors)
moved = list((RB_ROOT / 'duplicates-office').rglob('*.pages'))
_moved.extend(moved)
P('the removed .pages landed in the OFFICE recycle-bin subfolder',
  len(moved) == 1 and moved[0].name == 'templates_copy.pages',
  [str(p) for p in moved])
P('no Visio file was moved anywhere',
  not list((RB_ROOT / 'duplicates-office').rglob('*.vsd*')))
P('the console reports the office recycle-bin folder',
  str(RB_ROOT / 'duplicates-office') in real_out,
  [line for line in real_out.splitlines() if 'duplicates-office' in line])

real_report = newest_report('duplicate_office')
_reports.append(real_report)
real_text = real_report.read_text(encoding='utf-8') if real_report else ''
P('the section report keeps its own prefix and title',
  bool(real_report) and real_report.name.startswith('duplicate_office_')
  and i18n.get('reports.office_duplicates_title') in real_text, str(real_report))
P('the report names both files and records the move',
  'templates.pages' in real_text and 'templates_copy.pages' in real_text
  and ('Moved to' in real_text or 'نُقل إلى' in real_text))
P('non-image files still get no meaningless "Dimensions: 0x0" line',
  '0x0' not in real_text)

# --------------------------------------------------------------------------
SEP('D. Menu: the new entry is reachable and numbered correctly')
# --------------------------------------------------------------------------
menu_console = Console(file=io.StringIO(), force_terminal=False, width=200)
menu_handler = cmh.CLIMenuHandler(menu_console)
orig_int_ask = cmh.IntPrompt.ask


def _patch_int(answer):
    cmh.IntPrompt.ask = staticmethod(lambda *a, **k: answer)


def _unpatch_int():
    cmh.IntPrompt.ask = orig_int_ask


_patch_int('0')
back = menu_handler.show_section_menu('office')
_unpatch_int()
menu_text = menu_console.file.getvalue()

P('the office menu shows all six entries plus Back',
  all(i18n.get(label) in menu_text for _o, _e, label in SECTIONS['office']['options'])
  and i18n.get('common.back') in menu_text)
P('the menu lines are numbered 1..6, and 0 leaves the section',
  all((str(i) + ' - ') in menu_text for i in range(1, 7)) and back is None, back)

_patch_int('5')
pick_other = menu_handler.show_section_menu('office')
_unpatch_int()
P('entry 5 opens the new "other office formats" scan', pick_other == 'office_other', pick_other)

_patch_int('6')
pick_all = menu_handler.show_section_menu('office')
_unpatch_int()
P('the combined entry is still last', pick_all == 'all', pick_all)

P('the archives menu is untouched by this round',
  [option[0] for option in SECTIONS['archives']['options']]
  == ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'all'])


# --------------------------------------------------------------------------
SEP('E. Leave the machine as we found it')
# --------------------------------------------------------------------------
config.set('safety.dry_run_mode', DR0)
config.set('safety.confirm_before_delete', CONFIRM0)
_restore_cfg()

P('settings.json is byte-identical again',
  _CFG_FILE.read_bytes() == _CFG_BYTES)

for report in _reports:
    if report and Path(report).exists():
        Path(report).unlink()
for moved_file in _moved:
    try:
        Path(moved_file).unlink()
    except OSError:
        pass

leftovers = []
bin_office = RB_ROOT / 'duplicates-office'
if bin_office.exists():
    for path in sorted(bin_office.rglob('*'), key=lambda p: len(str(p)), reverse=True):
        if path.is_file():
            if path.name == 'templates_copy.pages':
                leftovers.append(str(path))
        elif not any(path.iterdir()):
            path.rmdir()          # prune the session folders we created

P('no suite file is left behind in the office recycle bin', not leftovers, leftovers)
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
