//! Auth strategies, one per auth mode.
//!
//! A strategy turns user-supplied inputs into a credentials object and, where
//! the provider supports it, mints a new token from stored credentials. Each is
//! written once, as `async` code over a [`Transport`], and so serves both
//! managers. Register your own with [`Strategies::register`].

use std::collections::HashMap;
use std::sync::Arc;

use base64::Engine;
use base64::engine::general_purpose::{STANDARD as B64, URL_SAFE_NO_PAD};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use crate::credentials::{in_ms, iso, num, parse_raw_credentials};
use crate::error::{Error, ErrorKind, Result};
use crate::http::{BoxFuture, HttpResponse, Request, Transport};
use crate::interpolation::{
    extract_step_number, format_pem, interpolate, interpolate_deep, is_unresolved, make_url, merged, pem_kind, stable_replacers,
    strip_credential, strip_step_response,
};
use crate::models::AuthMode;

/// Everything a strategy needs for one connect or refresh attempt.
#[derive(Debug, Clone)]
pub struct AuthContext {
    pub connector_id: String,
    pub provider: Arc<Map<String, Value>>,
    pub auth_mode: AuthMode,
    pub credentials: Map<String, Value>,
    pub connection_config: Map<String, Value>,
    pub integration_config: Map<String, Value>,
    pub is_refresh: bool,
}

impl AuthContext {
    fn provider_str(&self, key: &str) -> Option<&str> {
        self.provider.get(key).and_then(Value::as_str)
    }
}

/// A handler for one auth mode.
pub trait AuthStrategy: Send + Sync {
    fn auth_mode(&self) -> AuthMode;
    /// True when the mode needs a redirect flow owned by the caller.
    fn external_oauth(&self) -> bool {
        false
    }
    /// True when `refresh` can mint a fresh token without user interaction.
    fn refreshable(&self) -> bool {
        false
    }
    /// Produce the credentials, sending whatever requests the mode needs.
    fn flow<'a>(&'a self, ctx: &'a AuthContext, transport: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>>;
    /// Re-mint credentials. Defaults to running [`AuthStrategy::flow`] again.
    fn refresh_flow<'a>(&'a self, ctx: &'a AuthContext, transport: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        self.flow(ctx, transport)
    }
}

/// The strategy for each auth mode. [`Strategies::default`] holds the built-in ones.
#[derive(Clone)]
pub struct Strategies {
    by_mode: HashMap<AuthMode, Arc<dyn AuthStrategy>>,
}

impl Default for Strategies {
    fn default() -> Self {
        let mut s = Self { by_mode: HashMap::new() };
        for strategy in [
            Arc::new(Static(AuthMode::None)) as Arc<dyn AuthStrategy>,
            Arc::new(Static(AuthMode::ApiKey)),
            Arc::new(Static(AuthMode::Basic)),
            Arc::new(Static(AuthMode::InstallPlugin)),
            Arc::new(Static(AuthMode::Tba)),
            Arc::new(OAuth2ClientCredentials),
            Arc::new(TwoStep),
            Arc::new(Jwt),
            Arc::new(Signature),
            Arc::new(External { mode: AuthMode::Oauth2, token_keys: &["access_token"] }),
            Arc::new(External { mode: AuthMode::Oauth1, token_keys: &["oauth_token"] }),
            Arc::new(External { mode: AuthMode::McpOauth2, token_keys: &["access_token"] }),
            Arc::new(External { mode: AuthMode::McpOauth2Generic, token_keys: &["access_token"] }),
            Arc::new(External { mode: AuthMode::App, token_keys: &["access_token"] }),
            Arc::new(External { mode: AuthMode::Custom, token_keys: &["access_token"] }),
            Arc::new(Unsupported(AuthMode::Bill, "the Bill.com session-token exchange is not implemented yet")),
            Arc::new(Unsupported(AuthMode::AwsSigv4, "AWS SigV4 role assumption is not implemented yet; use a BASIC aws-* connector")),
        ] {
            s.register(strategy);
        }
        s
    }
}

impl Strategies {
    /// Plug in your own handler, or override a built-in one.
    pub fn register(&mut self, strategy: Arc<dyn AuthStrategy>) {
        self.by_mode.insert(strategy.auth_mode(), strategy);
    }

    pub fn get(&self, mode: AuthMode) -> Arc<dyn AuthStrategy> {
        self.by_mode.get(&mode).cloned().unwrap_or_else(|| Arc::new(Unsupported(mode, "no strategy registered for this auth mode")))
    }
}

fn ready<'a, T: Send + 'a>(value: T) -> BoxFuture<'a, T> {
    Box::pin(std::future::ready(value))
}

fn s(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    }
}

fn first(source: &Map<String, Value>, names: &[&str]) -> String {
    names.iter().find_map(|n| source.get(*n).and_then(Value::as_str).filter(|v| !v.is_empty())).unwrap_or("").to_string()
}

fn form(params: &[(String, String)]) -> String {
    url::form_urlencoded::Serializer::new(String::new()).extend_pairs(params).finish()
}

// -- user-supplied credentials (no I/O) ---------------------------------------

