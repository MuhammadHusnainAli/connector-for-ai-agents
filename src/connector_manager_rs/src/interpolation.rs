//! Template interpolation for connector definitions.
//!
//! Connector definitions use `${...}` placeholders with a small expression
//! language, so urls, headers and token params can be declared as data. This is
//! a line-for-line port of the Python engine; both read the same catalogue.
//!
//! ```text
//! ${apiKey}                       flat key lookup
//! ${connectionConfig.domain}      dot path lookup
//! ${a} || ${b}                    fallback (left wins if it resolved)
//! ${base64(${user}:${pass})}      base64 of the resolved inner expression
//! ${sha256Hex(${body})}           hex sha256
//! ${hmacSha1Hex(${msg}, ${key})}  hex hmac-sha1, key is the last argument
//! ${fingerprint(${privateKey})}   SHA256:<base64> of the public key SPKI
//! ${now}                          ISO-8601 timestamp
//! ${now:YYYY-MM-DD}               formatted timestamp
//! ${now+7:days:YYYY-MM-DD}        offset then formatted
//! ${random}                       uuid4
//! ```
//!
//! Unresolvable placeholders are left in place, so callers detect them with
//! [`is_unresolved`].

use std::sync::LazyLock;

use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use chrono::{DateTime, Datelike, Duration, Utc};
use hmac::{Hmac, KeyInit, Mac};
use regex::{Captures, Regex};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::error::{Error, ErrorKind, Result};

/// Matches one innermost `${...}` placeholder.
pub static PLACEHOLDER_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\$\{([^{}]*)\}").unwrap());
static BASE64_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\$\{base64\((.*?)\)\}").unwrap());
static SHA256_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\$\{sha256Hex\((.*?)\)\}").unwrap());
static HMAC_SHA1_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\$\{hmacSha1Hex\(([\s\S]*?)\)\}").unwrap());
static FINGERPRINT_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\$\{fingerprint\((.*?)\)\}").unwrap());
static NOW_OFFSET_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^now([+-]\d+):([a-zA-Z]+):(.+)$").unwrap());
static NOW_FORMAT_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^now:(.+)$").unwrap());
static STEP_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\$\{step(\d+)\..*?\}").unwrap());
static STEP_PREFIX_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"step\d+\.").unwrap());

const WEEKDAYS: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS: [&str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

pub fn has_placeholder(value: &str) -> bool {
    value.contains("${")
}

pub fn is_unresolved(value: &str) -> bool {
    PLACEHOLDER_RE.is_match(value)
}

/// Drop the `credentials.` prefix so `${credentials.x}` resolves as `${x}`.
pub fn strip_credential(value: &Value) -> Value {
    map_strings(value, &|s| s.replace("credentials.", ""))
}

/// Drop `stepN.` prefixes, for resolving against one step's response.
pub fn strip_step_response(value: &Value) -> Value {
    map_strings(value, &|s| STEP_PREFIX_RE.replace_all(s, "").into_owned())
}

fn map_strings(value: &Value, f: &dyn Fn(&str) -> String) -> Value {
    match value {
        Value::String(s) => Value::String(f(s)),
        Value::Object(m) => Value::Object(m.iter().map(|(k, v)| (k.clone(), map_strings(v, f))).collect()),
        Value::Array(a) => Value::Array(a.iter().map(|v| map_strings(v, f)).collect()),
        other => other.clone(),
    }
}

pub fn extract_step_number(value: &str) -> Option<usize> {
    STEP_RE.captures(value).and_then(|c| c[1].parse().ok())
}

/// Resolve a lodash-style `a.b[0].c` path.
pub fn extract_value_by_path<'a>(obj: &'a Value, path: &str) -> Option<&'a Value> {
    let mut current = obj;
    for part in path.split(['.', '[', ']']) {
        if part.is_empty() {
            continue;
        }
        current = match current {
            Value::Object(m) => m.get(part)?,
            Value::Array(a) => {
                if !part.bytes().all(|b| b.is_ascii_digit()) {
                    return None;
                }
                a.get(part.parse::<usize>().ok()?)?
            }
            _ => return None,
        };
    }
    Some(current)
}

