#!/usr/bin/env python3
"""Rebuild ``data/tools/index.json``, the map that keeps a cold start cheap.

Without it, answering "what tools does stripe have?" means opening all 406
packs to find the one that claims ``stripe`` -- an `applies_to` alias is only
visible inside the file that declares it. The index records, per pack, the file
serving it, how many tools it holds and every connector id it answers to, so a
lookup reads exactly one file.

    python scripts/build_index.py            # write the index
    python scripts/build_index.py --check    # CI: is it current?

Run it after adding, removing or renaming a pack.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "src" / "connector_manager" / "data" / "tools"
INDEX = TOOLS_DIR / "index.json"

#: Bumped when the index grows a field the loader relies on.
FORMAT_VERSION = 1


def pack_files() -> list[Path]:
    """Every pack, which is every JSON under tools/ except the index itself."""
    return sorted(p for p in TOOLS_DIR.rglob("*.json") if p != INDEX)


def build() -> str:
    packs: dict[str, dict[str, Any]] = {}
    by_connector: dict[str, str] = {}

    for path in pack_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected an object at the top level")

        connector_id = str(data.get("connector_id") or path.stem)
        if connector_id in packs:
            raise ValueError(f"duplicate tool pack for {connector_id!r} in {path}")

        ids = [connector_id] + [str(c) for c in (data.get("applies_to") or [])]
        packs[connector_id] = {
            "file": f"{path.parent.name}/{path.name}",
            "tools": len(data.get("tools") or {}),
            "ids": ids,
            "display_name": str(data.get("display_name") or ""),
            "generated": bool(data.get("generated")),
        }
        for cid in ids:
            owner = by_connector.get(cid)
            if owner is not None and owner != connector_id:
                raise ValueError(f"connector {cid!r} is claimed by both {owner} and {connector_id}")
            by_connector[cid] = connector_id

    return json.dumps(
        {"version": FORMAT_VERSION, "packs": packs, "by_connector": by_connector},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args()

    payload = build()
    counts = json.loads(payload)
    summary = (
        f"{len(counts['packs'])} packs, {len(counts['by_connector'])} connector ids, "
        f"{sum(p['tools'] for p in counts['packs'].values()):,} tools"
    )

    if args.check:
        # Compared as parsed JSON, not as text: whitespace carries no meaning
        # here, and an editor that reformats the file on save should not fail
        # a build over it.
        try:
            current = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.is_file() else None
        except json.JSONDecodeError:
            current = None
        if current != counts:
            print(
                "data/tools/index.json is out of date -- run "
                "`python scripts/build_index.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"ok: index.json is current ({summary})")
        return 0

    INDEX.write_text(payload, encoding="utf-8")
    print(f"wrote {INDEX.relative_to(REPO_ROOT)} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
