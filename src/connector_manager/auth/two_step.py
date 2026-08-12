"""TWO_STEP -- providers that trade user credentials for a session token.

The provider definition describes the token request (url / params / headers /
body format), optionally extra chained steps (``additional_steps``), and where
the token lives in the response (``token_response``).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from ..credentials import parse_raw_credentials
from ..errors import TokenExchangeError, UnsupportedAuthModeError
from ..flows import Flow
from ..http import Request
from ..interpolation import (
    extract_step_number,
    interpolate,
    interpolate_deep,
    is_unresolved,
    make_url,
    stable_replacers,
    strip_credential,
    strip_step_response,
)
from ..models import AuthMode
from .base import AuthContext, AuthStrategy
from .jwt_auth import sign_provider_jwt

#: Keys the strategy manages itself and never copies back from user input.
_RESERVED = frozenset({"type", "token", "refresh_token", "expires_at", "raw"})


class TwoStepAuth(AuthStrategy):
    auth_mode = AuthMode.TWO_STEP
    refreshable = True

    def flow(self, ctx: AuthContext) -> Flow[dict[str, Any]]:
        provider = ctx.provider
        dynamic: dict[str, Any] = {**ctx.integration_config, **ctx.credentials}
        self._guard(ctx, dynamic)

        if provider.get("signature"):
            # A locally signed JWT becomes the credential the token call uses.
            dynamic["token"] = sign_provider_jwt(provider, dynamic, ctx.connection_config)["token"]

        response = yield self._first_request(ctx, dynamic)

        if response.status not in (200, 201):
            raise TokenExchangeError(
                f"Token request failed with status {response.status}",
                connector_id=ctx.connector_id,
                status=response.status,
                response=response.body(),
            )

        wanted_headers = provider.get("token_response_headers") or []
        header_values = _extract_header_values(response.headers, wanted_headers)
        step_responses: list[Any] = [response.json() if response.json() is not None else {}]

        for index, step in enumerate(provider.get("additional_steps") or [], start=1):
            step_response = yield self._step_request(ctx, step, dynamic, step_responses)
            if step_response.status not in (200, 201):
                raise TokenExchangeError(
                    f"Token request step {index} failed with status {step_response.status}",
                    connector_id=ctx.connector_id,
                    step=index,
                    status=step_response.status,
                    response=step_response.body(),
                )
            step_responses.append(
                step_response.json() if step_response.json() is not None else {}
            )
            for key, value in _extract_header_values(
                step_response.headers, wanted_headers
            ).items():
                if key == "_cookies" and header_values.get("_cookies"):
                    header_values["_cookies"] = f"{header_values['_cookies']}; {value}"
                else:
                    header_values[key] = value

        return self._credentials(ctx, dynamic, step_responses, header_values)

    # -- request building --------------------------------------------------

    def _guard(self, ctx: AuthContext, dynamic: dict[str, Any]) -> None:
        if ctx.provider.get("assertion") and not dynamic.get("refresh_token"):
            raise UnsupportedAuthModeError(
                f"Connector '{ctx.connector_id}' needs a SAML/JWT assertion, which is not implemented yet.",
                connector_id=ctx.connector_id,
            )
        if ctx.provider.get("body_format") == "xml":
            raise UnsupportedAuthModeError(
                f"Connector '{ctx.connector_id}' uses an XML token exchange, which is not implemented yet.",
                connector_id=ctx.connector_id,
            )

    def _first_request(self, ctx: AuthContext, dynamic: dict[str, Any]) -> Request:
        provider = ctx.provider
        # Some providers rate-limit the token url and expose a dedicated refresh url.
        wants_refresh = bool(
            provider.get("refresh_token_params") or provider.get("refresh_token_headers")
        )
        is_refresh = wants_refresh and bool(dynamic.get("refresh_token"))

        token_url = (
            (provider.get("refresh_url") or provider.get("token_url"))
            if is_refresh
            else provider.get("token_url")
        )
        token_params = (
            provider.get("refresh_token_params") if is_refresh else provider.get("token_params")
        )
        token_headers = (
            (provider.get("refresh_token_headers") or provider.get("token_headers"))
            if is_refresh
            else provider.get("token_headers")
        )

        if not isinstance(token_url, str) or not token_url.strip():
            raise TokenExchangeError(
                f"Connector '{ctx.connector_id}' has no token_url", connector_id=ctx.connector_id
            )

        return _build_request(
            url=make_url(token_url, {**ctx.connection_config, **dynamic}),
            method="GET" if provider.get("token_request_method") == "GET" else "POST",
            body=_resolve_params(token_params or {}, dynamic, ctx.connection_config),
            headers=_resolve_headers(token_headers or {}, dynamic, ctx.connection_config),
            body_format=provider.get("body_format") or "json",
        )

    def _step_request(
        self,
        ctx: AuthContext,
        step: dict[str, Any],
        dynamic: dict[str, Any],
        step_responses: list[Any],
    ) -> Request:
        return _build_request(
            url=_resolve_step_url(step["token_url"], step_responses, ctx.connection_config),
            method="GET" if step.get("token_request_method") == "GET" else "POST",
            body={
                key: _resolve_step_value(value, dynamic, step_responses, ctx.connection_config)
                for key, value in (step.get("token_params") or {}).items()
            },
            headers={
                key: _resolve_step_value(value, dynamic, step_responses, ctx.connection_config)
                for key, value in (step.get("token_headers") or {}).items()
            },
            body_format=step.get("body_format") or ctx.provider.get("body_format") or "json",
        )

    def _credentials(
        self,
        ctx: AuthContext,
        dynamic: dict[str, Any],
        step_responses: list[Any],
        header_values: dict[str, str],
    ) -> dict[str, Any]:
        final = step_responses[-1]
        if not isinstance(final, dict):
            final = {"value": final}
        parsed = parse_raw_credentials(final, AuthMode.TWO_STEP, ctx.provider)

        # Keep the user's own inputs (they are needed to refresh later).
        for key, value in dynamic.items():
            if value is not None and key not in _RESERVED and key not in ctx.integration_config:
                parsed[key] = value
        for key, value in header_values.items():
            if key not in _RESERVED:
                parsed[key] = value
        return parsed


def _build_request(
    url: str,
    method: str,
    body: dict[str, Any],
    headers: dict[str, Any],
    body_format: str,
) -> Request:
    send_headers = {k: str(v) for k, v in headers.items() if v is not None}
    if method == "GET":
        return Request("GET", url, headers=send_headers)

    if body_format == "form":
        send_headers.setdefault("content-type", "application/x-www-form-urlencoded")
        content = urlencode({k: v for k, v in body.items() if v is not None})
    else:
        send_headers.setdefault("content-type", "application/json")
        content = json.dumps(body)
    return Request("POST", url, headers=send_headers, content=content)


def _resolve_params(
    params: dict[str, Any], dynamic: dict[str, Any], connection_config: dict[str, Any]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        stripped = strip_credential(value)
        if isinstance(stripped, (dict, list)):
            out[key] = interpolate_deep(stripped, dynamic)
        elif isinstance(stripped, str):
            out[key] = interpolate(stripped, dynamic)
        else:
            out[key] = stripped
    # A second pass resolves ${connectionConfig.x} placeholders.
    return {
        key: interpolate(value, {"connectionConfig": connection_config, **connection_config})
        if isinstance(value, str)
        else value
        for key, value in out.items()
    }


def _resolve_headers(
    headers: dict[str, Any], dynamic: dict[str, Any], connection_config: dict[str, Any]
) -> dict[str, Any]:
    values = [v for v in headers.values() if isinstance(v, str)]
    namespace = {
        **connection_config,
        **dynamic,
        "connectionConfig": connection_config,
        **stable_replacers(values),
    }
    out: dict[str, Any] = {}
    for key, value in headers.items():
        stripped = strip_credential(value)
        if isinstance(stripped, (dict, list)):
            out[key] = interpolate_deep(stripped, namespace)
        elif isinstance(stripped, str):
            out[key] = interpolate(stripped, namespace)
        else:
            out[key] = stripped
    return out


def _resolve_step_value(
    value: Any, dynamic: dict[str, Any], step_responses: list[Any], connection_config: dict[str, Any]
) -> Any:
    """Prefer a value taken from a previous step's response, else from credentials."""
    if not isinstance(value, str):
        return value

    step_number = extract_step_number(value)
    step_scope = _step_response(step_number, step_responses) if step_number else {}
    from_step = interpolate(strip_step_response(value), step_scope)
    if not is_unresolved(from_step):
        return from_step
    from_credentials = interpolate(
        strip_credential(value), {**connection_config, **dynamic, "connectionConfig": connection_config}
    )
    return from_credentials if not is_unresolved(from_credentials) else from_step


