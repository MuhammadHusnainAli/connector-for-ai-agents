"""Authenticated request building, across the whole catalogue."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from connector_manager import AuthMode, Connection, ConnectorManager
from connector_manager.interpolation import is_unresolved

#: Connectors whose base url only exists after a live handshake (the provider
#: returns the instance url / MCP server url), plus OAuth1 which needs consumer
#: credentials from the caller's OAuth layer.
CANNOT_BUILD_FROM_SCHEMA_ALONE = {
    "linear-mcp",
    "mcp-generic",
    "salesforce-cdp",
    "salesforce-jwt",
    "teamwork",
    "unauthenticated",
    "garmin",
    "smugmug",
    "trello",
    "twitter",
}


@pytest.fixture(scope="module")
def manager() -> ConnectorManager:
    with ConnectorManager() as m:
        yield m


def _placeholder_connection(manager: ConnectorManager, connector_id: str) -> Connection:
    schema = manager.get_auth_schema(connector_id)

    def value(field) -> str:
        if field.enum:
            return field.enum[0]
        return field.example or "placeholder"

    credentials = {f.name: value(f) for f in schema.credentials}
    credentials.setdefault("access_token", "test-token")
    credentials.setdefault("token", "test-token")
    credentials["type"] = schema.auth_mode.value
    return Connection(
        connection_id="test",
        connector_id=connector_id,
        auth_mode=schema.auth_mode,
        credentials=credentials,
        connection_config={f.name: value(f) for f in schema.connection_config},
        integration_config={f.name: value(f) for f in schema.integration_config},
    )


def test_every_connector_builds_a_resolved_request(manager: ConnectorManager) -> None:
    """No provider template may leak an unresolved ``${...}`` into a request."""
    problems: list[str] = []
    for connector in manager.list_connectors():
        if connector.id in CANNOT_BUILD_FROM_SCHEMA_ALONE:
            continue
        connection = _placeholder_connection(manager, connector.id)
        try:
            request = manager.prepare_request(connection, "GET", "/ping")
        except Exception as err:  # noqa: BLE001 - collected and reported below
            problems.append(f"{connector.id}: {type(err).__name__}: {err}")
            continue
        if is_unresolved(request.url):
            problems.append(f"{connector.id}: unresolved url {request.url}")
        for key, value in request.headers.items():
            if is_unresolved(str(value)):
                problems.append(f"{connector.id}: unresolved header {key}")
    assert problems == []


def test_connectors_needing_a_live_handshake_fail_loudly(manager: ConnectorManager) -> None:
    from connector_manager import RequestError

    for connector_id in sorted(CANNOT_BUILD_FROM_SCHEMA_ALONE):
        connection = _placeholder_connection(manager, connector_id)
        with pytest.raises(RequestError):
            manager.prepare_request(connection, "GET", "/ping")


def test_api_key_header_comes_from_the_provider_template(manager: ConnectorManager) -> None:
    connection = Connection(
        connection_id="c",
        connector_id="affinity-v2",
        auth_mode=AuthMode.API_KEY,
        credentials={"type": "API_KEY", "apiKey": "secret-key"},
    )
    request = manager.prepare_request(connection, "GET", "/v2/persons")
    assert request.url == "https://api.affinity.co/v2/persons"
    assert request.headers["authorization"] == "Bearer secret-key"


def test_connection_config_is_interpolated_into_the_base_url(manager: ConnectorManager) -> None:
    connection = Connection(
        connection_id="c",
        connector_id="bamboohr-basic",
        auth_mode=AuthMode.BASIC,
        credentials={"type": "BASIC", "username": "key", "password": "x"},
        connection_config={"subdomain": "acme"},
    )
    request = manager.prepare_request(connection, "GET", "/v1/employees/directory")
    assert request.url == "https://api.bamboohr.com/api/gateway.php/acme/v1/employees/directory"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"key:x").decode()


def test_absolute_endpoints_are_passed_through(manager: ConnectorManager) -> None:
    connection = Connection(
        connection_id="c",
        connector_id="affinity-v2",
        auth_mode=AuthMode.API_KEY,
        credentials={"type": "API_KEY", "apiKey": "k"},
    )
    request = manager.prepare_request(connection, "GET", "https://api.affinity.co/v2/lists")
    assert request.url == "https://api.affinity.co/v2/lists"


@respx.mock
def test_request_sends_the_prepared_call(manager: ConnectorManager) -> None:
    route = respx.get("https://api.affinity.co/v2/persons").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    connection = Connection(
        connection_id="c",
        connector_id="affinity-v2",
        auth_mode=AuthMode.API_KEY,
        credentials={"type": "API_KEY", "apiKey": "k"},
    )
    response = manager.request(connection, "GET", "/v2/persons", params={"limit": 1})
    assert route.called
    assert response.ok and response.json() == {"data": []}
    assert route.calls.last.request.url.params["limit"] == "1"


def test_tba_signs_each_request(manager: ConnectorManager) -> None:
    connection = Connection(
        connection_id="c",
        connector_id="netsuite-tba",
        auth_mode=AuthMode.TBA,
        credentials={
            "type": "TBA",
            "token_id": "tid",
            "token_secret": "tsecret",
            "client_id": "ck",
            "client_secret": "cs",
        },
        connection_config={"accountId": "TSTDRV-123"},
    )
    header = manager.prepare_request(connection, "GET", "/record/v1/customer").headers["authorization"]
    assert header.startswith('OAuth realm="TSTDRV_123"')
    assert 'oauth_signature_method="HMAC-SHA256"' in header
    assert 'oauth_token="tid"' in header
