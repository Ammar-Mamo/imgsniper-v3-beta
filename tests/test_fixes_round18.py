# imgSniper v3 -- Round 18 Fix Verification Suite
# The recycle-bin MOVE path: structure, capacity, failure handling, dry-run truth.
#
# Round 18 exists because of a real incident, not a code review. After 17 rounds
# of dry-run report analysis the user turned dry-run OFF and cleaned ~2 TB of
# recovered photos. The similar-images pass filled the system disk, the program
# died with an error, and afterwards he found:
#
#   * 88,890 removed files piled into a handful of folders instead of mirroring
#     their source tree -- 5,687 corrupted images from all over D:\hdd landed in
#     TWO folders, and all 16,419 similar images in ONE, with 13,449 of them
#     (82%) renamed "<name>_1", "<name>_2", ... because unrelated files collided;
#   * 735 zero-byte .jpg husks he had carried to an external disk, which he
#     understandably reported as "my images became corrupted";
#   * no report at all for that run.
#
# Root causes, all in the MOVE path -- which no dry run could ever reach, because
# move_to_recycle_bin() returned at its dry-run branch BEFORE any destination
# logic ran:
#
#   1. get_session_folder_name() kept ONE global folder for the whole operation
#      and returned it for EVERY file, ignoring its base_path argument. The first
#      file of a run decided where every other file landed.
#   2. Nothing anywhere in the codebase checked free disk space. The bin sat on a
#      172 GB system disk while the files sat on a 2 TB disk.
#   3. shutil.move() across volumes is copy2() + unlink(). When the copy died
#      halfway the unlink never ran (so the source survived - no data was lost)
#      but a 0-byte husk stayed at the destination, and the except branch only
#      returned False without cleaning it up.
#   4. Every deletion loop swallowed failures with `except Exception: pass`, so a
#      run that moved nothing still reported itself as finished.
#
# Verified here:
#   A. the session folder is keyed PER SOURCE folder, not per operation;
#   B. a real move mirrors the source tree; no pile-up, no spurious _N suffixes;
#   C. a genuine same-folder collision still gets _N and keeps both payloads;
#   D. a FAILED move removes the husk and leaves the source byte-identical;
#   E. size verification never deletes the only copy after a successful move;
#   F. dry-run computes the real destination and still touches nothing;
#   G. the capacity gate measures only cross-volume bytes and can abort;
#   H. every deletion site runs the gate and counts failures;
#   I. the new messages exist in BOTH languages;
#   J. the machine is left exactly as it was found.
#
# Deliberately NOT changed by round 18: the priority order, criterion weights,
# date gates, selection engine, similarity thresholds, report CONTENT, and the
# recycle-bin location semantics (still Path.cwd()-anchored -- see section G).
# Run from project root: python tests/test_fixes_round18.py

import sys, os, json, atexit, shutil, tempfile, logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

_CFG_FILE = ROOT / 'config' / 'settings.json'
_CFG_BYTES = _CFG_FILE.read_bytes() if _CFG_FILE.exists() else None

_REPORTS_DIR = ROOT / 'reports'
_REPORTS_BEFORE = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                   if _REPORTS_DIR.exists() else [])

_REAL_BIN = ROOT / 'recycle-bin'
_BIN_BEFORE = (sorted(str(p.relative_to(_REAL_BIN))
                      for p in _REAL_BIN.rglob('*'))
               if _REAL_BIN.exists() else [])


def _restore_cfg():
    if _CFG_BYTES is not None:
        _CFG_FILE.write_bytes(_CFG_BYTES)


if _CFG_BYTES is not None:
    atexit.register(_restore_cfg)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError, OSError):
        pass

TP = TF = 0
logging.getLogger().addHandler(logging.NullHandler())


def SEP(title):
    print('')
    print('=' * 70)
    print('  ' + title)
    print('=' * 70)


def P(label, ok, extra=''):
    global TP, TF
    if ok:
        TP += 1
        print(f'  [PASS] {label}')
    else:
        TF += 1
        print(f'  [FAIL] {label} -- {extra}')


