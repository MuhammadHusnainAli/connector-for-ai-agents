"""The tool layer's machinery: binding, validation, scopes, execution.

:mod:`tests.test_tool_packs` checks the bundled data; this file checks the code
that turns it into requests and permission verdicts, with the network mocked.
"""

from __future__ import annotations

import base64
import json
from email import message_from_bytes

import httpx
import pytest
import respx

from connector_manager import (
    AsyncConnectorManager,
    Connection,
    ConnectorManager,
    ToolAvailability,
    ToolPermissionError,
    ToolValidationError,
    UnknownToolError,
)
from connector_manager.tools.executor import MISSING, _bind, form_pairs, template_arguments
from connector_manager.tools.models import ScopeRules, Tool, ToolRequest, parse_scope_string
from connector_manager.tools.permissions import connection_scopes


@pytest.fixture(scope="module")
def manager() -> ConnectorManager:
    return ConnectorManager()


def connection(connector_id: str = "outlook", **kwargs) -> Connection:
    credentials = {"access_token": "test-token"}
    credentials.update(kwargs.pop("credentials", {}))
    return Connection(
        connection_id="c1",
        connector_id=connector_id,
        auth_mode=kwargs.pop("auth_mode", "OAUTH2"),
        credentials=credentials,
        **kwargs,
    )


# -- catalogue ---------------------------------------------------------------


def test_tools_are_bundled(manager: ConnectorManager) -> None:
    stats = manager.tool_stats()
    assert stats["packs"] >= 30
    assert stats["tools"] >= 400
    assert manager.has_tools("hubspot")
    assert not manager.has_tools("definitely-not-a-connector")


def test_applies_to_shares_one_pack(manager: ConnectorManager) -> None:
    """Outlook and Microsoft 365 are the same API, so they share a pack."""
    assert manager.tool_pack("outlook") is manager.tool_pack("microsoft")
    assert manager.get_tool("outlook", "send_email").connector_id == "microsoft"


def test_aliases_do_not_inherit_by_accident(manager: ConnectorManager) -> None:
    """google-mail and google-calendar both alias `google` but are different APIs."""
    gmail = {t.name for t in manager.list_tools("google-mail")}
    calendar = {t.name for t in manager.list_tools("google-calendar")}
    assert "send_email" in gmail and "send_email" not in calendar
    assert "create_event" in calendar and "create_event" not in gmail


def test_unknown_tool_names_what_is_available(manager: ConnectorManager) -> None:
    with pytest.raises(UnknownToolError) as err:
        manager.get_tool("hubspot", "no_such_tool")
    assert "create_contact" in err.value.context["available"]


def test_unknown_connector_tools_is_empty_not_an_error(manager: ConnectorManager) -> None:
    assert manager.list_tools("nowhere") == []
    with pytest.raises(UnknownToolError):
        manager.tool_pack("nowhere")


def test_search_tools(manager: ConnectorManager) -> None:
    hits = manager.search_tools("attachment")
    assert {t.connector_id for t in hits} >= {"microsoft", "google-mail"}
    assert all("attachment" in f"{t.name}{t.title}{t.description}".lower() for t in hits)


# -- LLM specs ---------------------------------------------------------------


def test_anthropic_spec_shape(manager: ConnectorManager) -> None:
    spec = manager.get_tool("hubspot", "create_contact").spec("anthropic")
    assert spec["name"] == "create_contact"
    assert spec["input_schema"]["required"] == ["properties"]
    assert spec["input_schema"]["additionalProperties"] is False


def test_openai_and_mcp_specs(manager: ConnectorManager) -> None:
    tool = manager.get_tool("github", "create_issue")
    openai = tool.spec("openai")
    assert openai["type"] == "function"
    assert openai["function"]["parameters"]["type"] == "object"

    mcp = tool.spec("mcp")
    assert mcp["outputSchema"]["type"] == "object"
    assert mcp["annotations"]["readOnlyHint"] is False


def test_spec_prefix_qualifies_the_name(manager: ConnectorManager) -> None:
    spec = manager.get_tool("slack", "send_message").spec("anthropic", prefix=True)
    assert spec["name"] == "slack_send_message"


def test_unknown_spec_format_is_rejected(manager: ConnectorManager) -> None:
    with pytest.raises(ValueError, match="unknown tool spec format"):
        manager.get_tool("slack", "send_message").spec("langchain")


# -- argument validation -----------------------------------------------------


def test_missing_required_arguments_are_all_reported(manager: ConnectorManager) -> None:
    with pytest.raises(ToolValidationError) as err:
        manager.validate_tool_arguments("microsoft", "send_email", {})
    assert set(err.value.argument_errors) == {"to", "subject", "body"}


def test_unknown_arguments_are_rejected(manager: ConnectorManager) -> None:
    with pytest.raises(ToolValidationError) as err:
        manager.validate_tool_arguments(
            "microsoft", "send_email", {"to": ["a@b.com"], "subject": "x", "body": "y", "nope": 1}
        )
    assert "nope" in err.value.argument_errors


