//! Credential verification: call the connector's own `proxy.verification` endpoint.

use std::sync::Arc;

use serde_json::{Map, Value, json};

use crate::error::{Error, ErrorKind, Result};
use crate::http::Transport;
use crate::interpolation::{interpolate_deep, merged};
use crate::models::Connection;
use crate::proxy::{Call, RequestBuilder};

/// Outcome of the verification call.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct VerificationResult {
    pub verified: bool,
    /// False when no call was made (no endpoint declared, or a script-only check).
    pub tested: bool,
    pub endpoint: Option<String>,
    pub status: Option<u16>,
    pub reason: Option<String>,
    pub response: Option<Value>,
}

impl VerificationResult {
    pub fn to_json(&self) -> Value {
        json!({
            "verified": self.verified,
            "tested": self.tested,
            "endpoint": self.endpoint,
            "status": self.status,
            "reason": self.reason,
        })
    }

    /// `Err(Verification)` unless verified.
    pub fn into_result(self, connector_id: &str) -> Result<Self> {
        if self.verified {
            return Ok(self);
        }
        Err(Error::new(ErrorKind::Verification, self.reason.clone().unwrap_or_else(|| "Credential verification failed".into()))
            .with("connector_id", connector_id)
            .with("endpoint", self.endpoint.clone())
            .with("status", self.status)
            .with("response", self.response.clone().unwrap_or(Value::Null)))
    }
}

/// Try each declared verification endpoint until one answers 2xx.
pub async fn verify(provider: Arc<Map<String, Value>>, connection: &Connection, transport: &dyn Transport) -> Result<VerificationResult> {
    if provider.get("credentials_verification_script").is_some() {
        return Ok(VerificationResult {
            reason: Some("This connector verifies credentials with a provider-specific script, which is not ported.".into()),
            ..Default::default()
        });
    }
    let spec = provider.get("proxy").and_then(|p| p.get("verification")).and_then(Value::as_object).cloned();
    let Some(spec) = spec.filter(|s| !s.is_empty()) else {
        return Ok(VerificationResult { reason: Some("Connector declares no verification endpoint".into()), ..Default::default() });
    };
    let method = spec.get("method").and_then(Value::as_str).unwrap_or("GET").to_uppercase();
    let endpoints: Vec<String> = match spec.get("endpoints") {
        Some(Value::String(s)) => vec![s.clone()],
        Some(Value::Array(a)) if !a.is_empty() => a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
        _ => vec![String::new()],
    };
    let mut builder = RequestBuilder::new(provider.clone(), connection.clone());
    if let Some(base) = spec.get("base_url_override").and_then(Value::as_str) {
        builder = builder.with_base_url(base);
    }
    let headers: std::collections::BTreeMap<String, String> = spec
        .get("headers")
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .filter(|(_, v)| !v.is_null())
        .map(|(k, v)| (k.to_lowercase(), v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string())))
        .collect();
    let payload = spec
        .get("data")
        .filter(|v| !v.is_null())
        .map(|body| interpolate_deep(body, &merged([&connection.connection_config, &connection.credentials])));
    let declared_type = provider
        .get("proxy")
        .and_then(|p| p.get("headers"))
        .and_then(Value::as_object)
        .is_some_and(|h| h.keys().any(|k| k.eq_ignore_ascii_case("content-type")));

    let mut last = None;
    for endpoint in endpoints {
        let mut call = Call::new(&method, endpoint);
        call.headers = headers.clone();
        if let Some(body) = &payload {
            // Hand the body to the builder: a signing connector hashes it while building.
            if !declared_type {
                call.headers.entry("content-type".into()).or_insert_with(|| "application/json".into());
            }
            call.content = Some(serde_json::to_vec(body)?);
            call.payload = Some(body.clone());
        }
        let response = transport.send(builder.build(call)?).await?;
        if response.ok() {
            return Ok(VerificationResult {
                verified: true,
                tested: true,
                endpoint: Some(response.url),
                status: Some(response.status),
                ..Default::default()
            });
        }
        last = Some(VerificationResult {
            verified: false,
            tested: true,
            reason: Some(format!("Verification request returned {}", response.status)),
            response: Some(response.body()),
            endpoint: Some(response.url),
            status: Some(response.status),
        });
    }
    Ok(last.unwrap_or(VerificationResult { tested: true, reason: Some("No endpoint was called".into()), ..Default::default() }))
}
