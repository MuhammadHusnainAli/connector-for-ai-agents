//! Data models for the tool layer: tools, parameters, scope rules, packs and reports.

use std::collections::{BTreeSet, HashMap};
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Value, json};

use crate::error::{Error, ErrorKind, Result};

/// The JSON Schema types a tool parameter may declare.
pub const PARAM_TYPES: [&str; 6] = ["string", "integer", "number", "boolean", "array", "object"];

/// Tool names are snake_case, so they are valid identifiers in every runtime.
pub static TOOL_NAME_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_]*$").unwrap());

/// Whether a connection's credentials may run a tool.
///
/// `Unknown` is deliberately distinct from `Disabled`: an API key whose
/// permissions are never disclosed is not a token known to lack a scope.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ToolAvailability {
    Enabled,
    Disabled,
    Unknown,
}

impl ToolAvailability {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Enabled => "enabled",
            Self::Disabled => "disabled",
            Self::Unknown => "unknown",
        }
    }
}

/// The LLM tool-definition shapes [`Tool::spec`] can emit.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SpecFormat {
    /// `{"name", "description", "input_schema"}` for the Claude API.
    #[default]
    Anthropic,
    /// `{"type": "function", "function": {...}}`.
    OpenAi,
    /// MCP: `inputSchema`, `outputSchema` and read-only/destructive hints.
    Mcp,
}

impl std::str::FromStr for SpecFormat {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "anthropic" => Ok(Self::Anthropic),
            "openai" => Ok(Self::OpenAi),
            "mcp" => Ok(Self::Mcp),
            other => Err(Error::new(ErrorKind::Validation, format!("unknown tool spec format '{other}' (anthropic, openai, mcp)"))),
        }
    }
}

/// One argument a tool accepts, in JSON Schema terms.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ToolParameter {
    pub name: String,
    pub param_type: String,
    pub title: String,
    pub description: String,
    pub required: bool,
    pub default: Option<Value>,
    pub r#enum: Vec<Value>,
    pub example: Option<Value>,
    pub pattern: Option<String>,
    pub format: Option<String>,
    pub minimum: Option<f64>,
    pub maximum: Option<f64>,
    pub min_length: Option<usize>,
    pub max_length: Option<usize>,
    pub items: Option<Value>,
    pub properties: Option<Value>,
    pub secret: bool,
}

fn number(v: f64) -> Value {
    if v.fract() == 0.0 && v.abs() < 1e15 { json!(v as i64) } else { json!(v) }
}

impl ToolParameter {
    pub fn json_schema(&self) -> Value {
        let mut s = Map::new();
        s.insert("type".into(), json!(self.param_type));
        if !self.description.is_empty() {
            s.insert("description".into(), json!(self.description));
        }
        if !self.title.is_empty() {
            s.insert("title".into(), json!(self.title));
        }
        if !self.r#enum.is_empty() {
            s.insert("enum".into(), Value::Array(self.r#enum.clone()));
        }
        if let Some(d) = &self.default {
            s.insert("default".into(), d.clone());
        }
        if let Some(p) = &self.pattern {
            s.insert("pattern".into(), json!(p));
        }
        if let Some(f) = &self.format {
            s.insert("format".into(), json!(f));
        }
        if let Some(m) = self.minimum {
            s.insert("minimum".into(), number(m));
        }
        if let Some(m) = self.maximum {
            s.insert("maximum".into(), number(m));
        }
        if let Some(m) = self.min_length {
            s.insert("minLength".into(), json!(m));
        }
        if let Some(m) = self.max_length {
            s.insert("maxLength".into(), json!(m));
        }
        if let Some(i) = &self.items {
            s.insert("items".into(), i.clone());
        }
        if let Some(p) = &self.properties {
            s.insert("properties".into(), p.clone());
        }
        if let Some(e) = &self.example {
            s.insert("examples".into(), json!([e]));
        }
        Value::Object(s)
    }

    pub fn to_json(&self) -> Value {
        json!({
            "name": self.name, "type": self.param_type, "title": self.title, "description": self.description,
            "required": self.required, "default": self.default, "enum": self.r#enum, "example": self.example,
            "secret": self.secret, "schema": self.json_schema(),
        })
    }

    pub(crate) fn label(&self) -> &str {
        if self.title.is_empty() { &self.name } else { &self.title }
    }
}

/// The HTTP call a tool makes, as templates over its arguments.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolRequest {
    pub method: String,
    pub path: String,
    /// Per-key templates, or one `"${arg}"` naming a whole object of parameters.
    pub query: Value,
    pub headers: Map<String, Value>,
    pub body: Option<Value>,
    /// `json`, or `form` (url-encoded with bracket notation for nested values).
    pub encoding: String,
    /// Raw, already-encoded body.
    pub content: Option<Value>,
    /// Wins over the connector's `proxy.base_url` for this call.
    pub base_url_override: Option<String>,
}

