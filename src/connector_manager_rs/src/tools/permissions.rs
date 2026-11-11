//! Which tools a credential may call: read the grant off a connection, or ask
//! the provider, then judge every tool against it.

use std::sync::Arc;

use serde_json::{Map, Value};

use crate::credentials::decode_jwt_payload;
use crate::error::Result;
use crate::http::Transport;
use crate::interpolation::extract_value_by_path;
use crate::models::Connection;
use crate::proxy::{Call, RequestBuilder};

use super::models::{ScopeDiscovery, Tool, ToolAvailability, ToolPack, ToolReport, ToolStatus, parse_scope_string};

/// Keys that carry a granted-scope list, checked in this order.
const SCOPE_KEYS: [&str; 3] = ["granted_scopes", "scopes", "scope"];

/// The scopes recorded on a connection and where they were found, or
/// `(None, "unknown")` when nothing on it says what was granted.
pub fn connection_scopes(connection: &Connection) -> (Option<Vec<String>>, String) {
    for (label, source) in
        [("metadata", &connection.metadata), ("credentials", &connection.credentials), ("connection_config", &connection.connection_config)]
    {
        for key in SCOPE_KEYS {
            if let Some(v) = source.get(key).filter(|v| !v.is_null() && v.as_str() != Some("")) {
                let scopes = parse_scope_string(v, " ");
                if !scopes.is_empty() {
                    return (Some(scopes), format!("{label}.{key}"));
                }
            }
        }
    }
    (None, "unknown".into())
}

/// Judge every tool in `pack` against a grant (or the one recorded on `connection`).
///
/// A tool declaring no scopes is always enabled. One that does is enabled when
/// the grant covers it, disabled with the shortfall named when it does not,
/// and unknown when the grant itself could not be determined.
pub fn build_report(
    pack: &ToolPack,
    connection: Option<&Connection>,
    granted: Option<Vec<String>>,
    scope_source: &str,
    connector_id: Option<&str>,
) -> ToolReport {
    let (granted, source) = match (granted, connection) {
        (Some(g), _) => (Some(g), scope_source.to_string()),
        (None, Some(c)) => connection_scopes(c),
        (None, None) => (None, scope_source.to_string()),
    };
    let statuses = pack.tools.iter().map(|t| status(pack, t, granted.as_deref())).collect();
    ToolReport {
        connector_id: connector_id
            .map(str::to_string)
            .or_else(|| connection.map(|c| c.connector_id.clone()))
            .unwrap_or_else(|| pack.connector_id.clone()),
        connection_id: connection.map(|c| c.connection_id.clone()).unwrap_or_default(),
        granted_scopes: granted,
        scope_source: source,
        statuses,
    }
}

fn status(pack: &ToolPack, tool: &Tool, granted: Option<&[String]>) -> ToolStatus {
    let make = |availability, missing_scopes, reason: String| ToolStatus { tool: tool.clone(), availability, missing_scopes, reason };
    if tool.required_scopes().is_empty() {
        return make(ToolAvailability::Enabled, Vec::new(), "Needs no scope beyond a valid credential.".into());
    }
    let Some(granted) = granted else {
        return make(
            ToolAvailability::Unknown,
            Vec::new(),
            "The granted scopes for this connection are not known. Record them on the connection, or call discover_scopes() to ask the provider.".into(),
        );
    };
    let missing = pack.scope_rules.missing(tool, granted);
    if missing.is_empty() {
        make(ToolAvailability::Enabled, Vec::new(), "All required scopes are granted.".into())
    } else {
        let reason = format!("Credential is missing: {}", missing.join(", "));
        make(ToolAvailability::Disabled, missing, reason)
    }
}

/// Ask the provider which scopes a live credential carries: from the access
/// token's own claims, from a token-info endpoint, or else from the connection.
pub async fn discover_scopes(
    provider: Arc<Map<String, Value>>,
    pack: &ToolPack,
    connection: &Connection,
    transport: &dyn Transport,
) -> Result<ScopeDiscovery> {
    let recorded = || {
        let (scopes, source) = connection_scopes(connection);
        let known = scopes.is_some();
        (scopes, if known { source } else { "unknown".to_string() })
    };
    let Some(spec) = &pack.scope_discovery else {
        let (scopes, source) = connection_scopes(connection);
        let reason = scopes.is_none().then(|| format!("Connector '{}' declares no scope-discovery endpoint.", pack.connector_id));
        return Ok(ScopeDiscovery { scopes, source, tested: false, reason });
    };
    if spec.is_local() {
        return Ok(from_token_claim(connection, spec.jwt_claim.as_deref().unwrap_or("scp"), &spec.separator));
    }
    let mut builder = RequestBuilder::new(provider, connection.clone());
    if let Some(base) = &spec.base_url_override {
        builder = builder.with_base_url(base);
    }
    let mut call = Call::new(&spec.method, spec.endpoint.clone());
    call.headers = spec.headers.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_string())).collect();
    call.params = spec.query.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_string())).collect();
    let response = transport.send(builder.build(call)?).await?;
    if !response.ok() {
        let (scopes, source) = recorded();
        return Ok(ScopeDiscovery { scopes, source, tested: true, reason: Some(format!("Scope discovery returned {}", response.status)) });
    }
    // A few providers answer in a header rather than the body (GitHub).
    let raw = match spec.scopes_path.strip_prefix("header:") {
        Some(name) => response.headers.get(&name.to_lowercase()).map(|h| Value::String(h.clone())).unwrap_or(Value::Null),
        None => response.json().and_then(|body| extract_value_by_path(&body, &spec.scopes_path).cloned()).unwrap_or(Value::Null),
    };
    let scopes = parse_scope_string(&raw, &spec.separator);
    if scopes.is_empty() {
        return Ok(ScopeDiscovery {
            scopes: None,
            source: "unknown".into(),
            tested: true,
            reason: Some(format!("No scopes at '{}' in the provider's response", spec.scopes_path)),
        });
    }
    Ok(ScopeDiscovery { scopes: Some(scopes), source: "provider".into(), tested: true, reason: None })
}

fn from_token_claim(connection: &Connection, claim: &str, separator: &str) -> ScopeDiscovery {
    let Some(token) = connection.access_token() else {
        return ScopeDiscovery {
            scopes: None,
            source: "unknown".into(),
            tested: false,
            reason: Some("Connection carries no access token".into()),
        };
    };
    let Some(payload) = decode_jwt_payload(token) else {
        let (scopes, source) = connection_scopes(connection);
        let source = if scopes.is_some() { source } else { "unknown".into() };
        return ScopeDiscovery { scopes, source, tested: false, reason: Some("Access token is not a readable JWT".into()) };
    };
    // `scp` holds delegated permissions, `roles` application ones; accept either.
    let mut raw = payload.get(claim).cloned().unwrap_or(Value::Null);
    let empty = matches!(&raw, Value::Null) || raw.as_str() == Some("") || raw.as_array().is_some_and(Vec::is_empty);
    if empty && claim == "scp" {
        raw = payload.get("roles").cloned().unwrap_or(Value::Null);
    }
    let scopes = parse_scope_string(&raw, separator);
    if scopes.is_empty() {
        return ScopeDiscovery {
            scopes: None,
            source: "unknown".into(),
            tested: false,
            reason: Some(format!("Access token carries no '{claim}' claim")),
        };
    }
    ScopeDiscovery { scopes: Some(scopes), source: "access_token".into(), tested: false, reason: None }
}
