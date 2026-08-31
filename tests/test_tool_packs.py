"""Every bundled tool pack, checked as data.

These tests are the contract a new ``data/tools/<auth-mode>/<connector>.yaml``
has to meet, and they run over every pack, so adding a connector's tools cannot
quietly ship a tool that names an argument it never declares, points at a path
it cannot resolve, or claims to be read-only while issuing a DELETE.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from connector_manager import AuthMode, Connection, ConnectorRegistry, ToolRegistry
from connector_manager.interpolation import is_unresolved
from connector_manager.models import FieldGroup
from connector_manager.tools.executor import ToolExecutor, template_arguments
from connector_manager.tools.models import PARAM_TYPES, TOOL_NAME_RE, Tool, ToolPack
from connector_manager.tools.registry import TOOLS_DIR

#: Methods a tool may use. Anything else is a typo.
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
#: Methods that only read, so must be flagged read_only and never destructive.
SAFE_METHODS = frozenset({"GET"})


@pytest.fixture(scope="module")
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


@pytest.fixture(scope="module")
def tools() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture(scope="module")
def packs(tools: ToolRegistry) -> list[ToolPack]:
    assert tools.packs, "expected bundled tool packs under data/tools/"
    return tools.packs


def all_tools(tools: ToolRegistry) -> list[Tool]:
    return [tool for pack in tools.packs for tool in pack.tools.values()]


def _id(tool: Tool) -> str:
    return tool.qualified_name


# -- layout ------------------------------------------------------------------


def test_packs_live_in_their_auth_mode_folder(packs: list[ToolPack], registry: ConnectorRegistry) -> None:
    """``data/tools/oauth2/hubspot.yaml`` -- folder mirrors the catalogue's sharding."""
    for pack in packs:
        path = Path(pack.source)
        assert path.stem == pack.connector_id, f"{path.name} should be named {pack.connector_id}.yaml"
        expected = registry.get(pack.connector_id).auth_mode.value.lower().replace("_", "-")
        assert path.parent.name == expected, (
            f"{path.name} is under {path.parent.name}/ but {pack.connector_id} is {expected}"
        )


def test_every_pack_targets_a_real_connector(packs: list[ToolPack], registry: ConnectorRegistry) -> None:
    for pack in packs:
        assert pack.connector_id in registry, pack.connector_id
        for other in pack.applies_to:
            assert other in registry, f"{pack.connector_id} applies_to unknown connector {other}"
            assert registry.get(other).auth_mode is registry.get(pack.connector_id).auth_mode, (
                f"{other} and {pack.connector_id} have different auth modes; they cannot share a pack"
            )


def test_packs_have_display_name_and_docs(packs: list[ToolPack]) -> None:
    for pack in packs:
        assert pack.display_name, f"{pack.connector_id} has no display_name"
        assert pack.docs_url and pack.docs_url.startswith("http"), (
            f"{pack.connector_id} has no docs_url -- reviewers need the source for its scopes"
        )


def test_no_connector_is_claimed_twice(tools: ToolRegistry) -> None:
    seen: dict[str, str] = {}
    for pack in tools.packs:
        for connector_id in pack.connector_ids:
            assert connector_id not in seen, f"{connector_id} served by both {seen[connector_id]} and {pack.source}"
            seen[connector_id] = pack.source


#: Connectors whose provider really does expose fewer than three endpoints, so a
#: small pack is the complete answer rather than an abandoned one. Each entry is
#: a claim someone checked against the provider's reference -- add to it only
#: after reading the docs, not to quieten the rule.
SMALL_BY_NATURE = {
    # Abstract sells one API per hostname, and this connector is wired to the
    # email validation one: a single GET is its entire surface.
    "abstract": 1,
}


def test_packs_are_not_empty(packs: list[ToolPack]) -> None:
    """A pack with one or two tools is usually one someone gave up on."""
    for pack in packs:
        floor = SMALL_BY_NATURE.get(pack.connector_id, 3)
        assert len(pack) >= floor, f"{pack.connector_id} ships only {len(pack)} tool(s)"