impl Default for ToolRequest {
    fn default() -> Self {
        Self {
            method: "GET".into(),
            path: String::new(),
            query: Value::Object(Map::new()),
            headers: Map::new(),
            body: None,
            encoding: "json".into(),
            content: None,
            base_url_override: None,
        }
    }
}

impl ToolRequest {
    pub fn to_json(&self) -> Value {
        json!({
            "method": self.method, "path": self.path, "query": self.query, "headers": self.headers,
            "body": self.body, "encoding": self.encoding, "content": self.content, "base_url_override": self.base_url_override,
        })
    }
}

/// What a tool gives back, described for the model reading it.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolOutput {
    pub description: String,
    pub output_type: String,
    pub properties: Map<String, Value>,
    pub items: Option<Value>,
    /// Dot path to the useful part of the response, e.g. `value`.
    pub response_path: Option<String>,
}

impl Default for ToolOutput {
    fn default() -> Self {
        Self { description: String::new(), output_type: "object".into(), properties: Map::new(), items: None, response_path: None }
    }
}

impl ToolOutput {
    pub fn json_schema(&self) -> Value {
        let mut s = Map::new();
        s.insert("type".into(), json!(self.output_type));
        if !self.description.is_empty() {
            s.insert("description".into(), json!(self.description));
        }
        if !self.properties.is_empty() {
            s.insert("properties".into(), Value::Object(self.properties.clone()));
        }
        if let Some(i) = &self.items {
            s.insert("items".into(), i.clone());
        }
        Value::Object(s)
    }

    pub fn to_json(&self) -> Value {
        json!({
            "description": self.description, "type": self.output_type, "properties": self.properties,
            "items": self.items, "response_path": self.response_path, "schema": self.json_schema(),
        })
    }
}

/// One callable capability of a connector.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Tool {
    pub connector_id: String,
    pub name: String,
    pub title: String,
    pub description: String,
    pub category: String,
    /// Scopes the caller needs all of.
    pub scopes: Vec<String>,
    /// Scopes the caller needs any one of.
    pub scopes_any: Vec<String>,
    pub read_only: bool,
    /// True when a mistake is not undoable: deletes, sends, payments.
    pub destructive: bool,
    pub request: ToolRequest,
    pub input: Vec<ToolParameter>,
    pub output: ToolOutput,
    pub docs_url: Option<String>,
    pub notes: String,
    /// True when derived from catalogue metadata rather than hand-authored.
    pub generated: bool,
}

impl Tool {
    /// `hubspot.create_contact`: unique across the whole catalogue.
    pub fn qualified_name(&self) -> String {
        format!("{}.{}", self.connector_id, self.name)
    }

    pub fn required_scopes(&self) -> Vec<String> {
        self.scopes.iter().chain(&self.scopes_any).cloned().collect()
    }

    pub fn parameter(&self, name: &str) -> Option<&ToolParameter> {
        self.input.iter().find(|p| p.name == name)
    }

    pub fn required_parameters(&self) -> Vec<&ToolParameter> {
        self.input.iter().filter(|p| p.required).collect()
    }

