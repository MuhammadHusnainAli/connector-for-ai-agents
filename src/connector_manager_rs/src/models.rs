//! Data models: auth modes, field schemas, connectors, pages and connections.
//!
//! Everything here serialises to the same JSON shape as the Python package's
//! `to_dict()`, so a [`Connection`] saved by one library loads in the other.

use std::sync::Arc;

use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

/// The auth mechanisms connectors use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AuthMode {
    None,
    ApiKey,
    Basic,
    Oauth1,
    Oauth2,
    #[serde(rename = "OAUTH2_CC")]
    Oauth2Cc,
    TwoStep,
    Jwt,
    Signature,
    Tba,
    App,
    Custom,
    Bill,
    #[serde(rename = "AWS_SIGV4")]
    AwsSigv4,
    InstallPlugin,
    #[serde(rename = "MCP_OAUTH2")]
    McpOauth2,
    #[serde(rename = "MCP_OAUTH2_GENERIC")]
    McpOauth2Generic,
}

impl AuthMode {
    pub const ALL: [AuthMode; 17] = [
        Self::None,
        Self::ApiKey,
        Self::Basic,
        Self::Oauth1,
        Self::Oauth2,
        Self::Oauth2Cc,
        Self::TwoStep,
        Self::Jwt,
        Self::Signature,
        Self::Tba,
        Self::App,
        Self::Custom,
        Self::Bill,
        Self::AwsSigv4,
        Self::InstallPlugin,
        Self::McpOauth2,
        Self::McpOauth2Generic,
    ];

    /// The catalogue spelling, e.g. `"OAUTH2_CC"`.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::None => "NONE",
            Self::ApiKey => "API_KEY",
            Self::Basic => "BASIC",
            Self::Oauth1 => "OAUTH1",
            Self::Oauth2 => "OAUTH2",
            Self::Oauth2Cc => "OAUTH2_CC",
            Self::TwoStep => "TWO_STEP",
            Self::Jwt => "JWT",
            Self::Signature => "SIGNATURE",
            Self::Tba => "TBA",
            Self::App => "APP",
            Self::Custom => "CUSTOM",
            Self::Bill => "BILL",
            Self::AwsSigv4 => "AWS_SIGV4",
            Self::InstallPlugin => "INSTALL_PLUGIN",
            Self::McpOauth2 => "MCP_OAUTH2",
            Self::McpOauth2Generic => "MCP_OAUTH2_GENERIC",
        }
    }

    /// Parse a catalogue spelling; anything unknown or missing is `NONE`.
    pub fn parse(value: Option<&str>) -> Self {
        let value = value.unwrap_or("NONE");
        Self::ALL.into_iter().find(|m| m.as_str() == value).unwrap_or(Self::None)
    }

    /// Modes `connect()` completes end to end, with no browser redirect.
    pub fn is_self_service(self) -> bool {
        matches!(
            self,
            Self::None
                | Self::ApiKey
                | Self::Basic
                | Self::InstallPlugin
                | Self::Oauth2Cc
                | Self::TwoStep
                | Self::Jwt
                | Self::Signature
                | Self::Tba
        )
    }

    /// Modes whose first handshake is a redirect flow run by your own OAuth layer.
    pub fn requires_external_oauth(self) -> bool {
        matches!(self, Self::Oauth1 | Self::Oauth2 | Self::App | Self::Custom | Self::McpOauth2 | Self::McpOauth2Generic)
    }

    /// Modes with no handler at all.
    pub fn is_unsupported(self) -> bool {
        matches!(self, Self::Bill | Self::AwsSigv4)
    }
}

impl std::fmt::Display for AuthMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Where a collected value belongs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldGroup {
    Credentials,
    ConnectionConfig,
    IntegrationConfig,
    AssertionOption,
}

impl FieldGroup {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Credentials => "credentials",
            Self::ConnectionConfig => "connection_config",
            Self::IntegrationConfig => "integration_config",
            Self::AssertionOption => "assertion_option",
        }
    }
}

/// One value the end user (or admin) has to supply.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuthField {
    pub name: String,
    pub group: FieldGroup,
    pub title: String,
    pub description: String,
    #[serde(rename = "type")]
    pub field_type: String,
    pub required: bool,
    pub secret: bool,
    pub example: Option<String>,
    pub pattern: Option<String>,
    pub format: Option<String>,
    pub default_value: Option<String>,
    pub r#enum: Vec<String>,
    pub prefix: Option<String>,
    pub suffix: Option<String>,
    pub order: i64,
    pub automated: bool,
    pub hidden: bool,
    pub visible_when: Option<Map<String, Value>>,
}