fn now(replacers: &Map<String, Value>) -> DateTime<Utc> {
    replacers.get("now").and_then(Value::as_str).filter(|s| !s.is_empty()).and_then(crate::credentials::parse_iso).unwrap_or_else(Utc::now)
}

/// Render a moment.js-style format (`YYYY-MM-DD HH:mm:ss`, `X`, `ddd, DD MMM`).
pub(crate) fn moment_format(dt: DateTime<Utc>, fmt: &str) -> String {
    if fmt == "X" {
        return dt.timestamp().to_string();
    }
    const TOKENS: [&str; 10] = ["YYYY", "SSS", "MMM", "MM", "DD", "ddd", "HH", "mm", "ss", "X"];
    let mut out = String::new();
    let mut rest = fmt;
    'scan: while !rest.is_empty() {
        for token in TOKENS {
            if let Some(tail) = rest.strip_prefix(token) {
                out.push_str(&match token {
                    "YYYY" => format!("{:04}", dt.year()),
                    "SSS" => format!("{:03}", dt.timestamp_subsec_millis()),
                    "MMM" => MONTHS[dt.month0() as usize].to_string(),
                    "MM" => format!("{:02}", dt.month()),
                    "DD" => format!("{:02}", dt.day()),
                    "ddd" => WEEKDAYS[dt.weekday().num_days_from_monday() as usize].to_string(),
                    "HH" => dt.format("%H").to_string(),
                    "mm" => dt.format("%M").to_string(),
                    "ss" => dt.format("%S").to_string(),
                    _ => dt.timestamp().to_string(),
                });
                rest = tail;
                continue 'scan;
            }
        }
        let ch = rest.chars().next().unwrap();
        out.push(ch);
        rest = &rest[ch.len_utf8()..];
    }
    out
}

fn resolve_now(expression: &str, replacers: &Map<String, Value>) -> Option<String> {
    if expression == "now" {
        if let Some(iso) = replacers.get("now").and_then(Value::as_str).filter(|s| !s.is_empty()) {
            return Some(iso.to_string());
        }
        return Some(crate::credentials::iso(now(replacers)));
    }
    if let Some(c) = NOW_OFFSET_RE.captures(expression) {
        let amount: i64 = c[1].parse().ok()?;
        let unit = match c[2].to_lowercase().as_str() {
            "hour" | "hours" | "h" => Duration::hours(amount),
            "minute" | "minutes" | "m" => Duration::minutes(amount),
            "second" | "seconds" | "s" => Duration::seconds(amount),
            "week" | "weeks" | "w" => Duration::weeks(amount),
            _ => Duration::days(amount),
        };
        return Some(moment_format(now(replacers) + unit, &c[3]));
    }
    NOW_FORMAT_RE.captures(expression).map(|c| moment_format(now(replacers), &c[1]))
}

fn resolve_key<'a>(key: &str, replacers: &'a Map<String, Value>) -> Option<&'a Value> {
    if let Some(v) = replacers.get(key) {
        return Some(v);
    }
    let mut parts = key.split('.');
    let mut current = replacers.get(parts.next()?)?;
    for part in parts {
        current = current.as_object()?.get(part)?;
    }
    Some(current)
}

/// The text `str(value)` gives in Python, for the scalar values a template inserts.
pub(crate) fn scalar_text(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

/// Normalise a possibly single-line or header-less PEM blob.
pub fn format_pem(pem: &str, kind: &str) -> Result<String> {
    if pem.is_empty() {
        return Err(Error::new(ErrorKind::Interpolation, "Invalid PEM input: must be a non-empty string"));
    }
    static HEADER: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"-----(BEGIN|END) [^-]+-----").unwrap());
    let body = pem.replace("\\n", "\n");
    let body = HEADER.replace_all(&body, "");
    let body: String = body.trim().chars().filter(|c| !c.is_whitespace()).collect();
    if body.is_empty() {
        return Err(Error::new(ErrorKind::Interpolation, "PEM content is empty after normalization"));
    }
    if !body.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '/' | '=')) {
        return Err(Error::new(ErrorKind::Interpolation, "PEM contains invalid characters (must be base64)"));
    }
    let chunks: Vec<&str> = body.as_bytes().chunks(64).map(|c| std::str::from_utf8(c).unwrap()).collect();
    Ok(format!("-----BEGIN {kind}-----\n{}\n-----END {kind}-----\n", chunks.join("\n")))
}