def test_the_small_pack_allowance_is_not_stale(packs: list[ToolPack]) -> None:
    """An allowance that stopped being needed should be deleted, not left lying."""
    sizes = {pack.connector_id: len(pack) for pack in packs}
    for connector_id, expected in SMALL_BY_NATURE.items():
        assert connector_id in sizes, f"{connector_id} is allowed a small pack but has none"
        assert sizes[connector_id] <= max(expected, 2), (
            f"{connector_id} now ships {sizes[connector_id]} tools -- drop it from SMALL_BY_NATURE"
        )


# -- tool shape --------------------------------------------------------------


def test_no_key_was_swallowed_by_yaml_booleans(packs: list[ToolPack]) -> None:
    """A bare `on:`/`off:`/`yes:`/`no:` key parses as a boolean, not a string.

    YAML 1.1 turns those into ``True``/``False``, so an argument or query
    parameter named `on` silently becomes a key of the wrong type. Quote it.
    """
    for pack in packs:
        for tool in pack.tools.values():
            for name in (p.name for p in tool.input):
                assert isinstance(name, str), f"{_id(tool)} has a non-string argument name {name!r}"
                assert name not in ("True", "False"), (
                    f"{_id(tool)} has an argument named {name!r} -- quote the key in the YAML"
                )
            for container in (tool.request.query, tool.request.headers):
                for key in container:
                    assert key not in ("True", "False"), (
                        f"{_id(tool)} has a {key!r} key -- quote it in the YAML"
                    )


def test_tool_names_are_snake_case(tools: ToolRegistry) -> None:
    for tool in all_tools(tools):
        assert TOOL_NAME_RE.match(tool.name), f"{_id(tool)} is not snake_case"


def test_tools_are_described(tools: ToolRegistry) -> None:
    """A thin description is the difference between a usable tool and a guess."""
    for tool in all_tools(tools):
        assert tool.title, f"{_id(tool)} has no title"
        assert len(tool.description) >= 40, f"{_id(tool)} has a {len(tool.description)}-char description"
        assert tool.category, f"{_id(tool)} has no category"


def test_requests_are_well_formed(tools: ToolRegistry) -> None:
    for tool in all_tools(tools):
        request = tool.request
        assert request.method in METHODS, f"{_id(tool)} uses method {request.method}"
        assert request.encoding in ("json", "form"), f"{_id(tool)} encoding {request.encoding!r}"
        assert request.path.startswith("/"), f"{_id(tool)} path {request.path!r} must start with /"
        if request.method in SAFE_METHODS:
            assert request.body is None, f"{_id(tool)} is a {request.method} with a body"


def test_read_only_and_destructive_match_the_method(tools: ToolRegistry) -> None:
    """The hints an agent runtime gates on must not contradict the verb.

    A POST may legitimately be read-only -- GraphQL, Graph's findMeetingTimes,
    Airtable's search -- so only the verbs that certainly mutate are policed.
    """
    for tool in all_tools(tools):
        method = tool.request.method
        if method in SAFE_METHODS:
            assert tool.read_only, f"{_id(tool)} is a {method} but is not read_only"
        if method in ("PUT", "PATCH", "DELETE"):
            assert not tool.read_only, f"{_id(tool)} is a {method} but claims read_only"
        if method == "DELETE":
            assert tool.destructive, f"{_id(tool)} deletes but is not flagged destructive"
        assert not (tool.read_only and tool.destructive), f"{_id(tool)} is both read_only and destructive"


def test_parameters_are_valid(tools: ToolRegistry) -> None:
    for tool in all_tools(tools):
        for param in tool.input:
            where = f"{_id(tool)}.{param.name}"
            assert param.type in PARAM_TYPES, f"{where} has type {param.type!r}"
            assert param.description, f"{where} has no description"
            assert TOOL_NAME_RE.match(param.name), f"{where} is not snake_case"
            if param.enum and param.default is not None:
                assert param.default in param.enum, f"{where} default {param.default!r} is not in its enum"
            if param.required:
                assert param.default is None, f"{where} is required yet carries a default"
            if param.type == "array":
                assert param.items is not None, f"{where} is an array with no items schema"


