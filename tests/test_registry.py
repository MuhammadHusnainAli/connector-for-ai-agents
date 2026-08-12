"""Registry / catalogue coverage across the whole bundled provider set."""

from __future__ import annotations

import pytest

from connector_manager import AuthMode, ConnectorRegistry


@pytest.fixture(scope="module")
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


def test_loads_the_full_catalogue(registry: ConnectorRegistry) -> None:
    assert len(registry) > 900
    assert "slack" in registry
    assert registry.get("slack").display_name == "Slack"


def test_every_connector_has_name_and_auth_mode(registry: ConnectorRegistry) -> None:
    for connector in registry:
        assert connector.display_name, connector.id
        assert isinstance(connector.auth_mode, AuthMode), connector.id


def test_every_connector_has_an_icon(registry: ConnectorRegistry) -> None:
    missing = [c.id for c in registry if not c.icon_svg]
    assert missing == []


def test_icons_are_svg(registry: ConnectorRegistry) -> None:
    icon = registry.icon("stripe")
    assert icon is not None and "<svg" in icon


def test_aliases_inherit_their_target(registry: ConnectorRegistry) -> None:
    aliased = [c for c in registry if c.alias]
    assert aliased, "expected providers.yaml to contain aliases"
    for connector in aliased:
        target = registry.get(connector.alias)
        # An alias keeps the target's auth mode unless it overrides it explicitly.
        assert connector.auth_mode is target.auth_mode or "auth_mode" in connector.raw


def test_auth_schema_builds_for_every_connector(registry: ConnectorRegistry) -> None:
    for connector in registry:
        schema = registry.auth_schema(connector.id)
        assert schema.connector_id == connector.id
        assert schema.auth_mode is connector.auth_mode
        for field in schema.fields:
            assert field.name
            assert field.group


def test_self_service_connectors_declare_credential_fields(registry: ConnectorRegistry) -> None:
    """Anything we can connect without OAuth must tell the user what to enter."""
    needs_input = {
        AuthMode.API_KEY,
        AuthMode.BASIC,
        AuthMode.OAUTH2_CC,
        AuthMode.TWO_STEP,
        AuthMode.JWT,
        AuthMode.SIGNATURE,
        AuthMode.TBA,
        AuthMode.INSTALL_PLUGIN,
    }
    for connector in registry:
        if connector.auth_mode not in needs_input:
            continue
        schema = registry.auth_schema(connector.id)
        assert schema.credentials, f"{connector.id} has no credential fields"


def test_filters(registry: ConnectorRegistry) -> None:
    crm = registry.list(category="crm")
    assert crm and all("crm" in c.categories for c in crm)

    api_key = registry.list(auth_mode="API_KEY")
    assert api_key and all(c.auth_mode is AuthMode.API_KEY for c in api_key)

    searched = registry.list(search="slack")
    assert any(c.id == "slack" for c in searched)

    page = registry.list(limit=10, offset=5)
    assert len(page) == 10

    assert all(c.supported for c in registry.list(supported_only=True))


def test_unknown_connector_raises(registry: ConnectorRegistry) -> None:
    from connector_manager import UnknownConnectorError

    with pytest.raises(UnknownConnectorError):
        registry.get("definitely-not-a-provider")
