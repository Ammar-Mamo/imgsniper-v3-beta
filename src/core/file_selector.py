"""
File selection logic for choosing the best file from a group
"""

import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple

from .config import config, DEFAULT_PRIORITY_ORDER
from ..utils.helpers.date_extractor import date_extractor
from ..utils.helpers.image_codec import read_dimensions


def compute_size_score(size_mb: float) -> float:
    """Legacy capped 0-10 size score (kept for the round-5 report guards).

    Round 7 replaced this ABSOLUTE scale inside the selection engine with
    group-normalised scores (build_group_scoretable): 0.07 MB used to score
    0.14/10, which made real size differences invisible next to the raw 1-9
    filename scale.
    """
    return min(10.0, max(0.1, size_mb / 0.5))


def compute_resolution_score(pixels: int) -> float:
    """Legacy capped 0-10 resolution score (round-5 report guards only).

    Round 7 replaced this ABSOLUTE 10 MP-capped scale inside the selection
    engine: below the cap a 4x pixel difference collapsed to ~0.5 point,
    which is how a 360x449 file could beat a 720x897 one.
    """
    return min(10.0, max(0.1, pixels / 1_000_000))


# ---------------------------------------------------------------------------
# Round 7: comparable criterion scales (single source of truth)
# ---------------------------------------------------------------------------
# The old per-criterion scores were NOT comparable: filename importance lived
# on a raw 1-9 scale (swings of ~6 points) while size/resolution used absolute
# caps aimed at multi-MB / multi-MP files, so a 0.07 MB image scored 0.14/10
# and a 4x pixel difference only ~0.5 point. The weighted sum was therefore
# dominated by whichever criterion had the widest scale, no matter what rank
# the user gave it (#518/#526/#572: a 360x449 file was kept over 720x897).
#
# Every criterion is now normalised WITHIN the group onto one comparable 0-10
# scale, and a no-decision gate keeps noise out:
#   * resolution/size -> log-ratio scale (best = 10, worst = 0); a spread
#     below SCORE_GATE_RATIO is a tie (5.0 for everyone).
#   * filename        -> proportional (importance * 10/9); identical
#     importances are a tie (5.0).
#   * date            -> relative to the group as before, with a minimum-gap
#     gate so a one-second EXIF difference cannot decide anything.
# With every criterion spanning 0-10, the weights (4/3/2/1) finally express
# the user's priority order for real.
SCORE_GATE_RATIO = 1.05          # < 5% spread -> the criterion is a tie
DATE_GATE_SECONDS = 60.0         # < 1 minute apart -> the date is a tie
QUALITY_FLOOR_RATIO = 2.0        # resolution boost kicks in above 2x pixels
QUALITY_FLOOR_MAX_BOOST = 3.0    # hard cap: date/filename still matter


def gate_passes(hi, lo, min_ratio: float = SCORE_GATE_RATIO) -> bool:
    """True when the spread hi/lo is big enough to count as a real difference."""
    try:
        hi, lo = float(hi), float(lo)
    except (TypeError, ValueError):
        return False
    if hi <= 0 or lo <= 0:
        return hi != lo
    return (hi / lo) >= min_ratio


def ratio_scores(values: dict) -> dict:
    """Normalise positive values onto a comparable 0-10 LOG-ratio scale.

    Best value -> 10, worst -> 0; a spread below SCORE_GATE_RATIO is a tie
    (5.0 for everyone, so noise cannot decide). Missing/invalid values (0)
    score 0: a file whose metrics could not be read must never win a quality
    criterion by default.
    """
    valid = {}
    for key, value in values.items():
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            valid[key] = value
    if len(valid) < 2 or not gate_passes(max(valid.values()), min(valid.values())):
        return {key: 5.0 for key in values}
    lo = min(valid.values())
    denom = math.log(max(valid.values()) / lo)
    scores = {key: 0.0 for key in values}
    for key, value in valid.items():
        scores[key] = max(0.0, min(10.0, 10.0 * math.log(value / lo) / denom))
    return scores


def filename_scores(importances: dict) -> dict:
    """Normalise filename importance (1-9) proportionally onto 0-10.

    Proportional, NOT min-max: an 8-vs-7 gap is a minor difference and must
    stay minor; only a 9-vs-1 gap approaches a full swing. Identical
    importances are a tie (5.0).
    """
    scores = {}
    for key, value in importances.items():
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        scores[key] = max(0.0, min(10.0, value * 10.0 / 9.0))
    if scores and len(set(scores.values())) == 1:
        return {key: 5.0 for key in scores}
    return scores


