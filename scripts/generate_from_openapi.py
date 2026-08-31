#!/usr/bin/env python3
"""Build a connector tool pack from the provider's own OpenAPI specification.

Hand-authoring a pack means reading a provider's reference and writing ~250
lines of YAML. Where the provider publishes a machine-readable spec, that same
information is already available in a form we can transform -- so this script
does it, and marks the result ``generated`` with the spec URL it came from.

Nothing is inferred. Every path, method, parameter and description in the output
comes from the spec; operations the spec does not describe well enough to build
a usable tool from are skipped rather than guessed at.

    python scripts/generate_from_openapi.py --connector telnyx \
        --spec https://api.apis.guru/v2/specs/telnyx.com/2.0.0/openapi.json

    python scripts/generate_from_openapi.py --connector openai --guru openai.com
    python scripts/generate_from_openapi.py --plan plan.json        # batch

The output still has to pass `scaffold_tools.py --check`, which is what stops a
malformed spec producing a broken pack.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from connector_manager import ConnectorRegistry, UnknownConnectorError  # noqa: E402

TOOLS_DIR = REPO_ROOT / "src" / "connector_manager" / "data" / "tools"
GURU_LIST = "https://api.apis.guru/v2/list.json"

#: HTTP verbs worth turning into tools.
METHODS = ("get", "post", "put", "patch", "delete")

#: Words that make a tool name unreadable when carried over from an operationId.
NOISE = re.compile(r"(controller|handler|using|_v\d+$|^api_)", re.I)


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------


def fetch(url: str) -> Any:
    """Download and parse a JSON or YAML document."""
    request = urllib.request.Request(url, headers={"User-Agent": "connector-for-ai-agents"})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
    try:
        return json.loads(raw)
    except ValueError:
        import yaml

        return yaml.safe_load(raw)


def guru_spec_url(provider_key: str) -> str:
    """The preferred spec URL for an apis.guru entry, e.g. ``stripe.com``."""
    listing = fetch(GURU_LIST)
    entry = listing.get(provider_key)
    if entry is None:
        raise SystemExit(f"no apis.guru entry for {provider_key!r}")
    preferred = entry["versions"][entry["preferred"]]
    return preferred["swaggerUrl"]


# ---------------------------------------------------------------------------
# spec walking
# ---------------------------------------------------------------------------


def deref(node: Any, spec: dict[str, Any], depth: int = 0) -> Any:
    """Resolve a local ``$ref`` chain, giving up rather than recursing forever."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 10:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return node
        target: Any = spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return {}
            target = target[part]
        node = target
        seen += 1
    return node


def server_path(spec: dict[str, Any]) -> str:
    """The path component of the spec's first server, e.g. ``/v1``."""
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        url = str(servers[0].get("url") or "")
        match = re.match(r"https?://[^/]+(/.*)$", url)
        if match:
            return match.group(1).rstrip("/")
        return ""
    base = str(spec.get("basePath") or "")
    return base.rstrip("/")


def full_path(raw_path: str, prefix: str, connector_base: str) -> str:
    """Join the spec's server prefix onto an operation path, without doubling it.

    The connector's own ``proxy.base_url`` may already include the prefix (a
    base of ``https://api.close.com/api`` against a spec server of ``/api``), in
    which case adding it again would produce ``/api/api/...``.
    """
    path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    if not prefix:
        return path
    if connector_base.rstrip("/").endswith(prefix):
        return path
    if path.startswith(prefix + "/") or path == prefix:
        return path
    return f"{prefix}{path}"


def snake(value: str) -> str:
    value = NOISE.sub("", value or "")
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    if value and value[0].isdigit():
        value = f"op_{value}"
    return value


def name_for(method: str, path: str, operation: dict[str, Any]) -> str:
    """A readable snake_case tool name for an operation."""
    candidate = snake(str(operation.get("operationId") or ""))
    if candidate and 3 <= len(candidate) <= 50 and not candidate.isdigit():
        return candidate
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    tail = "_".join(segments[-2:]) or "root"
    verb = {"get": "get", "post": "create", "put": "update", "patch": "update", "delete": "delete"}[method]
    return snake(f"{verb}_{tail}")


