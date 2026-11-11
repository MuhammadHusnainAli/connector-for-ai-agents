//! The public entry points: [`ConnectorManager`] (blocking) and
//! [`AsyncConnectorManager`] (async).
//!
//! Both deref to [`BaseConnectorManager`], which holds everything that needs no
//! network: the catalogue, auth schemas, validation, request building, tools and
//! permission reports. The network operations are written once, as async
//! methods on the base taking a [`Transport`]; the blocking manager runs them
//! with [`block_on`] over a blocking client, the async one awaits them.

use std::ops::Deref;
use std::sync::Arc;

use serde_json::{Map, Value};

use crate::auth::{AuthContext, AuthStrategy, Strategies};
use crate::data::DataSource;
use crate::error::{Error, ErrorKind, Result};
use crate::http::{AsyncTransport, BlockingTransport, HttpOptions, HttpResponse, Request, Transport, block_on};
use crate::models::{AuthMode, AuthSchema, Connection, Connector, ConnectorPage};
use crate::proxy::{Call, RequestBuilder};
use crate::registry::{ConnectorFilter, ConnectorRegistry};
use crate::tools::{
    ScopeDiscovery, SpecFormat, Tool, ToolAvailability, ToolExecutor, ToolPack, ToolRegistry, ToolReport, ToolResult, baseline_pack,
    build_report, discover_scopes,
};
use crate::validation::{Validated, validate};
use crate::verification::{VerificationResult, verify};

/// Turn a JSON value into an argument object; anything but an object is empty.
fn object(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(m) => m,
        _ => Map::new(),
    }
}

/// What to connect with. Build it with the chained setters.
#[derive(Debug, Clone)]
pub struct ConnectOptions {
    pub credentials: Map<String, Value>,
    pub connection_config: Map<String, Value>,
    pub integration_config: Map<String, Value>,
    pub connection_id: Option<String>,
    pub metadata: Map<String, Value>,
    /// Call the connector's verification endpoint (default true).
    pub verify: bool,
    /// Turn a failed verification into an error instead of `verified = false`.
    pub require_verified: bool,
}

impl Default for ConnectOptions {
    fn default() -> Self {
        Self {
            credentials: Map::new(),
            connection_config: Map::new(),
            integration_config: Map::new(),
            connection_id: None,
            metadata: Map::new(),
            verify: true,
            require_verified: false,
        }
    }
}

impl ConnectOptions {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn credentials(mut self, v: Value) -> Self {
        self.credentials = object(v);
        self
    }
    pub fn connection_config(mut self, v: Value) -> Self {
        self.connection_config = object(v);
        self
    }
    pub fn integration_config(mut self, v: Value) -> Self {
        self.integration_config = object(v);
        self
    }
    pub fn metadata(mut self, v: Value) -> Self {
        self.metadata = object(v);
        self
    }
    pub fn connection_id(mut self, id: impl Into<String>) -> Self {
        self.connection_id = Some(id.into());
        self
    }
    pub fn verify(mut self, verify: bool) -> Self {
        self.verify = verify;
        self
    }
    pub fn require_verified(mut self) -> Self {
        self.require_verified = true;
        self
    }
}

/// Everything that needs no network access, shared by both managers.
#[derive(Clone)]
pub struct BaseConnectorManager {
    pub registry: ConnectorRegistry,
    pub tools: Arc<ToolRegistry>,
    pub strategies: Strategies,
}

impl BaseConnectorManager {
    /// The bundled catalogue and tool packs.
    pub fn new() -> Result<Self> {
        Self::from_source(DataSource::default())
    }

    /// A data tree laid out like the bundled one.
    pub fn from_source(source: DataSource) -> Result<Self> {
        Ok(Self {
            registry: ConnectorRegistry::from_source(source.clone())?,
            tools: Arc::new(ToolRegistry::from_source(source)?),
            strategies: Strategies::default(),
        })
    }

    pub fn with_parts(registry: ConnectorRegistry, tools: ToolRegistry) -> Self {
        Self { registry, tools: Arc::new(tools), strategies: Strategies::default() }
    }

    /// Plug in your own auth handler, or override a built-in one.
    pub fn register_strategy(&mut self, strategy: Arc<dyn AuthStrategy>) {
        self.strategies.register(strategy);
    }

    // -- 1. catalogue -----------------------------------------------------------

