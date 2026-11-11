//! Turning a tool plus arguments into a real, authenticated request, with no I/O:
//! validate the arguments, bind them into the request templates, parse the reply.

use std::collections::BTreeMap;
use std::sync::Arc;

use base64::Engine;
use base64::engine::general_purpose::{STANDARD as B64, URL_SAFE};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use regex::Captures;
use serde_json::{Map, Value, json};

use crate::error::{Error, ErrorKind, Result};
use crate::http::{HttpResponse, Request};
use crate::interpolation::{PLACEHOLDER_RE, extract_value_by_path, interpolate};
use crate::models::Connection;
use crate::proxy::{Call, RequestBuilder};
use crate::validation::pattern_matches;

use super::models::{PARAM_TYPES, Tool, ToolParameter, ToolResult};

/// Prepares one tool call for one connection.
#[derive(Debug, Clone)]
pub struct ToolExecutor {
    pub provider: Arc<Map<String, Value>>,
    pub tool: Tool,
    pub connection: Connection,
}

impl ToolExecutor {
    pub fn new(provider: Arc<Map<String, Value>>, tool: Tool, connection: Connection) -> Self {
        Self { provider, tool, connection }
    }

    /// Check and normalise arguments, filling defaults. Every problem is reported at once.
    pub fn validate(&self, arguments: &Map<String, Value>) -> Result<Map<String, Value>> {
        let known: Vec<&str> = self.tool.input.iter().map(|p| p.name.as_str()).collect();
        let mut errors: BTreeMap<String, String> = BTreeMap::new();
        let mut out = Map::new();
        let mut sorted_known = known.clone();
        sorted_known.sort();
        for extra in arguments.keys().filter(|k| !known.contains(&k.as_str())) {
            let accepts = if sorted_known.is_empty() { "(none)".to_string() } else { sorted_known.join(", ") };
            errors.insert(extra.clone(), format!("unknown argument; {} accepts: {accepts}", self.tool.name));
        }
        for param in &self.tool.input {
            let raw = arguments.get(&param.name).filter(|v| !v.is_null() && v.as_str() != Some(""));
            let Some(raw) = raw else {
                if let Some(default) = &param.default {
                    out.insert(param.name.clone(), default.clone());
                } else if param.required {
                    errors.insert(param.name.clone(), format!("{} is required", param.label()));
                }
                continue;
            };
            match coerce(param, raw).and_then(|v| check(param, &v).map_or(Ok(v), Err)) {
                Ok(v) => {
                    out.insert(param.name.clone(), v);
                }
                Err(problem) => {
                    errors.insert(param.name.clone(), problem);
                }
            }
        }
        if !errors.is_empty() {
            let listed = errors.iter().map(|(k, v)| format!("{k} ({v})")).collect::<Vec<_>>().join(", ");
            let argument_errors: Map<String, Value> = errors.into_iter().map(|(k, v)| (k, Value::String(v))).collect();
            return Err(Error::new(
                ErrorKind::ToolValidation,
                format!("Invalid arguments for tool '{}': {listed}", self.tool.qualified_name()),
            )
            .with("argument_errors", Value::Object(argument_errors)));
        }
        Ok(out)
    }

    /// The fully authenticated request this call would send.
    pub fn build(&self, arguments: &Map<String, Value>) -> Result<Request> {
        self.build_with(arguments, true)
    }

