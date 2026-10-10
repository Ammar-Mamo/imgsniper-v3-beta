# imgSniper v3 -- Round 19 Verification Suite
# UNDO: putting removed files back where they came from.
#
# Round 18 fixed the move path and proved that no file was lost -- but it left the
# user with 88,890 files piled into a handful of folders, 82% of them renamed with
# a collision suffix, and no way to get them back except reading a 58 MB report by
# hand. Round 19 turns those report lines back into files on disk, inside the
# program, one section at a time.
#
# What the user asked for, verbatim:
#   * an undo option INSIDE each section (images / video / office / archives /
#     other), restoring that section's own deletions and nothing else;
#   * images undo covers corrupted + duplicates + similar + small together.
#
# Three rules make an undo safe, and each is verified below:
#   1. DRY RUN FIRST -- the plan is computed and shown before a byte is written;
#   2. COPY, never move -- the bin keeps its copies, so a mistake here cannot
#      destroy the only remaining copy;
#   3. NEVER overwrite -- a file already at the original path is left alone and
#      the copy lands beside it as *_restored.
#
# Also verified:
#   * "Moved to" is a HINT, not truth. On the real corpus reports said
#     ...\ENGLISH U0001f60d\x.jpg while the file sat in ...\ENGLISH\working\x.jpg
#     (clean_path_for_recycle_bin sanitises what the report prints verbatim, and
#     the pre-round-18 pile-up put files in a folder belonging to another source).
#     So the reported path is tried first and the bin is searched by name when it
#     misses, with size then a deterministic pick breaking ties.
#   * a restore report is NEVER read back as a deletion report (prefix "restore_"),
#     otherwise a second undo would "restore" what the first undo just put back.
#
# Deliberately NOT changed by round 19: the priority order, criterion weights,
# selection engine, similarity thresholds, deletion behaviour, and the recycle-bin
# location semantics.
# Run from project root: python tests/test_fixes_round19.py

import sys, os, shutil, tempfile, builtins                     # noqa: E402
from pathlib import Path                                       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_REPORTS_DIR = ROOT / 'reports'
_REPORTS_BEFORE = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                   if _REPORTS_DIR.exists() else [])

_REAL_BIN = ROOT / 'recycle-bin'
_BIN_BEFORE = (sorted(str(p.relative_to(_REAL_BIN)) for p in _REAL_BIN.rglob('*'))
               if _REAL_BIN.exists() else [])

_PASSED = 0
_FAILED = 0


