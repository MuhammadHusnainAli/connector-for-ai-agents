"""SIGNATURE -- WS-Security UsernameToken, computed locally from user/password."""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any

from ..credentials import in_ms, iso, utcnow
from ..errors import UnsupportedAuthModeError
from ..models import AuthMode
from .base import AuthContext, AuthStrategy


class SignatureAuth(AuthStrategy):
    auth_mode = AuthMode.SIGNATURE
    refreshable = True

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        protocol = (ctx.provider.get("signature") or {}).get("protocol")
        if protocol != "WSSE":
            raise UnsupportedAuthModeError(
                f"Unsupported signature protocol '{protocol}'", protocol=protocol
            )
        username = str(ctx.credentials.get("username", ""))
        password = str(ctx.credentials.get("password", ""))
        expires_in_ms = float((ctx.provider.get("token") or {}).get("expires_in_ms") or 3_600_000)
        return {
            "type": AuthMode.SIGNATURE.value,
            **ctx.credentials,
            "username": username,
            "password": password,
            "token": generate_wsse(username, password),
            "expires_at": iso(in_ms(expires_in_ms)),
        }


def generate_wsse(username: str, password: str) -> str:
    nonce = secrets.token_hex(16)
    created = utcnow().isoformat().replace("+00:00", "Z")
    sha1_hex = hashlib.sha1((nonce + created + password).encode()).hexdigest()
    digest = base64.b64encode(sha1_hex.encode()).decode()
    return (
        f'UsernameToken Username="{username}", PasswordDigest="{digest}", '
        f'Nonce="{nonce}", Created="{created}"'
    )