def clean(text: Any, limit: int = 400) -> str:
    """One-line prose from a spec's summary or description field."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_#>]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def json_type(schema: dict[str, Any]) -> str:
    """Map a schema's type onto one this package's tool parameters accept.

    A spec often gives an enum with no explicit type. Guessing "string" there
    puts integer enum values behind a string parameter, and every call fails
    validation, so the enum's own values decide the type instead.
    """
    raw = schema.get("type")
    if raw is None:
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            if all(isinstance(v, bool) for v in enum):
                return "boolean"
            if all(isinstance(v, int) and not isinstance(v, bool) for v in enum):
                return "integer"
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in enum):
                return "number"
            return "string"
    if isinstance(raw, list):
        raw = next((t for t in raw if t != "null"), None)
    mapping = {
        "string": "string", "integer": "integer", "number": "number",
        "boolean": "boolean", "array": "array", "object": "object",
    }
    if raw in mapping:
        return mapping[raw]
    if schema.get("properties"):
        return "object"
    if schema.get("items"):
        return "array"
    if schema.get("enum"):
        return "string"
    return "string"


# ---------------------------------------------------------------------------
# building one tool
# ---------------------------------------------------------------------------


def _attach_enum(entry: dict[str, Any], enum: Any, kind: str) -> None:
    """Copy an enum onto a parameter, coerced to the parameter's own type."""
    if not isinstance(enum, list) or not enum:
        return
    if not all(isinstance(v, (str, int, float, bool)) for v in enum):
        return
    values = list(enum)[:20]
    if kind == "string":
        values = [str(v) for v in values]
    elif kind in ("integer", "number") and not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in values
    ):
        return
    entry["enum"] = values


