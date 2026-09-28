# Changelog

ImgSniper v3 beta — post-audit remediation history.

Every entry below names the audit finding it closes, what was actually wrong,
what was changed, and which test suite now pins the behaviour so it cannot
regress silently. The three audit reports that produced these findings are
`ImgSniper-v3-AUDIT-FOR-AI.md`, `ImgSniper-v3-AUDIT-FOR-ENGINEER.md` and
`ImgSniper-v3-AUDIT-FOR-NONTECHNICAL.md`.

Format: newest first. `P0` = data-loss risk, `P1` = correctness, `P2` =
significant defect, `P3` = hygiene.

---

## Round 7

### P1 — selection criteria were not comparable; the filename decided everything

The weighted sum (weights 4/3/2/1) combined scores that lived on wildly
different scales: filename importance used the raw 1–9 score (swings of ~6
points) while size/resolution used absolute caps tuned for multi-MB / multi-MP
files, so a 0.07 MB image scored 0.14/10 and a 4x pixel difference only ~0.5
point. The configured priority order was effectively ignored — in the reported
groups #518/#526/#572 a 360x449 file was kept over a 720x897 one because its
name scored 8/9 vs 2/9.

- Every criterion is now normalised WITHIN the group onto one comparable 0–10
  scale: log-ratio for resolution/size (best = 10, worst = 0), proportional
  for filename (importance × 10/9), relative for dates as before.
- No-decision gates: spreads below 5% (resolution/size) are ties; date gaps
  below one minute — or below a full day when a filename date is involved —
  are ties. The midnight artifact of a filename date can no longer decide a
  group (round 5's #14/#239 had only fixed the report wording, not the
  scoring).
- `build_group_scoretable()` in `file_selector.py` is now the single source of
  truth for BOTH the selection engine and the report reasons.

### P1 — report reasons were ambiguous and counter-factual

`get_deletion_reason()` printed the deleted file's own attribute as a bare
label ("Higher resolution"), which reads as a justification — and it fired on
the first score that merely differed (`!=`), so a 1-pixel gap (736x826 vs
735x826) was presented as a reason. Selection reasons could cite a 0.01 MB
micro-gap against one file while a 0.08 MB sibling existed.

