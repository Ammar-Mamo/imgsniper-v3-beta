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

## Round 12

### Fix — the scan filters stopped being silent, and got a one-button "Recovery Mode"

The user asked a fair question: *"is there a size limit on the videos you
compare?"* There was — and it was not the only one. `filters.*` has governed
**every** section since round 4 wired it into the single scanner
(`get_all_images()` → `collect_files()`):

| filter | shipped value | effect |
|---|---|---|
| `max_file_size_mb` | **500** | any file above 500 MB is never scanned |
| `min_file_size_bytes` | 1024 | anything smaller is never scanned |
| `exclude_patterns` | `*.tmp` `*.temp` **`*_backup*`** `*.bak` | matching NAMES are never scanned |
| `include_hidden` | false | hidden files and files inside hidden folders are never scanned |
| `include_system` | false | system files are never scanned |

None of it was announced. The concrete failure this round reproduces in a test:
a folder holding **four byte-identical videos** — `clip.mp4`,
`clip_backup.mp4`, `.hidden_a.mp4`, `.hidden_a (1).mp4` — reported
**"no duplicate video files found"**, because one copy matched `*_backup*` and
two were hidden. For someone cleaning up after a data-recovery run, where
recovered files are routinely named `*_backup*` and written into hidden
folders, that is the most expensive possible answer: the tool says the library
is clean while the duplicates are still there.

**Two changes, both reversible, neither changing what the shipped defaults do:**

1. **Transparency.** The scanner now counts every file it drops and why
   (`too_large`, `too_small`, `excluded_pattern`, `hidden`, `system`,
   `unreadable`, `not_regular`, `own_output`), and every flow prints ONE summary
   per operation:

   ```
   ⚠️ 3 file(s) were NOT scanned because of the scan filters
      (not duplicates - simply never looked at):
        - 1 matched an exclude_patterns entry (*.tmp, *.temp, *_backup*, *.bak)
        - 2 hidden (filters.include_hidden = false)
        Tip: Settings → Recovery Mode scans these files too ...
   ```

   All six scan flows do this: image duplicates, similar images, corrupted
   images, small images, the office/archives/other sections and video. Counting
   is free (no extra `stat`), and when nothing was skipped nothing is printed.

2. **Settings → Recovery Mode** (new menu item 5). One action writes
   `RECOVERY_FILTERS`: `max_file_size_mb = 0` (no cap), `exclude_patterns = []`,
   `include_hidden = true`. The same action turns it back off and restores
   `DEFAULT_FILTERS` exactly. After every toggle the resulting filter values are
   printed, and the settings panel shows the current state, so the effect is
   never a guess. The active state is **derived from the values**, not from a
   separate flag, so the menu cannot claim a state `settings.json` does not
   have.

Both profiles live as constants in `config.py` next to `DEFAULT_PRIORITY_ORDER`
(one source of truth), and the suite asserts `DEFAULT_FILTERS` still mirrors the
shipped `filters.*` block, so the two can never drift apart.

**Deliberately NOT changed:** `include_system` stays `false` in Recovery Mode
too — "System Volume Information" and `$RECYCLE.BIN` are not user data, and a
tool that moves files must never wander into them. `min_file_size_bytes` stays
1024 (sub-KB stubs are noise, not media), though it is reported when it fires.

### Tests

`tests/test_fixes_round12.py` (57 assertions): the profiles cannot drift from
`settings.json`; menu item 5 flips exactly the three keys it owns **through the
real settings loop** and restores them **byte-identically**; the menu entry and the status line exist; the
four-identical-copies folder reports zero duplicates under the defaults and two
groups under Recovery Mode; the per-reason counters are exact; all six flows
announce their skips (including the small-image flow, which builds its own
Console); an unfiltered folder prints no warning at all; and an end-to-end
recovery run keeps `clip.mp4` / `.hidden_a.mp4`, moves `clip_backup.mp4` and
`.hidden_a (1).mp4` into `duplicates-video`, and documents them in a report.
`run_all.py` now runs **13 suites**; all green, ruff clean.

## Round 11

### Feature — the Video section now does real work: EXACT duplicates, byte for byte

Main-menu item 2 printed "Coming Soon" since round 9. It now runs a real scan,
and the scope is deliberately narrow: **exact duplicates only**.