    pub fn build_with(&self, arguments: &Map<String, Value>, validate: bool) -> Result<Request> {
        let values = if validate { self.validate(arguments)? } else { arguments.clone() };
        let spec = &self.tool.request;
        let path = bind_path(&spec.path, &values);
        // An absent container is an absent query string or body, not a dropped request.
        let query = match bind(&spec.query, &values) {
            Some(Value::Object(q)) => q,
            _ => Map::new(),
        };
        let mut headers: BTreeMap<String, String> = match bind(&Value::Object(spec.headers.clone()), &values) {
            Some(Value::Object(h)) => h.iter().map(|(k, v)| (k.clone(), as_query_value(v))).collect(),
            _ => BTreeMap::new(),
        };
        let mut body = spec.body.as_ref().and_then(|b| bind(b, &values));
        let mut content = spec.content.as_ref().and_then(|c| bind(c, &values));
        if body.is_some() && spec.encoding == "form" {
            // Stripe and Twilio take form bodies, nested values in brackets.
            let pairs = form_pairs(body.as_ref().unwrap(), "");
            content = Some(Value::String(url::form_urlencoded::Serializer::new(String::new()).extend_pairs(pairs).finish()));
            if !headers.keys().any(|k| k.eq_ignore_ascii_case("content-type")) {
                headers.insert("content-type".into(), "application/x-www-form-urlencoded".into());
            }
            body = None;
        }
        let builder = self.builder(spec.base_url_override.as_deref());
        builder.build(Call {
            method: spec.method.clone(),
            endpoint: path,
            headers,
            params: query.iter().map(|(k, v)| (k.clone(), as_query_value(v))).collect(),
            json_body: body,
            content: content.and_then(|c| c.as_str().map(|s| s.as_bytes().to_vec())),
            payload: None,
        })
    }

    fn builder(&self, base_url_override: Option<&str>) -> RequestBuilder {
        let Some(base) = base_url_override.filter(|b| !b.is_empty()) else {
            return RequestBuilder::new(self.provider.clone(), self.connection.clone());
        };
        // An override means it, so the connection's own base_url must not shadow it,
        // unless the override is built from it.
        let keep = base.contains("connectionConfig.base_url");
        let mut connection = self.connection.clone();
        if !keep {
            connection.connection_config.remove("base_url");
        }
        RequestBuilder::new(self.provider.clone(), connection).with_base_url(base)
    }

    /// The provider's answer as a [`ToolResult`].
    pub fn parse(&self, response: &HttpResponse) -> ToolResult {
        let body = response.body();
        if !response.ok() {
            return ToolResult {
                tool: self.tool.name.clone(),
                connector_id: self.tool.connector_id.clone(),
                ok: false,
                status: Some(response.status),
                error: Some(error_message(response.status, &body)),
                data: body,
                url: response.url.clone(),
            };
        }
        let mut data = body.clone();
        if let Some(path) = self.tool.output.response_path.as_deref().filter(|p| !p.is_empty()) {
            if body.is_object() || body.is_array() {
                if let Some(extracted) = extract_value_by_path(&body, path) {
                    data = extracted.clone();
                }
            }
        }
        ToolResult {
            tool: self.tool.name.clone(),
            connector_id: self.tool.connector_id.clone(),
            ok: true,
            status: Some(response.status),
            data,
            error: None,
            url: response.url.clone(),
        }
    }
}

fn python_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Null => "None".into(),
        other => other.to_string(),
    }
}

/// Fit a raw argument to the declared type, forgivingly (`"5"` is a fine integer).
fn coerce(param: &ToolParameter, raw: &Value) -> std::result::Result<Value, String> {
    let label = param.label();
    if !PARAM_TYPES.contains(&param.param_type.as_str()) {
        return Err(format!("{} declares unsupported type '{}'", param.name, param.param_type));
    }
    match param.param_type.as_str() {
        "string" => match raw {
            Value::Object(_) | Value::Array(_) => Err(format!("{label} must be a string")),
            other => Ok(Value::String(python_str(other))),
        },
        "boolean" => match raw {
            Value::Bool(b) => Ok(Value::Bool(*b)),
            other => match python_str(other).trim().to_lowercase().as_str() {
                "true" | "1" | "yes" | "on" => Ok(Value::Bool(true)),
                "false" | "0" | "no" | "off" => Ok(Value::Bool(false)),
                _ => Err(format!("{label} must be true or false")),
            },
        },
        "integer" => match raw {
            Value::Number(n) => n
                .as_i64()
                .map(Value::from)
                .or_else(|| n.as_f64().map(|f| Value::from(f.trunc() as i64)))
                .ok_or_else(|| format!("{label} must be an integer")),
            Value::String(s) => s.trim().parse::<i64>().map(Value::from).map_err(|_| format!("{label} must be an integer")),
            _ => Err(format!("{label} must be an integer")),
        },
        "number" => match raw {
            Value::Number(n) => n.as_f64().map(|f| json!(f)).ok_or_else(|| format!("{label} must be a number")),
            Value::String(s) => s.trim().parse::<f64>().map(|f| json!(f)).map_err(|_| format!("{label} must be a number")),
            _ => Err(format!("{label} must be a number")),
        },
        "array" => match raw {
            Value::Array(a) => Ok(Value::Array(a.clone())),
            // A single value where a list is wanted is a common model slip.
            Value::String(_) | Value::Number(_) | Value::Bool(_) => Ok(Value::Array(vec![raw.clone()])),
            _ => Err(format!("{label} must be an array")),
        },
        "object" => match raw {
            Value::Object(_) => Ok(raw.clone()),
            _ => Err(format!("{label} must be an object")),
        },
        _ => Ok(raw.clone()),
    }
}

