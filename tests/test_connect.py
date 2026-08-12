"""End-to-end connect flows, with the provider APIs mocked."""

from __future__ import annotations

import httpx
import pytest
import respx

from connector_manager import (
    AuthMode,
    Connection,
    ConnectorManager,
    ExternalAuthRequiredError,
    ValidationError,
)


@pytest.fixture()
def manager() -> ConnectorManager:
    with ConnectorManager() as m:
        yield m


# -- API_KEY --------------------------------------------------------------------


@respx.mock
def test_api_key_connect_and_verify(manager: ConnectorManager) -> None:
    """Api key in, verification call out, verified connection back."""
    route = respx.get("https://api.affinity.co/v2/auth/whoami").mock(
        return_value=httpx.Response(200, json={"tenant": {"id": 1}})
    )

    connection = manager.connect("affinity-v2", credentials={"apiKey": "key-123"})

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer key-123"
    assert connection.verified is True
    assert connection.auth_mode is AuthMode.API_KEY
    assert connection.credentials["apiKey"] == "key-123"
    assert connection.connection_id


@respx.mock
def test_verification_failure_is_reported_not_raised(manager: ConnectorManager) -> None:
    respx.get("https://api.affinity.co/v2/auth/whoami").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    connection = manager.connect("affinity-v2", credentials={"apiKey": "nope"})
    assert connection.verified is False
    assert connection.metadata["verification"]["status"] == 401


@respx.mock
def test_require_verified_raises(manager: ConnectorManager) -> None:
    from connector_manager import VerificationError

    respx.get("https://api.affinity.co/v2/auth/whoami").mock(return_value=httpx.Response(403))
    with pytest.raises(VerificationError):
        manager.connect("affinity-v2", credentials={"apiKey": "nope"}, require_verified=True)


def test_missing_required_credential_is_rejected(manager: ConnectorManager) -> None:
    with pytest.raises(ValidationError) as excinfo:
        manager.connect("affinity-v2", credentials={})
    assert "apiKey" in excinfo.value.field_errors


def test_connection_config_pattern_is_enforced(manager: ConnectorManager) -> None:
    with pytest.raises(ValidationError) as excinfo:
        manager.connect(
            "1password-events",
            credentials={"apiKey": "eyJhbGciOi.eyJhbGciOi.signature"},
            connection_config={"domain": "not-an-allowed-enum"},
        )
    assert "domain" in excinfo.value.field_errors


# -- BASIC ----------------------------------------------------------------------


@respx.mock
def test_basic_auth_header(manager: ConnectorManager) -> None:
    import base64

    schema = manager.get_auth_schema("bamboohr-basic")
    assert schema.auth_mode is AuthMode.BASIC

    api_key = "59d783083fb25565aba21744e6bba90de8634de0"
    respx.get(f"https://api.bamboohr.com/api/gateway.php/acme/v1/meta/fields").mock(
        return_value=httpx.Response(200, json=[])
    )
    connection = manager.connect(
        "bamboohr-basic",
        credentials={"username": api_key},
        connection_config={"subdomain": "acme"},
    )
    # `password` defaults to "x" in the provider definition, so the user only enters a key.
    expected = "Basic " + base64.b64encode(f"{api_key}:x".encode()).decode()
    assert respx.calls.last.request.headers["authorization"] == expected
    assert connection.verified is True


# -- OAUTH2_CC ------------------------------------------------------------------


@respx.mock
def test_client_credentials_exchange(manager: ConnectorManager) -> None:
    token = respx.post("https://api.1password.com/v1beta1/users/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    )

    connection = manager.connect(
        "1password-users",
        credentials={"client_id": "5ab87915-2deb-429c-a1e2-8b0495900f45", "client_secret": "s3cret"},
        connection_config={"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"},
        verify=False,
    )

    assert token.called
    # token_request_auth_method: basic -> credentials go in the Authorization header.
    assert token.calls.last.request.headers["authorization"].startswith("Basic ")
    assert b"grant_type=client_credentials" in token.calls.last.request.content
    assert connection.credentials["token"] == "tok-1"
    assert connection.credentials["type"] == "OAUTH2_CC"
    assert connection.expires_at is not None
    assert connection.is_expired() is False


@respx.mock
def test_client_credentials_refresh_mints_a_new_token(manager: ConnectorManager) -> None:
    respx.post("https://api.1password.com/v1beta1/users/oauth2/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok-1", "expires_in": 0}),
            httpx.Response(200, json={"access_token": "tok-2", "expires_in": 3600}),
        ]
    )
    connection = manager.connect(
        "1password-users",
        credentials={"client_id": "5ab87915-2deb-429c-a1e2-8b0495900f45", "client_secret": "s3cret"},
        connection_config={"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"},
        verify=False,
    )
    assert connection.is_expired() is True

    manager.ensure_fresh(connection)
    assert connection.credentials["token"] == "tok-2"