    /// The tool's arguments as one JSON Schema object.
    pub fn input_schema(&self) -> Value {
        let properties: Map<String, Value> = self.input.iter().map(|p| (p.name.clone(), p.json_schema())).collect();
        let required: Vec<&str> = self.input.iter().filter(|p| p.required).map(|p| p.name.as_str()).collect();
        json!({"type": "object", "properties": properties, "required": required, "additionalProperties": false})
    }

    pub fn output_schema(&self) -> Value {
        self.output.json_schema()
    }

    /// This tool as an LLM tool definition. `prefix` uses the connector-qualified name.
    pub fn spec(&self, format: SpecFormat, prefix: bool) -> Value {
        let name = if prefix { self.qualified_name().replace('.', "_") } else { self.name.clone() };
        let schema = self.input_schema();
        let title = if self.title.is_empty() { self.name.clone() } else { self.title.clone() };
        match format {
            SpecFormat::OpenAi => {
                json!({"type": "function", "function": {"name": name, "description": self.description, "parameters": schema}})
            }
            SpecFormat::Mcp => json!({
                "name": name, "title": title, "description": self.description, "inputSchema": schema,
                "outputSchema": self.output_schema(),
                "annotations": {"title": title, "readOnlyHint": self.read_only, "destructiveHint": self.destructive},
            }),
            SpecFormat::Anthropic => json!({"name": name, "description": self.description, "input_schema": schema}),
        }
    }

    pub fn to_json(&self) -> Value {
        json!({
            "connector_id": self.connector_id, "name": self.name, "qualified_name": self.qualified_name(),
            "title": self.title, "description": self.description, "category": self.category,
            "scopes": self.scopes, "scopes_any": self.scopes_any, "read_only": self.read_only,
            "destructive": self.destructive, "docs_url": self.docs_url, "notes": self.notes,
            "generated": self.generated, "request": self.request.to_json(),
            "input": self.input.iter().map(ToolParameter::to_json).collect::<Vec<_>>(),
            "input_schema": self.input_schema(), "output": self.output.to_json(),
        })
    }
}

static GROUPED_SCOPE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^([A-Za-z_][A-Za-z0-9_-]*)\((.+)\)$").unwrap());

/// How to compare a provider's scope strings (case, prefixes, implications, groups).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ScopeRules {
    pub case_insensitive: bool,
    /// Prefixes stripped before comparison, e.g. Google's scope URL root.
    pub strip_prefixes: Vec<String>,
    /// `granted -> also counts as`, expanded transitively.
    pub implies: HashMap<String, Vec<String>>,
    /// Treat `verb(a,b)` as each of `verb(a)` and `verb(b)` (Accelo).
    pub expand_groups: bool,
}

impl ScopeRules {
    pub fn normalize(&self, scope: &str) -> String {
        let mut value = scope.trim();
        for prefix in &self.strip_prefixes {
            if let Some(rest) = value.strip_prefix(prefix.as_str()) {
                value = rest;
                break;
            }
        }
        if self.case_insensitive { value.to_lowercase() } else { value.to_string() }
    }

    /// `read(a,b)` as `[read(a), read(b)]`; anything else unchanged.
    pub fn ungroup(&self, scope: &str) -> Vec<String> {
        if !self.expand_groups {
            return vec![scope.to_string()];
        }
        let Some(c) = GROUPED_SCOPE.captures(scope.trim()) else { return vec![scope.to_string()] };
        let parts: Vec<String> = c[2].split(',').map(str::trim).filter(|p| !p.is_empty()).map(|p| format!("{}({p})", &c[1])).collect();
        if parts.is_empty() { vec![scope.to_string()] } else { parts }
    }

    /// Every scope the grant implies, normalised, following chains.
    pub fn expand<S: AsRef<str>>(&self, granted: &[S]) -> BTreeSet<String> {
        let implies: HashMap<String, Vec<String>> =
            self.implies.iter().map(|(k, v)| (self.normalize(k), v.iter().map(|s| self.normalize(s)).collect())).collect();
        let mut out = BTreeSet::new();
        let mut queue: Vec<String> = Vec::new();
        for scope in granted {
            if scope.as_ref().trim().is_empty() {
                continue;
            }
            queue.extend(self.ungroup(&self.normalize(scope.as_ref())));
        }
        while let Some(scope) = queue.pop() {
            if out.insert(scope.clone()) {
                if let Some(more) = implies.get(&scope) {
                    queue.extend(more.iter().cloned());
                }
            }
        }
        out
    }