fn loosely_equal(a: &Value, b: &Value) -> bool {
    match (a.as_f64(), b.as_f64()) {
        (Some(x), Some(y)) if !a.is_boolean() && !b.is_boolean() => x == y,
        _ => a == b,
    }
}

fn check(param: &ToolParameter, value: &Value) -> Option<String> {
    let label = param.label();
    if !param.r#enum.is_empty() && !param.r#enum.iter().any(|e| loosely_equal(e, value)) {
        let options = param.r#enum.iter().map(python_str).collect::<Vec<_>>().join(", ");
        return Some(format!("{label} must be one of: {options}"));
    }
    match value {
        Value::String(s) => {
            if let Some(p) = &param.pattern {
                if !pattern_matches(p, s) {
                    return Some(format!("{label} does not match the expected format"));
                }
            }
            let len = s.chars().count();
            if param.min_length.is_some_and(|m| len < m) {
                return Some(format!("{label} must be at least {} characters", param.min_length.unwrap()));
            }
            if param.max_length.is_some_and(|m| len > m) {
                return Some(format!("{label} must be at most {} characters", param.max_length.unwrap()));
            }
        }
        Value::Number(n) => {
            let f = n.as_f64().unwrap_or(0.0);
            if param.minimum.is_some_and(|m| f < m) {
                return Some(format!(
                    "{label} must be >= {}",
                    crate::interpolation::scalar_text(&json!(param.minimum.unwrap())).unwrap_or_default()
                ));
            }
            if param.maximum.is_some_and(|m| f > m) {
                return Some(format!(
                    "{label} must be <= {}",
                    crate::interpolation::scalar_text(&json!(param.maximum.unwrap())).unwrap_or_default()
                ));
            }
        }
        Value::Array(a) => {
            if param.min_length.is_some_and(|m| a.len() < m) {
                return Some(format!("{label} must have at least {} items", param.min_length.unwrap()));
            }
            if param.max_length.is_some_and(|m| a.len() > m) {
                return Some(format!("{label} must have at most {} items", param.max_length.unwrap()));
            }
        }
        _ => {}
    }
    None
}

/// Every `${argument}` a template refers to (the first segment of a dotted name).
pub fn template_arguments(value: &Value) -> std::collections::BTreeSet<String> {
    let mut names = std::collections::BTreeSet::new();
    match value {
        Value::String(s) => {
            for c in PLACEHOLDER_RE.captures_iter(s) {
                names.insert(c[1].split('.').next().unwrap_or("").to_string());
            }
        }
        Value::Object(m) => {
            if m.len() == 1 && (m.contains_key("$map") || m.contains_key("$keyed")) {
                if let Some(Value::Object(spec)) = m.values().next() {
                    names.extend(template_arguments(spec.get("source").unwrap_or(&Value::Null)));
                    for key in ["template", "key", "value"] {
                        names.extend(
                            template_arguments(spec.get(key).unwrap_or(&Value::Null)).into_iter().filter(|n| n != "item" && n != "index"),
                        );
                    }
                    return names;
                }
            }
            for v in m.values() {
                names.extend(template_arguments(v));
            }
        }
        Value::Array(a) => {
            for v in a {
                names.extend(template_arguments(v));
            }
        }
        _ => {}
    }
    names
}

