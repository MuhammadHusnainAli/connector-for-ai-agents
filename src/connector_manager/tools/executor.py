"""Turning a tool plus arguments into a real, authenticated HTTP request.

:class:`ToolExecutor` does three things and no I/O:

1. **validate** the arguments against the tool's input schema, filling defaults
   and coercing the stringly-typed values LLM runtimes tend to emit;
2. **bind** them into the tool's method/path/query/body templates;
3. **parse** the provider's response back into a :class:`ToolResult`.

The request itself is built by the same :class:`~connector_manager.proxy.RequestBuilder`
that serves ``manager.request``, so a tool call is authenticated, base-url
resolved and header-templated exactly like a hand-written call.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from ..errors import ToolValidationError
from ..http import HttpResponse, Request
from ..interpolation import PLACEHOLDER_RE, extract_value_by_path, interpolate
from ..models import Connection
from ..proxy import RequestBuilder
from .models import PARAM_TYPES, Tool, ToolParameter, ToolResult

#: Marks a template slot whose argument was not supplied, so the whole key can
#: be dropped rather than sent as an empty string.
MISSING = object()

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


class ToolExecutor:
    """Prepares one tool call for one connection."""

    def __init__(
        self,
        provider: dict[str, Any],
        tool: Tool,
        connection: Connection,
    ) -> None:
        self.provider = provider
        self.tool = tool
        self.connection = connection

    # -- 1. validate -------------------------------------------------------

    def validate(self, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Check and normalise arguments, or raise :class:`ToolValidationError`.

        Every problem is collected before raising, so a caller (or a model
        retrying its own call) sees the whole list at once.
        """
        supplied = dict(arguments or {})
        known = {p.name for p in self.tool.input}
        errors: dict[str, str] = {}
        out: dict[str, Any] = {}

        for extra in sorted(set(supplied) - known):
            errors[extra] = (
                f"unknown argument; {self.tool.name} accepts: {', '.join(sorted(known)) or '(none)'}"
            )

        for param in self.tool.input:
            raw = supplied.get(param.name)
            if raw is None or raw == "":
                if param.default is not None:
                    out[param.name] = param.default
                elif param.required:
                    errors[param.name] = f"{param.title or param.name} is required"
                continue
            value, problem = _coerce(param, raw)
            if problem:
                errors[param.name] = problem
                continue
            problem = _check(param, value)
            if problem:
                errors[param.name] = problem
                continue
            out[param.name] = value

        if errors:
            raise ToolValidationError(
                f"Invalid arguments for tool '{self.tool.qualified_name}': "
                f"{', '.join(f'{k} ({v})' for k, v in sorted(errors.items()))}",
                errors,
            )
        return out

    # -- 2. bind -----------------------------------------------------------

    def build(self, arguments: Mapping[str, Any] | None = None, validate: bool = True) -> Request:
        """The fully authenticated request this tool call would send."""
        values = self.validate(arguments) if validate else dict(arguments or {})
        spec = self.tool.request

        path = _bind_path(spec.path, values)
        # A top-level container that binds to nothing is an absent query string
        # or an absent body, not a dropped request -- only nested objects
        # disappear entirely.
        bound_query = _present(_bind(spec.query, values), {})
        # A whole-object query slot binds to a dict of parameters; per-key
        # templates bind to a dict already. Anything else means nothing to send.
        query = bound_query if isinstance(bound_query, dict) else {}
        # Header values go on the wire as text, so an integer argument bound
        # into one (Greenhouse's numeric On-Behalf-Of, say) must be rendered.
        headers = {k: _as_query_value(v) for k, v in _present(_bind(spec.headers, values), {}).items()}
        body = _present(_bind(spec.body, values), None) if spec.body is not None else None
        content = _present(_bind(spec.content, values), None) if spec.content is not None else None

        if body is not None and spec.encoding == "form":
            # Stripe and Twilio take form bodies, nested values in brackets.
            content = urlencode(form_pairs(body))
            headers.setdefault("content-type", "application/x-www-form-urlencoded")
            body = None

        builder = self._builder(spec.base_url_override)
        return builder.build(
            spec.method,
            path,
            headers=headers,
            params={k: _as_query_value(v) for k, v in query.items()},
            json_body=body,
            content=content if isinstance(content, (str, bytes)) else None,
        )

    def _builder(self, base_url_override: str | None) -> RequestBuilder:
        if not base_url_override:
            return RequestBuilder(self.provider, self.connection)
        provider = {
            **self.provider,
            "proxy": {**(self.provider.get("proxy") or {}), "base_url": base_url_override},
        }
        # A tool that overrides the base url means it, so the connection's own
        # base_url must not shadow it (Google's per-service hosts, uploads, ...).
        connection = Connection(
            connection_id=self.connection.connection_id,
            connector_id=self.connection.connector_id,
            auth_mode=self.connection.auth_mode,
            credentials=self.connection.credentials,
            connection_config={
                k: v for k, v in self.connection.connection_config.items() if k != "base_url"
            },
            integration_config=self.connection.integration_config,
        )
        return RequestBuilder(provider, connection)

    # -- 3. parse ----------------------------------------------------------

    def parse(self, response: HttpResponse) -> ToolResult:
        """The provider's answer as a :class:`ToolResult`."""
        body = response.body()
        if not response.ok:
            return ToolResult(
                tool=self.tool.name,
                connector_id=self.tool.connector_id,
                ok=False,
                status=response.status,
                data=body,
                error=_error_message(response.status, body),
                url=response.url,
            )
        data = body
        path = self.tool.output.response_path
        if path and isinstance(body, (dict, list)):
            extracted = extract_value_by_path(body, path)
            if extracted is not None:
                data = extracted
        return ToolResult(
            tool=self.tool.name,
            connector_id=self.tool.connector_id,
            ok=True,
            status=response.status,
            data=data,
            url=response.url,
        )


