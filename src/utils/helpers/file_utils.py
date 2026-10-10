
# ══════════════════════════════════════════════════════════════════════════════
# 📁 أدوات التعامل مع الملفات - File Utilities
# ══════════════════════════════════════════════════════════════════════════════
# الوظائف الأساسية:
#   • فحص وجلب ملفات الصور
#   • نقل آمن للملفات إلى سلة المهملات المنظمة
#   • التعامل مع الملفات المحمية والقراءة فقط
#   • الحذف القسري للملفات المحمية
#   • إدارة صلاحيات الملفات عبر أنظمة التشغيل المختلفة
# ══════════════════════════════════════════════════════════════════════════════

"""
دوال مساعدة للتعامل مع الملفات
تحتوي على جميع العمليات المتعلقة بـ:
- فحص الملفات والمجلدات
- نقل الملفات إلى سلة المهملات
- التحقق من صلاحيات الملفات
- الحذف القسري للملفات المحمية
"""
# وحدة مساعدة - دوال مشتركة ومساعدة للوحدات الأخرى


import fnmatch
import logging
import os
import shutil
import stat as stat_module
from pathlib import Path
from typing import Any, Dict, List, Set

from ...core.config import (config, RECOVERY_LIFTABLE_REASONS,
                            recovery_mode_active)
from ...core.i18n.i18n import i18n

import sys

logger = logging.getLogger(__name__)

from rich.console import Console

from .progress_ui import track
from .console_input import ask_line

# Module-level console used for status messages that previously used bare
# print calls. Rich degrades gracefully on limited code pages / redirected
# stdout, so emoji/Unicode output can no longer crash file operations.
_utils_console = Console()


# Round 14: how often the directory walk reports its running count. One call
# per 500 entries is noise next to the stat() every entry already costs, while
# still updating several times a second on a hard disk.
_WALK_REPORT_EVERY = 500


def _safe_print(message) -> None:
    """Print a status message without ever raising on Unicode/encoding issues.

    markup=False is essential: file paths may contain '[' / ']' which rich
    would otherwise misinterpret as markup tags.
    """
    try:
        _utils_console.print(message, markup=False, highlight=False)
    except Exception:
        try:
            sys.stdout.write(str(message).encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:
            pass


def clean_path_for_recycle_bin(source_path: Path) -> Path:
    """Clean and organize path for recycle bin, removing user-specific parts."""
    source_absolute = source_path.resolve()
    
    # Try to find a معنىful relative مسار
    relative_path = None
    
    # Common base مسارs to remove (مستخدم-محدد جزءs)
    common_bases = [
        Path.home(),  # C:\Users\مستخدماسم
        Path.home().parent,  # C:\Users
        Path("C:/Users"),
        Path("C:/"),
        Path("/")
    ]
    
    for base in common_bases:
        try:
            if source_absolute.is_relative_to(base):
                relative_path = source_absolute.relative_to(base)
                break
        except (ValueError, AttributeError):
            continue
    
    # If no relative مسار found, use the مملوء مسار without drive
    if relative_path is None:
        relative_path = Path(*source_absolute.parts[1:]) if len(source_absolute.parts) > 1 else source_absolute
    
    # إزالة مستخدم-محدد مجلد اسمs from the مسار
    path_parts = []
    skip_next = False
    
    for part in relative_path.parts[:-1]:  # Exclude ملفاسم
        part_lower = part.lower()
        
        # Skip مستخدم-محدد مجلدs and temp مجلدs
        if part_lower in ['users', 'user', 'home']:
            skip_next = True
            continue
        elif skip_next:
            skip_next = False
            continue
        elif part_lower in ['appdata', 'temp', 'tmp'] or part_lower.startswith('tmp'):
            # Skip temp مجلدs كاملly
            continue
        else:
            path_parts.append(part)
    
    # Return cleaned مسار, ensuring we have at least something معنىful
    if path_parts:
        return Path(*path_parts)
    else:
        # If no معنىful مسار, use the parent مجلد اسم of the ملف
        parent_name = source_absolute.parent.name
        if parent_name and parent_name.lower() not in ['temp', 'tmp', 'appdata']:
            return Path(parent_name)
        else:
            return Path("misc")  # Deعيب مجلد for miscellaneous ملفات

# جلب جميع ملفات الصور من المجلدات المحددة
        # يبحث في جميع المجلدات الفرعية بشكل تلقائي
        # يدعم الصيغ: jpg, jpeg, png, gif, bmp, webp, tiff, svg
        # يتجاهل الملفات التالفة أو غير القابلة للقراءة

# ── Audit finding P2-7 ────────────────────────────────────────────────────────
# get_all_images() used to return EVERY file carrying an image extension,
# ignoring the whole filters.* section of settings.json and descending into
# ImgSniper's own output directories. When the scanned folder contained the
# project (or was the CWD the recycle bin gets created in), files already
# deleted into recycle-bin/ came straight back into the pipeline and were
# hashed, reported and MOVED AGAIN.
#
# The exclusion list below is resolved to ABSOLUTE paths rather than matched by
# directory NAME on purpose: a user may legitimately keep photos in a folder
# called "reports", and silently skipping it would hide real images.
#
# filters.min_resolution / max_resolution are deliberately NOT applied here.
# Honouring them would mean opening and decoding every candidate image during
# the scan (tens of thousands of files) purely to decide whether to skip it,
# which would dwarf the cost of the actual duplicate/similarity work. Resolution
# is already considered where the image gets opened anyway: the small-images
# detector and the quality-floor guard in FileSelector.

# src/utils/helpers/file_utils.py -> helpers -> utils -> src -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Windows-only stat attributes. Both are absent on POSIX, where the checks
# below degrade to the dot-prefix convention (hidden) and "never system".
_WIN_ATTRS = hasattr(stat_module, 'FILE_ATTRIBUTE_HIDDEN')
_WIN_HIDDEN = getattr(stat_module, 'FILE_ATTRIBUTE_HIDDEN', 0)
_WIN_SYSTEM = getattr(stat_module, 'FILE_ATTRIBUTE_SYSTEM', 0)

# Directory flags are stat'ed at most once per scan; a deep tree would
# otherwise re-stat the same ancestor for every single file inside it.
_DIR_FLAG_CACHE = {}


def _get_excluded_dir_prefixes() -> List[str]:
    """
    Normalized path prefixes ImgSniper writes to, which must never be scanned.

    Resolved against BOTH the project root and the current working directory:
    move_to_recycle_bin() builds its target from Path.cwd(), while the settings
    file itself lives under the project root, so either can be the real one
    depending on how the app was launched. Every entry is separator-terminated
    so the prefix test matches only true descendants and can never catch a
    sibling such as "reports-old", which would silently hide real photos.
    """
    prefixes = []
    seen = set()
    for key, default in (('paths.recycle_bin', 'recycle-bin'),
                         ('paths.reports', 'reports'),
                         ('paths.temp', 'temp'),
                         ('paths.cache', 'cache')):
        name = config.get(key, default)
        if not name:
            continue
        for base in (_PROJECT_ROOT, Path.cwd()):
            try:
                resolved = (base / str(name)).resolve()
            except OSError:
                continue
            text = os.path.normcase(str(resolved))
            if text in seen:
                continue
            seen.add(text)
            prefixes.append(text + os.sep)
    return prefixes


def _is_excluded(resolved_text: str, prefixes: List[str]) -> bool:
    """True when a normalized absolute path sits inside an excluded directory."""
    return any(resolved_text.startswith(p) for p in prefixes)


def _dir_flags(dir_path: Path):
    """Cached (hidden, system) flags for one directory."""
    key = str(dir_path)
    cached = _DIR_FLAG_CACHE.get(key)
    if cached is not None:
        return cached
    hidden = dir_path.name.startswith('.')
    system = False
    if _WIN_ATTRS:
        try:
            attrs = os.stat(dir_path).st_file_attributes
            hidden = hidden or bool(attrs & _WIN_HIDDEN)
            system = bool(attrs & _WIN_SYSTEM)
        except OSError:
            pass
    cached = (hidden, system)
    _DIR_FLAG_CACHE[key] = cached
    return cached


def _ancestor_flags(file_path: Path, root: Path):
    """OR-ed (hidden, system) over every directory between root and the file."""
    hidden = system = False
    parent = file_path.parent
    while parent != root and parent != parent.parent:
        dir_hidden, dir_system = _dir_flags(parent)
        hidden = hidden or dir_hidden
        system = system or dir_system
        parent = parent.parent
    return hidden, system


def _matches_exclude_pattern(name: str, patterns: List[str]) -> bool:
    """Case-insensitive glob match, behaving identically on Windows and Linux."""
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in patterns)


