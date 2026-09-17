#!/usr/bin/env python3
"""Count what the package ships: connectors, and tools across all connectors.

    python scripts/count_catalogue.py                     # the two totals
    python scripts/count_catalogue.py --include-baseline  # + synthesised tools

Connectors come from ``data/connectors/*.json``, tools from the authored packs
under ``data/tools/<auth-mode>/<connector-id>.json``. A connector with no pack
still gets a baseline pack at runtime (``check_connection`` plus the raw HTTP
verbs); those are synthesised rather than authored, so they are counted only
with ``--include-baseline``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from connector_manager.registry import ConnectorRegistry  # noqa: E402
from connector_manager.tools import ToolRegistry, baseline_pack  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--include-baseline",
        action="store_true",
        help="also count the tools synthesised for connectors without a pack",
    )
    args = parser.parse_args()

    connectors = ConnectorRegistry()
    tools = ToolRegistry()

    total_connectors = len(connectors)
    total_tools = tools.total_tools()

    baseline_tools = 0
    if args.include_baseline:
        for connector in connectors:
            if tools.has(connector.id):
                continue
            pack = baseline_pack(connector.id, connector.display_name, connector.raw)
            if pack is not None:
                baseline_tools += len(pack)

    print(f"connectors: {total_connectors}")
    print(f"tools:      {total_tools + baseline_tools}")
    if args.include_baseline:
        print(f"            {total_tools} authored + {baseline_tools} baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
