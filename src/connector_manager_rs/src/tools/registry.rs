//! Loads tool packs, `data/tools/<auth-mode>/<connector-id>.json`, and generates
//! the baseline tools every connector gets.
//!
//! With `tools/index.json` present, packs are parsed on first use, so opening
//! one connector's tools reads one file. Without it every pack is read up front.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Arc, Mutex};

use serde_json::{Map, Value};

use crate::data::DataSource;
use crate::error::{Error, ErrorKind, Result};
use crate::registry::truthy;

use super::models::*;

/// Name of the tool generated from a connector's verification endpoint.
pub const BASELINE_TOOL: &str = "check_connection";

/// Connection-config fields that hold the API's own address.
pub const ENDPOINT_FIELDS: [&str; 9] =
    ["mcp_server_url", "base_url", "server_url", "api_url", "instance_url", "endpoint", "endpoint_url", "api_domain", "url"];

/// The authenticated escape-hatch tools every connector gets.
pub const RAW_TOOLS: [(&str, &str, &str); 5] = [
    ("get_from_api", "GET", "Read from"),
    ("post_to_api", "POST", "Send data to"),
    ("put_to_api", "PUT", "Replace a resource at"),
    ("patch_api", "PATCH", "Partially update a resource at"),
    ("delete_from_api", "DELETE", "Delete a resource at"),
];

const INDEX: &str = "tools/index.json";

/// Read-only index of every bundled tool pack.
pub struct ToolRegistry {
    source: DataSource,
    /// connector id -> owning pack id, when an index exists.
    by_connector: BTreeMap<String, String>,
    /// owning pack id -> (file, tool count).
    packs: BTreeMap<String, (String, usize)>,
    loaded: Mutex<HashMap<String, Arc<ToolPack>>>,
}

impl std::fmt::Debug for ToolRegistry {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ToolRegistry").field("packs", &self.packs.len()).finish()
    }
}

impl ToolRegistry {
    /// The bundled packs.
    pub fn new() -> Result<Self> {
        Self::from_source(DataSource::default())
    }

    pub fn from_source(source: DataSource) -> Result<Self> {
        let mut registry =
            Self { source: source.clone(), by_connector: BTreeMap::new(), packs: BTreeMap::new(), loaded: Mutex::new(HashMap::new()) };
        if let Some(bytes) = source.read(INDEX) {
            let index: Value = serde_json::from_slice(&bytes)?;
            for (cid, owner) in index.get("by_connector").and_then(Value::as_object).into_iter().flatten() {
                registry.by_connector.insert(cid.clone(), owner.as_str().unwrap_or_default().to_string());
            }
            for (owner, spec) in index.get("packs").and_then(Value::as_object).into_iter().flatten() {
                let file = spec.get("file").and_then(Value::as_str).unwrap_or_default().to_string();
                let tools = spec.get("tools").and_then(Value::as_u64).unwrap_or(0) as usize;
                registry.packs.insert(owner.clone(), (file, tools));
            }
            return Ok(registry);
        }
        // No index: read every pack now.
        let mut loaded = HashMap::new();
        for rel in source.json_files("tools") {
            if rel == INDEX {
                continue;
            }
            let bytes = source.read(&rel).ok_or_else(|| Error::data(format!("cannot read {rel}")))?;
            let pack = Arc::new(load_pack(&bytes, &rel)?);
            if registry.packs.contains_key(&pack.connector_id) {
                return Err(Error::data(format!("duplicate tool pack for '{}' in {rel}", pack.connector_id)));
            }
            for cid in pack.connector_ids() {
                if let Some(owner) = registry.by_connector.get(&cid) {
                    return Err(Error::data(format!("connector '{cid}' is claimed by both {owner} and {}", pack.connector_id)));
                }
                registry.by_connector.insert(cid, pack.connector_id.clone());
            }
            let file = rel.trim_start_matches("tools/").to_string();
            registry.packs.insert(pack.connector_id.clone(), (file, pack.len()));
            loaded.insert(pack.connector_id.clone(), pack);
        }
        registry.loaded = Mutex::new(loaded);
        Ok(registry)
    }