def test_outputs_are_described(tools: ToolRegistry) -> None:
    for tool in all_tools(tools):
        assert tool.output.description, f"{_id(tool)} does not describe its output"
        assert tool.output.type in ("object", "array", "string"), f"{_id(tool)} output type {tool.output.type}"
        if tool.output.type == "array":
            assert tool.output.items is not None, f"{_id(tool)} returns an array with no items schema"


# -- templates match the declared arguments ----------------------------------


def test_templates_only_read_declared_arguments(tools: ToolRegistry, registry: ConnectorRegistry) -> None:
    """No template may name an argument the tool does not accept.

    Connection-scoped values are the exception: a path like
    ``/ex/jira/${cloudId}/rest/api/3/issue`` is resolved by the RequestBuilder
    from the connection itself, not from the caller's arguments, so any field
    the connector's auth schema declares is allowed through.
    """
    for pack in tools.packs:
        schema = registry.auth_schema(pack.connector_id)
        from_connection = {f.name for f in schema.fields} | {
            "connectionConfig", "connection_config", "credentials", "integrationConfig", "accessToken"
        }
        for tool in pack.tools.values():
            declared = {p.name for p in tool.input}
            unknown = _template_arguments(tool) - declared - from_connection
            assert not unknown, f"{_id(tool)} templates read undeclared argument(s): {sorted(unknown)}"


def test_every_argument_reaches_the_request(tools: ToolRegistry) -> None:
    """An argument no template reads is dead weight in the tool's schema."""
    for tool in all_tools(tools):
        used = _template_arguments(tool)
        unused = {p.name for p in tool.input} - used
        assert not unused, f"{_id(tool)} declares unused argument(s): {sorted(unused)}"


def test_path_placeholders_are_required_arguments(tools: ToolRegistry) -> None:
    """A path slot with nothing in it would call the wrong URL, so it cannot be optional."""
    for tool in all_tools(tools):
        for name in template_arguments(tool.request.path):
            param = tool.parameter(name)
            if param is None:
                continue  # a connection-scoped value; checked above
            assert param.required or param.default is not None, (
                f"{_id(tool)} path segment ${{{name}}} is optional with no default"
            )


def _template_arguments(tool: Tool) -> set[str]:
    request = tool.request
    return (
        template_arguments(request.path)
        | template_arguments(request.query)
        | template_arguments(request.headers)
        | template_arguments(request.body)
        | template_arguments(request.content)
    )


# -- the tools actually build a request --------------------------------------


def test_every_tool_builds_a_resolvable_request(tools: ToolRegistry, registry: ConnectorRegistry) -> None:
    """The point of the whole layer: each tool must produce a real, resolved call.

    Synthetic arguments are fed through the executor's own validation and
    binding, so this catches a path that never resolves, a body that keeps a
    placeholder, and a required argument the schema forgot.
    """
    for pack in tools.packs:
        provider = registry.raw(pack.connector_id)
        connection = _connection(registry, pack.connector_id)
        for tool in pack.tools.values():
            executor = ToolExecutor(provider, tool, connection)
            request = executor.build(_arguments(tool))
            assert request.method == tool.request.method, _id(tool)
            assert request.url.startswith("http"), f"{_id(tool)} built url {request.url!r}"
            assert not is_unresolved(request.url), f"{_id(tool)} url keeps a placeholder: {request.url}"
            assert not is_unresolved(json.dumps(request.json_body or {})), (
                f"{_id(tool)} body keeps a placeholder: {request.json_body}"
            )
            if request.content is not None:
                assert not is_unresolved(str(request.content)), (
                    f"{_id(tool)} body keeps a placeholder: {request.content}"
                )
            for key, value in request.params.items():
                assert not is_unresolved(value), f"{_id(tool)} query {key} keeps a placeholder"
            for key, value in request.headers.items():
                assert isinstance(value, str), f"{_id(tool)} header {key} is {type(value).__name__}, not a string"
                assert not is_unresolved(value), f"{_id(tool)} header {key} keeps a placeholder"


