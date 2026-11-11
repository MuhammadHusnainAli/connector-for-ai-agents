# connector-for-ai-agents for Rust

The Rust crate: the same library as the Python package, for Rust. It lives in
[`src/connector_manager_rs`](src/connector_manager_rs) and is imported as
`connector_manager`, the same name as the Python import.

Both libraries read one data directory, `src/connector_manager/data`, so the
connectors, auth schemas, tool packs and icons are identical, and a
`Connection` saved by one loads in the other. Back to the [README](README.md);
the Python documentation is [PYTHON.md](PYTHON.md).

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Browse the catalogue](#browse-the-catalogue)
- [Ask what a connector needs](#ask-what-a-connector-needs)
- [Connect](#connect)
- [Use the connection and keep it alive](#use-the-connection-and-keep-it-alive)
- [Blocking and async](#blocking-and-async)
- [Tools](#tools)
- [Using this from an AI agent](#using-this-from-an-ai-agent)
- [Auth mode coverage](#auth-mode-coverage)
- [Errors](#errors)
- [Adding your own auth mode](#adding-your-own-auth-mode)
- [Testing without a network](#testing-without-a-network)
- [Your own catalogue](#your-own-catalogue)
- [Command line](#command-line)
- [How it is put together](#how-it-is-put-together)
- [Keeping Rust and Python identical](#keeping-rust-and-python-identical)

## Install

The crate is not on crates.io yet. Depend on it from git; Cargo finds the
package inside the repository:

```toml
[dependencies]
connector-for-ai-agents = { git = "https://github.com/MuhammadHusnainAli/connector-for-ai-agents" }
serde_json = "1"
# only for AsyncConnectorManager:
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
```

Rust 1.85+. HTTP goes through `reqwest` with rustls. The catalogue, every tool
pack and every logo are compiled into the binary by the default `bundled`
feature (about 40 MB of JSON and SVG), so nothing is fetched at runtime. Build
with `default-features = false` and use [`DataSource::Dir`](#your-own-catalogue)
to read them from disk instead.

Working on the crate itself:

```bash
cd src/connector_manager_rs
cargo test                 # unit tests, integration tests and the examples in this file
cargo run --bin connectors -- list --search slack
```

## Quick start

Four calls cover the whole lifecycle: find a connector, ask what it needs,
connect, then call the API.

```rust,no_run
use connector_manager::{Call, ConnectOptions, ConnectorFilter, ConnectorManager};
use serde_json::json;

let manager = ConnectorManager::new()?;

// 1. find it
let found = manager.list_connectors(&ConnectorFilter::default().search("affinity"), Some(5), 0);

// 2. ask what it needs: enough to render a form or a tool spec
let schema = manager.describe_auth("affinity-v2")?;

// 3. connect: validates the fields, runs any token exchange, verifies the result
let mut connection = manager.connect("affinity-v2", ConnectOptions::new().credentials(json!({"apiKey": "..."})))?;
assert!(connection.verified);

// 4. call the API with the credentials applied for you
let response = manager.request(&mut connection, Call::new("GET", "/v2/persons"))?;
println!("{}", response.body());

// 5. or work in capabilities rather than endpoints
let report = manager.check_tools(&connection, None)?;
println!("{}", report.summary());
# Ok::<(), connector_manager::Error>(())
```

## Browse the catalogue

Everything here reads the bundled data; there is no network call.

```rust
use connector_manager::{AuthMode, ConnectorFilter, ConnectorManager};

let manager = ConnectorManager::new()?;
assert!(manager.len() > 2000);

let crm = ConnectorFilter::default().category("crm").self_service_only();
for connector in manager.list_connectors(&crm, Some(10), 0) {
    println!("{} {} {}", connector.id, connector.display_name, connector.auth_mode);
}

let slack = manager.get_connector("slack")?;
let svg = manager.get_icon("slack");                 // inline SVG
let modes = manager.auth_modes();                    // [(AuthMode::ApiKey, 9xx), ...]
let categories = manager.categories();
let api_key_only = ConnectorFilter::default().auth_mode(AuthMode::ApiKey);
# Ok::<(), connector_manager::Error>(())
```

### Pagination

A page carries its items and the numbers a picker needs, `total` included, so
"showing 21-40 of 2,174" never costs a second call.

```rust
use connector_manager::{ConnectorFilter, ConnectorManager};

let manager = ConnectorManager::new()?;
let page = manager.paginate_connectors(2, 20, None, &ConnectorFilter::default())?;
assert_eq!((page.page(), page.count(), page.has_previous()), (2, 20, true));
println!("showing {}-{} of {}", page.first_index(), page.last_index(), page.total);

let next = page.next_offset();                      // Some(40)
let json = page.to_json();                          // {"items": [...], "pagination": {...}}

// walk everything
let pages = manager.connector_pages(200, &ConnectorFilter::default())?;
# Ok::<(), connector_manager::Error>(())
```

## Ask what a connector needs

`get_auth_schema` lists every field, grouped by where it goes, with what a form
needs to render and validate it.

```rust
use connector_manager::ConnectorManager;

let manager = ConnectorManager::new()?;
let schema = manager.get_auth_schema("1password-users")?;
for field in schema.user_fields() {
    println!("{:<18} {:<14} {:<16} required={} secret={}",
        field.group.as_str(), field.name, field.title, field.required, field.secret);
}
// connection_config  domain         API Domain       required=true secret=false
// connection_config  accountId      Account ID       required=true secret=false
// credentials        client_id      Client ID        required=true secret=false
// credentials        client_secret  Client Secret    required=true secret=true
# Ok::<(), connector_manager::Error>(())
```

Each `AuthField` carries `title`, `description`, `example`, `pattern`, `format`,
`enum`, `default_value`, `secret`, `order`, `automated`, `hidden` and
`visible_when`. `schema.to_json()` is the same JSON as Python's `to_dict()`.

Validate input without calling the provider; every bad field is reported at once:

```rust
use connector_manager::{ConnectorManager, ErrorKind};
use serde_json::json;

let manager = ConnectorManager::new()?;
let err = manager.validate("1password-users", json!({}), json!({"domain": "nope"}), json!({})).unwrap_err();
assert_eq!(err.kind, ErrorKind::Validation);
assert!(err.field_errors().contains_key("client_id"));
# Ok::<(), connector_manager::Error>(())
```

## Connect

`connect` validates the fields, runs whatever the auth mode needs (nothing, a
client-credentials exchange, a multi-step login, a locally signed JWT), then
calls the connector's own verification endpoint.

```rust,no_run
use connector_manager::{ConnectOptions, ConnectorManager};
use serde_json::json;

let manager = ConnectorManager::new()?;
let connection = manager.connect(
    "1password-users",
    ConnectOptions::new()
        .credentials(json!({"client_id": "...", "client_secret": "..."}))
        .connection_config(json!({"domain": "api.1password.com", "accountId": "XLQMR47VZPBKJHSGWNCYFDE3T9"}))
        .require_verified(),            // fail instead of returning verified = false
)?;

// persist it yourself; this crate stores nothing
let saved = connection.to_json();
let restored = connector_manager::Connection::from_json(saved)?;
# Ok::<(), connector_manager::Error>(())
```

`ConnectOptions` also takes `integration_config`, `metadata`, a fixed
`connection_id`, and `.verify(false)` to skip the verification call.

OAuth connectors need a browser redirect, which belongs to your application. Run
the flow there, then import the tokens; with a `refresh_token`, `client_id` and
`client_secret` this crate can keep the token fresh:

```rust,no_run
use connector_manager::{ConnectOptions, ConnectorManager};
use serde_json::json;

let manager = ConnectorManager::new()?;
let connection = manager.import_connection(
    "hubspot",
    ConnectOptions::new().credentials(json!({
        "access_token": "...", "refresh_token": "...",
        "client_id": "...", "client_secret": "...", "scope": "crm.objects.contacts.read"
    })),
)?;
# Ok::<(), connector_manager::Error>(())
```

## Use the connection and keep it alive

```rust,no_run
use connector_manager::{Call, ConnectorManager, Connection};

let manager = ConnectorManager::new()?;
let mut connection: Connection = Connection::from_json(serde_json::from_str("{}")?)?;

// refreshes first when the token is within 60 s of expiring
let response = manager.request(&mut connection, Call::new("GET", "/v2/persons").param("limit", "50"))?;

manager.ensure_fresh(&mut connection, 300)?;       // refresh if within 5 minutes
manager.refresh(&mut connection)?;                 // refresh now (no-op for static keys)
let result = manager.verify(&connection)?;        // re-run the verification call

// or hand the fully resolved call to something else: a worker, an agent runtime
let request = manager.prepare_request(&connection, Call::new("GET", "/v2/persons"))?;
println!("{} {} {:?}", request.method, request.url, request.headers);
# Ok::<(), connector_manager::Error>(())
```

A `Call` takes headers, query `param`s, a `json` body or raw `content`. Requests
to `aws-*` and `alibaba-cloud-*` connectors are signed (SigV4 / ACS3) as they
are built.

## Blocking and async

`ConnectorManager` blocks; `AsyncConnectorManager` returns futures and needs a
Tokio runtime. Both deref to `BaseConnectorManager`, which holds everything that
needs no network (catalogue, schemas, validation, request building, tools), so
those methods are identical on both.

The network work is written once. Every auth flow, the verification call and
scope discovery are `async` functions over a `Transport`; the async manager
awaits them on an async HTTP client, the blocking manager drives the very same
futures to completion over a blocking client. The two cannot drift apart.

```rust,no_run
use connector_manager::{AsyncConnectorManager, Call, ConnectOptions};
use serde_json::json;

#[tokio::main]
async fn main() -> connector_manager::Result<()> {
    let manager = AsyncConnectorManager::new()?;
    let mut connection = manager
        .connect("affinity-v2", ConnectOptions::new().credentials(json!({"apiKey": "..."})))
        .await?;
    let response = manager.request(&mut connection, Call::new("GET", "/v2/persons")).await?;
    let result = manager.call_tool(&mut connection, "whoami", json!({})).await?;
    Ok(())
}
```

`HttpOptions` sets the timeout, redirects and TLS verification:
`ConnectorManager::with_options(HttpOptions { timeout: Duration::from_secs(10), ..Default::default() })`.

## Tools

A tool is one thing an agent can do with a connector: a name, a description,
typed inputs, a described output, and the scopes the provider demands. Every
connector has tools: a hand-authored pack where one exists, else
`check_connection` from its verification endpoint plus the raw `*_api` request
tools. [TOOLS.md](TOOLS.md) lists them all.

```rust
use connector_manager::{ConnectorManager, SpecFormat};

let manager = ConnectorManager::new()?;
let tools = manager.list_tools("outlook")?;
let send = manager.get_tool("outlook", "send_email")?;
println!("{} {} {:?}", send.request.method, send.request.path, send.scopes);

let anthropic = manager.tool_specs("outlook", SpecFormat::Anthropic, false)?;
let openai = manager.tool_specs("outlook", SpecFormat::OpenAi, false)?;
let mcp = manager.tool_specs("outlook", SpecFormat::Mcp, false)?;

let found = manager.search_tools("invoice", None)?;
let stats = manager.tool_stats();
# Ok::<(), connector_manager::Error>(())
```

### Which tools may this credential call?

`check_tools` compares the grant recorded on the connection (or one you pass)
with each tool's scopes, using the provider's own scope rules (case, URL
prefixes, `Mail.ReadWrite` implying `Mail.Read`, ...).

```rust
use connector_manager::{AuthMode, Connection, ConnectorManager};
use serde_json::json;

let manager = ConnectorManager::new()?;
let mut connection = Connection::new("outlook", AuthMode::Oauth2);
connection.credentials.insert("scope".into(), json!("Mail.Read User.Read"));

let report = manager.check_tools(&connection, None)?;
println!("{}", report.summary());   // outlook: 20/54 tools enabled, 34 disabled, 0 unknown (...)
let status = report.status("send_email").unwrap();
println!("{:?} {:?}", status.availability, status.missing_scopes);   // Disabled ["Mail.Send"]
let callable = report.specs(connector_manager::SpecFormat::Anthropic, false);
# Ok::<(), connector_manager::Error>(())
```

`check_tools_live` asks the provider instead: it reads a JWT access token's own
`scp`/`roles` claim, or calls the connector's token-info endpoint.

### Calling one

```rust,no_run
use connector_manager::{ConnectorManager, Connection};
use serde_json::json;

let manager = ConnectorManager::new()?;
let mut connection = Connection::from_json(serde_json::from_str(&std::fs::read_to_string("conn.json").unwrap())?)?;

let result = manager.call_tool(&mut connection, "send_email", json!({
    "to": ["ada@example.com"], "subject": "Hi", "body": "<p>Hello</p>"
}))?;
println!("{} {:?} {}", result.ok, result.status, result.data);

// build without sending, e.g. to show a human before an agent acts
let request = manager.prepare_tool_request(&connection, "send_email", json!({"to": ["a@b.com"], "subject": "x", "body": "y"}))?;
# Ok::<(), connector_manager::Error>(())
```

Arguments are validated first, and every problem is named at once
(`ErrorKind::ToolValidation`, `err.argument_errors()`). A call the recorded
grant rules out fails with `ErrorKind::ToolPermission` before anything is sent;
an unknown grant never blocks. `call_tool_with_options` turns either check off.

## Using this from an AI agent

```rust,no_run
use connector_manager::{ConnectorManager, Connection, SpecFormat};
use serde_json::{Value, json};

let manager = ConnectorManager::new()?;
let mut connection = Connection::from_json(json!({"connector_id": "outlook", "auth_mode": "OAUTH2",
    "credentials": {"access_token": "...", "scope": "Mail.Read Mail.Send"}}))?;

// 1. give the model exactly the tools this credential can use
let tools: Vec<Value> = manager.enabled_tool_specs(&connection, SpecFormat::Anthropic)?;

// 2. ...send `tools` with your Messages API request, then run each tool_use block:
let (name, input) = ("send_email", json!({"to": ["a@b.com"], "subject": "Hi", "body": "Hello"}));
let result = manager.call_tool(&mut connection, name, input)?;
let tool_result = result.to_json();    // put this in the tool_result content
# Ok::<(), connector_manager::Error>(())
```

`tool.read_only` and `tool.destructive` are there for your approval policy:
auto-run reads, ask a human before a destructive call.

## Auth mode coverage

| Auth mode | What `connect` does |
| --- | --- |
| `NONE`, `API_KEY`, `BASIC`, `INSTALL_PLUGIN` | takes the values as given, then verifies them |
| `TBA` | OAuth 1.0a HMAC-SHA256 signature per request (NetSuite) |
| `OAUTH2_CC` | client-credentials exchange (basic, body, custom or `private_key_jwt` client auth) |
| `TWO_STEP` | the provider's login exchange, including chained steps, cookies and signed-JWT assertions |
| `JWT` | signs the token locally (RS256, ES256, HS256, ...) |
| `SIGNATURE` | WS-Security UsernameToken |
| `OAUTH2`, `OAUTH1`, `MCP_OAUTH2`, `MCP_OAUTH2_GENERIC`, `APP`, `CUSTOM` | imports tokens your OAuth layer obtained; OAUTH2 refreshes here |
| `BILL`, `AWS_SIGV4` | not implemented: `ErrorKind::UnsupportedAuthMode` |

AWS and Alibaba Cloud services connect over `BASIC` (access key id and secret)
and every request is signed with SigV4 or ACS3-HMAC-SHA256. The signers are
tested against AWS's published SigV4 vectors and give the same signatures as
botocore and Alibaba Cloud's SDK.

## Errors

Every failure is one `Error` with an `ErrorKind` named after the Python
exception class, a message, and structured context:

```rust
use connector_manager::{ConnectorManager, ErrorKind};

let manager = ConnectorManager::new()?;
let err = manager.get_connector("no-such-thing").unwrap_err();
assert_eq!(err.kind, ErrorKind::UnknownConnector);
println!("{}", err.to_json());   // {"error": "UnknownConnectorError", "message": ..., "connector_id": ...}
# Ok::<(), connector_manager::Error>(())
```

Kinds: `UnknownConnector`, `UnsupportedAuthMode`, `ExternalAuthRequired`,
`Validation`, `Interpolation`, `TokenExchange`, `Verification`, `Request`,
`UnknownTool`, `ToolValidation`, `ToolPermission`, `Data`.

## Adding your own auth mode

Implement `AuthStrategy` and register it on the manager. Send requests through
the `Transport` you are given and the strategy works in both managers.

```rust,no_run
use std::sync::Arc;
use connector_manager::http::{BoxFuture, Request, Transport};
use connector_manager::{AuthContext, AuthMode, AuthStrategy, ConnectorManager, Error};
use serde_json::{Map, Value, json};

struct BillAuth;

impl AuthStrategy for BillAuth {
    fn auth_mode(&self) -> AuthMode { AuthMode::Bill }
    fn refreshable(&self) -> bool { true }
    fn flow<'a>(&'a self, ctx: &'a AuthContext, transport: &'a dyn Transport)
        -> BoxFuture<'a, connector_manager::Result<Map<String, Value>>> {
        Box::pin(async move {
            let request = Request::new("POST", "https://api.bill.com/api/v2/Login.json")
                .header("content-type", "application/json")
                .content(serde_json::to_vec(&ctx.credentials)?);
            let response = transport.send(request).await?;
            let session = response.json().and_then(|v| v["response_data"]["sessionId"].as_str().map(str::to_string))
                .ok_or_else(|| Error::new(connector_manager::ErrorKind::TokenExchange, "no session"))?;
            Ok(json!({"type": "BILL", "token": session}).as_object().unwrap().clone())
        })
    }
}

let mut manager = ConnectorManager::new()?;
manager.base_mut().register_strategy(Arc::new(BillAuth));
# Ok::<(), connector_manager::Error>(())
```

## Testing without a network

`Transport` is the only I/O. Implement it to return canned responses, and build
a manager on it with `with_transport`:

```rust
use connector_manager::http::{BoxFuture, HttpResponse, Request, Transport};
use connector_manager::{BaseConnectorManager, ConnectOptions, ConnectorManager};
use serde_json::json;

struct Canned;

impl Transport for Canned {
    fn send<'a>(&'a self, request: Request) -> BoxFuture<'a, connector_manager::Result<HttpResponse>> {
        let response = HttpResponse { status: 200, headers: Default::default(), text: "{}".into(), url: request.url };
        Box::pin(std::future::ready(Ok(response)))
    }
}

let manager = ConnectorManager::with_transport(BaseConnectorManager::new()?, Box::new(Canned));
let connection = manager.connect("affinity-v2", ConnectOptions::new().credentials(json!({"apiKey": "test-key"})))?;
assert!(connection.verified);
# Ok::<(), connector_manager::Error>(())
```

## Your own catalogue

`DataSource::Dir` reads a directory laid out like the bundled data
(`connectors/*.json`, `tools/<auth-mode>/*.json` plus `tools/index.json`,
`icons/*.svg`):

```rust,no_run
use connector_manager::{BaseConnectorManager, BlockingTransport, ConnectorManager, DataSource, HttpOptions};

let base = BaseConnectorManager::from_source(DataSource::Dir("/srv/my-catalogue".into()))?;
let manager = ConnectorManager::with_transport(base, Box::new(BlockingTransport::new(&HttpOptions::default())?));
# Ok::<(), connector_manager::Error>(())
```

## Command line

The crate builds a `connectors` binary with the same commands as
`python -m connector_manager`:

```bash
cargo install --git https://github.com/MuhammadHusnainAli/connector-for-ai-agents connector-for-ai-agents

connectors list --search slack
connectors list --category crm --page 2 --page-size 20
connectors show affinity-v2
connectors stats
connectors connect affinity-v2 -c apiKey=... -o conn.json      # written with mode 0600
connectors request conn.json GET /v2/persons -q limit=50
connectors tools outlook --format anthropic
connectors tool outlook send_email
connectors check-tools conn.json --live
connectors call conn.json send_email -a to:='["a@b.com"]' -a subject=Hi --dry-run
```

Credentials are redacted from terminal output unless you pass `--show-secrets`.

## How it is put together

| Module | Main items | Role |
| --- | --- | --- |
| `manager` | `BaseConnectorManager`, `ConnectorManager`, `AsyncConnectorManager`, `ConnectOptions` | the public facade |
| `registry` | `ConnectorRegistry`, `ConnectorFilter` | loads the catalogue, resolves aliases, filters, pages, builds `AuthSchema` |
| `models` | `Connector`, `ConnectorPage`, `AuthField`, `AuthSchema`, `Connection`, `AuthMode` | the data model |
| `auth` | `AuthStrategy`, `Strategies`, `AuthContext` | one strategy per auth mode |
| `http` | `Request`, `HttpResponse`, `Transport`, `BlockingTransport`, `AsyncTransport`, `block_on` | the only I/O |
| `proxy` | `RequestBuilder`, `Call` | base urls, auth headers, templates, OAuth 1.0a/TBA, SigV4/ACS3 |
| `signing` | `sign_aws_sigv4`, `sign_acs3` | per-request cloud signatures |
| `verification` | `verify`, `VerificationResult` | proves credentials work |
| `validation` | `validate`, `Validated` | required, pattern, enum, format, `visible_when` |
| `interpolation` | `interpolate`, `make_url` | the `${...}` template engine |
| `credentials` | `parse_raw_credentials` | token responses and their many expiry formats |
| `tools` | `ToolRegistry`, `ToolExecutor`, `Tool`, `ToolPack`, `ToolReport`, `ScopeRules` | tools, permissions, argument binding |
| `data` | `DataSource` | bundled or on-disk data |

## Keeping Rust and Python identical

`scripts/check_rust_parity.py` builds every case with the Python package, has
the Rust CLI build the same case, and compares the results:

- every connector's auth schema and tool list;
- a request through every connector with a placeholder connection;
- every hand-authored tool, with synthetic arguments.

```bash
uv run python scripts/check_rust_parity.py          # ~35,000 cases
uv run python scripts/check_rust_parity.py --quick  # a sample
```

Header values that change on every build (nonces, timestamps and the signatures
over them) are compared by name only. CI runs the full check, so a change to
either library that makes them disagree fails the build.
