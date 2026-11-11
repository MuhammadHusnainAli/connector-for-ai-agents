#!/usr/bin/env python3
"""Copy the shared data and docs into the Rust crate, so it can be published.

    python scripts/stage_crate.py           # stage, before `cargo package` / `cargo publish`
    python scripts/stage_crate.py --clean   # remove the staged copies again

In the repository the crate compiles in the data and documentation it shares
with the Python package (`src/connector_manager/data`, `RUST.md`, `LICENSE`).
A crate on crates.io can only carry files inside its own folder, so this copies
them into `src/connector_manager_rs/` first. The copies are git-ignored, and
the crate's `build.rs` prefers them when they exist.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CRATE = REPO / "src" / "connector_manager_rs"
DATA = REPO / "src" / "connector_manager" / "data"
#: Only what the crate reads: the catalogue, the tool packs and the logos.
DATA_PARTS = ("connectors", "tools", "icons")
FILES = {"RUST.md": REPO / "RUST.md", "LICENSE": REPO / "LICENSE"}


def clean() -> None:
    shutil.rmtree(CRATE / "data", ignore_errors=True)
    for name in FILES:
        (CRATE / name).unlink(missing_ok=True)


def stage() -> None:
    clean()
    for part in DATA_PARTS:
        shutil.copytree(DATA / part, CRATE / "data" / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name, source in FILES.items():
        shutil.copyfile(source, CRATE / name)
    files = sum(1 for p in (CRATE / "data").rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in (CRATE / "data").rglob("*") if p.is_file())
    print(f"staged {files} data files ({size / 1e6:.1f} MB) and {', '.join(FILES)} into {CRATE.relative_to(REPO)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clean", action="store_true", help="remove the staged copies")
    args = parser.parse_args()
    if args.clean:
        clean()
        print("removed the staged copies")
    else:
        stage()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
