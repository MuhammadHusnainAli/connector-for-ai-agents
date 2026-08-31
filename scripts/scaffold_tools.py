#!/usr/bin/env python3
"""Create and check connector tool packs.

Tools live in ``data/tools/<auth-mode>/<connector-id>.yaml``, one file per
connector, mirroring how the connector catalogue is sharded by auth mode.
Adding a connector's tools is a one-file job -- no code change, no registry
edit -- and this script writes the skeleton in the right place and validates
what is there.

    python scripts/scaffold_tools.py --new stripe     # write the skeleton
    python scripts/scaffold_tools.py --check          # CI: lint every pack
    python scripts/scaffold_tools.py --list           # what is covered so far
    python scripts/scaffold_tools.py --readme         # refresh README's coverage table
    python scripts/scaffold_tools.py --backlog        # what still needs a pack, worst first
    python scripts/scaffold_tools.py --catalogue      # write TOOLS.md: every connector and its tools

``--check`` is the same contract ``tests/test_tool_packs.py`` enforces, in a
form you can run against a file you are still editing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from connector_manager import ConnectorRegistry, UnknownConnectorError  # noqa: E402
from connector_manager.tools.executor import template_arguments  # noqa: E402
from connector_manager.tools.models import PARAM_TYPES, TOOL_NAME_RE, Tool, ToolPack  # noqa: E402
from connector_manager.tools.registry import ToolRegistry, load_pack  # noqa: E402

TOOLS_DIR = REPO_ROOT / "src" / "connector_manager" / "data" / "tools"

METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

SKELETON = '''\
# {display_name} tools.
#
# Docs: {docs_url}
#
# Fill in one entry per capability. Each tool needs: a description a model can
# act on, the scopes the provider demands, the request it makes, typed inputs,
# and a described output. `python scripts/scaffold_tools.py --check` validates
# the file; `pytest tests/test_tool_packs.py` is the same contract in CI.

connector_id: {connector_id}
display_name: {display_name}
docs_url: {docs_url}

# Uncomment when the provider's scope names need normalising before comparison
# (case-insensitive names, a shared URL prefix, or hierarchical scopes).
# scope_rules:
#   case_insensitive: false
#   strip_prefixes: []
#   implies:
#     write: [read]

# Uncomment when the provider can report a live credential's real scopes,
# either from a token-info endpoint or from the access token's own claims.
# scope_discovery:
#   method: GET
#   endpoint: /oauth/token/info
#   scopes_path: scopes          # or "header:x-oauth-scopes", or jwt_claim: scp

tools:

  list_things:
    title: List things
    description: >-
      Replace this with a description an agent can act on: what the tool does,
      what it returns, and when to reach for a different tool instead.
    category: things
    scopes: []
    read_only: true
    request:
      method: GET
      path: /v1/things
      query:
        limit: "${{limit}}"
    input:
      limit:
        type: integer
        description: How many things to return.
        optional: true
        default: 50
        minimum: 1
        maximum: 100
    output:
      description: A page of things.
      type: object
      properties:
        data: {{type: array}}
'''


def slug(mode: str) -> str:
    """``OAUTH2_CC`` -> ``oauth2-cc``, the folder a pack for that mode lives in."""
    return mode.lower().replace("_", "-")


# ---------------------------------------------------------------------------
# --new
# ---------------------------------------------------------------------------


def scaffold(connector_id: str, registry: ConnectorRegistry, force: bool) -> int:
    try:
        connector = registry.get(connector_id)
    except UnknownConnectorError:
        print(f"no connector '{connector_id}' in the catalogue", file=sys.stderr)
        return 1

    path = TOOLS_DIR / slug(connector.auth_mode.value) / f"{connector_id}.yaml"
    if path.exists() and not force:
        print(f"{display(path)} already exists (pass --force to overwrite)", file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        SKELETON.format(
            connector_id=connector_id,
            display_name=connector.display_name,
            docs_url="https://example.com/api-docs  # replace with the provider's reference",
        ),
        encoding="utf-8",
    )
    print(f"wrote {display(path)}")
    print(f"  auth mode : {connector.auth_mode.value}")
    print(f"  base url  : {connector.base_url or '-'}  (tool paths are relative to this)")
    print("\nNext: fill in the tools, then run")
    print("  python scripts/scaffold_tools.py --check")
    return 0


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def check(paths: list[Path] | None = None) -> int:
    registry = ConnectorRegistry()
    problems: list[str] = []

    if paths:
        packs = [load_pack(path) for path in paths]
    else:
        packs = ToolRegistry(TOOLS_DIR).packs
        if not packs:
            print(f"no tool packs under {display(TOOLS_DIR)}", file=sys.stderr)
            return 1

    seen: dict[str, str] = {}
    for pack in packs:
        problems.extend(_check_pack(pack, registry, seen))

    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problem(s) across {len(packs)} pack(s).", file=sys.stderr)
        return 1

    total = sum(len(pack) for pack in packs)
    covered = sum(len(pack.connector_ids) for pack in packs)
    print(f"ok: {total} tools across {len(packs)} packs, covering {covered} connectors")
    return 0


def _check_pack(pack: ToolPack, registry: ConnectorRegistry, seen: dict[str, str]) -> list[str]:
    problems: list[str] = []
    path = Path(pack.source)
    where = path.name

    try:
        connector = registry.get(pack.connector_id)
    except UnknownConnectorError:
        return [f"{where}: connector '{pack.connector_id}' is not in the catalogue"]

    if path.stem != pack.connector_id:
        problems.append(f"{where}: should be named {pack.connector_id}.yaml")
    expected = slug(connector.auth_mode.value)
    if path.parent.name != expected:
        problems.append(f"{where}: is under {path.parent.name}/ but {pack.connector_id} is {expected}")
    if not pack.display_name:
        problems.append(f"{where}: no display_name")
    if not (pack.docs_url or "").startswith("http"):
        problems.append(f"{where}: docs_url must point at the provider's reference")
    elif "example.com" in (pack.docs_url or ""):
        problems.append(f"{where}: docs_url is still the scaffold placeholder")
    if not pack.tools:
        problems.append(f"{where}: declares no tools")

    for other in pack.applies_to:
        try:
            if registry.get(other).auth_mode is not connector.auth_mode:
                problems.append(f"{where}: applies_to '{other}' has a different auth mode")
        except UnknownConnectorError:
            problems.append(f"{where}: applies_to unknown connector '{other}'")

    for connector_id in pack.connector_ids:
        if connector_id in seen:
            problems.append(f"{where}: connector '{connector_id}' is already served by {seen[connector_id]}")
        seen[connector_id] = where

    for tool in pack.tools.values():
        problems.extend(_check_tool(tool, where))
    return problems


def _check_tool(tool: Tool, where: str) -> list[str]:
    problems: list[str] = []
    name = f"{where}:{tool.name}"

    if not TOOL_NAME_RE.match(tool.name):
        problems.append(f"{name}: tool names are snake_case")
    if len(tool.description) < 40:
        problems.append(f"{name}: description is only {len(tool.description)} characters")
    if not tool.category:
        problems.append(f"{name}: no category")
    if not tool.output.description:
        problems.append(f"{name}: does not describe its output")

    request = tool.request
    if request.method not in METHODS:
        problems.append(f"{name}: method {request.method}")
    if not request.path.startswith("/"):
        problems.append(f"{name}: path {request.path!r} must start with /")
    if request.encoding not in ("json", "form"):
        problems.append(f"{name}: encoding {request.encoding!r}")
    if request.method == "GET":
        if request.body is not None:
            problems.append(f"{name}: GET with a body")
        if not tool.read_only:
            problems.append(f"{name}: GET that is not marked read_only")
    if request.method in ("PUT", "PATCH", "DELETE") and tool.read_only:
        problems.append(f"{name}: {request.method} marked read_only")
    if request.method == "DELETE" and not tool.destructive:
        problems.append(f"{name}: DELETE not marked destructive")

    declared = {p.name for p in tool.input}
    used = (
        template_arguments(request.path)
        | template_arguments(request.query)
        | template_arguments(request.headers)
        | template_arguments(request.body)
        | template_arguments(request.content)
    )
    for unused in sorted(declared - used):
        problems.append(f"{name}: argument '{unused}' is declared but no template reads it")

    for param in tool.input:
        if param.type not in PARAM_TYPES:
            problems.append(f"{name}.{param.name}: type {param.type!r}")
        if not param.description:
            problems.append(f"{name}.{param.name}: no description")
        if param.required and param.default is not None:
            problems.append(f"{name}.{param.name}: required yet carries a default")
        if param.enum and param.default is not None and param.default not in param.enum:
            problems.append(f"{name}.{param.name}: default is not one of its enum values")
        if param.type == "array" and param.items is None:
            problems.append(f"{name}.{param.name}: array with no items schema")
    return problems


# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------


#: The README section this script owns, so the coverage table cannot go stale.
MARKERS = ("tool-coverage", "tool-coverage-summary", "tool-coverage-note")
README = REPO_ROOT / "README.md"


def coverage_sections() -> dict[str, str]:
    """The three generated README blocks, built from the bundled packs."""
    from connector_manager import AuthMode, ConnectorRegistry as _Registry

    registry = _Registry()
    tools = ToolRegistry(TOOLS_DIR)

    rows = ["| Connector | Provider | Tools | Source |", "|---|---|---:|---|"]
    for pack in sorted(tools.packs, key=lambda p: (bool(p.generated), -len(p), p.connector_id)):
        ids = ", ".join(f"`{c}`" for c in pack.connector_ids)
        origin = "spec-generated" if pack.generated else "hand-authored"
        rows.append(f"| {ids} | {pack.display_name} | {len(pack)} | {origin} |")

    from connector_manager.tools import baseline_pack

    covered = len(tools.connector_ids())
    generated = [
        c.id for c in registry
        if not tools.has(c.id) and baseline_pack(c.id, c.display_name, c.raw) is not None
    ]
    bare = len(registry) - covered - len(generated)
    oauth2 = [c for c in registry if c.auth_mode is AuthMode.OAUTH2]
    oauth2_left = len([c for c in oauth2 if not tools.has(c.id)])

    authored_packs = [p for p in tools.packs if not p.generated]
    spec_packs = [p for p in tools.packs if p.generated]
    authored_tools = sum(len(p) for p in authored_packs)
    spec_tools = sum(len(p) for p in spec_packs)
    from connector_manager import ConnectorManager as _Manager

    manager = _Manager()
    with_check = sum(
        1 for c in registry
        if not tools.has(c.id)
        and any(t.name == "check_connection" for t in manager.list_tools(c.id))
    )
    raw_only = len(registry) - covered - with_check
    all_tools = sum(len(manager.list_tools(c.id)) for c in registry)
    summary = (
        f"**Every one of the {len(registry):,} connectors exposes tools — {all_tools:,} in total.**\n\n"
        f"- **{authored_tools:,} hand-authored** across {len(authored_packs)} packs covering "
        f"{sum(len(p.connector_ids) for p in authored_packs)} connectors, written against the "
        f"providers' own references, with typed inputs and real scope names.\n"
        f"- **{spec_tools:,} generated from providers' published OpenAPI specifications**, across "
        f"{len(spec_packs)} packs.\n"
        f"- **{with_check:,} connectors** get a `check_connection` tool built from the "
        f"verification endpoint their catalogue entry declares.\n"
        f"- **{raw_only:,} connectors** have only the raw authenticated request tools, which "
        f"claim nothing about the provider's API.\n\n"
        f"[TOOLS.md](TOOLS.md) lists every connector and its tools."
    )
    note = (
        f"A pack is always better than the fallbacks: it names real operations instead of "
        f"handing the caller a raw request. {oauth2_left} of the connectors without one are "
        f"OAuth2. Adding a pack is a single file — see\n"
        f"[Adding tools for a connector](#adding-tools-for-a-connector), or let\n"
        f"`scripts/generate_from_openapi.py` build one where the provider publishes a spec."
    )
    return {
        "tool-coverage": "\n".join(rows),
        "tool-coverage-summary": summary,
        "tool-coverage-note": note,
    }


def render_readme(check_only: bool) -> int:
    """Write, or verify, the generated blocks in README.md."""
    text = README.read_text(encoding="utf-8")
    updated = text
    for name, body in coverage_sections().items():
        start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
        if start not in updated or end not in updated:
            print(f"README is missing the {name} markers", file=sys.stderr)
            return 1
        head, _, rest = updated.partition(start)
        _, _, tail = rest.partition(end)
        updated = f"{head}{start}\n{body}\n{end}{tail}"

    if check_only:
        if updated != text:
            print(
                "README's tool coverage is out of date -- run "
                "`python scripts/scaffold_tools.py --readme`.",
                file=sys.stderr,
            )
            return 1
        return 0

    if updated != text:
        README.write_text(updated, encoding="utf-8")
        print(f"updated {display(README)}")
    else:
        print(f"{display(README)} is already up to date")
    return 0


def listing() -> int:
    tools = ToolRegistry(TOOLS_DIR)
    stats = tools.stats()
    for connector_id, count in stats["by_connector"].items():
        pack = tools.get_pack(connector_id)
        also = f"  (also serves {', '.join(pack.applies_to)})" if pack.applies_to else ""
        print(f"{connector_id:<20} {count:>4} tools   {Path(pack.source).parent.name}/{also}")
    print(
        f"\n{stats['tools']} tools across {stats['packs']} packs, "
        f"covering {stats['connectors_covered']} connectors"
    )
    return 0


CATALOGUE = REPO_ROOT / "TOOLS.md"

CATALOGUE_HEADER = """\
# Every connector and its tools