    /// Connectors matching the filter, ordered by display name.
    pub fn list_connectors(&self, filter: &ConnectorFilter, limit: Option<usize>, offset: usize) -> Vec<Connector> {
        self.registry.list(filter, limit, offset)
    }

    /// One page of the listing, with the total and next/previous offsets.
    pub fn paginate_connectors(
        &self,
        page: usize,
        page_size: usize,
        offset: Option<usize>,
        filter: &ConnectorFilter,
    ) -> Result<ConnectorPage> {
        self.registry.paginate(page, page_size, offset, filter)
    }

    /// Walk the whole filtered catalogue one page at a time.
    pub fn connector_pages(&self, page_size: usize, filter: &ConnectorFilter) -> Result<Vec<ConnectorPage>> {
        self.registry.iter_pages(page_size, 0, filter)
    }

    pub fn get_connector(&self, id: &str) -> Result<&Connector> {
        self.registry.get(id)
    }

    /// The connector's logo as an inline SVG string.
    pub fn get_icon(&self, id: &str) -> Option<String> {
        self.registry.icon(id)
    }

    pub fn categories(&self) -> Vec<String> {
        self.registry.categories()
    }

    /// Auth mode -> connector count, most common first.
    pub fn auth_modes(&self) -> Vec<(AuthMode, usize)> {
        self.registry.auth_modes()
    }

    pub fn len(&self) -> usize {
        self.registry.len()
    }

    pub fn is_empty(&self) -> bool {
        self.registry.is_empty()
    }

    // -- 2. auth requirements ---------------------------------------------------

    /// What this connector needs: credential fields and connection config fields.
    pub fn get_auth_schema(&self, id: &str) -> Result<AuthSchema> {
        self.registry.auth_schema(id)
    }

    /// JSON-ready auth schema, for rendering a form or a tool spec.
    pub fn describe_auth(&self, id: &str) -> Result<Value> {
        Ok(self.get_auth_schema(id)?.to_json())
    }

    /// Check filled-in values without calling the provider.
    pub fn validate(&self, id: &str, credentials: Value, connection_config: Value, integration_config: Value) -> Result<Validated> {
        validate(&self.get_auth_schema(id)?, &object(credentials), &object(connection_config), &object(integration_config), true)
    }

    pub fn requires_external_oauth(&self, id: &str) -> Result<bool> {
        Ok(self.registry.get(id)?.requires_external_oauth())
    }

    pub fn supports_self_service(&self, id: &str) -> Result<bool> {
        Ok(self.registry.get(id)?.self_service())
    }

    // -- 3. request building (no I/O) -------------------------------------------

    pub fn request_builder(&self, connection: &Connection) -> Result<RequestBuilder> {
        Ok(RequestBuilder::new(self.registry.raw(&connection.connector_id)?, connection.clone()))
    }

    /// Resolve url and auth headers for a call without sending it.
    pub fn prepare_request(&self, connection: &Connection, call: Call) -> Result<Request> {
        self.request_builder(connection)?.build(call)
    }

    // -- 4. tools (no network) --------------------------------------------------

    fn baseline(&self, id: &str) -> Option<ToolPack> {
        let connector = self.registry.get(id).ok()?;
        baseline_pack(&connector.id, &connector.display_name, &connector.raw)
    }

    fn pack_for(&self, id: &str) -> Result<Option<Arc<ToolPack>>> {
        match self.tools.pack(id)? {
            Some(p) => Ok(Some(p)),
            None => Ok(self.baseline(id).map(Arc::new)),
        }
    }

    /// True when [`Self::list_tools`] returns anything, generated tools included.
    pub fn has_tools(&self, id: &str) -> Result<bool> {
        Ok(self.pack_for(id)?.is_some())
    }

    /// True when a hand-authored pack is bundled for this connector.
    pub fn has_authored_tools(&self, id: &str) -> bool {
        self.tools.has(id)
    }

    /// Connector ids that ship tools; `include_generated` adds every connector with a generated pack.
    pub fn tool_connectors(&self, include_generated: bool) -> Vec<String> {
        let mut ids: std::collections::BTreeSet<String> = self.tools.connector_ids().into_iter().collect();
        if include_generated {
            ids.extend(self.registry.iter().filter(|c| self.baseline(&c.id).is_some()).map(|c| c.id.clone()));
        }
        ids.into_iter().collect()
    }