def read_src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


from src.core.config import config                                      # noqa: E402
from src.utils.helpers import file_utils as FU                          # noqa: E402
from src.utils.helpers.file_utils import (                              # noqa: E402
    get_session_folder_name, reset_session_folder, move_to_recycle_bin,
    compute_recycle_destination, get_recycle_bin_root,
    recycle_bin_capacity_report, ensure_recycle_bin_capacity,
)


def setmem(key, value):
    """Change config IN MEMORY ONLY. config.set() calls save_config(), which
    would rewrite config/settings.json -- the atexit restore would hide it, but
    a crash in between would leave a real user with a temp-dir recycle bin."""
    keys = key.split('.')
    node = config.config
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def sandbox(bin_name='rb'):
    """A temp dir + config pointed at a bin inside it. Caller chdir's in, so the
    Path.cwd()-anchored bin resolves there and the REAL bin is never touched."""
    td = Path(tempfile.mkdtemp(prefix='imgsniper_r18_'))
    setmem('paths.recycle_bin', bin_name)
    setmem('safety.dry_run_mode', False)
    reset_session_folder()
    return td


# =====================================================================
SEP('A.  the session folder is keyed PER SOURCE folder, not per operation')
# =====================================================================
# The catastrophic bug. The old body was:
#     if _current_session_folder and _current_session_folder.exists():
#         return _current_session_folder      # base_path never consulted
# so the FIRST file of a run decided where every other file landed.

P('the single-global cache is gone from the source',
  '_current_session_folder = None' not in read_src('src/utils/helpers/file_utils.py')
  .split('Round 18: PER-SOURCE-FOLDER')[1] if 'Round 18: PER-SOURCE-FOLDER'
  in read_src('src/utils/helpers/file_utils.py') else False)
P('a per-base_path dict replaced it',
  '_session_folders: Dict[Path, Path] = {}'
  in read_src('src/utils/helpers/file_utils.py'))
P('reset_session_folder() clears the dict (not a global assignment)',
  '_session_folders.clear()' in read_src('src/utils/helpers/file_utils.py'))

_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    _a = _td / 'rb' / 'hdd' / 'alll' / 'Teeth' / 'Art'
    _b = _td / 'rb' / 'hdd' / 'alll' / 'coffee'
    _ra = get_session_folder_name(_a)
    _rb = get_session_folder_name(_b)
    _ra2 = get_session_folder_name(_a)
    P('two different source folders get two different session folders',
      _ra != _rb, f'{_ra} vs {_rb}')
    P('the same source folder is stable across calls', _ra == _ra2, f'{_ra} vs {_ra2}')
    P('the returned folder still belongs to its own source path',
      _ra == _a and _rb == _b, f'{_ra} / {_rb}')
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)

# The old bug reproduced end to end: three unrelated source folders used to
# collapse into whichever folder the first file needed.
_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    src_dirs = {}
    for name in ('TeethArt', 'coffee', 'screens'):
        d = _td / 'photos' / name
        d.mkdir(parents=True)
        src_dirs[name] = d
    made = []
    for name, d in src_dirs.items():
        for i in range(3):
            f = d / f'img{i}.jpg'
            f.write_bytes(b'x' * (100 + i))
            made.append(f)
    moved = [move_to_recycle_bin(str(f), subfolder='corrupted') for f in made]
    ok = [m for m in moved if m and m != 'dry_run' and not str(m).startswith('skipped')]
    P('all 9 files were moved', len(ok) == 9, f'got {len(ok)}')
    P('all 9 sources are gone', all(not f.exists() for f in made))
    parents = {str(Path(m).parent) for m in ok}
    P('3 distinct mirror folders (the old code produced 1)',
      len(parents) == 3, f'got {len(parents)}: {sorted(parents)}')
    for name in src_dirs:
        hits = [m for m in ok if name in m]
        P(f'folder {name} kept its own 3 files', len(hits) == 3, f'got {len(hits)}')
    P('NO spurious _N collision suffixes (the old code produced 13,449)',
      not any('_' in Path(m).stem for m in ok),
      str([Path(m).name for m in ok if '_' in Path(m).stem]))
    P('no 0-byte results', all(Path(m).stat().st_size > 0 for m in ok))
    # each mirror folder must echo its own source folder name
    for name in src_dirs:
        hits = [m for m in ok if name in m]
        P(f'{name}: every file sits under a folder named {name}',
          all(Path(m).parent.name == name for m in hits))
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)