Generated by `python scripts/scaffold_tools.py --catalogue` — do not edit by hand.

{summary}

Tools come from one of four places, shown in the **Source** column:

| Source | What it means |
|---|---|
| `authored` | Hand-authored against the provider's own API reference. Typed inputs, described outputs, real OAuth scope names. |
| `spec` | Generated from the provider's published OpenAPI specification. Real paths and parameters, no scopes, a slice of the API rather than all of it. |
| `verification` | The connector's declared verification endpoint, exposed as `check_connection`. |
| `raw` | The authenticated request itself — `get_from_api` and friends. Claims nothing about which endpoints exist; the caller must know the provider's API. |

A connector shows the best source it has, and every tool it exposes is listed.
The `raw` tools are present on every connector, so they appear alongside a
pack's own tools where one exists.

---

"""


def catalogue(check_only: bool = False) -> int:
    """Write TOOLS.md: one row per connector, listing the tools it has."""
    from connector_manager import ConnectorManager

    manager = ConnectorManager()
    tools = ToolRegistry(TOOLS_DIR)

    rows: list[tuple[str, str, str, str, int, str]] = []
    for connector in sorted(manager.registry, key=lambda c: c.id):
        pack = tools.pack(connector.id)
        names = [t.name for t in manager.list_tools(connector.id)]
        if pack and not pack.generated:
            source = "authored"
        elif pack:
            source = "spec"
        elif "check_connection" in names:
            source = "verification"
        else:
            source = "raw"
        rows.append((
            connector.id, connector.display_name, connector.auth_mode.value,
            source, len(names), ", ".join(f"`{n}`" for n in names),
        ))

    by_source: dict[str, int] = {}
    for row in rows:
        by_source[row[3]] = by_source.get(row[3], 0) + 1
    total_tools = sum(r[4] for r in rows)
    summary = (
        f"**{len(rows):,} connectors, {total_tools:,} tools.** "
        + ", ".join(f"{count:,} {source}" for source, count in sorted(by_source.items(), key=lambda kv: -kv[1]))
        + "."
    )

    lines = [CATALOGUE_HEADER.format(summary=summary)]
    lines.append("| Connector | Provider | Auth | Source | Tools | Tool names |")
    lines.append("|---|---|---|---|---:|---|")
    for connector_id, display, auth, source, count, names in rows:
        lines.append(f"| `{connector_id}` | {display} | {auth} | {source} | {count} | {names} |")
    body = "\n".join(lines) + "\n"

    if check_only:
        if not CATALOGUE.exists() or CATALOGUE.read_text(encoding="utf-8") != body:
            print(
                "TOOLS.md is out of date -- run `python scripts/scaffold_tools.py --catalogue`.",
                file=sys.stderr,
            )
            return 1
        return 0

    if CATALOGUE.exists() and CATALOGUE.read_text(encoding="utf-8") == body:
        print(f"{display_path(CATALOGUE)} is already up to date")
    else:
        CATALOGUE.write_text(body, encoding="utf-8")
        print(f"wrote {display_path(CATALOGUE)}: {len(rows):,} connectors, {total_tools:,} tools")
    return 0


def backlog(limit: int | None = None, category: str | None = None) -> int:
    """What still needs a hand-authored pack, most-connected categories first.

    Splits the catalogue three ways so the next session can pick up without
    re-deriving anything: connectors with a researched pack, connectors running
    on the generated ``check_connection`` tool, and connectors with nothing at
    all because their entry declares no endpoint to build from.
    """
    from collections import Counter

    from connector_manager import ConnectorRegistry as _Registry
    from connector_manager.tools import baseline_pack

    registry = _Registry()
    tools = ToolRegistry(TOOLS_DIR)

    authored, generated, bare = [], [], []
    for connector in registry:
        if tools.has(connector.id):
            authored.append(connector)
        elif baseline_pack(connector.id, connector.display_name, connector.raw):
            generated.append(connector)
        else:
            bare.append(connector)

    print(f"authored packs        : {len(authored):>5} connectors, {tools.total_tools()} tools")
    print(f"generated check only  : {len(generated):>5} connectors")
    print(f"no tool at all        : {len(bare):>5} connectors")
    print()

    todo = [c for c in generated + bare if not category or category in c.categories]
    if category:
        print(f"filtered to category {category!r}: {len(todo)} connectors\n")

    by_category: dict[str, list] = {}
    for connector in todo:
        for name in connector.categories or ["uncategorised"]:
            by_category.setdefault(name, []).append(connector)

    order = [c for c, _ in Counter({k: len(v) for k, v in by_category.items()}).most_common()]
    shown = 0
    for name in order:
        entries = sorted(by_category[name], key=lambda c: c.id)
        print(f"## {name}  ({len(entries)})")
        for connector in entries:
            state = "generated" if baseline_pack(connector.id, connector.display_name, connector.raw) else "none"
            print(f"  {connector.id:<42} {connector.auth_mode.value:<12} {state:<10} {connector.base_url or '-'}")
            shown += 1
            if limit and shown >= limit:
                print(f"\n... stopped at --limit {limit}")
                return 0
        print()
    return 0


def display_path(path: Path) -> str:
    """Repo-relative when it lives in the repo, absolute otherwise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:  # pragma: no cover - a path outside the repo
        return str(path)