# ---------------------------------------------------------------------------
# Round 12: scan-filter transparency.
#
# Every filter below is legitimate, but until now they were SILENT: a 4 GB movie
# (max_file_size_mb), a "video_backup.mp4" (exclude_patterns) or a file in a
# hidden folder (include_hidden) simply never appeared in any scan, and the user
# was told "no duplicates found" for a library that was never really looked at.
# After a data-recovery run that is the worst possible answer.
#
# So the single scanner counts every file it drops, and why; the detectors print
# one honest summary line per operation. Counting is free (no extra stat) and
# nothing about WHICH files are scanned changes -- this only makes existing
# behaviour visible. "Recovery Mode" in Settings lifts the limits themselves.
# ---------------------------------------------------------------------------
# reason -> (i18n key, English fallback, Arabic fallback), following the
# project's _honest_reason() convention: never show "[Missing: ...]".
SKIP_REASONS = {
    'too_large': ('filters.skip_too_large',
                  '{} larger than filters.max_file_size_mb ({} MB)',
                  '{} أكبر من filters.max_file_size_mb ({} ميجابايت)'),
    'too_small': ('filters.skip_too_small',
                  '{} smaller than filters.min_file_size_bytes ({} bytes)',
                  '{} أصغر من filters.min_file_size_bytes ({} بايت)'),
    'excluded_pattern': ('filters.skip_excluded_pattern',
                         '{} matched an exclude_patterns entry ({})',
                         '{} طابق نمطًا في exclude_patterns ({})'),
    'hidden': ('filters.skip_hidden',
               '{} hidden (filters.include_hidden = false)',
               '{} مخفي (filters.include_hidden = false)'),
    'system': ('filters.skip_system',
               '{} system files (filters.include_system = false)',
               '{} ملف نظام (filters.include_system = false)'),
    'unreadable': ('filters.skip_unreadable',
                   '{} unreadable (permissions or a broken link)',
                   '{} تعذّرت قراءته (أذونات أو رابط تالف)'),
    'not_regular': ('filters.skip_not_regular',
                    '{} not a regular file (folder/link/device)',
                    '{} ليس ملفًا عاديًا (مجلد/رابط/جهاز)'),
    'own_output': ('filters.skip_own_output',
                   "{} inside ImgSniper's own folders (recycle-bin/reports)",
                   '{} داخل مجلدات البرنامج (recycle-bin/reports)'),
}

# Print order: the reasons a user can actually act on come first.
SKIP_REASON_ORDER = ('too_large', 'excluded_pattern', 'hidden', 'system',
                     'too_small', 'unreadable', 'not_regular', 'own_output')

_SCAN_SKIPS = {reason: 0 for reason in SKIP_REASONS}


def reset_scan_skips() -> None:
    """Zero the skip counters at the START of one scan operation."""
    for reason in _SCAN_SKIPS:
        _SCAN_SKIPS[reason] = 0


def count_skip(reason: str) -> None:
    """Record one file dropped by a scan filter (unknown reasons are ignored)."""
    if reason in _SCAN_SKIPS:
        _SCAN_SKIPS[reason] += 1


def get_scan_skips() -> Dict[str, int]:
    """A copy of the per-reason skip counts collected since the last reset."""
    return dict(_SCAN_SKIPS)


