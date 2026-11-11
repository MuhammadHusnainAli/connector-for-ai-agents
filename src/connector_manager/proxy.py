"""Build authenticated requests from a provider definition + a Connection.

:class:`RequestBuilder` resolves a connector's ``proxy.base_url``,
``proxy.headers``, ``proxy.query`` and ``proxy.body`` templates against a
connection and applies the per-auth-mode authorization header. It performs no
I/O, so the sync and async managers share it unchanged.
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
from .interpolation import (
    has_placeholder,
    interpolate,
    interpolate_deep,
    is_unresolved,
    stable_replacers,
)
from .models import AuthMode, Connection
from .signing import canonical_query, serialise_body, sign_acs3, sign_aws_sigv4

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
        json_body = self.body(json_body)
        payload = body if body is not None else json_body
        request = Request(
            method=method,
            url=url,
            headers=self.headers(method, url, headers, payload),
            params=self.params(params),
            json_body=json_body,
            content=content,
        )
        return self._sign(request)

    # -- request signing ----------------------------------------------------

    def _sign(self, request: Request) -> Request:
        """Apply a ``proxy.aws_sigv4`` or ``proxy.acs3`` signature, if declared.

        Signing must see the request exactly as sent, so a signed request
        carries its body as raw content and its query string inside the url.
        """
        proxy = self.provider.get("proxy") or {}
        sigv4, acs3 = proxy.get("aws_sigv4"), proxy.get("acs3")
        if not isinstance(sigv4, Mapping) and not isinstance(acs3, Mapping):
            return request

        creds = self.connection.credentials
        access_key = str(creds.get("username") or creds.get("accessKeyId") or "")
        secret_key = str(creds.get("password") or creds.get("secretAccessKey") or "")
        if not access_key or not secret_key:
            raise RequestError(
                f"Connector '{self.connection.connector_id}' signs requests and needs an access key "
                "id (username) and secret (password).",
                connector_id=self.connection.connector_id,
            )
        session_token = creds.get("sessionToken") or None
        namespace = self.namespace()
        raw = serialise_body(request.json_body, request.content)
        headers = dict(request.headers)
        if request.json_body is not None and request.content is None:
            headers.setdefault("content-type", "application/json")

        if isinstance(sigv4, Mapping):
            region = interpolate(str(sigv4.get("region") or "${connectionConfig.region}"), namespace)
            service = interpolate(str(sigv4.get("service") or ""), namespace)
            if is_unresolved(region) or is_unresolved(service) or not region or not service:
                raise RequestError(
                    f"Connector '{self.connection.connector_id}' could not resolve the SigV4 region/service.",
                    connector_id=self.connection.connector_id,
                )
            url, signed = sign_aws_sigv4(
                method=request.method,
                url=request.url,
                headers=headers,
                params=request.params,
                body=raw,
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                service=service,
                session_token=session_token,
            )
        else:
            assert isinstance(acs3, Mapping)
            for header, key in (("x-acs-version", "version"), ("x-acs-action", "action")):
                if acs3.get(key):
                    headers.setdefault(header, interpolate(str(acs3[key]), namespace))
            url, signed = sign_acs3(
                method=request.method,
                url=request.url,
                headers=headers,
                params=request.params,
                body=raw,
                access_key=access_key,
                secret_key=secret_key,
                security_token=session_token,
            )

        query = _signed_query(request.url, request.params)
        if query:
            url = url.split("?", 1)[0] + "?" + query
        return Request(
            method=request.method,
            url=url,
            headers=signed,
            params={},
            json_body=request.json_body,
            content=raw if (raw or request.content is not None) else None,
        )

    def body(self, json_body: Any = None) -> Any:
        """Caller body plus any ``proxy.body`` template (api-key-in-body).

        A handful of providers -- Adyntel, Mandrill, Sage -- authenticate on
        every call from a field inside the JSON body rather than from a header,
        and the catalogue records that as ``proxy.body``. Merging it here is
        what keeps those credentials out of every tool's argument list. The
        caller wins on a conflict, and a request with no JSON body of its own is
        left alone: this must never turn a GET into a request with content.
        """
        template = (self.provider.get("proxy") or {}).get("body")
        if not isinstance(template, Mapping) or not isinstance(json_body, Mapping):
            return json_body
        resolved = _drop_unresolved(interpolate_deep(dict(template), self.namespace()))
        return _merge(resolved, dict(json_body))

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


def _signed_query(url: str, params: Mapping[str, str]) -> str:
    """The canonical (sorted, RFC 3986) query both signers hash, for the wire."""
    return canonical_query(urlparse(url).query, params)


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



def _drop_unresolved(node: Any) -> Any:
    """Strip the keys whose template the connection could not fill in.

    A connector's ``proxy.body`` may name a connection_config field the user
    never supplied. Sending ``"${acctId}"`` verbatim is worse than sending
    nothing, so those keys are dropped -- and an object left empty by that goes
    with them, since providers read ``{}`` as "clear this".
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            cleaned = _drop_unresolved(value)
            if cleaned is None:
                continue
            out[key] = cleaned
        return out or None
    if isinstance(node, list):
        items = [c for c in (_drop_unresolved(v) for v in node) if c is not None]
        return items or None
    if isinstance(node, str) and is_unresolved(node):
        return None
    return node


def _merge(base: Any, override: Mapping[str, Any]) -> dict[str, Any]:
    """``override`` wins, but nested objects merge rather than replace."""
    out = dict(base or {})
    for key, value in override.items():
        existing = out.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            out[key] = _merge(existing, value)
        else:
            out[key] = value
    return out


def _q(value: str) -> str:
    return quote(str(value), safe="-._~")