def display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:  # pragma: no cover - a path outside the repo
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--new", metavar="CONNECTOR_ID", help="write a tool pack skeleton")
    group.add_argument("--check", action="store_true", help="validate the bundled packs")
    group.add_argument("--list", action="store_true", help="show what is covered so far")
    group.add_argument("--readme", action="store_true", help="refresh README's coverage table")
    group.add_argument("--backlog", action="store_true", help="list the connectors still needing a pack")
    group.add_argument("--catalogue", action="store_true", help="write TOOLS.md, every connector and its tools")
    parser.add_argument("--force", action="store_true", help="overwrite an existing pack with --new")
    parser.add_argument(
        "--path", type=Path, action="append", help="with --check, validate only these files"
    )
    parser.add_argument("--limit", type=int, help="with --backlog, stop after this many rows")
    parser.add_argument("--category", help="with --backlog, only this catalogue category")
    args = parser.parse_args()

    if args.new:
        return scaffold(args.new, ConnectorRegistry(), args.force)
    if args.check:
        return check(args.path) or render_readme(check_only=True) or catalogue(check_only=True)
    if args.readme:
        return render_readme(check_only=False)
    if args.backlog:
        return backlog(limit=args.limit, category=args.category)
    if args.catalogue:
        return catalogue()
    return listing()


if __name__ == "__main__":
    raise SystemExit(main())