    /// The whole pack, falling back to the generated one.
    pub fn tool_pack(&self, id: &str) -> Result<Arc<ToolPack>> {
        match self.pack_for(id)? {
            Some(p) => Ok(p),
            None => self.tools.get_pack(id),
        }
    }

    /// Every tool this connector has, whatever the credential can do.
    pub fn list_tools(&self, id: &str) -> Result<Vec<Tool>> {
        Ok(self.pack_for(id)?.map(|p| p.tools.clone()).unwrap_or_default())
    }

    pub fn get_tool(&self, id: &str, name: &str) -> Result<Tool> {
        match self.pack_for(id)?.and_then(|p| p.get(name).cloned()) {
            Some(t) => Ok(t),
            None => self.tools.tool(id, name),
        }
    }

    /// JSON-ready description of a connector's whole tool surface.
    pub fn describe_tools(&self, id: &str, include_request: bool) -> Result<Value> {
        Ok(self.tool_pack(id)?.to_json(include_request))
    }

    /// Tools whose name, title, description or category mentions `query`.
    pub fn search_tools(&self, query: &str, connector_id: Option<&str>) -> Result<Vec<Tool>> {
        self.tools.search(query, connector_id)
    }

    /// How many packs and tools are bundled, and how far they reach.
    pub fn tool_stats(&self) -> Value {
        let mut stats = self.tools.stats();
        let generated = self.registry.iter().filter(|c| !self.tools.has(&c.id) && self.baseline(&c.id).is_some()).count();
        let covered = stats["connectors_covered"].as_u64().unwrap_or(0) as usize;
        let obj = stats.as_object_mut().unwrap();
        obj.insert("generated_connectors".into(), generated.into());
        obj.insert("connectors_with_any_tool".into(), (covered + generated).into());
        obj.insert("connectors_without_tools".into(), self.registry.len().saturating_sub(covered + generated).into());
        stats
    }

    /// A connector's tools as LLM tool definitions.
    pub fn tool_specs(&self, id: &str, format: SpecFormat, prefix: bool) -> Result<Vec<Value>> {
        Ok(self.list_tools(id)?.iter().map(|t| t.spec(format, prefix)).collect())
    }

    // -- 5. tool permissions (no network) ---------------------------------------

    /// Which tools this connection may call, judged against `granted` scopes or the
    /// grant recorded on the connection.
    pub fn check_tools(&self, connection: &Connection, granted: Option<Vec<String>>) -> Result<ToolReport> {
        let pack = self.tool_pack(&connection.connector_id)?;
        Ok(build_report(&pack, Some(connection), granted, "explicit", Some(&connection.connector_id)))
    }

    /// LLM tool definitions for exactly what this connection can call.
    pub fn enabled_tool_specs(&self, connection: &Connection, format: SpecFormat) -> Result<Vec<Value>> {
        Ok(self.check_tools(connection, None)?.specs(format, false))
    }

    // -- 6. tool calls (building only) ------------------------------------------

    fn executor(&self, connection: &Connection, name: &str) -> Result<ToolExecutor> {
        let tool = self.get_tool(&connection.connector_id, name)?;
        Ok(ToolExecutor::new(self.registry.raw(&connection.connector_id)?, tool, connection.clone()))
    }

    /// Validate arguments and build the authenticated request, without sending.
    pub fn prepare_tool_request(&self, connection: &Connection, name: &str, arguments: Value) -> Result<Request> {
        self.executor(connection, name)?.build(&object(arguments))
    }

    /// Check arguments against a tool's input schema, filling defaults.
    pub fn validate_tool_arguments(&self, connector_id: &str, name: &str, arguments: Value) -> Result<Map<String, Value>> {
        let tool = self.get_tool(connector_id, name)?;
        let placeholder = Connection::new(connector_id, AuthMode::None);
        ToolExecutor::new(self.registry.raw(connector_id)?, tool, placeholder).validate(&object(arguments))
    }

    fn guard_tool_scopes(&self, connection: &Connection, name: &str) -> Result<()> {
        let report = self.check_tools(connection, None)?;
        if let Some(status) = report.status(name).filter(|s| s.availability == ToolAvailability::Disabled) {
            return Err(Error::new(
                ErrorKind::ToolPermission,
                format!("Tool '{name}' needs scopes this connection does not have: {}", status.missing_scopes.join(", ")),
            )
            .with("tool", name)
            .with("missing_scopes", status.missing_scopes.clone()));
        }
        Ok(())
    }

