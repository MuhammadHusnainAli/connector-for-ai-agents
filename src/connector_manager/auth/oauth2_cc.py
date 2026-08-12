"""OAUTH2_CC -- the OAuth2 client-credentials grant.

Fully machine-to-machine, so this package can complete it end to end: the user
supplies a client id/secret, we POST the token endpoint and store the token.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

from ..credentials import parse_raw_credentials
from ..errors import TokenExchangeError, ValidationError
from ..flows import Flow
from ..http import Request
from ..interpolation import interpolate, make_url
from ..models import AuthMode
from .base import AuthContext, AuthStrategy


class OAuth2ClientCredentialsAuth(AuthStrategy):
    auth_mode = AuthMode.OAUTH2_CC
    refreshable = True

    def flow(self, ctx: AuthContext) -> Flow[dict[str, Any]]:
        request, client_id, client_secret = self._token_request(ctx)

        response = yield request

        if not response.ok:
            raise TokenExchangeError(
                f"Client credentials request failed with status {response.status}",
                connector_id=ctx.connector_id,
                status=response.status,
                response=response.body(),
            )

        raw = response.json()
        if not isinstance(raw, dict):
            raise TokenExchangeError(
                "Token endpoint did not return a JSON object",
                connector_id=ctx.connector_id,
                response=response.text[:500],
            )

        parsed = parse_raw_credentials(raw, AuthMode.OAUTH2_CC, ctx.provider)
        parsed["client_id"] = client_id
        parsed["client_secret"] = client_secret or ""
        return parsed

    def _token_request(self, ctx: AuthContext) -> tuple[Request, str, str]:
        """Build the token call: url, auth style, params and body format."""
        provider = ctx.provider
        token_url = provider.get("token_url")
        if isinstance(token_url, dict):
            token_url = token_url.get("OAUTH2CC") or token_url.get("OAUTH2")
        if not token_url or not str(token_url).strip():
            raise TokenExchangeError(
                f"Connector '{ctx.connector_id}' has no token_url", connector_id=ctx.connector_id
            )

        client_id = _first(ctx.credentials, "client_id", "clientId")
        client_secret = _first(ctx.credentials, "client_secret", "clientSecret")
        if not client_id:
            raise ValidationError("client_id is required", {"client_id": "required"})

        url = make_url(str(token_url), {**ctx.connection_config, **ctx.credentials})

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        body_format = provider.get("body_format") or "form"
        if body_format != "query":
            headers["content-type"] = (
                "application/json" if body_format == "json" else "application/x-www-form-urlencoded"
            )

        auth_method = provider.get("token_request_auth_method")
        if auth_method == "basic":
            if not client_secret:
                raise ValidationError("client_secret is required", {"client_secret": "required"})
            token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["authorization"] = f"Basic {token}"
        elif auth_method == "custom":
            if not client_secret:
                raise ValidationError("client_secret is required", {"client_secret": "required"})
            params["username"] = client_id
            params["password"] = client_secret
        elif auth_method == "private_key_jwt":
            params.update(_private_key_jwt_params(ctx, client_id, url))
        else:
            params["client_id"] = client_id
            if client_secret:
                params["client_secret"] = client_secret

        namespace = {
            **ctx.connection_config,
            **ctx.credentials,
            "connectionConfig": ctx.connection_config,
        }
        for key, value in (provider.get("token_params") or {}).items():
            if isinstance(value, str):
                resolved = interpolate(value, namespace)
                if "${" not in resolved:
                    params[key] = resolved
            elif value is not None:
                params[key] = str(value)

        scopes = ctx.connection_config.get("oauth_scopes") or ctx.credentials.get("scopes")
        if scopes:
            separator = provider.get("scope_separator") or " "
            params["scope"] = (
                separator.join(scopes)
                if isinstance(scopes, (list, tuple))
                else separator.join(str(scopes).split(","))
            )

        if body_format == "query":
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
            content: str | None = None
        elif body_format == "json":
            content = json.dumps(params)
        else:
            content = urlencode(params)

        return Request("POST", url, headers=headers, content=content), client_id, client_secret


def _first(source: dict[str, Any], *names: str) -> str:
    for name in names:
        value = source.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _private_key_jwt_params(ctx: AuthContext, client_id: str, url: str) -> dict[str, str]:
    """Build a ``client_assertion`` from a JWK private key (RFC 7523)."""
    import time
    import uuid

    import jwt as pyjwt
    from cryptography.hazmat.primitives import serialization

    raw_key = _first(ctx.credentials, "client_private_key", "privateKey")
    if not raw_key:
        raise ValidationError(
            "client_private_key is required for private_key_jwt", {"client_private_key": "required"}
        )
    try:
        jwk = json.loads(raw_key)
        key = serialization.load_pem_private_key(
            pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk)).private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            password=None,
        )
        kid = jwk.get("kid")
    except Exception as err:  # noqa: BLE001 - surfaced as a validation error
        raise ValidationError(f"invalid client_private_key format: {err}") from err

    now = int(time.time())
    assertion = pyjwt.encode(
        {
            "iss": client_id,
            "sub": client_id,
            "aud": url,
            "iat": now,
            "exp": now + 300,
            "jti": str(uuid.uuid4()),
        },
        key,
        algorithm="RS256",
        headers={"kid": kid} if kid else None,
    )
    return {
        "client_id": client_id,
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }
