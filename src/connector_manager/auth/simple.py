"""Auth modes whose credentials are supplied directly by the user.

No token exchange happens here, so these flows need no I/O at all: the values
are normalised, stamped with their type and returned. Whether they actually work
is answered by the verification step (the connector's ``proxy.verification``).
"""

from __future__ import annotations

from typing import Any

from ..models import AuthMode
from .base import AuthContext, AuthStrategy


class NoneAuth(AuthStrategy):
    auth_mode = AuthMode.NONE

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        return {"type": AuthMode.NONE.value}


class ApiKeyAuth(AuthStrategy):
    auth_mode = AuthMode.API_KEY

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        return {"type": AuthMode.API_KEY.value, **ctx.credentials}


class BasicAuth(AuthStrategy):
    auth_mode = AuthMode.BASIC

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        creds = dict(ctx.credentials)
        return {
            "type": AuthMode.BASIC.value,
            **creds,
            "username": creds.get("username", ""),
            "password": creds.get("password", ""),
        }


class InstallPluginAuth(BasicAuth):
    """Providers that expose a plugin install step but authenticate as BASIC."""

    auth_mode = AuthMode.INSTALL_PLUGIN

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        return {**super().flow(ctx), "type": AuthMode.INSTALL_PLUGIN.value}


class TbaAuth(AuthStrategy):
    """Token-based auth (NetSuite): stored as-is, signed per request."""

    auth_mode = AuthMode.TBA

    def flow(self, ctx: AuthContext) -> dict[str, Any]:
        return {"type": AuthMode.TBA.value, **ctx.credentials}