    // -- network operations, written once ---------------------------------------

    fn context(
        &self,
        connector: &Connector,
        credentials: Map<String, Value>,
        config: Map<String, Value>,
        integration: Map<String, Value>,
        refresh: bool,
    ) -> AuthContext {
        AuthContext {
            connector_id: connector.id.clone(),
            provider: connector.raw.clone(),
            auth_mode: connector.auth_mode,
            credentials,
            connection_config: config,
            integration_config: integration,
            is_refresh: refresh,
        }
    }

    /// Authenticate a connector and return the connection (see [`ConnectorManager::connect`]).
    pub async fn connect_with(&self, transport: &dyn Transport, connector_id: &str, options: ConnectOptions) -> Result<Connection> {
        let connector = self.registry.get(connector_id)?.clone();
        let schema = self.registry.auth_schema(connector_id)?;
        let validated = validate(&schema, &options.credentials, &options.connection_config, &options.integration_config, true)?;
        let ctx = self.context(
            &connector,
            validated.credentials.clone(),
            validated.connection_config.clone(),
            validated.integration_config.clone(),
            false,
        );
        let strategy = self.strategies.get(connector.auth_mode);
        let credentials = strategy.flow(&ctx, transport).await?;
        let mut connection = Connection::new(connector.id.clone(), connector.auth_mode);
        if let Some(id) = options.connection_id.filter(|i| !i.is_empty()) {
            connection.connection_id = id;
        }
        connection.credentials = credentials;
        connection.connection_config = validated.connection_config;
        connection.integration_config = validated.integration_config;
        connection.metadata = options.metadata;
        if options.verify {
            let result = self.verify_with(transport, &connection).await?;
            connection.verified = result.verified;
            connection.metadata.insert("verification".into(), result.to_json());
            if options.require_verified {
                result.into_result(&connector.id)?;
            }
        }
        Ok(connection)
    }

    pub async fn verify_with(&self, transport: &dyn Transport, connection: &Connection) -> Result<VerificationResult> {
        verify(self.registry.raw(&connection.connector_id)?, connection, transport).await
    }

    pub async fn refresh_with(&self, transport: &dyn Transport, connection: &mut Connection) -> Result<()> {
        let connector = self.registry.get(&connection.connector_id)?.clone();
        let strategy = self.strategies.get(connector.auth_mode);
        if !strategy.refreshable() {
            return Ok(());
        }
        let ctx = self.context(
            &connector,
            connection.credentials.clone(),
            connection.connection_config.clone(),
            connection.integration_config.clone(),
            true,
        );
        connection.credentials = strategy.refresh_flow(&ctx, transport).await?;
        connection.touch();
        Ok(())
    }

    pub async fn ensure_fresh_with(&self, transport: &dyn Transport, connection: &mut Connection, buffer_seconds: i64) -> Result<()> {
        if connection.is_expired(buffer_seconds) {
            self.refresh_with(transport, connection).await?;
        }
        Ok(())
    }

    pub async fn request_with(
        &self,
        transport: &dyn Transport,
        connection: &mut Connection,
        call: Call,
        auto_refresh: bool,
    ) -> Result<HttpResponse> {
        if auto_refresh {
            self.ensure_fresh_with(transport, connection, 60).await?;
        }
        transport.send(self.prepare_request(connection, call)?).await
    }

    pub async fn discover_scopes_with(&self, transport: &dyn Transport, connection: &Connection) -> Result<ScopeDiscovery> {
        let pack = self.tool_pack(&connection.connector_id)?;
        discover_scopes(self.registry.raw(&connection.connector_id)?, &pack, connection, transport).await
    }

    pub async fn check_tools_live_with(&self, transport: &dyn Transport, connection: &Connection) -> Result<ToolReport> {
        let discovery = self.discover_scopes_with(transport, connection).await?;
        if !discovery.known() {
            return self.check_tools(connection, None);
        }
        let pack = self.tool_pack(&connection.connector_id)?;
        Ok(build_report(&pack, Some(connection), discovery.scopes, &discovery.source, Some(&connection.connector_id)))
    }

