"""
Exact video duplicate detection (Round 11).
كشف الفيديوهات المتطابقة تمامًا (بايت ببايت).

Scope -- and what is deliberately OUT of scope
----------------------------------------------
IN:  same extension + same byte size + same FULL-FILE SHA-256.
OUT: content similarity of any kind. A re-encode (H.264 -> H.265), another
     resolution or bitrate, a remux (MP4 -> MKV), another audio/subtitle track,
     a trim, a crop or a watermark are NOT duplicates here, and no decoder is
     installed to look for them (no ffmpeg/ffprobe/OpenCV/PyAV/moviepy).

Why a subclass of DuplicateDetector instead of a copy or a merge
----------------------------------------------------------------
The parent already owns the two things this flow must NOT reinvent: the
full-file SHA-256 worker and the shared deletion plumbing (_collect_group_info,
_move_files_to_bin, _print_deletion_footer -- documented there as shared by the
image and non-image flows). Inheriting reuses them verbatim, so videos land in
the same recycle-bin mechanism, honour the same dry-run/protected-file rules and
print the same footer as every other section.

What is added here is video-only and lives nowhere else:

  * a SAMPLE PRE-FILTER, because a video is 1000x an office file. It reads at
    most 2 MiB per candidate (first MiB + last MiB). Byte-identical files always
    share a sample, so a mismatch PROVES two files differ and drops them; a
    match proves nothing at all. A sample is therefore allowed to REMOVE
    candidates and is never allowed to decide one -- the verdict is always the
    full-file SHA-256 of stage 3, and no file is ever moved on a sample.
  * a cap on concurrent full-file hashes, so 16 threads do not thrash a disk
    with 16 simultaneous multi-GB reads.

The parent's find_duplicate_files() is NOT touched: office/archives/other keep
their exact behaviour, thresholds and reports.
"""

import hashlib
import logging
from concurrent.futures import as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.progress import (Progress, SpinnerColumn, TextColumn, BarColumn,
                           TimeElapsedColumn)

from ..file_categories import collect_files
from ..i18n.i18n import i18n
from ..video_file_selector import VideoFileSelector
from ...utils.helpers.file_utils import (handle_protected_files_with_user_choice,
                                         reset_session_folder)
from ...utils.helpers.progress_ui import track
from ...utils.reports.video_duplicate_report_generator import VideoDuplicateReportGenerator
from .duplicate_detector import (DuplicateDetector, GENERIC_CHUNK_SIZE,
                                 _calculate_file_hash_worker)

# Sample pre-filter: 1 MiB from the start + 1 MiB from the end of each file.
# 2 MiB of a 4 GB video is 0.05% of it, which is the whole point of the stage.
VIDEO_SAMPLE_BYTES = 1024 * 1024

# Full-file hashing is I/O bound on multi-GB files: reading 16 of them at once
# thrashes a spinning disk and buys nothing, so the scan-mode worker count is
# capped here. hashlib releases the GIL on large buffers, so 4 threads still
# overlap reading and hashing.
VIDEO_MAX_HASH_WORKERS = 4

