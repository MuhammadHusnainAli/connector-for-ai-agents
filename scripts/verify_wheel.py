"""Assert a built wheel carries the catalogue, not just the code.

A wheel whose data did not make it in still imports and still looks fine until
the first lookup raises. The index in particular is easy to lose: it is one
generated file among 406 packs, and without it every lookup falls back to
opening all of them, which is the cold start this layout exists to avoid.
"""

from __future__ import annotations

import glob
import sys
import zipfile

wheels = glob.glob("dist/*.whl")
if not wheels:
    sys.exit("no wheel in dist/")

names = zipfile.ZipFile(wheels[0]).namelist()
packs = [n for n in names if "/data/tools/" in n and n.endswith(".json")]
connectors = [n for n in names if "/data/connectors/" in n and n.endswith(".json")]
has_index = any(n.endswith("data/tools/index.json") for n in names)
stray_yaml = [n for n in names if n.endswith((".yaml", ".yml"))]

problems = []
if not has_index:
    problems.append("data/tools/index.json is missing")
if len(packs) < 400:
    problems.append(f"only {len(packs)} tool packs")
if len(connectors) < 10:
    problems.append(f"only {len(connectors)} connector files")
if stray_yaml:
    problems.append(f"{len(stray_yaml)} YAML file(s) still bundled, e.g. {stray_yaml[0]}")

if problems:
    sys.exit(f"{wheels[0]}: " + "; ".join(problems))

print(
    f"ok: wheel ships {len(packs) - 1} tool packs, {len(connectors)} connector files, "
    "the index, and no YAML"
)