    pub async fn call_tool_with(
        &self,
        transport: &dyn Transport,
        connection: &mut Connection,
        name: &str,
        arguments: Value,
        enforce_scopes: bool,
        auto_refresh: bool,
    ) -> Result<ToolResult> {
        if enforce_scopes {
            self.guard_tool_scopes(connection, name)?;
        }
        let arguments = object(arguments);
        // Validate before refreshing, so a bad call fails locally and cheaply.
        self.executor(connection, name)?.build(&arguments)?;
        if auto_refresh {
            self.ensure_fresh_with(transport, connection, 60).await?;
        }
        let executor = self.executor(connection, name)?;
        let response = transport.send(executor.build(&arguments)?).await?;
        Ok(executor.parse(&response))
    }
}

/// Blocking catalogue and connection manager.
///
/// ```no_run
/// use connector_manager::{ConnectorManager, ConnectOptions, Call};
/// use serde_json::json;
///
/// let manager = ConnectorManager::new()?;
/// let schema = manager.get_auth_schema("sendgrid")?;
/// let mut connection = manager.connect("sendgrid", ConnectOptions::new().credentials(json!({"apiKey": "SG.xxx"})))?;
/// let response = manager.request(&mut connection, Call::new("GET", "/v3/user/profile"))?;
/// # Ok::<(), connector_manager::Error>(())
/// ```
pub struct ConnectorManager {
    base: BaseConnectorManager,
    transport: Box<dyn Transport>,
}

impl Deref for ConnectorManager {
    type Target = BaseConnectorManager;
    fn deref(&self) -> &Self::Target {
        &self.base
    }
}

impl ConnectorManager {
    /// Bundled data, a blocking HTTP client with default options.
    pub fn new() -> Result<Self> {
        Self::with_options(HttpOptions::default())
    }

    pub fn with_options(options: HttpOptions) -> Result<Self> {
        Ok(Self { base: BaseConnectorManager::new()?, transport: Box::new(BlockingTransport::new(&options)?) })
    }

    /// Any base and any transport whose futures complete synchronously (a test double, say).
    pub fn with_transport(base: BaseConnectorManager, transport: Box<dyn Transport>) -> Self {
        Self { base, transport }
    }

    pub fn base_mut(&mut self) -> &mut BaseConnectorManager {
        &mut self.base
    }

    /// Validate inputs, run any token exchange, verify, and return the connection.
    pub fn connect(&self, connector_id: &str, options: ConnectOptions) -> Result<Connection> {
        block_on(self.base.connect_with(&*self.transport, connector_id, options))
    }

    /// Build a connection from tokens your own OAuth layer already obtained.
    pub fn import_connection(&self, connector_id: &str, options: ConnectOptions) -> Result<Connection> {
        self.connect(connector_id, options)
    }

    /// Call the provider's verification endpoint for a connection.
    pub fn verify(&self, connection: &Connection) -> Result<VerificationResult> {
        block_on(self.base.verify_with(&*self.transport, connection))
    }

    /// Mint fresh credentials in place (token modes; static modes are left alone).
    pub fn refresh(&self, connection: &mut Connection) -> Result<()> {
        block_on(self.base.refresh_with(&*self.transport, connection))
    }

    /// Refresh only when the token is expired or within `buffer_seconds` of it.
    pub fn ensure_fresh(&self, connection: &mut Connection, buffer_seconds: i64) -> Result<()> {
        block_on(self.base.ensure_fresh_with(&*self.transport, connection, buffer_seconds))
    }

    /// Make an authenticated call, refreshing first if the token is about to expire.
    pub fn request(&self, connection: &mut Connection, call: Call) -> Result<HttpResponse> {
        block_on(self.base.request_with(&*self.transport, connection, call, true))
    }

    /// Send a request built elsewhere (e.g. by [`BaseConnectorManager::prepare_tool_request`]).
    pub fn send(&self, request: Request) -> Result<HttpResponse> {
        block_on(self.transport.send(request))
    }

    /// Ask the provider which scopes this credential actually carries.
    pub fn discover_scopes(&self, connection: &Connection) -> Result<ScopeDiscovery> {
        block_on(self.base.discover_scopes_with(&*self.transport, connection))
    }

    /// [`BaseConnectorManager::check_tools`] against the scopes the provider reports.
    pub fn check_tools_live(&self, connection: &Connection) -> Result<ToolReport> {
        block_on(self.base.check_tools_live_with(&*self.transport, connection))
    }

