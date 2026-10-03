"""Shared test helper (Round 13): judge the CODE, not the user's live settings.

Why this exists
---------------
`Settings -> Recovery Mode` and `safety.dry_run_mode` are legitimate LIVE
states -- that is exactly what the Settings menu offers, and a real
post-recovery cleanup runs with both enabled. Suites that inherited those
values from `config/settings.json` reported failures that were NOT code
defects: on a machine mid-cleanup, rounds 4, 8, 11 and 12 all failed for this
single reason (`exclude_patterns` empty, `include_hidden` true,
`max_file_size_mb` 0, `dry_run_mode` true).

Every suite already captures the original `settings.json` bytes before it
imports anything and restores them at exit, so pinning the in-memory singleton
here never costs the user their own configuration -- it only makes the verdict
about the code deterministic.
"""

from pathlib import Path

from src.core.config import DEFAULT_FILTERS, config


def pin_shipped_config(dry_run: bool = False, path=None):
    """Force the shipped `filters.*` and `safety.dry_run_mode` into memory.

    When `path` (the suite's `config/settings.json`) is given the same values
    are written to disk as well, and the resulting bytes are RETURNED so the
    suite can use them as the baseline for its "settings.json is
    byte-identical again" assertions. Without that, a machine that legitimately
    runs in Recovery Mode could never satisfy a byte comparison against its own
    prior bytes -- toggling Recovery Mode OFF writes the shipped defaults by
    design, so those bytes differ.

    `min_resolution` / `max_resolution` are deliberately left alone: they are
    not part of DEFAULT_FILTERS and no suite judges them.
    """
    config.config.setdefault('filters', {}).update(DEFAULT_FILTERS)
    config.config.setdefault('safety', {})['dry_run_mode'] = dry_run

    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        return None

    import json
    data = json.loads(path.read_bytes().decode('utf-8'))
    data.setdefault('filters', {}).update(DEFAULT_FILTERS)
    data.setdefault('safety', {})['dry_run_mode'] = dry_run
    path.write_bytes(json.dumps(data, indent=4, ensure_ascii=False).encode('utf-8'))
    return path.read_bytes()