//! Build authenticated requests from a provider definition and a [`Connection`].
//!
//! [`RequestBuilder`] resolves a connector's `proxy.base_url`, `proxy.headers`,
//! `proxy.query` and `proxy.body` templates against a connection, applies the
//! auth mode's authorization, and signs the request when the connector declares
//! `proxy.aws_sigv4` or `proxy.acs3`. It performs no I/O.

use std::collections::BTreeMap;
use std::sync::Arc;

use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use chrono::Utc;
use hmac::{Hmac, KeyInit, Mac};
use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, utf8_percent_encode};
use serde_json::{Map, Value};

use crate::error::{Error, Result};
use crate::http::Request;
use crate::interpolation::{has_placeholder, interpolate, interpolate_deep, is_unresolved, merged, stable_replacers};
use crate::models::{AuthMode, Connection};
use crate::signing::{SignInput, canonical_query, sign_acs3, sign_aws_sigv4};

/// Headers a caller may not silently lose when provider headers are merged in.
const CALLER_PRESERVED: &[&str] = &["user-agent"];
const OAUTH_SAFE: &AsciiSet = &NON_ALPHANUMERIC.remove(b'-').remove(b'.').remove(b'_').remove(b'~');

/// One call to build: what the caller wants, before auth and templates are applied.
#[derive(Debug, Clone, Default)]
pub struct Call {
    pub method: String,
    /// A path under the connector's base url, or an absolute url.
    pub endpoint: String,
    pub headers: BTreeMap<String, String>,
    pub params: BTreeMap<String, String>,
    /// JSON body.
    pub json_body: Option<Value>,
    /// Raw body (form text, XML...). Wins over `json_body` on the wire.
    pub content: Option<Vec<u8>>,
    /// The payload signing header templates see (`${bodyCanonicalParams}`), when it is not `json_body`.
    pub payload: Option<Value>,
}

impl Call {
    pub fn new(method: &str, endpoint: impl Into<String>) -> Self {
        Self { method: method.to_uppercase(), endpoint: endpoint.into(), ..Default::default() }
    }
    pub fn header(mut self, k: &str, v: impl Into<String>) -> Self {
        self.headers.insert(k.to_string(), v.into());
        self
    }
    pub fn param(mut self, k: &str, v: impl Into<String>) -> Self {
        self.params.insert(k.to_string(), v.into());
        self
    }
    pub fn json(mut self, body: Value) -> Self {
        self.json_body = Some(body);
        self
    }
    pub fn content(mut self, body: impl Into<Vec<u8>>) -> Self {
        self.content = Some(body.into());
        self
    }
}

/// Turns a [`Call`] into a fully authenticated [`Request`].
#[derive(Debug, Clone)]
pub struct RequestBuilder {
    pub provider: Arc<Map<String, Value>>,
    pub connection: Connection,
}

fn proxy_of(provider: &Map<String, Value>) -> Map<String, Value> {
    provider.get("proxy").and_then(Value::as_object).cloned().unwrap_or_default()
}

impl RequestBuilder {
    pub fn new(provider: Arc<Map<String, Value>>, connection: Connection) -> Self {
        Self { provider, connection }
    }

    /// The same builder with `proxy.base_url` replaced.
    pub fn with_base_url(&self, base_url: &str) -> Self {
        let mut provider = (*self.provider).clone();
        let mut proxy = proxy_of(&provider);
        proxy.insert("base_url".into(), Value::String(base_url.into()));
        provider.insert("proxy".into(), Value::Object(proxy));
        Self { provider: Arc::new(provider), connection: self.connection.clone() }
    }

    pub fn build(&self, call: Call) -> Result<Request> {
        let method = call.method.to_uppercase();
        let url = self.url(&call.endpoint)?;
        let json_body = self.body(call.json_body);
        let payload = call.payload.clone().or_else(|| json_body.clone());
        let request = Request {
            headers: self.headers(&method, &url, &call.headers, payload.as_ref())?,
            params: self.params(&call.params),
            method,
            url,
            content: call.content,
            json_body,
        };
        self.sign(request)
    }

    /// Caller body plus any `proxy.body` template (credentials carried in the JSON body).
    pub fn body(&self, json_body: Option<Value>) -> Option<Value> {
        let template = proxy_of(&self.provider).get("body").cloned();
        match (template, json_body) {
            (Some(Value::Object(t)), Some(Value::Object(body))) => {
                let resolved =
                    drop_unresolved(&interpolate_deep(&Value::Object(t), &self.namespace())).unwrap_or(Value::Object(Map::new()));
                Some(merge(&resolved, &body))
            }
            (_, body) => body,
        }
    }