def _skip_text(key: str, english: str, arabic: str) -> str:
    """Localized text with a hard-coded fallback (never "[Missing: ...]")."""
    try:
        value = i18n.get(key)
    except Exception:                                  # pragma: no cover
        value = None
    if value and not str(value).startswith('[Missing'):
        return str(value)
    return arabic if i18n.current_language == 'ar' else english


def announce_scan_skips(console) -> int:
    """Print WHY files were skipped; returns how many. Silent when none were.

    Called once per operation by every detector (images, office, archives,
    other and video), so no section can quietly scan less than the folder holds.
    """
    skips = get_scan_skips()
    total = sum(skips.values())
    if not total or console is None:
        return total

    filters = config.get('filters', {}) or {}
    if not isinstance(filters, dict):
        filters = {}
    max_mb = filters.get('max_file_size_mb', 0) or 0
    min_bytes = filters.get('min_file_size_bytes', 0) or 0
    patterns = ', '.join(filters.get('exclude_patterns') or []) or '-'

    header = _skip_text(
        'filters.skipped_header',
        '⚠️ {} file(s) were NOT scanned because of the scan filters '
        '(not duplicates - simply never looked at):',
        '⚠️ {} ملف لم يُفحص بسبب مرشّحات الفحص (ليست مكررة - بل لم تُفحص أصلًا):')
    console.print(f"[yellow]{header.format(total)}[/yellow]")

    for reason in SKIP_REASON_ORDER:
        count = skips.get(reason, 0)
        if not count:
            continue
        key, english, arabic = SKIP_REASONS[reason]
        line = _skip_text(key, english, arabic)
        try:
            if reason == 'too_large':
                line = line.format(count, max_mb)
            elif reason == 'too_small':
                line = line.format(count, min_bytes)
            elif reason == 'excluded_pattern':
                line = line.format(count, patterns)
            else:
                line = line.format(count)
        except (IndexError, KeyError, ValueError):     # pragma: no cover
            line = f"{count} ({reason})"
        console.print(f"[dim]     - {line}[/dim]")

    # Round 17: the advice is now CONDITIONAL. It used to print unconditionally,
    # which produced two distinct lies on a real recovery scan:
    #   * Recovery Mode was ALREADY ON, and the line still said "enable it";
    #   * the 61 skipped files were dropped by filters.min_file_size_bytes, a
    #     floor Recovery Mode deliberately does NOT lift -- so enabling it would
    #     have changed nothing at all.
    # Only reasons in RECOVERY_LIFTABLE_REASONS can actually be rescued.
    def _hint(key: str, english: str, arabic: str) -> str:
        text = _skip_text(key, english, arabic)
        try:
            return text.format(min_bytes)
        except (IndexError, KeyError, ValueError):     # pragma: no cover
            return text

    liftable = sum(skips.get(reason, 0) for reason in RECOVERY_LIFTABLE_REASONS)
    if recovery_mode_active(filters):
        console.print("[dim]     " + _hint(
            'filters.recovery_hint_already_on',
            'Recovery Mode is already ON: these files are skipped by rules it does '
            'not lift (the {} byte floor, system areas, unreadable files).',
            'وضع الاسترجاع مُفعّل أصلًا: هذه الملفات تُتخطّى بقواعد لا يرفعها '
            '(أرضية {} بايت، مناطق النظام، الملفات التي تعذّرت قراءتها).') + "[/dim]")
    elif liftable:
        console.print("[dim]     " + _hint(
            'filters.recovery_hint',
            'Tip: Settings → Recovery Mode scans these files too '
            '(no size cap, hidden files included, no name exclusions).',
            'تلميح: الإعدادات ← وضع الاسترجاع يفحص هذه الملفات أيضًا '
            '(بلا حدّ للحجم، مع الملفات المخفية، وبلا استثناء للأسماء).') + "[/dim]")
    else:
        console.print("[dim]     " + _hint(
            'filters.recovery_hint_wont_help',
            'Recovery Mode would NOT change this: these files are skipped by the '
            '{} byte floor, which it keeps on purpose (sub-KB stubs are cache '
            'noise, not media).',
            'وضع الاسترجاع لن يغيّر هذا: هذه الملفات تُتخطّى بأرضية {} بايت، '
            'والتي يبقيها عمدًا (الملفات دون الكيلوبايت ضجيج كاش لا وسائط).') + "[/dim]")
    return total


