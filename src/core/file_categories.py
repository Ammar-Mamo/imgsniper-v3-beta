"""
Central registry of the non-image file sections (Round 9).
السجل المركزي لأقسام الملفات غير الصوريّة: الأوفيس / الأرشيف / الملفات الأخرى.

Why a registry and not scattered lists:
  * the CLI menu, the scan engine, the recycle-bin subfolder and the report
    prefix all read the SAME descriptor, so a new type is one line here plus
    its i18n label -- there is no second place to update;
  * matching is PER EXTENSION (see DuplicateDetector.find_duplicate_files):
    a .doc is only ever compared against other .doc files, even inside the
    combined "all types" scan, because two different formats are two
    different artifacts even when their bytes happen to be identical.
"""

from typing import Dict, List

from ..utils.helpers.file_utils import get_all_images

# ---------------------------------------------------------------------------
# Extension tables
# ---------------------------------------------------------------------------
# A "type" groups the extensions that are the SAME artifact for the user:
# Word = .doc + .docx together, PowerPoint = .ppt + .pptx, and so on.
WORD_EXTENSIONS = ['.doc', '.docx']
EXCEL_EXTENSIONS = ['.xls', '.xlsx']
POWERPOINT_EXTENSIONS = ['.ppt', '.pptx']
PDF_EXTENSIONS = ['.pdf']

OFFICE_TYPES: Dict[str, List[str]] = {
    'word': WORD_EXTENSIONS,
    'excel': EXCEL_EXTENSIONS,
    'powerpoint': POWERPOINT_EXTENSIONS,
    'pdf': PDF_EXTENSIONS,
}

ARCHIVE_TYPES: Dict[str, List[str]] = {
    'zip': ['.zip'],
    'rar': ['.rar'],
    '7z': ['.7z'],
    'tar': ['.tar'],
    'gz': ['.gz', '.tgz'],
    'bz2': ['.bz2'],
    'xz': ['.xz'],
}


def all_extensions(types: Dict[str, List[str]]) -> List[str]:
    """Every extension of a type table, de-duplicated, order preserved."""
    merged: List[str] = []
    for extensions in (types or {}).values():
        for extension in extensions:
            if extension not in merged:
                merged.append(extension)
    return merged


OFFICE_EXTENSIONS = all_extensions(OFFICE_TYPES)
ARCHIVE_EXTENSIONS = all_extensions(ARCHIVE_TYPES)



# ---------------------------------------------------------------------------
# Sections -- one descriptor per CLI section.
#   options            : (option_id, extensions, label_key); extensions=None
#                        means the option asks the user for them at run time.
#   recycle_subfolder  : every file this section removes lands there, so a
#                        section's deletions stay grouped and recoverable.
#   report_prefix      : report file name prefix (images keep "duplicates").
# ---------------------------------------------------------------------------
SECTIONS: Dict[str, Dict[str, object]] = {
    'office': {
        'label_key': 'categories.office',
        'recycle_subfolder': 'duplicates-office',
        'report_prefix': 'duplicate_office',
        'report_title_key': 'reports.office_duplicates_title',
        'found_key': 'office_operations.found_files',
        'no_duplicates_key': 'office_operations.no_duplicates_found',
        'options': [
            ('word', WORD_EXTENSIONS, 'office_operations.word'),
            ('excel', EXCEL_EXTENSIONS, 'office_operations.excel'),
            ('powerpoint', POWERPOINT_EXTENSIONS, 'office_operations.powerpoint'),
            ('pdf', PDF_EXTENSIONS, 'office_operations.pdf'),
            ('all', OFFICE_EXTENSIONS, 'office_operations.all'),
        ],
    },
    'archives': {
        'label_key': 'categories.archives',
        'recycle_subfolder': 'duplicates-archives',
        'report_prefix': 'duplicate_archives',
        'report_title_key': 'reports.archives_duplicates_title',
        'found_key': 'archives_operations.found_files',
        'no_duplicates_key': 'archives_operations.no_duplicates_found',
        'options': [
            ('zip', ARCHIVE_TYPES['zip'], 'archives_operations.zip'),
            ('rar', ARCHIVE_TYPES['rar'], 'archives_operations.rar'),
            ('7z', ARCHIVE_TYPES['7z'], 'archives_operations.7z'),
            ('tar', ARCHIVE_TYPES['tar'], 'archives_operations.tar'),
            ('gz', ARCHIVE_TYPES['gz'], 'archives_operations.gz'),
            ('bz2', ARCHIVE_TYPES['bz2'], 'archives_operations.bz2'),
            ('xz', ARCHIVE_TYPES['xz'], 'archives_operations.xz'),
            ('all', ARCHIVE_EXTENSIONS, 'archives_operations.all'),
        ],
    },
    'other': {
        'label_key': 'categories.others',
        'recycle_subfolder': 'duplicates-other',
        'report_prefix': 'duplicate_other',
        'report_title_key': 'reports.other_duplicates_title',
        'found_key': 'other_operations.found_files',
        'no_duplicates_key': 'other_operations.no_duplicates_found',
        'options': [
            ('custom', None, 'other_operations.custom'),
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# A file extension longer than this is a typo, not a format ("this-is-way-too
# -long"), so the answer is rejected instead of scanning for nothing.
MAX_EXTENSION_LENGTH = 10


def normalize_extensions(raw: str) -> List[str]:
    """Turn a free-text answer into a clean, de-duplicated extension list.

    "iso, apk; .PNG" -> ['.iso', '.apk', '.png']

    Invalid tokens (empty, dot-only, too long, illegal characters) are dropped
    here; the caller decides what to do when the result is empty -- the CLI
    refuses to scan and says so, instead of reporting "no duplicates found"
    for a scan that never happened.
    """
    found: List[str] = []

    for token in str(raw or '').replace(';', ',').replace('|', ',').split(','):
        # Spaces inside one answer ("iso apk") are separators too.
        for part in token.split():
            body = part.strip().strip('.')
            if not body or len(body) > MAX_EXTENSION_LENGTH:
                continue
            cleaned = body.replace('.', '').replace('-', '').replace('_', '').replace('+', '')
            if not cleaned.isalnum():
                continue
            extension = '.' + body.lower()
            if extension not in found:
                found.append(extension)

    return found


def collect_files(folders: List[str], extensions) -> List[str]:
    """Every file with one of `extensions` inside `folders` (recursive).

    Reuses get_all_images() -- deliberately: it applies the filters.* section
    of settings.json (size limits, hidden/system, exclude_patterns) and, more
    importantly, never returns files inside ImgSniper's own recycle-bin /
    reports directories, so a file moved there can never be scanned and moved
    again on the next run.
    """
    wanted = {str(ext).lower() for ext in (extensions or []) if ext}
    if not wanted:
        return []

    found: List[str] = []
    for folder in folders or []:
        found.extend(get_all_images(folder, wanted))
    return found
