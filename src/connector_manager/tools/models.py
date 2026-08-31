"""Data models for the tool layer.

A **tool** is one concrete thing an agent can do with a connector -- "send an
email with a file attachment", "create a HubSpot deal", "append rows to a
sheet". It carries everything an LLM runtime needs (name, description, typed
inputs, described output) *and* everything this package needs to actually run it
(HTTP method, path, query/body templates), plus the OAuth scopes the provider
demands for it.

Tools are data: they live in ``data/tools/<auth-mode>/<connector-id>.yaml`` and
are loaded by :class:`~connector_manager.tools.registry.ToolRegistry`. Nothing
here performs I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

#: The JSON Schema types a tool parameter may declare.
PARAM_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})

#: Tool names are snake_case so they are valid identifiers in every runtime.
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolAvailability(str, Enum):
    """Whether a connection's credentials may run a given tool.

    ``UNKNOWN`` is deliberately distinct from ``DISABLED``: an API key whose
    permissions the provider never discloses is not the same as a token we know
    lacks a scope, and a UI should say so rather than grey the tool out.
    """

    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ToolParameter:
    """One argument a tool accepts, in JSON-Schema terms."""

    name: str
    type: str = "string"
    title: str = ""
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[Any] = field(default_factory=list)
    example: Any = None
    pattern: str | None = None
    format: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    #: For ``array``: the schema of one element. For ``object``: free-form.
    items: dict[str, Any] | None = None
    #: For ``object``: named sub-properties, purely descriptive.
    properties: dict[str, Any] | None = None
    secret: bool = False

    def json_schema(self) -> dict[str, Any]:
        """This parameter as a JSON Schema fragment."""
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.title:
            schema["title"] = self.title
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.default is not None:
            schema["default"] = self.default
        if self.pattern:
            schema["pattern"] = self.pattern
        if self.format:
            schema["format"] = self.format
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.items is not None:
            schema["items"] = self.items
        if self.properties is not None:
            schema["properties"] = self.properties
        if self.example is not None:
            schema["examples"] = [self.example]
        return schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "required": self.required,
            "default": self.default,
            "enum": list(self.enum),
            "example": self.example,
            "secret": self.secret,
            "schema": self.json_schema(),
        }


@dataclass(slots=True)
class ToolRequest:
    """The HTTP call a tool makes, as templates over the tool's arguments.

    ``${argument}`` placeholders are bound at call time. A value that is exactly
    one placeholder keeps the argument's own type (an object stays an object);
    an embedded placeholder is interpolated into the surrounding string. Keys
    whose placeholders bind to nothing are dropped, which is how optional
    arguments disappear from the query string and the body.
    """

    method: str = "GET"
    path: str = ""
    #: Either per-key templates, or one ``"${arg}"`` naming a whole object of
    #: query parameters (which is what the raw request tools take).
    query: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    #: How ``body`` goes on the wire. ``form`` is
    #: ``application/x-www-form-urlencoded`` with Stripe/Twilio-style bracket
    #: notation for nested values (``metadata[tier]=gold``).
    encoding: str = "json"
    #: Raw (already-encoded) body, for the few endpoints that want text.
    content: str | None = None
    #: Wins over the connector's ``proxy.base_url`` for this one call.
    base_url_override: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "query": dict(self.query) if isinstance(self.query, dict) else self.query,
            "headers": dict(self.headers),
            "body": self.body,
            "encoding": self.encoding,
            "content": self.content,
            "base_url_override": self.base_url_override,
        }


@dataclass(slots=True)
class ToolOutput:
    """What the tool gives back, described for the model that reads it."""

    description: str = ""
    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    items: dict[str, Any] | None = None
    #: Dot path to the useful part of the response, e.g. ``value`` or ``results``.
    response_path: str | None = None

    def json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.properties:
            schema["properties"] = dict(self.properties)
        if self.items is not None:
            schema["items"] = self.items
        return schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "type": self.type,
            "properties": dict(self.properties),
            "items": self.items,
            "response_path": self.response_path,
            "schema": self.json_schema(),
        }


@dataclass(slots=True)
class Tool:
    """One callable capability of a connector."""

    connector_id: str
    name: str
    title: str = ""
    description: str = ""
    category: str = ""
    #: Scopes the caller needs *all* of.
    scopes: list[str] = field(default_factory=list)
    #: Scopes the caller needs *any one* of (providers that accept alternatives).
    scopes_any: list[str] = field(default_factory=list)
    read_only: bool = False
    #: True when a mistake is not undoable -- deletes, sends, payments.
    destructive: bool = False
    request: ToolRequest = field(default_factory=ToolRequest)
    input: list[ToolParameter] = field(default_factory=list)
    output: ToolOutput = field(default_factory=ToolOutput)
    docs_url: str | None = None
    notes: str = ""
    #: True when this tool was derived from the connector's catalogue metadata
    #: rather than hand-authored against the provider's documentation.
    generated: bool = False

    @property
    def qualified_name(self) -> str:
        """``hubspot.create_contact`` -- unique across the whole catalogue."""
        return f"{self.connector_id}.{self.name}"

    @property
    def required_scopes(self) -> list[str]:
        """Every scope named by this tool, in either mode."""
        return [*self.scopes, *self.scopes_any]

    def parameter(self, name: str) -> ToolParameter | None:
        return next((p for p in self.input if p.name == name), None)

    def required_parameters(self) -> list[ToolParameter]:
        return [p for p in self.input if p.required]

    def input_schema(self) -> dict[str, Any]:
        """The tool's arguments as one JSON Schema object."""
        return {
            "type": "object",
            "properties": {p.name: p.json_schema() for p in self.input},
            "required": [p.name for p in self.input if p.required],
            "additionalProperties": False,
        }

    def output_schema(self) -> dict[str, Any]:
        return self.output.json_schema()

    def spec(self, format: str = "anthropic", prefix: bool = False) -> dict[str, Any]:
        """This tool as an LLM tool definition.

        ``format`` is ``anthropic`` (``input_schema``), ``openai`` (a
        ``function`` wrapper with ``parameters``) or ``mcp`` (``inputSchema``
        plus ``outputSchema`` and MCP's read-only/destructive hints).
        ``prefix=True`` uses the connector-qualified name, for runtimes that
        expose several connectors at once.
        """
        name = self.qualified_name.replace(".", "_") if prefix else self.name
        schema = self.input_schema()
        if format == "openai":
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": self.description,
                    "parameters": schema,
                },
            }
        if format == "mcp":
            return {
                "name": name,
                "title": self.title or self.name,
                "description": self.description,
                "inputSchema": schema,
                "outputSchema": self.output_schema(),
                "annotations": {
                    "title": self.title or self.name,
                    "readOnlyHint": self.read_only,
                    "destructiveHint": self.destructive,
                },
            }
        if format == "anthropic":
            return {"name": name, "description": self.description, "input_schema": schema}
        raise ValueError(f"unknown tool spec format {format!r} (anthropic, openai, mcp)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "scopes": list(self.scopes),
            "scopes_any": list(self.scopes_any),
            "read_only": self.read_only,
            "destructive": self.destructive,
            "docs_url": self.docs_url,
            "notes": self.notes,
            "generated": self.generated,
            "request": self.request.to_dict(),
            "input": [p.to_dict() for p in self.input],
            "input_schema": self.input_schema(),
            "output": self.output.to_dict(),
        }