/// NONE, API_KEY, BASIC, INSTALL_PLUGIN, TBA: credentials are taken as given and
/// proved by the verification call.
struct Static(AuthMode);

impl AuthStrategy for Static {
    fn auth_mode(&self) -> AuthMode {
        self.0
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, _: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        let mut out = Map::new();
        out.insert("type".into(), json!(self.0.as_str()));
        if self.0 != AuthMode::None {
            out.extend(ctx.credentials.clone());
            out.insert("type".into(), json!(self.0.as_str()));
        }
        if matches!(self.0, AuthMode::Basic | AuthMode::InstallPlugin) {
            out.insert("username".into(), json!(s(ctx.credentials.get("username"))));
            out.insert("password".into(), json!(s(ctx.credentials.get("password"))));
        }
        ready(Ok(out))
    }
}

/// SIGNATURE: a WS-Security UsernameToken computed locally (Emarsys).
struct Signature;

impl AuthStrategy for Signature {
    fn auth_mode(&self) -> AuthMode {
        AuthMode::Signature
    }
    fn refreshable(&self) -> bool {
        true
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, _: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        let protocol = ctx.provider.get("signature").and_then(|v| v.get("protocol")).and_then(Value::as_str);
        if protocol != Some("WSSE") {
            return ready(Err(Error::new(
                ErrorKind::UnsupportedAuthMode,
                format!("Unsupported signature protocol '{}'", protocol.unwrap_or("None")),
            )));
        }
        let username = s(ctx.credentials.get("username"));
        let password = s(ctx.credentials.get("password"));
        let lifetime = ctx.provider.get("token").and_then(|t| t.get("expires_in_ms")).and_then(num).unwrap_or(3_600_000.0);
        let mut out = ctx.credentials.clone();
        out.insert("type".into(), json!("SIGNATURE"));
        out.insert("username".into(), json!(username));
        out.insert("password".into(), json!(password));
        out.insert("token".into(), json!(generate_wsse(&username, &password)));
        out.insert("expires_at".into(), json!(iso(in_ms(lifetime))));
        ready(Ok(out))
    }
}

/// The `X-WSSE` UsernameToken value: digest is `base64(sha256_hex(nonce + created + password))`.
pub fn generate_wsse(username: &str, password: &str) -> String {
    let nonce = uuid::Uuid::new_v4().simple().to_string();
    let created = iso(chrono::Utc::now());
    let digest = B64.encode(hex::encode(Sha256::digest(format!("{nonce}{created}{password}").as_bytes())));
    format!("UsernameToken Username=\"{username}\", PasswordDigest=\"{digest}\", Nonce=\"{nonce}\", Created=\"{created}\"")
}

/// JWT: the credential is a token signed locally from the provider's templates.
struct Jwt;

impl AuthStrategy for Jwt {
    fn auth_mode(&self) -> AuthMode {
        AuthMode::Jwt
    }
    fn refreshable(&self) -> bool {
        true
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, _: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        ready((|| {
            let token = sign_provider_jwt(&ctx.provider, &ctx.credentials, &ctx.connection_config)?;
            let lifetime = ctx.provider.get("token").and_then(|t| t.get("expires_in_ms")).and_then(num).unwrap_or(3_600_000.0);
            let mut out = ctx.credentials.clone();
            out.insert("type".into(), json!("JWT"));
            out.insert("token".into(), json!(token));
            out.insert("expires_at".into(), json!(iso(in_ms(lifetime))));
            Ok(out)
        })())
    }
}

/// Sign the JWT described by `provider.token` / `provider.signature`.
pub fn sign_provider_jwt(
    provider: &Map<String, Value>,
    credentials: &Map<String, Value>,
    connection_config: &Map<String, Value>,
) -> Result<String> {
    let token_spec = provider.get("token").and_then(Value::as_object).ok_or_else(|| Error::token("missing_token_body"))?;
    let signature_spec = provider.get("signature").and_then(Value::as_object).ok_or_else(|| Error::token("missing_signature_type"))?;

    let mut credentials = credentials.clone();
    // Ghost admin keys arrive as "<id>:<secret>" and are split before signing.
    if let Some(Value::String(key)) = credentials.get("privateKey").cloned() {
        if key.contains(':') && !key.contains("-----") {
            let (id, secret) = key.split_once(':').unwrap();
            credentials.insert("privateKey".into(), json!({"id": id, "secret": secret}));
        }
    }
    let nested = credentials.get("connectionConfig").and_then(Value::as_object).cloned().unwrap_or_default();
    let config = merged([&nested, connection_config]);
    let mut ns = credentials.clone();
    ns.insert("connectionConfig".into(), Value::Object(config.clone()));
    ns.extend(config);

    let empty = Map::new();
    let mut payload = resolve_template(token_spec.get("payload").and_then(Value::as_object).unwrap_or(&empty), &ns);
    let header = resolve_template(token_spec.get("header").and_then(Value::as_object).unwrap_or(&empty), &ns);
    let lifetime_s = token_spec.get("expires_in_ms").and_then(num).unwrap_or(3_600_000.0) / 1000.0;
    let now = chrono::Utc::now().timestamp();
    payload.insert("iat".into(), json!(now));
    payload.insert("exp".into(), json!(now + lifetime_s as i64));

    let key_template = strip_credential(token_spec.get("signing_key").unwrap_or(&Value::Null));
    let signing_key = match &key_template {
        Value::String(t) => interpolate(t, &ns),
        _ => String::new(),
    };
    if signing_key.is_empty() || is_unresolved(&signing_key) {
        let mut fe = Map::new();
        fe.insert("signing_key".into(), json!("required"));
        return Err(Error::validation("The signing key required by this connector is missing from the credentials", fe));
    }

    let algorithm = header
        .get("alg")
        .and_then(Value::as_str)
        .or_else(|| token_spec.get("header").and_then(|h| h.get("alg")).and_then(Value::as_str))
        .unwrap_or("HS256")
        .to_string();
    let key = if signature_spec.get("protocol").and_then(Value::as_str) == Some("HMAC") {
        let bytes = if signature_spec.get("hmac_secret_encoding").and_then(Value::as_str) == Some("utf8") {
            signing_key.into_bytes()
        } else {
            hex::decode(&signing_key).map_err(|e| Error::new(ErrorKind::Validation, format!("HMAC signing key is not hex: {e}")))?
        };
        jsonwebtoken::EncodingKey::from_secret(&bytes)
    } else {
        let pem = format_pem(&signing_key, &pem_kind(&signing_key, "PRIVATE KEY"))?;
        pem_key(&pem, &algorithm)?
    };
    let mut full_header = Map::new();
    full_header.insert("alg".into(), json!(algorithm));
    full_header.insert("typ".into(), json!("JWT"));
    full_header.extend(header);
    encode_jwt(&full_header, &payload, &key, &algorithm)
}