# ---------------------------------------------------------------------------
# argument coercion and checking
# ---------------------------------------------------------------------------


def _coerce(param: ToolParameter, raw: Any) -> tuple[Any, str | None]:
    """Fit ``raw`` to the parameter's declared type, forgivingly.

    Tool arguments usually arrive from a model's JSON, where ``"5"`` and ``5``
    are both plausible, so numeric and boolean strings are accepted rather than
    rejected. Structural types are not guessed at.
    """
    expected = param.type
    if expected not in PARAM_TYPES:
        return raw, f"{param.name} declares unsupported type '{expected}'"

    if expected == "string":
        if isinstance(raw, (dict, list)):
            return raw, f"{param.title or param.name} must be a string"
        return str(raw), None
    if expected == "boolean":
        if isinstance(raw, bool):
            return raw, None
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True, None
        if text in _FALSE:
            return False, None
        return raw, f"{param.title or param.name} must be true or false"
    if expected in ("integer", "number"):
        if isinstance(raw, bool):
            return raw, f"{param.title or param.name} must be a number"
        try:
            value = int(raw) if expected == "integer" else float(raw)
        except (TypeError, ValueError):
            return raw, f"{param.title or param.name} must be {'an integer' if expected == 'integer' else 'a number'}"
        return value, None
    if expected == "array":
        if isinstance(raw, (list, tuple)):
            return list(raw), None
        # A single value where a list is wanted is a common model slip.
        if isinstance(raw, (str, int, float)):
            return [raw], None
        return raw, f"{param.title or param.name} must be an array"
    if expected == "object":
        if isinstance(raw, dict):
            return raw, None
        return raw, f"{param.title or param.name} must be an object"
    return raw, None


def _check(param: ToolParameter, value: Any) -> str | None:
    label = param.title or param.name
    if param.enum and value not in param.enum:
        return f"{label} must be one of: {', '.join(str(e) for e in param.enum)}"
    if isinstance(value, str):
        if param.pattern:
            try:
                if not re.search(param.pattern, value):
                    return f"{label} does not match the expected format"
            except re.error:
                pass
        if param.min_length is not None and len(value) < param.min_length:
            return f"{label} must be at least {param.min_length} characters"
        if param.max_length is not None and len(value) > param.max_length:
            return f"{label} must be at most {param.max_length} characters"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if param.minimum is not None and value < param.minimum:
            return f"{label} must be >= {param.minimum}"
        if param.maximum is not None and value > param.maximum:
            return f"{label} must be <= {param.maximum}"
    if isinstance(value, list):
        if param.min_length is not None and len(value) < param.min_length:
            return f"{label} must have at least {param.min_length} items"
        if param.max_length is not None and len(value) > param.max_length:
            return f"{label} must have at most {param.max_length} items"
    return None