def test_defaults_are_filled_in(manager: ConnectorManager) -> None:
    values = manager.validate_tool_arguments(
        "microsoft", "send_email", {"to": ["a@b.com"], "subject": "x", "body": "y"}
    )
    assert values["body_type"] == "HTML"
    assert values["save_to_sent_items"] is True


def test_stringly_typed_arguments_are_coerced(manager: ConnectorManager) -> None:
    """Models emit "25" and "true" where an integer and a boolean are wanted."""
    values = manager.validate_tool_arguments("microsoft", "list_messages", {"limit": "25"})
    assert values["limit"] == 25
    values = manager.validate_tool_arguments(
        "microsoft", "mark_message_read", {"message_id": "m1", "is_read": "false"}
    )
    assert values["is_read"] is False


def test_a_bare_value_becomes_a_list(manager: ConnectorManager) -> None:
    values = manager.validate_tool_arguments(
        "microsoft", "send_email", {"to": "a@b.com", "subject": "x", "body": "y"}
    )
    assert values["to"] == ["a@b.com"]


def test_enum_and_bounds_are_enforced(manager: ConnectorManager) -> None:
    with pytest.raises(ToolValidationError, match="body_type"):
        manager.validate_tool_arguments(
            "microsoft", "send_email",
            {"to": ["a@b.com"], "subject": "x", "body": "y", "body_type": "Markdown"},
        )
    with pytest.raises(ToolValidationError, match="limit"):
        manager.validate_tool_arguments("microsoft", "list_messages", {"limit": 5000})


def test_non_numeric_string_for_an_integer_is_rejected(manager: ConnectorManager) -> None:
    with pytest.raises(ToolValidationError, match="limit"):
        manager.validate_tool_arguments("microsoft", "list_messages", {"limit": "lots"})


# -- template binding --------------------------------------------------------


def test_whole_slot_keeps_the_argument_type() -> None:
    assert _bind({"a": "${x}"}, {"x": {"k": "v"}}) == {"a": {"k": "v"}}
    assert _bind({"a": "${x}"}, {"x": [1, 2]}) == {"a": [1, 2]}
    assert _bind({"a": "${x}"}, {"x": False}) == {"a": False}


def test_embedded_placeholder_interpolates_into_the_string() -> None:
    assert _bind({"a": "v=${x}!"}, {"x": 7}) == {"a": "v=7!"}


def test_absent_arguments_drop_their_key() -> None:
    assert _bind({"a": "${x}", "b": "keep"}, {}) == {"b": "keep"}
    assert _bind("${x}", {}) is MISSING


def test_map_expands_a_list_and_disappears_when_empty() -> None:
    template = {"$map": {"source": "${to}", "template": {"e": {"address": "${item}"}}}}
    assert _bind(template, {"to": ["a", "b"]}) == [{"e": {"address": "a"}}, {"e": {"address": "b"}}]
    assert _bind(template, {}) is MISSING


def test_map_exposes_the_index() -> None:
    template = {"$map": {"source": "${xs}", "template": {"i": "${index}", "v": "${item}"}}}
    assert _bind(template, {"xs": ["a", "b"]}) == [{"i": 0, "v": "a"}, {"i": 1, "v": "b"}]


def test_keyed_builds_a_map_from_a_list() -> None:
    """Planner wants {"<user-id>": {...}}, not a list, from a list of ids."""
    template = {"$keyed": {"source": "${ids}", "key": "${item}", "value": {"t": "a"}}}
    assert _bind(template, {"ids": ["u1", "u2"]}) == {"u1": {"t": "a"}, "u2": {"t": "a"}}
    assert _bind(template, {}) is MISSING


def test_template_arguments_ignores_map_bindings() -> None:
    template = {"$map": {"source": "${rows}", "template": {"v": "${item}", "n": "${index}"}}}
    assert template_arguments(template) == {"rows"}
    assert template_arguments({"$keyed": {"source": "${ids}", "key": "${item}"}}) == {"ids"}
    # ...but a real argument called index is still seen.
    assert template_arguments({"a": "${index}"}) == {"index"}


def test_when_drops_an_object_that_lost_its_content() -> None:
    """Without the guard, only the defaults would survive and be sent."""
    template = {"subject": "${subject}", "body": {"$when": "${body}", "contentType": "${body_type}", "content": "${body}"}}
    assert _bind(template, {"subject": "New", "body_type": "HTML"}) == {"subject": "New"}
    assert _bind(template, {"subject": "New", "body_type": "HTML", "body": "hi"}) == {
        "subject": "New", "body": {"contentType": "HTML", "content": "hi"}
    }
    # At the root, everything dropping means "no body at all", which build()
    # turns into a request that sends none.
    assert _bind({"body": {"$when": "${body}", "content": "${body}"}}, {}) is MISSING


