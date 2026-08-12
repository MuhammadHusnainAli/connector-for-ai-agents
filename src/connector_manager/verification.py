"""Credential verification.

Most providers declare a cheap read-only endpoint under ``proxy.verification``.
Calling it is how we prove the credentials the user just entered actually work.

Like the auth strategies, :class:`CredentialVerifier` is written as a flow, so
the same code verifies through the sync and the async manager.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import VerificationError
from .flows import Flow
from .http import Request
from .interpolation import interpolate_deep
from .models import Connection
from .proxy import RequestBuilder


@dataclass(slots=True)
class VerificationResult:
    """Outcome of the verification call."""

    verified: bool
    tested: bool
    endpoint: str | None = None
    status: int | None = None
    reason: str | None = None
    response: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "tested": self.tested,
            "endpoint": self.endpoint,
            "status": self.status,
            "reason": self.reason,
        }

    def raise_for_status(self, connector_id: str) -> None:
        if self.verified:
            return
        raise VerificationError(
            self.reason or "Credential verification failed",
            connector_id=connector_id,
            endpoint=self.endpoint,
            status=self.status,
            response=self.response,
        )


class CredentialVerifier:
    """Calls a provider's ``proxy.verification`` endpoint for a connection."""

    def __init__(self, provider: dict[str, Any], connection: Connection) -> None:
        self.provider = provider
        self.connection = connection
        self.builder = RequestBuilder(provider, connection)

    def flow(self) -> Flow[VerificationResult]:
        """Try each declared endpoint until one answers 2xx."""
        skipped = self._skip_reason()
        if skipped is not None:
            return skipped

        spec = (self.provider.get("proxy") or {}).get("verification") or {}
        method = (spec.get("method") or "GET").upper()
        endpoints = spec.get("endpoints") or [""]
        if isinstance(endpoints, str):
            endpoints = [endpoints]
        base_override = spec.get("base_url_override")
        extra_headers = {
            key.lower(): str(value)
            for key, value in (spec.get("headers") or {}).items()
            if value is not None
        }
        body = spec.get("data")

        last: VerificationResult | None = None
        for endpoint in endpoints:
            response = yield self._request(method, endpoint, base_override, extra_headers, body)
            if response.ok:
                return VerificationResult(
                    verified=True, tested=True, endpoint=response.url, status=response.status
                )
            last = VerificationResult(
                verified=False,
                tested=True,
                endpoint=response.url,
                status=response.status,
                reason=f"Verification request returned {response.status}",
                response=response.body(),
            )

        return last or VerificationResult(
            verified=False, tested=True, reason="No endpoint was called"
        )

    # -- internals ---------------------------------------------------------

    def _skip_reason(self) -> VerificationResult | None:
        if self.provider.get("credentials_verification_script"):
            return VerificationResult(
                verified=False,
                tested=False,
                reason="This connector verifies credentials with a provider-specific script, which is not ported.",
            )
        if not (self.provider.get("proxy") or {}).get("verification"):
            return VerificationResult(
                verified=False, tested=False, reason="Connector declares no verification endpoint"
            )
        return None

    def _request(
        self,
        method: str,
        endpoint: str,
        base_override: str | None,
        extra_headers: dict[str, str],
        body: Any,
    ) -> Request:
        builder = self.builder if not base_override else self._override_builder(base_override)
        payload = (
            interpolate_deep(
                body,
                {**self.connection.connection_config, **self.connection.credentials},
            )
            if body
            else None
        )
        request = builder.build(method, endpoint, headers=extra_headers, body=payload)
        if payload is not None:
            request.headers.setdefault("content-type", "application/json")
            request.content = json.dumps(payload)
        return request

    def _override_builder(self, base_override: str) -> RequestBuilder:
        """A ``base_url_override`` must win over the connection's own base_url."""
        provider = {
            **self.provider,
            "proxy": {**(self.provider.get("proxy") or {}), "base_url": base_override},
        }
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