impl AuthField {
    pub(crate) fn new(name: &str, group: FieldGroup) -> Self {
        Self {
            name: name.to_string(),
            group,
            title: String::new(),
            description: String::new(),
            field_type: "string".into(),
            required: true,
            secret: false,
            example: None,
            pattern: None,
            format: None,
            default_value: None,
            r#enum: Vec::new(),
            prefix: None,
            suffix: None,
            order: 0,
            automated: false,
            hidden: false,
            visible_when: None,
        }
    }

    pub fn to_json(&self) -> Value {
        serde_json::to_value(self).unwrap_or(Value::Null)
    }
}

/// The full set of inputs needed to connect one connector.
#[derive(Debug, Clone, PartialEq)]
pub struct AuthSchema {
    pub connector_id: String,
    pub display_name: String,
    pub auth_mode: AuthMode,
    pub supported: bool,
    pub self_service: bool,
    pub requires_external_oauth: bool,
    pub credentials: Vec<AuthField>,
    pub connection_config: Vec<AuthField>,
    pub integration_config: Vec<AuthField>,
    pub assertion_option: Vec<AuthField>,
    pub default_scopes: Vec<String>,
    pub authorization_url: Option<String>,
    pub unsupported_reason: Option<String>,
}

fn sorted(fields: &[AuthField]) -> Vec<&AuthField> {
    let mut out: Vec<&AuthField> = fields.iter().collect();
    out.sort_by(|a, b| (a.order, &a.name).cmp(&(b.order, &b.name)));
    out
}

impl AuthSchema {
    /// Every field, in the order a form should render them.
    pub fn fields(&self) -> Vec<&AuthField> {
        let mut out = Vec::new();
        for group in [&self.connection_config, &self.credentials, &self.integration_config, &self.assertion_option] {
            out.extend(sorted(group));
        }
        out
    }

    /// Fields a human should actually be prompted for.
    pub fn user_fields(&self) -> Vec<&AuthField> {
        self.fields().into_iter().filter(|f| !f.automated && !f.hidden).collect()
    }

    pub fn to_json(&self) -> Value {
        let group = |fields: &[AuthField]| Value::Array(sorted(fields).into_iter().map(AuthField::to_json).collect());
        json!({
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "auth_mode": self.auth_mode.as_str(),
            "supported": self.supported,
            "self_service": self.self_service,
            "requires_external_oauth": self.requires_external_oauth,
            "unsupported_reason": self.unsupported_reason,
            "credentials": group(&self.credentials),
            "connection_config": group(&self.connection_config),
            "integration_config": group(&self.integration_config),
            "assertion_option": group(&self.assertion_option),
            "default_scopes": self.default_scopes,
            "authorization_url": self.authorization_url,
        })
    }
}

/// One connector: identity, categories, api base url, and its alias-resolved definition.
#[derive(Debug, Clone)]
pub struct Connector {
    pub id: String,
    pub display_name: String,
    pub auth_mode: AuthMode,
    pub categories: Vec<String>,
    pub base_url: Option<String>,
    pub alias: Option<String>,
    /// The alias-resolved catalogue entry.
    pub raw: Arc<Map<String, Value>>,
}

impl Connector {
    /// True when `connect()` alone yields a working connection.
    pub fn self_service(&self) -> bool {
        self.auth_mode.is_self_service()
    }

    /// True when this crate can produce a connection at all (OAuth modes via import).
    pub fn supported(&self) -> bool {
        !self.auth_mode.is_unsupported()
    }

    pub fn requires_external_oauth(&self) -> bool {
        self.auth_mode.requires_external_oauth()
    }

    pub fn to_json(&self) -> Value {
        json!({
            "id": self.id,
            "display_name": self.display_name,
            "auth_mode": self.auth_mode.as_str(),
            "categories": self.categories,
            "base_url": self.base_url,
            "alias": self.alias,
            "supported": self.supported(),
            "self_service": self.self_service(),
            "requires_external_oauth": self.requires_external_oauth(),
        })
    }
}

/// One page of a connector listing, plus the numbers a UI needs.
#[derive(Debug, Clone)]
pub struct ConnectorPage {
    pub items: Vec<Connector>,
    /// Connectors matching the filters before paging.
    pub total: usize,
    pub limit: usize,
    pub offset: usize,
}

impl ConnectorPage {
    pub fn count(&self) -> usize {
        self.items.len()
    }

    /// 1-based page number implied by `offset` / `limit`.
    pub fn page(&self) -> usize {
        self.offset.checked_div(self.limit).map_or(1, |n| n + 1)
    }

    pub fn pages(&self) -> usize {
        if self.limit == 0 { usize::from(self.total > 0) } else { self.total.div_ceil(self.limit) }
    }

