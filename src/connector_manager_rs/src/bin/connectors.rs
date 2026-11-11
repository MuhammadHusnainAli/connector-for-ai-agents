//! `connectors`: explore the catalogue, create connections and run tools.
//!
//! ```text
//! connectors list --search slack
//! connectors show affinity-v2
//! connectors connect affinity-v2 -c apiKey=... -o conn.json
//! connectors request conn.json GET /v2/persons
//! connectors tools outlook
//! connectors tool outlook send_email
//! connectors check-tools conn.json --live
//! connectors call conn.json send_email -a to:='["a@b.com"]' -a subject=Hi
//! ```
//!
//! The same commands as `python -m connector_manager`.

use std::io::{BufRead, Write};
use std::path::Path;
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use connector_manager::tools::SpecFormat;
use connector_manager::{
    AuthMode, Call, ConnectOptions, Connection, ConnectorFilter, ConnectorManager, ConnectorPage, DEFAULT_PAGE_SIZE, Error, ErrorKind,
};
use serde_json::{Map, Value, json};

const REDACTED: &str = "<redacted>";
const SECRET_WORDS: [&str; 17] = [
    "auth",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "hash",
    "key",
    "passphrase",
    "passwd",
    "password",
    "salt",
    "secret",
    "session",
    "sig",
    "signature",
    "token",
];
const PUBLIC_CREDENTIAL_KEYS: [&str; 7] = ["type", "expires_at", "expires_in", "token_type", "scope", "scopes", "created_at"];
const PUBLIC_KEYS: [&str; 5] = ["auth_mode", "authmode", "auth_type", "authtype", "token_type"];