def compute_date_scores(dates: dict, want_oldest: bool, sources: dict = None) -> dict:
    """Relative date scores for a group (shared by engine and reports).

    Unknown dates score 3.0 -- below any known date, because a provable
    capture time is a more credible "original".

    A difference only counts when it is meaningful for the PRECISION we have:
    gaps under DATE_GATE_SECONDS are ignored (a one-second EXIF difference
    must never decide), and when any date in the group comes from a FILENAME
    (day-level precision) gaps under a full day are ignored as well -- the
    midnight timestamp is an artifact of the file name, not a real capture
    time (rounds 5 #14/#239 fixed only the REPORT wording; the scoring itself
    still rewarded the artifact until round 7). Ties score 5.0 for everyone.
    """
    known = {k: d for k, d in dates.items() if d is not None}
    if not known:
        return {key: 5.0 for key in dates}
    if len(known) == 1:
        # Exactly one known date: it wins, unknowns get 3.0
        scores = {}
        for key, date in dates.items():
            if date is not None:
                scores[key] = 10.0
            else:
                scores[key] = 3.0
        return scores
    lo, hi = min(known.values()), max(known.values())
    span = (hi - lo).total_seconds()
    if span < DATE_GATE_SECONDS:
        return {key: 5.0 for key in dates}
    if sources and any(str(source).lower() == 'filename'
                       for source in sources.values()) and span < 86400:
        return {key: 5.0 for key in dates}
    scores = {}
    for key, date in dates.items():
        if date is None:
            scores[key] = 3.0
        else:
            ratio = (date - lo).total_seconds() / span
            scores[key] = 10.0 * (1.0 - ratio) if want_oldest else 10.0 * ratio
    return scores


def compute_resolution_boost_from_pixels(pixels) -> float:
    """Capped boost for the resolution criterion on extreme pixel spreads.

    Grows logarithmically with the max/min ratio and is capped, so resolution
    gets meaningful extra weight without ever becoming an outright veto.
    """
    values = [float(p) for p in pixels if p and p > 0]
    if len(values) < 2:
        return 1.0
    lo, hi = min(values), max(values)
    if lo <= 0:
        return 1.0
    ratio = hi / lo
    if ratio <= QUALITY_FLOOR_RATIO:
        return 1.0
    return min(QUALITY_FLOOR_MAX_BOOST, 1.0 + math.log2(ratio) * 0.5)


def build_group_scoretable(pixels: dict, size_bytes: dict, filename_importance: dict,
                           date_scores: dict, priority_order, resolution_boost: float = 1.0,
                           enabled: dict = None) -> dict:
    """Score every file of a group on ONE comparable 0-10 scale per criterion.

    Round 7: single source of truth for BOTH the selection engine and the
    reports -- deletion/selection reasons are computed from the exact table
    that picked the winner, so a report can never describe a decision the
    engine did not actually make.

    Returns {path: {'scores': {...}, 'weighted': {...}, 'total': float}}.
    """
    files = list(pixels.keys())
    resolution = ratio_scores({f: pixels.get(f, 0) for f in files})
    size = ratio_scores({f: size_bytes.get(f, 0) for f in files})
    filename = filename_scores({f: filename_importance.get(f, 0) for f in files})
    dates = {f: date_scores.get(f, 5.0) for f in files}

    priorities = ['resolution', 'size', 'date', 'filename']
    order = priority_order if (isinstance(priority_order, list)
                               and sorted(priority_order) == [1, 2, 3, 4]) \
        else list(DEFAULT_PRIORITY_ORDER)
    weights = {criterion: 5 - rank for criterion, rank in zip(priorities, order)}
    enabled = enabled or {}

    table = {}
    for file_path in files:
        scores = {
            'resolution': resolution[file_path],
            'size': size[file_path],
            'date': dates[file_path],
            'filename': filename[file_path],
        }
        weighted = {}
        total = 0.0
        for criterion in priorities:
            if enabled.get(criterion, True) is False:
                weighted[criterion] = 0.0
                continue
            contribution = scores[criterion] * weights[criterion]
            if criterion == 'resolution' and resolution_boost > 1.0:
                contribution *= resolution_boost
            weighted[criterion] = contribution
            total += contribution
        table[file_path] = {'scores': scores, 'weighted': weighted, 'total': total}
    return table