    /// Scopes `tool` needs that the grant does not cover.
    pub fn missing<S: AsRef<str>>(&self, tool: &Tool, granted: &[S]) -> Vec<String> {
        let held = self.expand(granted);
        let mut missing: Vec<String> = tool.scopes.iter().filter(|s| !held.contains(&self.normalize(s))).cloned().collect();
        if !tool.scopes_any.is_empty() && !tool.scopes_any.iter().any(|s| held.contains(&self.normalize(s))) {
            missing.extend(tool.scopes_any.iter().cloned());
        }
        missing
    }

    pub fn to_json(&self) -> Value {
        json!({"case_insensitive": self.case_insensitive, "strip_prefixes": self.strip_prefixes, "implies": self.implies, "expand_groups": self.expand_groups})
    }
}

/// How to ask the provider which scopes a live credential carries.
#[derive(Debug, Clone, PartialEq)]
pub struct ScopeDiscoverySpec {
    pub method: String,
    pub endpoint: String,
    /// Dot path in the response body, or `header:<name>`.
    pub scopes_path: String,
    pub separator: String,
    pub base_url_override: Option<String>,
    pub headers: Map<String, Value>,
    pub query: Map<String, Value>,
    /// Read the grant from this claim of a JWT access token, with no request.
    pub jwt_claim: Option<String>,
}

impl ScopeDiscoverySpec {
    pub fn is_local(&self) -> bool {
        self.jwt_claim.as_ref().is_some_and(|c| !c.is_empty()) && self.endpoint.is_empty()
    }

    pub fn to_json(&self) -> Value {
        json!({"method": self.method, "endpoint": self.endpoint, "scopes_path": self.scopes_path, "separator": self.separator,
               "base_url_override": self.base_url_override, "query": self.query, "jwt_claim": self.jwt_claim})
    }
}

/// Every tool one connector ships, plus how to read its scopes.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ToolPack {
    pub connector_id: String,
    pub display_name: String,
    pub docs_url: Option<String>,
    /// Other connector ids served by this pack (`outlook` -> `microsoft`).
    pub applies_to: Vec<String>,
    pub scope_rules: ScopeRules,
    pub scope_discovery: Option<ScopeDiscoverySpec>,
    /// Tools in authoring order.
    pub tools: Vec<Tool>,
    pub source: String,
    pub generated_from: String,
    pub generated: bool,
}

impl ToolPack {
    pub fn len(&self) -> usize {
        self.tools.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    pub fn connector_ids(&self) -> Vec<String> {
        std::iter::once(self.connector_id.clone()).chain(self.applies_to.iter().cloned()).collect()
    }

    pub fn get(&self, name: &str) -> Option<&Tool> {
        self.tools.iter().find(|t| t.name == name)
    }

    pub fn categories(&self) -> Vec<String> {
        self.tools.iter().filter(|t| !t.category.is_empty()).map(|t| t.category.clone()).collect::<BTreeSet<_>>().into_iter().collect()
    }

    /// Every distinct scope any tool in the pack asks for.
    pub fn scopes(&self) -> Vec<String> {
        self.tools.iter().flat_map(Tool::required_scopes).collect::<BTreeSet<_>>().into_iter().collect()
    }

    pub fn to_json(&self, include_request: bool) -> Value {
        let tools: Vec<Value> = self
            .tools
            .iter()
            .map(|t| {
                let mut v = t.to_json();
                if !include_request {
                    v.as_object_mut().unwrap().remove("request");
                }
                v
            })
            .collect();
        json!({
            "connector_id": self.connector_id, "display_name": self.display_name, "docs_url": self.docs_url,
            "applies_to": self.applies_to, "generated": self.generated, "generated_from": self.generated_from,
            "tool_count": self.tools.len(), "categories": self.categories(), "scopes": self.scopes(),
            "scope_rules": self.scope_rules.to_json(),
            "scope_discovery": self.scope_discovery.as_ref().map(ScopeDiscoverySpec::to_json), "tools": tools,
        })
    }
}

/// One tool's verdict against a connection's permissions.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolStatus {
    pub tool: Tool,
    pub availability: ToolAvailability,
    pub missing_scopes: Vec<String>,
    pub reason: String,
}