Two videos are duplicates when they share **the same extension, the same byte
size and the same full-file SHA-256**. Nothing else counts:

- a re-encode (H.264 → H.265), another resolution or bitrate → NOT a match;
- a remux (MP4 → MKV) → NOT a match, and `.mp4` never meets `.mov` even when
  their bytes are identical, because the combined "all video types" scan is
  per extension too;
- another audio/subtitle track, a trim, a crop, a watermark → NOT a match.

**No decoder was added.** No FFmpeg, no FFprobe, no OpenCV, no PyAV, no MoviePy:
this phase reads bytes and never decodes one. `requirements.txt` and
`pyproject.toml` are unchanged, and the suite asserts that no decoder module is
imported anywhere in `src/`.

### The eight video families (24 extensions)

`mp4/m4v`, `mov`, `mkv`, `avi`, `wmv/asf`, `mpg/mpeg/m2v/m2ts/mts/vob`,
`webm/ogv`, an "other containers" entry (`flv/f4v/3gp/3g2/rm/rmvb/divx/mxf/insv`)
and the combined "all video types" entry. Deliberately excluded, with the reason
recorded in the registry itself: `.ts` (shared with TypeScript sources — a
"video" scan of a development folder would hash thousands of code files),
`.m4a`/`.mka` (audio) and `.iso` (disc image). All three stay reachable through
"Other Files", which accepts any extension the user types.

### Three honest stages, because videos are the biggest files here

1. **Size pre-filter** — `stat()` only, nothing is read. A unique
   (extension, size) cannot have a byte-identical twin.
2. **Sample pre-filter (video only)** — the first + last 1 MiB of each surviving
   candidate. Byte-identical files ALWAYS share a sample, so a mismatch PROVES
   two files differ; a match proves nothing at all. The console reports both
   numbers honestly ("8.0 MiB read instead of 12.0 MiB").
3. **Full-file SHA-256** — the ONLY verdict. A sample can never decide a
   duplicate and never authorises a deletion. The suite proves the separation:
   two files identical in their first and last MiB but different in the middle
   survive the sample stage and are then correctly split by the full hash.

Concurrency is capped at 4 simultaneous full-file hashes
(`VIDEO_MAX_HASH_WORKERS`) instead of the scan mode's 16 workers — 16
multi-GB reads at once thrash a disk instead of speeding it up.

### Which copy survives, and why, in writing

Selection is video-specific (`src/core/video_file_selector.py`). Name
**provenance** is the primary key, because a copy counter says more about where
a file came from than any score can:

`recovery-style (0) < copy (1) < weak marker (2) < neutral (3) < original (4)`

- copy counters of ANY size: `file (1).mp4`, `file (15).mp4` — while
  `Movie (2018).mp4` is a YEAR and is reported as such, not penalised;
- copy words: `- Copy`, `Copy`, `_copy`, `clone`, `duplicate`;
- **Arabic patterns**: `نسخة`, `نسخة 1`, `نسخة (1)`, `نسخة٣`, `مكرر`. Matching
  reads the filename text with Arabic numerals normalised, so detection never
  depends on the Windows/OS locale;
- recovery names: `Recovered`, `recovery`, `restored`, `مسترد`, `استرداد`;
- **numbers are never penalised as such**: `20180817.mp4`,
  `VID_20180817_143522.mp4`, `Episode 2.mp4`, `Video 01.mp4` and `Camera 02.mp4`
  are not copies — camera-style names are in fact rewarded;
- dates come from the EXISTING validated extractor (`strptime`), so `20189999`
  and `12345678` are rejected and the report says they were ignored;
- among equally original names the **older** date wins, and
  `priorities.date_priority = "newest"` flips it exactly as everywhere else;
- ties fall back to modification time, then path — so two runs over the same
  folder always pick the same file.

Every file of a group gets a decision record (provenance class, importance,
date + source, per-criterion scores, weights, total, reasons), and the report
prints those reasons line by line, e.g. `decided by name provenance:
original-looking name beats copy-suffixed or copy-named`.

### Reuse vs isolation — decided from the code, not from a guess