# ---------------------------------------------------------------------------
# template binding
# ---------------------------------------------------------------------------


def template_arguments(value: Any) -> set[str]:
    """Every ``${argument}`` name a template refers to.

    Used by the executor and by the pack tests, which assert that no template
    reads an argument the tool does not declare.
    """
    names: set[str] = set()
    if isinstance(value, str):
        names.update(m.group(1).split(".", 1)[0] for m in PLACEHOLDER_RE.finditer(value))
    elif isinstance(value, dict):
        if set(value) in ({"$map"}, {"$keyed"}) and isinstance(next(iter(value.values())), dict):
            spec = next(iter(value.values()))
            names |= template_arguments(spec.get("source"))
            # ``item`` and ``index`` are bound by $map itself, not by the
            # caller, so they are not arguments -- but an argument genuinely
            # named ``index`` elsewhere still is.
            names |= template_arguments(spec.get("template")) - {"item", "index"}
            names |= template_arguments(spec.get("key")) - {"item", "index"}
            names |= template_arguments(spec.get("value")) - {"item", "index"}
            return names
        for item in value.values():
            names |= template_arguments(item)
    elif isinstance(value, list):
        for item in value:
            names |= template_arguments(item)
    return names


def _bind(template: Any, values: Mapping[str, Any]) -> Any:
    """Substitute arguments into a template, preserving their types.

    ``"${rows}"`` (a whole slot) yields the list itself; ``"Bearer ${token}"``
    yields a string. A slot whose argument is absent yields :data:`MISSING`, and
    the containing key is dropped -- that is how optional arguments vanish from
    the query string and the JSON body instead of arriving as ``null``.

    A ``$when`` key makes a whole object conditional on one argument: if that
    argument was not supplied the object disappears rather than being sent with
    only its defaults and literals left in it::

        body:
          $when: "${body}"
          contentType: "${body_type}"
          content: "${body}"

    Two structural forms are understood, because providers overwhelmingly want a
    list -- or a map -- of shaped objects where a tool should accept a list of
    plain values::

        toRecipients:
          $map:
            source: "${to}"
            template: {emailAddress: {address: "${item}"}}

    Inside ``template``, ``${item}`` is the element and ``${index}`` its
    position, so ``["ada@example.com"]`` becomes Graph's recipient objects
    without the caller ever seeing the shape. ``$keyed`` is the same idea for a
    map::

        assignments:
          $keyed:
            source: "${assignee_ids}"
            key: "${item}"
            value: {"@odata.type": "#microsoft.graph.plannerAssignment"}
    """
    if isinstance(template, str):
        return _bind_string(template, values)
    if isinstance(template, dict):
        if set(template) == {"$map"}:
            return _bind_map(template["$map"], values)
        if set(template) == {"$mime"}:
            return _bind_mime(template["$mime"], values)
        if set(template) == {"$keyed"}:
            return _bind_keyed(template["$keyed"], values)
        if "$when" in template and _bind(template["$when"], values) is MISSING:
            # The whole node hangs on that argument. Without it the object would
            # be a hollow shell -- a Graph message body with a contentType and no
            # content, a HubSpot filter group with no filters -- which providers
            # read as "set this to nothing" rather than "leave it alone".
            return MISSING
        out: dict[str, Any] = {}
        wanted = 0
        for key, item in template.items():
            if key == "$when":
                continue
            wanted += 1
            bound = _bind(item, values)
            if bound is MISSING:
                continue
            out[key] = bound
        if wanted and not out:
            # Every key dropped, so the object holds nothing the caller asked
            # for. Sending ``{}`` reads as "clear this field" to most providers
            # and as a validation error to the rest; a literal empty object in
            # the template (``folder: {}``) is untouched, since it wanted nothing.
            return MISSING
        return out
    if isinstance(template, list):
        bound_items = [_bind(item, values) for item in template]
        kept = [item for item in bound_items if item is not MISSING]
        # A list that only ever held templated items disappears when they all
        # drop, rather than being sent as an empty array.
        if not kept and bound_items:
            return MISSING
        return kept
    return template


