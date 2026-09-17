"""Loads the bundled tool packs.

Layout, mirroring the connector catalogue's one-file-per-auth-mode sharding::

    data/tools/<auth-mode>/<connector-id>.json

so ``data/tools/oauth2/hubspot.json`` holds every HubSpot tool and nothing else.
Adding a connector's tools means adding one file -- no code change, no registry
edit. :mod:`scripts.scaffold_tools` writes the skeleton and ``--check``
validates placement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from ..errors import UnknownToolError
from .models import (
    ScopeDiscoverySpec,
    ScopeRules,
    Tool,
    ToolOutput,
    ToolPack,
    ToolParameter,
    ToolRequest,
)

#: Name of the tool synthesised from a connector's declared verification endpoint.
BASELINE_TOOL = "check_connection"

#: The authenticated escape-hatch tools every connector with a base url gets.
#: They make no claim about which endpoints exist -- they expose the request the
#: manager can already make, so a connector with no pack is still drivable.
#: Connection-config field names that hold the address of the API itself, for
#: connectors whose endpoint is configured per connection rather than fixed.
ENDPOINT_FIELDS = (
    "mcp_server_url", "base_url", "server_url", "api_url", "instance_url",
    "endpoint", "endpoint_url", "api_domain", "url",
)

RAW_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("get_from_api", "GET", "Read from"),
    ("post_to_api", "POST", "Send data to"),
    ("put_to_api", "PUT", "Replace a resource at"),
    ("patch_api", "PATCH", "Partially update a resource at"),
    ("delete_from_api", "DELETE", "Delete a resource at"),
)


def _data_dir() -> Path:
    try:
        from importlib.resources import files

        return Path(str(files("connector_manager") / "data"))
    except Exception:  # pragma: no cover - fallback for exotic loaders
        return Path(__file__).parent.parent / "data"


#: Root of the bundled tool packs, one JSON file per connector.
TOOLS_DIR = _data_dir() / "tools"
#: Name of the index living beside them: connector id -> the one pack file that
#: serves it, plus each pack's tool count. With it, opening a connector's tools
#: reads a single small file; without it the only way to find the pack claiming
#: an ``applies_to`` alias is to open all 406, which was 12s of cold start.
#: Maintained by ``scripts/build_index.py``.
INDEX_NAME = "index.json"


class ToolRegistry:
    """Read-only index of every tool pack shipped with the package.

    >>> tools = ToolRegistry()
    >>> "hubspot" in tools
    True
    >>> tools.tool("outlook", "send_email").request.method     # via applies_to
    'POST'
    """

    def __init__(self, tools_dir: str | Path | None = None) -> None:
        self._packs: dict[str, ToolPack] = {}
        self._by_connector: dict[str, ToolPack] = {}
        #: Populated only in compiled mode; ``None`` means every pack is already
        #: parsed and :attr:`_by_connector` is authoritative.
        self._index: dict[str, Any] | None = None

        # An index means packs can be found without opening them, so they are
        # parsed on demand. A directory without one -- a caller pointing at
        # their own packs -- is read eagerly, which still works, just slower.
        self.tools_dir = Path(tools_dir or TOOLS_DIR)
        index = self.tools_dir / INDEX_NAME
        if index.is_file():
            self._index = json.loads(index.read_text(encoding="utf-8"))
        else:
            self._load()

    # -- lazy resolution ---------------------------------------------------

    def _pack_for(self, connector_id: object) -> ToolPack | None:
        """The pack serving ``connector_id``, parsing its file on first use."""
        if self._index is None:
            return self._by_connector.get(connector_id)  # type: ignore[arg-type]
        owner = self._index["by_connector"].get(connector_id)
        if owner is None:
            return None
        pack = self._packs.get(owner)
        if pack is None:
            pack = load_pack(self.tools_dir / self._index["packs"][owner]["file"])
            self._packs[owner] = pack
            for cid in pack.connector_ids:
                self._by_connector[cid] = pack
        return pack

    def _materialise(self) -> None:
        """Parse every pack. Only whole-catalogue callers need this."""
        if self._index is None:
            return
        for owner in self._index["packs"]:
            self._pack_for(owner)

    # -- loading -----------------------------------------------------------

    def _load(self) -> None:
        if not self.tools_dir.is_dir():
            return
        for path in sorted(self.tools_dir.rglob("*.json")):
            if path.name == INDEX_NAME:
                continue
            pack = load_pack(path)
            if pack.connector_id in self._packs:
                raise ValueError(f"duplicate tool pack for {pack.connector_id!r} in {path}")
            self._packs[pack.connector_id] = pack
            for connector_id in pack.connector_ids:
                owner = self._by_connector.get(connector_id)
                if owner is not None and owner is not pack:
                    raise ValueError(
                        f"connector {connector_id!r} is claimed by both "
                        f"{owner.source} and {pack.source}"
                    )
                self._by_connector[connector_id] = pack

    # -- lookup ------------------------------------------------------------

    def __len__(self) -> int:
        """How many packs are bundled (not how many tools)."""
        return len(self._index["packs"]) if self._index is not None else len(self._packs)

    def __iter__(self) -> Iterator[ToolPack]:
        self._materialise()
        return iter(self._packs.values())

    def __contains__(self, connector_id: object) -> bool:
        if self._index is not None:
            return connector_id in self._index["by_connector"]
        return connector_id in self._by_connector

    @property
    def packs(self) -> list[ToolPack]:
        self._materialise()
        return list(self._packs.values())

    def connector_ids(self) -> list[str]:
        """Every connector id that resolves to a pack, aliases included."""
        if self._index is not None:
            return sorted(self._index["by_connector"])
        return sorted(self._by_connector)

    def has(self, connector_id: str) -> bool:
        if self._index is not None:
            return connector_id in self._index["by_connector"]
        return connector_id in self._by_connector

    def pack(self, connector_id: str) -> ToolPack | None:
        """The pack serving ``connector_id``, or ``None`` when none is bundled."""
        return self._pack_for(connector_id)

    def get_pack(self, connector_id: str) -> ToolPack:
        pack = self._pack_for(connector_id)
        if pack is None:
            raise UnknownToolError(
                f"No tools are bundled for connector '{connector_id}'",
                connector_id=connector_id,
            )
        return pack

    def tools(self, connector_id: str) -> list[Tool]:
        pack = self._pack_for(connector_id)
        return list(pack.tools.values()) if pack else []

    def tool(self, connector_id: str, name: str) -> Tool:
        pack = self.get_pack(connector_id)
        tool = pack.get(name)
        if tool is None:
            raise UnknownToolError(
                f"Connector '{connector_id}' has no tool '{name}'",
                connector_id=connector_id,
                tool=name,
                available=sorted(pack.tools),
            )
        return tool

    def total_tools(self) -> int:
        # The index carries per-pack counts, so this stays a sum over integers
        # rather than a reason to parse the whole catalogue.
        if self._index is not None:
            return sum(p["tools"] for p in self._index["packs"].values())
        return sum(len(pack) for pack in self._packs.values())

    def search(self, query: str, connector_id: str | None = None) -> list[Tool]:
        """Tools whose name, title or description mentions ``query``."""
        needle = (query or "").strip().lower()
        # Searching one connector reads one pack; searching all of them is the
        # one call that genuinely needs every file.
        packs = [self.get_pack(connector_id)] if connector_id else self.packs
        out: list[Tool] = []
        for pack in packs:
            for tool in pack.tools.values():
                haystack = f"{tool.name} {tool.title} {tool.description} {tool.category}".lower()
                if not needle or needle in haystack:
                    out.append(tool)
        return sorted(out, key=lambda t: (t.connector_id, t.name))

    def stats(self) -> dict[str, Any]:
        """Counts a README or a CLI ``stats`` command can print verbatim."""
        if self._index is not None:
            counts = {cid: p["tools"] for cid, p in self._index["packs"].items()}
            return {
                "packs": len(counts),
                "connectors_covered": len(self._index["by_connector"]),
                "tools": self.total_tools(),
                "by_connector": dict(
                    sorted(counts.items(), key=lambda kv: -kv[1])
                ),
            }
        return {
            "packs": len(self._packs),
            "connectors_covered": len(self._by_connector),
            "tools": self.total_tools(),
            "by_connector": {
                pack.connector_id: len(pack)
                for pack in sorted(self._packs.values(), key=lambda p: -len(p))
            },
        }


# ---------------------------------------------------------------------------
# JSON -> dataclasses
# ---------------------------------------------------------------------------


def load_pack(path: str | Path) -> ToolPack:
    """Parse one ``<connector-id>.json`` tool pack."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    connector_id = str(data.get("connector_id") or path.stem)
    return ToolPack(
        connector_id=connector_id,
        display_name=str(data.get("display_name") or ""),
        docs_url=data.get("docs_url"),
        applies_to=[str(c) for c in (data.get("applies_to") or [])],
        scope_rules=_scope_rules(data.get("scope_rules")),
        scope_discovery=_scope_discovery(data.get("scope_discovery")),
        tools=_tools(connector_id, data.get("tools"), data.get("docs_url")),
        source=str(path),
        generated=_truthy(data.get("generated")),
        generated_from=str(data.get("generated_from") or ""),
    )


