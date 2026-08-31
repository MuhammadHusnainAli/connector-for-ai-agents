#!/usr/bin/env python3
"""Build a connector tool pack from a Google API discovery document.

Google publishes a machine-readable description of every one of its APIs --
paths, HTTP methods, parameters with their types, enums and defaults, and,
uniquely useful here, *the OAuth scopes each individual method requires*. That
last part is what a normal OpenAPI spec cannot give us: it lets a generated
pack carry real, per-tool scope annotations, so `check_tools()` can tell a
caller which Google tools their grant actually permits.

    python scripts/generate_from_google_discovery.py \
        --connector google-tasks \
        --discovery "https://tasks.googleapis.com/\\$discovery/rest?version=v1"

Nothing is invented. Paths, descriptions, parameters and scopes all come from
the document. What the script adds is presentation: readable snake_case tool
names in place of Google's dotted method ids (`tasklists.insert` becomes
`create_task_list`), a category per resource, and read-only/destructive hints
taken from the HTTP verb.

The output still has to pass `scaffold_tools.py --check`.
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

from connector_manager import ConnectorRegistry  # noqa: E402

TOOLS_DIR = REPO_ROOT / "src" / "connector_manager" / "data" / "tools"

#: Google scope URLs all share this root; the packs store the short form.
SCOPE_ROOT = "https://www.googleapis.com/auth/"

#: Discovery verb -> the word an agent-facing tool name should use.
VERBS = {
    "list": "list", "get": "get", "insert": "create", "create": "create",
    # Google offers both: `patch` is the partial update, `update` the full
    # replacement, so they must not collapse to the same tool name.
    "patch": "update", "update": "replace", "delete": "delete", "batchUpdate": "batch_update",
    "batchGet": "batch_get", "search": "search", "query": "query", "clear": "clear",
    "move": "move", "copy": "copy", "watch": "watch", "stop": "stop", "trash": "trash",
    "untrash": "untrash", "import": "import", "export": "export", "send": "send",
}

#: Type names discovery uses -> the JSON Schema types a tool parameter may declare.
TYPES = {
    "string": "string", "integer": "integer", "number": "number",
    "boolean": "boolean", "array": "array", "object": "object", "any": "object",
}

#: A request schema wider than this is passed through as one object argument
#: rather than exploded into fields, which keeps a tool's schema readable.
MAX_BODY_FIELDS = 24


def fetch(url: str) -> dict[str, Any]:
    """The discovery document, from Google or from a local copy of one."""
    if not url.startswith(("http://", "https://")):
        return json.loads(Path(url).read_text(encoding="utf-8"))
    request = urllib.request.Request(url, headers={"User-Agent": "connector-for-ai-agents"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read())


def snake(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_").lower()


#: Resources Google spells as one word but that read as two in a tool name.
COMPOUND = {
    "tasklists": "task_list", "tasklist": "task_list",
    "calendarList": "calendar_list", "freebusy": "free_busy",
    "spreadsheets": "spreadsheet", "presentations": "presentation",
    "otherContacts": "other_contact", "contactGroups": "contact_group",
    "changes": "change", "revisions": "revision", "permissions": "permission",
}


def singular(word: str) -> str:
    """`tasklists` -> `task_list`, `messages` -> `message`, `status` unchanged."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("sses") or word.endswith("shes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and not word.endswith("us"):
        return word[:-1]
    return word


