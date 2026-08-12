"""connector_manager -- 950+ API connectors, their auth requirements, and connections.

What this package does:

1. **List connectors** -- id, display name, icon SVG, categories, auth mode.
2. **Describe auth** -- exactly which fields (client id, client secret, api key,
   domain, ...) a connector needs, with titles, examples and validation rules.
3. **Connect** -- take those filled-in values, run the token exchange when the
   provider needs one, verify the credentials against a live endpoint, and
   return a ``Connection``.
4. **Use** -- refresh tokens and make authenticated requests with a connection.

What it deliberately does *not* do: store connections, encrypt secrets, or run
OAuth redirect flows. ``connect()`` returns a plain ``Connection`` object;
persistence and the OAuth/security layer stay in your application.

Sync::

    from connector_manager import ConnectorManager

    with ConnectorManager() as manager:
        for connector in manager.list_connectors(category="crm", limit=5):
            print(connector.id, connector.display_name)

        schema = manager.get_auth_schema("affinity-v2")
        for field in schema.user_fields():
            print(field.group.value, field.name, field.title, field.secret)

        connection = manager.connect("affinity-v2", credentials={"apiKey": "..."})
        saved = connection.to_dict()          # persist this yourself
        response = manager.request(connection, "GET", "/v2/persons")

Async -- same API, same auth logic, coroutines for the network parts::

    from connector_manager import AsyncConnectorManager, Connection

    async with AsyncConnectorManager() as manager:
        connection = await manager.connect("affinity-v2", credentials={"apiKey": "..."})
        connection = Connection.from_dict(saved)
        response = await manager.request(connection, "GET", "/v2/persons")
"""

from __future__ import annotations

from .auth import AuthContext, AuthStrategy, get_strategy, register_strategy
from .errors import (
    ConnectorError,
    ExternalAuthRequiredError,
    InterpolationError,
    RequestError,
    TokenExchangeError,
    UnknownConnectorError,
    UnsupportedAuthModeError,
    ValidationError,
    VerificationError,
)
from .flows import AsyncFlowRunner, Flow, FlowRunner
from .http import AsyncHttpClient, HttpClient, HttpResponse, Request
from .manager import AsyncConnectorManager, BaseConnectorManager, ConnectorManager
from .models import (
    EXTERNAL_OAUTH_MODES,
    SELF_SERVICE_MODES,
    UNSUPPORTED_MODES,
    AuthField,
    AuthMode,
    AuthSchema,
    Connection,
    Connector,
    ConnectorPage,
    FieldGroup,
)
from .proxy import RequestBuilder
from .registry import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, ConnectorRegistry
from .verification import CredentialVerifier, VerificationResult

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "EXTERNAL_OAUTH_MODES",
    "MAX_PAGE_SIZE",
    "SELF_SERVICE_MODES",
    "UNSUPPORTED_MODES",
    "AsyncConnectorManager",
    "AsyncFlowRunner",
    "AsyncHttpClient",
    "AuthContext",
    "AuthField",
    "AuthMode",
    "AuthSchema",
    "AuthStrategy",
    "BaseConnectorManager",
    "Connection",
    "Connector",
    "ConnectorError",
    "ConnectorManager",
    "ConnectorPage",
    "ConnectorRegistry",
    "CredentialVerifier",
    "ExternalAuthRequiredError",
    "FieldGroup",
    "Flow",
    "FlowRunner",
    "HttpClient",
    "HttpResponse",
    "InterpolationError",
    "Request",
    "RequestBuilder",
    "RequestError",
    "TokenExchangeError",
    "UnknownConnectorError",
    "UnsupportedAuthModeError",
    "ValidationError",
    "VerificationError",
    "VerificationResult",
    "__version__",
    "get_strategy",
    "register_strategy",
]