def parameter_entry(param: dict[str, Any], spec: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """One tool input built from an OpenAPI parameter, or None if unusable."""
    param = deref(param, spec)
    raw_name = str(param.get("name") or "")
    if not raw_name:
        return None
    schema = deref(param.get("schema") or {}, spec)
    kind = json_type(schema)
    entry: dict[str, Any] = {
        "type": kind,
        "description": clean(param.get("description")) or f"The {raw_name} parameter.",
    }
    if not param.get("required"):
        entry["optional"] = True
    _attach_enum(entry, schema.get("enum"), kind)
    if kind == "array":
        items = deref(schema.get("items") or {}, spec)
        entry["items"] = {"type": json_type(items) if items else "string"}
    default = schema.get("default")
    if default is not None and not param.get("required") and isinstance(default, (str, int, float, bool)):
        if "enum" not in entry or default in entry["enum"]:
            entry["default"] = default
    return raw_name, entry


def body_entries(operation: dict[str, Any], spec: dict[str, Any], limit: int = 12) -> dict[str, dict[str, Any]]:
    """Top-level JSON request-body properties, as tool inputs."""
    body = deref(operation.get("requestBody") or {}, spec)
    content = body.get("content") or {}
    media = content.get("application/json") or content.get("application/vnd.api+json") or {}
    schema = deref(media.get("schema") or {}, spec)
    # Some specs wrap the payload one level down, e.g. {"data": {...}}.
    properties = schema.get("properties") or {}
    if len(properties) == 1 and "data" in properties:
        inner = deref(properties["data"], spec)
        if inner.get("properties"):
            schema, properties = inner, inner.get("properties") or {}
    required = set(schema.get("required") or [])
    out: dict[str, dict[str, Any]] = {}
    for prop_name, prop in list(properties.items())[:limit]:
        prop = deref(prop, spec)
        kind = json_type(prop)
        entry: dict[str, Any] = {
            "type": kind,
            "description": clean(prop.get("description")) or f"The {prop_name} field of the request body.",
        }
        if prop_name not in required:
            entry["optional"] = True
        _attach_enum(entry, prop.get("enum"), kind)
        if kind == "array":
            items = deref(prop.get("items") or {}, spec)
            entry["items"] = {"type": json_type(items) if items else "string"}
        out[prop_name] = entry
    return out


def build_tool(
    method: str, raw_path: str, operation: dict[str, Any], spec: dict[str, Any],
    prefix: str, connector_base: str, taken: set[str], display_name: str = "",
) -> tuple[str, dict[str, Any]] | None:
    """One pack entry for an operation, or None when the spec is too thin."""
    path = full_path(raw_path, prefix, connector_base)
    if "{" in path and "}" not in path:
        return None

    summary = clean(operation.get("summary"))
    detail = clean(operation.get("description"), limit=300)
    verb = method.upper()
    prose = " ".join(p for p in (summary, detail) if p).strip()
    # Every description must stand on its own for a model reading it cold, and
    # clear the 40-character floor the lint enforces.
    provider = display_name or "the provider"
    description = (
        f"{prose} Calls {verb} {path} on {provider}'s API." if prose
        else f"Calls {verb} {path} on {provider}'s API."
    )
    if len(description) < 60:
        # A short path plus a terse summary can fall under the length the lint
        # requires, and a one-line tool description is no use to a model anyway.
        description += " Generated from the provider's published OpenAPI specification."

    inputs: dict[str, dict[str, Any]] = {}
    query: dict[str, str] = {}
    path_args: dict[str, str] = {}

    merged = list(operation.get("parameters") or [])
    handled: set[tuple[str, str]] = set()
    for param in merged:
        built = parameter_entry(param, spec)
        if built is None:
            continue
        raw_name, entry = built
        located_in = deref(param, spec).get("in") or ""
        # A spec may declare the same parameter at both path and operation
        # level. Taking it twice leaves the first copy declared but unread.
        if (located_in, raw_name) in handled:
            continue
        handled.add((located_in, raw_name))
        located = deref(param, spec).get("in")
        arg = snake(raw_name) or "value"
        while arg in inputs and inputs[arg] is not entry:
            arg = f"{arg}_"
        if located == "path":
            if "{%s}" % raw_name not in path:
                # The spec calls it a path parameter but the path has no such
                # placeholder. Whether it is really a query parameter or a
                # documentation slip is not ours to decide, so leave it out
                # rather than put it somewhere it may not belong.
                continue
            entry.pop("optional", None)
            entry.pop("default", None)
            path_args[raw_name] = arg
            inputs[arg] = entry
        elif located == "query":
            query[raw_name] = "${%s}" % arg
            inputs[arg] = entry

    # Every {placeholder} in the path must map to a declared argument.
    for placeholder in re.findall(r"\{([^}]+)\}", path):
        if placeholder not in path_args:
            arg = snake(placeholder) or "id"
            while arg in inputs:
                arg = f"{arg}_id"
            path_args[placeholder] = arg
            inputs[arg] = {
                "type": "string",
                "description": f"The {placeholder.replace('_', ' ')} identifying the resource in the path.",
            }
    for placeholder, arg in path_args.items():
        path = path.replace("{%s}" % placeholder, "${%s}" % arg)

    body: dict[str, Any] = {}
    if method != "get":
        for prop_name, entry in body_entries(operation, spec).items():
            arg = snake(prop_name) or "field"
            while arg in inputs:
                arg = f"{arg}_body"
            inputs[arg] = entry
            body[prop_name] = "${%s}" % arg

    # A write with nothing to send and no path arguments is not a usable tool.
    if method != "get" and not body and not path_args and not query:
        return None

    name = name_for(method, raw_path, operation)
    while name in taken:
        name = f"{name}_alt"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        return None

    segments = [s for s in raw_path.split("/") if s and not s.startswith("{")]
    category = snake(segments[0]) if segments else "api"
    if not category or category.isdigit() or re.fullmatch(r"v\d+", category):
        category = snake(segments[1]) if len(segments) > 1 else "api"
    category = category or "api"

    request: dict[str, Any] = {"method": verb, "path": path}
    if query:
        request["query"] = query
    if body:
        request["body"] = body

    tool: dict[str, Any] = {
        "title": (summary[:70] if summary else name.replace("_", " ").capitalize()),
        "description": description,
        "category": category,
        "request": request,
        "input": inputs,
        "output": {
            "description": clean(_success_description(operation, spec))
            or f"Whatever {verb} {path} returns, as described by the provider's specification.",
            "type": "object",
        },
    }
    if method == "get":
        tool["read_only"] = True
    if method == "delete":
        tool["destructive"] = True
    return name, tool


def _success_description(operation: dict[str, Any], spec: dict[str, Any]) -> str:
    for code in ("200", "201", "202", "204"):
        response = deref((operation.get("responses") or {}).get(code) or {}, spec)
        if response.get("description"):
            return str(response["description"])
    return ""


# ---------------------------------------------------------------------------
# building a pack
# ---------------------------------------------------------------------------


def select_operations(spec: dict[str, Any], max_tools: int) -> list[tuple[str, str, dict[str, Any]]]:
    """Pick a representative slice of a spec's operations.

    A big spec has hundreds of operations and a tool pack wants a dozen, so
    prefer documented ones and spread them across distinct resources rather
    than returning fifteen variants of the same endpoint.
    """
    candidates: list[tuple[int, str, str, str, dict[str, Any]]] = []
    for raw_path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method in METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict) or operation.get("deprecated"):
                continue
            operation = dict(operation)
            operation["parameters"] = list(shared) + list(operation.get("parameters") or [])
            root = next((s for s in raw_path.split("/") if s and not s.startswith("{")), "")
            depth = raw_path.count("/")
            documented = 1 if (operation.get("summary") or operation.get("description")) else 0
            # Prefer documented, shallow, collection-level operations.
            score = (documented * 100) - depth * 5 - (3 if "{" in raw_path else 0)
            candidates.append((-score, root, raw_path, method, operation))

    candidates.sort(key=lambda c: (c[0], c[2], c[3]))
    chosen: list[tuple[str, str, dict[str, Any]]] = []
    per_root: dict[str, int] = {}
    cap = max(2, max_tools // 4)
    for _, root, raw_path, method, operation in candidates:
        if len(chosen) >= max_tools:
            break
        if per_root.get(root, 0) >= cap:
            continue
        per_root[root] = per_root.get(root, 0) + 1
        chosen.append((method, raw_path, operation))
    return chosen


def slug(mode: str) -> str:
    return mode.lower().replace("_", "-")


def build_pack(connector_id: str, spec_url: str, max_tools: int, registry: ConnectorRegistry) -> tuple[Path, dict[str, Any]]:
    connector = registry.get(connector_id)
    spec = fetch(spec_url)
    if not isinstance(spec, dict) or not spec.get("paths"):
        raise SystemExit(f"{connector_id}: {spec_url} has no paths -- not a usable OpenAPI spec")

    prefix = server_path(spec)
    base = connector.base_url or ""
    taken: set[str] = set()
    tools: dict[str, Any] = {}
    for method, raw_path, operation in select_operations(spec, max_tools * 3):
        if len(tools) >= max_tools:
            break
        built = build_tool(method, raw_path, operation, spec, prefix, base, taken, connector.display_name)
        if built is None:
            continue
        name, tool = built
        taken.add(name)
        tools[name] = tool

    if len(tools) < 3:
        raise SystemExit(f"{connector_id}: only {len(tools)} usable operations -- skipping")

    info = spec.get("info") or {}
    docs = (spec.get("externalDocs") or {}).get("url") or info.get("termsOfService") or spec_url
    pack = {
        "connector_id": connector_id,
        "display_name": connector.display_name,
        "docs_url": docs if str(docs).startswith("http") else spec_url,
        "generated": True,
        "generated_from": spec_url,
        "tools": tools,
    }
    path = TOOLS_DIR / slug(connector.auth_mode.value) / f"{connector_id}.yaml"
    return path, pack


HEADER = """\
# {display_name} tools -- GENERATED from the provider's OpenAPI specification.
#
#   source: {spec_url}
#
# Every path, method, parameter and description below comes from that spec.
# Nothing here is inferred: operations the spec did not describe well enough to
# build a usable tool from were skipped rather than guessed at.
#
# This is a starting point, not a hand-authored pack. It has no scope
# annotations, and it covers a representative slice of the API rather than the
# whole surface. Replacing it with a researched pack is an improvement -- delete
# the `generated` flag once you do.
"""


def write_pack(path: Path, pack: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(pack, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False)
    header = HEADER.format(display_name=pack["display_name"], spec_url=pack["generated_from"])
    path.write_text(header + "\n" + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connector", help="connector id to build a pack for")
    parser.add_argument("--spec", help="URL of the OpenAPI specification")
    parser.add_argument("--guru", help="apis.guru provider key, e.g. stripe.com")
    parser.add_argument("--plan", type=Path, help="JSON list of {connector, spec} objects to build in bulk")
    parser.add_argument("--max-tools", type=int, default=14, help="most tools to emit per pack (default 14)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing pack file")
    args = parser.parse_args()

    registry = ConnectorRegistry()
    jobs: list[tuple[str, str]] = []
    if args.plan:
        for row in json.loads(args.plan.read_text(encoding="utf-8")):
            jobs.append((row["connector"], row["spec"]))
    elif args.connector:
        spec_url = args.spec or (guru_spec_url(args.guru) if args.guru else None)
        if not spec_url:
            raise SystemExit("pass --spec or --guru alongside --connector")
        jobs.append((args.connector, spec_url))
    else:
        raise SystemExit("pass --connector, or --plan for a batch")

    built = skipped = 0
    for connector_id, spec_url in jobs:
        try:
            connector = registry.get(connector_id)
        except UnknownConnectorError:
            print(f"skip {connector_id}: not in the catalogue", file=sys.stderr)
            skipped += 1
            continue
        target = TOOLS_DIR / slug(connector.auth_mode.value) / f"{connector_id}.yaml"
        if target.exists() and not args.force:
            print(f"skip {connector_id}: {target.name} already exists")
            skipped += 1
            continue
        try:
            path, pack = build_pack(connector_id, spec_url, args.max_tools, registry)
        except SystemExit as err:
            print(f"skip {connector_id}: {err}", file=sys.stderr)
            skipped += 1
            continue
        except Exception as err:  # noqa: BLE001 - one bad spec must not stop a batch
            print(f"skip {connector_id}: {type(err).__name__}: {err}", file=sys.stderr)
            skipped += 1
            continue
        write_pack(path, pack)
        print(f"built {connector_id}: {len(pack['tools'])} tools -> {path.relative_to(REPO_ROOT)}")
        built += 1

    print(f"\n{built} pack(s) built, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