def test_an_object_that_wanted_content_and_got_none_drops() -> None:
    assert _bind({"assignee": {"id": "${a}"}, "summary": "${s}"}, {"s": "t"}) == {"summary": "t"}


def test_a_literal_empty_object_is_preserved() -> None:
    """Drive asks for `folder: {}` to mean "make this a folder"."""
    assert _bind({"folder": {}, "name": "${n}"}, {"n": "x"}) == {"folder": {}, "name": "x"}


def test_a_list_of_templated_items_drops_when_they_all_do() -> None:
    assert _bind({"limit": 50, "filterGroups": [{"filters": "${f}"}]}, {}) == {"limit": 50}


def test_form_pairs_uses_bracket_notation() -> None:
    pairs = form_pairs({"metadata": {"tier": "gold"}, "items": [{"price": "p1"}], "live": True})
    assert ("metadata[tier]", "gold") in pairs
    assert ("items[0][price]", "p1") in pairs
    assert ("live", "true") in pairs


# -- request building --------------------------------------------------------


def test_graph_send_mail_request(manager: ConnectorManager) -> None:
    request = manager.prepare_tool_request(
        connection(), "send_email_with_file_attachments",
        {
            "to": ["ada@example.com"],
            "subject": "Q3",
            "body": "<p>see attached</p>",
            "attachments": [{"name": "q3.pdf", "content_bytes": "QUJD", "content_type": "application/pdf"}],
        },
    )
    assert request.method == "POST"
    assert request.url == "https://graph.microsoft.com/v1.0/me/sendMail"
    assert request.headers["authorization"] == "Bearer test-token"
    message = request.json_body["message"]
    assert message["toRecipients"] == [{"emailAddress": {"address": "ada@example.com"}}]
    assert message["attachments"][0]["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert "bccRecipients" not in message  # omitted optional argument, not null


def test_path_arguments_are_percent_encoded(manager: ConnectorManager) -> None:
    request = manager.prepare_tool_request(connection(), "get_message", {"message_id": "a/b?c"})
    assert request.url.endswith("/v1.0/me/messages/a%2Fb%3Fc")


def test_query_values_are_stringified(manager: ConnectorManager) -> None:
    request = manager.prepare_tool_request(
        connection(), "list_messages", {"limit": 10, "select": ["subject", "from"]}
    )
    assert request.params["$top"] == "10"
    assert request.params["$select"] == "subject,from"


def test_connection_config_resolves_in_a_path(manager: ConnectorManager) -> None:
    conn = connection("jira", connection_config={"cloudId": "abc-123"})
    request = manager.prepare_tool_request(conn, "get_issue", {"issue_key": "ENG-1"})
    assert request.url == "https://api.atlassian.com/ex/jira/abc-123/rest/api/3/issue/ENG-1"


def test_form_encoded_connectors_send_a_form_body(manager: ConnectorManager) -> None:
    conn = connection("stripe", credentials={"scope": "read_write"})
    request = manager.prepare_tool_request(
        conn, "create_customer", {"email": "a@b.com", "metadata": {"tier": "gold"}}
    )
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.json_body is None
    assert "metadata%5Btier%5D=gold" in request.content


def test_base_url_override_wins(manager: ConnectorManager) -> None:
    request = manager.prepare_tool_request(connection("jira"), "list_accessible_sites", {})
    assert request.url == "https://api.atlassian.com/oauth/token/accessible-resources"


def test_gmail_builds_a_real_mime_message(manager: ConnectorManager) -> None:
    request = manager.prepare_tool_request(
        connection("google-mail"), "send_email_with_attachments",
        {
            "to": ["ada@example.com"],
            "subject": "Report",
            "body": "<b>attached</b>",
            "attachments": [
                {"name": "a.txt", "content_bytes": base64.b64encode(b"hello").decode(), "content_type": "text/plain"}
            ],
        },
    )
    raw = base64.urlsafe_b64decode(request.json_body["raw"])
    message = message_from_bytes(raw)
    assert message["To"] == "ada@example.com"
    assert message["Subject"] == "Report"
    filenames = [p.get_filename() for p in message.walk()]
    assert "a.txt" in filenames


def test_twilio_path_reads_the_account_sid_from_credentials(manager: ConnectorManager) -> None:
    conn = Connection(
        connection_id="c1", connector_id="twilio", auth_mode="BASIC",
        credentials={"username": "AC123", "password": "secret"},
    )
    request = manager.prepare_tool_request(conn, "send_sms", {"to": "+15550001111", "body": "hi"})
    assert request.url == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert request.headers["authorization"].startswith("Basic ")
    assert "To=%2B15550001111" in request.content


def test_a_partial_update_does_not_wipe_the_field_it_omits(manager: ConnectorManager) -> None:
    """Renaming a draft must not PATCH an empty body over its content."""
    request = manager.prepare_tool_request(
        connection(), "update_draft", {"message_id": "m1", "subject": "New"}
    )
    assert request.json_body == {"subject": "New"}


def test_a_partial_event_update_omits_the_times_it_was_not_given(manager: ConnectorManager) -> None:
    request = manager.prepare_tool_request(
        connection(), "update_event", {"event_id": "e1", "subject": "New"}
    )
    assert request.json_body == {"subject": "New"}


def test_a_search_with_no_filters_sends_no_filter_group(manager: ConnectorManager) -> None:
    """HubSpot rejects a filter group with no filters in it."""
    conn = connection("hubspot")
    assert manager.prepare_tool_request(conn, "search_deals", {"query": "acme"}).json_body == {
        "query": "acme", "limit": 50
    }


def test_a_templated_send_omits_the_empty_content_block(manager: ConnectorManager) -> None:
    """SendGrid rejects a content entry with a type and no value."""
    request = manager.prepare_tool_request(
        connection("sendgrid", auth_mode="API_KEY"),
        "send_email",
        {"to": ["a@b.com"], "from_email": "c@d.com", "template_id": "d-1"},
    )
    assert "content" not in request.json_body
    assert request.json_body["template_id"] == "d-1"


# -- scopes ------------------------------------------------------------------


def test_scope_string_parsing() -> None:
    assert parse_scope_string("a b c") == ["a", "b", "c"]
    assert parse_scope_string("a,b, c") == ["a", "b", "c"]
    assert parse_scope_string(["a", "b"]) == ["a", "b"]
    assert parse_scope_string(None) == []


def test_connection_scopes_prefers_metadata() -> None:
    conn = connection(credentials={"scope": "from-credentials"})
    conn.metadata["granted_scopes"] = ["from-metadata"]
    assert connection_scopes(conn) == (["from-metadata"], "metadata.granted_scopes")


def test_scope_rules_expand_transitively() -> None:
    rules = ScopeRules(case_insensitive=True, implies={"a": ["b"], "b": ["c"]})
    assert rules.expand(["A"]) == {"a", "b", "c"}


def test_grouped_scopes_survive_splitting() -> None:
    """Accelo grants read(companies,contacts) as one scope, not two."""
    assert parse_scope_string("read(companies,contacts),write(staff)") == [
        "read(companies,contacts)",
        "write(staff)",
    ]
    # A separator inside parentheses is the only one that is spared.
    assert parse_scope_string("read(a,b) write(c)") == ["read(a,b)", "write(c)"]


def test_grouped_scopes_expand_to_one_scope_each() -> None:
    rules = ScopeRules(expand_groups=True, implies={"write(tasks)": ["read(tasks)"]})
    assert rules.expand(["read(companies,contacts)", "write(tasks)"]) == {
        "read(companies)",
        "read(contacts)",
        "write(tasks)",
        "read(tasks)",
    }


def test_grouped_scopes_are_left_alone_unless_asked_for() -> None:
    """Off by default: no other provider means read(a,b) as two grants."""
    assert ScopeRules().expand(["read(a,b)"]) == {"read(a,b)"}


def test_accelo_reports_a_grouped_grant_correctly() -> None:
    """The pack that motivated the rule, judged end to end."""
    manager = ConnectorManager()
    conn = Connection(
        connection_id="c",
        connector_id="accelo",
        auth_mode="OAUTH2",
        credentials={"access_token": "t", "scope": "read(companies,contacts),write(tasks)"},
        connection_config={"subdomain": "acme"},
    )
    enabled = {s.tool.name for s in manager.check_tools(conn).enabled}
    assert {"list_companies", "get_contact"} <= enabled
    # write(tasks) carries read(tasks) with it, and nothing beyond tasks.
    assert {"create_task", "list_tasks"} <= enabled
    assert "create_company" not in enabled


def test_scope_rules_strip_google_prefix() -> None:
    rules = ScopeRules(strip_prefixes=["https://www.googleapis.com/auth/"])
    assert rules.normalize("https://www.googleapis.com/auth/gmail.send") == "gmail.send"


def test_report_splits_tools_by_grant(manager: ConnectorManager) -> None:
    conn = connection(credentials={"scope": "Mail.Read Mail.ReadWrite"})
    report = manager.check_tools(conn)
    assert report.status("list_messages").availability is ToolAvailability.ENABLED
    assert report.status("create_draft").availability is ToolAvailability.ENABLED  # Mail.ReadWrite
    send = report.status("send_email")
    assert send.availability is ToolAvailability.DISABLED
    assert send.missing_scopes == ["Mail.Send"]
    assert "Mail.Send" in report.missing_scopes()
    assert report.counts()["enabled"] + report.counts()["disabled"] == report.counts()["total"]


def test_scopes_any_needs_only_one(manager: ConnectorManager) -> None:
    conn = connection("google-mail", credentials={"scope": "https://www.googleapis.com/auth/gmail.send"})
    report = manager.check_tools(conn)
    assert report.status("send_email").enabled
    assert not report.status("list_messages").enabled


def test_implied_scope_enables_a_tool(manager: ConnectorManager) -> None:
    """Gmail's full-mailbox scope implies the narrower ones it covers.

    It does not cover everything: Google gates delegates, forwarding addresses
    and send-as identities on `gmail.settings.sharing`, which
    `https://mail.google.com/` does not grant. That the report says so is the
    point of scope checking, so this asserts both halves.
    """
    conn = connection("google-mail", credentials={"scope": "https://mail.google.com/"})
    report = manager.check_tools(conn)

    for name in ("list_messages", "send_email", "create_draft", "trash_message"):
        assert report.status(name).enabled, name

    disabled = set(report.disabled_names())
    assert disabled, "the sharing-gated settings tools should be reported disabled"
    for name in disabled:
        assert report.status(name).missing_scopes == ["gmail.settings.sharing"], name


def test_unknown_grant_reports_unknown_not_disabled(manager: ConnectorManager) -> None:
    report = manager.check_tools(connection())
    assert report.granted_scopes is None
    assert report.scope_source == "unknown"
    assert not report.disabled
    assert {s.availability for s in report.statuses} == {ToolAvailability.UNKNOWN}


def test_scopeless_tools_are_always_enabled(manager: ConnectorManager) -> None:
    """Notion gates on page sharing, not scopes, so nothing is ever disabled."""
    report = manager.check_tools(connection("notion"))
    assert report.disabled_names() == []
    assert report.enabled_names() == [t.name for t in manager.list_tools("notion")]


def test_enabled_specs_exclude_what_the_grant_forbids(manager: ConnectorManager) -> None:
    conn = connection(credentials={"scope": "Mail.Read"})
    names = {spec["name"] for spec in manager.enabled_tool_specs(conn)}
    assert "list_messages" in names
    assert "send_email" not in names


def test_explicit_scopes_override_the_connection(manager: ConnectorManager) -> None:
    report = manager.check_tools(connection(), granted_scopes=["Mail.Send"])
    assert report.status("send_email").enabled
    assert not report.status("list_messages").enabled


# -- calling tools -----------------------------------------------------------


@respx.mock
def test_call_tool_parses_the_response(manager: ConnectorManager) -> None:
    route = respx.get("https://api.hubapi.com/crm/v3/objects/contacts/42").mock(
        return_value=httpx.Response(200, json={"id": "42", "properties": {"email": "a@b.com"}})
    )
    conn = connection("hubspot", credentials={"scope": "crm.objects.contacts.read"})
    result = manager.call_tool(conn, "get_contact", {"contact_id": "42"})
    assert route.called
    assert result.ok and result.status == 200
    assert result.data["properties"]["email"] == "a@b.com"


@respx.mock
def test_response_path_unwraps_the_envelope(manager: ConnectorManager) -> None:
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}], "@odata.nextLink": "..."})
    )
    result = manager.call_tool(connection(), "list_messages", {})
    assert result.data == [{"id": "m1"}]


