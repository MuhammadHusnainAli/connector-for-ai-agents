"""Exception hierarchy for the connector manager."""

from __future__ import annotations

from typing import Any


class ConnectorError(Exception):
    """Base class for every error raised by this package."""

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"error": type(self).__name__, "message": self.message, **self.context}


class UnknownConnectorError(ConnectorError):
    """The requested connector id does not exist in the registry."""


class UnsupportedAuthModeError(ConnectorError):
    """The connector's auth mode is not handled by this package."""


class ExternalAuthRequiredError(ConnectorError):
    """The connector needs an OAuth flow, which is handled outside this package.

    Obtain the tokens with your own OAuth/security layer, then call
    ``ConnectorManager.import_connection`` to build a Connection object.
    """


class ValidationError(ConnectorError):
    """Supplied credentials / connection config failed schema validation."""

    def __init__(self, message: str, field_errors: dict[str, str] | None = None) -> None:
        super().__init__(message, field_errors=field_errors or {})
        self.field_errors = field_errors or {}


class InterpolationError(ConnectorError):
    """A provider template could not be fully resolved."""


class TokenExchangeError(ConnectorError):
    """The provider rejected the token request."""


class VerificationError(ConnectorError):
    """The credentials verification call failed."""


class RequestError(ConnectorError):
    """An authenticated proxy request failed."""