class FileSelector:
    """Handles selection of the best file from a group based on various criteria."""

    # When a group spans an extreme resolution range, resolution receives extra
    # weight so a tiny thumbnail cannot win on date/filename alone. This is a
    # WEIGHTED influence that is deliberately capped -- dimensions are taken
    # into account but never given absolute preference.
    # Single source of truth lives at module level (round 7); these aliases
    # keep existing callers/tests working.
    QUALITY_FLOOR_RATIO = QUALITY_FLOOR_RATIO
    QUALITY_FLOOR_MAX_BOOST = QUALITY_FLOOR_MAX_BOOST

    @staticmethod
    def _is_valid_rank_permutation(order) -> bool:
        """True only when `order` is a genuine permutation of the ranks 1..4.

        Duplicate ranks (e.g. [1,1,2,3]) used to be accepted silently; because
        Python's sort is stable they resolved to the positional default and
        produced the OPPOSITE of what the user intended (audit P0-3).
        """
        try:
            return sorted(int(x) for x in order) == [1, 2, 3, 4]
        except (TypeError, ValueError):
            return False

    def select_best_file(self, files: List[str]) -> str:
        """
        Select the best file from a group based on weighted quality scoring.

        Round 7: every criterion is normalised WITHIN the group onto one
        comparable 0-10 scale (build_group_scoretable) and a no-decision gate
        keeps noise-level differences from deciding, so the configured
        priority order genuinely governs the outcome. A criterion switched
        off in the priority settings contributes nothing.
        """
        if len(files) == 1:
            return files[0]

        priority_order = config.get('priorities.order', list(DEFAULT_PRIORITY_ORDER))

        # Defensive fallback (audit P0-3): the CLI validates ranks, but the
        # engine must not trust its callers -- a corrupt settings.json with
        # duplicate ranks would otherwise silently invert the user's intent.
        if not self._is_valid_rank_permutation(priority_order):
            priority_order = list(DEFAULT_PRIORITY_ORDER)

        pixels, size_bytes, importances = {}, {}, {}
        for file_path in files:
            dimensions = read_dimensions(file_path)
            pixels[file_path] = (dimensions[0] * dimensions[1]) if dimensions else 0
            try:
                size_bytes[file_path] = Path(file_path).stat().st_size
            except OSError:
                size_bytes[file_path] = 0
            try:
                importances[file_path] = date_extractor.get_filename_importance_score(
                    Path(file_path).name)
            except Exception:
                importances[file_path] = 0

        date_scores = self._compute_group_date_scores(files)
        resolution_boost = self._compute_resolution_boost(files)
        enabled = {criterion: bool(config.get(f'priorities.{criterion}_priority', True))
                   for criterion in ('resolution', 'size', 'date', 'filename')}

        table = build_group_scoretable(
            pixels, size_bytes, importances, date_scores,
            priority_order, resolution_boost, enabled)

        # Highest weighted total wins; a tie keeps the earliest file in scan
        # order (stable behaviour).
        return min(table.keys(), key=lambda f: (-table[f]['total'], files.index(f)))

    def _compute_group_date_scores(self, files: List[str]) -> dict:
        """Normalize capture dates across the group onto a 0-10 scale.

        Dates come from `date_extractor.get_best_date()`, which merges BOTH
        sources -- EXIF and the filename -- because many images carry a date
        only in the filename (WhatsApp/social downloads strip EXIF) while
        others have EXIF but a meaningless filename.

        Round 7: delegates to the shared compute_date_scores(), passing the
        DATE SOURCE along so precision is respected -- a filename date is
        day-level, and a sub-day gap involving one is an artifact, not a
        decision. Gaps under DATE_GATE_SECONDS are a tie for the same reason.
        """
        date_priority = config.get('priorities.date_priority', 'oldest')
        want_oldest = str(date_priority).strip().lower() != 'newest'

        dates = {}
        sources = {}
        for f in files:
            try:
                d, source = date_extractor.get_best_date(f, str(date_priority))
            except Exception:
                d, source = None, None
            dates[f] = d
            sources[f] = source

        return compute_date_scores(dates, want_oldest, sources)


    def _group_pixel_counts(self, files: List[str]) -> List[int]:
        """Readable pixel counts for the group (unreadable files are skipped)."""
        pixels = []
        for f in files:
            dimensions = read_dimensions(f)
            if dimensions is None:
                # Audit P2-20: was a silent "pass". An unreadable file drops out
                # of the pixel list, which weakens the quality-floor guard (it
                # compares the kept image against the group's best resolution)
                # with no indication that input data was missing. Round 6:
                # RAW/HEIC now decode through the central codec helper.
                logging.debug('Pixel count unreadable for %s', f)
                continue
            pixels.append(dimensions[0] * dimensions[1])
        return pixels

    def _compute_resolution_boost(self, files: List[str]) -> float:
        """Extra multiplier for the resolution criterion on extreme spreads.

        Round 7: delegates to compute_resolution_boost_from_pixels(); the
        boost stays capped so an older, lower-resolution original can still
        win on the other criteria.
        """
        return compute_resolution_boost_from_pixels(self._group_pixel_counts(files))

    def detect_resolution_sacrifice(self, kept_file: str,
                                    group_files: List[str]) -> Optional[Tuple[int, int]]:
        """Detect that a HIGHER-resolution sibling was discarded for `kept_file`.

        Returns (kept_pixels, best_discarded_pixels) when the kept file is not
        the highest-resolution member of its group, otherwise None. This drives
        the explicit report warning, so a silent quality downgrade can never
        pass unnoticed.
        """
        kept_dims = read_dimensions(kept_file)
        if kept_dims is None:
            return None
        kept_px = kept_dims[0] * kept_dims[1]

        best_px = 0
        for f in group_files or []:
            if f == kept_file:
                continue
            dims = read_dimensions(f)
            if dims is None:
                # Audit P2-20: was a silent "pass". This feeds the
                # resolution-sacrifice warning, so an unreadable candidate can
                # silently suppress a warning that should have been shown.
                logging.debug('Pixel count unreadable for %s', f)
                continue
            best_px = max(best_px, dims[0] * dims[1])

        return (kept_px, best_px) if best_px > kept_px else None