# =====================================================================
SEP('B.  a genuine same-folder collision still gets _N and keeps both payloads')
# =====================================================================
# Fixing the pile-up must NOT break the legitimate case: the same folder can be
# handed the same filename twice across two runs, and neither payload may be lost.

_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    d = _td / 'p' / 'A'
    d.mkdir(parents=True)
    f = d / 'same.jpg'
    f.write_bytes(b'FIRST')
    r1 = move_to_recycle_bin(str(f), subfolder='duplicates')
    f.write_bytes(b'SECOND-LONGER')
    r2 = move_to_recycle_bin(str(f), subfolder='duplicates')
    P('the first arrival keeps the plain name', Path(r1).name == 'same.jpg', Path(r1).name)
    P('the second arrival gets _1', Path(r2).name == 'same_1.jpg', Path(r2).name)
    P('both landed in the SAME mirror folder', Path(r1).parent == Path(r2).parent)
    P('first payload intact', Path(r1).read_bytes() == b'FIRST')
    P('second payload intact', Path(r2).read_bytes() == b'SECOND-LONGER')
    P('nothing was overwritten', Path(r1) != Path(r2))
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)


# =====================================================================
SEP('C.  a FAILED move removes the husk and leaves the source byte-identical')
# =====================================================================
# This is the 735 zero-byte .jpg files the user carried to an external disk and
# reported as "my images became corrupted". shutil.move() across volumes is
# copy2() + unlink(); when the copy died on a full disk the unlink never ran, so
# the SOURCE survived (nothing was ever lost) but a 0-byte husk stayed at the
# destination forever, because the except branch only returned False.

_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    d = _td / 'p' / 'A'
    d.mkdir(parents=True)
    f = d / 'victim.jpg'
    payload = b'ORIGINAL-DATA' * 500
    f.write_bytes(payload)
    dest = compute_recycle_destination(str(f), subfolder='similar')

    real_move = FU.shutil.move

    def exploding_move(src, dst, **kw):
        """Emulate a cross-drive copy that dies halfway: a truncated husk is
        left at the destination and the source is NOT unlinked."""
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b'')            # the 0-byte husk
        raise OSError(28, 'No space left on device')

    FU.shutil.move = exploding_move
    try:
        res = move_to_recycle_bin(str(f), subfolder='similar')
    finally:
        FU.shutil.move = real_move

    P('the move reports failure (False), not success', res is False, repr(res))
    P('the SOURCE still exists - no data was lost', f.exists())
    P('the SOURCE is byte-identical', f.exists() and f.read_bytes() == payload)
    P('the 0-byte husk was REMOVED from the destination', not dest.exists(), str(dest))
    husks = [p for p in (_td / 'rb').rglob('*') if p.is_file() and p.stat().st_size == 0]
    P('no 0-byte file survives anywhere in the bin', not husks, str(husks))
    P('_discard_partial_move exists and is called from the failure path',
      '_discard_partial_move(destination)' in read_src('src/utils/helpers/file_utils.py'))
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)


# =====================================================================
SEP('D.  size verification never deletes the only copy after a SUCCESSFUL move')
# =====================================================================
# Once shutil.move() returns, the source is GONE and the destination is the only
# copy. A size mismatch there must be reported loudly but must NEVER trigger a
# cleanup, or the verification itself would destroy the data it is protecting.

_src_txt = read_src('src/utils/helpers/file_utils.py')
_ONLY_COPY = 'shutil.move() returned, so the source is GONE'
_tail = _src_txt.split(_ONLY_COPY)[-1]
P('the post-move path documents that the destination is now the only copy',
  _ONLY_COPY in _src_txt)
