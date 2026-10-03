"""
Report generation module

Round 13 -- two shared guarantees for EVERY report writer
---------------------------------------------------------
`unique_report_path()` is the single place where a report file name is turned
into a path, and it enforces both:

  * **the folder exists at write time.** It used to be created only once, in
    `ReportGenerator.__init__` at program start. A real 36528-file cleanup then
    ended in `❌ Error: [Errno 2] ... reports\duplicates_<ts>.txt` with NO
    report, because the `reports/` folder had been removed while the scan was
    running -- the files had already been moved, so the operation was complete
    and only its documentation was lost.

  * **no report ever overwrites another.** Every writer names its file
    `{prefix}_{timestamp}.txt` with a one-second resolution, so two operations
    inside the same second (a dry run followed by the real one, or an image
    scan and a section scan that share the `duplicates` prefix) silently
    replaced each other. `video_duplicate_report_generator` already guarded
    against this for videos only; the guard now belongs to all of them.
"""

from pathlib import Path


def unique_report_path(reports_dir: Path, filename: str) -> Path:
    """Return `reports_dir/filename`, creating the folder and never colliding.

    The folder is (re)created here, immediately before the caller opens the
    file, so a `reports/` folder that disappears mid-run cannot turn a
    completed operation into an error. If the name is already taken a numeric
    suffix is appended: `duplicates_<ts>_1.txt`, `_2.txt`, ...
    """
    reports_dir.mkdir(parents=True, exist_ok=True)

    candidate = reports_dir / filename
    if not candidate.exists():
        return candidate

    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while True:
        candidate = reports_dir / f'{stem}_{counter}{suffix}'
        if not candidate.exists():
            return candidate
        counter += 1