def get_all_images(folder_path: str, supported_formats: Set[str],
                   progress_cb=None) -> List[str]:
    """
    Get all image files from a folder and its subfolders.

    Applies the filters.* section of settings.json (exclude_patterns,
    include_hidden, include_system, min_file_size_bytes, max_file_size_mb) and
    never returns files inside ImgSniper's own output directories. See the
    P2-7 note above for why resolution filters are intentionally skipped.

    Every size/attribute filter treats 0 (or a missing/invalid value) as
    "disabled", so the scan can always be widened again from settings.json
    without a code change.

    Round 14: `progress_cb` is optional and purely cosmetic -- it is called with
    the number of directory entries examined since the previous call, so a walk
    that covers a whole USB hard disk shows a running count instead of a dead
    screen. Which files are accepted is decided by exactly the same filters in
    exactly the same order as before; the callback cannot influence the result.
    """
    image_files = []
    folder = Path(folder_path)

    if not folder.exists():
        return image_files

    # Read the filter settings ONCE, not per file: a scan can cover tens of
    # thousands of images and every value below is constant for the whole walk.
    filters = config.get('filters', {}) or {}
    if not isinstance(filters, dict):
        filters = {}

    exclude_patterns = [p for p in (filters.get('exclude_patterns') or [])
                        if isinstance(p, str) and p.strip()]
    include_hidden = bool(filters.get('include_hidden', False))
    include_system = bool(filters.get('include_system', False))

    try:
        min_size = max(0, int(filters.get('min_file_size_bytes', 0) or 0))
    except (TypeError, ValueError):
        min_size = 0
    try:
        max_size = max(0, int(float(filters.get('max_file_size_mb', 0) or 0)
                              * 1024 * 1024))
    except (TypeError, ValueError):
        max_size = 0

    excluded_prefixes = _get_excluded_dir_prefixes()
    _DIR_FLAG_CACHE.clear()

    examined = 0
    for file_path in folder.rglob('*'):
        examined += 1
        # Round 14: one call per 500 entries is free next to the stat() each
        # entry already costs, and it is the difference between a live count and
        # a screen that looks frozen for minutes on a USB hard disk.
        if progress_cb is not None and examined % _WALK_REPORT_EVERY == 0:
            progress_cb(_WALK_REPORT_EVERY)

        if file_path.suffix.lower() not in supported_formats:
            continue

        # A single stat() answers existence, regular-file, size and (on
        # Windows) hidden/system attributes, so the walk stays cheap.
        try:
            st = file_path.stat()
        except OSError:
            count_skip('unreadable')      # broken symlink / permission denied
            continue
        if not stat_module.S_ISREG(st.st_mode):
            count_skip('not_regular')
            continue

        # Never rescan ImgSniper's own output. Without this, files already
        # deleted into recycle-bin/ re-entered the pipeline and were reported
        # and moved again on the next run.
        if excluded_prefixes:
            try:
                resolved_text = os.path.normcase(str(file_path.resolve()))
            except OSError:
                resolved_text = os.path.normcase(str(file_path.absolute()))
            if _is_excluded(resolved_text, excluded_prefixes):
                count_skip('own_output')
                continue

        if not include_hidden or not include_system:
            hidden = file_path.name.startswith('.')
            system = False
            if _WIN_ATTRS:
                attrs = getattr(st, 'st_file_attributes', 0)
                hidden = hidden or bool(attrs & _WIN_HIDDEN)
                system = bool(attrs & _WIN_SYSTEM)
            if not hidden or not system:
                anc_hidden, anc_system = _ancestor_flags(file_path, folder)
                hidden = hidden or anc_hidden
                system = system or anc_system
            if hidden and not include_hidden:
                count_skip('hidden')
                continue
            if system and not include_system:
                count_skip('system')
                continue

        if exclude_patterns and _matches_exclude_pattern(file_path.name,
                                                        exclude_patterns):
            count_skip('excluded_pattern')
            continue

        if min_size and st.st_size < min_size:
            count_skip('too_small')
            continue
        if max_size and st.st_size > max_size:
            count_skip('too_large')
            continue

        image_files.append(str(file_path))

    if progress_cb is not None:
        remainder = examined % _WALK_REPORT_EVERY
        if remainder:
            progress_cb(remainder)

    return image_files

# Round 18: PER-SOURCE-FOLDER session cache (was a single global path).
#
# The old implementation kept ONE global folder for the whole operation and
# returned it for EVERY file, ignoring the base_path argument completely:
#
#     if _current_session_folder and _current_session_folder.exists():
#         return _current_session_folder      # base_path never consulted
#
# So the FIRST file of a run decided where every other file landed. A real
# 2 TB run proved it: 5,687 corrupted images collected from all over D:\hdd
# ended up in just two folders, and all 16,419 similar images in ONE folder,
# with 13,449 of them (82%) renamed to "<name>_1", "<name>_2", ... because
# unrelated files from unrelated folders collided on the same name. The
# structured recycle bin this module promises ("moves files here with their
# folder structure intact, so every removed file stays recoverable") was not
# preserved at all, and a removed file's original location could no longer be
# read back from disk.
#
# The cache is now keyed BY base_path: every distinct source folder keeps its
# own session folder, so files land where their real path says they belong.
_session_folders: Dict[Path, Path] = {}

# Round 18: destinations already handed out during the CURRENT dry run. A dry
# run writes nothing, so destination.exists() cannot see the collisions the
# real run would hit; without this set a dry-run report would promise the very
# same path for every same-named file and could not be compared to reality.
_dry_run_reserved: Set[str] = set()


def get_session_folder_name(base_path: Path) -> Path:
    """Return the session folder belonging to THIS source folder.

    Round 18: keyed per base_path. Two files from two different source folders
    now get two different session folders instead of both being forced into
    whichever folder the first file of the run happened to need.

    The "(2)", "(3)" ... behaviour is unchanged and still separates one run's
    output from an earlier run's output that already occupies base_path; it is
    simply resolved once per source folder now, not once per operation.
    """
    cached = _session_folders.get(base_path)
    if cached is not None:
        return cached

    # No previous output for this source folder: use it directly.
    if not base_path.exists():
        _session_folders[base_path] = base_path
        return base_path

    # base_path is taken by an earlier run -> find a free sibling name.
    counter = 2
    original_name = base_path.name
    parent = base_path.parent

    while True:
        new_name = f"{original_name} ({counter})"
        new_path = parent / new_name
        if not new_path.exists():
            _session_folders[base_path] = new_path
            return new_path
        counter += 1


def reset_session_folder():
    """Clear the per-source session cache for a new operation.

    Round 18: also drops the dry-run reservation set, so a dry run never leaks
    its simulated destinations into the next operation.
    """
    _session_folders.clear()
    _dry_run_reserved.clear()

# نقل الملف إلى سلة المهملات المنظمة
        # ينشئ هيكل مجلدات منظم حسب نوع العملية
        # يتعامل مع الملفات المحمية والمكررة الأسماء
        # يعيد مسار المجلد الذي تم النقل إليه عند النجاح