/// The `BEGIN <kind>` label of a PEM, or `default`.
pub fn pem_kind(pem: &str, default: &str) -> String {
    static KIND: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"-----BEGIN ([A-Z0-9 ]+)-----").unwrap());
    KIND.captures(pem).map(|c| c[1].to_string()).unwrap_or_else(|| default.to_string())
}

/// `SHA256:<base64>` of the public key's SPKI, from an RSA private key PEM.
pub fn fingerprint(private_key_pem: &str) -> Result<String> {
    use rsa::pkcs1::DecodeRsaPrivateKey;
    use rsa::pkcs8::{DecodePrivateKey, EncodePublicKey};
    let pem = format_pem(private_key_pem, &pem_kind(private_key_pem, "PRIVATE KEY"))?;
    let key = rsa::RsaPrivateKey::from_pkcs8_pem(&pem)
        .or_else(|_| rsa::RsaPrivateKey::from_pkcs1_pem(&pem))
        .map_err(|e| Error::new(ErrorKind::Interpolation, format!("cannot read private key: {e}")))?;
    let der = key
        .to_public_key()
        .to_public_key_der()
        .map_err(|e| Error::new(ErrorKind::Interpolation, format!("cannot encode public key: {e}")))?;
    Ok(format!("SHA256:{}", B64.encode(Sha256::digest(der.as_bytes()))))
}

fn apply_functions(value: &str, replacers: &Map<String, Value>) -> String {
    let inner = |s: &str| interpolate(s, replacers);
    let value = HMAC_SHA1_RE.replace_all(value, |c: &Captures| {
        let body = &c[1];
        match body.rfind(',') {
            None => c[0].to_string(),
            Some(i) => {
                let message = inner(&body[..i]);
                let key = inner(body[i + 1..].trim());
                let mut mac = Hmac::<sha1::Sha1>::new_from_slice(key.as_bytes()).expect("hmac accepts any key");
                mac.update(message.as_bytes());
                hex::encode(mac.finalize().into_bytes())
            }
        }
    });
    let value = BASE64_RE.replace_all(&value, |c: &Captures| B64.encode(inner(&c[1])));
    let value = SHA256_RE.replace_all(&value, |c: &Captures| hex::encode(Sha256::digest(inner(&c[1]).as_bytes())));
    let value = FINGERPRINT_RE.replace_all(&value, |c: &Captures| fingerprint(&inner(&c[1])).unwrap_or_else(|_| c[0].to_string()));
    value.into_owned()
}

/// Resolve every placeholder in `value` against `replacers`.
pub fn interpolate(value: &str, replacers: &Map<String, Value>) -> String {
    if !value.contains("${") {
        return value.to_string();
    }
    let value = apply_functions(value, replacers);

    if let Some((left, right)) = value.split_once("||") {
        let (left, right) = (left.trim(), right.trim());
        if !left.is_empty() {
            let resolved = interpolate(left, replacers);
            if !resolved.is_empty() && !is_unresolved(&resolved) {
                return resolved;
            }
        }
        return if right.is_empty() { String::new() } else { interpolate(right, replacers) };
    }

    PLACEHOLDER_RE
        .replace_all(&value, |c: &Captures| {
            let key = &c[1];
            if let Some(v) = resolve_now(key, replacers) {
                return v;
            }
            if key == "random" {
                return replacers
                    .get("random")
                    .and_then(scalar_text)
                    .filter(|s| !s.is_empty())
                    .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
            }
            resolve_key(key, replacers).and_then(scalar_text).unwrap_or_else(|| c[0].to_string())
        })
        .into_owned()
}

/// Interpolate every string leaf of a nested structure.
pub fn interpolate_deep(value: &Value, replacers: &Map<String, Value>) -> Value {
    match value {
        Value::String(s) => Value::String(interpolate(s, replacers)),
        Value::Object(m) => Value::Object(m.iter().map(|(k, v)| (k.clone(), interpolate_deep(v, replacers))).collect()),
        Value::Array(a) => Value::Array(a.iter().map(|v| interpolate_deep(v, replacers)).collect()),
        other => other.clone(),
    }
}

