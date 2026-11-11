#!/usr/bin/env python3
"""Keep the Python package and the Rust crate on one version number.

    python scripts/sync_version.py                # print the version every file states
    python scripts/sync_version.py --check        # CI: fail unless they all agree
    python scripts/sync_version.py --check --tag v0.3.0   # ...and agree with this tag
    python scripts/sync_version.py --set 0.3.0    # write a new version everywhere

`pyproject.toml` is the source of truth. The same number lives in the crate's
`Cargo.toml` and `Cargo.lock`, and in the package's `__version__`, so PyPI and
crates.io always publish matching releases.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

#: file -> (pattern whose group 2 is the version, label)
PLACES: dict[Path, tuple[re.Pattern[str], str]] = {
    REPO / "pyproject.toml": (re.compile(r'(?m)^(version = ")([^"]+)(")'), "Python package"),
    REPO / "src/connector_manager_rs/Cargo.toml": (re.compile(r'(?m)^(version = ")([^"]+)(")'), "Rust crate"),
    REPO / "src/connector_manager_rs/Cargo.lock": (
        re.compile(r'(name = "connector-for-ai-agents"\nversion = ")([^"]+)(")'),
        "Rust lockfile",
    ),
    REPO / "src/connector_manager/__init__.py": (re.compile(r'(?m)^(__version__ = ")([^"]+)(")'), "__version__"),
}


def versions() -> dict[Path, str]:
    out = {}
    for path, (pattern, _) in PLACES.items():
        match = pattern.search(path.read_text(encoding="utf-8"))
        if not match:
            raise SystemExit(f"no version found in {path.relative_to(REPO)}")
        out[path] = match.group(2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail unless every file states the same version")
    parser.add_argument("--tag", help="with --check, also require this tag (v-prefixed or not)")
    parser.add_argument("--set", dest="new", metavar="VERSION", help="write this version everywhere")
    args = parser.parse_args()

    if args.new:
        if not SEMVER.match(args.new):
            raise SystemExit(f"not a semantic version: {args.new}")
        for path, (pattern, _) in PLACES.items():
            text = path.read_text(encoding="utf-8")
            path.write_text(pattern.sub(lambda m: f"{m.group(1)}{args.new}{m.group(3)}", text, count=1), encoding="utf-8")
        print(f"version set to {args.new} in {len(PLACES)} files")

    found = versions()
    for path, version in found.items():
        print(f"    {version:<10} {PLACES[path][1]:<16} {path.relative_to(REPO)}")
    distinct = set(found.values())
    if len(distinct) != 1:
        print(f"versions disagree: {sorted(distinct)}", file=sys.stderr)
        return 1
    version = distinct.pop()
    if args.tag and args.tag.removeprefix("v") != version:
        print(f"tag {args.tag} does not match version {version}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