    /// How many packs are bundled (not how many tools).
    pub fn len(&self) -> usize {
        self.packs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.packs.is_empty()
    }

    pub fn has(&self, connector_id: &str) -> bool {
        self.by_connector.contains_key(connector_id)
    }

    /// Every connector id that resolves to a pack, aliases included.
    pub fn connector_ids(&self) -> Vec<String> {
        self.by_connector.keys().cloned().collect()
    }

    /// The pack serving `connector_id`, parsed on first use; `None` when none is bundled.
    pub fn pack(&self, connector_id: &str) -> Result<Option<Arc<ToolPack>>> {
        let Some(owner) = self.by_connector.get(connector_id) else { return Ok(None) };
        if let Some(pack) = self.loaded.lock().unwrap().get(owner) {
            return Ok(Some(pack.clone()));
        }
        let (file, _) = self.packs.get(owner).ok_or_else(|| Error::data(format!("index names no file for '{owner}'")))?;
        let rel = format!("tools/{file}");
        let bytes = self.source.read(&rel).ok_or_else(|| Error::data(format!("cannot read {rel}")))?;
        let pack = Arc::new(load_pack(&bytes, &rel)?);
        self.loaded.lock().unwrap().insert(owner.clone(), pack.clone());
        Ok(Some(pack))
    }

    pub fn get_pack(&self, connector_id: &str) -> Result<Arc<ToolPack>> {
        self.pack(connector_id)?.ok_or_else(|| {
            Error::new(ErrorKind::UnknownTool, format!("No tools are bundled for connector '{connector_id}'"))
                .with("connector_id", connector_id)
        })
    }

    /// Every pack, parsing all of them.
    pub fn packs(&self) -> Result<Vec<Arc<ToolPack>>> {
        self.packs.keys().map(|owner| self.get_pack(owner)).collect()
    }

    pub fn tool(&self, connector_id: &str, name: &str) -> Result<Tool> {
        let pack = self.get_pack(connector_id)?;
        pack.get(name).cloned().ok_or_else(|| {
            Error::new(ErrorKind::UnknownTool, format!("Connector '{connector_id}' has no tool '{name}'"))
                .with("connector_id", connector_id)
                .with("tool", name)
                .with("available", pack.tools.iter().map(|t| t.name.clone()).collect::<Vec<_>>())
        })
    }

    pub fn total_tools(&self) -> usize {
        self.packs.values().map(|(_, n)| n).sum()
    }

    /// Tools whose name, title, description or category mentions `query`.
    pub fn search(&self, query: &str, connector_id: Option<&str>) -> Result<Vec<Tool>> {
        let needle = query.trim().to_lowercase();
        let packs = match connector_id {
            Some(id) => vec![self.get_pack(id)?],
            None => self.packs()?,
        };
        let mut out: Vec<Tool> = packs
            .iter()
            .flat_map(|p| p.tools.iter())
            .filter(|t| {
                needle.is_empty() || format!("{} {} {} {}", t.name, t.title, t.description, t.category).to_lowercase().contains(&needle)
            })
            .cloned()
            .collect();
        out.sort_by(|a, b| (&a.connector_id, &a.name).cmp(&(&b.connector_id, &b.name)));
        Ok(out)
    }

    /// Counts a README or a `stats` command can print.
    pub fn stats(&self) -> Value {
        let mut by: Vec<(&String, usize)> = self.packs.iter().map(|(k, (_, n))| (k, *n)).collect();
        by.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(b.0)));
        let by_connector: Map<String, Value> = by.into_iter().map(|(k, n)| (k.clone(), Value::from(n))).collect();
        serde_json::json!({
            "packs": self.packs.len(), "connectors_covered": self.by_connector.len(),
            "tools": self.total_tools(), "by_connector": by_connector,
        })
    }
}

// -- JSON -> models -------------------------------------------------------------

fn text(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    }
}