def get_recycle_bin_root() -> Path:
    """Resolve the recycle-bin root - the SINGLE source of truth for it.

    Round 18: every place that needs the bin's location now calls this instead
    of re-deriving it inline. Before this round move_to_recycle_bin(),
    MainCLI._create_directories() and the four "files moved to" footers each
    wrote their own `Path.cwd() / config.get('paths.recycle_bin', ...)`
    expression, so the location announced to the user could drift from the one
    actually written to, and the folder created at startup could differ from the
    one the moves targeted.

    Resolution is deliberately UNCHANGED (Path.cwd(), as it has always been):
    _get_excluded_dir_prefixes() documents that either the project root or the
    CWD "can be the real one depending on how the app was launched" and guards
    against both, and the round-4 test suite sandboxes itself by chdir'ing into a
    temp directory and expecting the bin to appear there. Anchoring this to the
    project root instead would silently relocate a real user's bin and break
    that isolation, for no gain: the value of this function is that all callers
    now agree, not that the anchor moved.

    An absolute configured value is honoured as-is; a relative one is anchored
    to the current working directory.
    """
    configured = config.get('paths.recycle_bin', 'recycle-bin')
    if not configured or not isinstance(configured, str):
        configured = 'recycle-bin'
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _destination_taken(destination: Path) -> bool:
    """True when a destination is used on disk OR promised by this dry run."""
    if str(destination) in _dry_run_reserved:
        return True
    return destination.exists()


def compute_recycle_destination(file_path: str, subfolder: str = None) -> Path:
    """Round 18: PURE destination computation - creates and moves nothing.

    Shared by the dry-run path and the real path on purpose. A dry run that
    computes its destination differently from the real run cannot reveal
    destination bugs, which is exactly why seventeen rounds of dry-run report
    review never exposed the session-folder pile-up fixed above: the dry-run
    branch returned before ANY of this code ran.

    Dry-run callers must register the result in _dry_run_reserved so that
    same-named files receive the same "_1", "_2" ... suffixes a real run gives.
    """
    source = Path(file_path)
    recycle_bin = get_recycle_bin_root()
    if subfolder:
        recycle_bin = recycle_bin / subfolder

    cleaned_path = clean_path_for_recycle_bin(source)

    if cleaned_path != Path("."):
        destination_dir = get_session_folder_name(recycle_bin / cleaned_path)
    else:
        destination_dir = recycle_bin

    destination = destination_dir / source.name

    # Handle filename collisions
    counter = 1
    original_destination = destination
    while _destination_taken(destination):
        destination = destination_dir / (
            f"{original_destination.stem}_{counter}{original_destination.suffix}"
        )
        counter += 1

    return destination


def _discard_partial_move(destination: Path) -> None:
    """Round 18: remove the truncated file a FAILED cross-drive move leaves.

    shutil.move() across volumes is copy2() followed by os.unlink(src). When
    the copy dies halfway - a full disk is the common case - the unlink never
    runs, so the source survives but a 0-byte or truncated file stays at the
    destination. The old code caught the exception, returned False and left
    that husk behind forever: one real run filled C: and dumped hundreds of
    0-byte .jpg files into recycle-bin/similar, which the user later moved to
    an external disk and understandably reported as "corrupted images".

    Only ever called from the exception path, where the source still exists, so
    removing the destination can never destroy the only copy.
    """
    try:
        if destination.exists():
            destination.unlink()
    except OSError as e:
        logger.warning("Could not remove partial file %s: %s", destination, e)


# Round 18: headroom kept free on the recycle-bin volume. The operating system
# itself needs room to keep working (page file, journals, temp files), so a move
# that would leave exactly zero bytes free is treated as a failure even though
# it technically fits.
CAPACITY_SAFETY_MARGIN_BYTES = 512 * 1024 * 1024


def _format_bytes(num) -> str:
    """Human-readable size for the capacity-check messages."""
    try:
        num = float(num)
    except (TypeError, ValueError):
        return str(num)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(num) < 1024.0 or unit == 'TB':
            return f"{int(num)} B" if unit == 'B' else f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} TB"


def _drive_of(path) -> str:
    """Comparable volume key for a path ('' when it cannot be determined)."""
    try:
        anchor = Path(path).anchor        # 'C:\\' on Windows, '/' on POSIX
        return os.path.normcase(anchor) if anchor else ''
    except (OSError, ValueError):
        return ''


def recycle_bin_capacity_report(file_paths) -> Dict[str, Any]:
    """Round 18: PURE computation - how much room a deletion actually needs.

    A move WITHIN one volume is os.rename(): instant, atomic and free. A move
    ACROSS volumes is copy2() + unlink(): it needs the file's full size on the
    destination volume, and when that volume fills up mid-run the copy dies and
    leaves a 0-byte husk behind. Only cross-volume files are therefore counted;
    a user whose recycle bin sits on the same disk as the photos is never
    bothered by this check at all.

    Returns {'needed', 'free', 'total', 'cross_volume', 'bin_drive', 'bin_root',
    'ok'}.
    """
    bin_root = get_recycle_bin_root()
    bin_drive = _drive_of(bin_root)

    needed = 0
    cross_volume = 0
    total = 0
    for path in file_paths:
        if not path:
            continue
        try:
            size = Path(path).stat().st_size
        except OSError:
            continue
        total += 1
        src_drive = _drive_of(path)
        if bin_drive and src_drive and src_drive == bin_drive:
            continue                      # same volume -> rename, costs nothing
        needed += size
        cross_volume += 1

    # disk_usage() needs an EXISTING path, and the bin may not have been created
    # yet (a fresh install, or a nested configured value like "bin/2025"). Walk up
    # to the nearest ancestor that does exist: the volume's free space is the same
    # from any point on it. Without this the gate would read free=None on a
    # machine that has never run a deletion before and silently allow anything.
    free = None
    probe = bin_root
    while True:
        try:
            if probe.exists():
                free = shutil.disk_usage(str(probe)).free
                break
        except OSError:
            break
        if probe.parent == probe:
            break
        probe = probe.parent

    ok = True
    if needed > 0 and free is not None:
        ok = (needed + CAPACITY_SAFETY_MARGIN_BYTES) <= free

    return {'needed': needed, 'free': free, 'total': total,
            'cross_volume': cross_volume, 'bin_drive': bin_drive or '?',
            'bin_root': bin_root, 'ok': ok}