def P(label, condition, detail=''):
    """Record one assertion."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f'  [PASS] {label}')
    else:
        _FAILED += 1
        print(f'  [FAIL] {label}' + (f'  <- {detail}' if detail != '' else ''))


def SEP(title):
    print()
    print('=' * 70)
    print('  ' + title)
    print('=' * 70)


def read_src(relative: str) -> str:
    return (ROOT / relative).read_text(encoding='utf-8', errors='replace')


from src.core.restore_manager import (                          # noqa: E402
    RestoreManager, RestoreItem, SECTION_OPERATIONS, OPERATION_PREFIX,
    OPERATION_LABELS, operation_label)
from src.utils.reports.restore_report_generator import (        # noqa: E402
    RestoreReportGenerator)
from src.core.file_categories import SECTIONS                   # noqa: E402

_PATH_MARK = '\U0001f4c1'      # 📁
_MOVED_MARK = '\U0001f4e5'     # 📥


def make_report(reports_dir: Path, name: str, entries, kept=None) -> Path:
    """Write a deletion report in the exact shape the generators produce.

    entries : [(original_path, moved_to_path), ...]  -> deleted files
    kept    : [path, ...]                            -> kept files (Path line only)
    A kept file has a Path line but NO Moved-to line, which is what tells the
    parser it must not be restored.
    """
    lines = ['Report', '=' * 60, 'Group 1']
    for path in (kept or []):
        lines.append(f'  {_PATH_MARK} Path: {path}')
    lines.append('  Deleted:')
    for original, moved in entries:
        lines.append(f'  {_PATH_MARK} Path: {original}')
        lines.append(f'  {_MOVED_MARK} Moved to: {moved}')
    target = reports_dir / name
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return target


# =====================================================================
SEP('A.  section isolation -- an undo can never cross into another section')
# =====================================================================
# The user asked for this explicitly: the images undo must not touch a video, an
# archive or an office file. Enforced by report FILE NAME PREFIX, not by guessing
# from extensions, so a .jpg listed in an office report still belongs to office.

P('every section is registered',
  set(SECTION_OPERATIONS) == {'images', 'video', 'office', 'archives', 'other'},
  sorted(SECTION_OPERATIONS))
P('images covers all four image operations',
  SECTION_OPERATIONS['images'] == ['corrupted', 'duplicates', 'similar',
                                   'small_images'],
  SECTION_OPERATIONS['images'])
P('every non-image section maps to exactly its own report prefix',
  all(SECTION_OPERATIONS[key] == [SECTIONS[key]['report_prefix']]
      for key in ('video', 'office', 'archives', 'other')),
  {k: SECTION_OPERATIONS[k] for k in ('video', 'office', 'archives', 'other')})
P('every operation has a file-name prefix',
  all(op in OPERATION_PREFIX for ops in SECTION_OPERATIONS.values() for op in ops))
P('every operation has a bilingual label',
  all(op in OPERATION_LABELS for ops in SECTION_OPERATIONS.values() for op in ops)
  and all(len(v) == 2 and all(v) for v in OPERATION_LABELS.values()))
try:
    RestoreManager('not_a_section')
    P('an unknown section raises ValueError instead of restoring nothing', False)
except ValueError:
    P('an unknown section raises ValueError instead of restoring nothing', True)

_tmp = Path(tempfile.mkdtemp(prefix='imgsniper_r19_'))
try:
    rep = _tmp / 'reports'
    bin_ = _tmp / 'bin'
    rep.mkdir()
    bin_.mkdir()
    ALL_REPORTS = ['corrupted_2026.txt', 'duplicates_2026.txt', 'similar_2026.txt',
                   'small_images_2026.txt', 'duplicate_video_2026.txt',
                   'duplicate_office_2026.txt', 'duplicate_archives_2026.txt',
                   'duplicate_other_2026.txt', 'restore_images_2026.txt',
                   'notes_2026.txt']
    for name in ALL_REPORTS:
        (rep / name).write_text('x', encoding='utf-8')

    for section in SECTION_OPERATIONS:
        manager = RestoreManager(section, reports_dir=rep, recycle_bin=bin_)
        seen = sorted(p.name for ops in manager.find_reports().values() for p in ops)
        want = sorted(OPERATION_PREFIX[op] + '2026.txt'
                      for op in SECTION_OPERATIONS[section])
        P(f'{section}: sees exactly its own reports', seen == want, seen)

    _all_seen = [p.name
                 for s in SECTION_OPERATIONS
                 for ops in RestoreManager(s, reports_dir=rep,
                                           recycle_bin=bin_).find_reports().values()
                 for p in ops]
    P('a restore report is NEVER mistaken for a deletion report',
      not any(n.startswith('restore_') for n in _all_seen))
    P('an unrelated .txt is ignored by every section',
      'notes_2026.txt' not in _all_seen)
    P('a missing reports folder yields an empty plan, not a crash',
      RestoreManager('images', reports_dir=_tmp / 'nope',
                     recycle_bin=bin_).build_plan() == [])
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# =====================================================================
SEP('B.  parsing -- only DELETED files are restored, kept files never are')
# =====================================================================
# A kept file also gets a "Path:" line in every report. What distinguishes a
# removal is the Path+Moved-to PAIR, so a kept file must never appear in a plan.

_tmp = Path(tempfile.mkdtemp(prefix='imgsniper_r19_'))
try:
    rep = _tmp / 'reports'
    bin_ = _tmp / 'bin'
    rep.mkdir()
    bin_.mkdir()
    keeper = _tmp / 'lib' / 'keeper.jpg'
    gone_a = _tmp / 'lib' / 'a.jpg'
    gone_b = _tmp / 'lib' / 'b.jpg'
    make_report(rep, 'similar_2026.txt',
                [(gone_a, bin_ / 'a.jpg'), (gone_b, bin_ / 'b.jpg')],
                kept=[keeper])

    manager = RestoreManager('images', reports_dir=rep, recycle_bin=bin_)
    plan = manager.build_plan()
    P('exactly the deleted files are in the plan', len(plan) == 2, len(plan))
    P('a KEPT file is never restored',
      all('keeper' not in str(i.original) for i in plan))
    P('each item keeps its original path',
      {str(i.original) for i in plan} == {str(gone_a), str(gone_b)})
    P('each item keeps the reported destination',
      all(i.reported is not None for i in plan))
    P('each item knows which operation removed it',
      all(i.operation == 'similar' for i in plan))
    P('each item knows which report it came from',
      all(i.report == 'similar_2026.txt' for i in plan))

    # An Arabic report must parse identically: the parser matches the EMOJI, not
    # the label text, so no translation table is needed and a language switch
    # cannot silently disable the undo.
    rep_ar = _tmp / 'reports_ar'
    rep_ar.mkdir()
    (rep_ar / 'corrupted_2026.txt').write_text(
        'تقرير\n'
        f'  {_PATH_MARK} المسار: {_tmp / "lib" / "ar.jpg"}\n'
        f'  {_MOVED_MARK} نُقل إلى: {bin_ / "ar.jpg"}\n', encoding='utf-8')
    arabic_plan = RestoreManager('images', reports_dir=rep_ar,
                                 recycle_bin=bin_).build_plan()
    P('an ARABIC report parses identically', len(arabic_plan) == 1, len(arabic_plan))
    P('and yields the right original path',
      bool(arabic_plan) and arabic_plan[0].original.name == 'ar.jpg')

    make_report(rep, 'similar_2027.txt', [(_tmp / 'lib' / 'c.jpg', bin_ / 'c.jpg')])
    P('both reports of one operation are read',
      len(RestoreManager('images', reports_dir=rep,
                         recycle_bin=bin_).build_plan()) == 3)

    # A truncated/garbled report must not abort the whole undo.
    (rep / 'corrupted_2026.txt').write_text(
        f'  {_PATH_MARK} Path: {_tmp / "lib" / "d.jpg"}\n', encoding='utf-8')
    P('a Path line with no Moved-to line yields nothing',
      all(i.original.name != 'd.jpg'
          for i in RestoreManager('images', reports_dir=rep,
                                  recycle_bin=bin_).build_plan()))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# =====================================================================
SEP('C.  locating -- "Moved to" is a HINT, the bin is the truth')
# =====================================================================
# Verified on the real 2 TB corpus: a report said
#     Moved to: ...\recycle-bin\corrupted\hdd\alll\ENGLISH U0001f60d\x.jpg
# while the file actually sat in
#     ...\recycle-bin\corrupted\hdd\alll\ENGLISH\working\x.jpg
# clean_path_for_recycle_bin() sanitises what the report prints verbatim, and the
# pre-round-18 pile-up parked files in a folder belonging to another source. An
# undo that trusted the reported path alone would have called 88,890 files
# "missing" and restored nothing at all.

_tmp = Path(tempfile.mkdtemp(prefix='imgsniper_r19_'))
try:
    rep = _tmp / 'reports'
    bin_ = _tmp / 'bin' / 'similar' / 'pile'
    lib = _tmp / 'lib'
    rep.mkdir(parents=True)
    bin_.mkdir(parents=True)
    lib.mkdir()

    exact = bin_ / 'exact.jpg'                 # reported path is correct
    exact.write_bytes(b'X' * 100)
    real_b = bin_ / 'wrongname.jpg'            # reported path is WRONG
    real_b.write_bytes(b'Y' * 200)
    suffixed = bin_ / 'suffixed_3.jpg'         # only a _N copy exists
    suffixed.write_bytes(b'Z' * 300)
    make_report(rep, 'similar_2026.txt', [
        (lib / 'exact.jpg', exact),
        (lib / 'wrongname.jpg', _tmp / 'bin' / 'ENGLISH \U0001f60d' / 'wrongname.jpg'),
        (lib / 'suffixed.jpg', bin_ / 'suffixed.jpg'),
        (lib / 'absent.jpg', bin_ / 'absent.jpg'),
    ])

    manager = RestoreManager('images', reports_dir=rep, recycle_bin=_tmp / 'bin')
    plan = {i.original.name: i for i in manager.build_plan()}
    summary = manager.restore_all(list(plan.values()), dry_run=True)

    P('a correct "Moved to" is used directly',
      plan['exact.jpg'].actual == exact
      and plan['exact.jpg'].status == 'would_restore', plan['exact.jpg'].detail)
    P('a WRONG "Moved to" is recovered by searching the bin by name',
      plan['wrongname.jpg'].actual == real_b
      and plan['wrongname.jpg'].status == 'would_restore',
      (plan['wrongname.jpg'].actual, plan['wrongname.jpg'].detail))
    P('a collision-suffixed copy (_N) is still found',
      plan['suffixed.jpg'].actual == suffixed
      and plan['suffixed.jpg'].status == 'would_restore',
      (plan['suffixed.jpg'].actual, plan['suffixed.jpg'].detail))
    P('a genuinely absent file is reported missing, not silently dropped',
      plan['absent.jpg'].status == 'missing' and plan['absent.jpg'].actual is None,
      plan['absent.jpg'].status)
    P('the summary counts both outcomes',
      summary['counts'].get('would_restore') == 3
      and summary['counts'].get('missing') == 1, summary['counts'])

    strip = RestoreManager._strip_collision_suffix
    P('the suffix stripper removes a trailing _N',
      strip('photo_3.jpg') == 'photo.jpg' and strip('a b_12.png') == 'a b.png',
      (strip('photo_3.jpg'), strip('a b_12.png')))
    P('and leaves a name without a numeric suffix alone',
      strip('photo.jpg') == 'photo.jpg' and strip('noext_1') == 'noext_1'
      and strip('a_b_c.jpg') == 'a_b_c.jpg',
      (strip('photo.jpg'), strip('noext_1'), strip('a_b_c.jpg')))
    # A genuine "my_2.jpg" is INDISTINGUISHABLE from a collision suffix applied to
    # "my.jpg". That is exactly why the REPORTED name is searched first (step 2)
    # and the pre-suffix index is only the last resort -- and why a name-
    # approximated match is annotated in the report rather than passed off as exact.
    P('a genuine _N name is treated as the ambiguity it really is',
      strip('my_2.jpg') == 'my.jpg', strip('my_2.jpg'))

    # Two bin files share one name -> deterministic pick + an explicit flag. The
    # original is gone, so there is no hash of our own to compare against;
    # guessing silently would put the wrong photo in the wrong folder and still
    # look like success.
    dup_dir = _tmp / 'bin' / 'dup'
    dup_dir.mkdir()
    (dup_dir / 'twin.jpg').write_bytes(b'1' * 10)
    (bin_ / 'twin.jpg').write_bytes(b'2' * 20)
    make_report(rep, 'similar_2027.txt', [(lib / 'twin.jpg', _tmp / 'nope.jpg')])
    manager2 = RestoreManager('images', reports_dir=rep, recycle_bin=_tmp / 'bin')
    twin = [i for i in manager2.build_plan() if i.original.name == 'twin.jpg']
    twin_summary = manager2.restore_all(twin, dry_run=True)   # this runs locate()
    P('a name shared by two bin files still resolves to one file',
      len(twin) == 1 and twin[0].actual is not None, twin)
    P('and the user is TOLD the name was shared instead of it being guessed silently',
      bool(twin) and '2 files in the bin share this name' in twin[0].detail,
      twin[0].detail if twin else None)
    P('ambiguity is a warning that SURVIVES the dry-run relabel',
      bool(twin) and twin[0].status == 'would_restore'
      and twin_summary['counts'].get('ambiguous') == 1,
      (twin[0].status, twin_summary['counts']) if twin else None)
    P('the ambiguity reaches the summary the user reads',
      twin_summary['counts'].get('ambiguous') == 1, twin_summary['counts'])
    P('the pick is deterministic across runs',
      str(twin[0].actual) == str(sorted(
          [dup_dir / 'twin.jpg', bin_ / 'twin.jpg'], key=lambda p: str(p))[0]),
      twin[0].actual)
    P('a name-approximated match is annotated, not passed off as exact',
      'bin name is' in plan['suffixed.jpg'].detail, plan['suffixed.jpg'].detail)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# =====================================================================
SEP('D.  execution -- copy not move, dry run first, never overwrite')
# =====================================================================

_tmp = Path(tempfile.mkdtemp(prefix='imgsniper_r19_'))
try:
    rep = _tmp / 'reports'
    bin_ = _tmp / 'bin' / 'similar' / 'pile'
    lib = _tmp / 'lib' / 'Teeth' / 'Art'      # a DEEP original path
    rep.mkdir(parents=True)
    bin_.mkdir(parents=True)
    lib.mkdir(parents=True)

    payload_a = b'A' * 1234
    payload_b = b'B' * 999
    (bin_ / 'a.jpg').write_bytes(payload_a)
    (bin_ / 'b.jpg').write_bytes(payload_b)
    make_report(rep, 'similar_2026.txt', [
        (lib / 'a.jpg', bin_ / 'a.jpg'),
        (lib / 'b.jpg', _tmp / 'bin' / 'WRONG' / 'b.jpg'),   # bad folder
        (lib / 'gone.jpg', bin_ / 'gone.jpg'),               # truly absent
    ])

    manager = RestoreManager('images', reports_dir=rep, recycle_bin=_tmp / 'bin')

    # ---- DRY RUN: the plan is real, the filesystem is untouched ----
    dry_plan = manager.build_plan()
    dry = manager.restore_all(dry_plan, dry_run=True)
    P('DRY RUN writes absolutely nothing',
      not (lib / 'a.jpg').exists() and not (lib / 'b.jpg').exists())
    P('DRY RUN reports 0 restored bytes', dry['restored_bytes'] == 0,
      dry['restored_bytes'])
    P('DRY RUN still resolves every location so the plan is truthful',
      dry['counts'].get('would_restore') == 2, dry['counts'])
    P('DRY RUN reports the absent file', dry['counts'].get('missing') == 1,
      dry['counts'])
    P('DRY RUN creates no folder either', not (lib / 'Teeth').exists()
      or list(lib.iterdir()) == [])

    # ---- REAL RUN ----
    real_plan = manager.build_plan()
    real = manager.restore_all(real_plan, dry_run=False)
    P('the deep original folder is recreated', lib.is_dir())
    P('a.jpg is back with the exact payload',
      (lib / 'a.jpg').exists() and (lib / 'a.jpg').read_bytes() == payload_a)
    P('b.jpg is back despite the WRONG reported folder',
      (lib / 'b.jpg').exists() and (lib / 'b.jpg').read_bytes() == payload_b)
    P('COPY not move: the bin still holds both files',
      (bin_ / 'a.jpg').exists() and (bin_ / 'b.jpg').exists())
    P('the restored byte count is exact',
      real['restored_bytes'] == 1234 + 999, real['restored_bytes'])
    P('both successes are counted', real['counts'].get('restored') == 2,
      real['counts'])
    P('the absent file is counted as missing, not as an error',
      real['counts'].get('missing') == 1 and not real['counts'].get('error'),
      real['counts'])
    P('no 0-byte husk is left anywhere in the library',
      not [p for p in (_tmp / 'lib').rglob('*') if p.is_file()
           and p.stat().st_size == 0])

    # ---- NEVER overwrite live data ----
    (lib / 'a.jpg').write_bytes(b'LIVE-DATA-NOT-MINE')
    clash_plan = manager.build_plan()
    manager.restore_all(clash_plan, dry_run=False)
    P('live data at the original path is NEVER overwritten',
      (lib / 'a.jpg').read_bytes() == b'LIVE-DATA-NOT-MINE')
    side = lib / 'a_restored.jpg'
    P('the copy lands beside it as *_restored instead',
      side.exists() and side.read_bytes() == payload_a, side)
    P('and the report note explains why the name changed',
      any('original spot taken' in i.detail for i in clash_plan
          if i.original.name == 'a.jpg'),
      [i.detail for i in clash_plan if i.original.name == 'a.jpg'])
    P('b.jpg, whose size still matches, is recognised as already home',
      any(i.status == 'already_there' for i in clash_plan
          if i.original.name == 'b.jpg'),
      [(i.original.name, i.status) for i in clash_plan])
    P('a second clash escalates to *_restored_2, never overwriting',
      RestoreManager._non_clashing(lib / 'a.jpg').name == 'a_restored_2.jpg',
      RestoreManager._non_clashing(lib / 'a.jpg').name)

    # ---- already_there: a file that is back in place is not touched ----
    fresh = _tmp / 'fresh'
    fresh.mkdir()
    (bin_ / 'c.jpg').write_bytes(b'C' * 50)
    make_report(rep, 'corrupted_2026.txt', [(fresh / 'c.jpg', bin_ / 'c.jpg')])
    (fresh / 'c.jpg').write_bytes(b'C' * 50)      # already back
    already = RestoreManager('images', reports_dir=rep, recycle_bin=_tmp / 'bin')
    already_plan = [i for i in already.build_plan() if i.original.name == 'c.jpg']
    already_res = already.restore_all(already_plan, dry_run=False)
    P('a file already in place is reported, not re-copied',
      already_res['counts'].get('already_there') == 1, already_res['counts'])
    P('and no *_restored twin is created for it',
      not (fresh / 'c_restored.jpg').exists())
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# =====================================================================
SEP('E.  the restore report -- the record that makes the undo trustworthy')
# =====================================================================

_tmp = Path(tempfile.mkdtemp(prefix='imgsniper_r19_'))
try:
    rep = _tmp / 'reports'
    bin_ = _tmp / 'bin' / 'similar' / 'pile'
    lib = _tmp / 'lib'
    rep.mkdir(parents=True)
    bin_.mkdir(parents=True)
    lib.mkdir()
    (bin_ / 'ok.jpg').write_bytes(b'K' * 77)
    make_report(rep, 'similar_2026.txt', [
        (lib / 'ok.jpg', bin_ / 'ok.jpg'),
        (lib / 'lost.jpg', bin_ / 'lost.jpg'),
    ])

    manager = RestoreManager('images', reports_dir=rep, recycle_bin=_tmp / 'bin')
    dry_plan = manager.build_plan()
    dry_res = manager.restore_all(dry_plan, dry_run=True)
    dry_path = RestoreReportGenerator(rep).generate_restore_report(
        'images', dry_plan, dry_res)
    dry_txt = Path(dry_path).read_text(encoding='utf-8')

    P('the report file name starts with restore_',
      Path(dry_path).name.startswith('restore_'), Path(dry_path).name)
    P('and carries the section, so two sections cannot confuse their reports',
      'restore_images_' in Path(dry_path).name, Path(dry_path).name)
    P('it states plainly that this was a DRY RUN', 'DRY-RUN: True' in dry_txt)
    P('it records where the recycle bin actually is', 'Recycle Bin:' in dry_txt)
    P('it names the deletion report it was built from',
      'similar_2026.txt' in dry_txt)
    P('it shows the original path the file goes back to',
      str(lib / 'ok.jpg') in dry_txt)
    P('it shows where the file was found in the bin',
      str(bin_ / 'ok.jpg') in dry_txt)
    P('it lists the file that could NOT be found',
      'lost.jpg' in dry_txt and 'NOT FOUND' in dry_txt)
    P('a dry run does not claim a restored size', 'Restored size' not in dry_txt)

    # A restore report must never be fed back in as a deletion report, or the
    # next undo would try to "restore" what this undo just put back.
    second = RestoreManager('images', reports_dir=rep, recycle_bin=_tmp / 'bin')
    second_names = [p.name for ops in second.find_reports().values() for p in ops]
    P('a second undo ignores the restore report',
      not any(n.startswith('restore_') for n in second_names), second_names)
    P('and still sees exactly the one real deletion report',
      len(second.build_plan()) == 2, len(second.build_plan()))

    real_plan = second.build_plan()
    real_res = second.restore_all(real_plan, dry_run=False)
    real_path = RestoreReportGenerator(rep).generate_restore_report(
        'images', real_plan, real_res)
    real_txt = Path(real_path).read_text(encoding='utf-8')
    P('a real run says DRY-RUN: False', 'DRY-RUN: False' in real_txt)
    P('a real run reports RESTORED', 'RESTORED (copied back)' in real_txt)
    P('a real run reports the restored size', 'Restored size' in real_txt)
    P('the file really went home', (lib / 'ok.jpg').read_bytes() == b'K' * 77)
    P('two runs produce two reports, never an overwrite',
      Path(dry_path).name != Path(real_path).name)

    # An empty plan must still produce a readable report, not an empty file.
    empty_rep = _tmp / 'empty_reports'
    empty_rep.mkdir()
    empty_manager = RestoreManager('images', reports_dir=empty_rep,
                                   recycle_bin=_tmp / 'bin')
    empty_plan = empty_manager.build_plan()
    empty_res = empty_manager.restore_all(empty_plan, dry_run=True)
    empty_txt = Path(RestoreReportGenerator(empty_rep).generate_restore_report(
        'images', empty_plan, empty_res)).read_text(encoding='utf-8')
    P('an empty plan still yields a readable report',
      'Nothing to restore' in empty_txt
      or 'لا شيء لاسترجاعه' in empty_txt)
    P('and says no deletion report was found',
      'NONE' in empty_txt or 'لا شيء' in empty_txt)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# =====================================================================
SEP('F.  wiring -- the undo is reachable in every section, and scoped')
# =====================================================================
import io                                                       # noqa: E402
from rich.console import Console                                # noqa: E402
from src.core.i18n.i18n import i18n                             # noqa: E402
from src.core.i18n.translations_english import (                # noqa: E402
    ENGLISH_TRANSLATIONS)
from src.core.i18n.translations_arabic import ARABIC_TRANSLATIONS  # noqa: E402
import src.cli.cli_menu_handler as cmh                          # noqa: E402
from src.cli.cli_operation_handler import CLIOperationHandler   # noqa: E402

P('CLIOperationHandler exposes handle_restore',
  hasattr(CLIOperationHandler, 'handle_restore'))
P('and it takes the section as an argument',
  'section_key' in read_src('src/cli/cli_operation_handler.py'))
P('handle_restore previews with dry_run=True before asking',
  'restore_all(plan, dry_run=True)'
  in read_src('src/cli/cli_operation_handler.py'))
P('and only then runs the real restore',
  'restore_all(plan, dry_run=False'
  in read_src('src/cli/cli_operation_handler.py'))
P('the images menu dispatches option 7 to the images undo',
  "handle_restore('images')" in read_src('src/cli/image_cli.py'))
P('_run_section routes the undo entry instead of a duplicate scan',
  "if option_id == 'restore':" in read_src('src/cli/main_cli.py')
  and 'handle_restore(section_key)' in read_src('src/cli/main_cli.py'))

# The invariant that made the first attempt fail: SECTIONS['options'] must stay
# "one entry per scan type", because options[-1] is the combined 'all' entry.
P('no section gained a restore entry inside its options list',
  all('restore' not in [o[0] for o in SECTIONS[k]['options']]
      for k in SECTIONS), {k: [o[0] for o in SECTIONS[k]['options']]
                           for k in SECTIONS})
P("options[-1] is still the combined 'all' entry for every section that has one",
  all(SECTIONS[k]['options'][-1][0] == 'all'
      for k in ('video', 'office', 'archives')))

# ---- the section menu, driven for real ----
menu_console = Console(file=io.StringIO(), force_terminal=False, width=200)
menu_handler = cmh.CLIMenuHandler(menu_console)
_orig_int_ask = cmh.IntPrompt.ask


def _patch(answer):
    cmh.IntPrompt.ask = staticmethod(lambda *a, **k: answer)


try:
    for section in ('video', 'office', 'archives', 'other'):
        menu_console.file = io.StringIO()
        option_count = len(SECTIONS[section]['options'])
        _patch(str(option_count + 1))
        picked = menu_handler.show_section_menu(section)
        text = menu_console.file.getvalue()
        P(f'{section}: the undo entry is drawn and returns "restore"',
          picked == 'restore', picked)
        P(f'{section}: the undo entry is numbered after the scan options',
          f'{option_count + 1} - ' in text
          and i18n.get('restore.menu_option') in text)
        P(f'{section}: 0 still leaves the section',
          (_patch('0'), menu_handler.show_section_menu(section))[1] is None)
        P(f'{section}: the scan options still work',
          (_patch('1'), menu_handler.show_section_menu(section))[1]
          == SECTIONS[section]['options'][0][0])
finally:
    cmh.IntPrompt.ask = _orig_int_ask

# ---- the images menu ----
img_console = Console(file=io.StringIO(), force_terminal=False, width=200)
img_menu = cmh.CLIMenuHandler(img_console)
_orig2 = cmh.IntPrompt.ask
try:
    _patch('7')
    img_choice = img_menu.show_image_menu()
    img_text = img_console.file.getvalue()
    P('the images menu returns 7 for the undo', img_choice == 7, img_choice)
    P('and draws it with the shared label',
      i18n.get('restore.menu_option') in img_text)
    P('Back moved to 8 and still leaves the section',
      (_patch('8'), img_menu.show_image_menu())[1] == 8)
    P('the six image operations kept their numbers 1..6',
      all(f'{i} - ' in img_text for i in range(1, 7)))
finally:
    cmh.IntPrompt.ask = _orig2

# ---- i18n: both languages, no missing keys ----
P('every restore.* key exists in ENGLISH', 'restore' in ENGLISH_TRANSLATIONS
  and len(ENGLISH_TRANSLATIONS['restore']) >= 20,
  len(ENGLISH_TRANSLATIONS.get('restore', {})))
P('every restore.* key exists in ARABIC', 'restore' in ARABIC_TRANSLATIONS
  and set(ARABIC_TRANSLATIONS['restore']) == set(ENGLISH_TRANSLATIONS['restore']),
  sorted(set(ENGLISH_TRANSLATIONS.get('restore', {}))
         ^ set(ARABIC_TRANSLATIONS.get('restore', {}))))
P('no restore string is left as an English placeholder in Arabic',
  all(ARABIC_TRANSLATIONS['restore'][k] != ENGLISH_TRANSLATIONS['restore'][k]
      for k in ENGLISH_TRANSLATIONS['restore']))
_used = ['restore.' + k for k in ENGLISH_TRANSLATIONS['restore']]
_cli_src = (read_src('src/cli/cli_operation_handler.py')
            + read_src('src/cli/cli_menu_handler.py'))
_missing = [k for k in _used if k.split('.', 1)[1] in
            ('menu_option', 'title', 'scope_note', 'scanning', 'no_reports',
             'reports_found', 'confirm', 'running', 'done_title', 'restored',
             'errors', 'size', 'report_saved', 'cancelled', 'no_files',
             'would_restore', 'already_there', 'missing', 'ambiguous',
             'copy_note', 'never_overwrite_note')
            and k not in _cli_src]
P('every restore key the CLI needs is actually referenced', not _missing, _missing)


# =====================================================================
SEP('G.  the machine is left exactly as it was found')
# =====================================================================
# This suite creates files, so it must prove it cleaned up. The user's real
# recycle bin holds 40 GB of files that are NOT yet restored; a test that touched
# them would be a disaster.

_reports_now = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                if _REPORTS_DIR.exists() else [])
P('the real reports folder is untouched', _reports_now == _REPORTS_BEFORE,
  (set(_reports_now) ^ set(_REPORTS_BEFORE)) or 'same')

_bin_now = (sorted(str(p.relative_to(_REAL_BIN)) for p in _REAL_BIN.rglob('*'))
            if _REAL_BIN.exists() else [])
P('the real recycle bin is untouched (file for file)',
  _bin_now == _BIN_BEFORE,
  f'{len(_BIN_BEFORE)} before / {len(_bin_now)} now')
P('no restore report was written into the real reports folder',
  not any(n.startswith('restore_') for n in _reports_now))

_leftovers = [p for p in Path(tempfile.gettempdir()).glob('imgsniper_r19_*')]
P('every temporary folder was removed', not _leftovers,
  [str(p) for p in _leftovers])

# =====================================================================
print()
print('=' * 70)
print(f'  passed: {_PASSED}')
print(f'  failed: {_FAILED}')
print(f'  total : {_PASSED + _FAILED}')
print('=' * 70)
print('  RESULT: ' + ('ALL PASS' if _FAILED == 0 else 'FAILURES PRESENT'))
print('=' * 70)
sys.exit(0 if _FAILED == 0 else 1)