# ---------------------------------------------------------------------------
# ⚠️  WARNING / إنذار — READ BEFORE CHANGING THIS CONSTANT
#
# The stage-2 sample pre-filter is hard-coded to 4 threads. This is a
# DELIBERATE, TEMPORARY compromise, not a tuned value.
#
# WHY 4 AND NOT THE SCAN-MODE COUNT: stage 2 issues TWO seeks per file
# (first MiB + last MiB). On a spinning USB HDD every seek costs ~12 ms, so
# running the scan-mode count (up to 16 in Ultra) would thrash the read head
# across 16 unrelated file positions and finish SLOWER than fewer threads.
# 4 was chosen as a safe middle ground for the machine this was tested on.
#
# WHY THIS IS NOT FUTURE-PROOF: the project is meant to serve every class of
# user, not one machine. 4 fixed threads is:
#   * too few  on a modern NVMe drive, where 16+ concurrent 2 MiB reads are
#              cheap and would cut this stage several-fold
#     (measured on this project's own data: ~11 600 candidates x 2 MiB = ~23 GiB
#      -- minutes of pure I/O that a fast drive could absorb far quicker),
#   * possibly still too many on a very slow or heavily fragmented drive.
#
# WHAT SHOULD REPLACE IT (tracked work, not done yet):
#   1. detect the underlying medium -- rotational (HDD) vs solid-state (SSD/NVMe)
#      and removable vs fixed -- instead of assuming one number;
#   2. derive the worker count from that, the way the scan modes already derive
#      theirs from CPU count and RAM (scan_modes.py);
#   3. let the scan mode (Normal/Medium/Advanced/Ultra) actually influence this
#      stage too, since today it is ignored here on purpose.
#
# Until (1)-(3) exist, this constant is the ONLY place stage-2 parallelism is
# set, and changing it silently changes video-scan speed on every machine.
# ---------------------------------------------------------------------------
VIDEO_MAX_SAMPLE_WORKERS = 4


def calculate_sample_hash(file_path: str,
                          sample_bytes: int = VIDEO_SAMPLE_BYTES) -> Optional[str]:
    """SHA-256 of the FIRST and LAST `sample_bytes` of a file -- never a verdict.

    Byte-identical files always produce the same sample, so a DIFFERENT sample
    proves the files differ and the candidate can be dropped without reading the
    rest. The converse is not true (a sample match says nothing), which is why
    the caller must still hash the whole file before calling anything a
    duplicate. The size is folded into the digest so a sample can never travel
    between files of different lengths.

    Returns None when the file cannot be stat'ed or read; the caller drops such
    a file from the candidate set and never deletes it.
    """
    try:
        size = Path(file_path).stat().st_size
    except OSError:
        logging.debug('Sample skipped, size unreadable: %s', file_path)
        return None

    try:
        digest = hashlib.sha256()
        digest.update(size.to_bytes(8, 'big'))
        with open(file_path, 'rb') as handle:
            head = handle.read(sample_bytes)
            digest.update(head)
            # Only seek when the tail does not overlap the head: below twice the
            # sample the head already covers at least half of the file.
            if size > 2 * sample_bytes:
                handle.seek(size - sample_bytes)
                digest.update(handle.read(sample_bytes))
        return digest.hexdigest()
    except OSError as exc:
        # Permission denied, a vanished file, a broken symlink, a network drop:
        # the file simply leaves the candidate set. It is never deleted, because
        # only a completed full-file hash can put a file into a group.
        logging.debug('Sample hash failed for %s: %s', file_path, exc)
        return None


def _human_bytes(num_bytes: float) -> str:
    """Compact human size for the console ("2.0 MiB", "1.4 GiB")."""
    value = float(num_bytes or 0)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"                    # pragma: no cover