def _resolve_step_url(
    template: str, step_responses: list[Any], connection_config: dict[str, Any]
) -> str:
    step_number = extract_step_number(template)
    step_scope = _step_response(step_number, step_responses) if step_number else {}
    return make_url(
        strip_step_response(template),
        {**connection_config, "connectionConfig": connection_config, **step_scope},
    )


def _step_response(step_number: int | None, step_responses: list[Any]) -> dict[str, Any]:
    if step_number is None or step_number < 1 or len(step_responses) < step_number:
        return {}
    value = step_responses[step_number - 1]
    return value if isinstance(value, dict) else {}


def _extract_header_values(headers: dict[str, str], wanted: list[str]) -> dict[str, str]:
    """Pull values (including cookies) out of a token response's headers."""
    result: dict[str, str] = {}
    cookie_pairs: list[str] = []
    for name in wanted:
        value = headers.get(name.lower())
        if not value:
            continue
        if name.lower() == "set-cookie":
            for cookie in value.split(","):
                pair = cookie.split(";")[0]
                if "=" in pair:
                    cookie_name, _, cookie_value = pair.partition("=")
                    cookie_name, cookie_value = cookie_name.strip(), cookie_value.strip()
                    result[cookie_name] = cookie_value
                    cookie_pairs.append(f"{cookie_name}={cookie_value}")
        else:
            result[name] = value
    if cookie_pairs:
        result["_cookies"] = "; ".join(cookie_pairs)
    return result
