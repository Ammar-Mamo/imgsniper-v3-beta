# 🖼️ ImgSniper v3 (beta)

Batch image-cleanup tool for very large photo libraries. It finds duplicate,
visually similar, corrupted and undersized images, shows you exactly why each
decision was made, and **moves** the losers into a recycle bin instead of
deleting them.

> **نسخة تجريبية / beta.** See [Known limitations](#known-limitations) before
> pointing it at an irreplaceable library.

---

## Table of contents

- [What it does](#what-it-does)
- [The safety model — read this first](#the-safety-model--read-this-first)
- [Requirements](#requirements)
- [Install](#install)
- [Run](#run)
- [Configuration](#configuration)
- [Tests](#tests)
- [Lint](#lint)
- [Project layout](#project-layout)
- [Known limitations](#known-limitations)
- [License](#license)

---

## What it does

| Operation | How it decides |
|---|---|
| **Duplicate detection** | Exact byte-level matching via a cryptographic file hash — only bit-identical files are grouped. |
| **Similar-image detection** | Perceptual hashing (`imagehash`). Four scan modes trade speed for accuracy: `normal` (hash size 8), `medium` (10), `advanced` (12), `ultra` (16). The similarity threshold scales with the hash size so "similar" means the same thing in every mode. |
| **Corrupted-image detection** | Attempts a real decode and flags files that fail. |
| **Small-image detection** | Flags images below a resolution threshold (default 300×300). |
| **Reports** | A text report per operation, listing every group, the image kept, the images removed, each file's **full original path** (plus the recycle-bin destination outside dry-run), and a human-readable **reason** for each decision. |
| **Non-image duplicates** | The **Office**, **Archives** and **Other** sections run the same exact-hash duplicate detection for documents, spreadsheets, presentations, PDFs and archives. Matching is **per extension**, so a `.doc` is never offered as a duplicate of a `.docx`. Files with no EXIF and no date in the name fall back to their **modification time**, so the oldest copy is still the one kept. |

The CLI is available in **English** and **Arabic** (`language` in
`config/settings.json`, default `en`).

### Which files each category scans

| Main-menu item | Options | Types |
|---|---|---|
| **1 — Images** | duplicates, similar, corrupted, small | The image extensions in the scan filters |
| **2 — Videos** | *coming soon* | Postponed on purpose — video needs its own metadata source (duration/resolution/codec) and its own performance profile |
| **3 — Office** | Word, Excel, PowerPoint, PDF/XPS, other office formats, all office types | Whole **families**, not just the modern extension: Word `.doc .docx .docm .dot .dotx .dotm .rtf .odt .wps` — Excel `.xls .xlsx .xlsm .xlt .xltx .ods .csv .tsv .et` — PowerPoint `.ppt .pptx .pptm .pps .ppsx .pot .potx .odp .dps` — PDF/XPS `.pdf .xps .oxps` — other `.vsd .vsdx .pub .one .accdb .mdb .mpp .msg .eml .odg .odf .odb .pages .numbers .key` (45 extensions in total) |
| **4 — Archives** | ZIP, RAR, 7Z, TAR, GZ/TGZ, BZ2, XZ, all archives | `.zip .rar .7z .tar .gz/.tgz .bz2 .xz` |
| **5 — Other files** | custom extensions | You type them (`iso, apk` → `.iso, .apk`); an answer with no valid extension refuses to scan instead of reporting "no duplicates found" for a scan that never covered anything |
| **6 — Settings** | — | Program-wide configuration (Round 8 moved it out of the images section) |

Matching is **per extension even in the combined "all types" scan**: two files
are only compared when both their extension and their SHA-256 hash match, so a
`.doc` can never be grouped with a `.docx` (or a `.zip` with a `.7z`) just
because their bytes happen to be identical. Duplicates found in a section are
moved to their own recycle-bin folder — `duplicates-office`,
`duplicates-archives`, `duplicates-other` — and reports are prefixed
`duplicate_office_`, `duplicate_archives_`, `duplicate_other_`.

### How the "best" image is chosen

For each group of similar images, four criteria are scored and combined. The
**shipped default order** is date → resolution → size → filename
(`priorities.order`; rank 1 = highest, weights 4/3/2/1):

1. **Date** — EXIF capture date merged with dates embedded in the filename;
   `priorities.date_priority` selects `oldest` or `newest`. Each report line
   shows `Date Source: exif | filename | none`. A gap smaller than one minute
   — or smaller than a day when a filename date is involved (day-level
   precision) — counts as a tie, not a decision.
2. **Resolution** — higher pixel count wins.
3. **File size** — larger file wins (more detail, less compression).
4. **Filename** — names like `copy`, `(1)` or `Recovered_*` are penalised;
   clean camera names score higher.

**Round 7 — comparable scales.** Each criterion is normalised *within the
group* onto one comparable 0–10 scale (log-ratio for resolution/size,
proportional for filename) and a no-decision gate ignores spreads below 5%.
Previously size/resolution used absolute caps (0.07 MB scored 0.14/10) while
the filename scale swung ~6 points, so the filename dominated no matter what
rank it had — reports showed a 360×449 file kept over a 720×897 one. Reports
now state the *actual* deciding criterion, the weighted-score margin, and any
advantage the deleted file genuinely had ("…within the no-decision
threshold"), instead of ambiguous labels like "Higher resolution" for a
1-pixel gap.

**Round 8 — deterministic ties, readable reasons, full paths.** A full-score
tie is now broken **alphabetically by filename** (case-insensitive), so the
same folder keeps the same winner on every run instead of whatever file the
scan order happened to visit first. Reasons were shortened to the plain
deciding fact — `filename importance (6/9 vs 2/9)`, and for a deletion
`kept: … — this file: …` — with ties labelled
`Tie in weighted criteria — kept the alphabetically first filename`. Every
report shows the full original path of the kept **and** deleted files, plus
the exact `Moved to:` recycle-bin destination outside dry-run, so any removed
image can be found again instantly. Dry-run no longer prints one line per
file: those lines go to `imgsniper.log` and the console shows a single
`DRY-RUN: N files would be moved` summary.

**Round 9 — non-image files.** Word, Excel, PowerPoint, PDF and archive files
carry no EXIF and usually no date in the name, so the date criterion would
always tie. When a file has neither, its **modification time** is used and
reported as `Date Source: modified` — never dressed up as EXIF. Size, filename
and the alphabetical tie-break work exactly as they do for images, with one
difference: the size pre-filter (below) means a unique-size file is never hashed
and never even becomes a duplicate candidate.

Two guards prevent the classic failure mode of "kept a thumbnail, deleted the
real photo":

- **Quality floor** — when a group spans an extreme resolution range,
  resolution receives extra (but capped) weight, so a tiny image cannot win on
  date or filename alone.
- **Resolution-sacrifice warning** — if the kept image has *fewer* pixels than
  another image in the group, the report says so explicitly.

### The two-stage duplicate scan

Hashing every file of a documents or archives library would read hundreds of GB
for nothing, so duplicate detection runs in two stages:

1. **Size pre-filter (`stat` only).** Files are grouped by *extension + exact
   byte size*. A file whose size is unique cannot have a byte-identical twin, so
   it is dropped without being read at all.
2. **SHA-256.** Only same-size candidates are read (1 MiB blocks) and grouped by
   hash. The console states how many files were actually read, so the saving is
   visible rather than silent.

Image duplicate detection keeps its own stage-1 flow and its 4 KB chunk size,
unchanged.

---

## The safety model — read this first

**ImgSniper never permanently deletes anything.** Every removed file is
**moved** into `recycle-bin/`, preserving its original folder structure, so it
can be put back by hand at any time.

| Setting | Effect |
|---|---|
| `safety.confirm_before_delete` | Asks for an explicit `y` before anything is moved. |
| `safety.dry_run_mode` | Announces what *would* be moved and touches nothing at all — not even empty recycle-bin folders. |
| `safety.max_files_per_operation` | Hard cap on how many files one operation may move (`0` = unlimited). |

**Round 8 — all three toggles are in the CLI itself:** main menu →
**⚙️ Settings → 🛡️ Safety Settings** turns dry-run / confirmation on and off
and changes the max-files cap (no hand-editing `settings.json`, and no way to
get stuck in dry-run). The same menu hosts priorities, scan modes and
"reset to defaults".

Additional guarantees that are always on:

- ImgSniper's own output directories (`recycle-bin/`, `reports/`, `temp/`,
  `cache/`) are **never scanned**, so files you already removed cannot come
  back into a later run.
- Every removed file is recoverable byte-for-byte from the recycle bin.
- Unexpected failures (unreadable EXIF, unhashable files, failed comparison
  batches) are written to `imgsniper.log` rather than swallowed.

> **Recommended first run:** set `safety.dry_run_mode` to `true` — either in
> `config/settings.json` or from the CLI (main menu → **⚙️ Settings → 🛡️
> Safety Settings**) — run a scan, read the report, then toggle it back off.

---

## Requirements

- **Python 3.10 or newer** (developed and tested on 3.10.11)
- Windows or Linux. Windows consoles with a limited code page (cp1256/cp1252)
  are handled explicitly: emoji and Arabic output can never abort a file
  operation, and the log file is always UTF-8.

Five core third-party packages are used at runtime, plus two **optional**
codec extras (HEIC + camera RAW — the app runs fine without them and reports
every undecodable file instead of skipping it silently):

| Package | Purpose |
|---|---|
| `Pillow` | Image decoding and EXIF reading |
| `imagehash` | Perceptual hashing |
| `numpy` | Hash comparison |
| `psutil` | Memory/CPU-aware worker sizing |
| `rich` | Menus, panels, progress bars, prompts |
| `pillow-heif` *(optional)* | HEIC/HEIF decoding |
| `rawpy` *(optional)* | Camera RAW decoding (.cr2/.nef/.arw/.dng/…) |

---

## Install

**Windows**

```bat
install_requirements.bat
```

**Anywhere**

```bash
python -m pip install -r requirements.txt
```

Optional developer tooling:

```bash
python -m pip install ruff
```

---

## Run

```bash
python main.py
```

or, on Windows:

```bat
scripts\run.bat
```

The CLI is interactive: first pick a language, then a category from the main
menu (1 images, 2 video, 3 office, 4 archives, 5 other files, 6 settings), then
an operation and the folders to scan — review the summary, then confirm.

Reports are written to `reports/`. Removed files are moved to `recycle-bin/`.
Runtime messages are written to `imgsniper.log` (rotating, 10 MB × 5 files by
default). All three directories are git-ignored.

---

## Configuration

Everything lives in **`config/settings.json`**. Writes are atomic (temp file →
`fsync` → `os.replace`), and a save whose content is unchanged does not touch
the file at all.

### Sections that are actually read by the code

| Section | Controls |
|---|---|
| `language` | `en` or `ar` |
| `priorities` | The four selection criteria, their toggles, and `order` — the rank of each criterion, `[1, 2, 3, 4]` = resolution → size → date → filename |
| `processing` | `scan_mode`, `phash_threshold`, `batch_size`, `max_workers`, `memory_limit_mb`, caching and parallelism |
| `paths` | `recycle_bin`, `reports`, `temp`, `cache` — all four are excluded from scanning |
| `similarity` | Similarity grouping settings |
| `filters` | `exclude_patterns`, `include_hidden`, `include_system`, `min_file_size_bytes`, `max_file_size_mb`. Any numeric filter set to `0` is **disabled**, so a scan can always be widened without a code change |
| `safety` | `confirm_before_delete`, `dry_run_mode`, `max_files_per_operation` |
| `logging` | `level`, `file`, `max_size_mb`, `backup_count`, `format` |

Note on `filters.min_resolution` / `max_resolution`: these are **deliberately
not** applied during scanning. Honouring them would mean opening and decoding
every candidate image purely to decide whether to skip it, which would dwarf
the cost of the actual duplicate work. Resolution is taken into account where
images are opened anyway (small-image detection and the quality-floor guard).

### Sections present in the file but not yet wired up

These exist in `settings.json` for forward compatibility with features that are
still stubs. **Changing them currently has no effect:**

`file_types`, `watermark_removal`, `ui`, `models`, `advanced`,
`notifications`, `statistics`.

Two inert keys were **removed** rather than left in place, because a safety
setting that looks like a guarantee but does nothing is worse than no setting
at all: `safety.create_backup` and `safety.preserve_originals`. The recycle bin
already provides both guarantees unconditionally (see
[The safety model](#the-safety-model--read-this-first)). The rationale is
recorded in `safety._note` inside `settings.json`.

---

## Tests

The suites are plain scripts (no pytest needed). Each runs in its **own**
process so their global state — the config singleton, the i18n language, the
logging handlers — cannot leak into one another.

```bash
python tests/run_all.py
```

Exit code `0` means everything passed, so it works directly as a pre-commit or
CI gate.

| Suite | Focus | Assertions |
|---|---|---|
| `test_fixes.py` | Round 1 audit findings (P0/P1) | 63 |
| `verify_e2e.py` | End-to-end scenarios on real generated images | 22 |
| `test_fixes_round2.py` | Safety gate, date criterion, quality floor | 59 |
| `test_fixes_round3.py` | Scoring, date sources, language defaults | 43 |
| `test_fixes_round4.py` | Scan filters, logging, config writes, safety keys | 119 |
| `test_fixes_round5.py` | Recycle-bin behaviour, protected files, i18n | 45 |
| `test_fixes_round6.py` | Report layout, reason wording, path handling | 55 |
| `test_fixes_round7.py` | Comparable 0–10 criteria scales, no-decision gate, config restore | 22 |
| `test_fixes_round8.py` | Alphabetical tie-break, plain reasons, full paths, main-menu settings | 49 |
| `test_fixes_round9.py` | Office/archives/other SHA-256 duplicates, per-extension matching, section menus and reports | 93 |
| `test_fixes_round10.py` | Full office format coverage: macro/template/OpenDocument/WPS families, PDF+XPS, Visio/Publisher/Access/iWork entry | 46 |
| | **Total** | **616** |

Per-suite logs are written to the project root (`test_run.log`,
`verify_e2e.log`, `test_run_round<N>.log`). All are git-ignored.

The suites leave `config/settings.json` byte-for-byte untouched.

---

## Lint

```bash
python -m ruff check src main.py tests scripts
```

The gate is the **critical** rule set only — genuine defects rather than taste:
`E9` (syntax/indentation), `F63` (invalid comparisons, duplicate keys), `F7`
(misuse of `break`/`continue`/`return`) and `F82` (**undefined names**). It is
configured in `pyproject.toml` and is green.

The full rule set reports several hundred *pre-existing* style findings
(annotation modernisation, import sorting, blind except, …). Those are left for
incremental cleanup rather than being made blocking, which would either force a
large refactor or drown the gate in noise. To see them:

```bash
python -m ruff check --select ALL src main.py tests
```

---

## Project layout

```
main.py                     Entry point (configures logging, then starts the CLI)
config/settings.json        All configuration
requirements.txt            Core + optional codec dependencies
pyproject.toml              Project metadata + ruff configuration
install_requirements.bat    Windows dependency installer

src/
  cli/                      Interactive CLI, operation handler, settings handler
  core/
    config.py               Settings load/save (atomic, no-op-aware)
    file_selector.py        Chooses the best image of each group
    file_categories.py      Registry of categories, their extensions, report
                            prefixes and recycle-bin folders
    image_analyzer.py       Orchestrates the operations
    detectors/              Duplicate, similarity and corruption detectors
    processors/             Thin processor layer over the detectors
    i18n/                   English and Arabic translation tables
  utils/
    helpers/                File utils, date extraction, scan modes,
                            logging setup, system monitoring
    reports/                Report generators and formatters

tests/                      Eleven suites plus the unified runner (run_all.py)
scripts/                    run.bat and maintenance helpers

reports/                    Generated reports   (created at runtime, git-ignored)
recycle-bin/                Removed files       (created at runtime, git-ignored)
imgsniper.log               Rotating runtime log(created at runtime, git-ignored)
```

---

## Known limitations

This is a beta. Be aware of the following before relying on it:

- **Watermark removal, OCR and face detection are stubs.** Their configuration
  sections (`watermark_removal`, `models`) ship in `settings.json` but nothing
  loads them. Face detection is delivered by a separate project that will be
  merged later and brings its own dependencies.
- **Several settings sections are inert** — see
  [Sections present in the file but not yet wired up](#sections-present-in-the-file-but-not-yet-wired-up).
  They are kept for forward compatibility, not because they do anything.
- **`filters.min_resolution` / `max_resolution` are not applied** during
  scanning, for the performance reason given above.
- **Similarity comparison is pairwise** within each candidate set. On very
  large libraries the comparison phase dominates the runtime; there is no
  BK-tree / multi-index-hashing acceleration yet.
- **`use_gpu` has no effect** — no GPU code path exists in this project.
- **Video is not implemented.** Main-menu item 2 says so plainly instead of
  pretending; video needs its own metadata source (duration/resolution/codec)
  and its own performance profile.
- **"Duplicate" means byte-identical, by design.** A Word document re-saved by
  another program, or an archive re-compressed with a different tool, holds the
  same content but different bytes and is therefore **not** reported. Detecting
  that would require format-aware parsing, which this beta does not attempt.
- **Non-image sections keep the OLDEST copy when no date exists**, using the
  file's modification time. Moving or copying such files updates that
  timestamp, so it can change which copy is treated as the original.

The remediation history — every audit finding fixed so far, with the reasoning
and the tests that pin it — is in [`CHANGELOG.md`](CHANGELOG.md).

---

## ملخّص بالعربية

أداة لتنظيف مكتبات الصور الضخمة: تكشف الصور **المكررة** و**المتشابهة**
و**التالفة** و**الصغيرة**، وتشرح سبب كل قرار في تقرير نصّي، ثم **تنقل** الصور
الخاسرة إلى `recycle-bin/` بدل حذفها.

- **لا يوجد حذف نهائي إطلاقًا.** كل ملف يُنقل إلى سلة المهملات مع الحفاظ على
  هيكل مجلداته، فيبقى قابلاً للاسترداد بايت‑ببايت.
- جرّب أولًا بوضع `safety.dry_run_mode` على `true` واقرأ التقرير قبل أي تنفيذ.
- الاختيار يعتمد افتراضيًا على: **التاريخ ثم الدقة ثم الحجم ثم الاسم** (قابل
  للتغيير من الإعدادات، والترتيب **يُحفظ بين الجلسات**). كل معيار يُقاس داخل
  المجموعة نفسها على مقياس موحّد 0‑10، والفروق الضئيلة (أقل من 5%، أو أقل من
  دقيقة في التواريخ، أو أقل من يوم عند وجود تاريخ من الاسم) لا تُحتسب قرارًا —
  والتقرير يذكر الفارق الموزون الفعلي وأي ميزة حقيقية للملف المحذوف، مع حارسَي
  أمان: «حدّ الجودة» يمنع الاحتفاظ بصورة مصغّرة وحذف الصورة الحقيقية، و«تحذير
  التضحية بالدقة» يُظهر في التقرير إن كان الملف المُبقَى أقل دقة من غيره.
- الواجهة والتقرير متوفران بالعربية والإنجليزية.
- أقسام **الأوفيس** بعائلاتها الكاملة: Word (doc, docx, docm, dot, dotx, dotm, rtf, odt, wps)
  وExcel (xls, xlsx, xlsm, xlt, xltx, ods, csv, tsv, et) وPowerPoint (ppt, pptx, pptm, pps,
  ppsx, pot, potx, odp, dps) وPDF/XPS (pdf, xps, oxps) وخيار خامس لما تبقّى (Visio وPublisher
  وOneNote وAccess وProject وiWork وOpenDocument) — 45 امتداداً في المجموع. و**الملفات
  المضغوطة** (zip, rar, 7z, tar, gz, bz2, xz) و**ملفات أخرى** (تكتب امتداداتها بنفسك):
  كشف التكرار بالمحتوى (SHA‑256) بعد فرز أولي بالحجم، ولا تُقارن إلا الملفات المتطابقة في
  الامتداد، والمكرر يُنقل إلى `recycle-bin/duplicates-office` (أو `duplicates-archives` /
  `duplicates-other`) مع تقرير خاص بكل قسم. قسم **الفيديو** ما زال «قريبًا» بصراحة.

**التشغيل:** `python main.py` — **التثبيت:** `install_requirements.bat` —
**الاختبارات:** `python tests/run_all.py`

---

## License

MIT — see [`LICENSE`](LICENSE).