def _scope_rules(spec: Any) -> ScopeRules:
    if not isinstance(spec, dict):
        return ScopeRules()
    return ScopeRules(
        case_insensitive=_truthy(spec.get("case_insensitive")),
        strip_prefixes=[str(p) for p in (spec.get("strip_prefixes") or [])],
        implies={
            str(k): [str(s) for s in (v or [])]
            for k, v in (spec.get("implies") or {}).items()
        },
        expand_groups=_truthy(spec.get("expand_groups")),
    )


def _scope_discovery(spec: Any) -> ScopeDiscoverySpec | None:
    if not isinstance(spec, dict) or not spec:
        return None
    return ScopeDiscoverySpec(
        method=str(spec.get("method") or "GET").upper(),
        endpoint=str(spec.get("endpoint") or ""),
        scopes_path=str(spec.get("scopes_path") or "scope"),
        separator=str(spec.get("separator") or " "),
        base_url_override=spec.get("base_url_override"),
        headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items()},
        query={str(k): str(v) for k, v in (spec.get("query") or {}).items()},
        jwt_claim=spec.get("jwt_claim"),
    )


def _tools(connector_id: str, spec: Any, pack_docs: str | None) -> dict[str, Tool]:
    if not isinstance(spec, dict):
        return {}
    out: dict[str, Tool] = {}
    for name, raw in spec.items():
        raw = raw if isinstance(raw, dict) else {}
        out[str(name)] = Tool(
            connector_id=connector_id,
            name=str(name),
            title=str(raw.get("title") or _titleize(str(name))),
            description=str(raw.get("description") or "").strip(),
            category=str(raw.get("category") or ""),
            scopes=[str(s) for s in (raw.get("scopes") or [])],
            scopes_any=[str(s) for s in (raw.get("scopes_any") or [])],
            read_only=_truthy(raw.get("read_only")),
            destructive=_truthy(raw.get("destructive")),
            request=_request(raw.get("request")),
            input=_parameters(raw.get("input")),
            output=_output(raw.get("output")),
            docs_url=raw.get("docs_url") or pack_docs,
            notes=str(raw.get("notes") or "").strip(),
        )
    return out