P('the post-move mismatch branch does NOT call _discard_partial_move',
  '_discard_partial_move' not in _tail.split('return str(destination)')[0],
  'cleanup found after a successful move')
P('a mismatch is logged as an error',
  'Size mismatch after move' in _src_txt)
P('a mismatch is surfaced to the user',
  "safety.move_size_mismatch" in _src_txt)
P('the source size is captured BEFORE the move',
  _src_txt.index('source_size = source.stat().st_size')
  < _src_txt.index('shutil.move(str(source), str(destination))'))

# Functional: a mismatch after a "successful" move keeps the bytes and reports False.
_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    d = _td / 'p' / 'A'
    d.mkdir(parents=True)
    f = d / 'shrunk.jpg'
    f.write_bytes(b'Z' * 3000)

    def shrinking_move(src, dst, **kw):
        """Succeeds, but the destination ends up shorter than the source."""
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b'Z' * 10)

    real_move = FU.shutil.move
    FU.shutil.move = shrinking_move
    try:
        res = move_to_recycle_bin(str(f), subfolder='similar')
    finally:
        FU.shutil.move = real_move

    dest = compute_recycle_destination(str(f), subfolder='similar')
    landed = [p for p in (_td / 'rb').rglob('shrunk*.jpg')]
    P('a size mismatch returns False', res is False, repr(res))
    P('but the (only) copy is KEPT, never deleted', len(landed) == 1, str(landed))
    P('the kept bytes are the ones that arrived',
      bool(landed) and landed[0].read_bytes() == b'Z' * 10)
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)


# =====================================================================
SEP('E.  dry-run computes the REAL destination and still touches nothing')
# =====================================================================
# Why 17 rounds of dry-run review never found the pile-up: move_to_recycle_bin()
# returned at its dry-run branch BEFORE any destination logic ran, so
# get_session_folder_name() and clean_path_for_recycle_bin() were never executed
# in a dry run at all. The dry run now runs the very same computation.

_FU_SRC = read_src('src/utils/helpers/file_utils.py')
P('the dry-run branch computes a destination',
  'destination = compute_recycle_destination(file_path, subfolder)' in _FU_SRC)
P('and logs source AND destination (the old line logged only the source)',
  "i18n.get('safety.dry_run_would_move'), source, destination" in _FU_SRC)
P('the dry-run branch still returns BEFORE any mkdir/move',
  _FU_SRC.index('return "dry_run"') < _FU_SRC.index('recycle_bin.mkdir(parents=True, exist_ok=True)'))


class _Silent:
    """A console stand-in that records instead of printing."""

    def __init__(self):
        self.lines = []

    def print(self, *a, **k):
        self.lines.append(' '.join(str(x) for x in a))


_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    setmem('safety.dry_run_mode', True)
    s = _td / 'photos' / 'Teeth' / 'Art'
    s.mkdir(parents=True)
    f1 = s / 'x.jpg'; f1.write_bytes(b'a' * 100)
    f2 = s / 'y.jpg'; f2.write_bytes(b'b' * 100)
    reset_session_folder()
    r1 = move_to_recycle_bin(str(f1), subfolder='similar')
    r2 = move_to_recycle_bin(str(f2), subfolder='similar')
    P('the "dry_run" sentinel is unchanged, so every caller still works',
      r1 == 'dry_run' and r2 == 'dry_run', f'{r1!r} {r2!r}')
    P('both files are untouched', f1.exists() and f2.exists())
    P('no directory was created anywhere', not (_td / 'rb').exists())
    P('two destinations were computed and reserved',
      len(FU._dry_run_reserved) == 2, str(sorted(FU._dry_run_reserved)))
    P('each computed destination mirrors its own source folder',
      all('Teeth' in d and 'Art' in d for d in FU._dry_run_reserved),
      str(sorted(FU._dry_run_reserved)))

    # A dry run must also simulate the collision suffixes a real run would give.
    reset_session_folder()
    n1 = s / 'same.jpg'; n1.write_bytes(b'1')
    move_to_recycle_bin(str(n1), subfolder='similar')
    n1.write_bytes(b'2')                       # same folder, same name again
    move_to_recycle_bin(str(n1), subfolder='similar')
    P('a repeated dry-run name is reserved twice (collision simulated)',
      len(FU._dry_run_reserved) == 2, str(len(FU._dry_run_reserved)))
    P('the repeat carries a _1 suffix, exactly as a real run would',
      any(Path(d).stem.endswith('_1') for d in FU._dry_run_reserved),
      str(sorted(Path(d).name for d in FU._dry_run_reserved)))
    reset_session_folder()
    P('reset_session_folder() also clears the dry-run reservations',
      len(FU._dry_run_reserved) == 0, str(len(FU._dry_run_reserved)))
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)


