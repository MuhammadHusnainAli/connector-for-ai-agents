"""The bundled icon set stays small, valid, and the size it claims to be.

The set was 13.3 MB before 0.2.4, because 679 of the 1,643 files were Figma
exports wrapping a 4096px PNG to display a 42x42 logo. Re-encoding them brought
it to 2.9 MB. These tests exist so that cannot quietly come back: one dropped-in
export from a design tool can add half a megabyte on its own.

`python scripts/optimize_icons.py --report` measures the set without writing;
running it without `--report` re-encodes anything that has drifted.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET

from connector_manager.registry import ICONS_DIR

#: Headroom over the 2.9 MB the set currently occupies. Generous enough that
#: adding icons is never a fight, tight enough that one raw export trips it.
TOTAL_BUDGET_MB = 4.5
#: A single icon past this is almost certainly an unoptimised export rather
#: than a genuinely intricate logo -- the largest real one is about 56 KB.
PER_ICON_BUDGET_KB = 90
#: Icons render at 62x62. An embedded bitmap larger than twice that is pixels
#: nobody sees; the old set had one 4096px wide.
MAX_EMBEDDED_BYTES = 124 * 124 * 4

ICONS = sorted(ICONS_DIR.glob("*.svg"))


def test_there_are_icons() -> None:
    assert len(ICONS) > 1500, f"expected the bundled icon set, found {len(ICONS)}"


def test_every_icon_parses_and_is_an_svg() -> None:
    """A malformed icon renders as nothing, and nothing in the API would say so."""
    broken = []
    for path in ICONS:
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
        except ET.ParseError as exc:
            broken.append(f"{path.name}: {exc}")
            continue
        if not root.tag.endswith("svg"):
            broken.append(f"{path.name}: root element is {root.tag!r}")
    assert not broken, f"{len(broken)} invalid icon(s): " + "; ".join(broken[:5])


def test_the_set_fits_its_budget() -> None:
    total = sum(p.stat().st_size for p in ICONS) / 1e6
    assert total < TOTAL_BUDGET_MB, (
        f"icons total {total:.2f} MB, over the {TOTAL_BUDGET_MB} MB budget -- "
        "run `python scripts/optimize_icons.py`"
    )


def test_no_single_icon_is_oversized() -> None:
    fat = [
        f"{p.name} ({p.stat().st_size // 1024} KB)"
        for p in ICONS
        if p.stat().st_size > PER_ICON_BUDGET_KB * 1024
    ]
    assert not fat, (
        f"{len(fat)} icon(s) over {PER_ICON_BUDGET_KB} KB: {fat[:5]} -- "
        "run `python scripts/optimize_icons.py`"
    )


def test_embedded_bitmaps_are_not_wildly_oversized() -> None:
    """An icon may wrap a bitmap, but not one sized for a billboard."""
    oversized = []
    for path in ICONS:
        payload = re.search(
            r"base64,([A-Za-z0-9+/=]+)",
            path.read_text(encoding="utf-8", errors="replace"),
        )
        if payload is None:
            continue
        decoded = len(base64.b64decode(payload.group(1) + "==="))
        if decoded >= MAX_EMBEDDED_BYTES:
            oversized.append(f"{path.name} ({decoded // 1024} KB)")
    assert not oversized, (
        f"{len(oversized)} icon(s) embed a bitmap far larger than they display at: "
        f"{oversized[:5]} -- run `python scripts/optimize_icons.py`"
    )