@respx.mock
def test_error_responses_carry_a_readable_reason(manager: ConnectorManager) -> None:
    respx.get("https://graph.microsoft.com/v1.0/me/messages").mock(
        return_value=httpx.Response(403, json={"error": {"code": "Forbidden", "message": "Access denied"}})
    )
    result = manager.call_tool(connection(), "list_messages", {})
    assert not result.ok
    assert result.error == "HTTP 403: Access denied"


def test_call_tool_refuses_a_known_scope_shortfall(manager: ConnectorManager) -> None:
    conn = connection(credentials={"scope": "Mail.Read"})
    with pytest.raises(ToolPermissionError) as err:
        manager.call_tool(conn, "send_email", {"to": ["a@b.com"], "subject": "x", "body": "y"})
    assert err.value.missing_scopes == ["Mail.Send"]


@respx.mock
def test_enforce_scopes_can_be_turned_off(manager: ConnectorManager) -> None:
    route = respx.post("https://graph.microsoft.com/v1.0/me/sendMail").mock(
        return_value=httpx.Response(202, text="")
    )
    conn = connection(credentials={"scope": "Mail.Read"})
    result = manager.call_tool(
        conn, "send_email", {"to": ["a@b.com"], "subject": "x", "body": "y"}, enforce_scopes=False
    )
    assert route.called and result.ok