Reused verbatim: `collect_files()` (scan filters + recycle-bin/reports
exclusion), `_calculate_file_hash_worker()`, `_store_hash()`, and the whole
shared deletion plumbing (`_collect_group_info`, `_move_files_to_bin`,
`_print_deletion_footer`, `handle_protected_files_with_user_choice`,
`reset_session_folder`), plus the pure scoring helpers `ratio_scores()` /
`compute_date_scores()` and `date_extractor.extract_date_from_filename()` /
`normalize_arabic_numbers()`. `VideoDuplicateDetector` subclasses
`DuplicateDetector` to inherit that plumbing instead of copying it, so videos
honour the same dry-run, read-only and protected-file rules as every other
section.

Isolated on purpose:

- `date_extractor.filename_importance` was **NOT** extended. Adding `(15)`,
  `نسخة` or `recovery` there would silently change which IMAGE is kept, so the
  video heuristics live in their own module. The suite asserts the shared map
  gained no video marker and that `file_selector.py` still knows nothing about
  video.
- `DuplicateReportGenerator` was **NOT** touched: image/office/archive report
  formats are byte-identical to before. A video group has to state its
  extension, its SHA-256 and its selection reasons, which that writer has no
  concept of, so `VideoDuplicateReportGenerator` writes
  `duplicate_video_<option>_<timestamp>.txt` with the same conventions (i18n
  title, date/time, total groups, total deleted, the SAME one-line
  `CPU Usage | Memory Usage` system line read from `system_monitor`,
  `🧩 Group #n`, `🟢 Kept File` / `❌ Deleted Files`, `📄` name, `📁 Path`,
  `📥 Moved to`, `📅 Date Extracted` with the date-only annotation,
  `🧭 Date Source`, `🕒 Modified`, `📌 ... Reason`, and the `===` group
  separator) and never overwrites an existing report. What it ADDS is
  video-specific and would have changed every other report if it had been
  bolted onto the shared writer: the group's Extension, its full SHA-256, the
  shared byte size, the file count, each name's provenance class, and the
  selection reasons as a bullet list instead of one summary line.
- `FileSelector` (images) and `find_duplicate_files()` (office/archives/other)
  are untouched. An office scan still returns exactly the round-9 result shape
  (no `sample_stats`) and never prints the sample line.

### CLI

Item 2 opens the section through the SAME generic `_run_section()` loop as
office/archives/other, with a menu generated from the registry (8 families +
"all" + Back). The routing branch inside `handle_duplicate_files()` is driven by
the registry's new `engine: "video"` key rather than a hardcoded section name,
so a future section can opt in the same way. The safety gate (dry-run banner,
`confirm_before_delete`, `max_files_per_operation`) applies unchanged, and
removed files land in `recycle-bin/duplicates-video`.

### Tests

`tests/test_fixes_round11.py` (181 assertions): the registry and the generated
menu, labels in both languages that say EXACT, every filename heuristic above,
the sample/full-hash separation (same-size-different-bytes, and
identical-ends-different-middle), per-extension isolation inside the combined
scan, selection determinism and the "newest" flip, the report contents, the
video recycle bin, dry-run safety, the full flow through the CLI handler, the
inherited `filters.max_file_size_mb` behaviour, and guard rails for the old
flows plus the no-decoder footprint.
`tests/test_fixes_round9.py` was updated for the one
intended behaviour change (item 2 is no longer a stub). `run_all.py` now runs
**12 suites**; all green, ruff clean, `settings.json` byte-identical.

## Round 10

### Feature — the Office section now covers the whole office family, not four extensions

Round 9 shipped the office section with the mainstream minimum: `.doc .docx`,
`.xls .xlsx`, `.ppt .pptx` and `.pdf`. The user asked where the rest of the
office formats were — and "type them into Other Files one by one" is not a
menu, so the families are now complete.

- **Word** covers the whole family: `.doc .docx .docm .dot .dotx .dotm .rtf
  .odt .wps` (legacy + macro-enabled + templates + RTF + OpenDocument + WPS).
- **Excel**: `.xls .xlsx .xlsm .xlt .xltx .ods .csv .tsv .et`.
- **PowerPoint**: `.ppt .pptx .pptm .pps .ppsx .pot .potx .odp .dps` (slide
  shows and templates included).
- The PDF entry became **PDF / XPS** (`.pdf .xps .oxps`): both are fixed-layout
  documents — the same artifact for the user.
- **New fifth entry, "Other Office Files"**: `.vsd .vsdx .pub .one .accdb .mdb
  .mpp .msg .eml .odg .odf .odb .pages .numbers .key` — Visio, Publisher,
  OneNote, Access, Project, Outlook items, OpenDocument graphics/formula/
  database and Apple iWork.