_GROUPED_SCOPE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)\((.+)\)")


@dataclass(slots=True)
class ScopeRules:
    """How to compare a provider's scope strings.

    Providers spell scopes differently enough that a plain set intersection
    gets the answer wrong: Google grants full URLs, Microsoft is case-insensitive
    and hierarchical (``Mail.ReadWrite`` covers ``Mail.Read``), HubSpot is flat
    and lower-case. Each tool pack declares the rules its provider follows.
    """

    case_insensitive: bool = False
    #: Prefixes stripped before comparison, e.g. Google's scope URL root.
    strip_prefixes: list[str] = field(default_factory=list)
    #: ``granted -> also counts as`` (transitively expanded).
    implies: dict[str, list[str]] = field(default_factory=dict)
    #: Whether one granted scope may name several resources at once, in the
    #: ``verb(a,b)`` form Accelo uses. When set, such a grant counts as each of
    #: ``verb(a)`` and ``verb(b)`` -- otherwise a real grant reads as missing.
    expand_groups: bool = False

    def normalize(self, scope: str) -> str:
        value = str(scope).strip()
        for prefix in self.strip_prefixes:
            if value.startswith(prefix):
                value = value[len(prefix) :]
                break
        return value.lower() if self.case_insensitive else value

    def ungroup(self, scope: str) -> list[str]:
        """``read(a,b)`` as ``[read(a), read(b)]``; anything else unchanged.

        >>> ScopeRules(expand_groups=True).ungroup("read(companies,contacts)")
        ['read(companies)', 'read(contacts)']
        """
        if not self.expand_groups:
            return [scope]
        match = _GROUPED_SCOPE_RE.fullmatch(scope.strip())
        if match is None:
            return [scope]
        verb, inner = match.group(1), match.group(2)
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        return [f"{verb}({p})" for p in parts] or [scope]

    def expand(self, granted: Iterable[str]) -> set[str]:
        """Every scope the grant implies, normalised, following chains."""
        implies = {self.normalize(k): [self.normalize(s) for s in v] for k, v in self.implies.items()}
        out: set[str] = set()
        queue: list[str] = []
        for scope in granted:
            if not str(scope).strip():
                continue
            queue.extend(self.ungroup(self.normalize(scope)))
        while queue:
            scope = queue.pop()
            if scope in out:
                continue
            out.add(scope)
            queue.extend(implies.get(scope, ()))
        return out

    def missing(self, tool: Tool, granted: Iterable[str]) -> list[str]:
        """Scopes ``tool`` needs that the grant does not cover.

        For ``scopes_any`` the whole alternative set is reported when none of it
        is held, since any single one would do.
        """
        held = self.expand(granted)
        missing = [s for s in tool.scopes if self.normalize(s) not in held]
        if tool.scopes_any and not any(self.normalize(s) in held for s in tool.scopes_any):
            missing.extend(tool.scopes_any)
        return missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_insensitive": self.case_insensitive,
            "strip_prefixes": list(self.strip_prefixes),
            "implies": {k: list(v) for k, v in self.implies.items()},
            "expand_groups": self.expand_groups,
        }


