"""The tool layer: what each connector can actually *do*, and who may do it.

The catalogue answers "what does this connector need to authenticate". This
package answers the next two questions:

1. **What tools does a connector have?** Each one is a named capability with a
   description, typed inputs and a described output -- ready to hand to an LLM
   as a tool definition, or to call directly.
2. **Which of them may *this* credential use?** Tools declare the OAuth scopes
   the provider demands. Given a connection, the report splits them into
   enabled, disabled (with the missing scopes named) and unknown.

    from connector_manager import ConnectorManager

    manager = ConnectorManager()
    manager.list_tools("outlook")                  # every Outlook tool
    report = manager.check_tools(connection)       # what this token may call
    report.summary()
    result = manager.call_tool(connection, "send_email", {"to": [...], "subject": "..."})
"""

from __future__ import annotations

from .executor import ToolExecutor, build_mime_message, template_arguments
from .models import (
    PARAM_TYPES,
    TOOL_NAME_RE,
    ScopeDiscovery,
    ScopeDiscoverySpec,
    ScopeRules,
    Tool,
    ToolAvailability,
    ToolOutput,
    ToolPack,
    ToolParameter,
    ToolReport,
    ToolRequest,
    ToolResult,
    ToolStatus,
    parse_scope_string,
)
from .permissions import ScopeDiscoverer, build_report, connection_scopes
from .registry import BASELINE_TOOL, TOOLS_DIR, ToolRegistry, baseline_pack, load_pack

__all__ = [
    "BASELINE_TOOL",
    "PARAM_TYPES",
    "TOOLS_DIR",
    "TOOL_NAME_RE",
    "ScopeDiscoverer",
    "ScopeDiscovery",
    "ScopeDiscoverySpec",
    "ScopeRules",
    "Tool",
    "ToolAvailability",
    "ToolExecutor",
    "ToolOutput",
    "ToolPack",
    "ToolParameter",
    "ToolRegistry",
    "ToolReport",
    "ToolRequest",
    "ToolResult",
    "ToolStatus",
    "baseline_pack",
    "build_mime_message",
    "build_report",
    "connection_scopes",
    "load_pack",
    "parse_scope_string",
    "template_arguments",
]
