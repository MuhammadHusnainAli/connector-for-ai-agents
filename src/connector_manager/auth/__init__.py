"""Auth strategy registry -- one class per auth mode."""

from __future__ import annotations

from ..models import AuthMode
from .base import AuthContext, AuthStrategy
from .external import (
    ExternalOAuthAuth,
    OAuth1ImportAuth,
    OAuth2ImportAuth,
    UnsupportedAuth,
)
from .jwt_auth import JwtAuth, sign_provider_jwt
from .oauth2_cc import OAuth2ClientCredentialsAuth
from .signature import SignatureAuth
from .simple import ApiKeyAuth, BasicAuth, InstallPluginAuth, NoneAuth, TbaAuth
from .two_step import TwoStepAuth

STRATEGIES: dict[AuthMode, AuthStrategy] = {
    AuthMode.NONE: NoneAuth(),
    AuthMode.API_KEY: ApiKeyAuth(),
    AuthMode.BASIC: BasicAuth(),
    AuthMode.INSTALL_PLUGIN: InstallPluginAuth(),
    AuthMode.TBA: TbaAuth(),
    AuthMode.OAUTH2_CC: OAuth2ClientCredentialsAuth(),
    AuthMode.TWO_STEP: TwoStepAuth(),
    AuthMode.JWT: JwtAuth(),
    AuthMode.SIGNATURE: SignatureAuth(),
    AuthMode.OAUTH2: OAuth2ImportAuth(),
    AuthMode.OAUTH1: OAuth1ImportAuth(),
    AuthMode.MCP_OAUTH2: ExternalOAuthAuth(AuthMode.MCP_OAUTH2),
    AuthMode.MCP_OAUTH2_GENERIC: ExternalOAuthAuth(AuthMode.MCP_OAUTH2_GENERIC),
    AuthMode.APP: ExternalOAuthAuth(AuthMode.APP),
    AuthMode.CUSTOM: ExternalOAuthAuth(AuthMode.CUSTOM),
    AuthMode.BILL: UnsupportedAuth(
        AuthMode.BILL, "the Bill.com session-token exchange is not implemented yet"
    ),
    AuthMode.AWS_SIGV4: UnsupportedAuth(
        AuthMode.AWS_SIGV4, "AWS SigV4 request signing is not implemented yet"
    ),
}


def get_strategy(auth_mode: AuthMode) -> AuthStrategy:
    strategy = STRATEGIES.get(auth_mode)
    if strategy is None:
        return UnsupportedAuth(auth_mode, "no strategy registered for this auth mode")
    return strategy


def register_strategy(strategy: AuthStrategy) -> None:
    """Plug in your own handler (or override a built-in one)."""
    STRATEGIES[strategy.auth_mode] = strategy


__all__ = [
    "STRATEGIES",
    "AuthContext",
    "AuthStrategy",
    "get_strategy",
    "register_strategy",
    "sign_provider_jwt",
]