def _present(value: Any, fallback: Any) -> Any:
    """``MISSING`` is meaningful inside a body; at the top level it is just absent."""
    return fallback if value is MISSING else value


def _bind_map(spec: Any, values: Mapping[str, Any]) -> Any:
    """Expand a ``$map`` node into a list, or :data:`MISSING` if its source is."""
    if not isinstance(spec, dict):
        return MISSING
    source = _bind(spec.get("source"), values)
    if source is MISSING or source is None:
        return MISSING
    if not isinstance(source, (list, tuple)):
        source = [source]
    template = spec.get("template")
    out: list[Any] = []
    for index, item in enumerate(source):
        bound = _bind(template, {**values, "item": item, "index": index})
        if bound is not MISSING:
            out.append(bound)
    return out


def _bind_keyed(spec: Any, values: Mapping[str, Any]) -> Any:
    """Expand a ``$keyed`` node into an object keyed by each source element.

    The mirror of ``$map`` for the providers that want a map rather than a list
    -- Planner's ``assignments`` is ``{"<user-id>": {...}}``, not an array -- so
    a tool can still take a plain list of ids.
    """
    if not isinstance(spec, dict):
        return MISSING
    source = _bind(spec.get("source"), values)
    if source is MISSING or source is None:
        return MISSING
    if not isinstance(source, (list, tuple)):
        source = [source]
    out: dict[str, Any] = {}
    for index, item in enumerate(source):
        scope = {**values, "item": item, "index": index}
        key = _bind(spec.get("key", "${item}"), scope)
        value = _bind(spec.get("value"), scope)
        if key is MISSING or value is MISSING:
            continue
        out[str(key)] = value
    return out or MISSING


def _bind_mime(spec: Any, values: Mapping[str, Any]) -> Any:
    """Build a base64url RFC 2822 message from ordinary fields.

    Gmail accepts only a raw MIME message, which is not something a model can
    be asked to produce. This lets a Gmail tool declare the same to / subject /
    body / attachments arguments as any other mail tool and have the message
    assembled here.
    """
    if not isinstance(spec, dict):
        return MISSING
    parts = {key: _bind(value, values) for key, value in spec.items()}
    fields = {k: v for k, v in parts.items() if v is not MISSING and v is not None}
    if not fields.get("to") and not fields.get("body"):
        return MISSING
    return build_mime_message(
        to=_addresses(fields.get("to")),
        subject=str(fields.get("subject") or ""),
        body=str(fields.get("body") or ""),
        body_type=str(fields.get("body_type") or "html"),
        cc=_addresses(fields.get("cc")),
        bcc=_addresses(fields.get("bcc")),
        from_address=fields.get("from_address"),
        reply_to=fields.get("reply_to"),
        in_reply_to=fields.get("in_reply_to"),
        attachments=fields.get("attachments") or [],
    )