def _request(spec: Any) -> ToolRequest:
    if not isinstance(spec, dict):
        return ToolRequest()
    return ToolRequest(
        method=str(spec.get("method") or "GET").upper(),
        path=str(spec.get("path") or ""),
        query=(spec.get("query") if isinstance(spec.get("query"), str) else dict(spec.get("query") or {})),
        headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items()},
        body=spec.get("body"),
        encoding=str(spec.get("encoding") or "json").lower(),
        content=spec.get("content"),
        base_url_override=spec.get("base_url_override"),
    )


def _parameters(spec: Any) -> list[ToolParameter]:
    if not isinstance(spec, dict):
        return []
    out: list[ToolParameter] = []
    for name, raw in spec.items():
        raw = raw if isinstance(raw, dict) else {}
        out.append(
            ToolParameter(
                name=str(name),
                type=str(raw.get("type") or "string"),
                title=str(raw.get("title") or _titleize(str(name))),
                description=str(raw.get("description") or "").strip(),
                # ``optional: true`` matches how the connector catalogue spells it.
                required=not _truthy(raw.get("optional")),
                default=raw.get("default"),
                enum=list(raw.get("enum") or []),
                example=raw.get("example"),
                pattern=raw.get("pattern"),
                format=raw.get("format"),
                minimum=raw.get("minimum"),
                maximum=raw.get("maximum"),
                min_length=raw.get("min_length"),
                max_length=raw.get("max_length"),
                items=raw.get("items"),
                properties=raw.get("properties"),
                secret=_truthy(raw.get("secret")),
            )
        )
    return out