def test_an_unknown_grant_does_not_block_a_call(manager: ConnectorManager) -> None:
    """No scope information must not become a refusal -- the provider decides."""
    with respx.mock:
        route = respx.post("https://graph.microsoft.com/v1.0/me/sendMail").mock(
            return_value=httpx.Response(202, text="")
        )
        result = manager.call_tool(
            connection(), "send_email", {"to": ["a@b.com"], "subject": "x", "body": "y"}
        )
    assert route.called and result.ok


@respx.mock
def test_call_tool_validates_before_sending(manager: ConnectorManager) -> None:
    route = respx.post("https://graph.microsoft.com/v1.0/me/sendMail")
    with pytest.raises(ToolValidationError):
        manager.call_tool(connection(), "send_email", {"to": ["a@b.com"]})
    assert not route.called


# -- scope discovery ---------------------------------------------------------


@respx.mock
def test_discover_scopes_from_a_token_info_endpoint(manager: ConnectorManager) -> None:
    respx.get("https://api.hubapi.com/oauth/v1/access-tokens/test-token").mock(
        return_value=httpx.Response(200, json={"scopes": ["crm.objects.contacts.read", "oauth"]})
    )
    discovery = manager.discover_scopes(connection("hubspot"))
    assert discovery.known and discovery.tested
    assert discovery.source == "provider"
    assert "crm.objects.contacts.read" in discovery.scopes


