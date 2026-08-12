"""Auth modes whose initial handshake happens outside this package.

OAuth (and the MCP/GitHub-App variants) need a browser redirect, a callback URL
and client secrets that belong to your own OAuth + security layer. This package
deliberately does not run that flow. Instead:

1. your layer completes the flow and gets the tokens,
2. you call ``import_connection(...)`` with those tokens,
3. this package builds and verifies a :class:`~connector_manager.models.Connection`.

For OAUTH2 the refresh-token grant *is* implemented, so long-lived connections
can be kept alive here once you pass the client id/secret along.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

from ..credentials import parse_raw_credentials
from ..errors import ExternalAuthRequiredError, TokenExchangeError, UnsupportedAuthModeError
from ..flows import Flow
from ..http import Request
from ..interpolation import make_url
from ..models import AuthMode
from .base import AuthContext, AuthStrategy


class ExternalOAuthAuth(AuthStrategy):
    """Import-only strategy: stores tokens obtained elsewhere."""

    external_oauth = True
    token_keys: tuple[str, ...] = ("access_token",)

    def __init__(self, auth_mode: AuthMode) -> None:
        self.auth_mode = auth_mode

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        if not any(ctx.credentials.get(key) for key in self.token_keys):
            raise ExternalAuthRequiredError(
                f"Connector '{ctx.connector_id}' uses {self.auth_mode.value}: run the OAuth flow in "
                f"your own auth layer, then import the resulting tokens "
                f"({', '.join(self.token_keys)}).",
                connector_id=ctx.connector_id,
                auth_mode=self.auth_mode.value,
                required=list(self.token_keys),
            )
        return {"type": self.auth_mode.value, **ctx.credentials}


class OAuth2ImportAuth(ExternalOAuthAuth):
    """OAUTH2: import externally obtained tokens, refresh them here."""

    refreshable = True

    def __init__(self) -> None:
        super().__init__(AuthMode.OAUTH2)

    def refresh_flow(self, ctx: AuthContext) -> Flow[dict[str, Any]]:
        ctx.is_refresh = True
        request, client_id, client_secret, refresh_token = self._refresh_request(ctx)

        response = yield request

        if not response.ok:
            raise TokenExchangeError(
                f"Refresh request failed with status {response.status}",
                connector_id=ctx.connector_id,
                status=response.status,
                response=response.body(),
            )
        raw = response.json()
        if not isinstance(raw, dict):
            raise TokenExchangeError(
                "Refresh endpoint did not return a JSON object", connector_id=ctx.connector_id
            )

        parsed = parse_raw_credentials(raw, AuthMode.OAUTH2, ctx.provider)
        # Providers that omit refresh_token on refresh keep the previous one working.
        parsed["refresh_token"] = parsed.get("refresh_token") or refresh_token
        parsed["client_id"] = client_id
        if client_secret:
            parsed["client_secret"] = client_secret
        return parsed

    def _refresh_request(self, ctx: AuthContext) -> tuple[Request, str, str, str]:
        creds = ctx.credentials
        refresh_token = creds.get("refresh_token")
        client_id = creds.get("client_id") or ctx.integration_config.get("client_id")
        client_secret = creds.get("client_secret") or ctx.integration_config.get("client_secret")

        if not refresh_token:
            raise ExternalAuthRequiredError(
                f"Connection for '{ctx.connector_id}' has no refresh_token; re-run your OAuth flow.",
                connector_id=ctx.connector_id,
            )
        if not client_id:
            raise ExternalAuthRequiredError(
                "Refreshing an OAuth2 token needs the client_id (and usually client_secret) from "
                "your OAuth layer. Pass them via integration_config.",
                connector_id=ctx.connector_id,
            )

        provider = ctx.provider
        token_url = provider.get("refresh_url") or provider.get("token_url")
        if isinstance(token_url, dict):
            token_url = token_url.get("OAUTH2")
        if not token_url:
            raise TokenExchangeError(
                f"Connector '{ctx.connector_id}' has no token_url to refresh against",
                connector_id=ctx.connector_id,
            )

        url = make_url(str(token_url), {**ctx.connection_config, **creds})
        params = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            **(provider.get("refresh_params") or {}),
        }
        headers = {"content-type": "application/x-www-form-urlencoded"}
        if provider.get("token_request_auth_method") == "basic" and client_secret:
            token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["authorization"] = f"Basic {token}"
        else:
            params["client_id"] = client_id
            if client_secret:
                params["client_secret"] = client_secret

        request = Request("POST", url, headers=headers, content=urlencode(params))
        return request, client_id, client_secret or "", refresh_token


class OAuth1ImportAuth(ExternalOAuthAuth):
    token_keys = ("oauth_token",)

    def __init__(self) -> None:
        super().__init__(AuthMode.OAUTH1)


class UnsupportedAuth(AuthStrategy):
    """Placeholder for auth modes this package does not implement yet."""

    def __init__(self, auth_mode: AuthMode, reason: str) -> None:
        self.auth_mode = auth_mode
        self.reason = reason

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        raise UnsupportedAuthModeError(
            f"Connector '{ctx.connector_id}' uses {self.auth_mode.value}: {self.reason}",
            connector_id=ctx.connector_id,
            auth_mode=self.auth_mode.value,
        )