/// Substitute arguments into a template, keeping their types. `None` means the
/// slot's argument was not supplied, so the containing key is dropped.
///
/// `$when`, `$map`, `$keyed` and `$mime` nodes behave exactly as in the Python package.
pub fn bind(template: &Value, values: &Map<String, Value>) -> Option<Value> {
    match template {
        Value::String(s) => bind_string(s, values),
        Value::Object(m) => {
            if m.len() == 1 {
                if let Some(spec) = m.get("$map") {
                    return bind_map(spec, values);
                }
                if let Some(spec) = m.get("$mime") {
                    return bind_mime(spec, values);
                }
                if let Some(spec) = m.get("$keyed") {
                    return bind_keyed(spec, values);
                }
            }
            if let Some(when) = m.get("$when") {
                bind(when, values)?;
            }
            let mut out = Map::new();
            let mut wanted = 0;
            for (k, v) in m {
                if k == "$when" {
                    continue;
                }
                wanted += 1;
                if let Some(bound) = bind(v, values) {
                    out.insert(k.clone(), bound);
                }
            }
            // Every key dropped: sending `{}` reads as "clear this" to most providers.
            if wanted > 0 && out.is_empty() { None } else { Some(Value::Object(out)) }
        }
        Value::Array(a) => {
            let kept: Vec<Value> = a.iter().filter_map(|v| bind(v, values)).collect();
            if kept.is_empty() && !a.is_empty() { None } else { Some(Value::Array(kept)) }
        }
        other => Some(other.clone()),
    }
}

fn lookup(key: &str, values: &Map<String, Value>) -> Option<Value> {
    if let Some(v) = values.get(key) {
        return (!v.is_null()).then(|| v.clone());
    }
    extract_value_by_path(&Value::Object(values.clone()), key).filter(|v| !v.is_null()).cloned()
}

fn whole_placeholder(template: &str) -> Option<String> {
    let t = template.trim();
    PLACEHOLDER_RE.captures(t).filter(|c| c.get(0).unwrap().as_str() == t).map(|c| c[1].to_string())
}

fn bind_string(template: &str, values: &Map<String, Value>) -> Option<Value> {
    if !template.contains("${") {
        return Some(Value::String(template.into()));
    }
    if let Some(key) = whole_placeholder(template) {
        return lookup(&key, values);
    }
    let resolved = interpolate(template, values);
    (!PLACEHOLDER_RE.is_match(&resolved)).then_some(Value::String(resolved))
}

const SEGMENT: &percent_encoding::AsciiSet = &NON_ALPHANUMERIC.remove(b'-').remove(b'_').remove(b'.').remove(b'~');

/// Bind a url path, percent-encoding whatever goes into a segment. A template
/// that is only a placeholder holds a whole path, whose slashes are kept.
pub fn bind_path(template: &str, values: &Map<String, Value>) -> String {
    if !template.contains("${") {
        return template.to_string();
    }
    if let Some(key) = whole_placeholder(template) {
        let Some(value) = lookup(&key, values) else { return template.to_string() };
        let path = python_str(&value);
        if path.starts_with("http://") || path.starts_with("https://") {
            return path;
        }
        return if path.starts_with('/') { path } else { format!("/{path}") };
    }
    PLACEHOLDER_RE
        .replace_all(template, |c: &Captures| match lookup(&c[1], values) {
            Some(v) => utf8_percent_encode(&python_str(&v), SEGMENT).to_string(),
            None => c[0].to_string(),
        })
        .into_owned()
}

fn scope(values: &Map<String, Value>, item: &Value, index: usize) -> Map<String, Value> {
    let mut s = values.clone();
    s.insert("item".into(), item.clone());
    s.insert("index".into(), json!(index));
    s
}

