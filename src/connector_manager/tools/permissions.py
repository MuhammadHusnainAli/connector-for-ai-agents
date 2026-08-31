"""Deciding which tools a given credential is actually allowed to call.

Two halves:

* :func:`connection_scopes` reads the grant off a stored connection -- what the
  token response said, or what your OAuth layer recorded. No network.
* :class:`ScopeDiscoverer` asks the provider itself, either by decoding the
  access token's own claims or by calling its token-info endpoint. Written as a
  flow, so the sync and the async manager share one implementation.

Either way the answer feeds :func:`build_report`, which splits a connector's
tools into enabled / disabled / unknown and names the missing scopes.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from ..flows import Flow
from ..http import Request
from ..interpolation import extract_value_by_path
from ..models import Connection
from ..proxy import RequestBuilder
from .models import (
    ScopeDiscovery,
    Tool,
    ToolAvailability,
    ToolPack,
    ToolReport,
    ToolStatus,
    parse_scope_string,
)

#: Keys that carry a granted-scope list, checked in this order. The first two
#: are where your own OAuth layer would record what the user consented to; the
#: rest are what providers put in a token response.
_SCOPE_KEYS = ("granted_scopes", "scopes", "scope")


def connection_scopes(connection: Connection) -> tuple[list[str] | None, str]:
    """The scopes recorded on a connection, and where they were found.

    Returns ``(None, "unknown")`` when nothing on the connection says what was
    granted -- which is the common case for API keys, and is reported as
    *unknown* rather than *no scopes*.

    >>> conn = Connection(connection_id="", connector_id="hubspot",
    ...                   auth_mode="OAUTH2", credentials={"scope": "a b"})
    >>> connection_scopes(conn)
    (['a', 'b'], 'credentials.scope')
    """
    for label, source in (
        ("metadata", connection.metadata),
        ("credentials", connection.credentials),
        ("connection_config", connection.connection_config),
    ):
        for key in _SCOPE_KEYS:
            if key in source and source[key] not in (None, ""):
                scopes = parse_scope_string(source[key])
                if scopes:
                    return scopes, f"{label}.{key}"
    return None, "unknown"


def build_report(
    pack: ToolPack,
    connection: Connection | None = None,
    granted_scopes: Sequence[str] | None = None,
    scope_source: str = "unknown",
    connector_id: str | None = None,
) -> ToolReport:
    """Judge every tool in ``pack`` against a grant.

    A tool that declares no scopes is always enabled: the provider gates it on
    the credential existing, not on a scope. A tool that does declare scopes is
    enabled when the grant covers them (after the pack's normalisation rules),
    disabled with the shortfall named when it does not, and *unknown* when the
    grant itself could not be determined.
    """
    if granted_scopes is None and connection is not None:
        granted_scopes, scope_source = connection_scopes(connection)

    statuses: list[ToolStatus] = []
    for tool in pack.tools.values():
        statuses.append(_status(pack, tool, granted_scopes))

    return ToolReport(
        connector_id=connector_id or (connection.connector_id if connection else pack.connector_id),
        connection_id=connection.connection_id if connection else "",
        granted_scopes=list(granted_scopes) if granted_scopes is not None else None,
        scope_source=scope_source,
        statuses=statuses,
    )


def _status(pack: ToolPack, tool: Tool, granted: Sequence[str] | None) -> ToolStatus:
    if not tool.required_scopes:
        return ToolStatus(
            tool=tool,
            availability=ToolAvailability.ENABLED,
            reason="Needs no scope beyond a valid credential.",
        )
    if granted is None:
        return ToolStatus(
            tool=tool,
            availability=ToolAvailability.UNKNOWN,
            missing_scopes=[],
            reason=(
                "The granted scopes for this connection are not known. Record them on "
                "the connection, or call discover_scopes() to ask the provider."
            ),
        )
    missing = pack.scope_rules.missing(tool, granted)
    if missing:
        return ToolStatus(
            tool=tool,
            availability=ToolAvailability.DISABLED,
            missing_scopes=missing,
            reason=f"Credential is missing: {', '.join(missing)}",
        )
    return ToolStatus(
        tool=tool,
        availability=ToolAvailability.ENABLED,
        reason="All required scopes are granted.",
    )


def check_arguments_against_report(report: ToolReport, name: str) -> list[str]:
    """The missing scopes for ``name``, empty when it is callable."""
    status = report.status(name)
    return list(status.missing_scopes) if status and not status.enabled else []


class ScopeDiscoverer:
    """Asks the provider which scopes a live credential really carries.

    Providers expose this in one of two ways, and the pack declares which:

    * the access token is a JWT whose ``scp``/``roles`` claim *is* the grant --
      read locally, no request at all (Microsoft, Salesforce);
    * a token-info endpoint returns them (HubSpot, Google, Slack, GitHub's
      ``x-oauth-scopes`` response header).

    With neither declared, it falls back to whatever the connection recorded, so
    the caller always gets an answer of some kind.
    """

    def __init__(self, provider: dict[str, Any], pack: ToolPack, connection: Connection) -> None:
        self.provider = provider
        self.pack = pack
        self.connection = connection
        self.builder = RequestBuilder(provider, connection)

    def flow(self) -> Flow[ScopeDiscovery]:
        spec = self.pack.scope_discovery
        if spec is None:
            scopes, source = connection_scopes(self.connection)
            return ScopeDiscovery(
                scopes=scopes,
                source=source,
                tested=False,
                reason=(
                    None
                    if scopes is not None
                    else f"Connector '{self.pack.connector_id}' declares no scope-discovery endpoint."
                ),
            )

        if spec.is_local:
            return self._from_token_claim(spec.jwt_claim or "scp", spec.separator)

        builder = self.builder
        if spec.base_url_override:
            builder = RequestBuilder(
                {**self.provider, "proxy": {**(self.provider.get("proxy") or {}), "base_url": spec.base_url_override}},
                self.connection,
            )
        request: Request = builder.build(
            spec.method, spec.endpoint, headers=spec.headers, params=spec.query
        )
        response = yield request

        if not response.ok:
            scopes, source = connection_scopes(self.connection)
            return ScopeDiscovery(
                scopes=scopes,
                source=source if scopes is not None else "unknown",
                tested=True,
                reason=f"Scope discovery returned {response.status}",
            )

        # A few providers answer in a header instead of the body (GitHub).
        header_name = spec.scopes_path[len("header:") :] if spec.scopes_path.startswith("header:") else None
        if header_name:
            raw: Any = response.headers.get(header_name.lower())
        else:
            raw = extract_value_by_path(response.json(), spec.scopes_path)

        scopes = parse_scope_string(raw, spec.separator)
        if not scopes:
            return ScopeDiscovery(
                scopes=None,
                source="unknown",
                tested=True,
                reason=f"No scopes at '{spec.scopes_path}' in the provider's response",
            )
        return ScopeDiscovery(scopes=scopes, source="provider", tested=True)

    # -- internals ---------------------------------------------------------

    def _from_token_claim(self, claim: str, separator: str) -> ScopeDiscovery:
        token = self.connection.access_token
        if not token:
            return ScopeDiscovery(
                scopes=None, source="unknown", reason="Connection carries no access token"
            )
        try:
            import jwt

            payload = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
        except Exception as err:  # noqa: BLE001 - any decode failure means "cannot tell"
            scopes, source = connection_scopes(self.connection)
            return ScopeDiscovery(
                scopes=scopes,
                source=source if scopes is not None else "unknown",
                reason=f"Access token is not a readable JWT ({type(err).__name__})",
            )
        # ``scp`` is delegated permissions, ``roles`` application ones; a
        # client-credentials token carries the latter, so accept either.
        raw = payload.get(claim)
        if raw in (None, "", []) and claim == "scp":
            raw = payload.get("roles")
        scopes = parse_scope_string(raw, separator)
        if not scopes:
            return ScopeDiscovery(
                scopes=None,
                source="unknown",
                reason=f"Access token carries no '{claim}' claim",
            )
        return ScopeDiscovery(scopes=scopes, source="access_token", tested=False)


def normalize_all(rules: Any, scopes: Iterable[str]) -> list[str]:
    """Every scope in ``scopes`` as the pack's rules would compare it."""
    return sorted(rules.expand(scopes))
