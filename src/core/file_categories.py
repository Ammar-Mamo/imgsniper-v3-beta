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

from ..utils.helpers.file_utils import (get_all_images, announce_scan_skips,
                                        reset_scan_skips)
from ..utils.helpers.progress_ui import live_counter
from .i18n.i18n import i18n

# ---------------------------------------------------------------------------
# Extension tables
# ---------------------------------------------------------------------------
# Round 10: a "type" covers the whole FAMILY, not just the two modern
# extensions. Macro-enabled (docm/xlsm/pptm), templates (dotx/xltx/potx),
# show and legacy variants (pps/ppsx/dot/xlt), the WPS Office equivalents
# (wps/et/dps), RTF, and the OpenDocument twins (odt/ods/odp).
#
# Deliberately NOT listed: .pst / .ost (Outlook mailbox DATABASES -- multi-GB
# single files, where one duplicate pair means reading tens of GB) and .dwg
# (CAD drawings, not an office document). Both remain reachable through the
# "Other Files" entry, which accepts any extension the user types.
WORD_EXTENSIONS = ['.doc', '.docx', '.docm', '.dot', '.dotx', '.dotm', '.rtf', '.odt', '.wps']
EXCEL_EXTENSIONS = ['.xls', '.xlsx', '.xlsm', '.xlt', '.xltx', '.ods', '.csv', '.tsv', '.et']
POWERPOINT_EXTENSIONS = ['.ppt', '.pptx', '.pptm', '.pps', '.ppsx', '.pot', '.potx', '.odp', '.dps']
# PDF and XPS are the same artifact for the user: a fixed-layout document.
PDF_EXTENSIONS = ['.pdf', '.xps', '.oxps']
# Everything else an office suite produces: drawing/database files (Visio,
# Publisher, OneNote, Access, Project), Outlook items (.msg/.eml), the
# OpenDocument graphics/formula/database formats and the Apple iWork trio.
OTHER_OFFICE_EXTENSIONS = ['.vsd', '.vsdx', '.pub', '.one', '.accdb', '.mdb', '.mpp',
                           '.msg', '.eml', '.odg', '.odf', '.odb',
                           '.pages', '.numbers', '.key']

OFFICE_TYPES: Dict[str, List[str]] = {
    'word': WORD_EXTENSIONS,
    'excel': EXCEL_EXTENSIONS,
    'powerpoint': POWERPOINT_EXTENSIONS,
    'pdf': PDF_EXTENSIONS,
    'office_other': OTHER_OFFICE_EXTENSIONS,
}

# ---------------------------------------------------------------------------
# Round 11: video. EXACT duplicates only -- byte-for-byte, per extension.
#
# The families below are containers, not codecs: two files are compared only
# when they share BOTH the extension and every byte, so an .mp4 is never
# offered as a duplicate of a .mov, and a re-encode (H.264 -> H.265, 720p ->
# 1080p, another bitrate, another audio track) is by definition NOT a match.
#
# Deliberately NOT listed:
#   * .ts  -- the extension is shared with TypeScript sources, so a "video"
#             scan of a development folder would hash thousands of code files.
#   * .m4a / .mka / .mp3 / .wav -- audio, not video.
#   * .iso -- a disc image, reachable through "Other Files".
# All three stay reachable through the "Other Files" entry, which accepts any
# extension the user types.
MP4_EXTENSIONS = ['.mp4', '.m4v']          # ISO-BMFF (incl. the Apple variant)
MOV_EXTENSIONS = ['.mov']                  # QuickTime
MKV_EXTENSIONS = ['.mkv']                  # Matroska
AVI_EXTENSIONS = ['.avi']
WMV_EXTENSIONS = ['.wmv', '.asf']          # Windows Media
MPEG_EXTENSIONS = ['.mpg', '.mpeg', '.m2v', '.m2ts', '.mts', '.vob']
WEB_VIDEO_EXTENSIONS = ['.webm', '.ogv']
OTHER_VIDEO_EXTENSIONS = ['.flv', '.f4v', '.3gp', '.3g2', '.rm', '.rmvb',
                          '.divx', '.mxf', '.insv']