@respx.mock
def test_check_tools_live_uses_the_discovered_grant(manager: ConnectorManager) -> None:
    respx.get("https://api.hubapi.com/oauth/v1/access-tokens/test-token").mock(
        return_value=httpx.Response(200, json={"scopes": ["crm.objects.contacts.read"]})
    )
    report = manager.check_tools_live(connection("hubspot"))
    assert report.scope_source == "provider"
    assert report.status("list_contacts").enabled
    assert not report.status("create_contact").enabled


@respx.mock
def test_discovery_from_a_response_header(manager: ConnectorManager) -> None:
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"login": "ada"}, headers={"x-oauth-scopes": "repo, workflow"})
    )
    discovery = manager.discover_scopes(connection("github"))
    assert discovery.scopes == ["repo", "workflow"]


def test_discovery_from_the_access_token_claims(manager: ConnectorManager) -> None:
    """A Graph token is a JWT whose scp claim is the grant -- no request needed."""
    import jwt

    token = jwt.encode({"scp": "Mail.Read Mail.Send"}, "secret", algorithm="HS256")
    discovery = manager.discover_scopes(connection(credentials={"access_token": token}))
    assert discovery.source == "access_token"
    assert discovery.scopes == ["Mail.Read", "Mail.Send"]
    assert not discovery.tested  # nothing was sent


def test_discovery_falls_back_when_the_token_is_opaque(manager: ConnectorManager) -> None:
    conn = connection(credentials={"access_token": "not-a-jwt", "scope": "Mail.Read"})
    discovery = manager.discover_scopes(conn)
    assert discovery.scopes == ["Mail.Read"]
    assert discovery.source == "credentials.scope"


def test_discovery_without_a_declared_endpoint_reads_the_connection(manager: ConnectorManager) -> None:
    conn = connection("notion", credentials={"scope": "x"})
    discovery = manager.discover_scopes(conn)
    assert discovery.scopes == ["x"]
    assert not discovery.tested


@respx.mock
def test_a_failed_discovery_call_does_not_raise(manager: ConnectorManager) -> None:
    respx.get("https://api.hubapi.com/oauth/v1/access-tokens/test-token").mock(
        return_value=httpx.Response(401, json={"message": "expired"})
    )
    discovery = manager.discover_scopes(connection("hubspot"))
    assert not discovery.known
    assert "401" in discovery.reason


# -- async parity ------------------------------------------------------------


@pytest.mark.anyio
async def test_async_manager_shares_the_tool_layer() -> None:
    async with AsyncConnectorManager() as manager:
        assert manager.has_tools("slack")
        with respx.mock:
            respx.post("https://slack.com/api/chat.postMessage").mock(
                return_value=httpx.Response(200, json={"ok": True, "ts": "1.2"})
            )
            conn = connection("slack", credentials={"scope": "chat:write"})
            result = await manager.call_tool(conn, "send_message", {"channel": "C1", "text": "hi"})
        assert result.ok and result.data["ts"] == "1.2"