class VideoDuplicateDetector(DuplicateDetector):
    """Exact (byte-identical) video duplicates, matched per extension."""

    def __init__(self):
        super().__init__()
        # Selection and reporting are video-specific; deletion is inherited.
        self.video_selector = VideoFileSelector()
        self.video_report_generator = VideoDuplicateReportGenerator(
            self.report_generator.reports_dir)

    # ------------------------------------------------------------------
    def find_duplicate_videos(self, folders: List[str], console: Console,
                              extensions, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find byte-identical videos: same extension + same size + same SHA-256.

        Three stages, because videos are the biggest files this program reads:

          1) SIZE PRE-FILTER -- stat() only, nothing is read. A file whose
             (extension, size) is unique cannot have a byte-identical twin.
          2) SAMPLE PRE-FILTER -- at most 2 MiB per surviving candidate. A
             sample mismatch proves the files differ; a match proves nothing.
          3) FULL-FILE SHA-256 -- the ONLY verdict, keyed (extension, sha256),
             so an .mp4 is never grouped with a .mov, even inside "all types".

        Returns the same result shape as find_duplicate_files() (so the CLI
        safety gate and the report plumbing work unchanged) plus 'sample_stats'
        for transparency. None when no video file was found at all -- a scan
        that never happened is never reported as "no duplicates found".
        """
        console.print(f"[blue]{i18n.get('common.scanning')}[/blue]")

        all_files = collect_files(folders, extensions, console)
        console.print(f"[green]{i18n.get(spec['found_key']).format(len(all_files))}[/green]")
        console.print(f"[dim]{i18n.get('common.video_exact_only')}[/dim]")

        if not all_files:
            return None

        # ---- Stage 1: size pre-filter (stat only) ------------------------
        sizes: Dict[str, int] = {}
        size_groups: Dict[Any, List[str]] = {}
        for file_path in all_files:
            try:
                size = Path(file_path).stat().st_size
            except OSError:
                # Unreadable now -> not a candidate. Such a file can never be
                # deleted: only a completed full hash puts a file in a group.
                logging.debug('Size unreadable, skipped: %s', file_path)
                continue
            sizes[file_path] = size
            key = (Path(file_path).suffix.lower(), size)
            size_groups.setdefault(key, []).append(file_path)

        size_candidates = [paths for paths in size_groups.values() if len(paths) > 1]
        total_size_candidates = sum(len(paths) for paths in size_candidates)
        unique_sizes = len(all_files) - total_size_candidates
        console.print(f"[dim]{i18n.get('common.size_prefilter').format(total_size_candidates, len(all_files), unique_sizes)}[/dim]")

        if total_size_candidates == 0:
            console.print(f"[red]{i18n.get('common.duplicates_found_generic').format(0)}[/red]")
            return {
                'duplicates': {},
                'total_scanned': len(all_files),
                'total_duplicates': 0,
                'operation': 'duplicates',
                'sample_stats': None,
            }

        # ---- Stage 2: sample pre-filter (<= 2 MiB per candidate) ---------
        #
        # WHY THIS IS PARALLEL AND VISIBLE (Round 17): this stage used to be a
        # plain single-threaded `for` loop with no progress bar at all. On a
        # real library that meant ~11 600 candidates x 2 MiB = ~23 GiB read in
        # total silence -- ten minutes in which the console showed nothing and
        # the process looked frozen (CPU ~0%, RAM flat, because it is pure
        # disk I/O on one thread). The heavy stage 3 right below already had a
        # bar and threads; the lighter-looking stage 2 had neither, and it was
        # the single largest window of silence in the whole program.
        #
        # Two invariants are preserved exactly:
        #   1. A sample can only rule files OUT. It never decides a duplicate
        #      and no file is ever moved on it -- the verdict stays the
        #      full-file SHA-256 of stage 3.
        #   2. GROUPING ORDER IS DETERMINISTIC. Results are collected first and
        #      then grouped by iterating the candidates in their original scan
        #      order, never in `as_completed` order. Building the dict inside
        #      the completion loop would make the report's group numbering
        #      depend on which thread won the race, so two runs over the same
        #      folder could number the same groups differently.
        sample_flat = [candidate for paths in size_candidates for candidate in paths]
        sample_of: Dict[str, str] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:

            task = progress.add_task(i18n.get('common.sampling'),
                                     total=len(sample_flat))
            # Deliberately NOT the scan-mode count: see the WARNING on
            # VIDEO_MAX_SAMPLE_WORKERS. Two seeks per file on a spinning disk
            # makes more threads slower, not faster.
            sample_workers = max(1, min(self._get_max_workers(),
                                        VIDEO_MAX_SAMPLE_WORKERS))
            executor_class = self._get_executor_type()

            try:
                with executor_class(max_workers=sample_workers) as executor:
                    future_to_file = {
                        executor.submit(calculate_sample_hash, candidate,
                                        VIDEO_SAMPLE_BYTES): candidate
                        for candidate in sample_flat
                    }

                    for future in as_completed(future_to_file):
                        candidate = future_to_file[future]
                        try:
                            sample = future.result()
                            if sample:
                                sample_of[candidate] = sample
                        except Exception as exc:
                            # Never a silent pass: a file whose sample cannot be
                            # read simply never joins a sample group, so it can
                            # never be deleted either -- the safe direction.
                            logging.debug('Video sample failed for %s: %s',
                                          candidate, exc)
                        finally:
                            progress.advance(task)
            except Exception as exc:
                # Same conservative fallback as stage 3: if the pool itself
                # cannot be used, fall back to reading sequentially rather than
                # abandoning the scan.
                logging.debug('Video sample pool failed, falling back: %s', exc)
                for candidate in sample_flat:
                    sample = calculate_sample_hash(candidate, VIDEO_SAMPLE_BYTES)
                    if sample:
                        sample_of[candidate] = sample

        # Group in the ORIGINAL scan order so the result is byte-for-byte the
        # same as the sequential loop this replaced.
        sample_groups: Dict[Any, List[str]] = {}
        sampled_bytes = 0
        for candidate in sample_flat:
            sample = sample_of.get(candidate)
            if not sample:
                continue
            size = sizes.get(candidate, 0)
            sampled_bytes += min(size, 2 * VIDEO_SAMPLE_BYTES)
            key = (Path(candidate).suffix.lower(), size, sample)
            sample_groups.setdefault(key, []).append(candidate)

        sample_candidates = [paths for paths in sample_groups.values() if len(paths) > 1]
        total_sample_candidates = sum(len(paths) for paths in sample_candidates)
        # What the samples cost, against what hashing EVERY same-size candidate
        # would have cost. Both numbers are real bytes of this run, so the
        # console line can never claim a saving that did not happen.
        naive_full_bytes = sum(sizes.get(path, 0)
                               for paths in size_candidates for path in paths)
        full_hash_bytes = sum(sizes.get(path, 0)
                              for paths in sample_candidates for path in paths)
        console.print(f"[dim]{i18n.get('common.sample_prefilter').format(_human_bytes(VIDEO_SAMPLE_BYTES), total_sample_candidates, total_size_candidates, _human_bytes(sampled_bytes), _human_bytes(naive_full_bytes))}[/dim]")

        sample_stats = {
            'sample_bytes': VIDEO_SAMPLE_BYTES,
            'sampled_bytes': sampled_bytes,
            'size_candidates': total_size_candidates,
            'sample_candidates': total_sample_candidates,
            'naive_full_bytes': naive_full_bytes,
            'full_hash_bytes': full_hash_bytes,
        }

        if total_sample_candidates == 0:
            console.print(f"[red]{i18n.get('common.duplicates_found_generic').format(0)}[/red]")
            return {
                'duplicates': {},
                'total_scanned': len(all_files),
                'total_duplicates': 0,
                'operation': 'duplicates',
                'sample_stats': sample_stats,
            }

        # ---- Stage 3: FULL-FILE SHA-256 -- the ONLY verdict --------------
        hash_to_files: Dict[Any, List[str]] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console
        ) as progress:

            task = progress.add_task(i18n.get('common.searching'),
                                     total=total_sample_candidates)
            # The scan mode can ask for 16 workers; 16 concurrent multi-GB reads
            # thrash a disk instead of speeding it up, so the count is capped.
            max_workers = max(1, min(self._get_max_workers(), VIDEO_MAX_HASH_WORKERS))
            executor_class = self._get_executor_type()

            try:
                with executor_class(max_workers=max_workers) as executor:
                    future_to_file = {
                        executor.submit(_calculate_file_hash_worker, candidate,
                                        GENERIC_CHUNK_SIZE): candidate
                        for paths in sample_candidates
                        for candidate in paths
                    }

                    for future in as_completed(future_to_file):
                        candidate = future_to_file[future]
                        try:
                            result_path, file_hash = future.result()
                            self._store_hash(hash_to_files, result_path, file_hash)
                        except Exception as exc:
                            # Never a silent pass: a file that cannot be hashed
                            # is tellingly absent from the duplicate map, and it
                            # can never be deleted either.
                            logging.debug('Video hash failed for %s: %s', candidate, exc)
                        progress.advance(task)
            except Exception as exc:
                console.print(f"[yellow]⚠️ Falling back to single-threaded processing: {exc}[/yellow]")
                for paths in sample_candidates:
                    for candidate in paths:
                        try:
                            result_path, file_hash = _calculate_file_hash_worker(
                                candidate, GENERIC_CHUNK_SIZE)
                            self._store_hash(hash_to_files, result_path, file_hash)
                        except Exception as inner:
                            logging.debug('Video hash failed for %s: %s', candidate, inner)
                        progress.advance(task)

        duplicates = {key: files for key, files in hash_to_files.items() if len(files) > 1}
        total_duplicates = sum(len(files) - 1 for files in duplicates.values())
        console.print(f"[red]{i18n.get('common.duplicates_found_generic').format(total_duplicates)}[/red]")

        return {
            'duplicates': duplicates,
            'total_scanned': len(all_files),
            'total_duplicates': total_duplicates,
            'operation': 'duplicates',
            'sample_stats': sample_stats,
        }

    # ------------------------------------------------------------------
    def delete_duplicate_videos(self, result: Dict[str, Any], console: Console,
                                spec: Dict[str, Any], option_id: str = 'all'):
        """Move every non-surviving copy of each group into the video recycle bin.

        The same flow as delete_duplicate_files() -- protected-file handling,
        information collected BEFORE the moves, the shared move helper and the
        shared footer -- with three video differences:

          * the survivor is chosen by VideoFileSelector, which explains itself;
          * removed files land in duplicates-video, never mixed with an office
            or archive copy, so the section stays independently recoverable;
          * the report is the video one, so it carries the extension, the
          * SHA-256, the shared size and every selection reason.

        Detection stays separate from deletion: this method only ever acts on a
        result that find_duplicate_videos() already produced.
        """
        duplicates = (result or {}).get('duplicates')
        if not duplicates:
            return

        reset_session_folder()
        subfolder = spec.get('recycle_subfolder', 'duplicates-video')

        # Round 14: the video selector explains every decision, which means
        # opening metadata for every candidate of every group. That used to run
        # with no output at all; the choice itself is unchanged, only counted.
        files_to_delete: List[str] = []
        selections: Dict[Any, Dict[str, Any]] = {}
        with track(console, i18n.get('common.selecting_best'),
                   len(duplicates)) as (select_progress, select_task):
            for key, files in duplicates.items():
                if len(files) >= 2:
                    kept, decisions = self.video_selector.select_best_file(files)
                    if kept:
                        selections[key] = {'kept': kept, 'decisions': decisions}
                        files_to_delete.extend(path for path in files if path != kept)
                select_progress.advance(select_task)

        console.print(f"[yellow]{i18n.get('common.checking_permissions')}[/yellow]")
        files_to_delete, protected_count, force_deleted_count = \
            handle_protected_files_with_user_choice(files_to_delete, console,
                                                    subfolder=subfolder)

        all_files_info = self._collect_group_info(
            duplicates, self.report_generator.get_detailed_file_info, console)

        deleted_files, moved_map = self._move_files_to_bin(files_to_delete, console,
                                                           subfolder)

        self._print_deletion_footer(console, deleted_files, protected_count,
                                    force_deleted_count, subfolder)

        try:
            # Round 14: report writing is the second silent window of a big run.
            with console.status(i18n.get('common.report_writing')):
                report_path = self.video_report_generator.generate_video_duplicates_report(
                    duplicates, deleted_files, all_files_info, moved_map, spec,
                    option_id, selections)
            console.print(f"[green]{i18n.get('common.report_saved').format(report_path)}[/green]")
        except Exception as report_error:
            # Round 13: never let a report failure mask the completed operation.
            logging.warning('Video report could not be saved after a completed operation: %s',
                            report_error)
            console.print(
                f"[yellow]{i18n.get('common.report_failed').format(report_error)}[/yellow]")
        console.print(f"[green]{i18n.get('common.completed')}[/green]")