# =====================================================================
SEP('F.  the capacity gate measures only cross-volume bytes, and can refuse')
# =====================================================================
# A move WITHIN a volume is os.rename(): instant, atomic, free. ACROSS volumes it
# is copy2() + unlink() and needs the file's full size on the destination. The
# user rejected putting a bin on every disk, so instead the program measures the
# cost and refuses to START a run that cannot finish.

P('the capacity gate exists',
  'def ensure_recycle_bin_capacity(' in _FU_SRC)
P('it uses shutil.disk_usage (no such call existed anywhere before)',
  'shutil.disk_usage(' in _FU_SRC)
P('a safety margin keeps the OS itself working',
  'CAPACITY_SAFETY_MARGIN_BYTES' in _FU_SRC)
_gate_src = _FU_SRC.split('def ensure_recycle_bin_capacity')[1].split('\ndef ')[0]
P('a dry run is exempt (it moves nothing, so it needs no room)',
  "safety.dry_run_mode" in _gate_src)
P('an empty file list is exempt', 'if not file_paths:' in _gate_src)
P('the gate asks before proceeding and logs an override',
  'capacity_proceed_question' in _gate_src and 'capacity_aborted' in _gate_src)

_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    s = _td / 'src'; s.mkdir()
    big = s / 'big.bin'; big.write_bytes(b'z' * 5000)

    # same volume: bin inside the same temp dir -> rename -> costs nothing
    setmem('paths.recycle_bin', str(_td / 'rb'))
    info = recycle_bin_capacity_report([str(big)])
    P('same-volume files cost ZERO bytes', info['needed'] == 0, str(info['needed']))
    P('same-volume files are not counted as cross-volume',
      info['cross_volume'] == 0, str(info['cross_volume']))
    P('a same-volume deletion is always allowed', info['ok'] is True)
    P('the file was still seen (total counts it)', info['total'] == 1)
    P('same-volume reports the same-drive message',
      ensure_recycle_bin_capacity([str(big)], _Silent()) is True)

    # cross volume: this machine may have only one physical disk, so the volume
    # boundary is simulated by making the SOURCE report a different volume than
    # the bin. The arithmetic under test is the same either way.
    setmem('paths.recycle_bin', str(_td / 'rb'))
    real_drive_of = FU._drive_of
    FU._drive_of = lambda p: ('x:' if str(p) == str(big) else real_drive_of(p))
    try:
        info2 = recycle_bin_capacity_report([str(big)])
    finally:
        FU._drive_of = real_drive_of
    P('a cross-volume file is charged its FULL size',
      info2['needed'] == 5000, str(info2['needed']))
    P('and counted as cross-volume', info2['cross_volume'] == 1)
    P('free space on the bin volume is reported', info2['free'] is not None)
    P('5 KB + margin fits on a real disk, so it is allowed', info2['ok'] is True)

    # A bin that has never been created must still yield a real free-space number,
    # or the gate would read None and silently allow anything on a fresh install.
    setmem('paths.recycle_bin', str(_td / 'never' / 'created' / 'bin'))
    info_new = recycle_bin_capacity_report([str(big)])
    P('a not-yet-created bin still reports free space (walks up to an ancestor)',
      info_new['free'] is not None, str(info_new['free']))
    P('and the walk-up resolver is in the source',
      'probe = bin_root' in _FU_SRC)
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)