def test_required_arguments_are_enforced(tools: ToolRegistry, registry: ConnectorRegistry) -> None:
    """Calling a tool with nothing must name every missing argument, not 400 later."""
    from connector_manager import ToolValidationError

    for pack in tools.packs:
        provider = registry.raw(pack.connector_id)
        connection = _connection(registry, pack.connector_id)
        for tool in pack.tools.values():
            required = [p.name for p in tool.required_parameters()]
            if not required:
                continue
            executor = ToolExecutor(provider, tool, connection)
            with pytest.raises(ToolValidationError) as err:
                executor.build({})
            assert set(required) <= set(err.value.argument_errors), _id(tool)


def test_only_writes_carry_a_body(tools: ToolRegistry, registry: ConnectorRegistry) -> None:
    """A POST/PUT/PATCH that sends nothing is almost always a missing template."""
    for pack in tools.packs:
        provider = registry.raw(pack.connector_id)
        connection = _connection(registry, pack.connector_id)
        for tool in pack.tools.values():
            if tool.request.method not in ("POST", "PUT", "PATCH"):
                continue
            if tool.request.body is None and tool.request.content is None:
                # Action-style POSTs (Graph's /send, Calendar's quickAdd) carry
                # everything in the path or the query string, which is fine --
                # what is not fine is a required argument with nowhere to go.
                addressable = template_arguments(tool.request.path) | template_arguments(tool.request.query)
                stranded = [p.name for p in tool.required_parameters() if p.name not in addressable]
                assert not stranded, f"{_id(tool)} is a {tool.request.method} whose arguments go nowhere: {stranded}"


def test_required_only_calls_send_nothing_hollow(tools: ToolRegistry, registry: ConnectorRegistry) -> None:
    """Building with only the required arguments must not leave empty objects.

    The full-argument build above cannot catch this: an optional argument that
    is the whole point of a nested object leaves ``{"contentType": "HTML"}``
    behind when it is omitted, which providers read as "set this field to
    nothing". A template that literally asks for ``{}`` is untouched -- what is
    forbidden is an object or array that *wanted* content and got none.
    """
    for pack in tools.packs:
        provider = registry.raw(pack.connector_id)
        connection = _connection(registry, pack.connector_id)
        for tool in pack.tools.values():
            required = {p.name: _value(p) for p in tool.required_parameters()}
            request = ToolExecutor(provider, tool, connection).build(required)
            for path, node in _walk(request.json_body):
                assert node != {} or _template_at(tool.request.body, path) == {}, (
                    f"{_id(tool)} sends an empty object at {path or '<body>'} "
                    f"when only its required arguments are given"
                )
                assert node != [], (
                    f"{_id(tool)} sends an empty array at {path or '<body>'} "
                    f"when only its required arguments are given"
                )