def ensure_recycle_bin_capacity(file_paths, console) -> bool:
    """Round 18: refuse to START a deletion that cannot finish.

    Returns True when the operation may proceed and False when the user chose to
    stop. Nothing has been moved either way - callers run this BEFORE the
    deletion loop, which is the whole point: the old code discovered a full disk
    one file at a time, thousands of files deep into the run.

    A real 2 TB pass proved why this is needed. The recycle bin lived on a
    172 GB system disk while the files lived on a 2 TB disk, the disk filled
    part-way through the similar-images deletion, every later shutil.move()
    failed with "[Errno 28] No space left on device", those errors were
    swallowed by the callers' bare `except Exception: pass`, and the run ended
    with hundreds of 0-byte husks in the bin and - because the report writer
    also hit ENOSPC - no report at all.
    """
    if config.get('safety.dry_run_mode', False):
        return True                       # a dry run moves nothing, needs no room

    if not file_paths:
        return True

    info = recycle_bin_capacity_report(file_paths)

    if info['needed'] == 0:
        console.print(f"[dim]{i18n.get('safety.capacity_same_drive')}[/dim]")
        return True

    console.print(f"[bold cyan]{i18n.get('safety.capacity_title')}[/bold cyan]")
    console.print("  " + i18n.get('safety.capacity_needed').format(
        info['cross_volume'], _format_bytes(info['needed'])))
    if info['free'] is not None:
        console.print("  " + i18n.get('safety.capacity_free').format(
            info['bin_drive'], _format_bytes(info['free'])))

    if info['ok']:
        console.print(f"[green]{i18n.get('safety.capacity_ok')}[/green]")
        return True

    console.print(f"[bold red]{i18n.get('safety.capacity_insufficient')}[/bold red]")
    try:
        answer = ask_line(f"{i18n.get('safety.capacity_proceed_question')} [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        answer = ''
    if str(answer).strip().lower() in ('y', 'yes'):
        logger.warning("Capacity check overridden by the user: needed %s bytes, free %s bytes",
                       info['needed'], info['free'])
        return True

    console.print(f"[bold red]{i18n.get('safety.capacity_aborted')}[/bold red]")
    logger.warning("Operation aborted by the capacity check: needed %s bytes, free %s bytes",
                   info['needed'], info['free'])
    return False


def move_to_recycle_bin(file_path: str, subfolder: str = None):
    """Move a file to the recycle bin directory preserving folder structure.

    Args:
        file_path: Path to the file to move
        subfolder: Optional subfolder within recycle bin (e.g., 'small', 'corrupted')

    Audit P3-8: this function IS the recovery mechanism. ImgSniper never
    permanently deletes - it moves files here with their folder structure
    intact, so every removed file stays recoverable. That is exactly why the
    inert safety.create_backup / safety.preserve_originals settings were
    REMOVED rather than wired up: both described a guarantee this function
    already provides unconditionally, and a safety toggle that cannot actually
    be turned off is a false guarantee rather than a feature.

    Round 18 hardening, after a real 2 TB run filled the system disk:
      * the dry-run branch now computes and reports the REAL destination
        instead of returning before any destination logic ran;
      * the destination is computed by compute_recycle_destination(), the same
        code in both modes;
      * a FAILED move no longer leaves a 0-byte/truncated husk behind;
      * a successful move is size-verified, and because shutil.move() has
        already unlinked the source by then, a mismatch is reported and counted
        as a failure but the bytes are NEVER deleted.
    """
    source = Path(file_path)
    if not source.exists():
        return

    # safety.dry_run_mode: announce what WOULD be moved and touch nothing.
    # Checked BEFORE any mkdir so a dry run leaves the filesystem completely
    # untouched (no empty recycle-bin dirs either).
    # The "dry_run" sentinel is deliberately NOT in the callers' skip-lists, so
    # reports and counters still show exactly what would have been deleted.
    # Round 8: the per-file announcement goes to the LOG FILE only -- one
    # console line per file used to flood the UI with thousands of lines on
    # large libraries.
    # Round 18: the announced line now includes the DESTINATION, computed by
    # the very same function the real move uses. Before this round the dry-run
    # branch returned here and get_session_folder_name() / clean_path_for_
    # recycle_bin() were never executed at all, so no amount of dry-run report
    # review could ever show where files would actually land.
    if config.get('safety.dry_run_mode', False):
        try:
            destination = compute_recycle_destination(file_path, subfolder)
        except Exception as e:
            logger.warning("Dry-run destination could not be computed for %s: %s", source, e)
            destination = None
        if destination is not None:
            _dry_run_reserved.add(str(destination))
            logger.info("%s: %s -> %s",
                        i18n.get('safety.dry_run_would_move'), source, destination)
        else:
            logger.info("%s: %s", i18n.get('safety.dry_run_would_move'), source)
        return "dry_run"

    # Round 18: single deterministic root (was Path.cwd()).
    recycle_bin = get_recycle_bin_root()
    if subfolder:
        recycle_bin = recycle_bin / subfolder
    recycle_bin.mkdir(parents=True, exist_ok=True)

    destination = compute_recycle_destination(file_path, subfolder)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Cannot create recycle-bin folder %s: %s", destination.parent, e)
        _safe_print(f"\u274c {i18n.get('protected_files.error_moving')} {source} \u2192 {destination}: {e}")
        return False
    # Check if the file is read-only or protected before attempting to move
    try:
        if source.exists():
            import stat
            file_stat = source.stat()

            if not (file_stat.st_mode & stat.S_IWRITE):
                _safe_print(f"\u23ed\ufe0f {i18n.get('protected_files.skipping_readonly')}: {source}")
                _safe_print(f"   {i18n.get('protected_files.file_protected')}")
                return "skipped_readonly"

            # Try to open the file to check if it is in use
            try:
                with open(source, 'r+b'):
                    pass
            except PermissionError:
                _safe_print(f"\u23ed\ufe0f {i18n.get('protected_files.skipping_protected')}: {source}")
                _safe_print(f"   {i18n.get('protected_files.file_in_use')}")
                return "skipped_protected"

    except Exception:
        _safe_print(f"\u23ed\ufe0f {i18n.get('protected_files.access_check_failed')}: {source}")
        return "skipped_error"

    # Round 18: size captured BEFORE the move so the result can be verified.
    try:
        source_size = source.stat().st_size
    except OSError:
        source_size = None

    # Move the file only if it is not protected
    try:
        shutil.move(str(source), str(destination))
    except PermissionError as e:
        _discard_partial_move(destination)
        logger.error("Move blocked (permission) %s -> %s: %s", source, destination, e)
        _safe_print(f"\u26a0\ufe0f {i18n.get('protected_files.protection_changed')}: {source}: {e}")
        return False
    except FileNotFoundError as e:
        _discard_partial_move(destination)
        logger.error("Move failed (not found) %s -> %s: %s", source, destination, e)
        _safe_print(f"\u274c {i18n.get('protected_files.file_not_found')}: {source}: {e}")
        return False
    except Exception as e:
        # Round 18: a full disk surfaces here (OSError 28 / WinError 112).
        # The husk left at the destination is removed; the source is intact
        # because shutil.move() unlinks it only AFTER a successful copy.
        _discard_partial_move(destination)
        logger.error("Move failed %s -> %s: %s", source, destination, e)
        _safe_print(f"\u274c {i18n.get('protected_files.error_moving')} {source} \u2192 {destination}: {e}")
        return False

    # shutil.move() returned, so the source is GONE and the destination is now
    # the ONLY copy. It must never be deleted from here on: a size mismatch is
    # logged and counted as a failure, but the bytes are kept.
    if source_size is not None:
        try:
            moved_size = destination.stat().st_size
        except OSError:
            moved_size = None
        if moved_size != source_size:
            logger.error("Size mismatch after move (source %s bytes, moved %s bytes): %s",
                         source_size, moved_size, destination)
            _safe_print(f"\u26a0\ufe0f {i18n.get('safety.move_size_mismatch')}: {destination}")
            return False

    # Round 8: return the FULL destination path (was the parent folder) so the
    # callers can show "moved to <path>" lines in the reports. Callers that
    # only need the folder derive it with Path(result).parent.
    return str(destination)

# فحص ما إذا كان الملف محمي أو للقراءة فقط
        # يتحقق من صلاحيات النظام وحالة الاستخدام
        # يدعم أنظمة Windows و Linux و Mac
        # يعيد True إذا كان الملف محمي أو قيد الاستخدام

# فحص حالة حماية الملف وصلاحيات الوصول
# ═══════════════════════════════════════════
# يتحقق من:
# • صلاحيات القراءة والكتابة
# • حالة read-only
# • استخدام الملف من برنامج آخر
# • قيود نظام التشغيل
# يدعم: Windows, Linux, macOS
def is_file_protected(file_path: str) -> bool:
    """Check if a file is read-only or protected before attempting operations."""
    source = Path(file_path)
    
    try:
        if not source.exists():
            return False
            
        # فحص ملف سمات on Windows
        import stat
        file_stat = source.stat()
        
        # فحص if ملف is read-only
        if not (file_stat.st_mode & stat.S_IWRITE):
            return True
        
        # Try to open ملف to check if it's in use
        try:
            with open(source, 'r+b'):
                pass
        except PermissionError:
            return True
            
        return False
        
    except Exception:
        return True  # Consider as protected if we can't check

# إزالة حماية الملف وصلاحيات القراءة فقط
        # يستخدم chmod على Linux/Mac و attrib على Windows
        # يحاول عدة طرق لإزالة الحماية
        # يعيد True إذا تمت إزالة الحماية بنجاح

def remove_file_protection(file_path: str) -> bool:
    """Remove read-only and protection attributes from a file."""
    source = Path(file_path)
    
    try:
        if not source.exists():
            return False
            
        import stat
        import os
        
        # جلب حالي إذنs
        current_permissions = source.stat().st_mode
        
        # Add write إذنs
        new_permissions = current_permissions | stat.S_IWUSR | stat.S_IWRITE
        
        # Apply جديد إذنs
        os.chmod(source, new_permissions)
        
        # On Windows, also محاولة to remove read-only attribute
        if os.name == 'nt':
            try:
                import subprocess
                # إزالة read-only attribute using Windows attrib أمر
                subprocess.run(['attrib', '-R', str(source)], 
                             capture_output=True, check=False)
            except Exception:
                pass  # Fجميعback to chmod only
                
        return True
        
    except Exception as e:
        _safe_print(f"⚠️ {i18n.get('protected_files.force_failed').format(1)} {file_path}: {e}")
        return False

# حذف قسري للملف المحمي
        # يزيل الحماية أولاً ثم ينقل الملف
        # آمن - لا يحذف الملفات المستخدمة من برامج أخرى
        # يعيد True إذا تم الحذف بنجاح

def force_delete_protected_file(file_path: str, subfolder: str = "protected") -> bool:
    """Force delete a protected file by removing protection first."""
    try:
        # First, محاولة to remove protection
        if remove_file_protection(file_path):
            _safe_print(f"🔓 {i18n.get('protected_files.protection_removed').format(Path(file_path).name)}")
            
            # Now محاولة to move to recycle bin
            result = move_to_recycle_bin(file_path, subfolder=subfolder)
            
            if result and result not in ["skipped_readonly", "skipped_protected", "skipped_error"]:
                return True
        
        return False
        
    except Exception as e:
        _safe_print(f"❌ {i18n.get('protected_files.force_failed').format(1)}: {file_path}: {e}")
        return False

def filter_protected_files(file_list: list, force_delete: bool = False,
                           console=None) -> tuple:
    """Filter protected files from a list. 
    Args:
        file_list: List of file paths
        force_delete: If True, try to force delete protected files
        console: optional; only drives a progress bar (round 14)
    Returns: 
        (available_files, protected_files, force_deletable_files)

    Round 14: classifying touches EVERY file in the list, which on a USB disk
    with tens of thousands of entries is a visibly long phase that used to print
    nothing until it finished. The classification itself is untouched -- only its
    progress is shown, and the per-file notices are collected and printed once
    the bar closes, because they go through this module's own console and two
    consoles writing one terminal would tear the live display apart.
    """
    available_files = []
    protected_files = []
    force_deletable_files = []
    pending_notices = []

    with track(console, i18n.get('common.classifying_files'),
               len(file_list)) as (progress, task):
        for file_path in file_list:
            if is_file_protected(file_path):
                if force_delete:
                    # فحص if we can إمكانيةly قوة delete this ملف
                    if can_force_delete(file_path):
                        force_deletable_files.append(file_path)
                        pending_notices.append(f"🔓 {i18n.get('protected_files.detected_protected').format(1)} ({i18n.get('protected_files.force_delete_option')}): {Path(file_path).name}")
                    else:
                        protected_files.append(file_path)
                        pending_notices.append(f"⛔ {i18n.get('protected_files.cannot_force_delete').format(1)}: {Path(file_path).name}")
                else:
                    protected_files.append(file_path)
                    pending_notices.append(f"⏭️ {i18n.get('protected_files.skipping_readonly')}: {Path(file_path).name}")
            else:
                available_files.append(file_path)
            progress.advance(task)

    for notice in pending_notices:
        _safe_print(notice)

    return available_files, protected_files, force_deletable_files

def can_force_delete(file_path: str) -> bool:
    """Check if a protected file can potentially be force deleted."""
    source = Path(file_path)
    
    try:
        if not source.exists():
            return False
            
        # فحص if ملف is in use by another عملية
        try:
            with open(source, 'r+b'):
                pass
            # If we can open it, we can probably delete it
            return True
        except PermissionError:
            # File might be in use, but we can still محاولة to remove protection
            return True
        except Exception:
            return False
            
    except Exception:
        return False

# التعامل مع الملفات المحمية مع خيار المستخدم
        # يصنف الملفات إلى: عادية، محمية قابلة للحذف، محمية بقوة
        # يسأل المستخدم عن الحذف القسري للملفات المحمية
        # يعيد: (ملفات_للمعالجة، عدد_المحمية، عدد_المحذوفة_قسرياً)

# التعامل الذكي مع الملفات المحمية
# ════════════════════════════════════
# العملية:
# 1. تصنيف الملفات (عادية، محمية، محمية بقوة)
# 2. عرض خيارات على المستخدم
# 3. الحذف القسري للملفات المحمية (اختياري)
# 4. تقرير شامل عن النتائج
# الأمان: لا يحذف الملفات الحيوية للنظام
def handle_protected_files_with_user_choice(files_to_delete: list, console, subfolder: str = "protected") -> tuple:
    """Handle protected files with user choice for force deletion.
    Returns: (final_files_to_delete, protected_files_count, force_deleted_count)
    """
    from ...core.i18n.i18n import i18n
    
    # فحص for protected ملفات
    available_files, protected_files, force_deletable_files = filter_protected_files(
        files_to_delete, force_delete=True, console=console)
    
    if not protected_files and not force_deletable_files:
        return available_files, 0, 0
    
    total_protected = len(protected_files) + len(force_deletable_files)
    console.print(f"[yellow]{i18n.get('protected_files.detected_protected').format(total_protected)}[/yellow]")
    
    # If there are قوة-deleجدول ملفات, ask مستخدم
    force_deleted_count = 0
    if force_deletable_files:
        console.print(f"[yellow]{i18n.get('protected_files.force_delete_option')}[/yellow]")
        console.print(f"[red]{i18n.get('protected_files.force_delete_warning')}[/red]")
        
        try:
            # Round 14: drain keys typed while the scan/selection was running, so
            # a FORCE-DELETE answer is always deliberate -- a buffered Enter from
            # an impatient keypress must never reach this prompt.
            choice = ask_line(f"{i18n.get('protected_files.force_delete_confirm')} ").strip().lower()
            
            if choice in ['y', 'yes', 'نعم', 'ن']:
                console.print(f"[yellow]{i18n.get('protected_files.removing_protection')}[/yellow]")
                
                # Try to قوة delete كل protected ملف
                successfully_force_deleted = []
                for file_path in force_deletable_files:
                    if force_delete_protected_file(file_path, subfolder):
                        successfully_force_deleted.append(file_path)
                        force_deleted_count += 1
                
                if successfully_force_deleted:
                    console.print(f"[green]{i18n.get('protected_files.force_deleted').format(len(successfully_force_deleted))}[/green]")
                
                # Failed قوة deletions reرئيسي in protected قائمة
                failed_force_deletions = [f for f in force_deletable_files if f not in successfully_force_deleted]
                protected_files.extend(failed_force_deletions)
                
                if failed_force_deletions:
                    console.print(f"[red]{i18n.get('protected_files.force_failed').format(len(failed_force_deletions))}[/red]")
                    
            else:
                # User chose not to قوة delete
                protected_files.extend(force_deletable_files)
                console.print(f"[yellow]{i18n.get('protected_files.skip_protected').format(len(force_deletable_files))}[/yellow]")
                
        except KeyboardInterrupt:
            protected_files.extend(force_deletable_files)
            console.print(f"[yellow]{i18n.get('protected_files.skip_protected').format(len(force_deletable_files))}[/yellow]")
    
    # Show نهائي ملخص
    if protected_files:
        console.print(f"[yellow]{i18n.get('protected_files.cannot_force_delete').format(len(protected_files))}[/yellow]")
    
    return available_files, len(protected_files), force_deleted_count

def get_file_info(file_path: str) -> dict:
    """Get detailed information about a file."""
    path = Path(file_path)
    
    if not path.exists():
        return {}
    
    stat = path.stat()
    
    return {
        'name': path.name,
        'size': stat.st_size,
        'modified_time': stat.st_mtime,
        'created_time': stat.st_ctime,
        'path': str(path)
    }