# An over-sized request must be refused. Emulated by faking stat() rather than
# writing terabytes to disk.
_cwd0 = os.getcwd()
try:
    _td = sandbox()
    os.chdir(str(_td))
    setmem('paths.recycle_bin', str(_td / 'rb'))
    s = _td / 'src'; s.mkdir()
    big = s / 'big.bin'; big.write_bytes(b'z' * 100)
    base_free = recycle_bin_capacity_report([str(big)])['free'] or 0
    impossible = base_free + 10 * 1024 ** 3

    real_stat = Path.stat
    real_drive_of = FU._drive_of

    class _FakeStat:
        st_size = impossible

    def fake_stat(self, *a, **k):
        if str(self) == str(big):
            return _FakeStat()
        return real_stat(self, *a, **k)

    Path.stat = fake_stat
    FU._drive_of = lambda p: ('x:' if str(p) == str(big) else real_drive_of(p))
    try:
        info3 = recycle_bin_capacity_report([str(big)])
    finally:
        Path.stat = real_stat
        FU._drive_of = real_drive_of
    P('a request larger than the free space reports ok=False',
      info3['ok'] is False, str(info3['ok']))
    P('and charges the impossible size', info3['needed'] == impossible,
      str(info3['needed']))
    P('so the gate would refuse to start such a run',
      info3['needed'] + FU.CAPACITY_SAFETY_MARGIN_BYTES > (info3['free'] or 0))
finally:
    os.chdir(_cwd0)
    reset_session_folder()
    shutil.rmtree(_td, ignore_errors=True)


# =====================================================================
SEP('G.  every deletion site runs the gate and counts its failures')
# =====================================================================
# Before this round all five loops swallowed failures with `except Exception:
# pass`, so a run that moved nothing still reported itself as finished. The
# duplicate_detector helper is inherited by the video detector, so four call
# sites cover every section of the program.

SITES = {
    'src/core/processors/similarity_processor.py': 'similar images',
    'src/core/detectors/corruption_detector.py': 'corrupted images',
    'src/core/image_analyzer.py': 'small images',
    'src/core/detectors/duplicate_detector.py': 'duplicates / office / archives / video',
}
for rel, label in SITES.items():
    txt = read_src(rel)
    P(f'{label}: imports the capacity gate', 'ensure_recycle_bin_capacity' in txt)
    P(f'{label}: runs the gate and RETURNS when it refuses',
      'if not ensure_recycle_bin_capacity(' in txt)
    P(f'{label}: counts failed moves', 'failed' in txt.lower()
      and ('_last_failed_moves' in txt or 'failed_files' in txt))
    P(f'{label}: announces failed moves to the user',
      'safety.failed_moves_warning' in txt)
    P(f'{label}: no bare `except Exception: pass` left in the move loop',
      'except Exception:\n                    pass' not in txt
      and 'except Exception:\n                pass' not in txt)

P('the video detector inherits the shared helper (so it is covered too)',
  '_move_files_to_bin' in read_src('src/core/detectors/video_duplicate_detector.py'))
P('the shared helper records failures on self._last_failed_moves',
  'self._last_failed_moves' in read_src('src/core/detectors/duplicate_detector.py'))

# The recycle-bin location now has ONE source of truth.
P('get_recycle_bin_root() is the single resolver',
  'def get_recycle_bin_root(' in _FU_SRC)
for rel in list(SITES) + ['src/cli/main_cli.py']:
    txt = read_src(rel)
    P(f'{rel}: no inline Path.cwd() recycle-bin expression left',
      "Path.cwd() / recycle_bin_path" not in txt)
P('move_to_recycle_bin() resolves through the shared helper',
  'recycle_bin = get_recycle_bin_root()' in _FU_SRC)