fn opt_text(v: Option<&Value>) -> Option<String> {
    Some(text(v)).filter(|s| !s.is_empty())
}

fn strings(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array).map(|a| a.iter().map(|x| text(Some(x))).collect()).unwrap_or_default()
}

/// `send_email` -> `Send email`.
fn titleize(name: &str) -> String {
    let base = name.replace(['_', '-'], " ").trim().to_lowercase();
    let mut cs = base.chars();
    cs.next().map(|f| f.to_uppercase().collect::<String>() + cs.as_str()).unwrap_or_default()
}

/// Parse one `<connector-id>.json` tool pack.
pub fn load_pack(bytes: &[u8], source: &str) -> Result<ToolPack> {
    let data: Value = serde_json::from_slice(bytes).map_err(|e| Error::data(format!("{source}: {e}")))?;
    let data = data.as_object().ok_or_else(|| Error::data(format!("{source}: expected an object at the top level")))?;
    let stem = source.rsplit('/').next().unwrap_or(source).trim_end_matches(".json");
    let connector_id = opt_text(data.get("connector_id")).unwrap_or_else(|| stem.to_string());
    let docs_url = opt_text(data.get("docs_url"));
    Ok(ToolPack {
        display_name: text(data.get("display_name")),
        applies_to: strings(data.get("applies_to")),
        scope_rules: scope_rules(data.get("scope_rules")),
        scope_discovery: scope_discovery(data.get("scope_discovery")),
        tools: tools(&connector_id, data.get("tools"), docs_url.as_deref()),
        source: source.to_string(),
        generated: truthy(data.get("generated")),
        generated_from: text(data.get("generated_from")),
        docs_url,
        connector_id,
    })
}

fn scope_rules(spec: Option<&Value>) -> ScopeRules {
    let Some(Value::Object(s)) = spec else { return ScopeRules::default() };
    ScopeRules {
        case_insensitive: truthy(s.get("case_insensitive")),
        strip_prefixes: strings(s.get("strip_prefixes")),
        implies: s.get("implies").and_then(Value::as_object).into_iter().flatten().map(|(k, v)| (k.clone(), strings(Some(v)))).collect(),
        expand_groups: truthy(s.get("expand_groups")),
    }
}

fn scope_discovery(spec: Option<&Value>) -> Option<ScopeDiscoverySpec> {
    let Some(Value::Object(s)) = spec else { return None };
    if s.is_empty() {
        return None;
    }
    let string_map = |v: Option<&Value>| -> Map<String, Value> {
        v.and_then(Value::as_object).into_iter().flatten().map(|(k, v)| (k.clone(), Value::String(text(Some(v))))).collect()
    };
    Some(ScopeDiscoverySpec {
        method: opt_text(s.get("method")).unwrap_or_else(|| "GET".into()).to_uppercase(),
        endpoint: text(s.get("endpoint")),
        scopes_path: opt_text(s.get("scopes_path")).unwrap_or_else(|| "scope".into()),
        separator: opt_text(s.get("separator")).unwrap_or_else(|| " ".into()),
        base_url_override: opt_text(s.get("base_url_override")),
        headers: string_map(s.get("headers")),
        query: string_map(s.get("query")),
        jwt_claim: opt_text(s.get("jwt_claim")),
    })
}

fn tools(connector_id: &str, spec: Option<&Value>, pack_docs: Option<&str>) -> Vec<Tool> {
    let Some(Value::Object(spec)) = spec else { return Vec::new() };
    spec.iter()
        .map(|(name, raw)| {
            let empty = Map::new();
            let raw = raw.as_object().unwrap_or(&empty);
            Tool {
                connector_id: connector_id.to_string(),
                name: name.clone(),
                title: opt_text(raw.get("title")).unwrap_or_else(|| titleize(name)),
                description: text(raw.get("description")).trim().to_string(),
                category: text(raw.get("category")),
                scopes: strings(raw.get("scopes")),
                scopes_any: strings(raw.get("scopes_any")),
                read_only: truthy(raw.get("read_only")),
                destructive: truthy(raw.get("destructive")),
                request: request(raw.get("request")),
                input: parameters(raw.get("input")),
                output: output(raw.get("output")),
                docs_url: opt_text(raw.get("docs_url")).or_else(|| pack_docs.map(str::to_string)),
                notes: text(raw.get("notes")).trim().to_string(),
                generated: false,
            }
        })
        .collect()
}