- Reasons are computed from the same scoretable that decided and state the
  weighted-score margin with raw values ("+2.8 pts; main advantage: filename
  importance: 8/9 vs 2/9").
- Genuine advantages of the deleted file are named explicitly, and
  sub-threshold differences are labelled as such ("resolution differed only
  within the no-decision threshold (736x826 vs 735x826)").
- Selection reasons compare against the CLOSEST rival (highest weighted
  total) instead of the first file whose single criterion differs.

### P1 — user priorities silently reverted to the default

`config.set()` saves to disk immediately, but every test suite ended by
restoring its config backup IN MEMORY only — so after any test run the real
`config/settings.json` kept whatever the tests had written last (including
`priorities.order = [1, 2, 3, 4]`). That is exactly why user-set priorities
"reverted to default after a while".

- Every suite now snapshots `config/settings.json` bytes and restores them via
  `atexit`; verified by an MD5 comparison before/after a full `run_all.py`.
- `DEFAULT_PRIORITY_ORDER` is now `[2, 3, 1, 4]` = date → resolution → size →
  filename (the shipped default the user asked for); the CLI "Reset to
  Defaults" action follows it automatically.
- `main.py` logs the loaded priority order at startup, so any future overwrite
  is visible in `imgsniper.log` instead of a mystery.

Pinned by `tests/test_fixes_round7.py`.

---

## Round 6

### P1 — RAW/HEIC images were silently excluded from every scan (and flagged as "corrupted")

`.cr2/.nef/...` were listed as supported but Pillow cannot open them; HEIC was
not even listed. Such files either vanished from the similarity scan (debug
line only) or — worse — the corruption scan reported them as CORRUPTED and
offered them for deletion.

- New `src/utils/helpers/image_codec.py`: central decoder with OPTIONAL codecs
  — `rawpy` for camera RAW, `pillow-heif` for HEIC/HEIF (both now listed in
  `requirements.txt`, imported defensively). `open_image_with_reason()`
  distinguishes `missing_codec` (unsupported, NOT corrupted) from
  `decode_error` (genuinely unreadable).
- Similarity hashing, small-image analysis, resolution/size scoring, report
  info and similarity percentages all decode through the helper; `.heic/.heif`
  are registered in every scanning format list.
- Excluded files are counted, printed and logged by name (`total_excluded`),
  with an install hint when the cause is a missing codec; the corruption scan
  reports them under `unsupported_files` instead of flagging them.

Pinned by `tests/test_fixes_round6.py`.

---

## Round 5

### #1126 — identical UI/screenshot templates grouped as "similar"

pHash alone (distance 0–8 accepted) grouped WhatsApp screenshots with
identical layout but different content. A dHash secondary guard now requires
BOTH Hamming distances within the threshold; the user's 5-screenshot false
group became 0 groups.

### #7/#15/#18/#25/#535/#14/#239/#1124 — honest reasons, dates and warnings

Score-capped byte gaps no longer masquerade as reasons; the invented
"shorter filename" / "alphabetical order" / "Recovered/backup image" labels
were replaced with explicit tie labels; filename dates are annotated as
day-precision; the deletion reason uses the merged EXIF+filename dates; PIL
"Corrupt EXIF data" warnings are routed to logging instead of stderr.

Pinned by `tests/test_fixes_round5.py`.

---

## Round 4

### P2-7 — `get_all_images()` ignored every filter and rescanned the recycle bin

`get_all_images()` returned every file carrying an image extension. It never
consulted `filters.exclude_patterns`, `include_hidden`, `include_system`,
`min_file_size_bytes` or `max_file_size_mb` — all of which ship in
`settings.json` and were completely inert. Worse, it descended into ImgSniper's
own output directories: when the scanned folder contained the project (or was
the working directory the recycle bin is created in), files already removed
into `recycle-bin/` came straight back into the pipeline and were hashed,
reported and **moved again**.

- Filters are now applied, with one `stat()` per file serving existence,
  regular-file, size and Windows hidden/system attributes.
- `paths.recycle_bin`, `reports`, `temp` and `cache` are excluded by **resolved
  absolute path**, against both the project root and `Path.cwd()`
  (`move_to_recycle_bin` builds its target from cwd while `settings.json` lives
  under the project root, so either can be the real one).
- Matching is by path, never by directory **name**, so a user's real photo
  folder called `reports` is not silently skipped — and neither a sibling such
  as `reports-old` nor a file called `reports.jpg` is caught. Prefixes are
  separator-terminated for exactly that reason.
- Pattern matching is case-insensitive on every platform; every numeric filter
  treats `0` or an invalid value as **disabled**, so a scan can always be
  widened from `settings.json` alone.
- `filters.min_resolution` / `max_resolution` are deliberately **not** applied
  here: honouring them would mean opening and decoding every candidate image
  purely to decide whether to skip it, dwarfing the real duplicate work.
  Resolution is considered where images are opened anyway.

### P2-20 — the `logging` section existed but logging was never configured

`settings.json` shipped `logging.level`, `file`, `max_size_mb`, `backup_count`
and `format`, yet nothing in the project ever called `basicConfig` /
`dictConfig` or attached a handler. The only two `logging.warning()` calls fell
through to the root logger's `lastResort` handler — bare unformatted stderr
text — and `imgsniper.log` was **never written**. Batch failures in the
parallel similarity path left no trace, which is exactly when a log is needed.

- Added `src/utils/helpers/logging_setup.py`, called once from `main.py` before
  the CLI is constructed. Attaches a UTF-8 `RotatingFileHandler` via
  `dictConfig`.
- File handler only, deliberately: the CLI is an interactive Rich UI with live
  progress bars, and a stream handler would corrupt the rendered layout.
- `setup_logging()` never raises. An unknown level falls back to `INFO`; an
  invalid format string is probed at **boot** (logging validates formats
  lazily, so a typo would otherwise print `--- Logging error ---` on every
  single record); an unwritable location degrades to a `NullHandler`.
- Seven silent `except Exception: pass` sites that hid real failures now log:
  file-hash failures, perceptual-hash failures, batch-result collection
  (`WARNING`, matching its two sibling paths), EXIF and Exif sub-IFD reads, and
  both pixel-count readers feeding the quality-floor guard and the
  resolution-sacrifice warning.
- Four sites stay silent **on purpose**: `__del__` during interpreter shutdown,
  the `_safe_print` last resort (logging there would recurse into the same
  broken stdout), the `NullHandler` fallback itself, and the `report_formatter`
  i18n fallback, which is normal control flow rather than an error.

### P2-22 — every settings save rewrote the whole file and flipped line endings

Found while verifying P2-21. A single `config.set()` rewrote all 240+ lines of
`config/settings.json`. `open(..., 'w')` in text mode translates every newline
to CRLF on Windows while git stores LF (`core.autocrlf=true`), so one tiny
settings change produced a spurious "every line changed" diff that made the
file impossible to review — plus an fsync on every call even when nothing
changed.

- `save_config()` now serializes once, compares against the on-disk content
  with line endings normalized, and returns immediately when identical.
- When a write **is** needed it reuses the file's existing line-ending style
  and opens with `newline=''` so the payload lands byte-for-byte.
- The suites now leave `config/settings.json` untouched, and the round-4 log
  file survives `dictConfig()` closing every handler (it previously stopped
  writing at the first `setup_logging()` call, truncating the log at exactly
  the point where the interesting output began).

### P3-8 — inert `safety.create_backup` and `safety.preserve_originals` removed

Both sat in `settings.json` as `true` while no code anywhere ever read them —
yet both implied an active safety mechanism. In a tool that removes files, a
setting that looks like a guarantee but does nothing is worse than no setting
at all.

They were also redundant by design: ImgSniper **never** permanently deletes, it
moves files into `paths.recycle_bin` with their folder structure preserved, so
every removed file stays recoverable and the file kept for each group is by
definition the preserved original. Wiring them up would have meant either
doubling disk usage for a large library or introducing a brand-new
permanent-delete path, and a toggle that cannot really be turned off is a false
guarantee either way. Removed instead, with the rationale recorded in
`safety._note` and in the `move_to_recycle_bin()` docstring.

### P2-21 — 13 bare `except:` clauses replaced with `except Exception:`

A bare `except:` also catches `KeyboardInterrupt` and `SystemExit`, so Ctrl-C
during a long scan — the primary escape hatch in a batch tool — could be
swallowed silently and converted into a misleading fallback path (for example
`image_analyzer` falling back to hardcoded English labels, or
`similarity_group_finder` skipping a whole batch).

---

## Round 3

- **P0-8** — `original` and `camera` filename weights lowered to `8` and their
  bonus exemption removed, so they no longer outranked genuinely informative
  names.
- **P0-4** — `phash_threshold` is now scaled by `hash_size`
  (8→5, 10→8, 12→11, 16→20), so "similar" means the same thing in every scan
  mode instead of silently getting stricter as the hash grew.
- **P2-14** — `compare_images_by_date` no longer falls back to filename scoring
  when no real date exists.
- **P2-13** — reports now show the same merged EXIF+filename date the engine
  actually used, plus a `Date Source: exif | filename | none` line.
- **P2-18** — the default language was unified to English across
  `src/core/config.py`, `config/settings.json`, `src/cli/main_cli.py` and
  `src/core/i18n/i18n_manager.py`. Previously these sources disagreed and the
  effective language depended on which happened to win.
- **P3-6** — `run.bat` typos corrected (`newr` → `newer`, `runnig` →
  `running`).

---

## Rounds 1 and 2

Included in the baseline commit (tag `v3.0.0-beta`).

### Selection and grouping correctness

- **P0-1 / P0-3** — file selection replaced a short-circuit priority comparison
  with **weighted scoring**. Before the fix, many priority permutations could
  keep a tiny thumbnail and delete the high-resolution image; after it, every
  tested permutation keeps the high-resolution image.
- **P0-2** — Union-Find grouping unified across the small and large dataset
  paths, so the sequential and parallel code paths produce identical groups.
- **P0-6** — filename matching changed from substring to **word-boundary**
  matching, so hostile names no longer score by accident.
- **P2-5** — the date criterion was revived using group-relative date scoring
  over merged EXIF + filename dates.
- **Quality floor** — resolution now receives a capped extra boost on extreme
  resolution gaps, so a thumbnail cannot win on date or filename alone.
- **Resolution-sacrifice warning** — reports flag when a lower-resolution file
  is kept over a higher-resolution one.
- `max_distance` similarity maths is derived from the actual hash size.
- `DEFAULT_PRIORITY_ORDER = [1, 2, 3, 4]` is defined once and reused
  everywhere, so the default order can no longer drift apart.

### Safety and robustness

- `safety.dry_run_mode`, `safety.confirm_before_delete` and
  `safety.max_files_per_operation` made functional. They were inert — a user
  who set `dry_run_mode: true` got no change in behaviour at all.
- Atomic config writes (temp file → `fsync` → `os.replace`).
- `mkdir(parents=True, exist_ok=True)` throughout.
- Unicode/cp1256 print crashes fixed via `_safe_print` plus a stdout/stderr
  `errors="replace"` safety net, so emoji or Arabic output can no longer abort a
  file operation mid-run.
- Destructive migration scripts disabled.

### Hygiene

- Requirements trimmed from 22 packages (~3–5 GB of downloads, including torch,
  easyocr, opencv, scipy, scikit-image, pytesseract and `pathlib2` — a Python 2
  backport of `pathlib` that is actively harmful on Python 3) to the **five**
  actually imported: Pillow, imagehash, numpy, psutil, rich.
- `.gitignore` fixed: an unanchored `reports/` was also matching the source
  package `src/utils/reports/` (8 modules), silently hiding real code from git
  and producing a broken clone. Now anchored as `/reports/` and `/recycle-bin/`.
- Repository initialised with real history and tagged `v3.0.0-beta`.

---

## Round 5 — project scaffolding

- **P3-9** — added `README.md`, `CHANGELOG.md`, `pyproject.toml` (project
  metadata + ruff configuration) and a GitHub Actions workflow that runs
  byte-compilation, the critical lint gate and the full test suite on both
  Windows and Linux. `.gitignore` extended with `desktop.ini`, `.ruff_cache/`
  and `.zencoder/`.
- The lint gate is the **critical** rule set only (`E9` syntax/indentation,
  `F63` invalid comparisons, `F7` misuse of `break`/`continue`/`return`, `F82`
  undefined names) — genuine defects rather than taste — and is verified green.
  The full rule set reports several hundred pre-existing style findings, which
  are left for incremental cleanup rather than being made blocking.
- Test coverage now stands at **8 suites**, all passing,
  runnable as a single gate via `python tests/run_all.py` (exit code `0`).


