//! Whole-catalogue invariants, the Rust counterpart of the Python suite's
//! `test_registry.py`, `test_proxy.py` and `test_tool_packs.py`.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use connector_manager::http::{BoxFuture, HttpResponse, Request, Transport};
use connector_manager::interpolation::is_unresolved;
use connector_manager::tools::ToolExecutor;
use connector_manager::{
    AuthMode, BaseConnectorManager, Call, ConnectOptions, Connection, ConnectorFilter, ConnectorManager, ErrorKind, SpecFormat,
    ToolParameter,
};
use serde_json::{Map, Value, json};

/// Connectors whose base url needs a value the auth schema does not describe.
const CANNOT_BUILD_FROM_SCHEMA_ALONE: &[&str] = &[
    "linear-mcp",
    "mcp-generic",
    "salesforce-cdp",
    "salesforce-jwt",
    "teamwork",
    "unauthenticated",
    "garmin",
    "smugmug",
    "trello",
    "twitter",
];

fn base() -> BaseConnectorManager {
    BaseConnectorManager::new().expect("bundled catalogue loads")
}

fn placeholder(name: &str) -> String {
    let lowered = name.to_lowercase();
    if lowered.contains("url") || (lowered.contains("domain") && !lowered.contains("sub")) {
        "https://example.com".into()
    } else {
        "example".into()
    }
}

/// A plausible connection, so templated base urls resolve (as the Python tests build it).
fn connection(manager: &BaseConnectorManager, id: &str) -> Connection {
    let schema = manager.get_auth_schema(id).unwrap();
    let mut config = Map::new();
    for f in &schema.connection_config {
        let value = f
            .example
            .clone()
            .filter(|s| !s.is_empty())
            .or_else(|| f.default_value.clone().filter(|s| !s.is_empty()))
            .unwrap_or_else(|| placeholder(&f.name));
        config.insert(f.name.clone(), json!(value));
    }
    config.entry("subdomain").or_insert(json!("example"));
    let mut credentials: Map<String, Value> = json!({
        "access_token": "test-access-token", "token": "test-token", "apiKey": "test-api-key",
        "api_key": "test-api-key", "username": "test-user", "password": "test-password"
    })
    .as_object()
    .unwrap()
    .clone();
    for f in &schema.credentials {
        credentials
            .entry(f.name.clone())
            .or_insert(json!(f.example.clone().filter(|s| !s.is_empty()).unwrap_or_else(|| "test-value".into())));
    }
    let mut c = Connection::new(id, manager.get_connector(id).unwrap().auth_mode);
    c.credentials = credentials;
    c.connection_config = config;
    c.integration_config = json!({"client_id": "test-client-id", "client_secret": "test-client-secret"}).as_object().unwrap().clone();
    c
}

fn object_from(schema: &Value) -> Value {
    match schema.get("properties").and_then(Value::as_object).filter(|p| !p.is_empty()) {
        None => json!({"example": "value"}),
        Some(props) => Value::Object(
            props
                .iter()
                .map(|(k, spec)| {
                    let numeric = matches!(spec.get("type").and_then(Value::as_str), Some("integer" | "number"));
                    (k.clone(), if numeric { json!(1) } else { json!("example") })
                })
                .collect(),
        ),
    }
}

/// A synthetic value for an argument, as the Python tests choose it.
fn value(p: &ToolParameter) -> Value {
    if let Some(first) = p.r#enum.first() {
        return first.clone();
    }
    if let Some(d) = &p.default {
        return d.clone();
    }
    match p.param_type.as_str() {
        "integer" => json!(p.minimum.map_or(1, |m| m as i64)),
        "number" => json!(p.minimum.unwrap_or(1.0)),
        "boolean" => json!(true),
        "array" => {
            let items = p.items.clone().unwrap_or(json!({}));
            let one = match items.get("type").and_then(Value::as_str).unwrap_or("string") {
                "object" => object_from(&items),
                "string" => json!("example"),
                _ => json!(1),
            };
            let n = p.min_length.unwrap_or(1).max(1);
            Value::Array(vec![one; n])
        }
        "object" => object_from(&json!({"properties": p.properties.clone().unwrap_or(json!({}))})),
        _ if p.format.as_deref() == Some("email") => json!("person@example.com"),
        _ => {
            let mut s = p.example.as_ref().and_then(Value::as_str).unwrap_or("example").to_string();
            if let Some(max) = p.max_length {
                s = s.chars().take(max).collect();
            }
            if let Some(min) = p.min_length {
                while s.chars().count() < min {
                    s.push('x');
                }
            }
            json!(s)
        }
    }
}

