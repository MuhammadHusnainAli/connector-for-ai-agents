"""connector_manager -- 1,586 API connectors, their auth, their tools, and connections.

What this package does:

1. **List connectors** -- id, display name, icon SVG, categories, auth mode.
2. **Describe auth** -- exactly which fields (client id, client secret, api key,
   domain, ...) a connector needs, with titles, examples and validation rules.
3. **Connect** -- take those filled-in values, run the token exchange when the
   provider needs one, verify the credentials against a live endpoint, and
   return a ``Connection``.
4. **Use** -- refresh tokens and make authenticated requests with a connection.
5. **Tools** -- what each connector can actually *do*, as named capabilities with
   typed inputs and described outputs, and which of them a given credential's
   scopes allow. See :mod:`connector_manager.tools`.

What it deliberately does *not* do: store connections, encrypt secrets, or run
OAuth redirect flows. ``connect()`` returns a plain ``Connection`` object;
persistence and the OAuth/security layer stay in your application.

Tools -- what a connector can do, and what this credential may do::

    manager.list_tools("outlook")                    # 54 named capabilities
    report = manager.check_tools(connection)         # enabled / disabled / unknown
    report.status("send_email").missing_scopes       # ['Mail.Send']
    manager.call_tool(connection, "create_draft", {"subject": "Hi", "body": "..."})

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
    ToolError,
    ToolPermissionError,
    ToolValidationError,
    UnknownToolError,
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
from .tools import (
    ScopeDiscoverer,
    ScopeDiscovery,
    ScopeDiscoverySpec,
    ScopeRules,
    Tool,
    ToolAvailability,
    ToolExecutor,
    ToolOutput,
    ToolPack,
    ToolParameter,
    ToolRegistry,
    ToolReport,
    ToolRequest,
    ToolResult,
    ToolStatus,
)
from .verification import CredentialVerifier, VerificationResult

__version__ = "0.2.0"

__all__ = [
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
    "DEFAULT_PAGE_SIZE",
    "EXTERNAL_OAUTH_MODES",
    "ExternalAuthRequiredError",
    "FieldGroup",
    "Flow",
    "FlowRunner",
    "HttpClient",
    "HttpResponse",
    "InterpolationError",
    "MAX_PAGE_SIZE",
    "Request",
    "RequestBuilder",
    "RequestError",
    "SELF_SERVICE_MODES",
    "ScopeDiscoverer",
    "ScopeDiscovery",
    "ScopeDiscoverySpec",
    "ScopeRules",
    "TokenExchangeError",
    "Tool",
    "ToolAvailability",
    "ToolError",
    "ToolExecutor",
    "ToolOutput",
    "ToolPack",
    "ToolParameter",
    "ToolPermissionError",
    "ToolRegistry",
    "ToolReport",
    "ToolRequest",
    "ToolResult",
    "ToolStatus",
    "ToolValidationError",
    "UNSUPPORTED_MODES",
    "UnknownConnectorError",
    "UnknownToolError",
    "UnsupportedAuthModeError",
    "ValidationError",
    "VerificationError",
    "VerificationResult",
    "__version__",
    "get_strategy",
    "register_strategy",
]
