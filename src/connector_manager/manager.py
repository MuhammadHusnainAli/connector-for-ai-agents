"""The public entry points: :class:`ConnectorManager` and :class:`AsyncConnectorManager`.

Responsibilities, and nothing else:

* list connectors (id, display name, icon, categories, auth mode),
* describe what each connector needs in order to authenticate,
* take those filled-in values and produce a verified ``Connection``,
* refresh a connection's token, and make authenticated requests with it.

Storage, encryption, OAuth redirects and multi-tenancy live in your own layer:
``connect()`` hands back a plain ``Connection`` for you to persist however you
like, and every other method accepts one back.

All the catalogue/schema/validation logic lives on :class:`BaseConnectorManager`;
the two subclasses differ only in how they drive network flows.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Sequence

from .auth import AuthContext, AuthStrategy, get_strategy
from .errors import ToolPermissionError, UnknownConnectorError
from .flows import AsyncFlowRunner, FlowRunner
from .http import AsyncHttpClient, BaseHttpClient, HttpClient, HttpResponse, Request
from .models import AuthMode, AuthSchema, Connection, Connector, ConnectorPage
from .proxy import RequestBuilder
from .registry import DEFAULT_PAGE_SIZE, ConnectorRegistry
from .tools import (
    ScopeDiscoverer,
    ScopeDiscovery,
    Tool,
    ToolExecutor,
    ToolPack,
    ToolRegistry,
    ToolReport,
    ToolResult,
    baseline_pack,
    build_report,
)
from .validation import validate as validate_inputs
from .verification import CredentialVerifier, VerificationResult


class BaseConnectorManager:
    """Everything that needs no network access, shared by both managers."""

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.registry = registry or ConnectorRegistry()
        self.tools = tools or ToolRegistry()

    # ------------------------------------------------------------------
    # 1. Catalogue
    # ------------------------------------------------------------------

    def list_connectors(
        self,
        search: str | None = None,
        category: str | None = None,
        auth_mode: str | AuthMode | None = None,
        supported_only: bool = False,
        self_service_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Connector]:
        """Connectors matching the filters, ordered by display name."""
        return self.registry.list(
            search=search,
            category=category,
            auth_mode=auth_mode,
            supported_only=supported_only,
            self_service_only=self_service_only,
            limit=limit,
            offset=offset,
        )

    def list_connectors_dict(
        self, include_icon: bool = False, **filters: Any
    ) -> list[dict[str, Any]]:
        """Same as :meth:`list_connectors`, JSON-ready.

        ``include_icon=True`` inlines each SVG -- handy for a picker UI, heavy
        for a full 950+ dump (~8 MB), so it is off by default. Prefer
        :meth:`paginate_connectors` when you are feeding a paged UI.
        """
        return [c.to_dict(include_icon=include_icon) for c in self.list_connectors(**filters)]

    def paginate_connectors(
        self,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        offset: int | None = None,
        search: str | None = None,
        category: str | None = None,
        auth_mode: str | AuthMode | None = None,
        supported_only: bool = False,
        self_service_only: bool = False,
    ) -> ConnectorPage:
        """One page of the listing, with the total and next/prev offsets.

        Address the page by number (``page=2, page_size=20``) or by raw
        ``offset``; ``offset`` wins when both are given. The filters match
        :meth:`list_connectors`.

        >>> manager = ConnectorManager()
        >>> page = manager.paginate_connectors(page=2, page_size=20)
        >>> page.page, page.count, page.has_previous
        (2, 20, True)
        """
        return self.registry.paginate(
            page=page,
            page_size=page_size,
            offset=offset,
            search=search,
            category=category,
            auth_mode=auth_mode,
            supported_only=supported_only,
            self_service_only=self_service_only,
        )

    def iter_connector_pages(
        self,
        page_size: int = DEFAULT_PAGE_SIZE,
        start_offset: int = 0,
        **filters: Any,
    ) -> Iterator[ConnectorPage]:
        """Walk the whole filtered catalogue one page at a time.

        >>> manager = ConnectorManager()
        >>> ids = [c.id for page in manager.iter_connector_pages(page_size=200) for c in page]
        >>> len(ids) == len(manager)
        True
        """
        return self.registry.iter_pages(page_size=page_size, start_offset=start_offset, **filters)

    def get_connector(self, connector_id: str) -> Connector:
        return self.registry.get(connector_id)

    def get_icon(self, connector_id: str) -> str | None:
        """The connector's logo as an inline SVG string."""
        return self.registry.icon(connector_id)

    def categories(self) -> list[str]:
        return self.registry.categories()

    def auth_modes(self) -> dict[str, int]:
        """Auth mode -> connector count, most common first."""
        return self.registry.auth_modes()

    def __len__(self) -> int:
        return len(self.registry)

    def __iter__(self) -> Iterator[Connector]:
        return iter(self.registry)

    # ------------------------------------------------------------------
    # 2. Auth requirements
    # ------------------------------------------------------------------

    def get_auth_schema(self, connector_id: str) -> AuthSchema:
        """What this connector needs: credential fields + connection config fields."""
        return self.registry.auth_schema(connector_id)

    def describe_auth(self, connector_id: str) -> dict[str, Any]:
        """JSON-ready auth schema, suitable for rendering a form or a tool spec."""
        return self.get_auth_schema(connector_id).to_dict()

    def validate(
        self,
        connector_id: str,
        credentials: Mapping[str, Any] | None = None,
        connection_config: Mapping[str, Any] | None = None,
        integration_config: Mapping[str, Any] | None = None,
        require_all: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """Check filled-in values without calling the provider."""
        return validate_inputs(
            self.get_auth_schema(connector_id),
            credentials=credentials,
            connection_config=connection_config,
            integration_config=integration_config,
            require_all=require_all,
        )

    def requires_external_oauth(self, connector_id: str) -> bool:
        """True when the initial handshake must happen in your OAuth layer."""
        return self.registry.get(connector_id).requires_external_oauth

    def supports_self_service(self, connector_id: str) -> bool:
        """True when ``connect`` alone can produce a working connection."""
        return self.registry.get(connector_id).self_service

    # ------------------------------------------------------------------
    # 3. Request building (no I/O)
    # ------------------------------------------------------------------

    def request_builder(self, connection: Connection) -> RequestBuilder:
        """The object that resolves urls and auth headers for a connection."""
        return RequestBuilder(self.registry.raw(connection.connector_id), connection)

    def prepare_request(
        self,
        connection: Connection,
        method: str,
        endpoint: str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        json_body: Any = None,
        data: Any = None,
    ) -> Request:
        """Resolve url + auth headers for an API call without sending it.

        Useful when the actual call belongs to another layer (an agent tool
        runtime, a queue worker, a different HTTP client).
        """
        payload = body if body is not None else (json_body if json_body is not None else data)
        content = (
            BaseHttpClient.build_request("POST", "https://x", data=data).content
            if data is not None
            else None
        )
        return self.request_builder(connection).build(
            method,
            endpoint,
            headers=headers,
            params=params,
            body=payload,
            json_body=json_body,
            content=content,
        )

    # ------------------------------------------------------------------
    # 4. Tools -- what a connector can do (no network)
    # ------------------------------------------------------------------

    def has_tools(self, connector_id: str) -> bool:
        """True when :meth:`list_tools` would return anything for this connector.

        That includes the one generated tool a connector gets from its own
        declared verification endpoint; use :meth:`has_authored_tools` for the
        stricter "ships a hand-authored pack".
        """
        return self._pack_for(connector_id) is not None

    def has_authored_tools(self, connector_id: str) -> bool:
        """True when a hand-authored tool pack is bundled for this connector."""
        return self.tools.has(connector_id)

    def tool_connectors(self, include_generated: bool = False) -> list[str]:
        """Connector ids that ship tools, aliases included.

        By default only the hand-authored packs. ``include_generated=True`` adds
        every connector that declares a verification endpoint, and so gets a
        generated ``check_connection`` tool.
        """
        authored = set(self.tools.connector_ids())
        if not include_generated:
            return sorted(authored)
        return sorted(
            authored | {c.id for c in self.registry if self._baseline_pack(c.id) is not None}
        )

    def tool_pack(self, connector_id: str) -> ToolPack:
        """The whole pack: tools, scope rules and how to discover scopes.

        Falls back to the generated single-tool pack when no hand-authored one
        is bundled, and raises only when the connector has neither.
        """
        pack = self._pack_for(connector_id)
        if pack is None:
            return self.tools.get_pack(connector_id)  # raises UnknownToolError
        return pack

    def list_tools(self, connector_id: str) -> list[Tool]:
        """Every tool this connector has, whatever the credential can do.

        >>> manager = ConnectorManager()
        >>> [t.name for t in manager.list_tools("outlook")][:2]
        ['list_messages', 'search_messages']
        """
        pack = self._pack_for(connector_id)
        return list(pack.tools.values()) if pack else []

    def get_tool(self, connector_id: str, name: str) -> Tool:
        pack = self._pack_for(connector_id)
        if pack is None or name not in pack.tools:
            return self.tools.tool(connector_id, name)  # raises with the available names
        return pack.tools[name]

    def describe_tools(self, connector_id: str, include_request: bool = True) -> dict[str, Any]:
        """JSON-ready description of a connector's whole tool surface."""
        return self.tool_pack(connector_id).to_dict(include_request=include_request)

    def search_tools(self, query: str, connector_id: str | None = None) -> list[Tool]:
        """Tools whose name, title, description or category mentions ``query``."""
        return self.tools.search(query, connector_id=connector_id)

    def tool_stats(self) -> dict[str, Any]:
        """How many packs and tools are bundled, and how far they reach.

        ``authored`` counts the hand-authored packs; ``generated`` counts the
        connectors that get a ``check_connection`` tool from their own declared
        verification endpoint instead.
        """
        stats = self.tools.stats()
        generated = [
            c.id
            for c in self.registry
            if not self.tools.has(c.id) and self._baseline_pack(c.id) is not None
        ]
        stats["generated_connectors"] = len(generated)
        stats["connectors_with_any_tool"] = stats["connectors_covered"] + len(generated)
        stats["connectors_without_tools"] = len(self.registry) - stats["connectors_with_any_tool"]
        return stats

    def tool_specs(
        self,
        connector_id: str,
        format: str = "anthropic",
        prefix: bool = False,
    ) -> list[dict[str, Any]]:
        """A connector's tools as LLM tool definitions.

        ``format`` is ``anthropic``, ``openai`` or ``mcp``. This is the whole
        surface; for only what a given credential may call, use
        :meth:`check_tools` and :meth:`ToolReport.specs`.
        """
        return [t.spec(format=format, prefix=prefix) for t in self.list_tools(connector_id)]

    # ------------------------------------------------------------------
    # 5. Tool permissions (no network)
    # ------------------------------------------------------------------

    def check_tools(
        self,
        connection: Connection,
        granted_scopes: Sequence[str] | None = None,
        connector_id: str | None = None,
        scope_source: str = "explicit",
    ) -> ToolReport:
        """Which of the connector's tools this connection may actually call.

        Reads the grant off the connection (what the token response said, or
        what your OAuth layer recorded) and compares it with each tool's
        required scopes, so a client id and secret with partial permissions
        yields a list of enabled tools and a list of disabled ones with the
        missing scopes named. Pass ``granted_scopes`` to judge against a grant
        you hold elsewhere; use :meth:`ConnectorManager.check_tools_live` to ask
        the provider instead.
        """
        connector_id = connector_id or connection.connector_id
        pack = self.tool_pack(connector_id)
        return build_report(
            pack,
            connection=connection,
            granted_scopes=granted_scopes,
            scope_source=scope_source,
            connector_id=connector_id,
        )

    def enabled_tool_specs(
        self,
        connection: Connection,
        format: str = "anthropic",
        granted_scopes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """LLM tool definitions for exactly what this connection can call."""
        return self.check_tools(connection, granted_scopes=granted_scopes).specs(format=format)

    # ------------------------------------------------------------------
    # 6. Tool calls (request building only; the managers send them)
    # ------------------------------------------------------------------

    def prepare_tool_request(
        self,
        connection: Connection,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Request:
        """Validate arguments and build the authenticated request, without sending.

        For agent runtimes that own the HTTP call, and for inspecting exactly
        what a tool would do before letting it.
        """
        return self._tool_executor(connection, name).build(arguments)

    def validate_tool_arguments(
        self,
        connector_id: str,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check arguments against a tool's input schema, filling defaults."""
        tool = self.get_tool(connector_id, name)
        placeholder = Connection(connection_id="", connector_id=connector_id, auth_mode=AuthMode.NONE)
        return ToolExecutor(self.registry.raw(connector_id), tool, placeholder).validate(arguments)

    # ------------------------------------------------------------------
    # internals shared by both flavours
    # ------------------------------------------------------------------

    def _baseline_pack(self, connector_id: str) -> ToolPack | None:
        """The generated pack for a connector, or ``None`` when it has no basis."""
        try:
            connector = self.registry.get(connector_id)
        except UnknownConnectorError:
            return None
        return baseline_pack(connector.id, connector.display_name, connector.raw)

    def _pack_for(self, connector_id: str) -> ToolPack | None:
        """The hand-authored pack if there is one, else the generated fallback."""
        return self.tools.pack(connector_id) or self._baseline_pack(connector_id)

    def _tool_executor(self, connection: Connection, name: str) -> ToolExecutor:
        tool = self.get_tool(connection.connector_id, name)
        return ToolExecutor(self.registry.raw(connection.connector_id), tool, connection)

    def _scope_discoverer(self, connection: Connection) -> ScopeDiscoverer:
        pack = self.tool_pack(connection.connector_id)
        return ScopeDiscoverer(self.registry.raw(connection.connector_id), pack, connection)

    def _guard_tool_scopes(self, connection: Connection, name: str) -> None:
        """Refuse a call the recorded grant already rules out.

        Only a *known* shortfall blocks: an unknown grant lets the call through
        so the provider gets the final say.
        """
        report = self.check_tools(connection)
        status = report.status(name)
        if status is not None and status.availability.value == "disabled":
            raise ToolPermissionError(
                f"Tool '{name}' needs scopes this connection does not have: "
                f"{', '.join(status.missing_scopes)}",
                tool=name,
                missing_scopes=list(status.missing_scopes),
            )

    def _connect_context(
        self,
        connector_id: str,
        credentials: Mapping[str, Any] | None,
        connection_config: Mapping[str, Any] | None,
        integration_config: Mapping[str, Any] | None,
    ) -> tuple[AuthStrategy, AuthContext, dict[str, dict[str, Any]], Connector]:
        connector = self.registry.get(connector_id)
        validated = self.validate(
            connector_id,
            credentials=credentials,
            connection_config=connection_config,
            integration_config=integration_config,
        )
        ctx = AuthContext(
            connector_id=connector.id,
            provider=connector.raw,
            auth_mode=connector.auth_mode,
            credentials=validated["credentials"],
            connection_config=validated["connection_config"],
            integration_config=validated["integration_config"],
        )
        return get_strategy(connector.auth_mode), ctx, validated, connector

    @staticmethod
    def _build_connection(
        connector: Connector,
        credentials: dict[str, Any],
        validated: dict[str, dict[str, Any]],
        connection_id: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> Connection:
        return Connection(
            connection_id=connection_id or "",
            connector_id=connector.id,
            auth_mode=connector.auth_mode,
            credentials=credentials,
            connection_config=validated["connection_config"],
            integration_config=validated["integration_config"],
            metadata=dict(metadata or {}),
        )

    def _refresh_context(self, connection: Connection) -> tuple[AuthStrategy, AuthContext]:
        connector = self.registry.get(connection.connector_id)
        ctx = AuthContext(
            connector_id=connector.id,
            provider=connector.raw,
            auth_mode=connector.auth_mode,
            credentials=dict(connection.credentials),
            connection_config=dict(connection.connection_config),
            integration_config=dict(connection.integration_config),
            is_refresh=True,
        )
        return get_strategy(connector.auth_mode), ctx

    def _verifier(self, connection: Connection) -> CredentialVerifier:
        return CredentialVerifier(self.registry.raw(connection.connector_id), connection)

    @staticmethod
    def _apply_verification(connection: Connection, result: VerificationResult) -> None:
        connection.verified = result.verified
        connection.metadata["verification"] = result.to_dict()


class ConnectorManager(BaseConnectorManager):
    """Synchronous catalogue + connection manager.

    >>> manager = ConnectorManager()
    >>> len(manager.list_connectors()) > 1500
    True
    >>> manager.get_auth_schema("affinity-v2").auth_mode
    <AuthMode.API_KEY: 'API_KEY'>
    """

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        http: HttpClient | None = None,
        timeout: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(registry)
        self.http = http or HttpClient(timeout=timeout, verify=verify_ssl)
        self.runner = FlowRunner(self.http)

    # -- connect -----------------------------------------------------------

    def connect(
        self,
        connector_id: str,
        credentials: Mapping[str, Any] | None = None,
        connection_config: Mapping[str, Any] | None = None,
        integration_config: Mapping[str, Any] | None = None,
        connection_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        verify: bool = True,
        require_verified: bool = False,
    ) -> Connection:
        """Authenticate a connector and return the resulting connection.

        Depending on the auth mode this validates the inputs, performs a token
        exchange or signs a token locally, then calls the provider's
        verification endpoint. The returned :class:`Connection` is yours to
        persist -- this package keeps no state.

        ``require_verified=True`` turns a failed verification into a
        :class:`~connector_manager.errors.VerificationError` instead of a
        connection flagged ``verified=False``.
        """
        strategy, ctx, validated, connector = self._connect_context(
            connector_id, credentials, connection_config, integration_config
        )
        resolved = self.runner.run(strategy.flow(ctx))
        connection = self._build_connection(connector, resolved, validated, connection_id, metadata)
        if verify:
            result = self.verify(connection)
            self._apply_verification(connection, result)
            if require_verified:
                result.raise_for_status(connector.id)
        return connection

    def import_connection(
        self,
        connector_id: str,
        credentials: Mapping[str, Any],
        connection_config: Mapping[str, Any] | None = None,
        integration_config: Mapping[str, Any] | None = None,
        connection_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        verify: bool = True,
    ) -> Connection:
        """Build a connection from tokens your own OAuth layer already obtained.

        Use this for OAUTH2 / OAUTH1 / MCP / GitHub-App connectors: run the
        redirect flow yourself, then pass the tokens here (``access_token``,
        optionally ``refresh_token`` plus ``client_id`` / ``client_secret`` if
        you want this package to refresh them later).
        """
        return self.connect(
            connector_id,
            credentials=credentials,
            connection_config=connection_config,
            integration_config=integration_config,
            connection_id=connection_id,
            metadata=metadata,
            verify=verify,
        )

    # -- maintain ----------------------------------------------------------

    def verify(self, connection: Connection) -> VerificationResult:
        """Call the provider's verification endpoint for a connection."""
        return self.runner.run(self._verifier(connection).flow())

    def refresh(self, connection: Connection) -> Connection:
        """Mint fresh credentials for a connection, in place.

        Works for the token-based modes (OAUTH2_CC, TWO_STEP, JWT, SIGNATURE,
        and OAUTH2 when a refresh token plus client id/secret are present).
        Static modes (API_KEY, BASIC, ...) have nothing to refresh and are
        returned untouched.
        """
        strategy, ctx = self._refresh_context(connection)
        if not strategy.refreshable:
            return connection
        connection.credentials = self.runner.run(strategy.refresh_flow(ctx))
        connection.touch()
        return connection

    def ensure_fresh(self, connection: Connection, buffer_seconds: int = 60) -> Connection:
        """Refresh only if the token is expired or about to be."""
        if connection.is_expired(buffer_seconds=buffer_seconds):
            return self.refresh(connection)
        return connection

    # -- use ---------------------------------------------------------------

    def request(
        self,
        connection: Connection,
        method: str,
        endpoint: str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        auto_refresh: bool = True,
    ) -> HttpResponse:
        """Make an authenticated call against the connector's API."""
        if auto_refresh:
            connection = self.ensure_fresh(connection)
        return self.http.send(
            self.prepare_request(
                connection,
                method,
                endpoint,
                headers=headers,
                params=params,
                json_body=json_body,
                data=data,
            )
        )

    # -- tools -------------------------------------------------------------

    def discover_scopes(self, connection: Connection) -> ScopeDiscovery:
        """Ask the provider which scopes this credential actually carries.

        Reads the access token's own claims where the provider issues a JWT
        (no request at all), otherwise calls its token-info endpoint. Falls back
        to whatever the connection recorded when the connector declares neither,
        so there is always an answer -- check ``.known`` to tell "no scopes"
        from "could not tell".
        """
        return self.runner.run(self._scope_discoverer(connection).flow())

    def check_tools_live(self, connection: Connection) -> ToolReport:
        """:meth:`check_tools`, but against the scopes the provider reports.

        This is the authoritative answer to "what can this client id and secret
        really do": the grant comes from the provider, not from what your app
        asked for.
        """
        discovery = self.discover_scopes(connection)
        if not discovery.known:
            return self.check_tools(connection)
        return self.check_tools(
            connection, granted_scopes=discovery.scopes, scope_source=discovery.source
        )

    def call_tool(
        self,
        connection: Connection,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        enforce_scopes: bool = True,
        auto_refresh: bool = True,
    ) -> ToolResult:
        """Run one of the connector's tools and return its parsed result.

        Arguments are validated against the tool's input schema first, so a bad
        call fails locally with every problem named rather than as a provider
        400. ``enforce_scopes`` refuses a call the recorded grant already rules
        out; an unknown grant never blocks.

            result = manager.call_tool(connection, "send_email", {
                "to": ["ada@example.com"], "subject": "Hi", "body": "..."})
            result.ok, result.data
        """
        if enforce_scopes:
            self._guard_tool_scopes(connection, name)
        executor = self._tool_executor(connection, name)
        request = executor.build(arguments)
        if auto_refresh:
            connection = self.ensure_fresh(connection)
            request = self._tool_executor(connection, name).build(arguments)
        return executor.parse(self.http.send(request))

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "ConnectorManager":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AsyncConnectorManager(BaseConnectorManager):
    """Asynchronous twin of :class:`ConnectorManager`.

    Catalogue and schema methods are inherited and stay synchronous (they only
    read bundled data). Everything that touches the network is a coroutine, and
    runs the exact same auth flows as the sync manager.

        async with AsyncConnectorManager() as manager:
            connection = await manager.connect("affinity-v2", credentials={"apiKey": "…"})
            response = await manager.request(connection, "GET", "/v2/persons")
    """

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        http: AsyncHttpClient | None = None,
        timeout: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(registry)
        self.http = http or AsyncHttpClient(timeout=timeout, verify=verify_ssl)
        self.runner = AsyncFlowRunner(self.http)

    # -- connect -----------------------------------------------------------

    async def connect(
        self,
        connector_id: str,
        credentials: Mapping[str, Any] | None = None,
        connection_config: Mapping[str, Any] | None = None,
        integration_config: Mapping[str, Any] | None = None,
        connection_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        verify: bool = True,
        require_verified: bool = False,
    ) -> Connection:
        """Async counterpart of :meth:`ConnectorManager.connect`."""
        strategy, ctx, validated, connector = self._connect_context(
            connector_id, credentials, connection_config, integration_config
        )
        resolved = await self.runner.run(strategy.flow(ctx))
        connection = self._build_connection(connector, resolved, validated, connection_id, metadata)
        if verify:
            result = await self.verify(connection)
            self._apply_verification(connection, result)
            if require_verified:
                result.raise_for_status(connector.id)
        return connection

    async def import_connection(
        self,
        connector_id: str,
        credentials: Mapping[str, Any],
        connection_config: Mapping[str, Any] | None = None,
        integration_config: Mapping[str, Any] | None = None,
        connection_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        verify: bool = True,
    ) -> Connection:
        """Async counterpart of :meth:`ConnectorManager.import_connection`."""
        return await self.connect(
            connector_id,
            credentials=credentials,
            connection_config=connection_config,
            integration_config=integration_config,
            connection_id=connection_id,
            metadata=metadata,
            verify=verify,
        )

    # -- maintain ----------------------------------------------------------

    async def verify(self, connection: Connection) -> VerificationResult:
        """Async counterpart of :meth:`ConnectorManager.verify`."""
        return await self.runner.run(self._verifier(connection).flow())

    async def refresh(self, connection: Connection) -> Connection:
        """Async counterpart of :meth:`ConnectorManager.refresh`."""
        strategy, ctx = self._refresh_context(connection)
        if not strategy.refreshable:
            return connection
        connection.credentials = await self.runner.run(strategy.refresh_flow(ctx))
        connection.touch()
        return connection

    async def ensure_fresh(self, connection: Connection, buffer_seconds: int = 60) -> Connection:
        """Async counterpart of :meth:`ConnectorManager.ensure_fresh`."""
        if connection.is_expired(buffer_seconds=buffer_seconds):
            return await self.refresh(connection)
        return connection

    # -- use ---------------------------------------------------------------

    async def request(
        self,
        connection: Connection,
        method: str,
        endpoint: str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        auto_refresh: bool = True,
    ) -> HttpResponse:
        """Async counterpart of :meth:`ConnectorManager.request`."""
        if auto_refresh:
            connection = await self.ensure_fresh(connection)
        return await self.http.send(
            self.prepare_request(
                connection,
                method,
                endpoint,
                headers=headers,
                params=params,
                json_body=json_body,
                data=data,
            )
        )

    # -- tools -------------------------------------------------------------

    async def discover_scopes(self, connection: Connection) -> ScopeDiscovery:
        """Async counterpart of :meth:`ConnectorManager.discover_scopes`."""
        return await self.runner.run(self._scope_discoverer(connection).flow())

    async def check_tools_live(self, connection: Connection) -> ToolReport:
        """Async counterpart of :meth:`ConnectorManager.check_tools_live`."""
        discovery = await self.discover_scopes(connection)
        if not discovery.known:
            return self.check_tools(connection)
        return self.check_tools(
            connection, granted_scopes=discovery.scopes, scope_source=discovery.source
        )

    async def call_tool(
        self,
        connection: Connection,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        enforce_scopes: bool = True,
        auto_refresh: bool = True,
    ) -> ToolResult:
        """Async counterpart of :meth:`ConnectorManager.call_tool`."""
        if enforce_scopes:
            self._guard_tool_scopes(connection, name)
        executor = self._tool_executor(connection, name)
        request = executor.build(arguments)
        if auto_refresh:
            connection = await self.ensure_fresh(connection)
            request = self._tool_executor(connection, name).build(arguments)
        return executor.parse(await self.http.send(request))

    async def aclose(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> "AsyncConnectorManager":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()


__all__ = ["AsyncConnectorManager", "BaseConnectorManager", "ConnectorManager"]
