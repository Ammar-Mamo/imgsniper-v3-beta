"""
File selection logic for choosing the best file from a group
"""

import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image

from .config import config, DEFAULT_PRIORITY_ORDER
from ..utils.helpers.date_extractor import date_extractor


def compute_size_score(size_mb: float) -> float:
    """Public 0-10 size score -- the SAME scale FileSelector scores with.

    Reports need it to tell a DECISIVE size difference from a score-neutral
    one: at/above the 5 MB cap every file scores exactly 10.0, so a raw
    byte gap there (7.76 vs 7.77 MB) never decided anything and must not be
    reported as the deletion reason (audit round 5, issue #7).
    """
    return min(10.0, max(0.1, size_mb / 0.5))


def compute_resolution_score(pixels: int) -> float:
    """Public 0-10 resolution score -- the SAME scale FileSelector scores with.

    Mirrors the 10 MP cap: differences above it are score-neutral.
    """
    return min(10.0, max(0.1, pixels / 1_000_000))


class FileSelector:
    """Handles selection of the best file from a group based on various criteria."""

    # When a group spans an extreme resolution range, resolution receives extra
    # weight so a tiny thumbnail cannot win on date/filename alone. This is a
    # WEIGHTED influence that is deliberately capped -- dimensions are taken
    # into account but never given absolute preference.
    QUALITY_FLOOR_RATIO = 2.0        # only kick in above a 2x pixel spread
    QUALITY_FLOOR_MAX_BOOST = 3.0    # hard cap: date/filename still matter

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

        Instead of short-circuiting on the first priority (which causes
        high-resolution images to be deleted in favor of "original" filenames),
        this method computes a weighted quality score across ALL criteria.
        """
        if len(files) == 1:
            return files[0]

        priority_order = config.get('priorities.order', list(DEFAULT_PRIORITY_ORDER))

        # Defensive fallback (audit P0-3): the CLI validates ranks, but the
        # engine must not trust its callers -- a corrupt settings.json with
        # duplicate ranks would otherwise silently invert the user's intent.
        if not self._is_valid_rank_permutation(priority_order):
            priority_order = list(DEFAULT_PRIORITY_ORDER)

        priorities = ['resolution', 'size', 'date', 'filename']

        priority_mapping = list(zip(priorities, priority_order))
        sorted_priorities = sorted(priority_mapping, key=lambda x: x[1])

        # Date is RELATIVE: "oldest"/"newest" only means something compared to
        # the other members of the group, so it must be normalized per-group
        # rather than per-file.
        date_scores = self._compute_group_date_scores(files)

        # Quality floor: give resolution extra (capped) weight when the group
        # spans an extreme pixel range.
        resolution_boost = self._compute_resolution_boost(files)

        # Compute weighted quality score for each file
        file_scores = {}
        for file_path in files:
            weighted_score = self._compute_weighted_quality_score(
                file_path, sorted_priorities, date_scores, resolution_boost
            )
            file_scores[file_path] = weighted_score

        # Return the file with the highest weighted score.
        # On a tie, the first file wins (stable behavior) — we use min() with
        # a negated score so that higher scores win, and files.index breaks
        # ties in favor of the earliest file in the group.
        best_file = min(file_scores.keys(),
                        key=lambda f: (-file_scores[f], files.index(f)))
        return best_file

    def _compute_group_date_scores(self, files: List[str]) -> dict:
        """Normalize capture dates across the group onto a 0-10 scale.

        Dates come from `date_extractor.get_best_date()`, which already merges
        BOTH sources -- EXIF and the filename -- because many images carry a
        date only in the filename (WhatsApp/social downloads strip EXIF) while
        others have EXIF but a meaningless filename.

        Honours `priorities.date_priority`: 'oldest' rewards the earliest
        capture date, 'newest' the latest.
        """
        date_priority = config.get('priorities.date_priority', 'oldest')
        want_oldest = str(date_priority).strip().lower() != 'newest'

        dates = {}
        for f in files:
            try:
                d, _source = date_extractor.get_best_date(f, str(date_priority))
            except Exception:
                d = None
            dates[f] = d

        known = [d for d in dates.values() if d is not None]
        if not known:
            # No dates anywhere in the group -> the criterion is neutral and
            # must not influence the outcome.
            return {f: 5.0 for f in files}

        lo, hi = min(known), max(known)
        span = (hi - lo).total_seconds()

        scores = {}
        for f, d in dates.items():
            if d is None:
                # Unknown date scores below any known date: a file whose capture
                # time is provable is a more credible "original".
                scores[f] = 3.0
            elif span <= 0:
                scores[f] = 10.0          # every known date is identical
            else:
                ratio = (d - lo).total_seconds() / span   # 0.0 = oldest, 1.0 = newest
                scores[f] = 10.0 * (1.0 - ratio) if want_oldest else 10.0 * ratio
        return scores


    def _group_pixel_counts(self, files: List[str]) -> List[int]:
        """Readable pixel counts for the group (unreadable files are skipped)."""
        pixels = []
        for f in files:
            try:
                with Image.open(f) as img:
                    pixels.append(img.width * img.height)
            except Exception as e:
                # Audit P2-20: was a silent "pass". An unreadable file drops out
                # of the pixel list, which weakens the quality-floor guard (it
                # compares the kept image against the group's best resolution)
                # with no indication that input data was missing.
                logging.debug('Pixel count unreadable for %s: %s', f, e)
        return pixels

    def _compute_resolution_boost(self, files: List[str]) -> float:
        """Extra multiplier for the resolution criterion on extreme spreads.

        Grows logarithmically with the max/min pixel ratio and is capped, so a
        900x gap (3000x3000 vs 100x100) gets meaningful protection without
        letting resolution dictate the outcome outright.
        """
        pixels = self._group_pixel_counts(files)
        if len(pixels) < 2:
            return 1.0
        lo, hi = min(pixels), max(pixels)
        if lo <= 0:
            return 1.0
        ratio = hi / lo
        if ratio <= self.QUALITY_FLOOR_RATIO:
            return 1.0
        return min(self.QUALITY_FLOOR_MAX_BOOST, 1.0 + math.log2(ratio) * 0.5)

    def detect_resolution_sacrifice(self, kept_file: str,
                                    group_files: List[str]) -> Optional[Tuple[int, int]]:
        """Detect that a HIGHER-resolution sibling was discarded for `kept_file`.

        Returns (kept_pixels, best_discarded_pixels) when the kept file is not
        the highest-resolution member of its group, otherwise None. This drives
        the explicit report warning, so a silent quality downgrade can never
        pass unnoticed.
        """
        try:
            with Image.open(kept_file) as img:
                kept_px = img.width * img.height
        except Exception:
            return None

        best_px = 0
        for f in group_files or []:
            if f == kept_file:
                continue
            try:
                with Image.open(f) as img:
                    best_px = max(best_px, img.width * img.height)
            except Exception as e:
                # Audit P2-20: was a silent "pass". This feeds the
                # resolution-sacrifice warning, so an unreadable candidate can
                # silently suppress a warning that should have been shown.
                logging.debug('Pixel count unreadable for %s: %s', f, e)

        return (kept_px, best_px) if best_px > kept_px else None

    def _compute_weighted_quality_score(self, file_path: str,
                                         sorted_priorities: List[tuple],
                                         date_scores: dict = None,
                                         resolution_boost: float = 1.0) -> float:
        """
        Compute a weighted quality score for a file.
        Each criterion contributes a normalized quality score (0-10),
        multiplied by its priority weight.

        `date_scores` carries the per-group normalized date scores computed by
        `_compute_group_date_scores`; date is relative and cannot be scored for
        a single file in isolation.
        """
        total_score = 0.0
        date_scores = date_scores or {}

        for priority_type, rank in sorted_priorities:
            # rank 1 = weight 4 (highest), rank 4 = weight 1 (lowest)
            weight = 5 - rank

            # NOTE: `date_priority` holds a STRING ('oldest'/'newest'), not a
            # bool, so it is handled separately -- the generic truthiness test
            # below would always pass for it (audit: accidental truthiness bug).
            if priority_type == 'date':
                date_priority = config.get('priorities.date_priority', 'oldest')
                if not date_priority or not isinstance(date_priority, str):
                    continue          # criterion explicitly disabled
                criterion_score = float(date_scores.get(file_path, 5.0))
                total_score += criterion_score * weight
                continue

            if not config.get(f'priorities.{priority_type}_priority', True):
                continue

            if priority_type == 'resolution':
                criterion_score = self._get_resolution_quality_score(file_path)
                # Quality-floor guard: amplified only on extreme spreads.
                total_score += criterion_score * weight * max(1.0, resolution_boost)
                continue
            elif priority_type == 'size':
                criterion_score = self._get_size_quality_score(file_path)
            elif priority_type == 'filename':
                criterion_score = self._get_filename_quality_score(file_path)
            else:
                continue

            total_score += criterion_score * weight

        return total_score

    def _get_resolution_quality_score(self, file_path: str) -> float:
        """
        Normalize resolution to 0-10 scale.
        Reference: 10MP (4000×2500 ≈ 10,000,000 pixels) = 10.0
        Minimum: 0.1 (for extremely small images like 10×10)
        """
        try:
            with Image.open(file_path) as img:
                pixels = img.width * img.height
                # Scale: 10MP = 10.0, 1MP = 1.0, 100×100 = 0.1
                return compute_resolution_score(pixels)
        except Exception:
            return 0.5  # Unknown resolution gets mid-low score

    def _get_size_quality_score(self, file_path: str) -> float:
        """
        Normalize file size to 0-10 scale.
        Reference: 5MB = 10.0
        Minimum: 0.1 (for very small files)
        """
        try:
            size_bytes = Path(file_path).stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            # 0.5MB = 1.0, 5MB = 10.0 (capped) -- shared with the reports
            return compute_size_score(size_mb)
        except Exception:
            return 0.5

    def _get_filename_quality_score(self, file_path: str) -> float:
        """
        Map filename importance score to 0-10 quality scale.
        The filename_importance score (1-11) maps directly.
        """
        score = date_extractor.get_filename_importance_score(
            Path(file_path).name
        )
        return float(score)
