#!/usr/bin/env python3
"""Regroup the connector catalogue into one YAML file per auth mode.

The catalogue started life as a single ``connectors.yaml``. At ~1,600 entries
that file was 840 KB, which makes review diffs unreadable and edits
collision-prone. This script shards it into ``data/connectors/<auth-mode>.yaml``
and can re-run at any time to put entries back in the right file after an auth
mode changes.

    python scripts/split_connectors.py            # regroup in place
    python scripts/split_connectors.py --check    # CI: fail on drift

Grouping key is the *effective* auth mode: an alias inherits its target's mode
(following chains) unless it declares one of its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "connector_manager" / "data"
LEGACY_FILE = DATA_DIR / "connectors.yaml"
CONNECTORS_DIR = DATA_DIR / "connectors"

#: Bucket for entries whose auth mode is absent or unrecognised.
FALLBACK_MODE = "NONE"

HEADER = """\
# Connector definitions: {mode} auth.
#
# Auth mode, credential/config fields, api base url and verification endpoint
# for each connector, sorted by connector id. One file per auth mode; the
# registry loads every *.yaml under this directory and merges them.
#
# Machine-generated grouping -- run `python scripts/split_connectors.py` after
# changing an `auth_mode` so the entry lands in the right file.
"""


def slug(mode: str) -> str:
    """``OAUTH2_CC`` -> ``oauth2-cc``, the file stem for that mode."""
    return mode.lower().replace("_", "-")


def load_source(path: Path) -> dict[str, dict[str, Any]]:
    """Load the catalogue from a single YAML file or a directory of them."""
    entries: dict[str, dict[str, Any]] = {}
    for file in iter_yaml_files(path):
        chunk = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        for key, value in chunk.items():
            if key in entries:
                raise SystemExit(f"duplicate connector id {key!r} in {file}")
            entries[key] = value
    return entries


def iter_yaml_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        files = sorted(path.rglob("*.yaml"))
        if not files:
            raise SystemExit(f"no *.yaml files under {path}")
        return files
    if path.is_file():
        return [path]
    raise SystemExit(f"no such source: {path}")


def effective_mode(key: str, entries: dict[str, dict[str, Any]]) -> str:
    """The auth mode a connector ends up with once aliases are resolved.

    Aliases usually omit ``auth_mode`` and inherit it from their target, and a
    target can itself be an alias, so walk the chain. ``seen`` guards against a
    cycle in hand-edited data rather than trusting the file.
    """
    seen: set[str] = set()
    current = key
    while current in entries and current not in seen:
        seen.add(current)
        entry = entries[current]
        if not isinstance(entry, dict):
            break
        mode = entry.get("auth_mode")
        if mode:
            return str(mode)
        alias = entry.get("alias")
        if not alias:
            break
        current = str(alias)
    return FALLBACK_MODE


def group(entries: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """``{auth_mode: {connector_id: entry}}``, both levels sorted by key."""
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for key in sorted(entries):
        buckets.setdefault(effective_mode(key, entries), {})[key] = entries[key]
    return dict(sorted(buckets.items()))


def render(mode: str, bucket: dict[str, dict[str, Any]]) -> str:
    body = yaml.safe_dump(
        bucket,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    )
    return HEADER.format(mode=mode) + body


def write(buckets: dict[str, dict[str, dict[str, Any]]], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for mode, bucket in buckets.items():
        path = dest / f"{slug(mode)}.yaml"
        path.write_text(render(mode, bucket), encoding="utf-8")
        written.append(path)
    # Drop files for modes that no longer have any connectors.
    for stale in sorted(dest.glob("*.yaml")):
        if stale not in written:
            stale.unlink()
    return written


def check(buckets: dict[str, dict[str, dict[str, Any]]], dest: Path) -> int:
    """Compare the grouping against what is on disk; report every difference."""
    problems: list[str] = []
    expected = {dest / f"{slug(mode)}.yaml": render(mode, bucket) for mode, bucket in buckets.items()}
    on_disk = set(dest.glob("*.yaml"))

    for path in sorted(on_disk - set(expected)):
        problems.append(f"{path.name}: no connector uses this auth mode any more")
    for path, want in expected.items():
        if path not in on_disk:
            problems.append(f"{path.name}: missing")
        elif path.read_text(encoding="utf-8") != want:
            problems.append(f"{path.name}: out of date (wrong bucket, unsorted, or reformatted)")

    for problem in problems:
        print(f"drift: {problem}", file=sys.stderr)
    if problems:
        print(
            "\nRun `python scripts/split_connectors.py` to regroup.",
            file=sys.stderr,
        )
        return 1
    print(f"ok: {sum(len(b) for b in buckets.values())} connectors across {len(buckets)} files")
    return 0


def verify_roundtrip(source: dict[str, Any], dest: Path) -> None:
    """The split must be lossless: re-reading the shards yields the same data."""
    reloaded = load_source(dest)
    if reloaded != source:
        missing = sorted(set(source) - set(reloaded))
        added = sorted(set(reloaded) - set(source))
        changed = sorted(k for k in set(source) & set(reloaded) if source[k] != reloaded[k])
        raise SystemExit(
            "round-trip check failed -- refusing to leave a lossy split.\n"
            f"  missing: {missing[:10]}\n  added: {added[:10]}\n  changed: {changed[:10]}"
        )


def display(path: Path) -> str:
    """Repo-relative when it lives in the repo, absolute otherwise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="catalogue to read: a YAML file or a directory of them "
        f"(default: {CONNECTORS_DIR}, falling back to the legacy {LEGACY_FILE.name})",
    )
    parser.add_argument("--dest", type=Path, default=CONNECTORS_DIR, help="directory to write the per-mode files into")
    parser.add_argument("--check", action="store_true", help="report drift and exit non-zero instead of writing")
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="keep the legacy single-file catalogue after splitting it",
    )
    args = parser.parse_args()

    source = args.source
    if source is None:
        source = CONNECTORS_DIR if CONNECTORS_DIR.is_dir() else LEGACY_FILE

    entries = load_source(source)
    buckets = group(entries)

    if args.check:
        return check(buckets, args.dest)

    written = write(buckets, args.dest)
    verify_roundtrip(entries, args.dest)

    for path in written:
        count = len(buckets[next(m for m in buckets if slug(m) == path.stem)])
        print(f"{display(path)}: {count} connectors, {path.stat().st_size / 1024:.0f} KB")
    print(f"total: {len(entries)} connectors across {len(written)} files")

    if source.is_file() and source != args.dest and not args.keep_source:
        source.unlink()
        print(f"removed {display(source)} (now sharded under {display(args.dest)}/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
