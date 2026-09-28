#!/usr/bin/env python3
"""Unified test runner for imgSniper v3.

Runs every suite in tests/ as an isolated subprocess and reports a single
combined verdict with a proper exit code, so it can be used directly as a
CI / pre-commit gate:

    python tests/run_all.py            # exit 0 = everything passed

Design note: the suites are plain scripts (not pytest). They were kept that way
deliberately -- they already produce rich, sectioned logs with per-assertion
detail, and running each in its OWN process keeps their global state (config
singleton, i18n language, logging handlers) from leaking into one another.
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / 'tests'

SUITES = [
    ('test_fixes.py', 'Round 1 -- audit findings P0/P1 verification'),
    ('verify_e2e.py', 'End-to-end scenarios on real images'),
    ('test_fixes_round2.py', 'Round 2 -- safety gate, date criterion, quality floor'),
    ('test_fixes_round3.py', 'Round 3 -- P0-4/P0-8 scoring, P2-13/P2-14 dates, P2-18 language'),
    ('test_fixes_round4.py', 'Round 4 -- P2-7 filters, P2-20 logging, P2-22 config, P3-8 safety'),
    ('test_fixes_round5.py', 'Round 5 -- dHash guard (#1126), honest reasons (#7/#18/#535), date-only (#14), warning capture'),
    ('test_fixes_round6.py', 'Round 6 -- RAW/HEIC codecs (pillow-heif/rawpy), visible skips, no false "corrupted"'),
]


def main() -> int:
    # Inherit the same encoding safety net main.py uses, so Arabic/emoji output
    # from child processes cannot crash this runner on a cp1256 console.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError, OSError):
            pass

    print('=' * 72)
    print('  imgSniper v3 -- FULL TEST RUN')
    print('=' * 72)

    results = []
    for name, description in SUITES:
        path = TESTS / name
        if not path.exists():
            print(f'\n[SKIP] {name} -- not found')
            results.append((name, description, None, 0.0))
            continue

        print(f'\n>>> {name} :: {description}')
        started = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(path)],
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            code = proc.returncode
        except Exception as exc:                       # pragma: no cover
            print(f'    could not launch: {exc}')
            code = -1
        elapsed = time.time() - started

        status = 'PASS' if code == 0 else 'FAIL'
        print(f'    [{status}] exit={code} in {elapsed:.1f}s')
        results.append((name, description, code, elapsed))

    print('\n' + '=' * 72)
    print('  SUMMARY')
    print('=' * 72)
    passed = failed = skipped = 0
    for name, _desc, code, elapsed in results:
        if code is None:
            skipped += 1
            mark = 'SKIP'
        elif code == 0:
            passed += 1
            mark = 'PASS'
        else:
            failed += 1
            mark = 'FAIL'
        print(f'  [{mark}] {name:<24} ({elapsed:.1f}s)')

    print('-' * 72)
    print(f'  suites passed : {passed}')
    print(f'  suites failed : {failed}')
    print(f'  suites skipped: {skipped}')
    print('=' * 72)

    if failed:
        print('  RESULT: FAILED -- inspect the per-suite logs in the project root:')
        print('          test_run.log / verify_e2e.log / test_run_round2.log')
        print('          test_run_round3.log / test_run_round4.log')
        return 1
    print('  RESULT: ALL SUITES PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