fn source_list(spec: &Map<String, Value>, values: &Map<String, Value>) -> Option<Vec<Value>> {
    match bind(spec.get("source")?, values)? {
        Value::Array(a) => Some(a),
        Value::Null => None,
        other => Some(vec![other]),
    }
}

fn bind_map(spec: &Value, values: &Map<String, Value>) -> Option<Value> {
    let spec = spec.as_object()?;
    let template = spec.get("template").cloned().unwrap_or(Value::Null);
    let source = source_list(spec, values)?;
    Some(Value::Array(source.iter().enumerate().filter_map(|(i, item)| bind(&template, &scope(values, item, i))).collect()))
}

fn bind_keyed(spec: &Value, values: &Map<String, Value>) -> Option<Value> {
    let spec = spec.as_object()?;
    let source = source_list(spec, values)?;
    let key_template = spec.get("key").cloned().unwrap_or(Value::String("${item}".into()));
    let value_template = spec.get("value").cloned().unwrap_or(Value::Null);
    let mut out = Map::new();
    for (i, item) in source.iter().enumerate() {
        let s = scope(values, item, i);
        if let (Some(k), Some(v)) = (bind(&key_template, &s), bind(&value_template, &s)) {
            out.insert(python_str(&k), v);
        }
    }
    (!out.is_empty()).then_some(Value::Object(out))
}

fn addresses(v: Option<&Value>) -> Vec<String> {
    match v {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::String(s)) => vec![s.clone()],
        Some(Value::Array(a)) => a.iter().map(python_str).collect(),
        Some(other) => vec![python_str(other)],
    }
}

/// Assemble a Gmail raw message from ordinary to/subject/body/attachments arguments.
fn bind_mime(spec: &Value, values: &Map<String, Value>) -> Option<Value> {
    let spec = spec.as_object()?;
    let fields: Map<String, Value> =
        spec.iter().filter_map(|(k, v)| bind(v, values).filter(|b| !b.is_null()).map(|b| (k.clone(), b))).collect();
    let present = |k: &str| fields.get(k).is_some_and(|v| !(v.as_str() == Some("") || v.as_array().is_some_and(Vec::is_empty)));
    if !present("to") && !present("body") {
        return None;
    }
    let text = |k: &str| fields.get(k).map(python_str);
    Some(Value::String(build_mime_message(&MimeMessage {
        to: addresses(fields.get("to")),
        subject: text("subject").unwrap_or_default(),
        body: text("body").unwrap_or_default(),
        body_type: text("body_type").unwrap_or_else(|| "html".into()),
        cc: addresses(fields.get("cc")),
        bcc: addresses(fields.get("bcc")),
        from_address: text("from_address"),
        reply_to: text("reply_to"),
        in_reply_to: text("in_reply_to"),
        attachments: fields.get("attachments").and_then(Value::as_array).cloned().unwrap_or_default(),
    })))
}

/// The pieces of an email, for [`build_mime_message`].
#[derive(Debug, Clone, Default)]
pub struct MimeMessage {
    pub to: Vec<String>,
    pub subject: String,
    pub body: String,
    /// `html` (default) or `text`.
    pub body_type: String,
    pub cc: Vec<String>,
    pub bcc: Vec<String>,
    pub from_address: Option<String>,
    pub reply_to: Option<String>,
    pub in_reply_to: Option<String>,
    /// `{"name", "content_bytes": <base64>, "content_type"}`, as the Graph tools take.
    pub attachments: Vec<Value>,
}

fn header_text(value: &str) -> String {
    if value.is_ascii() { value.to_string() } else { format!("=?utf-8?b?{}?=", B64.encode(value)) }
}

fn wrap76(data: &[u8]) -> String {
    let encoded = B64.encode(data);
    encoded.as_bytes().chunks(76).map(|c| std::str::from_utf8(c).unwrap()).collect::<Vec<_>>().join("\r\n")
}