@respx.mock
def test_client_credentials_error_surfaces(manager: ConnectorManager) -> None:
    from connector_manager import TokenExchangeError

    respx.post("https://api.1password.com/v1beta1/users/oauth2/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    with pytest.raises(TokenExchangeError) as excinfo:
        manager.connect(
            "1password-users",
            credentials={"client_id": "5ab87915-2deb-429c-a1e2-8b0495900f45", "client_secret": "bad"},
            connection_config={"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"},
            verify=False,
        )
    assert excinfo.value.context["status"] == 401


# -- TWO_STEP -------------------------------------------------------------------


@respx.mock
def test_two_step_exchange(manager: ConnectorManager) -> None:
    token = respx.post("https://acme.3cx.us/connect/token").mock(
        return_value=httpx.Response(200, json={"access_token": "session-tok"})
    )

    connection = manager.connect(
        "3cx",
        credentials={"clientId": "cid", "clientSecret": "csecret"},
        connection_config={"domain": "acme.3cx.us"},
        verify=False,
    )

    assert token.called
    body = token.calls.last.request.content.decode()
    assert "client_id=cid" in body and "grant_type=client_credentials" in body
    assert connection.credentials["token"] == "session-tok"
    # The user's inputs are kept so the token can be re-minted later.
    assert connection.credentials["clientId"] == "cid"


# -- JWT ------------------------------------------------------------------------


def test_jwt_is_signed_locally(manager: ConnectorManager) -> None:
    import jwt as pyjwt

    key_id = "1234567890abcdef12345678"
    secret_hex = "abcdef1234567890" * 4
    connection = manager.connect(
        "ghost-admin",
        credentials={"privateKey": f"{key_id}:{secret_hex}"},
        connection_config={"adminDomain": "acme.ghost.io", "version": "v5.0"},
        verify=False,
    )
    token = connection.credentials["token"]
    decoded = pyjwt.decode(
        token, bytes.fromhex(secret_hex), algorithms=["HS256"], audience=["/admin/"], options={"verify_aud": False}
    )
    assert decoded["exp"] > decoded["iat"]
    assert pyjwt.get_unverified_header(token)["kid"] == key_id


# -- external OAuth -------------------------------------------------------------


def test_oauth2_connector_refuses_to_run_the_flow(manager: ConnectorManager) -> None:
    assert manager.requires_external_oauth("slack") is True
    with pytest.raises(ExternalAuthRequiredError):
        manager.connect("slack", credentials={})


@respx.mock
def test_oauth2_tokens_can_be_imported(manager: ConnectorManager) -> None:
    respx.route(host="slack.com").mock(return_value=httpx.Response(200, json={"ok": True}))
    connection = manager.import_connection(
        "slack",
        credentials={"access_token": "xoxb-123", "refresh_token": "r", "client_id": "c", "client_secret": "s"},
    )
    assert connection.credentials["access_token"] == "xoxb-123"
    assert connection.auth_mode is AuthMode.OAUTH2


@respx.mock
def test_oauth2_refresh_uses_the_refresh_token(manager: ConnectorManager) -> None:
    respx.route(host="slack.com", path="/api/oauth.v2.access").mock(
        return_value=httpx.Response(200, json={"access_token": "new-token", "expires_in": 3600})
    )
    connection = Connection(
        connection_id="c1",
        connector_id="slack",
        auth_mode=AuthMode.OAUTH2,
        credentials={
            "type": "OAUTH2",
            "access_token": "old",
            "refresh_token": "r1",
            "client_id": "c",
            "client_secret": "s",
        },
    )
    manager.refresh(connection)
    assert connection.credentials["access_token"] == "new-token"
    assert connection.credentials["refresh_token"] == "r1"


# -- unsupported ----------------------------------------------------------------


def test_unsupported_auth_mode_is_explicit(manager: ConnectorManager) -> None:
    from connector_manager import UnsupportedAuthModeError

    aws = manager.list_connectors(auth_mode="AWS_SIGV4")
    assert aws, "expected at least one AWS_SIGV4 connector"
    schema = manager.get_auth_schema(aws[0].id)
    placeholder = lambda f: f.enum[0] if f.enum else (f.example or "placeholder")
    credentials = {f.name: placeholder(f) for f in schema.credentials}
    required = lambda fields: {f.name: placeholder(f) for f in fields if f.required}
    assert schema.unsupported_reason
    with pytest.raises(UnsupportedAuthModeError):
        manager.connect(
            aws[0].id,
            credentials=credentials,
            connection_config=required(schema.connection_config),
            integration_config=required(schema.integration_config),
            verify=False,
        )


# -- connection round-trip ------------------------------------------------------


def test_connection_serialises_for_external_storage() -> None:
    connection = Connection(
        connection_id="c1",
        connector_id="stripe-app",
        auth_mode=AuthMode.API_KEY,
        credentials={"type": "API_KEY", "apiKey": "sk"},
        connection_config={"domain": "acme.io"},
    )
    restored = Connection.from_dict(connection.to_dict())
    assert restored.to_dict() == connection.to_dict()
    assert restored.credentials["apiKey"] == "sk"
