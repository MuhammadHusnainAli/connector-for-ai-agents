//! Parsing of provider token responses into credential objects.
//!
//! Providers express token lifetimes in wildly different ways (`expires_in`
//! seconds or milliseconds, `expires_at` dates, durations, JWT `exp` claims,
//! `"177:05:38"` strings). This module normalises all of them, exactly as the
//! Python package does.

use std::sync::LazyLock;

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use chrono::{DateTime, Duration, NaiveDate, NaiveDateTime, SecondsFormat, TimeZone, Utc};
use regex::Regex;
use serde_json::{Map, Value, json};

use crate::error::{Error, Result};
use crate::interpolation::extract_value_by_path;
use crate::models::AuthMode;

/// Fallback lifetime for client-credentials tokens without expiry info (55 min).
pub const DEFAULT_OAUTH_CC_EXPIRES_IN_MS: i64 = 55 * 60 * 1000;
/// "Never expires" horizon for TWO_STEP tokens (10 years).
pub const DEFAULT_INFINITE_EXPIRES_IN_MS: i64 = 10 * 365 * 24 * 60 * 60 * 1000;
/// Refresh a JWT-derived token this long before its own `exp`.
pub const REFRESH_MARGIN_MS: i64 = 15 * 60 * 1000;

/// ISO-8601 with a `Z` suffix, as Python's `isoformat().replace("+00:00", "Z")`.
pub fn iso(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(SecondsFormat::AutoSi, true)
}

/// Now plus `ms` milliseconds.
pub fn in_ms(ms: f64) -> DateTime<Utc> {
    Utc::now() + Duration::milliseconds(ms as i64)
}

/// Parse an ISO date or datetime the way Python's `fromisoformat` does; naive means UTC.
pub fn parse_iso(text: &str) -> Option<DateTime<Utc>> {
    let text = text.trim();
    if let Ok(dt) = DateTime::parse_from_rfc3339(text) {
        return Some(dt.with_timezone(&Utc));
    }
    if let Ok(dt) = DateTime::parse_from_str(text, "%Y-%m-%dT%H:%M:%S%.f%:z") {
        return Some(dt.with_timezone(&Utc));
    }
    for fmt in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(text, fmt) {
            return Some(Utc.from_utc_datetime(&naive));
        }
    }
    NaiveDate::parse_from_str(text, "%Y-%m-%d").ok().map(|d| Utc.from_utc_datetime(&d.and_hms_opt(0, 0, 0).unwrap()))
}

/// Parse `"3600"`, `3600`, `"1h"`, `"30 minutes"` into milliseconds.
pub fn parse_duration_ms(value: &Value) -> Option<i64> {
    static DURATION: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)^(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|seconds?|m|mins?|minutes?|h|hrs?|hours?|d|days?|w|weeks?|y|years?)$").unwrap()
    });
    match value {
        Value::Null => None,
        Value::Number(n) => n.as_f64().map(|f| (f * 1000.0) as i64),
        Value::Bool(_) => None,
        other => {
            let text = match other {
                Value::String(s) => s.trim().to_string(),
                v => v.to_string(),
            };
            if text.is_empty() {
                return None;
            }
            if text.bytes().all(|b| b.is_ascii_digit()) {
                return text.parse::<i64>().ok().map(|n| n * 1000);
            }
            let c = DURATION.captures(&text)?;
            let amount: f64 = c[1].parse().ok()?;
            let unit_ms: i64 = match c[2].to_lowercase().as_str() {
                "ms" => 1,
                "s" | "sec" | "secs" | "second" | "seconds" => 1000,
                "m" | "min" | "mins" | "minute" | "minutes" => 60_000,
                "h" | "hr" | "hrs" | "hour" | "hours" => 3_600_000,
                "d" | "day" | "days" => 86_400_000,
                "w" | "week" | "weeks" => 604_800_000,
                "y" | "year" | "years" => 31_536_000_000,
                _ => return None,
            };
            Some((amount * unit_ms as f64) as i64)
        }
    }
}

fn from_epoch(seconds: f64) -> Option<DateTime<Utc>> {
    DateTime::from_timestamp_millis((seconds * 1000.0) as i64)
}

