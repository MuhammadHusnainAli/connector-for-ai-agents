#!/usr/bin/env python3
"""Shrink the bundled icon set, keeping every file a valid 62x62 SVG.

Two thirds of the icons were never really vector: 679 of the 1,643 are Figma
exports that wrap a PNG -- often 4096px wide, cropped by a transform matrix to
show a 42x42 corner of itself -- inside an ``<image>`` element. Those 679 hold
11.5 MB of the 13.3 MB. The rest are genuine paths carrying export metadata and
six decimal places of coordinate precision.

    python scripts/optimize_icons.py --report   # measure, change nothing
    python scripts/optimize_icons.py            # rewrite them in place

Raster-backed icons are re-rendered: the *composed* SVG is rasterised at its
own declared size, so the crop and the transform are baked in rather than
reinterpreted, then quantised and re-wrapped. Vector icons keep their paths and
lose only what nothing reads.

Tracing the rasters into real paths was measured and rejected: the traced
output averaged 1.25x the size of the original file, which is roughly twelve
times what re-rendering costs, and banded the colours.

Needs inkscape and pillow:  uv run --with pillow --no-project python scripts/optimize_icons.py
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = REPO_ROOT / "src" / "connector_manager" / "data" / "icons"

#: Every icon in the set declares itself 62x62; that is the size they render at.
ICON_SIZE = 62
#: Palette size for a re-encoded raster. 64 keeps a logo's flat colours exact
#: and costs a third of what truecolor does; measured error is under 4/255.
PALETTE = 64
#: Coordinates are only rounded when the viewBox is large enough that two
#: decimals are sub-pixel. An icon drawn in a 0..1 viewBox would be destroyed.
MIN_VIEWBOX_FOR_ROUNDING = 20.0

#: One number in SVG path/points/transform grammar. Path data packs numbers
#: without separators -- "3.002.293" is *two* numbers, because a second dot can
#: only start a new one -- so numbers must be tokenised, never matched loosely
#: in the document text. Rounding "3.002" to "3" with a plain regex leaves
#: "3.293", silently merging two coordinates into one and bending the path.
NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
#: The attributes worth rounding. `transform` is deliberately absent: its
#: numbers are multipliers, not coordinates, so `scale(0.073321)` rounded to
#: two decimals becomes `scale(0.07)` -- a 4.5% error applied to the whole
#: drawing. Coordinates are in user space, where two decimals is sub-pixel.
GEOMETRY_ATTR = re.compile(r'\b(d|points)="([^"]*)"')
#: Any scale factor above this magnifies a rounding error rather than shrinking
#: it, so coordinates in such a document are left at full precision.
SCALE = re.compile(r"scale\(\s*([-\d.]+)|matrix\(\s*([-\d.]+)")
MAX_SAFE_SCALE = 1.5
VIEWBOX = re.compile(r'viewBox="\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)', re.I)


def is_raster(text: str) -> bool:
    return "base64," in text


# ---------------------------------------------------------------------------
# vector icons
# ---------------------------------------------------------------------------


def referenced_ids(text: str) -> set[str]:
    """Ids the document points at, via ``url(#x)``, ``href="#x"`` or ``begin``.

    Removing an id that a gradient fill or a ``<use>`` refers to silently blanks
    the icon, so only unreferenced ids may go.
    """
    out = set(re.findall(r"url\(\s*#([^)\s\"']+)", text))
    out |= set(re.findall(r'(?:xlink:)?href="#([^"]+)"', text))
    out |= set(re.findall(r'\bbegin="([^".]+)\.', text))
    return out


def round_numbers(value: str) -> str:
    """Round every number in one geometry attribute to two decimals.

    Tokenises rather than pattern-matching, and re-emits a separator whenever
    dropping one would let two numbers read as a single one -- which is exactly
    what a naive rounding pass does to packed path data.
    """
    out: list[str] = []
    pos = 0
    for m in NUMBER.finditer(value):
        out.append(value[pos : m.start()])
        text = f"{round(float(m.group()), 2):.2f}".rstrip("0").rstrip(".")
        if text in ("", "-0", "-"):
            text = "0"
        # A separator is needed when nothing already separates this number from
        # the last, and the join would parse as one number ("3" + ".29").
        if out and out[-1] == "" and text[0] not in "-+.":
            prev = "".join(out)
            if prev and (prev[-1].isdigit() or prev[-1] == "."):
                out.append(" ")
        elif out and out[-1] == "" and text[0] == ".":
            prev = "".join(out)
            if prev.endswith("."):
                out.append(" ")
        out.append(text)
        pos = m.end()
    out.append(value[pos:])
    return "".join(out)


def minify_vector(text: str) -> str:
    keep = referenced_ids(text)

    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<(metadata|title|desc)\b[^>]*>.*?</\1>", "", text, flags=re.S)
    text = re.sub(r"<(metadata|title|desc)\b[^>]*/>", "", text)

    # Editor bookkeeping. `class` is only safe to drop when no stylesheet or
    # presentation attribute could be selecting on it.
    text = re.sub(r'\s+(data-name|inkscape:[\w-]+|sodipodi:[\w-]+)="[^"]*"', "", text)
    if "<style" not in text and 'class="' in text:
        text = re.sub(r'\s+class="[^"]*"', "", text)

    def drop_unused_id(m: re.Match[str]) -> str:
        return "" if m.group(1) not in keep else m.group(0)

    text = re.sub(r'\s+id="([^"]*)"', drop_unused_id, text)

    # Coordinate precision, but only where the drawing is big enough for it.
    vb = VIEWBOX.search(text)
    big = True
    if vb:
        try:
            big = min(float(vb.group(1)), float(vb.group(2))) >= MIN_VIEWBOX_FOR_ROUNDING
        except ValueError:
            big = False

    # A magnifying transform turns a sub-pixel rounding error into a visible
    # one, so those documents keep their coordinates as authored.
    for m in SCALE.finditer(text):
        try:
            if abs(float(m.group(1) or m.group(2))) > MAX_SAFE_SCALE:
                big = False
                break
        except (TypeError, ValueError):
            big = False
            break

    if big:
        text = GEOMETRY_ATTR.sub(
            lambda m: f'{m.group(1)}="{round_numbers(m.group(2))}"', text
        )

    text = re.sub(r">\s+<", "><", text)
    text = re.sub(r"[ \t\r\n]{2,}", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# raster-backed icons
# ---------------------------------------------------------------------------


WRAPPER = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
    'viewBox="0 0 {s} {s}"><image width="{s}" height="{s}" '
    'href="data:image/png;base64,{data}"/></svg>'
)


def rerender_raster(path: Path) -> str | None:
    """Rasterise the composed icon at display size and re-wrap it.

    Rendering the whole SVG rather than pulling the embedded image out is what
    makes this safe: the pattern, the transform matrix and any vector chrome
    drawn over the bitmap are all baked into the result, so the icon looks the
    same instead of merely containing the same pixels.
    """
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "out.png"
        # argv is built entirely from this module's own constants plus a path
        # that came from globbing the bundled icon directory: no shell, no
        # user input, and inkscape is resolved from PATH because its location
        # differs across the platforms a contributor might run this on.
        result = subprocess.run(  # nosec B603 B607
            [
                "inkscape",
                f"--export-filename={png}",
                "--export-type=png",
                f"--export-width={ICON_SIZE}",
                f"--export-height={ICON_SIZE}",
                str(path),
            ],
            capture_output=True,
            timeout=90,
        )
        if result.returncode != 0 or not png.is_file():
            return None

        im = Image.open(png).convert("RGBA")
        im = im.quantize(colors=PALETTE, method=Image.FASTOCTREE).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)

    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return WRAPPER.format(s=ICON_SIZE, data=data)


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="measure without writing")
    parser.add_argument("--limit", type=int, default=0, help="process at most N icons")
    args = parser.parse_args()

    icons = sorted(ICONS_DIR.glob("*.svg"))
    if args.limit:
        icons = icons[: args.limit]
    if not icons:
        print(f"no icons under {ICONS_DIR}", file=sys.stderr)
        return 1

    before = {"vector": 0, "raster": 0}
    after = {"vector": 0, "raster": 0}
    counts = {"vector": 0, "raster": 0}
    failed: list[str] = []

    for path in icons:
        text = path.read_text(encoding="utf-8", errors="replace")
        size = path.stat().st_size
        kind = "raster" if is_raster(text) else "vector"
        counts[kind] += 1
        before[kind] += size

        new = rerender_raster(path) if kind == "raster" else minify_vector(text)
        if new is None or len(new) >= size:
            # Never make an icon bigger, and never drop one we could not render.
            if new is None:
                failed.append(path.name)
            after[kind] += size
            continue

        after[kind] += len(new.encode("utf-8"))
        if not args.report:
            path.write_text(new, encoding="utf-8")

    width = 13
    print(f"\n{'':<10}{'icons':>7}{'before':>{width}}{'after':>{width}}{'saved':>{width}}")
    for kind in ("vector", "raster"):
        b, a = before[kind], after[kind]
        pct = f"{(1 - a / b) * 100:.0f}%" if b else "-"
        print(f"{kind:<10}{counts[kind]:>7}{b / 1e6:>11.2f} MB{a / 1e6:>11.2f} MB{pct:>{width}}")
    b, a = sum(before.values()), sum(after.values())
    print(f"{'total':<10}{len(icons):>7}{b / 1e6:>11.2f} MB{a / 1e6:>11.2f} MB{(1 - a / b) * 100:>12.0f}%")
    if failed:
        print(f"\n{len(failed)} could not be rendered and were left alone: {failed[:5]}")
    if args.report:
        print("\n(--report: nothing was written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
