"""Build authenticated requests from a provider definition + a Connection.

:class:`RequestBuilder` resolves a connector's ``proxy.base_url``,
``proxy.headers`` and ``proxy.query`` templates against a connection and applies
the per-auth-mode authorization header. It performs no I/O, so the sync and async
managers share it unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any, Mapping
from urllib.parse import quote, urlencode, urlparse

from .errors import RequestError
from .http import Request
from .interpolation import has_placeholder, interpolate, is_unresolved, stable_replacers
from .models import AuthMode, Connection

#: Headers a caller may not silently lose when provider headers are merged in.
_CALLER_PRESERVED = ("user-agent",)


class RequestBuilder:
    """Turns ``(method, endpoint)`` into a fully authenticated :class:`Request`."""

    def __init__(self, provider: dict[str, Any], connection: Connection) -> None:
        self.provider = provider
        self.connection = connection

    # -- public API --------------------------------------------------------

    def build(
        self,
        method: str,
        endpoint: str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        json_body: Any = None,
        content: str | bytes | None = None,
    ) -> Request:
        method = method.upper()
        url = self.url(endpoint)
        payload = body if body is not None else json_body
        return Request(
            method=method,
            url=url,
            headers=self.headers(method, url, headers, payload),
            params=self.params(params),
            json_body=json_body,
            content=content,
        )

    def base_url(self) -> str:
        """Resolve the provider's proxy base url for this connection."""
        proxy = self.provider.get("proxy") or {}
        template = self.connection.connection_config.get("base_url") or proxy.get("base_url")
        if not template:
            raise RequestError(
                f"Connector '{self.connection.connector_id}' has no proxy.base_url; "
                "pass an absolute endpoint.",
                connector_id=self.connection.connector_id,
            )
        resolved = interpolate(str(template), self.namespace())
        if is_unresolved(resolved):
            raise RequestError(
                f"Could not resolve base_url template '{template}'",
                template=template,
                resolved=resolved,
            )
        return resolved.rstrip("/")

    def url(self, endpoint: str) -> str:
        """Join an endpoint onto the provider base url, resolving templates."""
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            resolved = interpolate(endpoint, self.namespace())
            if is_unresolved(resolved):
                raise RequestError(f"Could not resolve endpoint template '{endpoint}'")
            return resolved

        base = self.base_url()
        tail = interpolate(endpoint, self.namespace()).lstrip("/")
        host_and_path = base.split("://", 1)[-1]
        if tail and tail.startswith(host_and_path):
            tail = tail[len(host_and_path) :].lstrip("/")
        return f"{base}/{tail}" if tail else base

    def params(self, params: Mapping[str, Any] | None = None) -> dict[str, str]:
        """Caller params plus any ``proxy.query`` template (api-key-in-query)."""
        out: dict[str, str] = {k: str(v) for k, v in (params or {}).items()}
        namespace = self.namespace()
        for key, value in ((self.provider.get("proxy") or {}).get("query") or {}).items():
            if not isinstance(value, str):
                continue
            resolved = interpolate(value, namespace)
            if not is_unresolved(resolved):
                out[key] = resolved
        return out

    def headers(
        self,
        method: str,
        url: str,
        extra: Mapping[str, str] | None = None,
        body: Any = None,
    ) -> dict[str, str]:
        """Authorization header for the auth mode, merged with provider templates."""
        headers = self._authorization(method, url)
        headers.update(self._provider_headers(method, url, extra, body))
        for key, value in (extra or {}).items():
            lowered = key.lower()
            if lowered in _CALLER_PRESERVED and lowered in headers:
                continue
            headers[lowered] = value
        return headers

    def namespace(self) -> dict[str, Any]:
        """The interpolation namespace available to provider templates."""
        creds = dict(self.connection.credentials)
        config = dict(self.connection.connection_config)
        integration = dict(self.connection.integration_config)
        access_token = creds.get("access_token") or creds.get("token") or ""
        return {
            **config,
            **creds,
            "connectionConfig": config,
            "connection_config": config,
            "integrationConfig": integration,
            "credentials": creds,
            "accessToken": access_token,
            "clientId": creds.get("client_id") or integration.get("client_id") or "",
            "clientSecret": creds.get("client_secret") or integration.get("client_secret") or "",
            **integration,
        }

    # -- authorization -----------------------------------------------------

    def _authorization(self, method: str, url: str) -> dict[str, str]:
        creds = self.connection.credentials
        mode = AuthMode.parse(creds.get("type") or self.connection.auth_mode.value)
        proxy_headers = (self.provider.get("proxy") or {}).get("headers") or {}

        if mode in (AuthMode.BASIC, AuthMode.INSTALL_PLUGIN):
            raw = f"{creds.get('username', '')}:{creds.get('password', '') or ''}".encode()
            return {"authorization": "Basic " + base64.b64encode(raw).decode()}
        if mode in (AuthMode.OAUTH2, AuthMode.APP, AuthMode.MCP_OAUTH2, AuthMode.MCP_OAUTH2_GENERIC):
            return {"authorization": f"Bearer {creds.get('access_token', '')}"}
        if mode in (AuthMode.OAUTH2_CC, AuthMode.SIGNATURE, AuthMode.JWT):
            return {"authorization": f"Bearer {creds.get('token', '')}"}
        if mode is AuthMode.TWO_STEP:
            # Some TWO_STEP providers authenticate through a custom header/cookie instead.
            has_custom = any(
                isinstance(value, str)
                and (
                    (key.lower() == "cookie" and "${credentials._cookies}" in value)
                    or "${accessToken}" in value
                )
                for key, value in proxy_headers.items()
            )
            return {} if has_custom else {"authorization": f"Bearer {creds.get('token', '')}"}
        if mode is AuthMode.TBA:
            return {"authorization": self._tba_authorization(method, url)}
        if mode is AuthMode.OAUTH1:
            return {"authorization": self._oauth1_authorization(method, url)}
        # API_KEY and NONE carry no default header: the provider template decides.
        return {}

    def _provider_headers(
        self, method: str, url: str, extra: Mapping[str, str] | None, body: Any
    ) -> dict[str, str]:
        proxy_headers = (self.provider.get("proxy") or {}).get("headers") or {}
        if not proxy_headers:
            return {}

        values = [v for v in proxy_headers.values() if isinstance(v, str)]
        parsed = urlparse(url)
        content_type = ""
        for key, value in (extra or {}).items():
            if key.lower() == "content-type":
                content_type = str(value)

        namespace = {
            **self.namespace(),
            **stable_replacers(values),
            "method": method,
            "host": parsed.netloc,
            "path": parsed.path,
            "params": parsed.query,
            "urlCanonicalParams": parsed.query,
            "bodyCanonicalParams": _raw_body(method, body),
            "contentType": content_type,
            "endpoint": parsed.path.lstrip("/"),
        }

        out: dict[str, str] = {}
        for key, value in proxy_headers.items():
            if not isinstance(value, str):
                continue
            resolved = interpolate(value, namespace)
            if has_placeholder(value) and is_unresolved(resolved):
                # Leave the header off entirely rather than sending a broken template.
                continue
            out[key.lower()] = resolved
        return out

    # -- OAuth 1.0a style signing -----------------------------------------

    def _tba_authorization(self, method: str, url: str) -> str:
        """Token-based auth (NetSuite): OAuth 1.0a HMAC-SHA256 with a realm."""
        creds = self.connection.credentials
        config = self.connection.connection_config
        header = _oauth1_header(
            method=method,
            url=url,
            consumer_key=creds.get("client_id") or config.get("oauth_client_id") or "",
            consumer_secret=creds.get("client_secret") or config.get("oauth_client_secret") or "",
            token=creds.get("token_id", ""),
            token_secret=creds.get("token_secret", ""),
            signature_method="HMAC-SHA256",
        )
        realm = str(config.get("accountId", "")).replace("-", "_").upper()
        return header.replace("OAuth ", f'OAuth realm="{realm}", ', 1) if realm else header

    def _oauth1_authorization(self, method: str, url: str) -> str:
        creds = self.connection.credentials
        integration = self.connection.integration_config
        consumer_key = integration.get("client_id") or creds.get("client_id") or ""
        consumer_secret = integration.get("client_secret") or creds.get("client_secret") or ""
        if not consumer_key or not consumer_secret:
            raise RequestError(
                "OAuth1 requests need client_id/client_secret in the connection's integration_config"
            )
        return _oauth1_header(
            method=method,
            url=url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            token=creds.get("oauth_token", ""),
            token_secret=creds.get("oauth_token_secret", ""),
            signature_method=self.provider.get("signature_method") or "HMAC-SHA1",
        )


def _raw_body(method: str, body: Any) -> str:
    if method in ("GET", "HEAD") or body is None:
        return ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return urlencode(sorted(body.items()))
    return str(body)


def _oauth1_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
    signature_method: str,
) -> str:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": signature_method,
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }

    query_pairs = [
        tuple(pair.split("=", 1)) if "=" in pair else (pair, "")
        for pair in parsed.query.split("&")
        if pair
    ]
    all_pairs = sorted(list(oauth_params.items()) + query_pairs)
    normalized = "&".join(f"{_q(k)}={_q(v)}" for k, v in all_pairs)
    base_string = "&".join([method.upper(), _q(base), _q(normalized)])
    signing_key = f"{_q(consumer_secret)}&{_q(token_secret)}"

    digest = hashlib.sha1 if signature_method.upper().endswith("SHA1") else hashlib.sha256
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), digest).digest()
    ).decode()

    signed = {**oauth_params, "oauth_signature": signature}
    return "OAuth " + ", ".join(f'{_q(k)}="{_q(v)}"' for k, v in sorted(signed.items()))


def _q(value: str) -> str:
    return quote(str(value), safe="-._~")