impl ToolStatus {
    pub fn name(&self) -> &str {
        &self.tool.name
    }

    pub fn enabled(&self) -> bool {
        self.availability == ToolAvailability::Enabled
    }

    pub fn to_json(&self) -> Value {
        json!({
            "name": self.tool.name, "title": self.tool.title, "description": self.tool.description,
            "category": self.tool.category, "availability": self.availability.as_str(), "enabled": self.enabled(),
            "required_scopes": self.tool.required_scopes(), "missing_scopes": self.missing_scopes, "reason": self.reason,
        })
    }
}

/// Where a connection's granted scopes came from, and what they were.
#[derive(Debug, Clone, PartialEq)]
pub struct ScopeDiscovery {
    /// `None` means "could not be determined", which is not "none granted".
    pub scopes: Option<Vec<String>>,
    pub source: String,
    pub tested: bool,
    pub reason: Option<String>,
}

impl ScopeDiscovery {
    pub fn known(&self) -> bool {
        self.scopes.is_some()
    }

    pub fn to_json(&self) -> Value {
        json!({"scopes": self.scopes, "source": self.source, "tested": self.tested, "known": self.known(), "reason": self.reason})
    }
}

/// Which of a connector's tools a connection may actually call.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolReport {
    pub connector_id: String,
    pub connection_id: String,
    pub granted_scopes: Option<Vec<String>>,
    pub scope_source: String,
    pub statuses: Vec<ToolStatus>,
}

impl ToolReport {
    fn of(&self, a: ToolAvailability) -> Vec<&ToolStatus> {
        self.statuses.iter().filter(|s| s.availability == a).collect()
    }

    pub fn enabled(&self) -> Vec<&ToolStatus> {
        self.of(ToolAvailability::Enabled)
    }

    pub fn disabled(&self) -> Vec<&ToolStatus> {
        self.of(ToolAvailability::Disabled)
    }

    pub fn unknown(&self) -> Vec<&ToolStatus> {
        self.of(ToolAvailability::Unknown)
    }

    pub fn enabled_names(&self) -> Vec<String> {
        self.enabled().iter().map(|s| s.tool.name.clone()).collect()
    }

    pub fn disabled_names(&self) -> Vec<String> {
        self.disabled().iter().map(|s| s.tool.name.clone()).collect()
    }

    pub fn status(&self, name: &str) -> Option<&ToolStatus> {
        self.statuses.iter().find(|s| s.tool.name == name)
    }

    /// Every scope that would unlock at least one more tool.
    pub fn missing_scopes(&self) -> Vec<String> {
        self.disabled().iter().flat_map(|s| s.missing_scopes.iter().cloned()).collect::<BTreeSet<_>>().into_iter().collect()
    }

    /// LLM tool definitions for the tools this connection can call (enabled and unknown).
    pub fn specs(&self, format: SpecFormat, include_disabled: bool) -> Vec<Value> {
        self.statuses
            .iter()
            .filter(|s| include_disabled || s.availability != ToolAvailability::Disabled)
            .map(|s| s.tool.spec(format, false))
            .collect()
    }

    pub fn counts(&self) -> Value {
        json!({"total": self.statuses.len(), "enabled": self.enabled().len(), "disabled": self.disabled().len(), "unknown": self.unknown().len()})
    }

    pub fn summary(&self) -> String {
        format!(
            "{}: {}/{} tools enabled, {} disabled, {} unknown (scopes from {})",
            self.connector_id,
            self.enabled().len(),
            self.statuses.len(),
            self.disabled().len(),
            self.unknown().len(),
            self.scope_source
        )
    }