/// An RFC 2822 message, base64url-encoded the way Gmail's API wants it.
pub fn build_mime_message(m: &MimeMessage) -> String {
    let boundary = |tag: &str| format!("=_{tag}_{}", uuid::Uuid::new_v4().simple());
    let mut head = vec![format!("To: {}", m.to.join(", ")), format!("Subject: {}", header_text(&m.subject))];
    if !m.cc.is_empty() {
        head.push(format!("Cc: {}", m.cc.join(", ")));
    }
    if !m.bcc.is_empty() {
        head.push(format!("Bcc: {}", m.bcc.join(", ")));
    }
    if let Some(f) = m.from_address.as_deref().filter(|s| !s.is_empty()) {
        head.push(format!("From: {f}"));
    }
    if let Some(r) = m.reply_to.as_deref().filter(|s| !s.is_empty()) {
        head.push(format!("Reply-To: {r}"));
    }
    if let Some(r) = m.in_reply_to.as_deref().filter(|s| !s.is_empty()) {
        head.push(format!("In-Reply-To: {r}"));
        head.push(format!("References: {r}"));
    }
    head.push("MIME-Version: 1.0".into());

    let text_part = |ctype: &str, text: &str| {
        format!("Content-Type: {ctype}; charset=\"utf-8\"\r\nContent-Transfer-Encoding: base64\r\n\r\n{}\r\n", wrap76(text.as_bytes()))
    };
    let body_part = if matches!(m.body_type.to_lowercase().as_str(), "html" | "text/html") {
        let b = boundary("alt");
        format!(
            "Content-Type: multipart/alternative; boundary=\"{b}\"\r\n\r\n--{b}\r\n{}--{b}\r\n{}--{b}--\r\n",
            text_part("text/plain", "This message needs an HTML-capable reader."),
            text_part("text/html", &m.body)
        )
    } else {
        text_part("text/plain", &m.body)
    };

    let mut attachments = Vec::new();
    for a in m.attachments.iter().filter_map(Value::as_object) {
        let raw = a.get("content_bytes").and_then(Value::as_str).unwrap_or("");
        // A bad blob must not lose the whole message.
        let Ok(data) = B64.decode(raw.trim()) else { continue };
        let ctype = a.get("content_type").and_then(Value::as_str).filter(|s| !s.is_empty()).unwrap_or("application/octet-stream");
        let name = a.get("name").and_then(Value::as_str).filter(|s| !s.is_empty()).unwrap_or("attachment");
        attachments.push(format!(
            "Content-Type: {ctype}\r\nContent-Disposition: attachment; filename=\"{}\"\r\nContent-Transfer-Encoding: base64\r\n\r\n{}\r\n",
            name.replace('"', ""),
            wrap76(&data)
        ));
    }
    let message = if attachments.is_empty() {
        format!("{}\r\n{body_part}", head.join("\r\n"))
    } else {
        let b = boundary("mixed");
        let parts: String = std::iter::once(body_part).chain(attachments).map(|p| format!("--{b}\r\n{p}")).collect();
        format!("{}\r\nContent-Type: multipart/mixed; boundary=\"{b}\"\r\n\r\n{parts}--{b}--\r\n", head.join("\r\n"))
    };
    URL_SAFE.encode(message)
}

/// Flatten a body into form pairs with bracket notation (`metadata[tier]=gold`).
pub fn form_pairs(value: &Value, prefix: &str) -> Vec<(String, String)> {
    let mut pairs = Vec::new();
    match value {
        Value::Object(m) => {
            for (k, v) in m {
                pairs.extend(form_pairs(v, &if prefix.is_empty() { k.clone() } else { format!("{prefix}[{k}]") }));
            }
        }
        Value::Array(a) => {
            for (i, v) in a.iter().enumerate() {
                pairs.extend(form_pairs(v, &format!("{prefix}[{i}]")));
            }
        }
        Value::Bool(b) => pairs.push((prefix.to_string(), if *b { "true" } else { "false" }.into())),
        Value::Null => {}
        other => pairs.push((prefix.to_string(), python_str(other))),
    }
    pairs
}