fn pem_key(pem: &str, algorithm: &str) -> Result<jsonwebtoken::EncodingKey> {
    let bad = |e: jsonwebtoken::errors::Error| Error::new(ErrorKind::Validation, format!("invalid private key: {e}"));
    if algorithm.starts_with("ES") {
        jsonwebtoken::EncodingKey::from_ec_pem(pem.as_bytes()).map_err(bad)
    } else if algorithm == "EdDSA" {
        jsonwebtoken::EncodingKey::from_ed_pem(pem.as_bytes()).map_err(bad)
    } else {
        jsonwebtoken::EncodingKey::from_rsa_pem(pem.as_bytes()).map_err(bad)
    }
}

fn encode_jwt(
    header: &Map<String, Value>,
    payload: &Map<String, Value>,
    key: &jsonwebtoken::EncodingKey,
    algorithm: &str,
) -> Result<String> {
    let alg: jsonwebtoken::Algorithm =
        algorithm.parse().map_err(|_| Error::new(ErrorKind::Validation, format!("unsupported JWT algorithm '{algorithm}'")))?;
    let message =
        format!("{}.{}", URL_SAFE_NO_PAD.encode(serde_json::to_vec(header)?), URL_SAFE_NO_PAD.encode(serde_json::to_vec(payload)?));
    let signature =
        jsonwebtoken::crypto::sign(message.as_bytes(), key, alg).map_err(|e| Error::token(format!("JWT signing failed: {e}")))?;
    Ok(format!("{message}.{signature}"))
}

/// Interpolate a header/payload template, dropping entries that stay unresolved.
fn resolve_template(spec: &Map<String, Value>, ns: &Map<String, Value>) -> Map<String, Value> {
    let mut out = Map::new();
    for (key, value) in spec {
        match strip_credential(value) {
            Value::Null => {
                out.insert(key.clone(), Value::Null);
            }
            Value::Array(items) => {
                let resolved: Vec<Value> = items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(|item| interpolate(item, ns))
                    .filter(|t| !is_unresolved(t))
                    .flat_map(|t| t.split(',').map(str::trim).filter(|p| !p.is_empty()).map(|p| json!(p)).collect::<Vec<_>>())
                    .collect();
                if !resolved.is_empty() {
                    out.insert(key.clone(), Value::Array(resolved));
                }
            }
            v @ Value::Object(_) => {
                out.insert(key.clone(), interpolate_deep(&v, ns));
            }
            Value::String(t) => {
                let text = interpolate(&t, ns);
                if !is_unresolved(&text) {
                    out.insert(key.clone(), json!(text));
                }
            }
            other => {
                out.insert(key.clone(), other);
            }
        }
    }
    out
}

// -- OAUTH2_CC ----------------------------------------------------------------

/// The OAuth2 client-credentials grant, completed end to end.
struct OAuth2ClientCredentials;

impl AuthStrategy for OAuth2ClientCredentials {
    fn auth_mode(&self) -> AuthMode {
        AuthMode::Oauth2Cc
    }
    fn refreshable(&self) -> bool {
        true
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, transport: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        Box::pin(async move {
            let (request, client_id, client_secret) = client_credentials_request(ctx)?;
            let response = transport.send(request).await?;
            if !response.ok() {
                return Err(Error::token(format!("Client credentials request failed with status {}", response.status))
                    .with("connector_id", ctx.connector_id.clone())
                    .with("status", response.status)
                    .with("response", response.body()));
            }
            let raw = response.json().and_then(|v| v.as_object().cloned()).ok_or_else(|| {
                Error::token("Token endpoint did not return a JSON object")
                    .with("connector_id", ctx.connector_id.clone())
                    .with("response", response.text.chars().take(500).collect::<String>())
            })?;
            let mut parsed = parse_raw_credentials(&raw, AuthMode::Oauth2Cc, &ctx.provider)?;
            parsed.insert("client_id".into(), json!(client_id));
            parsed.insert("client_secret".into(), json!(client_secret));
            Ok(parsed)
        })
    }
}