#[derive(Parser)]
#[command(name = "connectors", version, about = "Explore 2,000+ API connectors, connect them, and run their tools.")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// List connectors
    List {
        #[arg(long)]
        search: Option<String>,
        #[arg(long)]
        category: Option<String>,
        #[arg(long)]
        auth_mode: Option<String>,
        #[arg(long)]
        supported_only: bool,
        /// Only connectors that connect without an external OAuth flow
        #[arg(long)]
        self_service_only: bool,
        #[arg(long, default_value_t = 1)]
        page: usize,
        #[arg(long, default_value_t = DEFAULT_PAGE_SIZE)]
        page_size: usize,
        /// Start at this item instead of a page number
        #[arg(long)]
        offset: Option<usize>,
        /// Page through the whole listing
        #[arg(long)]
        all: bool,
        #[arg(long)]
        json: bool,
    },
    /// Show a connector and everything it needs to authenticate
    Show {
        connector_id: String,
        #[arg(long)]
        json: bool,
    },
    /// Print a connector's SVG logo
    Icon {
        connector_id: String,
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Catalogue totals by auth mode and category
    Stats,
    /// Authenticate a connector and emit the connection
    Connect {
        connector_id: String,
        #[arg(short = 'c', long = "credential", value_name = "KEY=VALUE")]
        credential: Vec<String>,
        #[arg(short = 'x', long = "config", value_name = "KEY=VALUE")]
        config: Vec<String>,
        #[arg(short = 'i', long = "integration-config", value_name = "KEY=VALUE")]
        integration_config: Vec<String>,
        #[arg(long)]
        no_verify: bool,
        /// Write the connection JSON here (mode 0600)
        #[arg(short, long)]
        output: Option<String>,
        /// Print credentials instead of hiding them
        #[arg(long)]
        show_secrets: bool,
    },
    /// Re-run verification for a stored connection
    Verify {
        connection_file: String,
        #[arg(short, long)]
        output: Option<String>,
        #[arg(long)]
        show_secrets: bool,
    },
    /// Refresh a stored connection's token
    Refresh {
        connection_file: String,
        #[arg(short, long)]
        output: Option<String>,
        #[arg(long)]
        show_secrets: bool,
    },
    /// List the tools a connector has
    Tools {
        connector_id: String,
        #[arg(long)]
        search: Option<String>,
        #[arg(long)]
        category: Option<String>,
        /// Emit LLM tool definitions in this format (anthropic, openai, mcp)
        #[arg(long)]
        format: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// Show one tool: what it takes and what it returns
    Tool {
        connector_id: String,
        name: String,
        #[arg(long)]
        json: bool,
    },
    /// Which of a connector's tools a stored connection may call
    CheckTools {
        connection_file: String,
        /// Ask the provider which scopes the credential really holds
        #[arg(long)]
        live: bool,
        /// Judge against these scopes instead
        #[arg(long)]
        scope: Vec<String>,
        #[arg(long)]
        json: bool,
    },
    /// Run one of a connector's tools
    Call {
        connection_file: String,
        name: String,
        /// Tool argument; KEY:=<json> for lists, objects, numbers and booleans
        #[arg(short = 'a', long = "arg", value_name = "KEY=VALUE")]
        arg: Vec<String>,
        /// Print the prepared request only
        #[arg(long)]
        dry_run: bool,
        /// Call even when the recorded grant rules it out
        #[arg(long)]
        no_scope_check: bool,
        #[arg(long)]
        show_secrets: bool,
    },
    /// Make an authenticated API call
    Request {
        connection_file: String,
        method: String,
        endpoint: String,
        #[arg(short = 'q', long = "param", value_name = "KEY=VALUE")]
        param: Vec<String>,
        /// JSON request body
        #[arg(short = 'd', long)]
        data: Option<String>,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        show_secrets: bool,
    },
    /// Build cases from stdin (JSON lines) and print the results: the cross-language parity check.
    #[command(hide = true)]
    Parity,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let manager = match ConnectorManager::new() {
        Ok(m) => m,
        Err(e) => return fail(&e),
    };
    match run(&manager, cli.command) {
        Ok(code) => code,
        Err(e) => fail(&e),
    }
}

fn fail(err: &Error) -> ExitCode {
    eprintln!("{}", serde_json::to_string_pretty(&err.to_json()).unwrap_or_default());
    ExitCode::FAILURE
}

fn usage(message: String) -> Error {
    Error::new(ErrorKind::Validation, message)
}

fn words(key: &str) -> Vec<String> {
    let mut spaced = String::new();
    let chars: Vec<char> = key.chars().collect();
    for (i, c) in chars.iter().enumerate() {
        if i > 0 && c.is_ascii_uppercase() && (chars[i - 1].is_ascii_lowercase() || chars[i - 1].is_ascii_digit()) {
            spaced.push('_');
        }
        spaced.push(*c);
    }
    spaced.to_lowercase().split(|c: char| !c.is_ascii_alphanumeric()).filter(|w| !w.is_empty()).map(str::to_string).collect()
}

fn is_secret_key(key: &str) -> bool {
    !PUBLIC_KEYS.contains(&key.to_lowercase().as_str()) && words(key).iter().any(|w| SECRET_WORDS.contains(&w.as_str()))
}

fn hollow(v: &Value) -> bool {
    v.is_null() || v.as_object().is_some_and(Map::is_empty) || v.as_array().is_some_and(Vec::is_empty)
}

/// Copy `value` with every authenticating field replaced by `<redacted>`.
fn redact(value: &Value, in_credentials: bool) -> Value {
    match value {
        Value::Object(m) => Value::Object(
            m.iter()
                .map(|(k, v)| {
                    let out = if k == "credentials" && v.is_object() {
                        redact(v, true)
                    } else if (in_credentials && !PUBLIC_CREDENTIAL_KEYS.contains(&k.as_str())) || is_secret_key(k) {
                        if hollow(v) { v.clone() } else { json!(REDACTED) }
                    } else {
                        redact(v, in_credentials)
                    };
                    (k.clone(), out)
                })
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.iter().map(|v| redact(v, in_credentials)).collect()),
        other => other.clone(),
    }
}

fn dump(value: &Value, redacted: bool) {
    let shown = if redacted { redact(value, false) } else { value.clone() };
    println!("{}", serde_json::to_string_pretty(&shown).unwrap_or_default());
}

fn kv(pairs: &[String]) -> Result<Value, Error> {
    let mut out = Map::new();
    for pair in pairs {
        let (k, v) = pair.split_once('=').ok_or_else(|| usage(format!("expected key=value, got '{pair}'")))?;
        out.insert(k.trim().into(), json!(v));
    }
    Ok(Value::Object(out))
}

/// `-a subject=Hello` is a string; `-a to:='["a@b.com"]'` is parsed as JSON.
fn tool_args(pairs: &[String]) -> Result<Value, Error> {
    let mut out = Map::new();
    for pair in pairs {
        if let Some((k, v)) = pair.split_once(":=") {
            let parsed: Value = serde_json::from_str(v).map_err(|e| usage(format!("invalid JSON for '{}': {e}", k.trim())))?;
            out.insert(k.trim().into(), parsed);
            continue;
        }
        let (k, v) = pair.split_once('=').ok_or_else(|| usage(format!("expected key=value or key:=<json>, got '{pair}'")))?;
        out.insert(k.trim().into(), json!(v));
    }
    Ok(Value::Object(out))
}

fn load_connection(path: &str) -> Result<Connection, Error> {
    let text = std::fs::read_to_string(path).map_err(|e| usage(format!("cannot read {path}: {e}")))?;
    Connection::from_json(serde_json::from_str(&text)?)
}

fn write_private(path: &Path, payload: &Value) -> Result<(), Error> {
    let text = serde_json::to_string_pretty(payload)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(path)
            .map_err(|e| usage(format!("cannot write {}: {e}", path.display())))?;
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
        file.write_all(text.as_bytes()).map_err(|e| usage(e.to_string()))?;
    }
    #[cfg(not(unix))]
    std::fs::write(path, text).map_err(|e| usage(e.to_string()))?;
    Ok(())
}