/// Query strings are text: lists join with commas, booleans are lower-case.
pub fn as_query_value(value: &Value) -> String {
    match value {
        Value::Bool(b) => if *b { "true" } else { "false" }.into(),
        Value::Array(a) => a.iter().map(as_query_value).collect::<Vec<_>>().join(","),
        other => python_str(other),
    }
}

/// A one-line reason from whatever shape of error the provider returned.
pub fn error_message(status: u16, body: &Value) -> String {
    if let Value::Object(m) = body {
        for key in ["error_description", "message", "error", "detail", "title"] {
            match m.get(key) {
                Some(Value::String(s)) if !s.is_empty() => return format!("HTTP {status}: {s}"),
                Some(Value::Object(o)) => {
                    let nested = o.get("message").filter(|v| v.as_str().is_some_and(|s| !s.is_empty())).or_else(|| o.get("description"));
                    if let Some(Value::String(s)) = nested.filter(|v| v.as_str().is_some_and(|s| !s.is_empty())) {
                        return format!("HTTP {status}: {s}");
                    }
                }
                _ => {}
            }
        }
        if let Some(Value::Array(errors)) = m.get("errors") {
            if let Some(first) = errors.first() {
                let text = match first {
                    Value::Object(o) => o.get("message").map(python_str).unwrap_or_default(),
                    other => python_str(other),
                };
                if !text.is_empty() && text != "None" {
                    return format!("HTTP {status}: {text}");
                }
            }
        }
    }
    if let Value::String(s) = body {
        if !s.trim().is_empty() {
            return format!("HTTP {status}: {}", s.trim().chars().take(200).collect::<String>());
        }
    }
    format!("HTTP {status}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obj(v: Value) -> Map<String, Value> {
        v.as_object().unwrap().clone()
    }

    #[test]
    fn binding_drops_missing_and_keeps_types() {
        let values = obj(json!({"to": ["a@x.com"], "n": 3}));
        let t = json!({"recipients": {"$map": {"source": "${to}", "template": {"address": "${item}"}}}, "count": "${n}", "gone": "${nope}", "nested": {"x": "${nope}"}});
        let out = bind(&t, &values).unwrap();
        assert_eq!(out, json!({"recipients": [{"address": "a@x.com"}], "count": 3}));
        let when = json!({"$when": "${nope}", "contentType": "HTML"});
        assert_eq!(bind(&when, &values), None);
    }

    #[test]
    fn paths_encode_segments() {
        let values = obj(json!({"id": "a/b c", "full": "/v1/x"}));
        assert_eq!(bind_path("/items/${id}", &values), "/items/a%2Fb%20c");
        assert_eq!(bind_path("${full}", &values), "/v1/x");
    }

    #[test]
    fn form_and_query_values() {
        assert_eq!(
            form_pairs(&json!({"metadata": {"tier": "gold"}, "items": [{"price": "p1"}]}), ""),
            vec![("metadata[tier]".to_string(), "gold".to_string()), ("items[0][price]".to_string(), "p1".to_string())]
        );
        assert_eq!(as_query_value(&json!([1, true, "x"])), "1,true,x");
    }

    #[test]
    fn errors_are_summarised() {
        assert_eq!(error_message(404, &json!({"error": {"message": "nope"}})), "HTTP 404: nope");
        assert_eq!(error_message(400, &json!({"errors": [{"message": "bad"}]})), "HTTP 400: bad");
        assert_eq!(error_message(500, &json!("")), "HTTP 500");
    }

    #[test]
    fn mime_messages_decode() {
        let raw = build_mime_message(&MimeMessage {
            to: vec!["a@x.com".into()],
            subject: "Hi".into(),
            body: "<b>x</b>".into(),
            body_type: "html".into(),
            ..Default::default()
        });
        let text = String::from_utf8(URL_SAFE.decode(raw).unwrap()).unwrap();
        assert!(text.starts_with("To: a@x.com\r\nSubject: Hi\r\n"));
        assert!(text.contains("multipart/alternative"));
    }
}