#[test]
fn catalogue_loads_with_every_icon() {
    let m = base();
    assert!(m.len() > 2000, "expected the bundled catalogue, found {}", m.len());
    let missing: Vec<String> = m.registry.iter().filter(|c| m.get_icon(&c.id).is_none()).map(|c| c.id.clone()).collect();
    assert!(missing.is_empty(), "connectors without an icon: {missing:?}");
    assert!(m.get_icon("stripe").unwrap().contains("<svg"));
}

#[test]
fn every_connector_has_a_schema_and_tools() {
    let m = base();
    for c in m.registry.iter() {
        let schema = m.get_auth_schema(&c.id).unwrap();
        assert_eq!(schema.auth_mode, c.auth_mode, "{}", c.id);
        assert!(!m.list_tools(&c.id).unwrap().is_empty(), "{} has no tools", c.id);
    }
}

#[test]
fn listing_pages_and_filters() {
    let m = base();
    let all = ConnectorFilter::default();
    let pages = m.connector_pages(200, &all).unwrap();
    assert_eq!(pages.iter().map(|p| p.count()).sum::<usize>(), m.len());
    let crm = m.list_connectors(&ConnectorFilter::default().category("crm"), None, 0);
    assert!(!crm.is_empty() && crm.iter().all(|c| c.categories.iter().any(|x| x == "crm")));
    let page = m.paginate_connectors(2, 20, None, &all).unwrap();
    assert_eq!((page.page(), page.count(), page.has_previous(), page.next_offset()), (2, 20, true, Some(40)));
    assert!(m.paginate_connectors(1, 5000, None, &all).is_err());
    assert_eq!(m.get_connector("no-such-connector").unwrap_err().kind, ErrorKind::UnknownConnector);
}