    pub fn base_url(&self) -> Result<String> {
        let proxy = proxy_of(&self.provider);
        let template = self
            .connection
            .connection_config
            .get("base_url")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| proxy.get("base_url").and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string))
            .ok_or_else(|| {
                Error::request(format!("Connector '{}' has no proxy.base_url; pass an absolute endpoint.", self.connection.connector_id))
                    .with("connector_id", self.connection.connector_id.clone())
            })?;
        let resolved = interpolate(&template, &self.namespace());
        if is_unresolved(&resolved) {
            return Err(Error::request(format!("Could not resolve base_url template '{template}'"))
                .with("template", template)
                .with("resolved", resolved));
        }
        Ok(resolved.trim_end_matches('/').to_string())
    }

    /// Join an endpoint onto the base url, resolving templates.
    pub fn url(&self, endpoint: &str) -> Result<String> {
        if endpoint.starts_with("http://") || endpoint.starts_with("https://") {
            let resolved = interpolate(endpoint, &self.namespace());
            if is_unresolved(&resolved) {
                return Err(Error::request(format!("Could not resolve endpoint template '{endpoint}'")));
            }
            return Ok(resolved);
        }
        let base = self.base_url()?;
        let mut tail = interpolate(endpoint, &self.namespace()).trim_start_matches('/').to_string();
        let host_and_path = base.split_once("://").map_or(base.as_str(), |(_, rest)| rest);
        if !tail.is_empty() && tail.starts_with(host_and_path) {
            tail = tail[host_and_path.len()..].trim_start_matches('/').to_string();
        }
        Ok(if tail.is_empty() { base } else { format!("{base}/{tail}") })
    }

    /// Caller params plus any `proxy.query` template (credentials in the query string).
    pub fn params(&self, params: &BTreeMap<String, String>) -> BTreeMap<String, String> {
        let mut out = params.clone();
        let ns = self.namespace();
        for (key, value) in proxy_of(&self.provider).get("query").and_then(Value::as_object).into_iter().flatten() {
            if let Some(v) = value.as_str() {
                let resolved = interpolate(v, &ns);
                if !is_unresolved(&resolved) {
                    out.insert(key.clone(), resolved);
                }
            }
        }
        out
    }

    /// Authorization for the auth mode, merged with the provider's header templates.
    pub fn headers(
        &self,
        method: &str,
        url: &str,
        extra: &BTreeMap<String, String>,
        body: Option<&Value>,
    ) -> Result<BTreeMap<String, String>> {
        let mut headers = self.authorization(method, url)?;
        headers.extend(self.provider_headers(method, url, extra, body));
        for (key, value) in extra {
            let lowered = key.to_lowercase();
            if CALLER_PRESERVED.contains(&lowered.as_str()) && headers.contains_key(&lowered) {
                continue;
            }
            headers.insert(lowered, value.clone());
        }
        Ok(headers)
    }

    /// The interpolation namespace provider templates see.
    pub fn namespace(&self) -> Map<String, Value> {
        let creds = &self.connection.credentials;
        let config = &self.connection.connection_config;
        let integration = &self.connection.integration_config;
        let text = |m: &Map<String, Value>, k: &str| m.get(k).and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string);
        let mut ns = merged([config, creds]);
        ns.insert("connectionConfig".into(), Value::Object(config.clone()));
        ns.insert("connection_config".into(), Value::Object(config.clone()));
        ns.insert("integrationConfig".into(), Value::Object(integration.clone()));
        ns.insert("credentials".into(), Value::Object(creds.clone()));
        ns.insert("accessToken".into(), Value::String(text(creds, "access_token").or_else(|| text(creds, "token")).unwrap_or_default()));
        ns.insert(
            "clientId".into(),
            Value::String(text(creds, "client_id").or_else(|| text(integration, "client_id")).unwrap_or_default()),
        );
        ns.insert(
            "clientSecret".into(),
            Value::String(text(creds, "client_secret").or_else(|| text(integration, "client_secret")).unwrap_or_default()),
        );
        for (k, v) in integration {
            ns.insert(k.clone(), v.clone());
        }
        ns
    }

    fn cred(&self, key: &str) -> String {
        match self.connection.credentials.get(key) {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Null) | None => String::new(),
            Some(other) => other.to_string(),
        }
    }

    fn authorization(&self, method: &str, url: &str) -> Result<BTreeMap<String, String>> {
        let mode = match self.connection.credentials.get("type").and_then(Value::as_str) {
            Some(t) if !t.is_empty() => AuthMode::parse(Some(t)),
            _ => self.connection.auth_mode,
        };
        let proxy_headers = proxy_of(&self.provider).get("headers").and_then(Value::as_object).cloned().unwrap_or_default();
        let one = |v: String| BTreeMap::from([("authorization".to_string(), v)]);
        Ok(match mode {
            AuthMode::Basic | AuthMode::InstallPlugin => {
                one(format!("Basic {}", B64.encode(format!("{}:{}", self.cred("username"), self.cred("password")))))
            }
            AuthMode::Oauth2 | AuthMode::App | AuthMode::McpOauth2 | AuthMode::McpOauth2Generic => {
                one(format!("Bearer {}", self.cred("access_token")))
            }
            AuthMode::Oauth2Cc | AuthMode::Signature | AuthMode::Jwt => one(format!("Bearer {}", self.cred("token"))),
            AuthMode::TwoStep => {
                // Some TWO_STEP providers authenticate through a custom header or cookie instead.
                let custom = proxy_headers.iter().any(|(k, v)| {
                    v.as_str().is_some_and(|v| {
                        (k.eq_ignore_ascii_case("cookie") && v.contains("${credentials._cookies}")) || v.contains("${accessToken}")
                    })
                });
                if custom { BTreeMap::new() } else { one(format!("Bearer {}", self.cred("token"))) }
            }
            AuthMode::Tba => one(self.tba_authorization(method, url)),
            AuthMode::Oauth1 => one(self.oauth1_authorization(method, url)?),
            _ => BTreeMap::new(),
        })
    }

    fn provider_headers(
        &self,
        method: &str,
        url: &str,
        extra: &BTreeMap<String, String>,
        body: Option<&Value>,
    ) -> BTreeMap<String, String> {
        let templates = proxy_of(&self.provider).get("headers").and_then(Value::as_object).cloned().unwrap_or_default();
        if templates.is_empty() {
            return BTreeMap::new();
        }
        let strings: Vec<&str> = templates.values().filter_map(Value::as_str).collect();
        let parsed = url::Url::parse(url).ok();
        let host = parsed.as_ref().map(|u| match u.port() {
            Some(p) => format!("{}:{p}", u.host_str().unwrap_or("")),
            None => u.host_str().unwrap_or("").to_string(),
        });
        let path = parsed.as_ref().map(|u| u.path().to_string()).unwrap_or_default();
        let query = parsed.as_ref().and_then(|u| u.query().map(str::to_string)).unwrap_or_default();
        let content_type = extra.iter().find(|(k, _)| k.eq_ignore_ascii_case("content-type")).map(|(_, v)| v.clone()).unwrap_or_default();

        let mut ns = self.namespace();
        ns.extend(stable_replacers(strings.iter().copied()));
        for (k, v) in [
            ("method", method.to_string()),
            ("host", host.unwrap_or_default()),
            ("path", path.clone()),
            ("params", query.clone()),
            ("urlCanonicalParams", query),
            ("bodyCanonicalParams", raw_body(method, body)),
            ("contentType", content_type),
            ("endpoint", path.trim_start_matches('/').to_string()),
        ] {
            ns.insert(k.into(), Value::String(v));
        }
        let mut out = BTreeMap::new();
        for (key, value) in &templates {
            let Some(v) = value.as_str() else { continue };
            let resolved = interpolate(v, &ns);
            if has_placeholder(v) && is_unresolved(&resolved) {
                // Leave the header off entirely rather than send a broken template.
                continue;
            }
            out.insert(key.to_lowercase(), resolved);
        }
        out
    }

    fn tba_authorization(&self, method: &str, url: &str) -> String {
        let config = &self.connection.connection_config;
        let first = |a: String, key: &str| if a.is_empty() { config.get(key).and_then(Value::as_str).unwrap_or("").to_string() } else { a };
        let header = oauth1_header(
            method,
            url,
            &first(self.cred("client_id"), "oauth_client_id"),
            &first(self.cred("client_secret"), "oauth_client_secret"),
            &self.cred("token_id"),
            &self.cred("token_secret"),
            "HMAC-SHA256",
        );
        let realm = config.get("accountId").map(|v| v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string())).unwrap_or_default();
        let realm = realm.replace('-', "_").to_uppercase();
        if realm.is_empty() { header } else { header.replacen("OAuth ", &format!("OAuth realm=\"{realm}\", "), 1) }
    }

    fn oauth1_authorization(&self, method: &str, url: &str) -> Result<String> {
        let integration = &self.connection.integration_config;
        let pick = |key: &str| {
            integration.get(key).and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string).unwrap_or_else(|| self.cred(key))
        };
        let (key, secret) = (pick("client_id"), pick("client_secret"));
        if key.is_empty() || secret.is_empty() {
            return Err(Error::request("OAuth1 requests need client_id/client_secret in the connection's integration_config"));
        }
        let method_name = self.provider.get("signature_method").and_then(Value::as_str).unwrap_or("HMAC-SHA1");
        Ok(oauth1_header(method, url, &key, &secret, &self.cred("oauth_token"), &self.cred("oauth_token_secret"), method_name))
    }

    /// Apply a `proxy.aws_sigv4` or `proxy.acs3` signature, if the connector declares one.
    ///
    /// A signed request carries its query string inside the url and its body as
    /// raw content, so what is sent is exactly what was hashed.
    fn sign(&self, request: Request) -> Result<Request> {
        let proxy = proxy_of(&self.provider);
        let sigv4 = proxy.get("aws_sigv4").and_then(Value::as_object).cloned();
        let acs3 = proxy.get("acs3").and_then(Value::as_object).cloned();
        if sigv4.is_none() && acs3.is_none() {
            return Ok(request);
        }
        let id = &self.connection.connector_id;
        let access_key = Some(self.cred("username")).filter(|s| !s.is_empty()).unwrap_or_else(|| self.cred("accessKeyId"));
        let secret_key = Some(self.cred("password")).filter(|s| !s.is_empty()).unwrap_or_else(|| self.cred("secretAccessKey"));
        if access_key.is_empty() || secret_key.is_empty() {
            return Err(Error::request(format!(
                "Connector '{id}' signs requests and needs an access key id (username) and secret (password)."
            ))
            .with("connector_id", id.clone()));
        }
        let session_token = self.cred("sessionToken");
        let ns = self.namespace();
        let body = request.body_bytes().unwrap_or_default();
        let mut headers = request.headers.clone();
        if request.json_body.is_some() && request.content.is_none() {
            headers.entry("content-type".into()).or_insert_with(|| "application/json".into());
        }
        let input = |headers| SignInput {
            method: &request.method,
            url: &request.url,
            headers,
            params: &request.params,
            body: &body,
            access_key: &access_key,
            secret_key: &secret_key,
            session_token: Some(session_token.as_str()),
            now: Utc::now(),
        };
        let (url, signed) = if let Some(spec) = sigv4 {
            let region = interpolate(spec.get("region").and_then(Value::as_str).unwrap_or("${connectionConfig.region}"), &ns);
            let service = interpolate(spec.get("service").and_then(Value::as_str).unwrap_or(""), &ns);
            if region.is_empty() || service.is_empty() || is_unresolved(&region) || is_unresolved(&service) {
                return Err(Error::request(format!("Connector '{id}' could not resolve the SigV4 region/service."))
                    .with("connector_id", id.clone()));
            }
            sign_aws_sigv4(input(headers), &region, &service)
        } else {
            let spec = acs3.unwrap_or_default();
            for (header, key) in [("x-acs-version", "version"), ("x-acs-action", "action")] {
                if let Some(v) = spec.get(key).and_then(Value::as_str).filter(|s| !s.is_empty()) {
                    headers.entry(header.into()).or_insert_with(|| interpolate(v, &ns));
                }
            }
            sign_acs3(input(headers), &uuid::Uuid::new_v4().simple().to_string())
        };
        let query = canonical_query(
            url::Url::parse(&request.url).ok().and_then(|u| u.query().map(str::to_string)).as_deref().unwrap_or(""),
            &request.params,
        );
        let url = if query.is_empty() { url } else { format!("{url}?{query}") };
        let has_body = !body.is_empty() || request.content.is_some();
        Ok(Request {
            method: request.method,
            url,
            headers: signed,
            params: BTreeMap::new(),
            content: has_body.then_some(body),
            json_body: request.json_body,
        })
    }
}

