//! The tool layer: what each connector can do, and which of it a credential may do.

pub mod executor;
pub mod models;
pub mod permissions;
pub mod registry;

pub use executor::{
    MimeMessage, ToolExecutor, as_query_value, bind, bind_path, build_mime_message, error_message, form_pairs, template_arguments,
};
pub use models::{
    PARAM_TYPES, ScopeDiscovery, ScopeDiscoverySpec, ScopeRules, SpecFormat, TOOL_NAME_RE, Tool, ToolAvailability, ToolOutput, ToolPack,
    ToolParameter, ToolReport, ToolRequest, ToolResult, ToolStatus, parse_scope_string,
};
pub use permissions::{build_report, connection_scopes, discover_scopes};
pub use registry::{BASELINE_TOOL, ENDPOINT_FIELDS, RAW_TOOLS, ToolRegistry, baseline_pack, load_pack};