fn request(spec: Option<&Value>) -> ToolRequest {
    let Some(Value::Object(s)) = spec else { return ToolRequest::default() };
    ToolRequest {
        method: opt_text(s.get("method")).unwrap_or_else(|| "GET".into()).to_uppercase(),
        path: text(s.get("path")),
        query: match s.get("query") {
            Some(Value::String(q)) => Value::String(q.clone()),
            Some(Value::Object(q)) => Value::Object(q.clone()),
            _ => Value::Object(Map::new()),
        },
        headers: s
            .get("headers")
            .and_then(Value::as_object)
            .into_iter()
            .flatten()
            .map(|(k, v)| (k.clone(), Value::String(text(Some(v)))))
            .collect(),
        body: s.get("body").filter(|v| !v.is_null()).cloned(),
        encoding: opt_text(s.get("encoding")).unwrap_or_else(|| "json".into()).to_lowercase(),
        content: s.get("content").filter(|v| !v.is_null()).cloned(),
        base_url_override: opt_text(s.get("base_url_override")),
    }
}

fn float(v: Option<&Value>) -> Option<f64> {
    v.and_then(Value::as_f64)
}

fn parameters(spec: Option<&Value>) -> Vec<ToolParameter> {
    let Some(Value::Object(spec)) = spec else { return Vec::new() };
    spec.iter()
        .map(|(name, raw)| {
            let empty = Map::new();
            let raw = raw.as_object().unwrap_or(&empty);
            ToolParameter {
                name: name.clone(),
                param_type: opt_text(raw.get("type")).unwrap_or_else(|| "string".into()),
                title: opt_text(raw.get("title")).unwrap_or_else(|| titleize(name)),
                description: text(raw.get("description")).trim().to_string(),
                // `optional: true` is how the catalogue spells "not required".
                required: !truthy(raw.get("optional")),
                default: raw.get("default").filter(|v| !v.is_null()).cloned(),
                r#enum: raw.get("enum").and_then(Value::as_array).cloned().unwrap_or_default(),
                example: raw.get("example").filter(|v| !v.is_null()).cloned(),
                pattern: opt_text(raw.get("pattern")),
                format: opt_text(raw.get("format")),
                minimum: float(raw.get("minimum")),
                maximum: float(raw.get("maximum")),
                min_length: raw.get("min_length").and_then(Value::as_u64).map(|n| n as usize),
                max_length: raw.get("max_length").and_then(Value::as_u64).map(|n| n as usize),
                items: raw.get("items").filter(|v| !v.is_null()).cloned(),
                properties: raw.get("properties").filter(|v| !v.is_null()).cloned(),
                secret: truthy(raw.get("secret")),
            }
        })
        .collect()
}

fn output(spec: Option<&Value>) -> ToolOutput {
    let Some(Value::Object(s)) = spec else { return ToolOutput::default() };
    ToolOutput {
        description: text(s.get("description")).trim().to_string(),
        output_type: opt_text(s.get("type")).unwrap_or_else(|| "object".into()),
        properties: s.get("properties").and_then(Value::as_object).cloned().unwrap_or_default(),
        items: s.get("items").filter(|v| !v.is_null()).cloned(),
        response_path: opt_text(s.get("response_path")),
    }
}

// -- generated baseline tools ---------------------------------------------------