    pub fn has_next(&self) -> bool {
        self.offset + self.count() < self.total
    }

    pub fn has_previous(&self) -> bool {
        self.offset > 0
    }

    pub fn next_offset(&self) -> Option<usize> {
        self.has_next().then(|| self.offset + self.limit)
    }

    pub fn previous_offset(&self) -> Option<usize> {
        self.has_previous().then(|| self.offset.saturating_sub(self.limit))
    }

    /// 1-based index of the first item on this page (0 when empty).
    pub fn first_index(&self) -> usize {
        if self.count() > 0 { self.offset + 1 } else { 0 }
    }

    /// 1-based index of the last item on this page (0 when empty).
    pub fn last_index(&self) -> usize {
        if self.count() > 0 { self.offset + self.count() } else { 0 }
    }

    pub fn pagination(&self) -> Value {
        json!({
            "total": self.total,
            "count": self.count(),
            "limit": self.limit,
            "offset": self.offset,
            "page": self.page(),
            "page_size": self.limit,
            "pages": self.pages(),
            "has_next": self.has_next(),
            "has_previous": self.has_previous(),
            "next_offset": self.next_offset(),
            "previous_offset": self.previous_offset(),
            "first_index": self.first_index(),
            "last_index": self.last_index(),
        })
    }

    pub fn to_json(&self) -> Value {
        json!({
            "items": self.items.iter().map(Connector::to_json).collect::<Vec<_>>(),
            "pagination": self.pagination(),
        })
    }
}

/// The result of a successful connect. Persist it yourself; this crate stores nothing.
///
/// Serialises to the same JSON as the Python `Connection.to_dict()`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Connection {
    #[serde(default)]
    pub connection_id: String,
    pub connector_id: String,
    #[serde(deserialize_with = "auth_mode_lenient", default = "default_mode")]
    pub auth_mode: AuthMode,
    #[serde(default)]
    pub credentials: Map<String, Value>,
    #[serde(default)]
    pub connection_config: Map<String, Value>,
    #[serde(default)]
    pub integration_config: Map<String, Value>,
    #[serde(default)]
    pub metadata: Map<String, Value>,
    #[serde(default)]
    pub verified: bool,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub updated_at: String,
}

fn default_mode() -> AuthMode {
    AuthMode::None
}

fn auth_mode_lenient<'de, D: serde::Deserializer<'de>>(d: D) -> Result<AuthMode, D::Error> {
    let raw = Option::<String>::deserialize(d)?;
    Ok(AuthMode::parse(raw.as_deref()))
}

pub(crate) fn utc_now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}

impl Connection {
    /// A connection with a fresh id and timestamps.
    pub fn new(connector_id: impl Into<String>, auth_mode: AuthMode) -> Self {
        let now = utc_now_iso();
        Self {
            connection_id: uuid::Uuid::new_v4().to_string(),
            connector_id: connector_id.into(),
            auth_mode,
            credentials: Map::new(),
            connection_config: Map::new(),
            integration_config: Map::new(),
            metadata: Map::new(),
            verified: false,
            created_at: now.clone(),
            updated_at: now,
        }
    }

    /// Load a connection saved by either library, filling any missing id or timestamps.
    pub fn from_json(value: Value) -> crate::Result<Self> {
        let mut conn: Connection = serde_json::from_value(value)?;
        let now = utc_now_iso();
        if conn.connection_id.is_empty() {
            conn.connection_id = uuid::Uuid::new_v4().to_string();
        }
        if conn.created_at.is_empty() {
            conn.created_at = now.clone();
        }
        if conn.updated_at.is_empty() {
            conn.updated_at = now;
        }
        Ok(conn)
    }

    pub fn to_json(&self) -> Value {
        serde_json::to_value(self).unwrap_or(Value::Null)
    }

    /// When the access token expires, if the credentials say.
    pub fn expires_at(&self) -> Option<DateTime<Utc>> {
        let raw = self.credentials.get("expires_at")?.as_str()?;
        crate::credentials::parse_iso(raw)
    }

    /// True when the access token is gone or within `buffer_seconds` of expiring.
    pub fn is_expired(&self, buffer_seconds: i64) -> bool {
        match self.expires_at() {
            None => false,
            Some(at) => (at - Utc::now()).num_milliseconds() <= buffer_seconds * 1000,
        }
    }

    /// The bearer-ish token, whatever the auth mode calls it.
    pub fn access_token(&self) -> Option<&str> {
        ["access_token", "token"].into_iter().find_map(|k| self.credentials.get(k).and_then(Value::as_str).filter(|s| !s.is_empty()))
    }

    pub fn touch(&mut self) {
        self.updated_at = utc_now_iso();
    }
}