@dataclass(slots=True)
class ScopeDiscoverySpec:
    """How to ask the provider which scopes a live credential actually carries.

    Either an HTTP call (``endpoint`` + ``scopes_path``) or, for providers whose
    access token is a JWT carrying its own grant, a claim to read locally
    (``jwt_claim``) -- no network at all.
    """

    method: str = "GET"
    endpoint: str = ""
    scopes_path: str = "scope"
    separator: str = " "
    base_url_override: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    jwt_claim: str | None = None

    @property
    def is_local(self) -> bool:
        return bool(self.jwt_claim) and not self.endpoint

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "endpoint": self.endpoint,
            "scopes_path": self.scopes_path,
            "separator": self.separator,
            "base_url_override": self.base_url_override,
            "query": dict(self.query),
            "jwt_claim": self.jwt_claim,
        }


@dataclass(slots=True)
class ToolPack:
    """Every tool one connector ships, plus how to read its scopes."""

    connector_id: str
    display_name: str = ""
    docs_url: str | None = None
    #: Other connector ids served by this same pack (``outlook`` -> ``microsoft``).
    applies_to: list[str] = field(default_factory=list)
    scope_rules: ScopeRules = field(default_factory=ScopeRules)
    scope_discovery: ScopeDiscoverySpec | None = None
    tools: dict[str, Tool] = field(default_factory=dict)
    #: Where the pack was loaded from, for error messages and the layout tests.
    source: str = ""
    #: Provenance for a generated pack -- the spec URL it was built from.
    generated_from: str = ""
    #: True for a pack synthesised from catalogue metadata rather than loaded
    #: from a hand-authored file. Such a pack holds only what the catalogue
    #: itself declares -- nothing is inferred about the provider's API.
    generated: bool = False

    def __len__(self) -> int:
        return len(self.tools)

    def __iter__(self) -> Any:
        return iter(self.tools.values())

    def __contains__(self, name: object) -> bool:
        return name in self.tools

    @property
    def connector_ids(self) -> list[str]:
        return [self.connector_id, *self.applies_to]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def categories(self) -> list[str]:
        return sorted({t.category for t in self.tools.values() if t.category})

    def scopes(self) -> list[str]:
        """Every distinct scope any tool in the pack asks for."""
        seen: set[str] = set()
        for tool in self.tools.values():
            seen.update(tool.required_scopes)
        return sorted(seen)

    def to_dict(self, include_request: bool = True) -> dict[str, Any]:
        tools = []
        for tool in self.tools.values():
            data = tool.to_dict()
            if not include_request:
                data.pop("request", None)
            tools.append(data)
        return {
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "docs_url": self.docs_url,
            "applies_to": list(self.applies_to),
            "generated": self.generated,
            "generated_from": self.generated_from,
            "tool_count": len(self.tools),
            "categories": self.categories(),
            "scopes": self.scopes(),
            "scope_rules": self.scope_rules.to_dict(),
            "scope_discovery": self.scope_discovery.to_dict() if self.scope_discovery else None,
            "tools": tools,
        }


@dataclass(slots=True)
class ToolStatus:
    """One tool's verdict against a specific connection's permissions."""

    tool: Tool
    availability: ToolAvailability
    missing_scopes: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def enabled(self) -> bool:
        return self.availability is ToolAvailability.ENABLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.tool.name,
            "title": self.tool.title,
            "description": self.tool.description,
            "category": self.tool.category,
            "availability": self.availability.value,
            "enabled": self.enabled,
            "required_scopes": self.tool.required_scopes,
            "missing_scopes": list(self.missing_scopes),
            "reason": self.reason,
        }