fn required(field: &str) -> Error {
    let mut fe = Map::new();
    fe.insert(field.into(), json!("required"));
    Error::validation(format!("{field} is required"), fe)
}

fn client_credentials_request(ctx: &AuthContext) -> Result<(Request, String, String)> {
    let provider = &ctx.provider;
    let token_url = match provider.get("token_url") {
        Some(Value::Object(m)) => m.get("OAUTH2CC").or_else(|| m.get("OAUTH2")).and_then(Value::as_str).map(str::to_string),
        Some(Value::String(u)) => Some(u.clone()),
        _ => None,
    }
    .filter(|u| !u.trim().is_empty())
    .ok_or_else(|| {
        Error::token(format!("Connector '{}' has no token_url", ctx.connector_id)).with("connector_id", ctx.connector_id.clone())
    })?;

    let client_id = first(&ctx.credentials, &["client_id", "clientId"]);
    let client_secret = first(&ctx.credentials, &["client_secret", "clientSecret"]);
    if client_id.is_empty() {
        return Err(required("client_id"));
    }
    let mut url = make_url(&token_url, &merged([&ctx.connection_config, &ctx.credentials]))?;
    let body_format = ctx.provider_str("body_format").unwrap_or("form").to_string();
    let mut request = Request::new("POST", "");
    if body_format != "query" {
        request =
            request.header("content-type", if body_format == "json" { "application/json" } else { "application/x-www-form-urlencoded" });
    }
    let mut params: Vec<(String, String)> = Vec::new();
    let set = |params: &mut Vec<(String, String)>, k: &str, v: String| {
        params.retain(|(key, _)| key != k);
        params.push((k.to_string(), v));
    };
    match ctx.provider_str("token_request_auth_method") {
        Some("basic") => {
            if client_secret.is_empty() {
                return Err(required("client_secret"));
            }
            request = request.header("authorization", format!("Basic {}", B64.encode(format!("{client_id}:{client_secret}"))));
        }
        Some("custom") => {
            if client_secret.is_empty() {
                return Err(required("client_secret"));
            }
            set(&mut params, "username", client_id.clone());
            set(&mut params, "password", client_secret.clone());
        }
        Some("private_key_jwt") => {
            for (k, v) in private_key_jwt_params(ctx, &client_id, &url)? {
                set(&mut params, &k, v);
            }
        }
        _ => {
            set(&mut params, "client_id", client_id.clone());
            if !client_secret.is_empty() {
                set(&mut params, "client_secret", client_secret.clone());
            }
        }
    }
    let mut ns = merged([&ctx.connection_config, &ctx.credentials]);
    ns.insert("connectionConfig".into(), Value::Object(ctx.connection_config.clone()));
    for (key, value) in provider.get("token_params").and_then(Value::as_object).into_iter().flatten() {
        match value {
            Value::String(t) => {
                let resolved = interpolate(t, &ns);
                if !resolved.contains("${") {
                    set(&mut params, key, resolved);
                }
            }
            Value::Null => {}
            other => set(&mut params, key, crate::interpolation::scalar_text(other).unwrap_or_else(|| other.to_string())),
        }
    }
    let scopes = ctx
        .connection_config
        .get("oauth_scopes")
        .filter(|v| !is_empty(v))
        .or_else(|| ctx.credentials.get("scopes").filter(|v| !is_empty(v)));
    if let Some(scopes) = scopes {
        let sep = ctx.provider_str("scope_separator").filter(|s| !s.is_empty()).unwrap_or(" ");
        let joined = match scopes {
            Value::Array(a) => a.iter().map(|v| s(Some(v))).collect::<Vec<_>>().join(sep),
            other => s(Some(other)).split(',').collect::<Vec<_>>().join(sep),
        };
        set(&mut params, "scope", joined);
    }
    match body_format.as_str() {
        "query" => url = format!("{url}{}{}", if url.contains('?') { '&' } else { '?' }, form(&params)),
        "json" => {
            let obj: Map<String, Value> = params.iter().map(|(k, v)| (k.clone(), json!(v))).collect();
            request = request.content(serde_json::to_vec(&obj)?);
        }
        _ => request = request.content(form(&params)),
    }
    request.url = url;
    Ok((request, client_id, client_secret))
}

fn is_empty(v: &Value) -> bool {
    match v {
        Value::Null => true,
        Value::String(s) => s.is_empty(),
        Value::Array(a) => a.is_empty(),
        _ => false,
    }
}