/// Freeze `${now}` / `${random}` so they are identical across one request.
pub fn stable_replacers<'a>(values: impl IntoIterator<Item = &'a str>) -> Map<String, Value> {
    let joined: String = values.into_iter().collect();
    let mut out = Map::new();
    if joined.contains("${random}") {
        out.insert("random".into(), Value::String(uuid::Uuid::new_v4().to_string()));
    }
    if joined.contains("${now}") || joined.contains("${now:") || joined.contains("${now+") {
        out.insert("now".into(), Value::String(crate::credentials::iso(Utc::now())));
    }
    out
}

/// Resolve a URL template, failing when placeholders remain.
pub fn make_url(template: &str, config: &Map<String, Value>) -> Result<String> {
    let cleaned = template.replace("connectionConfig.", "").replace("credentials.", "");
    let resolved = interpolate(&cleaned, &drop_empty(config));
    if is_unresolved(&resolved) {
        return Err(Error::new(
            ErrorKind::Interpolation,
            format!("Failed to interpolate URL template: {template}. Missing config parameters."),
        )
        .with("template", template)
        .with("resolved", resolved));
    }
    Ok(resolved)
}

fn drop_empty(obj: &Map<String, Value>) -> Map<String, Value> {
    obj.iter()
        .filter(|(_, v)| !matches!(v, Value::Null) && v.as_str() != Some(""))
        .map(|(k, v)| (k.clone(), if let Value::Object(m) = v { Value::Object(drop_empty(m)) } else { v.clone() }))
        .collect()
}

/// Shallow-merge objects, later ones winning. The building block of every namespace.
pub(crate) fn merged<'a>(parts: impl IntoIterator<Item = &'a Map<String, Value>>) -> Map<String, Value> {
    let mut out = Map::new();
    for part in parts {
        for (k, v) in part {
            out.insert(k.clone(), v.clone());
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn ns(v: Value) -> Map<String, Value> {
        v.as_object().unwrap().clone()
    }

    #[test]
    fn lookups_paths_and_fallbacks() {
        let r = ns(json!({"apiKey": "k", "connectionConfig": {"domain": "d.example"}, "n": 5}));
        assert_eq!(interpolate("Bearer ${apiKey}", &r), "Bearer k");
        assert_eq!(interpolate("https://${connectionConfig.domain}/x", &r), "https://d.example/x");
        assert_eq!(interpolate("${missing} || ${apiKey}", &r), "k");
        assert_eq!(interpolate("${missing}", &r), "${missing}");
        assert_eq!(interpolate("${n}", &r), "5");
    }

    #[test]
    fn functions() {
        let r = ns(json!({"u": "user", "p": "pass", "body": "abc"}));
        assert_eq!(interpolate("Basic ${base64(${u}:${p})}", &r), "Basic dXNlcjpwYXNz");
        assert_eq!(interpolate("${sha256Hex(${body})}", &r), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assert_eq!(interpolate("${hmacSha1Hex(${body}, ${p})}", &r).len(), 40);
    }

    #[test]
    fn now_formats() {
        let r = ns(json!({"now": "2026-11-12T08:05:09.123456Z"}));
        assert_eq!(interpolate("${now:YYYY-MM-DDTHH:mm:ss}", &r), "2026-11-12T08:05:09");
        assert_eq!(interpolate("${now:ddd, DD MMM YYYY HH:mm:ss}", &r), "Thu, 12 Nov 2026 08:05:09");
        assert_eq!(interpolate("${now+7:days:YYYY-MM-DD}", &r), "2026-11-19");
        assert_eq!(interpolate("${now:X}", &r), "1794470709");
    }

    #[test]
    fn paths() {
        let v = json!({"a": {"b": [{"c": 1}]}});
        assert_eq!(extract_value_by_path(&v, "a.b[0].c"), Some(&json!(1)));
        assert_eq!(extract_value_by_path(&v, "a.x"), None);
    }

    #[test]
    fn urls() {
        let c = ns(json!({"subdomain": "acme", "empty": ""}));
        assert_eq!(make_url("https://${connectionConfig.subdomain}.x.com", &c).unwrap(), "https://acme.x.com");
        assert!(make_url("https://${empty}.x.com", &c).is_err());
    }
}