    pub fn to_json(&self) -> Value {
        json!({
            "connector_id": self.connector_id, "connection_id": self.connection_id, "granted_scopes": self.granted_scopes,
            "scope_source": self.scope_source, "counts": self.counts(), "missing_scopes": self.missing_scopes(),
            "tools": self.statuses.iter().map(ToolStatus::to_json).collect::<Vec<_>>(),
        })
    }
}

/// The outcome of calling a tool.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolResult {
    pub tool: String,
    pub connector_id: String,
    pub ok: bool,
    pub status: Option<u16>,
    pub data: Value,
    pub error: Option<String>,
    pub url: String,
}

impl ToolResult {
    pub fn to_json(&self) -> Value {
        json!({"tool": self.tool, "connector_id": self.connector_id, "ok": self.ok, "status": self.status, "url": self.url, "data": self.data, "error": self.error})
    }
}

/// Split a provider's scope value: a space- or comma-separated string, or a list.
///
/// Separators inside parentheses do not split: Accelo grants
/// `read(companies,contacts)` as one scope.
pub fn parse_scope_string(value: &Value, separator: &str) -> Vec<String> {
    match value {
        Value::Null => Vec::new(),
        Value::Array(a) => a
            .iter()
            .map(|v| v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string()).trim().to_string())
            .filter(|s| !s.is_empty())
            .collect(),
        other => {
            let text = other.as_str().map(str::to_string).unwrap_or_else(|| other.to_string());
            let whitespace = separator.trim().is_empty();
            let mut parts = Vec::new();
            let (mut depth, mut current) = (0usize, String::new());
            let mut chars = text.chars().peekable();
            while let Some(ch) = chars.next() {
                match ch {
                    '(' => {
                        depth += 1;
                        current.push(ch);
                    }
                    ')' => {
                        depth = depth.saturating_sub(1);
                        current.push(ch);
                    }
                    c if depth == 0 && whitespace && (c == ',' || c.is_whitespace()) => {
                        parts.push(std::mem::take(&mut current));
                        while chars.peek().is_some_and(|n| *n == ',' || n.is_whitespace()) {
                            chars.next();
                        }
                    }
                    c if depth == 0 && !whitespace && separator.starts_with(c) && text_has_sep(&mut chars, separator) => {
                        parts.push(std::mem::take(&mut current));
                    }
                    c => current.push(c),
                }
            }
            parts.push(current);
            parts.into_iter().map(|p| p.trim().to_string()).filter(|p| !p.is_empty()).collect()
        }
    }
}

/// Consume the rest of a multi-character separator whose first char was just read.
fn text_has_sep(chars: &mut std::iter::Peekable<std::str::Chars<'_>>, separator: &str) -> bool {
    let rest: Vec<char> = separator.chars().skip(1).collect();
    let mut probe = chars.clone();
    for expected in &rest {
        if probe.next() != Some(*expected) {
            return false;
        }
    }
    for _ in &rest {
        chars.next();
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scope_strings() {
        assert_eq!(parse_scope_string(&json!("a b,c"), " "), vec!["a", "b", "c"]);
        assert_eq!(
            parse_scope_string(&json!("read(companies,contacts),write(staff)"), " "),
            vec!["read(companies,contacts)", "write(staff)"]
        );
        assert_eq!(parse_scope_string(&json!("x|y"), "|"), vec!["x", "y"]);
        assert_eq!(parse_scope_string(&json!(["a", " b "]), " "), vec!["a", "b"]);
    }

    #[test]
    fn scope_rules_imply_and_group() {
        let rules = ScopeRules {
            case_insensitive: true,
            implies: HashMap::from([("Mail.ReadWrite".to_string(), vec!["Mail.Read".to_string()])]),
            ..Default::default()
        };
        let tool = Tool { scopes: vec!["Mail.Read".into()], ..Default::default() };
        assert!(rules.missing(&tool, &["mail.readwrite"]).is_empty());
        let grouped = ScopeRules { expand_groups: true, ..Default::default() };
        assert_eq!(grouped.ungroup("read(a,b)"), vec!["read(a)", "read(b)"]);
    }
}
