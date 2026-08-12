"""Auth strategy contract.

One strategy class per ``auth_mode``. A strategy turns user-supplied inputs into
a credentials dict and, where the provider supports it, mints a new token from
stored credentials.

Strategies never perform I/O themselves. They implement :meth:`AuthStrategy.flow`
which either

* returns the credentials dict directly (no network needed -- API_KEY, JWT, ...), or
* is a generator that ``yield``s :class:`~connector_manager.http.Request` objects
  and receives :class:`~connector_manager.http.HttpResponse` objects back.

That single implementation is then driven by ``FlowRunner`` (sync) or
``AsyncFlowRunner`` (async), so nothing here is duplicated per flavour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models import AuthMode


@dataclass(slots=True)
class AuthContext:
    """Everything a strategy needs for one connect/refresh attempt."""

    connector_id: str
    provider: dict[str, Any]
    auth_mode: AuthMode
    credentials: dict[str, Any] = field(default_factory=dict)
    connection_config: dict[str, Any] = field(default_factory=dict)
    integration_config: dict[str, Any] = field(default_factory=dict)
    is_refresh: bool = False

    def namespace(self) -> dict[str, Any]:
        """Interpolation namespace for token_url / token_params templates."""
        return {
            **self.connection_config,
            **self.credentials,
            "connectionConfig": self.connection_config,
            "credentials": self.credentials,
        }


class AuthStrategy(ABC):
    """Base class for auth-mode handlers."""

    auth_mode: AuthMode
    #: True when the mode needs a redirect-based flow owned by the caller.
    external_oauth: bool = False
    #: True when ``refresh_flow`` can mint a fresh token without user interaction.
    refreshable: bool = False

    @abstractmethod
    def flow(self, ctx: AuthContext) -> Any:
        """Produce the credentials dict, optionally yielding requests on the way."""

    def refresh_flow(self, ctx: AuthContext) -> Any:
        """Re-mint credentials. Defaults to re-running :meth:`flow`."""
        ctx.is_refresh = True
        return self.flow(ctx)