fn save_connection(connection: &Connection, output: Option<&str>, show_secrets: bool) -> Result<(), Error> {
    let payload = connection.to_json();
    if let Some(path) = output {
        write_private(Path::new(path), &payload)?;
        eprintln!("connection written to {path} (holds credentials; mode 0600)");
        return Ok(());
    }
    dump(&payload, !show_secrets);
    if !show_secrets {
        eprintln!("credentials hidden -- write the usable connection with -o FILE, or pass --show-secrets to print them");
    }
    Ok(())
}

fn page_footer(page: &ConnectorPage) -> String {
    if page.count() == 0 {
        return "no connectors matched".into();
    }
    let mut parts = vec![
        format!("showing {}-{} of {}", page.first_index(), page.last_index(), page.total),
        format!("page {}/{}", page.page(), page.pages()),
    ];
    if let Some(next) = page.next_offset() {
        parts.push(format!("next: --offset {next}"));
    }
    format!("\n{}", parts.join(" · "))
}

fn run(manager: &ConnectorManager, command: Command) -> Result<ExitCode, Error> {
    match command {
        Command::List { search, category, auth_mode, supported_only, self_service_only, page, page_size, offset, all, json } => {
            let filter = ConnectorFilter {
                search,
                category,
                auth_mode: auth_mode.map(|m| AuthMode::parse(Some(&m.to_uppercase()))),
                supported_only,
                self_service_only,
            };
            let pages = if all {
                manager.connector_pages(page_size, &filter)?
            } else {
                vec![manager.paginate_connectors(page, page_size, offset, &filter)?]
            };
            for page in pages {
                if json {
                    dump(&page.to_json(), false);
                    continue;
                }
                for c in &page.items {
                    let flag = if c.self_service() {
                        ""
                    } else if c.requires_external_oauth() {
                        "  (needs external OAuth)"
                    } else {
                        "  (auth mode not implemented)"
                    };
                    println!("{:<40} {:<14} {}{flag}", c.id, c.auth_mode.as_str(), c.display_name);
                }
                eprintln!("{}", page_footer(&page));
            }
        }
        Command::Show { connector_id, json } => {
            let connector = manager.get_connector(&connector_id)?;
            let schema = manager.get_auth_schema(&connector_id)?;
            if json {
                dump(&json!({"connector": connector.to_json(), "auth": schema.to_json()}), false);
                return Ok(ExitCode::SUCCESS);
            }
            println!("{}  [{}]", connector.display_name, connector.id);
            println!("  auth mode   : {}", schema.auth_mode);
            println!("  categories  : {}", if connector.categories.is_empty() { "-".into() } else { connector.categories.join(", ") });
            println!("  base url    : {}", connector.base_url.as_deref().unwrap_or("-"));
            if schema.requires_external_oauth {
                println!("  note        : run the OAuth flow in your own auth layer, then import the tokens");
            }
            if let Some(reason) = &schema.unsupported_reason {
                println!("  unsupported : {reason}");
            }
            println!("  fields:");
            for f in schema.user_fields() {
                let marks = [if f.required { "required" } else { "optional" }, if f.secret { "secret" } else { "" }]
                    .into_iter()
                    .filter(|m| !m.is_empty())
                    .collect::<Vec<_>>()
                    .join(",");
                println!("    - [{}] {} ({marks}): {}", f.group.as_str(), f.name, f.title);
                if !f.description.is_empty() {
                    println!("        {}", f.description);
                }
                if !f.r#enum.is_empty() {
                    println!("        one of: {}", f.r#enum.join(", "));
                }
                if let Some(e) = f.example.as_deref().filter(|e| !e.is_empty()) {
                    println!("        e.g. {e}");
                }
            }
        }
        Command::Icon { connector_id, output } => {
            let Some(icon) = manager.get_icon(&connector_id) else {
                eprintln!("no icon bundled for '{connector_id}'");
                return Ok(ExitCode::FAILURE);
            };
            match output {
                Some(path) => std::fs::write(&path, icon).map_err(|e| usage(e.to_string()))?,
                None => println!("{icon}"),
            }
        }
        Command::Stats => {
            let modes: Map<String, Value> = manager.auth_modes().into_iter().map(|(m, n)| (m.as_str().to_string(), json!(n))).collect();
            dump(
                &json!({"connectors": manager.len(), "auth_modes": modes, "categories": manager.categories(), "tools": manager.tool_stats()}),
                false,
            );
        }
        Command::Connect { connector_id, credential, config, integration_config, no_verify, output, show_secrets } => {
            let options = ConnectOptions::new()
                .credentials(kv(&credential)?)
                .connection_config(kv(&config)?)
                .integration_config(kv(&integration_config)?)
                .verify(!no_verify);
            let connection = manager.connect(&connector_id, options)?;
            save_connection(&connection, output.as_deref(), show_secrets)?;
        }
        Command::Verify { connection_file, output, show_secrets } => {
            let mut connection = load_connection(&connection_file)?;
            let result = manager.verify(&connection)?;
            connection.verified = result.verified;
            connection.metadata.insert("verification".into(), result.to_json());
            save_connection(&connection, output.as_deref(), show_secrets)?;
        }
        Command::Refresh { connection_file, output, show_secrets } => {
            let mut connection = load_connection(&connection_file)?;
            manager.refresh(&mut connection)?;
            save_connection(&connection, output.as_deref(), show_secrets)?;
        }
        Command::Tools { connector_id, search, category, format, json } => {
            let pack = manager.tool_pack(&connector_id)?;
            let needle = search.unwrap_or_default().trim().to_lowercase();
            let listing: Vec<_> = pack
                .tools
                .iter()
                .filter(|t| {
                    needle.is_empty() || format!("{} {} {} {}", t.name, t.title, t.description, t.category).to_lowercase().contains(&needle)
                })
                .filter(|t| category.as_ref().is_none_or(|c| &t.category == c))
                .collect();
            if let Some(format) = format {
                let format: SpecFormat = format.parse()?;
                dump(&Value::Array(listing.iter().map(|t| t.spec(format, false)).collect()), false);
                return Ok(ExitCode::SUCCESS);
            }
            if json {
                let mut v = pack.to_json(true);
                v["tools"] = Value::Array(listing.iter().map(|t| t.to_json()).collect());
                dump(&v, false);
                return Ok(ExitCode::SUCCESS);
            }
            println!("{}  [{}]  {} tool(s)", pack.display_name, pack.connector_id, listing.len());
            if pack.generated {
                println!("  note        : generated from this connector's catalogue entry; no hand-authored tool pack yet");
            }
            if !pack.applies_to.is_empty() {
                println!("  also serves : {}", pack.applies_to.join(", "));
            }
            if let Some(docs) = &pack.docs_url {
                println!("  docs        : {docs}");
            }
            let scopes = pack.scopes();
            println!("  scopes      : {}", if scopes.is_empty() { "-".into() } else { scopes.join(" ") });
            let mut sorted = listing.clone();
            sorted.sort_by(|a, b| (&a.category, &a.name).cmp(&(&b.category, &b.name)));
            let mut current: Option<&str> = None;
            for t in sorted {
                if current != Some(t.category.as_str()) {
                    current = Some(t.category.as_str());
                    println!("\n  [{}]", t.category);
                }
                let marks = [if t.read_only { "read-only" } else { "" }, if t.destructive { "destructive" } else { "" }]
                    .into_iter()
                    .filter(|m| !m.is_empty())
                    .collect::<Vec<_>>()
                    .join(",");
                let scopes = if !t.scopes.is_empty() {
                    t.scopes.join(" ")
                } else if !t.scopes_any.is_empty() {
                    t.scopes_any.join(" | ")
                } else {
                    "-".into()
                };
                println!("  {:<38} {:<7} {scopes:<45} {marks}", t.name, t.request.method);
            }
        }
        Command::Tool { connector_id, name, json } => {
            let t = manager.get_tool(&connector_id, &name)?;
            if json {
                dump(&t.to_json(), false);
                return Ok(ExitCode::SUCCESS);
            }
            println!("{}  [{}]", t.title, t.qualified_name());
            println!("  {}", t.description);
            println!("  call        : {} {}", t.request.method, t.request.path);
            println!("  category    : {}", t.category);
            println!("  scopes      : {}", if t.scopes.is_empty() { "-".into() } else { t.scopes.join(" ") });
            if !t.scopes_any.is_empty() {
                println!("  any one of  : {}", t.scopes_any.join(" | "));
            }
            println!("  read-only   : {}    destructive: {}", t.read_only, t.destructive);
            if !t.notes.is_empty() {
                println!("  note        : {}", t.notes);
            }
            println!("  arguments:");
            for p in &t.input {
                let default = p.default.as_ref().map(|d| format!(",default={d}")).unwrap_or_default();
                println!("    - {} ({}, {}{default})", p.name, p.param_type, if p.required { "required" } else { "optional" });
                println!("        {}", p.description);
                if !p.r#enum.is_empty() {
                    println!(
                        "        one of: {}",
                        p.r#enum
                            .iter()
                            .map(|e| e.as_str().map(str::to_string).unwrap_or_else(|| e.to_string()))
                            .collect::<Vec<_>>()
                            .join(", ")
                    );
                }
                if let Some(e) = &p.example {
                    println!("        e.g. {}", e.as_str().map(str::to_string).unwrap_or_else(|| e.to_string()));
                }
            }
            println!("  returns     : {}", t.output.description);
        }
        Command::CheckTools { connection_file, live, scope, json } => {
            let connection = load_connection(&connection_file)?;
            let report = if !scope.is_empty() {
                manager.check_tools(&connection, Some(scope))?
            } else if live {
                manager.check_tools_live(&connection)?
            } else {
                manager.check_tools(&connection, None)?
            };
            if json {
                dump(&report.to_json(), false);
                return Ok(ExitCode::SUCCESS);
            }
            println!("{}", report.summary());
            for s in &report.statuses {
                let mark = match s.availability.as_str() {
                    "enabled" => "+",
                    "disabled" => "-",
                    _ => "?",
                };
                let detail =
                    if s.missing_scopes.is_empty() { s.tool.title.clone() } else { format!("needs {}", s.missing_scopes.join(", ")) };
                println!(" {mark} {:<38} {detail}", s.tool.name);
            }
            let missing = report.missing_scopes();
            if !missing.is_empty() {
                println!("\nscopes that would unlock more: {}", missing.join(" "));
            }
        }
        Command::Call { connection_file, name, arg, dry_run, no_scope_check, show_secrets } => {
            let mut connection = load_connection(&connection_file)?;
            let arguments = tool_args(&arg)?;
            if dry_run {
                let request = manager.prepare_tool_request(&connection, &name, arguments)?;
                let mut v = request.to_json();
                v["json_body"] = request.json_body.clone().unwrap_or(Value::Null);
                dump(&v, !show_secrets);
                return Ok(ExitCode::SUCCESS);
            }
            let result = manager.call_tool_with_options(&mut connection, &name, arguments, !no_scope_check, true)?;
            dump(&result.to_json(), false);
            if !result.ok {
                return Ok(ExitCode::FAILURE);
            }
        }
        Command::Request { connection_file, method, endpoint, param, data, dry_run, show_secrets } => {
            let mut connection = load_connection(&connection_file)?;
            let mut call = Call::new(&method, endpoint);
            for p in &param {
                let (k, v) = p.split_once('=').ok_or_else(|| usage(format!("expected key=value, got '{p}'")))?;
                call.params.insert(k.trim().into(), v.into());
            }
            if let Some(d) = data {
                call.json_body = Some(serde_json::from_str(&d)?);
            }
            if dry_run {
                dump(&manager.prepare_request(&connection, call)?.to_json(), !show_secrets);
                return Ok(ExitCode::SUCCESS);
            }
            let response = manager.request(&mut connection, call)?;
            dump(&json!({"status": response.status, "url": response.url, "body": response.body()}), false);
            if !response.ok() {
                return Ok(ExitCode::FAILURE);
            }
        }
        Command::Parity => parity(manager)?,
    }
    Ok(ExitCode::SUCCESS)
}

