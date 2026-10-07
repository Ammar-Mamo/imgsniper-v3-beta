"""
Video-specific canonical-file selection (Round 11).
اختيار النسخة التي ستبقى داخل مجموعة فيديوهات متطابقة تمامًا.

Why this is NOT FileSelector
----------------------------
FileSelector is right for images and stays untouched. Three of its assumptions
do not hold for a video group:

  * an exact video duplicate group has no resolution, no codec and no container
    metadata in this phase (no decoder is installed -- and none is needed for
    byte-exact matching), so the resolution criterion would be pure noise;
  * videos carry no EXIF, and date_extractor.get_best_date() opens every file
    with PIL looking for one -- on a multi-GB file that is waste. The date here
    comes from the FILENAME (validated) and otherwise from the mtime;
  * the user must be able to READ why a file survived, so every decision made
    here carries its own reasons instead of only a winner.

What IS reused (pure functions, no coupling):
  * date_extractor.extract_date_from_filename() -- validates every candidate
    with strptime, so "20189999" or "12345678" never become a date;
  * date_extractor.normalize_arabic_numbers() -- so "نسخة ١" is read correctly;
  * file_selector.ratio_scores() / compute_date_scores() -- the SAME
    group-normalised 0-10 scales and no-decision gates the image engine uses,
    so video decisions obey the project's thresholds instead of new ones.

Deliberately NOT touched: date_extractor.filename_importance. Extending that
map (for "(15)", "نسخة" or "recovery") would silently change which IMAGE is
kept, so the video name heuristics live here instead.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import config, DEFAULT_PRIORITY_ORDER
from .file_selector import compute_date_scores, ratio_scores
from .i18n.i18n import i18n
from ..utils.helpers.date_extractor import date_extractor

# ---------------------------------------------------------------------------
# Name provenance -- the PRIMARY sort key.
#
# A copy counter, a "Copy" word or a recovery-style name is evidence about
# WHERE a file came from, which is stronger than any score: "20180817 (1).mp4"
# is a derived copy even when its date is the oldest in the group. The classes
# below are therefore compared FIRST, and the weighted criteria (date /
# filename / size, in the user's own priority order) only decide BETWEEN files
# of the same class. That satisfies both rules at once:
#   * an original-looking name beats a copy-suffixed one   (class gate);
#   * among equally original names the OLDER date wins     (weighted criteria).
# ---------------------------------------------------------------------------
CLASS_RECOVERED = 0
CLASS_COPY = 1
CLASS_WEAK = 2
CLASS_NEUTRAL = 3
CLASS_ORIGINAL = 4

# (i18n key, English fallback, Arabic fallback) -- a report can never print
# "[Missing: ...]", following the _honest_reason() convention of round 5.
CLASS_LABELS = {
    CLASS_ORIGINAL: ('video_reasons.class_original',
                     'original-looking name', 'اسم يبدو أصليًا'),
    CLASS_NEUTRAL: ('video_reasons.class_neutral',
                    'neutral name (no copy or recovery marker)',
                    'اسم محايد (بلا علامة نسخ أو استرداد)'),
    CLASS_WEAK: ('video_reasons.class_weak',
                 'weak marker in the name (backup / temp / edited)',
                 'علامة ضعيفة في الاسم (نسخة احتياطية / مؤقت / معدّل)'),
    CLASS_COPY: ('video_reasons.class_copy',
                 'copy-suffixed or copy-named', 'اسم بلاحقة نسخ أو بكلمة نسخ'),
    CLASS_RECOVERED: ('video_reasons.class_recovered',
                      'recovery-style name', 'اسم بأسلوب الاسترداد'),
}

# The SAME 1-9 filename scale the image engine uses, so ratio_scores() behaves
# identically here and the two engines stay comparable.
IMPORTANCE_BY_CLASS = {
    CLASS_ORIGINAL: 9,
    CLASS_NEUTRAL: 5,
    CLASS_WEAK: 3,
    CLASS_COPY: 2,
    CLASS_RECOVERED: 1,
}

# ---------------------------------------------------------------------------
# Name markers. Matched as WORDS (token equality or token prefix), never as raw
# substrings, so "David.mp4" is not a "vid" camera file. Detection reads the
# FILENAME TEXT only -- it never asks the operating system for a locale, so the
# behaviour is identical on every system language.
# ---------------------------------------------------------------------------
RECOVERY_MARKERS = ('recovered', 'recovery', 'recover', 'restored', 'restore',
                    'undeleted', 'undelete', 'salvaged', 'salvage',
                    'مستردة', 'مسترد', 'مستعادة', 'مستعاد', 'استرداد', 'استعادة')
COPY_MARKERS = ('copy', 'clone', 'duplicate',
                'نسخة', 'نسخ', 'مكررة', 'مكرر', 'تكرار')
WEAK_MARKERS = ('backup', 'bak', 'temp', 'tmp', 'edited', 'modified', 'new',
                'converted', 'convert', 'exported', 'export',
                'احتياطية', 'احتياطي', 'مؤقت', 'معدّل', 'معدل')
ORIGINAL_MARKERS = ('original', 'orig', 'camera', 'video', 'vid', 'img',
                    'image', 'dsc', 'dcim', 'photo', 'pic', 'clip', 'rec')

# "file (1).mp4" / "file (15).mp4": a parenthesised number at the END of the
# stem is a copy counter -- any number of digits, not just 1-9.
# Any number of digits, not only 1-4: "copy (99999999)" and "(221973601)" are
# de-duplication counters exactly like "(2)". A parenthesised YEAR stays exempt
# because YEAR_SUFFIX_RE below is tested FIRST (see analyze_video_filename).
COPY_SUFFIX_RE = re.compile(r'\(\s*(\d+)\s*\)\s*$')
# "Movie (2018).mp4" is a YEAR, not a copy counter, and must not be penalised.
YEAR_SUFFIX_RE = re.compile(r'\(\s*(?:19|20)\d{2}\s*\)\s*$')

# Tokens are runs of digits / latin letters / Arabic letters. Everything else
# (spaces, dashes, underscores, dots, brackets) separates them.
_TOKEN_RE = re.compile(r'[^0-9a-z\u0600-\u06ff]+')
_EIGHT_DIGITS_RE = re.compile(r'\d{8}')


def _text(key: str, english: str, arabic: str, *args) -> str:
    """Localized text with a hard-coded fallback (never "[Missing: ...]")."""
    value = None
    try:
        value = i18n.get(key)
    except Exception:                                  # pragma: no cover
        value = None
    if not value or str(value).startswith('[Missing'):
        value = arabic if i18n.current_language == 'ar' else english
    value = str(value)
    if args:
        try:
            return value.format(*args)
        except (IndexError, KeyError, ValueError):     # pragma: no cover
            logging.debug('video reason %s could not format %s', key, args)
            return value
    return value


def _tokens(stem: str) -> List[str]:
    """Word tokens of a stem, Arabic numerals normalised, lower-cased."""
    normalized = date_extractor.normalize_arabic_numbers(str(stem or '').lower())
    return [token for token in _TOKEN_RE.split(normalized) if token]


def _match_marker(tokens: List[str], markers) -> Tuple[Optional[str], Optional[str]]:
    """First (token, marker) where the token IS or STARTS WITH the marker."""
    for token in tokens:
        for marker in markers:
            if token == marker or token.startswith(marker):
                return token, marker
    return None, None


def _is_date_only_stem(stem: str, tokens: List[str]) -> bool:
    """True when the whole stem is nothing but a date ("20180817", "2018-08-17")."""
    return bool(tokens) and all(token.isdigit() for token in tokens) \
        and bool(re.fullmatch(r'[\d\-_./\s]+', str(stem or '')))


def analyze_video_filename(filename: str) -> Dict[str, Any]:
    """Explainable analysis of ONE video filename (no file access at all).

    Returns the provenance class, the 1-9 importance, the validated filename
    date and the human-readable reasons behind both. These are HEURISTICS, not
    truth -- a name can lie, which is exactly why the reasons are recorded: a
    report can show why a file was preferred and the user can overrule it.

    Numbers are never penalised as such: "20180817.mp4", "Episode 2.mp4",
    "Video 01.mp4" and "Camera 02.mp4" carry no copy marker. Only a
    parenthesised counter at the END of the stem counts as one, and a
    parenthesised YEAR does not.
    """
    name = Path(str(filename or '')).name
    stem = Path(str(filename or '')).stem
    tokens = _tokens(stem)
    reasons: List[str] = []
    provenance = CLASS_NEUTRAL
    copy_suffix = None

    # 1) A copy counter in parentheses at the end of the stem.
    match = COPY_SUFFIX_RE.search(stem)
    if match:
        number = match.group(1)
        if YEAR_SUFFIX_RE.search(stem):
            reasons.append(_text('video_reasons.year_not_copy',
                                 '"{}" is a year in parentheses, not a copy number',
                                 '"{}" سنة بين قوسين وليست رقم نسخة', f'({number})'))
        else:
            copy_suffix = f'({number})'
            provenance = min(provenance, CLASS_COPY)
            reasons.append(_text('video_reasons.copy_suffix',
                                 'copy suffix "{}" at the end of the name',
                                 'لاحقة نسخ "{}" في آخر الاسم', copy_suffix))

    # 2) Word markers, worst class first, so "Recovered Copy" stays RECOVERED.
    token, marker = _match_marker(tokens, RECOVERY_MARKERS)
    if marker:
        provenance = min(provenance, CLASS_RECOVERED)
        reasons.append(_text('video_reasons.recovery_marker',
                             'recovery marker "{}" in the name',
                             'علامة استرداد "{}" في الاسم', token))

    token, marker = _match_marker(tokens, COPY_MARKERS)
    if marker:
        provenance = min(provenance, CLASS_COPY)
        reasons.append(_text('video_reasons.copy_marker',
                             'copy marker "{}" in the name',
                             'علامة نسخ "{}" في الاسم', token))

    token, marker = _match_marker(tokens, WEAK_MARKERS)
    if marker:
        provenance = min(provenance, CLASS_WEAK)
        reasons.append(_text('video_reasons.weak_marker',
                             'weak marker "{}" in the name',
                             'علامة ضعيفة "{}" في الاسم', token))

    # 3) Original-looking markers. They can only LIFT a name that no marker
    #    lowered, so "Camera Copy.mp4" never becomes an original.
    token, marker = _match_marker(tokens, ORIGINAL_MARKERS)
    if marker and provenance >= CLASS_NEUTRAL:
        provenance = CLASS_ORIGINAL
        reasons.append(_text('video_reasons.original_marker',
                             'camera/original marker "{}" in the name',
                             'علامة كاميرا/أصل "{}" في الاسم', token))

    # 4) Dates -- validated by date_extractor, never "any long number".
    name_date = None
    try:
        name_date = date_extractor.extract_date_from_filename(name)
    except Exception:                                  # pragma: no cover
        name_date = None

    if name_date:
        reasons.append(_text('video_reasons.valid_date',
                             'valid date in the filename: {}',
                             'تاريخ صالح في اسم الملف: {}',
                             name_date.strftime('%Y-%m-%d')))
        if provenance >= CLASS_NEUTRAL and _is_date_only_stem(stem, tokens):
            provenance = CLASS_ORIGINAL
            reasons.append(_text('video_reasons.dated_original',
                                 'the whole name is a valid date - a camera-style original',
                                 'الاسم بالكامل تاريخ صالح - أصل بأسلوب الكاميرا'))
    else:
        # Honesty: an 8-digit run that is NOT a valid date is reported as
        # ignored, instead of silently looking like "no date at all".
        for chunk in _EIGHT_DIGITS_RE.findall(stem):
            if date_extractor.extract_date_from_filename(chunk) is None:
                reasons.append(_text('video_reasons.invalid_date_ignored',
                                     '"{}" looks like a date but is not a valid one - ignored',
                                     '"{}" يبدو تاريخًا لكنه ليس تاريخًا صالحًا - تم تجاهله',
                                     chunk))
                break
        reasons.append(_text('video_reasons.no_date_in_name',
                             'no valid date in the filename',
                             'لا يوجد تاريخ صالح في اسم الملف'))

    if provenance >= CLASS_NEUTRAL:
        reasons.append(_text('video_reasons.clean_name',
                             'no copy or recovery marker - the name looks original',
                             'لا علامة نسخ أو استرداد - الاسم يبدو أصليًا'))

    key, english, arabic = CLASS_LABELS[provenance]
    return {
        'name': name,
        'stem': stem,
        'provenance': provenance,
        'provenance_label': _text(key, english, arabic),
        'importance': IMPORTANCE_BY_CLASS[provenance],
        'copy_suffix': copy_suffix,
        'filename_date': name_date,
        'reasons': reasons,
    }


# ---------------------------------------------------------------------------
# Dates and weights
# ---------------------------------------------------------------------------
def get_video_date(file_path: str,
                   date_priority: str = 'oldest') -> Tuple[Optional[datetime], str]:
    """The date a video is judged by: a VALID date in the name, else the mtime.

    date_extractor.get_best_date() is deliberately NOT used: it opens the file
    with PIL looking for EXIF, which a video does not have -- on a multi-GB file
    that is pure waste. extract_date_from_filename() IS reused, and it validates
    every candidate with strptime, so "20189999" or "12345678" never become a
    date. The source is returned next to the value ('filename' / 'modified' /
    'none') so a report never pretends a modification time was a real date.
    """
    name = Path(str(file_path or '')).name
    try:
        name_date = date_extractor.extract_date_from_filename(name)
    except Exception:                                  # pragma: no cover
        name_date = None
    if name_date:
        return name_date, 'filename'

    try:
        modified = datetime.fromtimestamp(Path(file_path).stat().st_mtime)
    except (OSError, OverflowError, ValueError):
        # An unreadable file simply has no date: it loses the date criterion
        # (compute_date_scores scores an unknown date below any known one) and
        # is never preferred because of it.
        logging.debug('No modification time readable for %s', file_path)
        return None, 'none'
    return modified, 'modified'


# Positional meaning of priorities.order, exactly as the image engine reads it.
PRIORITY_POSITIONS = ('resolution', 'size', 'date', 'filename')
# The criteria a video group can actually differ in (no resolution in this phase).
VIDEO_CRITERIA = ('filename', 'date', 'size')


def video_criterion_weights(priority_order=None) -> Dict[str, float]:
    """Weights for the three criteria a video group can really differ in.

    Resolution has no data here (no decoder, and byte-exact matching does not
    need one), so the rank the user gave it is dropped and the remaining three
    keep their relative order on a 3/2/1 scale. With the shipped order
    [2, 3, 1, 4] -- date > resolution > size > filename -- that yields
    date 3.0 > size 2.0 > filename 1.0: the user's own priority, minus the one
    criterion that cannot be measured.

    Exact duplicates always share one size, so inside a provenance class the
    DATE decides in practice -- which is the behaviour that was asked for.
    """
    order = priority_order if (isinstance(priority_order, list)
                               and sorted(priority_order) == [1, 2, 3, 4]) \
        else list(DEFAULT_PRIORITY_ORDER)
    ranks = dict(zip(PRIORITY_POSITIONS, order))
    kept = {criterion: 5 - ranks[criterion] for criterion in VIDEO_CRITERIA}
    ranked = sorted(kept, key=lambda criterion: -kept[criterion])
    return {criterion: float(len(ranked) - index) for index, criterion in enumerate(ranked)}


def _file_size(file_path: str) -> int:
    """Byte size, or 0 when it cannot be read (ratio_scores() then scores it 0)."""
    try:
        return Path(file_path).stat().st_size
    except OSError:
        logging.debug('Size unreadable for %s', file_path)
        return 0


def _file_mtime(file_path: str) -> datetime:
    """Modification time; datetime.max when unreadable so it sorts LAST."""
    try:
        return datetime.fromtimestamp(Path(file_path).stat().st_mtime)
    except (OSError, OverflowError, ValueError):
        logging.debug('Modification time unreadable for %s', file_path)
        return datetime.max


# ---------------------------------------------------------------------------
# The selector
# ---------------------------------------------------------------------------
class VideoFileSelector:
    """Choose the surviving copy inside an EXACT video duplicate group.

    Detection, selection and deletion stay separate: this class only decides
    WHO SURVIVES and WHY. It never touches the filesystem beyond stat(), so a
    group can be inspected without deleting anything.
    """

    def select_best_file(self, files: List[str],
                         fallback_mtime: bool = True) -> Tuple[Optional[str], Dict[str, Any]]:
        """Return (kept_file, decisions) -- deterministic and explainable.

        `decisions` maps EVERY path of the group to its full explanation:
        provenance class + label, 1-9 importance, date and its source, the per
        criterion scores, weights, weighted total, mtime, is_kept and the list
        of human-readable reasons. Reports print it; tests assert on it.

        `fallback_mtime` is accepted for signature symmetry with
        FileSelector.select_best_file(); a video ALWAYS falls back to its
        modification time (there is no EXIF), so the flag changes nothing.
        """
        paths = [f for f in (files or []) if f]
        if not paths:
            return None, {}

        analyses = {f: analyze_video_filename(Path(f).name) for f in paths}

        date_priority = config.get('priorities.date_priority', 'oldest')
        want_oldest = str(date_priority).strip().lower() != 'newest'

        dates: Dict[str, Optional[datetime]] = {}
        sources: Dict[str, str] = {}
        for f in paths:
            try:
                value, source = get_video_date(f, date_priority)
            except Exception:                          # pragma: no cover
                value, source = None, 'none'
            dates[f], sources[f] = value, source

        # Reused from the image engine: the same group-normalised 0-10 scales
        # and the same no-decision gates, so a video group is judged with the
        # project's thresholds instead of newly invented ones.
        date_scores = compute_date_scores(dates, want_oldest, sources)
        sizes = {f: _file_size(f) for f in paths}
        size_scores = ratio_scores(sizes)
        name_scores = ratio_scores({f: float(analyses[f]['importance']) for f in paths})
        weights = video_criterion_weights()

        totals = {
            f: (name_scores[f] * weights['filename']
                + date_scores[f] * weights['date']
                + size_scores[f] * weights['size'])
            for f in paths
        }
        mtimes = {f: _file_mtime(f) for f in paths}

        # DETERMINISTIC: provenance class first (a copy-suffixed or recovered
        # name never beats a clean one, whatever the dates say), then the
        # weighted total, then the modification time, then the path -- the last
        # tie-break guarantees two runs over one folder pick the same file.
        ranked = sorted(paths, key=lambda f: (-analyses[f]['provenance'], -totals[f],
                                              mtimes[f], str(f)))
        kept = ranked[0]

        decisions: Dict[str, Any] = {}
        for f in paths:
            decisions[f] = {
                'path': f,
                'name': Path(f).name,
                'provenance': analyses[f]['provenance'],
                'provenance_label': analyses[f]['provenance_label'],
                'importance': analyses[f]['importance'],
                'copy_suffix': analyses[f]['copy_suffix'],
                'date': dates[f],
                'date_source': sources[f],
                'size_bytes': sizes[f],
                'mtime': mtimes[f],
                'scores': {'filename': name_scores[f], 'date': date_scores[f],
                           'size': size_scores[f]},
                'weights': weights,
                'total': totals[f],
                'is_kept': f == kept,
                'reasons': list(analyses[f]['reasons']),
            }

        # Comparative reasons: what actually decided it, and by how much.
        for f in paths:
            if f == kept:
                continue
            decisions[f]['reasons'].append(
                _text('video_reasons.lost_to', 'kept "{}" instead',
                      'تم الإبقاء على "{}" بدلًا منه', Path(kept).name))
            decisions[f]['reasons'].append(self._describe_margin(kept, f, decisions))

        if len(ranked) > 1:
            runner_up = ranked[1]
            decisions[kept]['reasons'].append(
                self._describe_margin(kept, runner_up, decisions))
            # The date comparison is only meaningful between files of the SAME
            # provenance class: when a copy-suffixed or recovered name already
            # lost on provenance, comparing its date would be noise the user
            # reads as a real argument. Same class -> the date really competed.
            same_class = analyses[kept]['provenance'] == analyses[runner_up]['provenance']
            if same_class and dates[kept] and dates[runner_up] \
                    and dates[kept] != dates[runner_up]:
                if dates[kept] < dates[runner_up]:
                    decisions[kept]['reasons'].append(
                        _text('video_reasons.older_date',
                              'older valid date than the competing duplicate(s)',
                              'تاريخ صالح أقدم من النسخ المتنافسة'))
                else:
                    decisions[kept]['reasons'].append(
                        _text('video_reasons.newer_date',
                              'newer valid date than the competing duplicate(s)',
                              'تاريخ صالح أحدث من النسخ المتنافسة'))

        return kept, decisions

    # ------------------------------------------------------------------
    @staticmethod
    def _criteria_by_weight(weights: Dict[str, float]) -> List[str]:
        """Criterion names, strongest weight first (the user's own order)."""
        return sorted(weights, key=lambda criterion: -weights[criterion])

    def _describe_margin(self, kept: str, other: str,
                         decisions: Dict[str, Any]) -> str:
        """Name the criterion that actually decided kept over other.

        Only a difference the engine really scored can be claimed: either the
        provenance classes differ, or a weighted contribution is more than 0.05
        apart. Anything smaller is reported as the tie it is, so a reason can
        never invent "older date" for a one-second gap.
        """
        kept_row, other_row = decisions[kept], decisions[other]

        if kept_row['provenance'] != other_row['provenance']:
            return _text('video_reasons.decided_by_provenance',
                         'decided by name provenance: {} beats {}',
                         'حُسم بأصالة الاسم: {} يتفوق على {}',
                         kept_row['provenance_label'], other_row['provenance_label'])

        weights = kept_row['weights']
        for criterion in self._criteria_by_weight(weights):
            gain = ((kept_row['scores'][criterion] - other_row['scores'][criterion])
                    * weights[criterion])
            if gain <= 0.05:
                continue
            if criterion == 'date':
                date_priority = config.get('priorities.date_priority', 'oldest')
                newest = str(date_priority).strip().lower() == 'newest'
                label = 'newer' if newest else 'older'
                return _text('video_reasons.decided_by_date',
                             'decided by the {} date: {} vs {}',
                             'حُسم بالتاريخ {}: {} مقابل {}',
                             label, _format_date(kept_row['date']),
                             _format_date(other_row['date']))
            if criterion == 'filename':
                return _text('video_reasons.decided_by_filename',
                             'decided by filename importance: {} vs {}',
                             'حُسم بأهمية اسم الملف: {} مقابل {}',
                             kept_row['importance'], other_row['importance'])
            return _text('video_reasons.decided_by_size',
                         'decided by file size: {} vs {}',
                         'حُسم بحجم الملف: {} مقابل {}',
                         kept_row['size_bytes'], other_row['size_bytes'])

        return _text('video_reasons.decided_by_tiebreak',
                     'every criterion tied - decided by modification time, then path',
                     'كل المعايير متعادلة - حُسم بوقت التعديل ثم المسار')


def _format_date(value: Optional[datetime]) -> str:
    """Render a decision date inside a reason line ('n/a' when there is none)."""
    if not value:
        return 'n/a'
    try:
        return value.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):               # pragma: no cover
        return str(value)
