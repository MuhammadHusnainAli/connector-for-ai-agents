"""Data models exposed by the connector manager.

Everything here is a plain dataclass with ``to_dict`` / ``from_dict`` so the
caller can persist and transport objects (notably :class:`Connection`) with any
storage layer they like -- this package never stores anything itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class AuthMode(str, Enum):
    """The auth mechanisms connectors can use."""

    NONE = "NONE"
    API_KEY = "API_KEY"
    BASIC = "BASIC"
    OAUTH1 = "OAUTH1"
    OAUTH2 = "OAUTH2"
    OAUTH2_CC = "OAUTH2_CC"
    TWO_STEP = "TWO_STEP"
    JWT = "JWT"
    SIGNATURE = "SIGNATURE"
    TBA = "TBA"
    APP = "APP"
    CUSTOM = "CUSTOM"
    BILL = "BILL"
    AWS_SIGV4 = "AWS_SIGV4"
    INSTALL_PLUGIN = "INSTALL_PLUGIN"
    MCP_OAUTH2 = "MCP_OAUTH2"
    MCP_OAUTH2_GENERIC = "MCP_OAUTH2_GENERIC"

    @classmethod
    def parse(cls, value: str | None) -> "AuthMode":
        try:
            return cls(value or "NONE")
        except ValueError:
            return cls.NONE


#: Auth modes this package can complete end to end (no browser redirect needed).
SELF_SERVICE_MODES = frozenset(
    {
        AuthMode.NONE,
        AuthMode.API_KEY,
        AuthMode.BASIC,
        AuthMode.INSTALL_PLUGIN,
        AuthMode.OAUTH2_CC,
        AuthMode.TWO_STEP,
        AuthMode.JWT,
        AuthMode.SIGNATURE,
        AuthMode.TBA,
    }
)

#: Auth modes that require a redirect-based flow. Run that flow in your own
#: OAuth/security layer, then use ``ConnectorManager.import_connection``.
EXTERNAL_OAUTH_MODES = frozenset(
    {
        AuthMode.OAUTH1,
        AuthMode.OAUTH2,
        AuthMode.APP,
        AuthMode.CUSTOM,
        AuthMode.MCP_OAUTH2,
        AuthMode.MCP_OAUTH2_GENERIC,
    }
)

#: Auth modes with no handler yet -- ``connect`` raises ``UnsupportedAuthModeError``.
UNSUPPORTED_MODES = frozenset({AuthMode.BILL, AuthMode.AWS_SIGV4})


class FieldGroup(str, Enum):
    """Where a value belongs once collected."""

    CREDENTIALS = "credentials"
    CONNECTION_CONFIG = "connection_config"
    INTEGRATION_CONFIG = "integration_config"
    ASSERTION_OPTION = "assertion_option"


@dataclass(slots=True)
class AuthField:
    """One value the end user (or admin) has to supply.

    Built from a connector's ``credentials`` / ``connection_config`` /
    ``integration_config`` / ``assertion_option`` blocks.
    """

    name: str
    group: FieldGroup
    title: str = ""
    description: str = ""
    type: str = "string"
    required: bool = True
    secret: bool = False
    example: str | None = None
    pattern: str | None = None
    format: str | None = None
    default_value: str | None = None
    enum: list[str] = field(default_factory=list)
    prefix: str | None = None
    suffix: str | None = None
    order: int = 0
    automated: bool = False
    hidden: bool = False
    visible_when: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group.value,
            "title": self.title,
            "description": self.description,
            "type": self.type,
            "required": self.required,
            "secret": self.secret,
            "example": self.example,
            "pattern": self.pattern,
            "format": self.format,
            "default_value": self.default_value,
            "enum": list(self.enum),
            "prefix": self.prefix,
            "suffix": self.suffix,
            "order": self.order,
            "automated": self.automated,
            "hidden": self.hidden,
            "visible_when": self.visible_when,
        }


@dataclass(slots=True)
class AuthSchema:
    """The full set of inputs needed to connect one connector."""

    connector_id: str
    display_name: str
    auth_mode: AuthMode
    supported: bool
    self_service: bool
    requires_external_oauth: bool
    credentials: list[AuthField] = field(default_factory=list)
    connection_config: list[AuthField] = field(default_factory=list)
    integration_config: list[AuthField] = field(default_factory=list)
    assertion_option: list[AuthField] = field(default_factory=list)
    default_scopes: list[str] = field(default_factory=list)
    authorization_url: str | None = None
    unsupported_reason: str | None = None

    @property
    def fields(self) -> list[AuthField]:
        """Every field, ordered as a form should render them."""
        groups: Iterable[list[AuthField]] = (
            self.connection_config,
            self.credentials,
            self.integration_config,
            self.assertion_option,
        )
        out: list[AuthField] = []
        for group in groups:
            out.extend(sorted(group, key=lambda f: (f.order, f.name)))
        return out

    def user_fields(self) -> list[AuthField]:
        """Fields a human should actually be prompted for."""
        return [f for f in self.fields if not f.automated and not f.hidden]

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "auth_mode": self.auth_mode.value,
            "supported": self.supported,
            "self_service": self.self_service,
            "requires_external_oauth": self.requires_external_oauth,
            "unsupported_reason": self.unsupported_reason,
            "credentials": [f.to_dict() for f in sorted(self.credentials, key=lambda f: (f.order, f.name))],
            "connection_config": [
                f.to_dict() for f in sorted(self.connection_config, key=lambda f: (f.order, f.name))
            ],
            "integration_config": [
                f.to_dict() for f in sorted(self.integration_config, key=lambda f: (f.order, f.name))
            ],
            "assertion_option": [
                f.to_dict() for f in sorted(self.assertion_option, key=lambda f: (f.order, f.name))
            ],
            "default_scopes": list(self.default_scopes),
            "authorization_url": self.authorization_url,
        }


@dataclass(slots=True)
class Connector:
    """One connector: its identity, category, api base url and icon."""

    id: str
    display_name: str
    auth_mode: AuthMode
    categories: list[str] = field(default_factory=list)
    base_url: str | None = None
    alias: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    _icon_loader: Any = field(default=None, repr=False, compare=False)

    @property
    def self_service(self) -> bool:
        """True when ``connect()`` alone yields a working connection."""
        return self.auth_mode in SELF_SERVICE_MODES

    @property
    def supported(self) -> bool:
        """True when this package can produce a connection at all.

        Includes the OAuth modes, whose tokens you import after running the
        redirect flow in your own auth layer.
        """
        return self.auth_mode not in UNSUPPORTED_MODES

    @property
    def requires_external_oauth(self) -> bool:
        return self.auth_mode in EXTERNAL_OAUTH_MODES

    @property
    def icon_svg(self) -> str | None:
        """The connector logo as an inline SVG string (lazily read from disk)."""
        if self._icon_loader is None:
            return None
        return self._icon_loader(self.id)

    def to_dict(self, include_icon: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "display_name": self.display_name,
            "auth_mode": self.auth_mode.value,
            "categories": list(self.categories),
            "base_url": self.base_url,
            "alias": self.alias,
            "supported": self.supported,
            "self_service": self.self_service,
            "requires_external_oauth": self.requires_external_oauth,
        }
        if include_icon:
            data["icon_svg"] = self.icon_svg
        return data


@dataclass(slots=True)
class ConnectorPage:
    """One page of a connector listing, plus the numbers a UI needs.

    ``total`` is the number of connectors matching the filters *before* paging,
    so a picker can render "showing 21-40 of 957" and a next/prev control
    without a second call.

    >>> page = ConnectorPage(items=[], total=957, limit=50, offset=0)
    >>> page.page, page.pages, page.has_next, page.next_offset
    (1, 20, True, 50)
    """

    items: list[Connector]
    total: int
    limit: int
    offset: int

    def __iter__(self) -> Any:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> Connector:
        return self.items[index]

    @property
    def count(self) -> int:
        """How many items this page actually holds."""
        return len(self.items)

    @property
    def page(self) -> int:
        """1-based page number implied by ``offset`` / ``limit``."""
        if self.limit <= 0:
            return 1
        return self.offset // self.limit + 1

    @property
    def page_size(self) -> int:
        return self.limit

    @property
    def pages(self) -> int:
        """Total number of pages (0 when nothing matched)."""
        if self.limit <= 0:
            return 1 if self.total else 0
        return -(-self.total // self.limit)  # ceil division

    @property
    def has_next(self) -> bool:
        return self.offset + self.count < self.total

    @property
    def has_previous(self) -> bool:
        return self.offset > 0

    @property
    def next_offset(self) -> int | None:
        """Offset to pass for the following page, or ``None`` at the end."""
        return self.offset + self.limit if self.has_next else None

    @property
    def previous_offset(self) -> int | None:
        return max(0, self.offset - self.limit) if self.has_previous else None

    @property
    def first_index(self) -> int:
        """1-based index of the first item on this page (0 when empty)."""
        return self.offset + 1 if self.count else 0

    @property
    def last_index(self) -> int:
        """1-based index of the last item on this page (0 when empty)."""
        return self.offset + self.count if self.count else 0

    def pagination(self) -> dict[str, Any]:
        """Just the page metadata, JSON-ready."""
        return {
            "total": self.total,
            "count": self.count,
            "limit": self.limit,
            "offset": self.offset,
            "page": self.page,
            "page_size": self.page_size,
            "pages": self.pages,
            "has_next": self.has_next,
            "has_previous": self.has_previous,
            "next_offset": self.next_offset,
            "previous_offset": self.previous_offset,
            "first_index": self.first_index,
            "last_index": self.last_index,
        }

    def to_dict(self, include_icon: bool = False) -> dict[str, Any]:
        """The whole page, JSON-ready: ``{"items": [...], "pagination": {...}}``."""
        return {
            "items": [c.to_dict(include_icon=include_icon) for c in self.items],
            "pagination": self.pagination(),
        }


@dataclass(slots=True)
class Connection:
    """The result of a successful connect -- persist this outside the package.

    ``credentials`` holds whatever the auth mode produced (tokens, api keys,
    expiry, provider raw response). ``connection_config`` holds the
    non-secret per-connection values (domain, account id, ...) that provider
    templates interpolate.
    """

    connection_id: str
    connector_id: str
    auth_mode: AuthMode
    credentials: dict[str, Any] = field(default_factory=dict)
    connection_config: dict[str, Any] = field(default_factory=dict)
    integration_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = _utc_now_iso()
        self.connection_id = self.connection_id or str(uuid.uuid4())
        self.auth_mode = AuthMode.parse(
            self.auth_mode.value if isinstance(self.auth_mode, AuthMode) else self.auth_mode
        )
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now

    @property
    def expires_at(self) -> datetime | None:
        raw = self.credentials.get("expires_at")
        if not raw:
            return None
        if isinstance(raw, datetime):
            return raw
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """True when the access token is gone or about to expire."""
        expires_at = self.expires_at
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return (expires_at - datetime.now(timezone.utc)).total_seconds() <= buffer_seconds

    @property
    def access_token(self) -> str | None:
        """The bearer-ish token, whatever the auth mode calls it."""
        creds = self.credentials
        for key in ("access_token", "token"):
            value = creds.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "connector_id": self.connector_id,
            "auth_mode": self.auth_mode.value,
            "credentials": _jsonable(self.credentials),
            "connection_config": _jsonable(self.connection_config),
            "integration_config": _jsonable(self.integration_config),
            "metadata": _jsonable(self.metadata),
            "verified": self.verified,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Connection":
        return cls(
            connection_id=data.get("connection_id") or "",
            connector_id=data["connector_id"],
            auth_mode=AuthMode.parse(data.get("auth_mode")),
            credentials=dict(data.get("credentials") or {}),
            connection_config=dict(data.get("connection_config") or {}),
            integration_config=dict(data.get("integration_config") or {}),
            metadata=dict(data.get("metadata") or {}),
            verified=bool(data.get("verified", False)),
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
        )

    def touch(self) -> None:
        self.updated_at = _utc_now_iso()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, AuthMode):
        return value.value
    return value