/// Best-effort parse of an expiry expressed as date, epoch (s or ms) or `D:HH:MM`.
pub fn parse_expiration(value: &Value) -> Option<DateTime<Utc>> {
    match value {
        Value::Null | Value::Bool(_) => None,
        Value::Number(n) => {
            let f = n.as_f64()?;
            // Values that look like milliseconds when read as seconds land before 1972.
            let as_ms = from_epoch(f / 1000.0)?;
            if chrono::Datelike::year(&as_ms) > 1971 { Some(as_ms) } else { from_epoch(f) }
        }
        Value::String(s) => {
            let text = s.trim();
            if text.is_empty() {
                return None;
            }
            if let Some(dt) = parse_iso(text) {
                return Some(dt);
            }
            if let Ok(f) = text.parse::<f64>() {
                if text.replacen('.', "", 1).bytes().all(|b| b.is_ascii_digit()) {
                    return parse_expiration(&json!(f));
                }
            }
            static DHM: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\d+:\d{2}:\d{2}$").unwrap());
            if DHM.is_match(text) {
                let parts: Vec<i64> = text.split(':').filter_map(|p| p.parse().ok()).collect();
                return Some(Utc::now() + Duration::days(parts[0]) + Duration::hours(parts[1]) + Duration::minutes(parts[2]));
            }
            None
        }
        _ => None,
    }
}

/// Read `exp` out of a JWT without verifying it.
pub fn decode_jwt_exp(token: &Value) -> Option<DateTime<Utc>> {
    let payload = decode_jwt_payload(token.as_str()?)?;
    payload.get("exp")?.as_f64().and_then(from_epoch)
}

/// The claims of a JWT, unverified. `None` when it is not a three-part JWT.
pub fn decode_jwt_payload(token: &str) -> Option<Map<String, Value>> {
    if token.matches('.').count() != 2 {
        return None;
    }
    let segment = token.split('.').nth(1)?.trim_end_matches('=');
    let bytes = URL_SAFE_NO_PAD.decode(segment).ok()?;
    serde_json::from_slice::<Value>(&bytes).ok()?.as_object().cloned()
}

fn incomplete(mode: AuthMode) -> Error {
    Error::token("incomplete_raw_credentials").with("auth_mode", mode.as_str())
}

fn truthy_str(v: Option<&Value>) -> Option<Value> {
    match v {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) if s.is_empty() => None,
        Some(Value::Bool(false)) => None,
        Some(v) => Some(v.clone()),
    }
}

/// Turn a provider token response into a credentials object.
pub fn parse_raw_credentials(raw: &Map<String, Value>, mode: AuthMode, provider: &Map<String, Value>) -> Result<Map<String, Value>> {
    match mode {
        AuthMode::Oauth2 => parse_oauth2(raw, provider),
        AuthMode::Oauth2Cc => parse_oauth2_cc(raw, provider),
        AuthMode::TwoStep => parse_two_step(raw, provider),
        AuthMode::Oauth1 => {
            let token = truthy_str(raw.get("oauth_token")).ok_or_else(|| incomplete(mode))?;
            let secret = truthy_str(raw.get("oauth_token_secret")).ok_or_else(|| incomplete(mode))?;
            Ok(obj(json!({"type": "OAUTH1", "oauth_token": token, "oauth_token_secret": secret, "raw": raw})))
        }
        other => Err(Error::token(format!("Cannot parse credentials for auth mode {other}")).with("auth_mode", other.as_str())),
    }
}

fn obj(v: Value) -> Map<String, Value> {
    v.as_object().cloned().unwrap_or_default()
}

fn iso_opt(dt: Option<DateTime<Utc>>) -> Value {
    dt.map(|d| Value::String(iso(d))).unwrap_or(Value::Null)
}

fn parse_oauth2(raw: &Map<String, Value>, provider: &Map<String, Value>) -> Result<Map<String, Value>> {
    let raw_value = Value::Object(raw.clone());
    let mut access_token = truthy_str(raw.get("access_token"));
    let mut context = raw.clone();
    if access_token.is_none() {
        if let Some(path) = provider.get("alternate_access_token_response_path").and_then(Value::as_str) {
            match extract_value_by_path(&raw_value, path) {
                Some(Value::Object(m)) => {
                    context = m.clone();
                    access_token = truthy_str(context.get("access_token"));
                }
                Some(other) => access_token = truthy_str(Some(other)),
                None => {}
            }
        }
    }
    let access_token = access_token.ok_or_else(|| incomplete(AuthMode::Oauth2))?;
    let mut expires_at = parse_expiration(context.get("expires_at").unwrap_or(&Value::Null));
    if expires_at.is_none() {
        if let Some(secs) = context.get("expires_in").and_then(num) {
            expires_at = Some(in_ms(secs * 1000.0));
        }
    }
    Ok(obj(json!({
        "type": "OAUTH2",
        "access_token": access_token,
        "refresh_token": context.get("refresh_token").cloned().unwrap_or(Value::Null),
        "expires_at": iso_opt(expires_at),
        "raw": raw_value,
    })))
}

/// A number, or a string holding one.
pub(crate) fn num(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}