def _output(spec: Any) -> ToolOutput:
    if not isinstance(spec, dict):
        return ToolOutput()
    return ToolOutput(
        description=str(spec.get("description") or "").strip(),
        type=str(spec.get("type") or "object"),
        properties=dict(spec.get("properties") or {}),
        items=spec.get("items"),
        response_path=spec.get("response_path"),
    )


def _configured_base(provider: dict[str, Any]) -> str | None:
    """Where to send requests for a connector with no fixed base url.

    Some connectors are pointed at their endpoint by the connection rather than
    the catalogue -- a generic MCP server, a self-hosted instance. The address
    is then a connection-config field, and interpolating it is enough. Failing
    that, an MCP connector's own OAuth endpoints share an origin with its
    server, which is derivable rather than guessed.
    """
    config = provider.get("connection_config") or {}
    for name in ENDPOINT_FIELDS:
        if name in config:
            return "${%s}" % name
    for key in ("authorization_url", "token_url", "registration_url"):
        value = provider.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            origin = re.match(r"(https://[^/]+)", value)
            if origin:
                return origin.group(1)
    return None


def _mcp_tools(connector_id: str, label: str, override: str | None) -> dict[str, Tool]:
    """The two calls every MCP server answers, per the Model Context Protocol.

    MCP is a specified JSON-RPC protocol, so ``tools/list`` and ``tools/call``
    are defined for any server that speaks it -- unlike a REST provider's
    endpoints, these do not have to be discovered or guessed.
    """
    def rpc(name: str, title: str, description: str, body: Any, inputs: list[ToolParameter], destructive: bool) -> Tool:
        return Tool(
            connector_id=connector_id,
            name=name,
            title=title,
            description=description,
            category="mcp",
            destructive=destructive,
            request=ToolRequest(
                method="POST",
                path="/",
                headers={"Accept": "application/json, text/event-stream"},
                body=body,
                base_url_override=override,
            ),
            input=inputs,
            output=ToolOutput(
                description="The server's JSON-RPC response: a `result` object, or an `error` when the call failed.",
                type="object",
            ),
            generated=True,
        )

    return {
        "list_server_tools": rpc(
            "list_server_tools",
            "List the MCP server's tools",
            (
                f"Ask {label}'s MCP server which tools it exposes, over the Model Context "
                "Protocol's tools/list method. The server decides what it offers, so this is "
                "how to discover the real tool surface before calling anything."
            ),
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"cursor": "${cursor}"}},
            [ToolParameter(
                name="cursor", type="string", title="Cursor",
                description="Paging cursor from a previous tools/list response.",
                required=False,
            )],
            destructive=False,
        ),
        "call_server_tool": rpc(
            "call_server_tool",
            "Call a tool on the MCP server",
            (
                f"Invoke one of {label}'s MCP tools by name, over the Model Context Protocol's "
                "tools/call method. Use list_server_tools first: the name and the shape of "
                "`arguments` are defined by the server, not by this package."
            ),
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "${name}", "arguments": "${arguments}"}},
            [
                ToolParameter(
                    name="name", type="string", title="Tool name",
                    description="Name of the server tool to call, from list_server_tools.",
                ),
                ToolParameter(
                    name="arguments", type="object", title="Arguments",
                    description="Arguments for that tool, matching the inputSchema the server published.",
                    required=False,
                ),
            ],
            destructive=True,
        ),
    }