/// Where to send requests for a connector with no fixed base url, when derivable.
fn configured_base(provider: &Map<String, Value>) -> Option<String> {
    let config = provider.get("connection_config").and_then(Value::as_object);
    if let Some(name) = ENDPOINT_FIELDS.iter().find(|n| config.is_some_and(|c| c.contains_key(**n))) {
        return Some(format!("${{{name}}}"));
    }
    for key in ["authorization_url", "token_url", "registration_url"] {
        if let Some(url) = provider.get(key).and_then(Value::as_str).filter(|u| u.starts_with("https://")) {
            let rest = &url["https://".len()..];
            let host = rest.split('/').next().unwrap_or("");
            if !host.is_empty() {
                return Some(format!("https://{host}"));
            }
        }
    }
    None
}

fn param(name: &str, ptype: &str, title: &str, description: String, required: bool) -> ToolParameter {
    ToolParameter { name: name.into(), param_type: ptype.into(), title: title.into(), description, required, ..Default::default() }
}

fn mcp_tools(connector_id: &str, label: &str, override_url: Option<&str>) -> Vec<Tool> {
    let rpc = |name: &str, title: &str, description: String, body: Value, input: Vec<ToolParameter>, destructive: bool| {
        let mut headers = Map::new();
        headers.insert("Accept".into(), Value::String("application/json, text/event-stream".into()));
        Tool {
            connector_id: connector_id.into(),
            name: name.into(),
            title: title.into(),
            description,
            category: "mcp".into(),
            destructive,
            request: ToolRequest {
                method: "POST".into(),
                path: "/".into(),
                headers,
                body: Some(body),
                base_url_override: override_url.map(str::to_string),
                ..Default::default()
            },
            input,
            output: ToolOutput {
                description: "The server's JSON-RPC response: a `result` object, or an `error` when the call failed.".into(),
                ..Default::default()
            },
            generated: true,
            ..Default::default()
        }
    };
    vec![
        rpc(
            "list_server_tools",
            "List the MCP server's tools",
            format!(
                "Ask {label}'s MCP server which tools it exposes, over the Model Context Protocol's tools/list method. The server decides what it offers, so this is how to discover the real tool surface before calling anything."
            ),
            serde_json::json!({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"cursor": "${cursor}"}}),
            vec![param("cursor", "string", "Cursor", "Paging cursor from a previous tools/list response.".into(), false)],
            false,
        ),
        rpc(
            "call_server_tool",
            "Call a tool on the MCP server",
            format!(
                "Invoke one of {label}'s MCP tools by name, over the Model Context Protocol's tools/call method. Use list_server_tools first: the name and the shape of `arguments` are defined by the server, not by this package."
            ),
            serde_json::json!({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "${name}", "arguments": "${arguments}"}}),
            vec![
                param("name", "string", "Tool name", "Name of the server tool to call, from list_server_tools.".into(), true),
                param(
                    "arguments",
                    "object",
                    "Arguments",
                    "Arguments for that tool, matching the inputSchema the server published.".into(),
                    false,
                ),
            ],
            true,
        ),
    ]
}

fn raw_request_tool(connector_id: &str, label: &str, name: &str, method: &str, verb: &str, absolute: bool) -> Tool {
    let write = !matches!(method, "GET" | "HEAD");
    let mut path = param(
        "path",
        "string",
        if absolute { "URL" } else { "Path" },
        if absolute {
            format!(
                "Full url to call, e.g. \"https://api.example.com/v1/users\". {label} has no base url of its own, so the whole address goes here."
            )
        } else {
            format!(
                "Path to call on {label}'s API, relative to its base url — for example \"/v1/users\" or \"/api/v2/tickets/42\". You need to know the provider's API to use this; nothing here validates the path."
            )
        },
        true,
    );
    path.example = Some(Value::String(if absolute { "https://api.example.com/v1/users".into() } else { "/v1/users".into() }));
    let mut input =
        vec![path, param("query", "object", "Query", "Query-string parameters as a flat object, e.g. {\"limit\": 50}.".into(), false)];
    if write {
        input.push(param("body", "object", "Body", "JSON request body to send.".into(), false));
    }
    Tool {
        connector_id: connector_id.into(),
        name: name.into(),
        title: format!("{verb} the API ({method})"),
        description: format!(
            "{verb} {label}'s API with this connection's credentials applied, at a path you supply. A general-purpose {method} escape hatch for a connector that has no purpose-built tools yet: it makes no claim about which endpoints exist, so the caller must know the provider's API. Prefer a named tool wherever one exists."
        ),
        category: "raw".into(),
        read_only: !write,
        destructive: method == "DELETE",
        request: ToolRequest {
            method: method.into(),
            path: "${path}".into(),
            query: Value::String("${query}".into()),
            body: write.then(|| Value::String("${body}".into())),
            ..Default::default()
        },
        input,
        output: ToolOutput {
            description: format!("Whatever {label}'s API returns for that request, parsed as JSON where possible."),
            ..Default::default()
        },
        generated: true,
        ..Default::default()
    }
}