fn parse_oauth2_cc(raw: &Map<String, Value>, provider: &Map<String, Value>) -> Result<Map<String, Value>> {
    let token = truthy_str(raw.get("access_token"))
        .or_else(|| truthy_str(raw.get("data").and_then(Value::as_object).and_then(|d| d.get("token"))))
        .or_else(|| truthy_str(raw.get("jwt")))
        .ok_or_else(|| incomplete(AuthMode::Oauth2Cc))?;
    let mut expires_at = parse_expiration(raw.get("expires_at").unwrap_or(&Value::Null));
    if expires_at.is_none() {
        if let Some(n) = raw.get("expires_in").and_then(num) {
            let multiplier = if provider.get("expires_in_unit").and_then(Value::as_str) == Some("milliseconds") { 1.0 } else { 1000.0 };
            expires_at = Some(in_ms(n * multiplier));
        }
    }
    let expires_at = expires_at.unwrap_or_else(|| in_ms(DEFAULT_OAUTH_CC_EXPIRES_IN_MS as f64));
    Ok(obj(json!({"type": "OAUTH2_CC", "token": token, "expires_at": iso(expires_at), "raw": raw})))
}

fn parse_two_step(raw: &Map<String, Value>, provider: &Map<String, Value>) -> Result<Map<String, Value>> {
    let spec = provider
        .get("token_response")
        .and_then(Value::as_object)
        .ok_or_else(|| Error::token("Token response structure is missing for TWO_STEP"))?;
    let raw_value = Value::Object(raw.clone());
    let path = |key: &str| spec.get(key).and_then(Value::as_str).filter(|s| !s.is_empty());
    let token = match path("token") {
        Some(p) => extract_value_by_path(&raw_value, p).cloned(),
        None => Some(raw_value.clone()),
    };
    let refresh_token = path("refresh_token").and_then(|p| extract_value_by_path(&raw_value, p).cloned());
    let expiration = path("token_expiration").and_then(|p| extract_value_by_path(&raw_value, p).cloned());
    let strategy = path("token_expiration_strategy").unwrap_or("expireAt");

    let token = truthy_str(token.as_ref()).ok_or_else(|| incomplete(AuthMode::TwoStep))?;
    let has_expiration = truthy_str(expiration.as_ref()).is_some();

    let mut expires_at = if strategy == "expireAt" && has_expiration {
        parse_expiration(expiration.as_ref().unwrap())
    } else if strategy == "expireIn" && has_expiration {
        let ms = parse_duration_ms(expiration.as_ref().unwrap())
            .ok_or_else(|| Error::token(format!("Unsupported expiration format: {}", expiration.as_ref().unwrap())))?;
        Some(in_ms(ms as f64))
    } else if let Some(configured) = provider.get("token_expires_in_ms").and_then(num) {
        (configured > 0.0).then(|| in_ms(configured))
    } else {
        Some(in_ms(DEFAULT_INFINITE_EXPIRES_IN_MS as f64))
    };

    // A JWT's own `exp` wins when it is sooner than whatever was derived above.
    let mut sooner = |candidate: Option<DateTime<Utc>>| {
        if let Some(exp) = candidate {
            let c = exp - Duration::milliseconds(REFRESH_MARGIN_MS);
            if expires_at.is_none_or(|e| c < e) {
                expires_at = Some(c);
            }
        }
    };
    if !has_expiration {
        sooner(decode_jwt_exp(&token));
    }
    if let Some(r) = truthy_str(refresh_token.as_ref()) {
        sooner(decode_jwt_exp(&r));
    }
    Ok(obj(json!({
        "type": "TWO_STEP",
        "token": token,
        "refresh_token": refresh_token.unwrap_or(Value::Null),
        "expires_at": iso_opt(expires_at),
        "raw": raw_value,
    })))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn durations() {
        assert_eq!(parse_duration_ms(&json!("1h")), Some(3_600_000));
        assert_eq!(parse_duration_ms(&json!("3600")), Some(3_600_000));
        assert_eq!(parse_duration_ms(&json!(2)), Some(2000));
        assert_eq!(parse_duration_ms(&json!("nonsense")), None);
    }

    #[test]
    fn expirations() {
        let ms = parse_expiration(&json!(1_794_470_709_000_i64)).unwrap();
        let s = parse_expiration(&json!(1_794_470_709)).unwrap();
        assert_eq!(ms, s);
        assert!(parse_expiration(&json!("2026-11-12T00:00:00Z")).is_some());
    }

    #[test]
    fn oauth2_cc_defaults_expiry() {
        let raw = obj(json!({"access_token": "t"}));
        let parsed = parse_raw_credentials(&raw, AuthMode::Oauth2Cc, &Map::new()).unwrap();
        assert_eq!(parsed["token"], "t");
        assert!(parsed["expires_at"].is_string());
        assert!(parse_raw_credentials(&Map::new(), AuthMode::Oauth2Cc, &Map::new()).is_err());
    }
}