- **45 office extensions in total**, still matched PER EXTENSION. The option
  lists are disjoint, so no file can be claimed by two menu entries and two
  different formats are never treated as the same artifact. (`.ods` and `.xls`
  with identical bytes stay two files, exactly like `.doc` and `.docx`.)
- **Deliberately excluded**, with the reason recorded in the registry itself:
  `.pst` / `.ost` (Outlook mailbox DATABASES — one duplicate pair can mean
  reading tens of GB) and `.dwg` (CAD, not an office document). Both remain
  reachable through "Other Files", which accepts any extension the user types.
- The menu labels in BOTH languages now name the extensions they cover, so the
  choice is not a guess: `Delete Duplicate Excel Files - xls, xlsx, ods, csv,
  et (sha256)`.

Nothing about the engine changed: same `stat()` size pre-filter, same SHA-256
in 1 MiB blocks, same `(extension, sha256)` keys, same report writer and the
same per-section recycle-bin folders.

### Tests

`tests/test_fixes_round10.py` (46 assertions): the exact extension tables, the
menu wiring (entry 5 → `office_other`, the combined entry still last), overlap
detection between option lists, well-formed extensions, the i18n labels in both
languages naming their formats, scans proving `.ods`/`.xls` with identical
bytes are NOT grouped, a `.pages` pair deleted while identical `.vsd`/`.vsdx`
stay untouched, the report prefix/title and the absence of a "0x0" line, and
the settings filter (`min_file_size_bytes`) still applying to section scans.
`tests/run_all.py` now runs **11 suites**.

## Round 9

### Feature — the Office, Archives and Other sections now do real work

Rounds 1–8 only ever handled images; the other three category menus answered
"Coming Soon". They now run the same SHA-256 duplicate pipeline as images, for
the file types the user asked for.

- **`src/core/file_categories.py` (new)** — one registry drives everything: the
  menu entries, each option's extensions, the recycle-bin subfolder and the
  report prefix. Adding a format is one line plus its label; there is no second
  place to update.
- **Office** = Word (`.doc` + `.docx` as ONE type), Excel (`.xls` + `.xlsx`),
  PowerPoint (`.ppt` + `.pptx`), PDF, or "all office types". **Archives** =
  `.zip .rar .7z .tar .gz/.tgz .bz2 .xz` or all of them. **Other Files** asks
  which extensions to scan (`iso, apk` → `.iso, .apk`) and refuses to scan when
  the answer holds no valid extension, instead of reporting "no duplicates
  found" for a scan that never covered anything.
- **Matching is PER EXTENSION**: even the combined "all types" scan groups by
  `(extension, sha256)`, so a `.doc` can never be declared a duplicate of a
  `.docx` (or a `.zip` of a `.7z`) just because their bytes happen to match.
- **Video stays "Coming Soon" on purpose**: it needs its own metadata source
  (duration/resolution/codec) and its own performance profile, so it was
  postponed rather than half-delivered.
- The gear emoji was dropped from the Settings entry so it matches the other
  categories, in both languages.

### P1 — a 4 GB archive must not be read to find out it has no twin

Hashing every file of a documents/archives library would read hundreds of GB
for nothing.

- `find_duplicate_files()` is a two-stage pipeline: (1) group by
  `(extension, exact byte size)` using `stat()` only — a unique size cannot
  have a byte-identical twin, so the file is dropped without a single read;
  (2) SHA-256 (1 MiB blocks) on same-size candidates only. The console reports
  how many files were actually read, so the saving is visible rather than
  silent.
- The image path is untouched: `find_duplicate_images()` keeps its own flow and
  its 4 KB scan-mode chunk size.

### P2 — non-image files had no date, so "keep the oldest copy" could never work

Word/Excel/PDF/archive files carry no EXIF and usually no date in the name,
so every such group was a permanent date tie.

- `date_extractor.get_best_date()` gained `fallback_mtime`: when there is no
  EXIF and no filename date, the file's MODIFICATION time is used and reported
  with the source **`modified`** — never dressed up as EXIF data. It is opt-in
  (`fallback_mtime=False` by default), so image behaviour is unchanged.