@dataclass(slots=True)
class ScopeDiscovery:
    """Where a connection's granted scopes came from, and what they were."""

    #: ``None`` means "could not be determined", which is not the same as "none".
    scopes: list[str] | None = None
    source: str = "unknown"
    tested: bool = False
    reason: str | None = None

    @property
    def known(self) -> bool:
        return self.scopes is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scopes": list(self.scopes) if self.scopes is not None else None,
            "source": self.source,
            "tested": self.tested,
            "known": self.known,
            "reason": self.reason,
        }


@dataclass(slots=True)
class ToolReport:
    """Which of a connector's tools this connection may actually call.

    This is the answer to "my client id and secret only have these permissions
    -- so which tools do I really have?": every tool, split into enabled,
    disabled and unknown, with the missing scopes named for each disabled one.
    """

    connector_id: str
    connection_id: str = ""
    granted_scopes: list[str] | None = None
    scope_source: str = "unknown"
    statuses: list[ToolStatus] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.statuses)

    def __iter__(self) -> Any:
        return iter(self.statuses)

    def _of(self, availability: ToolAvailability) -> list[ToolStatus]:
        return [s for s in self.statuses if s.availability is availability]

    @property
    def enabled(self) -> list[ToolStatus]:
        return self._of(ToolAvailability.ENABLED)

    @property
    def disabled(self) -> list[ToolStatus]:
        return self._of(ToolAvailability.DISABLED)

    @property
    def unknown(self) -> list[ToolStatus]:
        return self._of(ToolAvailability.UNKNOWN)

    def enabled_names(self) -> list[str]:
        return [s.tool.name for s in self.enabled]

    def disabled_names(self) -> list[str]:
        return [s.tool.name for s in self.disabled]

    def status(self, name: str) -> ToolStatus | None:
        return next((s for s in self.statuses if s.tool.name == name), None)

    def missing_scopes(self) -> list[str]:
        """Every scope that would unlock at least one more tool."""
        seen: set[str] = set()
        for entry in self.disabled:
            seen.update(entry.missing_scopes)
        return sorted(seen)

    def specs(self, format: str = "anthropic", include_disabled: bool = False) -> list[dict[str, Any]]:
        """LLM tool definitions for exactly the tools this connection can call."""
        chosen = self.statuses if include_disabled else [s for s in self.statuses if s.enabled or s.availability is ToolAvailability.UNKNOWN]
        return [s.tool.spec(format=format) for s in chosen]

    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.statuses),
            "enabled": len(self.enabled),
            "disabled": len(self.disabled),
            "unknown": len(self.unknown),
        }

    def summary(self) -> str:
        counts = self.counts()
        return (
            f"{self.connector_id}: {counts['enabled']}/{counts['total']} tools enabled, "
            f"{counts['disabled']} disabled, {counts['unknown']} unknown "
            f"(scopes from {self.scope_source})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "connection_id": self.connection_id,
            "granted_scopes": list(self.granted_scopes) if self.granted_scopes is not None else None,
            "scope_source": self.scope_source,
            "counts": self.counts(),
            "missing_scopes": self.missing_scopes(),
            "tools": [s.to_dict() for s in self.statuses],
        }


@dataclass(slots=True)
class ToolResult:
    """The outcome of actually calling a tool."""

    tool: str
    connector_id: str
    ok: bool
    status: int | None = None
    data: Any = None
    error: str | None = None
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "connector_id": self.connector_id,
            "ok": self.ok,
            "status": self.status,
            "url": self.url,
            "data": self.data,
            "error": self.error,
        }


def parse_scope_string(value: Any, separator: str = " ") -> list[str]:
    """Split a provider's scope value into a list.

    Providers return scopes as a space-separated string, a comma-separated one,
    or already as a list -- all three turn up in token responses.

    Separators inside parentheses do not split, because a few providers put a
    list of objects inside one scope: Accelo grants ``read(companies,contacts)``
    as a single scope, and splitting it would leave two halves that match
    nothing.

    >>> parse_scope_string("read(companies,contacts),write(staff)")
    ['read(companies,contacts)', 'write(staff)']
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    pattern = r"[,\s]+" if separator.strip() == "" or separator == " " else re.escape(separator)
    parts = _split_outside_parens(text, pattern)
    return [p.strip() for p in parts if p.strip()]


def _split_outside_parens(text: str, pattern: str) -> list[str]:
    """Split on ``pattern``, ignoring matches nested inside parentheses."""
    parts: list[str] = []
    start = depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0:
            match = re.compile(pattern).match(text, index)
            if match and match.end() > match.start():
                parts.append(text[start : match.start()])
                start = index = match.end()
                continue
        index += 1
    parts.append(text[start:])
    return parts


def merge_mappings(*sources: Mapping[str, Any] | None) -> dict[str, Any]:
    """Shallow-merge, later sources winning, skipping ``None``."""
    out: dict[str, Any] = {}
    for source in sources:
        if source:
            out.update(source)
    return out