VIDEO_TYPES: Dict[str, List[str]] = {
    'mp4': MP4_EXTENSIONS,
    'mov': MOV_EXTENSIONS,
    'mkv': MKV_EXTENSIONS,
    'avi': AVI_EXTENSIONS,
    'wmv': WMV_EXTENSIONS,
    'mpeg': MPEG_EXTENSIONS,
    'web': WEB_VIDEO_EXTENSIONS,
    'video_other': OTHER_VIDEO_EXTENSIONS,
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
VIDEO_EXTENSIONS = all_extensions(VIDEO_TYPES)



# ---------------------------------------------------------------------------
# Sections -- one descriptor per CLI section.
#   options            : (option_id, extensions, label_key); extensions=None
#                        means the option asks the user for them at run time.
#   recycle_subfolder  : every file this section removes lands there, so a
#                        section's deletions stay grouped and recoverable.
#   report_prefix      : report file name prefix (images keep "duplicates").
# ---------------------------------------------------------------------------
SECTIONS: Dict[str, Dict[str, object]] = {
    # Round 11: video -- EXACT duplicates only (same extension + same size +
    # same full-file SHA-256). No content/perceptual matching of any kind: a
    # re-encode, a remux, another resolution, bitrate or audio track is by
    # definition NOT a duplicate here. 'engine' routes this section to
    # VideoDuplicateDetector instead of the generic non-image flow.
    'video': {
        'label_key': 'categories.videos',
        'engine': 'video',
        'recycle_subfolder': 'duplicates-video',
        'report_prefix': 'duplicate_video',
        'report_title_key': 'reports.video_duplicates_title',
        'found_key': 'video_operations.found_files',
        'no_duplicates_key': 'video_operations.no_duplicates_found',
        'options': [
            ('mp4', MP4_EXTENSIONS, 'video_operations.mp4'),
            ('mov', MOV_EXTENSIONS, 'video_operations.mov'),
            ('mkv', MKV_EXTENSIONS, 'video_operations.mkv'),
            ('avi', AVI_EXTENSIONS, 'video_operations.avi'),
            ('wmv', WMV_EXTENSIONS, 'video_operations.wmv'),
            ('mpeg', MPEG_EXTENSIONS, 'video_operations.mpeg'),
            ('web', WEB_VIDEO_EXTENSIONS, 'video_operations.web'),
            ('video_other', OTHER_VIDEO_EXTENSIONS, 'video_operations.other_formats'),
            ('all', VIDEO_EXTENSIONS, 'video_operations.all'),
        ],
    },
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
            ('office_other', OTHER_OFFICE_EXTENSIONS, 'office_operations.other_formats'),
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


def collect_files(folders: List[str], extensions, console=None) -> List[str]:
    """Every file with one of `extensions` inside `folders` (recursive).

    Reuses get_all_images() -- deliberately: it applies the filters.* section
    of settings.json (size limits, hidden/system, exclude_patterns) and, more
    importantly, never returns files inside ImgSniper's own recycle-bin /
    reports directories, so a file moved there can never be scanned and moved
    again on the next run.

    Round 12: when `console` is given, one scan = one transparent summary of the
    files the filters skipped, so a section can never quietly look at less than
    the folder holds. The counters are reset HERE, at the start of the scan.

    Round 14: the walk itself now shows a running count. Scanning a whole USB
    hard disk used to print "Scanning folder and all subfolders" and then nothing
    at all for minutes -- which is exactly when users start pressing keys (see
    console_input). Which files come back is decided by get_all_images() exactly
    as before; the counter is cosmetic and cannot influence the result.
    """
    wanted = {str(ext).lower() for ext in (extensions or []) if ext}
    if not wanted:
        return []

    reset_scan_skips()
    found: List[str] = []
    with live_counter(console, i18n.get('common.scanning_files')) as counter:
        for folder in folders or []:
            found.extend(get_all_images(folder, wanted, progress_cb=counter.bump))
    announce_scan_skips(console)
    return found
