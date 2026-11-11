//! Validation of user-supplied values against a connector's auth schema.

use std::collections::BTreeMap;
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Value};

use crate::error::{Error, Result};
use crate::models::{AuthField, AuthSchema, FieldGroup};

/// Validated inputs, grouped by where they go.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Validated {
    pub credentials: Map<String, Value>,
    pub connection_config: Map<String, Value>,
    pub integration_config: Map<String, Value>,
    pub assertion_option: Map<String, Value>,
}

/// Validate inputs and return them normalised, grouped by destination.
///
/// Every offending field is reported at once in the error's `field_errors`, so
/// a UI can show all problems together. `require_all = false` skips the
/// "missing required field" checks, which refresh flows want.
pub fn validate(
    schema: &AuthSchema,
    credentials: &Map<String, Value>,
    connection_config: &Map<String, Value>,
    integration_config: &Map<String, Value>,
    require_all: bool,
) -> Result<Validated> {
    let empty = Map::new();
    let groups: [(FieldGroup, &Vec<AuthField>, &Map<String, Value>); 4] = [
        (FieldGroup::Credentials, &schema.credentials, credentials),
        (FieldGroup::ConnectionConfig, &schema.connection_config, connection_config),
        (FieldGroup::IntegrationConfig, &schema.integration_config, integration_config),
        (FieldGroup::AssertionOption, &schema.assertion_option, &empty),
    ];
    let mut errors: BTreeMap<String, String> = BTreeMap::new();
    let mut out = Validated::default();

    for (group, fields, values) in groups {
        let target = match group {
            FieldGroup::Credentials => &mut out.credentials,
            FieldGroup::ConnectionConfig => &mut out.connection_config,
            FieldGroup::IntegrationConfig => &mut out.integration_config,
            FieldGroup::AssertionOption => &mut out.assertion_option,
        };
        for field in fields {
            let raw = values.get(&field.name).filter(|v| !is_blank(v));
            let Some(raw) = raw else {
                if let Some(default) = &field.default_value {
                    // Providers use a default (often "") instead of asking.
                    target.insert(field.name.clone(), Value::String(default.clone()));
                } else if field.required && require_all && !field.automated && !field.hidden && !hidden_conditional(field, values) {
                    errors.insert(field.name.clone(), format!("{} is required", label(field)));
                }
                continue;
            };
            let text = match raw {
                Value::String(s) => s.clone(),
                Value::Number(n) => n.to_string(),
                Value::Bool(b) => {
                    if *b {
                        "True".into()
                    } else {
                        "False".into()
                    }
                }
                other => {
                    target.insert(field.name.clone(), other.clone());
                    continue;
                }
            };
            match check(field, &text) {
                Some(problem) => {
                    errors.insert(field.name.clone(), problem);
                }
                None => {
                    target.insert(field.name.clone(), Value::String(text));
                }
            }
        }
        // Keep extra values a provider template may still reference.
        for (k, v) in values {
            if !target.contains_key(k) {
                target.insert(k.clone(), v.clone());
            }
        }
    }

    if !errors.is_empty() {
        let names: Vec<&str> = errors.keys().map(String::as_str).collect();
        let message = format!("Invalid input for connector '{}': {}", schema.connector_id, names.join(", "));
        let field_errors = errors.into_iter().map(|(k, v)| (k, Value::String(v))).collect();
        return Err(Error::validation(message, field_errors));
    }
    Ok(out)
}

fn is_blank(v: &Value) -> bool {
    matches!(v, Value::Null) || v.as_str() == Some("")
}

fn label(field: &AuthField) -> &str {
    if field.title.is_empty() { &field.name } else { &field.title }
}

/// `visible_when` fields are only required while their condition holds.
fn hidden_conditional(field: &AuthField, values: &Map<String, Value>) -> bool {
    let Some(cond) = &field.visible_when else { return false };
    let target = cond.get("field").and_then(Value::as_str).unwrap_or("");
    let current = match values.get(target) {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    };
    Some(current.as_str()) != cond.get("equals").and_then(Value::as_str)
}

static EMAIL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[^@\s]+@[^@\s]+\.[^@\s]+$").unwrap());
static UUID: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$").unwrap());
static HOSTNAME: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?$").unwrap());

/// `re.search` semantics for a catalogue pattern. Patterns are written for
/// Python's engine, so lookarounds are allowed; an uncompilable one never blocks.
pub(crate) fn pattern_matches(pattern: &str, value: &str) -> bool {
    match fancy_regex::Regex::new(pattern) {
        Ok(re) => re.is_match(value).unwrap_or(true),
        Err(_) => true,
    }
}

fn check(field: &AuthField, value: &str) -> Option<String> {
    let name = label(field);
    if !field.r#enum.is_empty() && !field.r#enum.iter().any(|e| e == value) {
        return Some(format!("{name} must be one of: {}", field.r#enum.join(", ")));
    }
    if let Some(p) = &field.pattern {
        if !pattern_matches(p, value) {
            return Some(format!("{name} does not match the expected format"));
        }
    }
    match field.format.as_deref() {
        Some("email") if !EMAIL.is_match(value) => Some(format!("{name} must be a valid email address")),
        Some("uuid") if !UUID.is_match(value) => Some(format!("{name} must be a valid UUID")),
        Some("hostname") if !HOSTNAME.is_match(value) => Some(format!("{name} must be a valid hostname (no scheme or path)")),
        Some("uri") => match url::Url::parse(value) {
            Ok(u) if !u.scheme().is_empty() && u.host_str().is_some_and(|h| !h.is_empty()) => None,
            _ => Some(format!("{name} must be a valid URL")),
        },
        _ => None,
    }
}