/// A `client_assertion` signed with an RSA JWK private key (RFC 7523).
fn private_key_jwt_params(ctx: &AuthContext, client_id: &str, url: &str) -> Result<Vec<(String, String)>> {
    use rsa::pkcs1::EncodeRsaPrivateKey;
    let raw = first(&ctx.credentials, &["client_private_key", "privateKey"]);
    if raw.is_empty() {
        let mut fe = Map::new();
        fe.insert("client_private_key".into(), json!("required"));
        return Err(Error::validation("client_private_key is required for private_key_jwt", fe));
    }
    let invalid = |e: String| Error::new(ErrorKind::Validation, format!("invalid client_private_key format: {e}"));
    let jwk: Map<String, Value> = serde_json::from_str(&raw).map_err(|e| invalid(e.to_string()))?;
    let big = |k: &str| -> Result<rsa::BigUint> {
        let text = jwk.get(k).and_then(Value::as_str).ok_or_else(|| invalid(format!("JWK has no '{k}'")))?;
        Ok(rsa::BigUint::from_bytes_be(&URL_SAFE_NO_PAD.decode(text.trim_end_matches('=')).map_err(|e| invalid(e.to_string()))?))
    };
    let key = rsa::RsaPrivateKey::from_components(big("n")?, big("e")?, big("d")?, vec![big("p")?, big("q")?])
        .map_err(|e| invalid(e.to_string()))?;
    let der = key.to_pkcs1_der().map_err(|e| invalid(e.to_string()))?;
    let encoding = jsonwebtoken::EncodingKey::from_rsa_der(der.as_bytes());
    let now = chrono::Utc::now().timestamp();
    let mut header = Map::new();
    header.insert("alg".into(), json!("RS256"));
    header.insert("typ".into(), json!("JWT"));
    if let Some(kid) = jwk.get("kid").and_then(Value::as_str) {
        header.insert("kid".into(), json!(kid));
    }
    let payload =
        json!({"iss": client_id, "sub": client_id, "aud": url, "iat": now, "exp": now + 300, "jti": uuid::Uuid::new_v4().to_string()});
    let assertion = encode_jwt(&header, payload.as_object().unwrap(), &encoding, "RS256")?;
    Ok(vec![
        ("client_id".into(), client_id.into()),
        ("client_assertion_type".into(), "urn:ietf:params:oauth:client-assertion-type:jwt-bearer".into()),
        ("client_assertion".into(), assertion),
    ])
}

// -- externally obtained tokens ----------------------------------------------

/// OAUTH2, OAUTH1, MCP, APP, CUSTOM: import tokens your own OAuth layer obtained.
/// OAUTH2 tokens can then be refreshed here.
struct External {
    mode: AuthMode,
    token_keys: &'static [&'static str],
}

impl AuthStrategy for External {
    fn auth_mode(&self) -> AuthMode {
        self.mode
    }
    fn external_oauth(&self) -> bool {
        true
    }
    fn refreshable(&self) -> bool {
        self.mode == AuthMode::Oauth2
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, _: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        if !self.token_keys.iter().any(|k| ctx.credentials.get(*k).is_some_and(|v| !is_empty(v) && v != &json!(false))) {
            return ready(Err(Error::new(
                ErrorKind::ExternalAuthRequired,
                format!(
                    "Connector '{}' uses {}: run the OAuth flow in your own auth layer, then import the resulting tokens ({}).",
                    ctx.connector_id,
                    self.mode,
                    self.token_keys.join(", ")
                ),
            )
            .with("connector_id", ctx.connector_id.clone())
            .with("auth_mode", self.mode.as_str())
            .with("required", json!(self.token_keys))));
        }
        let mut out = Map::new();
        out.insert("type".into(), json!(self.mode.as_str()));
        out.extend(ctx.credentials.clone());
        out.insert("type".into(), json!(self.mode.as_str()));
        ready(Ok(out))
    }
    fn refresh_flow<'a>(&'a self, ctx: &'a AuthContext, transport: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        if self.mode != AuthMode::Oauth2 {
            return self.flow(ctx, transport);
        }
        Box::pin(async move {
            let (request, client_id, client_secret, refresh_token) = refresh_request(ctx)?;
            let response = transport.send(request).await?;
            if !response.ok() {
                return Err(Error::token(format!("Refresh request failed with status {}", response.status))
                    .with("connector_id", ctx.connector_id.clone())
                    .with("status", response.status)
                    .with("response", response.body()));
            }
            let raw = response.json().and_then(|v| v.as_object().cloned()).ok_or_else(|| {
                Error::token("Refresh endpoint did not return a JSON object").with("connector_id", ctx.connector_id.clone())
            })?;
            let mut parsed = parse_raw_credentials(&raw, AuthMode::Oauth2, &ctx.provider)?;
            // Providers that omit refresh_token on refresh keep the previous one working.
            if parsed.get("refresh_token").is_none_or(is_empty) {
                parsed.insert("refresh_token".into(), json!(refresh_token));
            }
            parsed.insert("client_id".into(), json!(client_id));
            if !client_secret.is_empty() {
                parsed.insert("client_secret".into(), json!(client_secret));
            }
            Ok(parsed)
        })
    }
}

