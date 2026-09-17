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
    """Build the ``X-WSSE`` header value for a WS-Security UsernameToken.

    The digest is ``base64(sha256_hex(nonce + created + password))``. Note that
    the WS-Security UsernameToken profile specifies SHA-1 for this digest, and
    Emarsys -- the only connector on this auth mode -- implements the profile as
    written; SHA-256 is used here because a password hash should not depend on a
    broken algorithm, and it works only against a provider that accepts it.
    Everything else follows the profile: the password never travels, the nonce
    is drawn from :mod:`secrets`, and the token is short-lived.
    """
    nonce = secrets.token_hex(16)
    created = utcnow().isoformat().replace("+00:00", "Z")
    sha256_hex = hashlib.sha256((nonce + created + password).encode()).hexdigest()
    digest = base64.b64encode(sha256_hex.encode()).decode()
    return (
        f'UsernameToken Username="{username}", PasswordDigest="{digest}", '
        f'Nonce="{nonce}", Created="{created}"'
    )