#[test]
fn every_connector_builds_a_resolved_request() {
    let m = base();
    let mut problems = Vec::new();
    for c in m.registry.iter() {
        if CANNOT_BUILD_FROM_SCHEMA_ALONE.contains(&c.id.as_str()) {
            continue;
        }
        let schema = m.get_auth_schema(&c.id).unwrap();
        let pick = |f: &connector_manager::AuthField| {
            json!(f.r#enum.first().cloned().or_else(|| f.example.clone()).unwrap_or_else(|| "placeholder".into()))
        };
        let mut conn = Connection::new(c.id.clone(), schema.auth_mode);
        conn.credentials = schema.credentials.iter().map(|f| (f.name.clone(), pick(f))).collect();
        conn.credentials.entry("access_token").or_insert(json!("test-token"));
        conn.credentials.entry("token").or_insert(json!("test-token"));
        conn.credentials.insert("type".into(), json!(schema.auth_mode.as_str()));
        conn.connection_config = schema.connection_config.iter().map(|f| (f.name.clone(), pick(f))).collect();
        conn.integration_config = schema.integration_config.iter().map(|f| (f.name.clone(), pick(f))).collect();
        match m.prepare_request(&conn, Call::new("GET", "/ping")) {
            Err(e) => problems.push(format!("{}: {e}", c.id)),
            Ok(r) => {
                if is_unresolved(&r.url) {
                    problems.push(format!("{}: unresolved url {}", c.id, r.url));
                }
                for (k, v) in &r.headers {
                    if is_unresolved(v) {
                        problems.push(format!("{}: unresolved header {k}", c.id));
                    }
                }
            }
        }
    }
    assert!(problems.is_empty(), "{} problem(s): {:?}", problems.len(), &problems[..problems.len().min(10)]);
}

#[test]
fn every_tool_builds_a_resolvable_request() {
    let m = base();
    let mut problems = Vec::new();
    let mut count = 0;
    for pack in m.tools.packs().unwrap() {
        let provider = m.registry.raw(&pack.connector_id).unwrap();
        let conn = connection(&m, &pack.connector_id);
        for tool in &pack.tools {
            count += 1;
            let args: Map<String, Value> = tool.input.iter().map(|p| (p.name.clone(), value(p))).collect();
            let executor = ToolExecutor::new(provider.clone(), tool.clone(), conn.clone());
            match executor.build(&args) {
                Err(e) => problems.push(format!("{}: {e}", tool.qualified_name())),
                Ok(r) => {
                    let body = serde_json::to_string(&r.json_body).unwrap();
                    let content = r.content.as_ref().map(|c| String::from_utf8_lossy(c).into_owned()).unwrap_or_default();
                    if r.method != tool.request.method
                        || !r.url.starts_with("http")
                        || is_unresolved(&r.url)
                        || is_unresolved(&body)
                        || is_unresolved(&content)
                    {
                        problems.push(format!("{}: built {} {}", tool.qualified_name(), r.method, r.url));
                    }
                    if r.headers.values().chain(r.params.values()).any(|v| is_unresolved(v)) {
                        problems.push(format!("{}: unresolved header or query", tool.qualified_name()));
                    }
                }
            }
            if tool.required_parameters().iter().any(|_| true) {
                let err = executor.build(&Map::new()).unwrap_err();
                assert_eq!(err.kind, ErrorKind::ToolValidation, "{}", tool.qualified_name());
            }
            for format in [SpecFormat::Anthropic, SpecFormat::OpenAi, SpecFormat::Mcp] {
                assert!(tool.spec(format, true).is_object());
            }
        }
    }
    assert!(count > 25_000, "expected the bundled tool packs, found {count} tools");
    assert!(problems.is_empty(), "{} problem(s): {:?}", problems.len(), &problems[..problems.len().min(10)]);
}

/// Records requests and answers from a script, like respx in the Python suite.
struct Script {
    sent: Mutex<Vec<Request>>,
    reply: Box<dyn Fn(&Request) -> HttpResponse + Send + Sync>,
}

/// Shares one script between the manager and the test that inspects it.
struct Shared(Arc<Script>);

impl Transport for Shared {
    fn send<'a>(&'a self, request: Request) -> BoxFuture<'a, connector_manager::Result<HttpResponse>> {
        let response = (self.0.reply)(&request);
        self.0.sent.lock().unwrap().push(request);
        Box::pin(std::future::ready(Ok(response)))
    }
}

fn reply(status: u16, body: Value) -> HttpResponse {
    HttpResponse { status, headers: BTreeMap::new(), text: body.to_string(), url: "https://example.test/".into() }
}

#[test]
fn api_key_connect_verifies_against_the_declared_endpoint() {
    let script = Arc::new(Script { sent: Mutex::new(Vec::new()), reply: Box::new(|_| reply(200, json!({"user": "me"}))) });
    let m = ConnectorManager::with_transport(base(), Box::new(Shared(script.clone())));
    let conn = m.connect("affinity-v2", ConnectOptions::new().credentials(json!({"apiKey": "k"}))).unwrap();
    assert!(conn.verified);
    let sent = script.sent.lock().unwrap();
    assert_eq!(sent.len(), 1);
    assert!(sent[0].url.ends_with("/v2/auth/whoami"));
    assert_eq!(sent[0].headers["authorization"], "Bearer k");
}