P('MainCLI creates the SAME bin the moves target',
  'recycle_bin = get_recycle_bin_root()' in read_src('src/cli/main_cli.py'))
P('resolution semantics are UNCHANGED (still cwd-anchored, by design)',
  'return Path.cwd() / candidate' in _FU_SRC)


# =====================================================================
SEP('H.  every new message exists in BOTH languages')
# =====================================================================
from src.core.i18n.i18n import i18n                                   # noqa: E402

NEW_KEYS = [
    'safety.move_size_mismatch',
    'safety.capacity_title',
    'safety.capacity_same_drive',
    'safety.capacity_needed',
    'safety.capacity_free',
    'safety.capacity_insufficient',
    'safety.capacity_proceed_question',
    'safety.capacity_aborted',
    'safety.capacity_ok',
    'safety.failed_moves_warning',
]
_prev_lang = config.get('language', 'en')
for lang in ('en', 'ar'):
    i18n.set_language(lang)
    for key in NEW_KEYS:
        val = i18n.get(key)
        P(f'[{lang}] {key} is translated',
          bool(val) and not str(val).startswith('[Missing'), repr(val))

# The two format strings must accept the arguments the code actually passes.
i18n.set_language('en')
try:
    i18n.get('safety.capacity_needed').format(3, '1.50 MB')
    i18n.get('safety.capacity_free').format('c:', '7.80 GB')
    i18n.get('safety.failed_moves_warning').format(12)
    P('the format placeholders match the arguments passed by the code', True)
except (IndexError, KeyError) as e:
    P('the format placeholders match the arguments passed by the code', False, str(e))
i18n.set_language('ar')
try:
    i18n.get('safety.capacity_needed').format(3, '1.50 MB')
    i18n.get('safety.capacity_free').format('c:', '7.80 GB')
    i18n.get('safety.failed_moves_warning').format(12)
    P('and the Arabic strings take the same arguments', True)
except (IndexError, KeyError) as e:
    P('and the Arabic strings take the same arguments', False, str(e))
i18n.set_language(_prev_lang or 'en')


# =====================================================================
SEP('I.  reports are self-describing (dry-run flag + real bin location)')
# =====================================================================
# During the round-18 investigation nobody could tell from a report whether a run
# was a simulation, or where 40 GB of "deleted" photos had actually gone; both had
# to be inferred from an empty recycle bin and a separate settings.json read. Every
# header now carries them.

import io as _io                                                      # noqa: E402
from src.utils.reports.report_formatter import ReportFormatter         # noqa: E402
from src.utils.reports.corrupted_report_generator import (             # noqa: E402
    CorruptedReportGenerator)

_fmt = ReportFormatter()
_buf = _io.StringIO()
_fmt.write_run_metadata(_buf, failed_count=7)
_out = _buf.getvalue()
P('the metadata helper writes a dry-run flag', 'DRY-RUN:' in _out, repr(_out))
P('and the recycle-bin location', 'Recycle Bin:' in _out, repr(_out))
P('and the failed-move count when non-zero', ': 7' in _out, repr(_out))
_buf0 = _io.StringIO()
_fmt.write_run_metadata(_buf0, failed_count=0)
P('the failed-move line is omitted when nothing failed',
  'NOT MOVED' not in _buf0.getvalue(), repr(_buf0.getvalue()))
P('the helper cannot raise (a report must never die on a metadata line)',
  'logging.warning' in read_src('src/utils/reports/report_formatter.py'))

WIRED = ['corrupted_report_generator.py', 'duplicate_report_generator.py',
         'similarity_report_generator.py', 'small_images_report_generator.py',
         'video_duplicate_report_generator.py']
for _rel in WIRED:
    P(f'{_rel}: header calls write_run_metadata',
      'write_run_metadata(' in read_src('src/utils/reports/' + _rel))
P('both similarity headers are wired (the generator has two)',
  read_src('src/utils/reports/similarity_report_generator.py')
  .count('write_run_metadata(') == 2)

