//! The error type, mirroring the Python package's exception hierarchy.
//!
//! Python raises one exception class per failure (`UnknownConnectorError`,
//! `ValidationError`, ...). Rust gets one [`Error`] carrying an [`ErrorKind`]
//! with the same names, a message, and the same structured context, so a
//! caller can match on the kind and still read the details a UI needs.

use std::fmt;

use serde_json::{Map, Value, json};

/// Which failure an [`Error`] is. The names match the Python exception classes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ErrorKind {
    /// The requested connector id does not exist in the catalogue.
    UnknownConnector,
    /// The connector's auth mode is not handled by this crate.
    UnsupportedAuthMode,
    /// The connector needs an OAuth flow, which runs outside this crate.
    ExternalAuthRequired,
    /// Supplied credentials or connection config failed schema validation.
    Validation,
    /// A provider template could not be fully resolved.
    Interpolation,
    /// The provider rejected the token request.
    TokenExchange,
    /// The credentials verification call failed.
    Verification,
    /// An authenticated request could not be built or sent.
    Request,
    /// The connector has no tool by that name, or ships no tools at all.
    UnknownTool,
    /// Arguments supplied to a tool failed its input schema.
    ToolValidation,
    /// The connection's granted scopes do not cover this tool.
    ToolPermission,
    /// The bundled or supplied data could not be read or parsed.
    Data,
}

impl ErrorKind {
    /// The Python exception class this kind corresponds to.
    pub fn name(self) -> &'static str {
        match self {
            Self::UnknownConnector => "UnknownConnectorError",
            Self::UnsupportedAuthMode => "UnsupportedAuthModeError",
            Self::ExternalAuthRequired => "ExternalAuthRequiredError",
            Self::Validation => "ValidationError",
            Self::Interpolation => "InterpolationError",
            Self::TokenExchange => "TokenExchangeError",
            Self::Verification => "VerificationError",
            Self::Request => "RequestError",
            Self::UnknownTool => "UnknownToolError",
            Self::ToolValidation => "ToolValidationError",
            Self::ToolPermission => "ToolPermissionError",
            Self::Data => "DataError",
        }
    }

    /// True for the tool layer's failures (`ToolError` in Python).
    pub fn is_tool_error(self) -> bool {
        matches!(self, Self::UnknownTool | Self::ToolValidation | Self::ToolPermission)
    }
}

/// Every failure this crate reports.
#[derive(Debug, Clone)]
pub struct Error {
    pub kind: ErrorKind,
    pub message: String,
    /// Structured details: `connector_id`, `status`, `field_errors`, ...
    pub context: Map<String, Value>,
}

/// Shorthand for `Result<T, connector_manager::Error>`.
pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub fn new(kind: ErrorKind, message: impl Into<String>) -> Self {
        Self { kind, message: message.into(), context: Map::new() }
    }

    /// Attach one context value, builder style.
    pub fn with(mut self, key: &str, value: impl Into<Value>) -> Self {
        self.context.insert(key.to_string(), value.into());
        self
    }

    /// Per-field problems of a [`ErrorKind::Validation`] error, by field name.
    pub fn field_errors(&self) -> Map<String, Value> {
        self.context.get("field_errors").and_then(Value::as_object).cloned().unwrap_or_default()
    }

    /// Per-argument problems of a [`ErrorKind::ToolValidation`] error.
    pub fn argument_errors(&self) -> Map<String, Value> {
        self.context.get("argument_errors").and_then(Value::as_object).cloned().unwrap_or_default()
    }

    /// Scopes a [`ErrorKind::ToolPermission`] error says are missing.
    pub fn missing_scopes(&self) -> Vec<String> {
        self.context
            .get("missing_scopes")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
            .unwrap_or_default()
    }

    /// `{"error": "<ClassName>", "message": ..., **context}`, like Python's `to_dict`.
    pub fn to_json(&self) -> Value {
        let mut out = Map::new();
        out.insert("error".into(), json!(self.kind.name()));
        out.insert("message".into(), json!(self.message));
        for (k, v) in &self.context {
            out.insert(k.clone(), v.clone());
        }
        Value::Object(out)
    }

    pub(crate) fn unknown_connector(id: &str) -> Self {
        Self::new(ErrorKind::UnknownConnector, format!("Unknown connector '{id}'")).with("connector_id", id)
    }

    pub(crate) fn validation(message: impl Into<String>, field_errors: Map<String, Value>) -> Self {
        Self::new(ErrorKind::Validation, message).with("field_errors", Value::Object(field_errors))
    }

    pub(crate) fn request(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Request, message)
    }

    pub(crate) fn token(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::TokenExchange, message)
    }

    pub(crate) fn data(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Data, message)
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.kind.name(), self.message)
    }
}

impl std::error::Error for Error {}

impl From<reqwest::Error> for Error {
    fn from(err: reqwest::Error) -> Self {
        Self::request(format!("HTTP transport error: {err}"))
    }
}

impl From<serde_json::Error> for Error {
    fn from(err: serde_json::Error) -> Self {
        Self::data(format!("invalid JSON: {err}"))
    }
}