    /// Run one tool: validate, enforce known scopes, refresh if needed, call, parse.
    pub fn call_tool(&self, connection: &mut Connection, name: &str, arguments: Value) -> Result<ToolResult> {
        block_on(self.base.call_tool_with(&*self.transport, connection, name, arguments, true, true))
    }

    /// [`Self::call_tool`] with scope enforcement and auto-refresh chosen explicitly.
    pub fn call_tool_with_options(
        &self,
        connection: &mut Connection,
        name: &str,
        arguments: Value,
        enforce_scopes: bool,
        auto_refresh: bool,
    ) -> Result<ToolResult> {
        block_on(self.base.call_tool_with(&*self.transport, connection, name, arguments, enforce_scopes, auto_refresh))
    }
}

/// Async twin of [`ConnectorManager`]: the same flows, awaited. Needs a Tokio runtime.
///
/// ```no_run
/// # async fn run() -> connector_manager::Result<()> {
/// use connector_manager::{AsyncConnectorManager, ConnectOptions, Call};
/// use serde_json::json;
///
/// let manager = AsyncConnectorManager::new()?;
/// let mut connection = manager.connect("sendgrid", ConnectOptions::new().credentials(json!({"apiKey": "SG.xxx"}))).await?;
/// let response = manager.request(&mut connection, Call::new("GET", "/v3/user/profile")).await?;
/// # Ok(()) }
/// ```
pub struct AsyncConnectorManager {
    base: BaseConnectorManager,
    transport: Box<dyn Transport>,
}

impl Deref for AsyncConnectorManager {
    type Target = BaseConnectorManager;
    fn deref(&self) -> &Self::Target {
        &self.base
    }
}

impl AsyncConnectorManager {
    pub fn new() -> Result<Self> {
        Self::with_options(HttpOptions::default())
    }

    pub fn with_options(options: HttpOptions) -> Result<Self> {
        Ok(Self { base: BaseConnectorManager::new()?, transport: Box::new(AsyncTransport::new(&options)?) })
    }

    pub fn with_transport(base: BaseConnectorManager, transport: Box<dyn Transport>) -> Self {
        Self { base, transport }
    }

    pub fn base_mut(&mut self) -> &mut BaseConnectorManager {
        &mut self.base
    }

    pub async fn connect(&self, connector_id: &str, options: ConnectOptions) -> Result<Connection> {
        self.base.connect_with(&*self.transport, connector_id, options).await
    }

    pub async fn import_connection(&self, connector_id: &str, options: ConnectOptions) -> Result<Connection> {
        self.connect(connector_id, options).await
    }

    pub async fn verify(&self, connection: &Connection) -> Result<VerificationResult> {
        self.base.verify_with(&*self.transport, connection).await
    }

    pub async fn refresh(&self, connection: &mut Connection) -> Result<()> {
        self.base.refresh_with(&*self.transport, connection).await
    }

    pub async fn ensure_fresh(&self, connection: &mut Connection, buffer_seconds: i64) -> Result<()> {
        self.base.ensure_fresh_with(&*self.transport, connection, buffer_seconds).await
    }

    pub async fn request(&self, connection: &mut Connection, call: Call) -> Result<HttpResponse> {
        self.base.request_with(&*self.transport, connection, call, true).await
    }

    pub async fn send(&self, request: Request) -> Result<HttpResponse> {
        self.transport.send(request).await
    }

    pub async fn discover_scopes(&self, connection: &Connection) -> Result<ScopeDiscovery> {
        self.base.discover_scopes_with(&*self.transport, connection).await
    }

    pub async fn check_tools_live(&self, connection: &Connection) -> Result<ToolReport> {
        self.base.check_tools_live_with(&*self.transport, connection).await
    }

    pub async fn call_tool(&self, connection: &mut Connection, name: &str, arguments: Value) -> Result<ToolResult> {
        self.base.call_tool_with(&*self.transport, connection, name, arguments, true, true).await
    }

    pub async fn call_tool_with_options(
        &self,
        connection: &mut Connection,
        name: &str,
        arguments: Value,
        enforce_scopes: bool,
        auto_refresh: bool,
    ) -> Result<ToolResult> {
        self.base.call_tool_with(&*self.transport, connection, name, arguments, enforce_scopes, auto_refresh).await
    }
}