fn raw_body(method: &str, body: Option<&Value>) -> String {
    if matches!(method, "GET" | "HEAD") {
        return String::new();
    }
    match body {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Object(m)) => {
            let mut pairs: Vec<(String, String)> =
                m.iter().map(|(k, v)| (k.clone(), crate::interpolation::scalar_text(v).unwrap_or_else(|| python_repr(v)))).collect();
            pairs.sort();
            url::form_urlencoded::Serializer::new(String::new()).extend_pairs(pairs).finish()
        }
        Some(other) => python_repr(other),
    }
}

fn python_repr(v: &Value) -> String {
    match v {
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Null => "None".into(),
        other => other.to_string(),
    }
}

/// An OAuth 1.0a `Authorization` header (HMAC-SHA1 or HMAC-SHA256).
pub fn oauth1_header(
    method: &str,
    url: &str,
    consumer_key: &str,
    consumer_secret: &str,
    token: &str,
    token_secret: &str,
    signature_method: &str,
) -> String {
    let q = |s: &str| utf8_percent_encode(s, OAUTH_SAFE).to_string();
    let (base, query) = match url::Url::parse(url) {
        Ok(u) => {
            let host = match u.port() {
                Some(p) => format!("{}:{p}", u.host_str().unwrap_or("")),
                None => u.host_str().unwrap_or("").to_string(),
            };
            (format!("{}://{host}{}", u.scheme(), u.path()), u.query().unwrap_or("").to_string())
        }
        Err(_) => (url.to_string(), String::new()),
    };
    let oauth: Vec<(String, String)> = vec![
        ("oauth_consumer_key".into(), consumer_key.into()),
        ("oauth_nonce".into(), uuid::Uuid::new_v4().simple().to_string()),
        ("oauth_signature_method".into(), signature_method.into()),
        ("oauth_timestamp".into(), Utc::now().timestamp().to_string()),
        ("oauth_token".into(), token.into()),
        ("oauth_version".into(), "1.0".into()),
    ];
    let mut all = oauth.clone();
    for pair in query.split('&').filter(|p| !p.is_empty()) {
        let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
        all.push((k.into(), v.into()));
    }
    all.sort();
    let normalized = all.iter().map(|(k, v)| format!("{}={}", q(k), q(v))).collect::<Vec<_>>().join("&");
    let base_string = format!("{}&{}&{}", method.to_uppercase(), q(&base), q(&normalized));
    let key = format!("{}&{}", q(consumer_secret), q(token_secret));
    let signature = if signature_method.to_uppercase().ends_with("SHA1") {
        let mut mac = Hmac::<sha1::Sha1>::new_from_slice(key.as_bytes()).expect("any key");
        mac.update(base_string.as_bytes());
        B64.encode(mac.finalize().into_bytes())
    } else {
        let mut mac = Hmac::<sha2::Sha256>::new_from_slice(key.as_bytes()).expect("any key");
        mac.update(base_string.as_bytes());
        B64.encode(mac.finalize().into_bytes())
    };
    let mut signed = oauth;
    signed.push(("oauth_signature".into(), signature));
    signed.sort();
    format!("OAuth {}", signed.iter().map(|(k, v)| format!("{}=\"{}\"", q(k), q(v))).collect::<Vec<_>>().join(", "))
}

/// Strip keys whose template the connection could not fill in; empty objects go too.
fn drop_unresolved(node: &Value) -> Option<Value> {
    match node {
        Value::Object(m) => {
            let out: Map<String, Value> = m.iter().filter_map(|(k, v)| drop_unresolved(v).map(|c| (k.clone(), c))).collect();
            (!out.is_empty()).then_some(Value::Object(out))
        }
        Value::Array(a) => {
            let items: Vec<Value> = a.iter().filter_map(drop_unresolved).collect();
            (!items.is_empty()).then_some(Value::Array(items))
        }
        Value::String(s) if is_unresolved(s) => None,
        other => Some(other.clone()),
    }
}

/// `over` wins, but nested objects merge rather than replace.
fn merge(base: &Value, over: &Map<String, Value>) -> Value {
    let mut out = base.as_object().cloned().unwrap_or_default();
    for (k, v) in over {
        match (out.get(k), v) {
            (Some(Value::Object(_)), Value::Object(o)) => {
                let existing = out[k].clone();
                out.insert(k.clone(), merge(&existing, o));
            }
            _ => {
                out.insert(k.clone(), v.clone());
            }
        }
    }
    Value::Object(out)
}
