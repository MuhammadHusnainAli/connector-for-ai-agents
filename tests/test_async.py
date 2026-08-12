"""The async manager, and its parity with the sync one.

Both managers drive the *same* auth flows, so these tests exist to prove the
async path produces identical results -- not to re-test the auth logic.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from connector_manager import (
    AsyncConnectorManager,
    AuthMode,
    Connection,
    ConnectorManager,
    ExternalAuthRequiredError,
    ValidationError,
)


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
async def manager() -> AsyncConnectorManager:
    async with AsyncConnectorManager() as m:
        yield m


pytestmark = pytest.mark.anyio


# -- catalogue (inherited, stays synchronous) -----------------------------------


async def test_catalogue_methods_are_shared(manager: AsyncConnectorManager) -> None:
    assert len(manager) > 900
    assert manager.get_connector("slack").display_name == "Slack"
    assert manager.get_auth_schema("affinity-v2").auth_mode is AuthMode.API_KEY
    assert "<svg" in (manager.get_icon("stripe") or "")
    assert manager.prepare_request(
        Connection(
            connection_id="c",
            connector_id="affinity-v2",
            auth_mode=AuthMode.API_KEY,
            credentials={"type": "API_KEY", "apiKey": "k"},
        ),
        "GET",
        "/v2/persons",
    ).headers["authorization"] == "Bearer k"


# -- connect -------------------------------------------------------------------


@respx.mock
async def test_api_key_connect_and_verify(manager: AsyncConnectorManager) -> None:
    route = respx.get("https://api.affinity.co/v2/auth/whoami").mock(
        return_value=httpx.Response(200, json={"tenant": {"id": 1}})
    )
    connection = await manager.connect("affinity-v2", credentials={"apiKey": "key-123"})

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer key-123"
    assert connection.verified is True
    assert connection.credentials["apiKey"] == "key-123"


@respx.mock
async def test_client_credentials_exchange(manager: AsyncConnectorManager) -> None:
    token = respx.post("https://api.1password.com/v1beta1/users/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    )
    connection = await manager.connect(
        "1password-users",
        credentials={"client_id": "5ab87915-2deb-429c-a1e2-8b0495900f45", "client_secret": "s"},
        connection_config={"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"},
        verify=False,
    )
    assert token.called
    assert connection.credentials["token"] == "tok-1"
    assert connection.is_expired() is False


@respx.mock
async def test_two_step_exchange(manager: AsyncConnectorManager) -> None:
    respx.post("https://acme.3cx.us/connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "session-tok"})
    )
    connection = await manager.connect(
        "3cx",
        credentials={"clientId": "cid", "clientSecret": "csecret"},
        connection_config={"domain": "acme.3cx.us"},
        verify=False,
    )
    assert connection.credentials["token"] == "session-tok"


async def test_jwt_needs_no_network(manager: AsyncConnectorManager) -> None:
    connection = await manager.connect(
        "ghost-admin",
        credentials={"privateKey": "1234567890abcdef12345678:" + "abcdef1234567890" * 4},
        connection_config={"adminDomain": "acme.ghost.io", "version": "v5.0"},
        verify=False,
    )
    assert connection.credentials["token"].count(".") == 2


async def test_validation_errors_are_raised_the_same_way(manager: AsyncConnectorManager) -> None:
    with pytest.raises(ValidationError):
        await manager.connect("affinity-v2", credentials={})


async def test_external_oauth_is_refused(manager: AsyncConnectorManager) -> None:
    with pytest.raises(ExternalAuthRequiredError):
        await manager.connect("slack", credentials={})


# -- maintain / use ------------------------------------------------------------


@respx.mock
async def test_refresh_and_ensure_fresh(manager: AsyncConnectorManager) -> None:
    respx.post("https://api.1password.com/v1beta1/users/oauth2/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok-1", "expires_in": 0}),
            httpx.Response(200, json={"access_token": "tok-2", "expires_in": 3600}),
        ]
    )
    connection = await manager.connect(
        "1password-users",
        credentials={"client_id": "5ab87915-2deb-429c-a1e2-8b0495900f45", "client_secret": "s"},
        connection_config={"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"},
        verify=False,
    )
    assert connection.is_expired() is True

    await manager.ensure_fresh(connection)
    assert connection.credentials["token"] == "tok-2"


@respx.mock
async def test_request(manager: AsyncConnectorManager) -> None:
    route = respx.get("https://api.affinity.co/v2/persons").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    connection = Connection(
        connection_id="c",
        connector_id="affinity-v2",
        auth_mode=AuthMode.API_KEY,
        credentials={"type": "API_KEY", "apiKey": "k"},
    )
    response = await manager.request(connection, "GET", "/v2/persons", params={"limit": 2})
    assert route.called and response.ok
    assert response.json() == {"data": []}
    assert route.calls.last.request.url.params["limit"] == "2"


@respx.mock
async def test_verify_reports_failure(manager: AsyncConnectorManager) -> None:
    respx.get("https://api.affinity.co/v2/auth/whoami").mock(return_value=httpx.Response(401))
    connection = Connection(
        connection_id="c",
        connector_id="affinity-v2",
        auth_mode=AuthMode.API_KEY,
        credentials={"type": "API_KEY", "apiKey": "bad"},
    )
    result = await manager.verify(connection)
    assert result.verified is False and result.status == 401


# -- parity --------------------------------------------------------------------


@respx.mock
async def test_sync_and_async_produce_the_same_credentials() -> None:
    """One auth implementation, two runners: the output must not differ."""
    payload = {"access_token": "same-token", "expires_in": 3600}
    respx.post("https://acme.3cx.us/connect/token").mock(
        return_value=httpx.Response(200, json=payload)
    )
    args = {
        "credentials": {"clientId": "cid", "clientSecret": "csecret"},
        "connection_config": {"domain": "acme.3cx.us"},
        "verify": False,
    }

    with ConnectorManager() as sync_manager:
        sync_connection = sync_manager.connect("3cx", **args)
    async with AsyncConnectorManager() as async_manager:
        async_connection = await async_manager.connect("3cx", **args)

    ignore = {"expires_at"}  # clock-dependent
    sync_creds = {k: v for k, v in sync_connection.credentials.items() if k not in ignore}
    async_creds = {k: v for k, v in async_connection.credentials.items() if k not in ignore}
    assert sync_creds == async_creds