/// Read cases as JSON lines on stdin, write one result per line on stdout.
///
/// Cases: `{"kind": "schema", "connector_id"}`, `{"kind": "tools", "connector_id"}`,
/// `{"kind": "request", "connection", "method", "endpoint"}`,
/// `{"kind": "tool", "connection", "tool", "arguments"}`.
fn parity(manager: &ConnectorManager) -> Result<(), Error> {
    let stdin = std::io::stdin();
    let mut out = std::io::BufWriter::new(std::io::stdout());
    for line in stdin.lock().lines() {
        let line = line.map_err(|e| usage(e.to_string()))?;
        if line.trim().is_empty() {
            continue;
        }
        let case: Value = serde_json::from_str(&line)?;
        let result = (|| -> Result<Value, Error> {
            let id = case["connector_id"].as_str().unwrap_or_default();
            Ok(match case["kind"].as_str().unwrap_or_default() {
                "schema" => manager.describe_auth(id)?,
                "tools" => json!(manager.list_tools(id)?.iter().map(|t| t.name.clone()).collect::<Vec<_>>()),
                "request" => {
                    let connection = Connection::from_json(case["connection"].clone())?;
                    let request = manager.prepare_request(
                        &connection,
                        Call::new(case["method"].as_str().unwrap_or("GET"), case["endpoint"].as_str().unwrap_or("")),
                    )?;
                    request_json(&request)
                }
                "tool" => {
                    let connection = Connection::from_json(case["connection"].clone())?;
                    request_json(&manager.prepare_tool_request(
                        &connection,
                        case["tool"].as_str().unwrap_or(""),
                        case["arguments"].clone(),
                    )?)
                }
                other => return Err(usage(format!("unknown case kind '{other}'"))),
            })
        })();
        let row = match result {
            Ok(v) => json!({"ok": v}),
            Err(e) => json!({"error": e.kind.name(), "message": e.message}),
        };
        writeln!(out, "{row}").map_err(|e| usage(e.to_string()))?;
    }
    Ok(())
}

fn request_json(r: &connector_manager::Request) -> Value {
    json!({
        "method": r.method, "url": r.url, "headers": r.headers, "params": r.params,
        "json_body": r.json_body, "content": r.content.as_ref().map(|c| String::from_utf8_lossy(c).into_owned()),
    })
}
