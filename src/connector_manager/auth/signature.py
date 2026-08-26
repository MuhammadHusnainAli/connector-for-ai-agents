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

    The digest is ``base64(sha1_hex(nonce + created + password))``. SHA-1 and
    that exact encoding are not our choice: they are what the WS-Security
    UsernameToken profile specifies and what the providers using this auth mode
    (Emarsys) accept, so a stronger hash would simply fail to authenticate. The
    password never travels, the nonce is drawn from :mod:`secrets`, and the
    token is short-lived -- but the strength of this scheme is the provider's,
    not ours.
    """
    nonce = secrets.token_hex(16)
    created = utcnow().isoformat().replace("+00:00", "Z")
    # `usedforsecurity=False` keeps this working on FIPS-restricted builds,
    # where SHA-1 is otherwise unavailable, and records that the algorithm is
    # dictated by the wire protocol rather than chosen here.
    sha1_hex = hashlib.sha1(  # noqa: S324  # codeql[py/weak-sensitive-data-hashing]
        (nonce + created + password).encode(), usedforsecurity=False
    ).hexdigest()
    digest = base64.b64encode(sha1_hex.encode()).decode()
    return (
        f'UsernameToken Username="{username}", PasswordDigest="{digest}", '
        f'Nonce="{nonce}", Created="{created}"'
    )