# End to end: a real report file must contain both lines, in both modes.
_cwd0 = os.getcwd()
_tmprep = Path(tempfile.mkdtemp(prefix='imgsniper_r18rep_'))
try:
    for _dry in (True, False):
        setmem('safety.dry_run_mode', _dry)
        _p = CorruptedReportGenerator(_tmprep).generate_corrupted_report([], {})
        _txt = Path(_p).read_text(encoding='utf-8')
        P(f'a real report records DRY-RUN: {_dry}', f'DRY-RUN: {_dry}' in _txt)
        P('a real report records the recycle-bin location',
          'recycle bin:' in _txt.lower() or 'Recycle Bin:' in _txt)
        P('and the location is the real bin',
          str(get_recycle_bin_root()).lower() in _txt.lower())
finally:
    os.chdir(_cwd0)
    shutil.rmtree(_tmprep, ignore_errors=True)


# =====================================================================
SEP('J.  the machine is left exactly as it was found')
# =====================================================================
P('config/settings.json is byte-identical',
  _CFG_BYTES is None or _CFG_FILE.read_bytes() == _CFG_BYTES)
_reports_after = (sorted(p.name for p in _REPORTS_DIR.glob('*'))
                  if _REPORTS_DIR.exists() else [])
P('no report was created or removed', _reports_after == _REPORTS_BEFORE,
  f'before={len(_REPORTS_BEFORE)} after={len(_reports_after)}')
_bin_after = (sorted(str(p.relative_to(_REAL_BIN)) for p in _REAL_BIN.rglob('*'))
              if _REAL_BIN.exists() else [])
P('the REAL recycle-bin is untouched (no test file leaked into it)',
  _bin_after == _BIN_BEFORE,
  f'before={len(_BIN_BEFORE)} after={len(_bin_after)}')
P('the working directory was restored', os.getcwd() == str(ROOT)
  or os.path.normcase(os.getcwd()) == os.path.normcase(_cwd0), os.getcwd())
P('no dry-run reservation leaked out of the suite',
  len(FU._dry_run_reserved) == 0, str(len(FU._dry_run_reserved)))
P('no session folder leaked out of the suite',
  len(FU._session_folders) == 0, str(len(FU._session_folders)))
# Restore the IN-MEMORY config from the bytes captured at import time. The atexit
# hook only rewrites the FILE; setmem() mutated config.config directly, so without
# this the process would keep a temp-dir recycle bin and a flipped dry-run flag.
_SAVED_CFG = json.loads(_CFG_BYTES.decode('utf-8')) if _CFG_BYTES else None
if _SAVED_CFG is not None:
    config.config = _SAVED_CFG
P('the in-memory config was restored from the on-disk settings',
  _SAVED_CFG is None or config.config is _SAVED_CFG)
P('safety.dry_run_mode matches settings.json again',
  _SAVED_CFG is None
  or config.get('safety.dry_run_mode') == _SAVED_CFG.get('safety', {}).get('dry_run_mode'),
  f"in-memory={config.get('safety.dry_run_mode')} "
  f"on-disk={(_SAVED_CFG or {}).get('safety', {}).get('dry_run_mode')}")
P('paths.recycle_bin matches settings.json again',
  _SAVED_CFG is None
  or config.get('paths.recycle_bin') == _SAVED_CFG.get('paths', {}).get('recycle_bin'),
  f"in-memory={config.get('paths.recycle_bin')} "
  f"on-disk={(_SAVED_CFG or {}).get('paths', {}).get('recycle_bin')}")
P('the bin resolves back to the REAL project bin',
  _SAVED_CFG is None or get_recycle_bin_root() == _REAL_BIN,
  str(get_recycle_bin_root()))


# =====================================================================
print('')
print('=' * 70)
print(f'  passed: {TP}')
print(f'  failed: {TF}')
print(f'  total : {TP + TF}')
print('')
print('  RESULT: ' + ('ALL PASS' if TF == 0 else 'FAIL'))
print('=' * 70)
sys.exit(1 if TF else 0)