@pytest.mark.anyio
async def test_async_scope_discovery() -> None:
    async with AsyncConnectorManager() as manager:
        with respx.mock:
            respx.get("https://api.hubapi.com/oauth/v1/access-tokens/test-token").mock(
                return_value=httpx.Response(200, json={"scopes": ["oauth"]})
            )
            report = await manager.check_tools_live(connection("hubspot"))
        assert report.granted_scopes == ["oauth"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# -- serialisation -----------------------------------------------------------


def test_report_is_json_ready(manager: ConnectorManager) -> None:
    conn = connection(credentials={"scope": "Mail.Read"})
    payload = json.loads(json.dumps(manager.check_tools(conn).to_dict()))
    assert payload["counts"]["total"] == len(manager.list_tools("outlook"))
    assert payload["connector_id"] == "outlook"
    disabled = [t for t in payload["tools"] if t["availability"] == "disabled"]
    assert disabled and all(t["missing_scopes"] for t in disabled)


def test_describe_tools_is_json_ready(manager: ConnectorManager) -> None:
    payload = json.loads(json.dumps(manager.describe_tools("slack")))
    assert payload["tool_count"] == len(manager.list_tools("slack"))
    assert payload["scope_discovery"]["scopes_path"] == "header:x-oauth-scopes"


def test_tool_request_defaults_are_sane() -> None:
    request = ToolRequest()
    assert request.method == "GET" and request.encoding == "json"
    tool = Tool(connector_id="x", name="y")
    assert tool.qualified_name == "x.y"
    assert tool.input_schema()["required"] == []


# -- CLI ---------------------------------------------------------------------


def _connection_file(tmp_path, scope: str = "Mail.Read Mail.ReadWrite"):
    path = tmp_path / "conn.json"
    path.write_text(
        json.dumps(
            {
                "connection_id": "c1",
                "connector_id": "outlook",
                "auth_mode": "OAUTH2",
                "credentials": {"access_token": "tok", "scope": scope},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cli_tools_listing(capsys) -> None:
    from connector_manager.__main__ import main

    assert main(["tools", "outlook"]) == 0
    out = capsys.readouterr().out
    assert "also serves : outlook" in out
    assert "send_email_with_file_attachments" in out


def test_cli_tool_specs_are_json(capsys) -> None:
    from connector_manager.__main__ import main

    assert main(["tools", "slack", "--format", "openai"]) == 0
    specs = json.loads(capsys.readouterr().out)
    assert all(spec["type"] == "function" for spec in specs)


def test_cli_tool_detail(capsys) -> None:
    from connector_manager.__main__ import main

    assert main(["tool", "hubspot", "create_contact"]) == 0
    out = capsys.readouterr().out
    assert "POST /crm/v3/objects/contacts" in out
    assert "crm.objects.contacts.write" in out


def test_cli_check_tools(tmp_path, capsys) -> None:
    from connector_manager.__main__ import main

    assert main(["check-tools", str(_connection_file(tmp_path))]) == 0
    captured = capsys.readouterr()
    assert "tools enabled" in captured.out
    assert "- send_email" in captured.out
    assert "Mail.Send" in captured.err  # the "request these scopes" hint


def test_cli_check_tools_json(tmp_path, capsys) -> None:
    from connector_manager.__main__ import main

    assert main(["check-tools", str(_connection_file(tmp_path)), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["disabled"] > 0
    assert report["scope_source"] == "credentials.scope"


def test_cli_call_dry_run_hides_the_token(tmp_path, capsys) -> None:
    from connector_manager.__main__ import main

    code = main(
        [
            "call", str(_connection_file(tmp_path)), "create_draft",
            "-a", "subject=Hi", "-a", "body=<p>hi</p>", "-a", 'to:=["ada@example.com"]',
            "--dry-run",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["url"].endswith("/v1.0/me/messages")
    assert payload["headers"]["authorization"] == "<redacted>"


def test_cli_call_typed_arguments_must_be_valid_json(tmp_path) -> None:
    from connector_manager.__main__ import main

    with pytest.raises(SystemExit, match="invalid JSON"):
        main(["call", str(_connection_file(tmp_path)), "create_draft", "-a", "to:=[oops"])


def test_cli_reports_a_scope_shortfall_as_an_error(tmp_path, capsys) -> None:
    from connector_manager.__main__ import main

    code = main(
        [
            "call", str(_connection_file(tmp_path, scope="Mail.Read")), "send_email",
            "-a", "subject=Hi", "-a", "body=x", "-a", 'to:=["a@b.com"]',
        ]
    )
    assert code == 1
    assert "Mail.Send" in capsys.readouterr().err


def test_cli_stats_counts_tools(capsys) -> None:
    from connector_manager.__main__ import main

    assert main(["stats"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["tools"]["tools"] > 400


# -- generated baseline tools ------------------------------------------------


def test_a_connector_without_a_pack_still_gets_a_real_tool(manager: ConnectorManager) -> None:
    """700-odd connectors declare a verification endpoint; that is a real tool."""
    assert not manager.has_authored_tools("manatal")
    assert manager.has_tools("manatal")
    names = [t.name for t in manager.list_tools("manatal")]
    # The declared verification endpoint, plus the universal raw escape hatches.
    assert names[0] == "check_connection"
    assert {"get_from_api", "post_to_api", "delete_from_api"} <= set(names)
    assert all(t.generated for t in manager.list_tools("manatal"))
    assert manager.tool_pack("manatal").generated is True


def test_the_generated_tool_builds_the_declared_endpoint(manager: ConnectorManager) -> None:
    conn = Connection(
        connection_id="c1", connector_id="manatal",
        auth_mode=manager.get_connector("manatal").auth_mode,
        credentials={"apiKey": "k", "access_token": "t"},
    )
    request = manager.prepare_tool_request(conn, "check_connection", {})
    provider = manager.registry.raw("manatal")
    declared = provider["proxy"]["verification"]["endpoints"][0]
    assert request.method == "GET"
    assert request.url.endswith(declared)


def test_no_check_connection_without_a_declared_endpoint(manager: ConnectorManager) -> None:
    """Nothing is invented: no verification endpoint means no check_connection.

    The connector still gets the raw request tools, which claim nothing about
    its API -- but it gets no endpoint this package did not find in the
    catalogue.
    """
    bare = next(
        c for c in manager.registry
        if not manager.has_authored_tools(c.id)
        and not (c.raw.get("proxy") or {}).get("verification")
        and c.base_url
    )
    names = {t.name for t in manager.list_tools(bare.id)}
    assert "check_connection" not in names
    assert "get_from_api" in names


def test_authored_packs_are_never_shadowed(manager: ConnectorManager) -> None:
    assert manager.has_authored_tools("hubspot")
    assert not manager.tool_pack("hubspot").generated
    assert len(manager.list_tools("hubspot")) > 1


def test_stats_separate_authored_from_generated(manager: ConnectorManager) -> None:
    stats = manager.tool_stats()
    assert stats["connectors_covered"] == len(manager.tool_connectors())
    assert stats["generated_connectors"] > 500
    assert (
        stats["connectors_with_any_tool"] + stats["connectors_without_tools"]
        == len(manager.registry)
    )
    assert len(manager.tool_connectors(include_generated=True)) == stats["connectors_with_any_tool"]


def test_generated_tools_are_json_serialisable(manager: ConnectorManager) -> None:
    payload = json.loads(json.dumps(manager.describe_tools("manatal")))
    assert payload["generated"] is True
    assert payload["tools"][0]["generated"] is True


def test_a_numeric_argument_in_a_header_is_rendered_as_text(manager: ConnectorManager) -> None:
    """Greenhouse's On-Behalf-Of is a user id; a header value must still be a string."""
    conn = Connection(
        connection_id="c1", connector_id="greenhouse", auth_mode="OAUTH2",
        credentials={"access_token": "t"}, connection_config={"resource": "harvest"},
    )
    request = manager.prepare_tool_request(
        conn, "add_candidate_note",
        {"candidate_id": 1, "body": "hi", "user_id": 2, "on_behalf_of": 3},
    )
    assert request.headers["on-behalf-of"] == "3"
    assert all(isinstance(v, str) for v in request.headers.values())


# -- the universal raw-request fallback --------------------------------------


def test_every_connector_with_a_base_url_is_drivable(manager: ConnectorManager) -> None:
    """No connector with an address should be dark, even with no pack written."""
    without = [
        c.id for c in manager.registry
        if c.base_url and not manager.has_tools(c.id)
    ]
    assert without == [], f"connectors with a base url but no tools: {without[:10]}"


#: A connector with a plain base url, an x-api-key header and no pack of its own,
#: which is what these tests need: the raw tier only shows where nothing authored
#: covers the connector. Swap it if `aiprise` ever gains a pack -- the neighbouring
#: test_raw_tools_never_shadow_an_authored_pack is what will tell you.
RAW_TIER_CONNECTOR = "aiprise"


def test_the_raw_tier_fixture_still_has_no_pack(manager: ConnectorManager) -> None:
    """Guards the three tests below, which need a pack-free connector."""
    assert not manager.has_authored_tools(RAW_TIER_CONNECTOR)


def test_raw_tools_build_a_real_authenticated_request(manager: ConnectorManager) -> None:
    conn = Connection(
        connection_id="c1", connector_id=RAW_TIER_CONNECTOR, auth_mode="API_KEY",
        credentials={"apiKey": "secret-key"},
    )
    request = manager.prepare_tool_request(
        conn, "get_from_api", {"path": "/v1/leads", "query": {"limit": 25}}
    )
    assert request.method == "GET"
    assert request.url == "https://api.aiprise.com/v1/leads"
    assert request.params == {"limit": "25"}
    assert request.headers["x-api-key"] == "secret-key"


def test_a_whole_path_argument_keeps_its_slashes(manager: ConnectorManager) -> None:
    """A whole-path slot is structural; only path *segments* are encoded."""
    conn = Connection(connection_id="c1", connector_id=RAW_TIER_CONNECTOR, auth_mode="API_KEY",
                      credentials={"apiKey": "k"})
    request = manager.prepare_tool_request(conn, "get_from_api", {"path": "v1/leads/42/notes"})
    assert request.url.endswith("/v1/leads/42/notes")


def test_raw_write_tools_send_the_body_and_flag_deletes(manager: ConnectorManager) -> None:
    conn = Connection(connection_id="c1", connector_id=RAW_TIER_CONNECTOR, auth_mode="API_KEY",
                      credentials={"apiKey": "k"})
    request = manager.prepare_tool_request(
        conn, "post_to_api", {"path": "/v1/leads", "body": {"name": "Ada"}}
    )
    assert request.json_body == {"name": "Ada"}
    assert manager.get_tool(RAW_TIER_CONNECTOR, "delete_from_api").destructive is True
    assert manager.get_tool(RAW_TIER_CONNECTOR, "get_from_api").read_only is True


def test_raw_tools_never_shadow_an_authored_pack(manager: ConnectorManager) -> None:
    assert "get_from_api" not in {t.name for t in manager.list_tools("hubspot")}
    assert manager.has_authored_tools("hubspot")