def _addresses(value: Any) -> list[str]:
    if value is None or value is MISSING:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def build_mime_message(
    to: list[str],
    subject: str,
    body: str,
    body_type: str = "html",
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    from_address: Any = None,
    reply_to: Any = None,
    in_reply_to: Any = None,
    attachments: Any = (),
) -> str:
    """An RFC 2822 message, base64url-encoded the way Gmail's API wants it.

    ``attachments`` items are ``{"name": ..., "content_bytes": <base64>,
    "content_type": ...}`` -- the same shape the Microsoft Graph tools take, so
    one caller-side attachment structure serves both providers.
    """
    import base64 as _base64
    from email.message import EmailMessage

    message = EmailMessage()
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    if from_address:
        message["From"] = str(from_address)
    if reply_to:
        message["Reply-To"] = str(reply_to)
    if in_reply_to:
        message["In-Reply-To"] = str(in_reply_to)
        message["References"] = str(in_reply_to)

    if str(body_type).lower() in ("html", "text/html"):
        message.set_content("This message needs an HTML-capable reader.")
        message.add_alternative(body, subtype="html")
    else:
        message.set_content(body)

    for attachment in attachments or ():
        if not isinstance(attachment, dict):
            continue
        raw = attachment.get("content_bytes") or ""
        try:
            data = _base64.b64decode(str(raw), validate=False)
        except Exception:  # noqa: BLE001 - a bad blob must not lose the message
            continue
        maintype, _, subtype = str(attachment.get("content_type") or "application/octet-stream").partition("/")
        message.add_attachment(
            data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=str(attachment.get("name") or "attachment"),
        )

    return _base64.urlsafe_b64encode(message.as_bytes()).decode()


def _bind_string(template: str, values: Mapping[str, Any]) -> Any:
    if "${" not in template:
        return template
    whole = PLACEHOLDER_RE.fullmatch(template.strip())
    if whole:
        resolved = _lookup(whole.group(1), values)
        return MISSING if resolved is None else resolved
    resolved = interpolate(template, dict(values))
    return MISSING if PLACEHOLDER_RE.search(resolved) else resolved


def _bind_path(template: str, values: Mapping[str, Any]) -> str:
    """Bind a url path, percent-encoding whatever goes into a segment.

    A message id or a file name is user data; dropping it into the path raw is
    how a stray ``/`` or ``?`` turns into a request against the wrong resource.

    The exception is a template that is *only* a placeholder: that slot holds a
    whole path rather than one segment, so its slashes are structural and are
    left alone.
    """
    if "${" not in template:
        return template

    whole = PLACEHOLDER_RE.fullmatch(template.strip())
    if whole:
        value = _lookup(whole.group(1), values)
        if value is None:
            return template
        path = str(value)
        if path.startswith(("http://", "https://")):
            # An absolute url is the whole address, not a path under a base.
            return path
        return path if path.startswith("/") else f"/{path}"

    def substitute(match: re.Match[str]) -> str:
        value = _lookup(match.group(1), values)
        if value is None:
            return match.group(0)
        return quote(str(value), safe="")

    return PLACEHOLDER_RE.sub(substitute, template)


def _lookup(key: str, values: Mapping[str, Any]) -> Any:
    if key in values:
        return values[key]
    return extract_value_by_path(dict(values), key)


def form_pairs(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a body into form pairs using bracket notation.

    ``{"metadata": {"tier": "gold"}, "items": [{"price": "p1"}]}`` becomes
    ``metadata[tier]=gold`` and ``items[0][price]=p1``, which is how Stripe and
    Twilio expect nested values.
    """
    pairs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            pairs.extend(form_pairs(item, f"{prefix}[{key}]" if prefix else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            pairs.extend(form_pairs(item, f"{prefix}[{index}]"))
    elif isinstance(value, bool):
        pairs.append((prefix, "true" if value else "false"))
    elif value is not None:
        pairs.append((prefix, str(value)))
    return pairs


def _as_query_value(value: Any) -> str:
    """Query strings are text: lists join with commas, booleans lower-case."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_as_query_value(v) for v in value)
    return str(value)


def _error_message(status: int, body: Any) -> str:
    """A one-line reason from whatever shape of error the provider returned."""
    if isinstance(body, dict):
        for key in ("error_description", "message", "error", "detail", "title"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return f"HTTP {status}: {value}"
            if isinstance(value, dict):
                nested = value.get("message") or value.get("description")
                if isinstance(nested, str) and nested:
                    return f"HTTP {status}: {nested}"
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            text = first.get("message") if isinstance(first, dict) else str(first)
            if text:
                return f"HTTP {status}: {text}"
    if isinstance(body, str) and body.strip():
        return f"HTTP {status}: {body.strip()[:200]}"
    return f"HTTP {status}"
