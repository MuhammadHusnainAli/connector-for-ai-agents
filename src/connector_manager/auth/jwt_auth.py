"""JWT -- credentials are a locally signed token, no network call needed.

The provider definition carries the header/payload templates, the signing key
location (usually a user-supplied private key) and the token lifetime.
"""

from __future__ import annotations

import time
from typing import Any

from ..credentials import in_ms, iso
from ..errors import TokenExchangeError, ValidationError
from ..interpolation import (
    format_pem,
    interpolate,
    interpolate_deep,
    is_unresolved,
    pem_kind,
    strip_credential,
)
from ..models import AuthMode
from .base import AuthContext, AuthStrategy


class JwtAuth(AuthStrategy):
    auth_mode = AuthMode.JWT
    refreshable = True

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        signed = sign_provider_jwt(ctx.provider, dict(ctx.credentials), ctx.connection_config)
        expires_in_ms = float(ctx.provider["token"]["expires_in_ms"])
        return {
            "type": AuthMode.JWT.value,
            **ctx.credentials,
            "token": signed["token"],
            "expires_at": iso(in_ms(expires_in_ms)),
        }


def sign_provider_jwt(
    provider: dict[str, Any],
    dynamic_credentials: dict[str, Any],
    connection_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Sign the JWT described by ``provider.token`` / ``provider.signature``."""
    import jwt as pyjwt

    token_spec = provider.get("token")
    signature_spec = provider.get("signature")
    if not token_spec:
        raise TokenExchangeError("missing_token_body")
    if not signature_spec:
        raise TokenExchangeError("missing_signature_type")

    connection_config = connection_config or {}
    credentials = dict(dynamic_credentials)

    # Ghost admin keys arrive as "<id>:<secret>" and must be split before signing.
    private_key = credentials.get("privateKey")
    if isinstance(private_key, str) and ":" in private_key and "-----" not in private_key:
        key_id, _, secret = private_key.partition(":")
        credentials["privateKey"] = {"id": key_id, "secret": secret}

    merged_config = {**(credentials.get("connectionConfig") or {}), **connection_config}
    namespace = {**credentials, "connectionConfig": merged_config, **merged_config}

    payload = _resolve_template(token_spec.get("payload") or {}, namespace)
    header = _resolve_template(token_spec.get("header") or {}, namespace)

    now = int(time.time())
    payload["iat"] = now
    payload["exp"] = now + int(float(token_spec["expires_in_ms"]) / 1000)

    signing_key_template = strip_credential(token_spec.get("signing_key"))
    signing_key = (
        interpolate(signing_key_template, namespace)
        if isinstance(signing_key_template, str)
        else signing_key_template
    )
    if not signing_key or (isinstance(signing_key, str) and is_unresolved(signing_key)):
        raise ValidationError(
            "The signing key required by this connector is missing from the credentials",
            {"signing_key": "required"},
        )

    protocol = signature_spec.get("protocol")
    algorithm = header.get("alg") or token_spec["header"].get("alg") or "HS256"

    if protocol == "HMAC":
        encoding = signature_spec.get("hmac_secret_encoding") or "hex"
        key: Any = signing_key if encoding == "utf8" else bytes.fromhex(signing_key)
    else:
        key = format_pem(signing_key, pem_kind(signing_key))

    token = pyjwt.encode(payload, key, algorithm=algorithm, headers=header or None)
    return {"token": token}


def _resolve_template(spec: dict[str, Any], namespace: dict[str, Any]) -> dict[str, Any]:
    """Interpolate a header/payload template, dropping unresolved entries."""
    out: dict[str, Any] = {}
    for key, value in spec.items():
        stripped = strip_credential(value)
        if stripped is None:
            out[key] = None
        elif isinstance(stripped, list):
            resolved: list[str] = []
            for item in stripped:
                if not isinstance(item, str):
                    continue
                text = interpolate(item, namespace)
                if is_unresolved(text):
                    continue
                resolved.extend(part.strip() for part in text.split(",") if part.strip())
            if resolved:
                out[key] = resolved
        elif isinstance(stripped, dict):
            out[key] = interpolate_deep(stripped, namespace)
        elif isinstance(stripped, str):
            text = interpolate(stripped, namespace)
            if not is_unresolved(text):
                out[key] = text
        else:
            out[key] = stripped
    return out