def _walk(node, path: str = ""):
    """Every dict and list inside a built body, with its dotted path."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        yield path, node
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def _template_at(template, path: str):
    """The template node a built path came from, or a sentinel when it is gone."""
    node = template
    for part in [p for p in path.replace("[", ".").replace("]", "").split(".") if p]:
        if isinstance(node, dict):
            node = node.get(part, None)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


# -- LLM specs ---------------------------------------------------------------


@pytest.mark.parametrize("format", ["anthropic", "openai", "mcp"])
def test_specs_are_json_serialisable(tools: ToolRegistry, format: str) -> None:
    for tool in all_tools(tools):
        spec = tool.spec(format=format)
        json.dumps(spec)  # raises on anything a runtime could not send
        schema = spec.get("input_schema") or spec.get("inputSchema") or spec["function"]["parameters"]
        assert schema["type"] == "object"
        assert set(schema["required"]) <= set(schema["properties"]), _id(tool)


def test_qualified_names_are_unique(tools: ToolRegistry) -> None:
    names = [t.qualified_name for t in all_tools(tools)]
    assert len(names) == len(set(names))


def test_to_dict_round_trips(tools: ToolRegistry) -> None:
    for pack in tools.packs:
        json.dumps(pack.to_dict())


# -- helpers -----------------------------------------------------------------


def _connection(registry: ConnectorRegistry, connector_id: str) -> Connection:
    """A plausible connection for a connector, so templated base urls resolve.

    Shopify wants a subdomain, Salesforce an instance url, Zendesk a subdomain:
    every connection_config field the catalogue declares is filled with an
    example, which is exactly what the real base_url templates read.
    """
    schema = registry.auth_schema(connector_id)
    config = {
        field.name: field.example or field.default_value or _placeholder(field.name)
        for field in schema.connection_config
    }
    config.setdefault("subdomain", "example")
    credentials = {
        "access_token": "test-access-token",
        "token": "test-token",
        "apiKey": "test-api-key",
        "api_key": "test-api-key",
        "username": "test-user",
        "password": "test-password",
    }
    for field in schema.credentials:
        credentials.setdefault(field.name, field.example or "test-value")
    return Connection(
        connection_id="test-connection",
        connector_id=connector_id,
        auth_mode=registry.get(connector_id).auth_mode,
        credentials=credentials,
        connection_config=config,
        # OAuth1 signing needs the consumer key/secret, which live here.
        integration_config={"client_id": "test-client-id", "client_secret": "test-client-secret"},
    )


def _placeholder(name: str) -> str:
    lowered = name.lower()
    if "url" in lowered or "domain" in lowered and "sub" not in lowered:
        return "https://example.com"
    return "example"


def _arguments(tool: Tool) -> dict[str, object]:
    """A synthetic value for every argument, required and optional alike."""
    values: dict[str, object] = {}
    for param in tool.input:
        values[param.name] = _value(param)
    return values


def _value(param) -> object:
    if param.enum:
        return param.enum[0]
    if param.default is not None:
        return param.default
    if param.type == "integer":
        return int(param.minimum) if param.minimum is not None else 1
    if param.type == "number":
        return float(param.minimum) if param.minimum is not None else 1.0
    if param.type == "boolean":
        return True
    if param.type == "array":
        item_type = (param.items or {}).get("type", "string")
        items = [_object_from(param.items or {})] if item_type == "object" else (
            ["example"] if item_type == "string" else [1]
        )
        if param.min_length is not None and len(items) < param.min_length:
            items = items * param.min_length
        return items
    if param.type == "object":
        return _object_from({"properties": param.properties or {}})
    if param.format == "email":
        return "person@example.com"
    value = param.example if isinstance(param.example, str) else "example"
    # Respect the parameter's own length bounds, so the fixture cannot fail
    # validation on a constraint the tool legitimately declares.
    if param.max_length is not None and len(value) > param.max_length:
        value = value[: param.max_length]
    if param.min_length is not None and len(value) < param.min_length:
        value = value.ljust(param.min_length, "x")
    return value


def _object_from(schema: dict) -> dict[str, object]:
    properties = schema.get("properties") or {}
    if not properties:
        return {"example": "value"}
    return {name: 1 if (spec or {}).get("type") in ("integer", "number") else "example" for name, spec in properties.items()}


# -- the lint script agrees with these tests ---------------------------------


def test_scaffold_check_script_passes() -> None:
    """`scripts/scaffold_tools.py --check` is the same contract, runnable by hand."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "scaffold_tools.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_scaffold_check_rejects_a_broken_pack(tmp_path: Path) -> None:
    """A pack that would break at call time must not pass the lint."""
    import subprocess
    import sys

    broken = tmp_path / "slack.yaml"
    broken.write_text(
        "connector_id: slack\n"
        "display_name: Slack\n"
        "docs_url: https://api.slack.com/methods\n"
        "tools:\n"
        "  bad:\n"
        "    description: short\n"
        "    request: {method: GET, path: no-leading-slash}\n"
        "    output: {}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "scripts" / "scaffold_tools.py"),
            "--check",
            "--path",
            str(broken),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "must start with /" in result.stderr


def test_readme_coverage_table_is_current() -> None:
    """The README's coverage table is generated, so it cannot drift."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "scripts" / "scaffold_tools.py"),
            "--readme",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "already up to date" in result.stdout, (
        "README's tool coverage was stale -- it has now been regenerated, commit the change"
    )


def test_tools_catalogue_is_current() -> None:
    """TOOLS.md is generated from the registry, so it cannot drift."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "scripts" / "scaffold_tools.py"),
            "--catalogue",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "already up to date" in result.stdout, (
        "TOOLS.md was stale -- it has now been regenerated, commit the change"
    )