#[test]
fn client_credentials_exchange_then_refresh() {
    let script = Arc::new(Script {
        sent: Mutex::new(Vec::new()),
        reply: Box::new(|r| {
            if r.url.contains("/oauth2/token") {
                reply(200, json!({"access_token": "fresh", "expires_in": 3600}))
            } else {
                reply(200, json!([]))
            }
        }),
    });
    let m = ConnectorManager::with_transport(base(), Box::new(Shared(script.clone())));
    let mut conn = m
        .connect(
            "1password-users",
            ConnectOptions::new()
                .credentials(json!({"client_id": "5ab87915-2deb-429c-a1e2-8b0495900f45", "client_secret": "s"}))
                .connection_config(json!({"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"}))
                .verify(false),
        )
        .unwrap();
    assert_eq!(conn.credentials["token"], "fresh");
    assert!(!conn.is_expired(60));
    let token_call = script.sent.lock().unwrap()[0].clone();
    assert!(token_call.headers["authorization"].starts_with("Basic "));
    assert!(String::from_utf8(token_call.content.unwrap()).unwrap().contains("grant_type=client_credentials"));

    conn.credentials.insert("expires_at".into(), json!("2000-01-01T00:00:00Z"));
    m.ensure_fresh(&mut conn, 60).unwrap();
    assert_eq!(script.sent.lock().unwrap().len(), 2, "an expired token is refreshed");
}

#[test]
fn oauth2_needs_imported_tokens() {
    let m = base();
    let script = Arc::new(Script { sent: Mutex::new(Vec::new()), reply: Box::new(|_| reply(200, json!({}))) });
    let manager = ConnectorManager::with_transport(m, Box::new(Shared(script)));
    let err = manager.connect("hubspot", ConnectOptions::new().verify(false)).unwrap_err();
    assert_eq!(err.kind, ErrorKind::ExternalAuthRequired);
}

#[test]
fn tool_permissions_follow_the_grant() {
    let m = base();
    let mut conn = Connection::new("outlook", AuthMode::Oauth2);
    conn.credentials.insert("access_token".into(), json!("t"));
    let unknown = m.check_tools(&conn, None).unwrap();
    assert!(!unknown.unknown().is_empty());
    conn.credentials.insert("scope".into(), json!("Mail.Read"));
    let report = m.check_tools(&conn, None).unwrap();
    let send = report.status("send_email").unwrap();
    assert_eq!(send.availability, connector_manager::ToolAvailability::Disabled);
    assert!(send.missing_scopes.iter().any(|s| s.eq_ignore_ascii_case("Mail.Send")));

    let script = Arc::new(Script { sent: Mutex::new(Vec::new()), reply: Box::new(|_| reply(202, json!({}))) });
    let manager = ConnectorManager::with_transport(m, Box::new(Shared(script.clone())));
    let err = manager.call_tool(&mut conn, "send_email", json!({"to": ["a@b.com"], "subject": "s", "body": "b"})).unwrap_err();
    assert_eq!(err.kind, ErrorKind::ToolPermission);
    assert!(script.sent.lock().unwrap().is_empty(), "a ruled-out call is never sent");
}

#[test]
fn connections_round_trip_through_json() {
    let mut c = Connection::new("affinity-v2", AuthMode::ApiKey);
    c.credentials.insert("apiKey".into(), json!("k"));
    let back = Connection::from_json(c.to_json()).unwrap();
    assert_eq!(back, c);
    let from_python = json!({"connector_id": "x", "auth_mode": "OAUTH2_CC", "credentials": {"token": "t"}});
    let loaded = Connection::from_json(from_python).unwrap();
    assert_eq!(loaded.auth_mode, AuthMode::Oauth2Cc);
    assert!(!loaded.connection_id.is_empty());
}

#[tokio::test]
async fn async_manager_matches_blocking() {
    let make = || Arc::new(Script { sent: Mutex::new(Vec::new()), reply: Box::new(|_| reply(200, json!({"ok": true}))) });
    let (a, b) = (make(), make());
    let sync = ConnectorManager::with_transport(base(), Box::new(Shared(a.clone())));
    let asynchronous = connector_manager::AsyncConnectorManager::with_transport(base(), Box::new(Shared(b.clone())));
    let options = || ConnectOptions::new().credentials(json!({"apiKey": "k"}));
    let one = sync.connect("affinity-v2", options()).unwrap();
    let two = asynchronous.connect("affinity-v2", options()).await.unwrap();
    assert_eq!(one.credentials, two.credentials);
    assert_eq!(one.verified, two.verified);
    assert_eq!(a.sent.lock().unwrap()[0].url, b.sent.lock().unwrap()[0].url);
}