def methods_of(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every method in the document, keyed by its dotted discovery id."""
    found: list[tuple[str, dict[str, Any]]] = []

    def walk(resources: dict[str, Any] | None, prefix: str) -> None:
        for name, resource in (resources or {}).items():
            for method_name, method in (resource.get("methods") or {}).items():
                found.append((f"{prefix}{name}.{method_name}", method))
            walk(resource.get("resources"), f"{prefix}{name}.")

    walk(document.get("resources"), "")
    for method_name, method in (document.get("methods") or {}).items():
        found.append((method_name, method))
    return sorted(found)


def tool_name(method_id: str, taken: set[str], overrides: dict[str, str]) -> str:
    """`tasklists.insert` -> `create_task_list`; collisions get their resource back."""
    if method_id in overrides:
        return overrides[method_id]
    parts = method_id.split(".")
    verb_raw, resource_parts = parts[-1], parts[:-1]
    verb = VERBS.get(verb_raw, snake(verb_raw))
    resource = resource_parts[-1] if resource_parts else ""
    if resource in COMPOUND:
        noun = COMPOUND[resource] + ("s" if verb == "list" else "")
    else:
        noun = snake(singular(resource)) if verb != "list" else snake(resource)
    # A parent resource disambiguates `messages.list` from `drafts.list` only
    # when the leaf alone is already taken.
    name = f"{verb}_{noun}".strip("_") or snake(method_id)
    if name in taken and len(resource_parts) > 1:
        name = f"{verb}_{snake(resource_parts[-2])}_{noun}"
    suffix = 2
    base = name
    while name in taken:
        name = f"{base}_{suffix}"
        suffix += 1
    return name


def clean(text: Any, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # Discovery descriptions are peppered with markdown links to guides; the
    # prose is what a model needs, not the URL.
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = text.replace("`", "")
    return text[:limit].strip()


def param_entry(name: str, spec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    entry: dict[str, Any] = {"type": TYPES.get(spec.get("type"), "string")}
    if entry["type"] == "array":
        items = spec.get("items") or {}
        entry["items"] = {"type": TYPES.get(items.get("type"), "string")}
    description = clean(spec.get("description"), 300)
    entry["description"] = description or f"The {name.replace('_', ' ')}."
    if not spec.get("required"):
        entry["optional"] = True
        if spec.get("default") is not None:
            default = spec["default"]
            if entry["type"] == "integer":
                try:
                    default = int(default)
                except (TypeError, ValueError):
                    default = None
            elif entry["type"] == "boolean":
                default = str(default).lower() == "true"
            if default is not None:
                entry["default"] = default
    if spec.get("enum"):
        entry["enum"] = [str(value) for value in spec["enum"]]
        if entry.get("default") is not None and str(entry["default"]) not in entry["enum"]:
            entry.pop("default")
    return name, entry


def body_fields(schema_ref: str, document: dict[str, Any]) -> dict[str, Any] | None:
    """The named schema's own properties, when there are few enough to be useful."""
    schema = (document.get("schemas") or {}).get(schema_ref) or {}
    properties = schema.get("properties") or {}
    usable = {
        name: spec for name, spec in properties.items()
        if not spec.get("readOnly") and name not in ("etag", "kind", "id")
    }
    if not usable or len(usable) > MAX_BODY_FIELDS:
        return None
    return usable


def build_tool(
    method_id: str,
    method: dict[str, Any],
    document: dict[str, Any],
    service_path: str,
    name: str,
    base_url: str = "",
) -> dict[str, Any]:
    http = (method.get("httpMethod") or "GET").upper()
    path = "/" + "/".join(p for p in (service_path.strip("/"), method.get("path", "")) if p)
    path = re.sub(r"/+", "/", path)

    inputs: dict[str, Any] = {}
    query: dict[str, str] = {}
    argument_for: dict[str, str] = {}
    parameters = method.get("parameters") or {}

    # Path parameters first, so a tool's required arguments read in URL order.
    ordered = sorted(parameters, key=lambda p: (parameters[p].get("location") != "path", p))
    for raw_name in ordered:
        spec = parameters[raw_name]
        if spec.get("location") not in ("path", "query"):
            continue
        argument = snake(raw_name)
        argument_for[raw_name] = argument
        key, entry = param_entry(argument, spec)
        # A path parameter is structurally required even where discovery gives
        # it a default, since the URL cannot be built without it.
        if spec.get("location") == "path":
            entry.pop("optional", None)
            entry.pop("default", None)
        inputs[key] = entry
        if spec.get("location") == "query":
            query[raw_name] = "${%s}" % argument

    # Discovery writes a path segment that may itself contain slashes as
    # `{+name}` -- URI Template reserved expansion -- and a plain one as
    # `{name}`. Both bind to the same argument. This substitutes in a single
    # pass: replacing them one at a time would rewrite the `${name}` a previous
    # replacement had just produced.
    path = re.sub(
        r"\{\+?([A-Za-z_0-9.]+)\}",
        lambda m: "${%s}" % argument_for.get(m.group(1), snake(m.group(1))),
        path,
    )

    request: dict[str, Any] = {"method": http, "path": path}
    if base_url:
        # The connector's own base url does not serve this API -- Play's routes
        # live on androidpublisher.googleapis.com, not play.googleapis.com --
        # so each tool addresses the host the discovery document names.
        request["base_url_override"] = base_url
    if query:
        request["query"] = query

    body_ref = (method.get("request") or {}).get("$ref")
    if body_ref and http in ("POST", "PUT", "PATCH"):
        fields = body_fields(body_ref, document)
        if fields:
            body: dict[str, Any] = {}
            for raw_name, spec in fields.items():
                argument = snake(raw_name)
                if argument in inputs:
                    argument = f"body_{argument}"
                key, entry = param_entry(argument, {**spec, "required": False})
                inputs[key] = entry
                body[raw_name] = "${%s}" % argument
            request["body"] = body
        else:
            inputs["body"] = {
                "type": "object",
                "description": f"The {body_ref} resource, as the API's own reference defines it.",
            }
            request["body"] = "${body}"

    scopes = [s.replace(SCOPE_ROOT, "") for s in (method.get("scopes") or [])]
    description = clean(method.get("description"))
    if len(description) < 40:
        # The lint floor exists so a tool is never a bare verb; where Google
        # left the method undocumented, name what it calls instead.
        suffix = f"Calls {method_id} on the {document.get('title', 'API')}."
        description = f"{description} {suffix}".strip() if description else suffix

    words = name.split("_")
    title = " ".join([words[0].capitalize(), *words[1:]])
    tool: dict[str, Any] = {
        "title": title,
        "description": description,
        "category": snake(method_id.split(".")[0]),
        "request": request,
        "input": inputs,
        "output": {
            "description": clean(
                (method.get("response") or {}).get("$ref")
                and f"The {(method['response'])['$ref']} resource."
                or "What the API returned."
            ) or "What the API returned.",
            "type": "object",
        },
    }
    if len(scopes) == 1:
        tool["scopes"] = scopes
    elif scopes:
        tool["scopes_any"] = scopes
    if http == "GET":
        tool["read_only"] = True
    if http == "DELETE":
        tool["destructive"] = True
    return tool


def build_pack(connector_id: str, url: str, overrides: dict[str, str], skip: set[str], base_url: str = "") -> dict[str, Any]:
    document = fetch(url)
    registry = ConnectorRegistry()
    connector = registry.get(connector_id)
    service_path = document.get("servicePath") or ""

    taken: set[str] = set()
    tools: dict[str, Any] = {}
    for method_id, method in methods_of(document):
        if method_id in skip:
            continue
        name = tool_name(method_id, taken, overrides)
        taken.add(name)
        tools[name] = build_tool(method_id, method, document, service_path, name, base_url)

    scope_names = sorted({
        s for tool in tools.values() for s in (tool.get("scopes", []) + tool.get("scopes_any", []))
    })
    implies: dict[str, list[str]] = {}
    for scope in scope_names:
        readonly = f"{scope}.readonly"
        if readonly in scope_names:
            implies[scope] = [readonly]

    pack: dict[str, Any] = {
        "connector_id": connector_id,
        "display_name": connector.display_name,
        "docs_url": document.get("documentationLink") or url,
    }
    # An API key carries no scope grant, so scope rules and Google's token
    # introspection endpoint have nothing to say about one.
    if connector.auth_mode.value.startswith("OAUTH") and scope_names:
        pack["scope_rules"] = {
            "strip_prefixes": [SCOPE_ROOT],
            **({"implies": implies} if implies else {}),
        }
        pack["scope_discovery"] = {
            "method": "GET",
            "base_url_override": "https://oauth2.googleapis.com",
            "endpoint": "/tokeninfo",
            "query": {"access_token": "${credentials.access_token}"},
            "scopes_path": "scope",
        }
    else:
        for tool in tools.values():
            tool.pop("scopes", None)
            tool.pop("scopes_any", None)
    pack["tools"] = tools
    return pack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connector", required=True)
    parser.add_argument("--discovery", required=True, help="Discovery document URL or local path")
    parser.add_argument("--out", help="Where to write (defaults to the auth-mode folder)")
    parser.add_argument("--rename", action="append", default=[], metavar="METHOD_ID=tool_name")
    parser.add_argument("--skip", action="append", default=[], metavar="METHOD_ID")
    parser.add_argument(
        "--base-url",
        default="",
        help="Set base_url_override on every tool, for an API the connector's own base url does not serve",
    )
    args = parser.parse_args()

    overrides = dict(pair.split("=", 1) for pair in args.rename)
    pack = build_pack(args.connector, args.discovery, overrides, set(args.skip), args.base_url)

    import yaml

    registry = ConnectorRegistry()
    mode = registry.get(args.connector).auth_mode.value.lower().replace("_", "-")
    path = Path(args.out) if args.out else TOOLS_DIR / mode / f"{args.connector}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(pack, sort_keys=False, width=100, allow_unicode=True), encoding="utf-8")
    print(f"wrote {path}: {len(pack['tools'])} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