fn refresh_request(ctx: &AuthContext) -> Result<(Request, String, String, String)> {
    let pick = |k: &str| {
        let v = s(ctx.credentials.get(k));
        if v.is_empty() { s(ctx.integration_config.get(k)) } else { v }
    };
    let refresh_token = s(ctx.credentials.get("refresh_token"));
    let (client_id, client_secret) = (pick("client_id"), pick("client_secret"));
    if refresh_token.is_empty() {
        return Err(Error::new(
            ErrorKind::ExternalAuthRequired,
            format!("Connection for '{}' has no refresh_token; re-run your OAuth flow.", ctx.connector_id),
        )
        .with("connector_id", ctx.connector_id.clone()));
    }
    if client_id.is_empty() {
        return Err(Error::new(
            ErrorKind::ExternalAuthRequired,
            "Refreshing an OAuth2 token needs the client_id (and usually client_secret) from your OAuth layer. Pass them via integration_config.",
        )
        .with("connector_id", ctx.connector_id.clone()));
    }
    let token_url = match ctx.provider.get("refresh_url").filter(|v| !is_empty(v)).or_else(|| ctx.provider.get("token_url")) {
        Some(Value::Object(m)) => m.get("OAUTH2").and_then(Value::as_str).map(str::to_string),
        Some(Value::String(u)) => Some(u.clone()),
        _ => None,
    }
    .filter(|u| !u.is_empty())
    .ok_or_else(|| Error::token(format!("Connector '{}' has no token_url to refresh against", ctx.connector_id)))?;
    let url = make_url(&token_url, &merged([&ctx.connection_config, &ctx.credentials]))?;
    let mut params: Vec<(String, String)> =
        vec![("grant_type".into(), "refresh_token".into()), ("refresh_token".into(), refresh_token.clone())];
    for (k, v) in ctx.provider.get("refresh_params").and_then(Value::as_object).into_iter().flatten() {
        params.retain(|(key, _)| key != k);
        params.push((k.clone(), s(Some(v))));
    }
    let mut request = Request::new("POST", url).header("content-type", "application/x-www-form-urlencoded");
    if ctx.provider_str("token_request_auth_method") == Some("basic") && !client_secret.is_empty() {
        request = request.header("authorization", format!("Basic {}", B64.encode(format!("{client_id}:{client_secret}"))));
    } else {
        params.push(("client_id".into(), client_id.clone()));
        if !client_secret.is_empty() {
            params.push(("client_secret".into(), client_secret.clone()));
        }
    }
    Ok((request.content(form(&params)), client_id, client_secret, refresh_token))
}