- `FileSelector.select_best_file(..., fallback_mtime=True)` is used by the
  section flow only, so the OLDEST copy survives there too.

### P2 — a Word document has no resolution, so the report must not invent one

- `ImageInfoExtractor.get_detailed_file_info()` returns the historic info dict
  plus `kind`: `'image'` with real dimensions, or `'file'` with `0x0` and the
  mtime date. Section reports then skip the Dimensions line instead of printing
  a meaningless "0x0".

### P2 — two report writers would have drifted apart

- `DuplicateReportGenerator._write_duplicates_report()` is now the ONLY
  duplicates writer. `spec=None` reproduces the image report byte-for-byte
  (same file name, title, labels, group separator, on-demand info extraction);
  a section `spec` switches the prefix (`duplicate_office_...`), the title, the
  kept/deleted labels and the info extractor.
- Fixed in passing: the no-info image variant built its reason-engine info dict
  late, inside the kept-file branch, and raised `NameError` when the kept file
  was unreadable — the report could not be written at all.
- Removed files keep their own recycle-bin subfolder per section
  (`duplicates-office`, `duplicates-archives`, `duplicates-other`; images keep
  `duplicates`), so recovery stays organised and a section's deletions are easy
  to find.

### Tests

`tests/test_fixes_round9.py` (91 assertions): registry and i18n coverage in
both languages, extension normalisation, the size pre-filter (a unique-size
file and a same-size/different-bytes file are never reported), per-extension
isolation in the combined scan, recycle-bin exclusion, dry-run vs real move,
report layout for images AND sections, mtime date fallback, menu rendering,
main-menu routing (3/4/5 → sections, 2 still video), custom extensions (valid
and invalid), and a full office flow through the CLI handler.
`tests/run_all.py` now runs **10 suites**.

## Round 8

### P1 — full-score ties were broken by scan order, so the same folder could keep a different file each run

The user reported a tie group where the alphabetical rule "no longer seemed
to be taken into account" (`errors.txt`): round 7's tie label said "tie broken
by scan order", meaning the winner depended on which file the scanner happened
to visit first — two runs over the same folder could delete a different image.

- `select_best_file()` now breaks a full-score tie by the FILENAME
  (case-insensitive) and only falls back to scan order when the names are
  identical too (in which case the files are interchangeable). Verified with
  3 identical files × all 6 input permutations → one single winner, the
  alphabetically first filename.

### P2 — report reasons were too convoluted to read

The round-7 sentences ("kept file has a higher weighted score (+4.4 pts; main
advantage: filename importance: 6/9 vs 2/9)") were accurate but unreadable —
the user asked to "just tell me the result, e.g. filename importance".

- Selection reason: `<criterion> (<kept> vs <deleted>)` →
  `filename importance (6/9 vs 2/9)`.
- Deletion reason: `<criterion> (kept: <kept> — this file: <deleted>)`.
- Full tie: `Tie in weighted criteria — kept the alphabetically first filename`
  (or `Tie — identical criteria and filename` when even the name matches).

### P2 — reports didn't show where the files actually are

- Every report now prints `📁 Path: <full original path>` for the kept file
  AND each deleted file (before, only the corrupted report had paths).
- Outside dry-run each deleted file's path is followed by
  `📥 Moved to: <recycle-bin destination>` — the exact path
  `move_to_recycle_bin()` returned — so recovery is copy-paste. Dry-run omits
  it, because nothing was moved.

### P3 — dry-run flooded the console and the settings were buried

- Dry-run used to print one "[DRY-RUN] would move…" line PER FILE (thousands
  of lines on large libraries). Those lines now go to `imgsniper.log`; the
  console keeps the banner plus ONE summary line
  (`DRY-RUN: N files would be moved — the full list is in the report`).
- Settings moved from the image menu to the MAIN menu (option 6): safety
  toggles (dry-run / confirm / max files — previously editable only by
  hand-editing settings.json, which is how a user ends up stuck in dry-run
  without knowing how to leave it), priorities, scan modes and "reset to
  defaults" now live in one place that also governs the future video/office
  categories.
- All new strings exist in EN + AR (`settings.*`, `reports.moved_to`,
  `reports.reason_criterion_decided*`, `reports.reason_tie_full`,
  `safety.dry_run_summary`).

Pinned by `tests/test_fixes_round8.py` (49 assertions).

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