/// The tools a connector gets with no pack: `check_connection` from its declared
/// verification endpoint, the MCP pair for MCP connectors, and the raw `*_api` tools.
pub fn baseline_pack(connector_id: &str, display_name: &str, provider: &Map<String, Value>) -> Option<ToolPack> {
    let label = if display_name.is_empty() { titleize(connector_id) } else { display_name.to_string() };
    let mut out: Vec<Tool> = Vec::new();
    let proxy = provider.get("proxy").and_then(Value::as_object);
    let spec = proxy.and_then(|p| p.get("verification")).and_then(Value::as_object);

    let endpoints: Vec<String> = match spec.and_then(|s| s.get("endpoints")) {
        Some(Value::String(s)) => vec![s.clone()],
        Some(Value::Array(a)) => a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
        _ => Vec::new(),
    };
    if let (Some(spec), Some(endpoint)) = (spec, endpoints.first()) {
        if provider.get("credentials_verification_script").is_none() {
            let method = opt_text(spec.get("method")).unwrap_or_else(|| "GET".into()).to_uppercase();
            out.push(Tool {
                connector_id: connector_id.into(),
                name: BASELINE_TOOL.into(),
                title: "Check the connection".into(),
                description: format!(
                    "Call {label}'s own verification endpoint ({method} {endpoint}) to confirm the credentials still work, and return whatever it answers. Taken from the connector's catalogue entry, so it is a call this package knows is real for {label}."
                ),
                category: "connection".into(),
                read_only: method == "GET",
                request: ToolRequest {
                    method: method.clone(),
                    path: if endpoint.starts_with('/') { endpoint.clone() } else { format!("/{endpoint}") },
                    headers: spec
                        .get("headers")
                        .and_then(Value::as_object)
                        .into_iter()
                        .flatten()
                        .filter(|(_, v)| !v.is_null())
                        .map(|(k, v)| (k.clone(), Value::String(text(Some(v)))))
                        .collect(),
                    base_url_override: opt_text(spec.get("base_url_override")),
                    ..Default::default()
                },
                output: ToolOutput {
                    description: "Whatever the provider's verification endpoint returns, usually the account behind the credentials.".into(),
                    ..Default::default()
                },
                generated: true,
                ..Default::default()
            });
        }
    }

    let has_base = proxy.and_then(|p| p.get("base_url")).and_then(Value::as_str).is_some_and(|s| !s.is_empty());
    let override_url = if has_base { None } else { configured_base(provider) };
    let absolute = !has_base && override_url.is_none();

    if provider.get("auth_mode").and_then(Value::as_str).is_some_and(|m| m.starts_with("MCP_")) {
        out.extend(mcp_tools(connector_id, &label, override_url.as_deref()));
    }
    for (name, method, verb) in RAW_TOOLS {
        let mut tool = raw_request_tool(connector_id, &label, name, method, verb, absolute);
        tool.request.base_url_override = override_url.clone();
        out.push(tool);
    }
    Some(ToolPack {
        connector_id: connector_id.into(),
        display_name: label,
        tools: out,
        source: "<generated from catalogue metadata>".into(),
        generated: true,
        ..Default::default()
    })
}