/// Auth modes with no handler yet.
struct Unsupported(AuthMode, &'static str);

impl AuthStrategy for Unsupported {
    fn auth_mode(&self) -> AuthMode {
        self.0
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, _: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        ready(Err(Error::new(ErrorKind::UnsupportedAuthMode, format!("Connector '{}' uses {}: {}", ctx.connector_id, self.0, self.1))
            .with("connector_id", ctx.connector_id.clone())
            .with("auth_mode", self.0.as_str())))
    }
}

// -- TWO_STEP -------------------------------------------------------------------

/// Providers that trade user credentials for a session token, possibly over several steps.
struct TwoStep;

const RESERVED: &[&str] = &["type", "token", "refresh_token", "expires_at", "raw"];

impl AuthStrategy for TwoStep {
    fn auth_mode(&self) -> AuthMode {
        AuthMode::TwoStep
    }
    fn refreshable(&self) -> bool {
        true
    }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, transport: &'a dyn Transport) -> BoxFuture<'a, Result<Map<String, Value>>> {
        Box::pin(async move {
            let provider = &ctx.provider;
            let mut dynamic = merged([&ctx.integration_config, &ctx.credentials]);
            if provider.get("assertion").is_some_and(|v| !is_empty(v)) && dynamic.get("refresh_token").is_none_or(is_empty) {
                return Err(Error::new(
                    ErrorKind::UnsupportedAuthMode,
                    format!("Connector '{}' needs a SAML/JWT assertion, which is not implemented yet.", ctx.connector_id),
                ));
            }
            if ctx.provider_str("body_format") == Some("xml") {
                return Err(Error::new(
                    ErrorKind::UnsupportedAuthMode,
                    format!("Connector '{}' uses an XML token exchange, which is not implemented yet.", ctx.connector_id),
                ));
            }
            if provider.get("signature").is_some_and(|v| !is_empty(v)) {
                // A locally signed JWT becomes the credential the token call uses.
                let token = sign_provider_jwt(provider, &dynamic, &ctx.connection_config)?;
                dynamic.insert("token".into(), json!(token));
            }
            let response = transport.send(first_request(ctx, &dynamic)?).await?;
            if !matches!(response.status, 200 | 201) {
                return Err(Error::token(format!("Token request failed with status {}", response.status))
                    .with("connector_id", ctx.connector_id.clone())
                    .with("status", response.status)
                    .with("response", response.body()));
            }
            let wanted: Vec<String> = provider
                .get("token_response_headers")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect();
            let mut header_values = header_values_of(&response, &wanted);
            let mut steps: Vec<Value> = vec![response.json().unwrap_or(json!({}))];

            let empty = Vec::new();
            for (index, step) in provider.get("additional_steps").and_then(Value::as_array).unwrap_or(&empty).iter().enumerate() {
                let step = step.as_object().cloned().unwrap_or_default();
                let step_response = transport.send(step_request(ctx, &step, &dynamic, &steps)?).await?;
                if !matches!(step_response.status, 200 | 201) {
                    return Err(Error::token(format!("Token request step {} failed with status {}", index + 1, step_response.status))
                        .with("connector_id", ctx.connector_id.clone())
                        .with("step", index + 1)
                        .with("status", step_response.status)
                        .with("response", step_response.body()));
                }
                steps.push(step_response.json().unwrap_or(json!({})));
                for (k, v) in header_values_of(&step_response, &wanted) {
                    if k == "_cookies" && header_values.contains_key("_cookies") {
                        let joined = format!("{}; {}", s(header_values.get("_cookies")), s(Some(&v)));
                        header_values.insert(k, json!(joined));
                    } else {
                        header_values.insert(k, v);
                    }
                }
            }

            let last = steps.last().cloned().unwrap_or(json!({}));
            let final_obj = match last {
                Value::Object(m) => m,
                other => {
                    let mut m = Map::new();
                    m.insert("value".into(), other);
                    m
                }
            };
            let mut parsed = parse_raw_credentials(&final_obj, AuthMode::TwoStep, provider)?;
            // Keep the user's own inputs: they are needed to refresh later.
            for (k, v) in &dynamic {
                if !v.is_null() && !RESERVED.contains(&k.as_str()) && !ctx.integration_config.contains_key(k) {
                    parsed.insert(k.clone(), v.clone());
                }
            }
            for (k, v) in header_values {
                if !RESERVED.contains(&k.as_str()) {
                    parsed.insert(k, json!(v));
                }
            }
            Ok(parsed)
        })
    }
}

fn first_request(ctx: &AuthContext, dynamic: &Map<String, Value>) -> Result<Request> {
    let p = &ctx.provider;
    let present = |k: &str| p.get(k).is_some_and(|v| !is_empty(v) && v != &json!({}));
    let wants_refresh = present("refresh_token_params") || present("refresh_token_headers");
    let is_refresh = wants_refresh && dynamic.get("refresh_token").is_some_and(|v| !is_empty(v));
    let pick = |a: &str, b: &str| if present(a) { p.get(a) } else { p.get(b) };
    let token_url = if is_refresh { pick("refresh_url", "token_url") } else { p.get("token_url") };
    let token_params = if is_refresh { p.get("refresh_token_params") } else { p.get("token_params") };
    let token_headers = if is_refresh { pick("refresh_token_headers", "token_headers") } else { p.get("token_headers") };
    let token_url = token_url
        .and_then(Value::as_str)
        .filter(|u| !u.trim().is_empty())
        .ok_or_else(|| Error::token(format!("Connector '{}' has no token_url", ctx.connector_id)))?;
    let empty = Map::new();
    build_two_step_request(
        make_url(token_url, &merged([&ctx.connection_config, dynamic]))?,
        if ctx.provider_str("token_request_method") == Some("GET") { "GET" } else { "POST" },
        resolve_params(token_params.and_then(Value::as_object).unwrap_or(&empty), dynamic, &ctx.connection_config),
        resolve_headers(token_headers.and_then(Value::as_object).unwrap_or(&empty), dynamic, &ctx.connection_config),
        ctx.provider_str("body_format").unwrap_or("json"),
    )
}

fn step_request(ctx: &AuthContext, step: &Map<String, Value>, dynamic: &Map<String, Value>, steps: &[Value]) -> Result<Request> {
    let empty = Map::new();
    let resolve_all = |key: &str| -> Map<String, Value> {
        step.get(key)
            .and_then(Value::as_object)
            .unwrap_or(&empty)
            .iter()
            .map(|(k, v)| (k.clone(), resolve_step_value(v, dynamic, steps, &ctx.connection_config)))
            .collect()
    };
    let url_template = step.get("token_url").and_then(Value::as_str).unwrap_or("");
    build_two_step_request(
        resolve_step_url(url_template, steps, &ctx.connection_config)?,
        if step.get("token_request_method").and_then(Value::as_str) == Some("GET") { "GET" } else { "POST" },
        resolve_all("token_params"),
        resolve_all("token_headers"),
        step.get("body_format").and_then(Value::as_str).or_else(|| ctx.provider_str("body_format")).unwrap_or("json"),
    )
}

fn build_two_step_request(
    url: String,
    method: &str,
    body: Map<String, Value>,
    headers: Map<String, Value>,
    body_format: &str,
) -> Result<Request> {
    let mut request = Request::new(method, url);
    for (k, v) in headers {
        if !v.is_null() {
            request.headers.insert(k.to_lowercase(), s(Some(&v)));
        }
    }
    if method == "GET" {
        return Ok(request);
    }
    if body_format == "form" {
        request.headers.entry("content-type".into()).or_insert_with(|| "application/x-www-form-urlencoded".into());
        let pairs: Vec<(String, String)> = body.iter().filter(|(_, v)| !v.is_null()).map(|(k, v)| (k.clone(), python_str(v))).collect();
        Ok(request.content(form(&pairs)))
    } else {
        request.headers.entry("content-type".into()).or_insert_with(|| "application/json".into());
        Ok(request.content(serde_json::to_vec(&body)?))
    }
}

fn python_str(v: &Value) -> String {
    match v {
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        other => s(Some(other)),
    }
}

fn resolve_value(value: &Value, ns: &Map<String, Value>) -> Value {
    match strip_credential(value) {
        v @ (Value::Object(_) | Value::Array(_)) => interpolate_deep(&v, ns),
        Value::String(t) => json!(interpolate(&t, ns)),
        other => other,
    }
}

fn resolve_params(params: &Map<String, Value>, dynamic: &Map<String, Value>, config: &Map<String, Value>) -> Map<String, Value> {
    let mut second = config.clone();
    second.insert("connectionConfig".into(), Value::Object(config.clone()));
    params
        .iter()
        .map(|(k, v)| {
            let first = resolve_value(v, dynamic);
            // A second pass resolves ${connectionConfig.x} placeholders.
            let resolved = match first {
                Value::String(t) => json!(interpolate(&t, &second)),
                other => other,
            };
            (k.clone(), resolved)
        })
        .collect()
}

fn resolve_headers(headers: &Map<String, Value>, dynamic: &Map<String, Value>, config: &Map<String, Value>) -> Map<String, Value> {
    let mut ns = merged([config, dynamic]);
    ns.insert("connectionConfig".into(), Value::Object(config.clone()));
    ns.extend(stable_replacers(headers.values().filter_map(Value::as_str)));
    headers.iter().map(|(k, v)| (k.clone(), resolve_value(v, &ns))).collect()
}

fn step_scope(step: Option<usize>, steps: &[Value]) -> Map<String, Value> {
    match step {
        Some(n) if n >= 1 && steps.len() >= n => steps[n - 1].as_object().cloned().unwrap_or_default(),
        _ => Map::new(),
    }
}

/// Prefer a value taken from a previous step's response, else from the credentials.
fn resolve_step_value(value: &Value, dynamic: &Map<String, Value>, steps: &[Value], config: &Map<String, Value>) -> Value {
    let Value::String(text) = value else { return value.clone() };
    let scope = step_scope(extract_step_number(text), steps);
    let from_step = interpolate(strip_step_response(value).as_str().unwrap_or(""), &scope);
    if !is_unresolved(&from_step) {
        return json!(from_step);
    }
    let mut ns = merged([config, dynamic]);
    ns.insert("connectionConfig".into(), Value::Object(config.clone()));
    let from_credentials = interpolate(strip_credential(value).as_str().unwrap_or(""), &ns);
    json!(if is_unresolved(&from_credentials) { from_step } else { from_credentials })
}

fn resolve_step_url(template: &str, steps: &[Value], config: &Map<String, Value>) -> Result<String> {
    let scope = step_scope(extract_step_number(template), steps);
    let mut ns = config.clone();
    ns.insert("connectionConfig".into(), Value::Object(config.clone()));
    ns.extend(scope);
    make_url(strip_step_response(&json!(template)).as_str().unwrap_or(""), &ns)
}

/// Pull values, including cookies, out of a token response's headers.
fn header_values_of(response: &HttpResponse, wanted: &[String]) -> Map<String, Value> {
    let mut out = Map::new();
    let mut cookies = Vec::new();
    for name in wanted {
        let Some(value) = response.headers.get(&name.to_lowercase()).filter(|v| !v.is_empty()) else { continue };
        if name.eq_ignore_ascii_case("set-cookie") {
            for cookie in value.split(',') {
                let pair = cookie.split(';').next().unwrap_or("");
                if let Some((k, v)) = pair.split_once('=') {
                    let (k, v) = (k.trim(), v.trim());
                    out.insert(k.into(), json!(v));
                    cookies.push(format!("{k}={v}"));
                }
            }
        } else {
            out.insert(name.clone(), json!(value));
        }
    }
    if !cookies.is_empty() {
        out.insert("_cookies".into(), json!(cookies.join("; ")));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hmac_jwt_signs_and_carries_claims() {
        let provider = json!({
            "token": {"expires_in_ms": 300000, "header": {"alg": "HS256", "kid": "${credentials.privateKey.id}"},
                      "payload": {"aud": "/admin/"}, "signing_key": "${credentials.privateKey.secret}"},
            "signature": {"protocol": "HMAC"}
        });
        let creds = json!({"privateKey": "abc123:00ff00ff"});
        let token = sign_provider_jwt(provider.as_object().unwrap(), creds.as_object().unwrap(), &Map::new()).unwrap();
        let header: Value = serde_json::from_slice(&URL_SAFE_NO_PAD.decode(token.split('.').next().unwrap()).unwrap()).unwrap();
        assert_eq!(header["kid"], "abc123");
        assert_eq!(header["alg"], "HS256");
        let claims = crate::credentials::decode_jwt_payload(&token).unwrap();
        assert_eq!(claims["aud"], "/admin/");
        assert!(claims["exp"].as_i64().unwrap() > claims["iat"].as_i64().unwrap());
    }

    #[test]
    fn wsse_shape() {
        let h = generate_wsse("u", "p");
        assert!(h.starts_with("UsernameToken Username=\"u\", PasswordDigest=\""));
    }
}