def _raw_request_tool(
    connector_id: str, label: str, name: str, method: str, verb: str, absolute: bool = False
) -> Tool:
    """One authenticated escape-hatch tool for a connector with no pack.

    ``absolute`` is for a connector with no address of its own at all, where the
    caller supplies the whole url rather than a path under a base.
    """
    write = method not in ("GET", "HEAD")
    inputs = [
        ToolParameter(
            name="path",
            type="string",
            title="URL" if absolute else "Path",
            description=(
                (
                    f"Full url to call, e.g. \"https://api.example.com/v1/users\". {label} has no "
                    "base url of its own, so the whole address goes here."
                ) if absolute else (
                    f"Path to call on {label}'s API, relative to its base url — for example "
                    "\"/v1/users\" or \"/api/v2/tickets/42\". You need to know the provider's "
                    "API to use this; nothing here validates the path."
                )
            ),
            example="https://api.example.com/v1/users" if absolute else "/v1/users",
        ),
        ToolParameter(
            name="query",
            type="object",
            title="Query",
            description="Query-string parameters as a flat object, e.g. {\"limit\": 50}.",
            required=False,
        ),
    ]
    if write:
        inputs.append(
            ToolParameter(
                name="body",
                type="object",
                title="Body",
                description="JSON request body to send.",
                required=False,
            )
        )
    return Tool(
        connector_id=connector_id,
        name=name,
        title=f"{verb} the API ({method})",
        description=(
            f"{verb} {label}'s API with this connection's credentials applied, at a path you "
            f"supply. A general-purpose {method} escape hatch for a connector that has no "
            "purpose-built tools yet: it makes no claim about which endpoints exist, so the "
            "caller must know the provider's API. Prefer a named tool wherever one exists."
        ),
        category="raw",
        read_only=not write,
        destructive=method == "DELETE",
        request=ToolRequest(
            method=method,
            path="${path}",
            query="${query}",
            body="${body}" if write else None,
        ),
        input=inputs,
        output=ToolOutput(
            description=f"Whatever {label}'s API returns for that request, parsed as JSON where possible.",
            type="object",
        ),
        generated=True,
    )


def baseline_pack(connector_id: str, display_name: str, provider: dict[str, Any]) -> ToolPack | None:
    """The tools a connector gets when no pack has been written or generated.

    Two kinds, both built from what the repo already knows and neither claiming
    anything about the provider's API:

    * ``check_connection``, when the catalogue declares a verification endpoint
      -- a real, cheap call that proves the credentials work;
    * the raw ``*_api`` tools, which expose the authenticated request this
      package can already make, so any connector with a base url is drivable by
      an agent that knows the provider's API.

    Returns ``None`` only when the connector has no base url to call at all.
    """
    label = display_name or _titleize(connector_id)
    tools: dict[str, Tool] = {}

    spec = ((provider.get("proxy") or {}).get("verification") or {})
    endpoints = spec.get("endpoints") or []
    if isinstance(endpoints, str):
        endpoints = [endpoints]
    endpoints = [e for e in endpoints if isinstance(e, str)]
    if endpoints and not provider.get("credentials_verification_script"):
        method = str(spec.get("method") or "GET").upper()
        endpoint = endpoints[0]
        tools[BASELINE_TOOL] = Tool(
            connector_id=connector_id,
            name=BASELINE_TOOL,
            title="Check the connection",
            description=(
                f"Call {label}'s own verification endpoint ({method} {endpoint}) to confirm the "
                "credentials still work, and return whatever it answers. Taken from the "
                "connector's catalogue entry, so it is a call this package knows is real for "
                f"{label}."
            ),
            category="connection",
            read_only=method == "GET",
            request=ToolRequest(
                method=method,
                path=endpoint if endpoint.startswith("/") else f"/{endpoint}",
                headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items() if v is not None},
                base_url_override=spec.get("base_url_override"),
            ),
            output=ToolOutput(
                description="Whatever the provider's verification endpoint returns, usually the account behind the credentials.",
                type="object",
            ),
            generated=True,
        )

    has_base = bool((provider.get("proxy") or {}).get("base_url"))
    override = None if has_base else _configured_base(provider)
    absolute = not has_base and override is None

    if str(provider.get("auth_mode") or "").startswith("MCP_"):
        tools.update(_mcp_tools(connector_id, label, override))

    for name, method, verb in RAW_TOOLS:
        tool = _raw_request_tool(connector_id, label, name, method, verb, absolute=absolute)
        if override:
            tool.request.base_url_override = override
        tools[name] = tool

    if not tools:
        return None
    return ToolPack(
        connector_id=connector_id,
        display_name=label,
        docs_url=None,
        tools=tools,
        source="<generated from catalogue metadata>",
        generated=True,
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _titleize(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip().capitalize()
