#![doc = include_str!("../../../RUST.md")]

pub mod auth;
pub mod credentials;
pub mod data;
pub mod error;
pub mod http;
pub mod interpolation;
pub mod manager;
pub mod models;
pub mod proxy;
pub mod registry;
pub mod signing;
pub mod tools;
pub mod validation;
pub mod verification;

pub use auth::{AuthContext, AuthStrategy, Strategies};
pub use data::DataSource;
pub use error::{Error, ErrorKind, Result};
pub use http::{AsyncTransport, BlockingTransport, HttpOptions, HttpResponse, Request, Transport, block_on};
pub use manager::{AsyncConnectorManager, BaseConnectorManager, ConnectOptions, ConnectorManager};
pub use models::{AuthField, AuthMode, AuthSchema, Connection, Connector, ConnectorPage, FieldGroup};
pub use proxy::{Call, RequestBuilder};
pub use registry::{ConnectorFilter, ConnectorRegistry, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE};
pub use tools::{
    ScopeDiscovery, ScopeRules, SpecFormat, Tool, ToolAvailability, ToolExecutor, ToolPack, ToolParameter, ToolRegistry, ToolReport,
    ToolResult, ToolStatus,
};
pub use validation::Validated;
pub use verification::VerificationResult;

/// The crate version, kept equal to the Python package's.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
