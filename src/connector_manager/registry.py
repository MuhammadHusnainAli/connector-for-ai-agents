"""Connector registry: loads the bundled connector definitions and icon set."""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Iterator

import yaml

from .errors import UnknownConnectorError
from .models import (
    EXTERNAL_OAUTH_MODES,
    SELF_SERVICE_MODES,
    AuthField,
    AuthMode,
    AuthSchema,
    Connector,
    ConnectorPage,
    FieldGroup,
)

def _data_dir() -> Path:
    """Locate the bundled data, whether running from a checkout or site-packages."""
    try:
        from importlib.resources import files

        return Path(str(files(__package__) / "data"))
    except Exception:  # pragma: no cover - fallback for exotic loaders
        return Path(__file__).parent / "data"


DATA_DIR = _data_dir()
#: Connector definitions, one YAML file per auth mode (``api-key.yaml``,
#: ``oauth2.yaml``, ...). Every ``*.yaml`` under here is loaded and merged, so
#: a bucket can be sharded further without touching this module.
CONNECTORS_DIR = DATA_DIR / "connectors"
#: The pre-0.1.3 single-file catalogue, still read when the directory is absent.
CONNECTORS_FILE = DATA_DIR / "connectors.yaml"
ICONS_DIR = DATA_DIR / "icons"

#: Page size used when a caller paginates without asking for one.
DEFAULT_PAGE_SIZE = 50
#: Upper bound, so a stray `page_size=10**9` cannot materialise a huge payload.
MAX_PAGE_SIZE = 1000

#: Field defaults for connectors that omit an explicit ``credentials`` block.
_DEFAULT_CREDENTIAL_FIELDS: dict[AuthMode, list[dict[str, Any]]] = {
    AuthMode.API_KEY: [
        {"name": "apiKey", "title": "API Key", "description": "Your API key.", "secret": True}
    ],
    AuthMode.BASIC: [
        {"name": "username", "title": "Username", "description": "Your username.", "order": 1},
        {
            "name": "password",
            "title": "Password",
            "description": "Your password.",
            "secret": True,
            "order": 2,
        },
    ],
    AuthMode.INSTALL_PLUGIN: [
        {"name": "username", "title": "Username", "description": "Your username.", "order": 1},
        {
            "name": "password",
            "title": "Password",
            "description": "Your password.",
            "secret": True,
            "order": 2,
        },
    ],
    AuthMode.OAUTH2_CC: [
        {"name": "client_id", "title": "Client ID", "description": "Your OAuth client id.", "order": 1},
        {
            "name": "client_secret",
            "title": "Client Secret",
            "description": "Your OAuth client secret.",
            "secret": True,
            "order": 2,
        },
    ],
    AuthMode.TBA: [
        {"name": "token_id", "title": "Token ID", "description": "Your token id.", "order": 1},
        {
            "name": "token_secret",
            "title": "Token Secret",
            "description": "Your token secret.",
            "secret": True,
            "order": 2,
        },
    ],
    # OAuth token fields are informational: the strategy raises
    # ExternalAuthRequiredError with the full explanation when they are missing.
    AuthMode.OAUTH2: [
        {
            "name": "access_token",
            "title": "Access Token",
            "description": "Access token obtained from your own OAuth flow.",
            "secret": True,
            "required": False,
            "order": 1,
        },
        {
            "name": "refresh_token",
            "title": "Refresh Token",
            "description": "Refresh token obtained from your own OAuth flow.",
            "secret": True,
            "required": False,
            "order": 2,
        },
    ],
    AuthMode.OAUTH1: [
        {
            "name": "oauth_token",
            "title": "OAuth Token",
            "secret": True,
            "required": False,
            "order": 1,
        },
        {
            "name": "oauth_token_secret",
            "title": "OAuth Token Secret",
            "secret": True,
            "required": False,
            "order": 2,
        },
    ],
}

_UNSUPPORTED_REASONS = {
    AuthMode.BILL: "Bill.com session-token auth is not implemented yet.",
    AuthMode.AWS_SIGV4: "AWS SigV4 request signing is not implemented yet.",
    AuthMode.APP: "App installation flows are handled outside this package.",
    AuthMode.CUSTOM: "App-scoped OAuth (CUSTOM) is handled outside this package.",
}


class ConnectorRegistry:
    """Read-only catalogue of every connector shipped with the package.

    >>> registry = ConnectorRegistry()
    >>> len(registry) > 1500
    True
    >>> registry.get("slack").display_name
    'Slack'
    """

    def __init__(
        self,
        connectors_file: str | Path | None = None,
        icons_dir: str | Path | None = None,
    ) -> None:
        # Accepts either a directory of per-auth-mode files (the bundled layout)
        # or a single YAML file, which is what callers passing a custom
        # catalogue -- and the pre-0.1.3 bundle -- have.
        self.connectors_path = Path(connectors_file) if connectors_file else _default_source()
        self.icons_dir = Path(icons_dir or ICONS_DIR)
        self._raw: dict[str, dict[str, Any]] = _load_definitions(self.connectors_path)
        self._connectors: dict[str, Connector] = {
            key: self._build_connector(key, entry) for key, entry in self._raw.items()
        }

    @property
    def connectors_file(self) -> Path:
        """Deprecated alias of :attr:`connectors_path`, which may be a directory."""
        return self.connectors_path

    # -- catalogue ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._connectors)

    def __iter__(self) -> Iterator[Connector]:
        return iter(self._connectors.values())

    def __contains__(self, connector_id: object) -> bool:
        return connector_id in self._connectors

    @property
    def ids(self) -> list[str]:
        return list(self._connectors)

    def get(self, connector_id: str) -> Connector:
        try:
            return self._connectors[connector_id]
        except KeyError:
            raise UnknownConnectorError(
                f"Unknown connector '{connector_id}'", connector_id=connector_id
            ) from None

    def raw(self, connector_id: str) -> dict[str, Any]:
        """The alias-resolved definition for a connector."""
        return self.get(connector_id).raw

    def match(
        self,
        search: str | None = None,
        category: str | None = None,
        auth_mode: str | AuthMode | None = None,
        supported_only: bool = False,
        self_service_only: bool = False,
    ) -> list[Connector]:
        """Every connector matching the filters, ordered by display name.

        This is the unpaged result set: :meth:`list` slices it and
        :meth:`paginate` also reports its size.

        ``supported_only`` drops the auth modes with no handler at all;
        ``self_service_only`` also drops the ones needing an external OAuth flow.
        """
        mode = AuthMode.parse(auth_mode) if auth_mode is not None else None
        needle = (search or "").strip().lower()
        out: list[Connector] = []
        for connector in self._connectors.values():
            if mode is not None and connector.auth_mode is not mode:
                continue
            if category and category not in connector.categories:
                continue
            if supported_only and not connector.supported:
                continue
            if self_service_only and not connector.self_service:
                continue
            if needle and needle not in connector.id.lower() and needle not in connector.display_name.lower():
                continue
            out.append(connector)
        # A stable total order matters for pagination: two calls for page 1 and
        # page 2 must slice the same sequence.
        out.sort(key=lambda c: (c.display_name.lower(), c.id))
        return out

    def list(
        self,
        search: str | None = None,
        category: str | None = None,
        auth_mode: str | AuthMode | None = None,
        supported_only: bool = False,
        self_service_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Connector]:
        """Filterable listing, optionally sliced by ``limit`` / ``offset``."""
        matches = self.match(
            search=search,
            category=category,
            auth_mode=auth_mode,
            supported_only=supported_only,
            self_service_only=self_service_only,
        )
        start = max(0, offset)
        end = None if limit is None else start + max(0, limit)
        return matches[start:end]

    def paginate(
        self,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        offset: int | None = None,
        search: str | None = None,
        category: str | None = None,
        auth_mode: str | AuthMode | None = None,
        supported_only: bool = False,
        self_service_only: bool = False,
    ) -> ConnectorPage:
        """One page of the listing, with the total and next/prev offsets.

        Address a page either by number (``page=2, page_size=20``) or by raw
        ``offset``; when both are given, ``offset`` wins. The filters are the
        same as :meth:`list`.
        """
        page, page_size, offset = _page_bounds(page, page_size, offset)
        matches = self.match(
            search=search,
            category=category,
            auth_mode=auth_mode,
            supported_only=supported_only,
            self_service_only=self_service_only,
        )
        return ConnectorPage(
            items=matches[offset : offset + page_size],
            total=len(matches),
            limit=page_size,
            offset=offset,
        )

    def iter_pages(
        self,
        page_size: int = DEFAULT_PAGE_SIZE,
        start_offset: int = 0,
        **filters: Any,
    ) -> Iterator[ConnectorPage]:
        """Walk the whole filtered listing one page at a time.

        >>> registry = ConnectorRegistry()
        >>> sum(page.count for page in registry.iter_pages(page_size=100)) == len(registry)
        True
        """
        offset = max(0, start_offset)
        while True:
            page = self.paginate(page_size=page_size, offset=offset, **filters)
            if not page.count:
                # Emit an empty first page so callers always see the total.
                if offset == max(0, start_offset):
                    yield page
                return
            yield page
            if page.next_offset is None:
                return
            offset = page.next_offset

    def categories(self) -> list[str]:
        seen: set[str] = set()
        for connector in self._connectors.values():
            seen.update(connector.categories)
        return sorted(seen)

    def auth_modes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for connector in self._connectors.values():
            counts[connector.auth_mode.value] = counts.get(connector.auth_mode.value, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    # -- icons -------------------------------------------------------------

    @functools.lru_cache(maxsize=1024)  # noqa: B019 - registry instances are long lived
    def icon(self, connector_id: str) -> str | None:
        """Inline SVG for a connector, or ``None`` when no icon is bundled."""
        path = self.icons_dir / f"{connector_id}.svg"
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def icon_path(self, connector_id: str) -> Path | None:
        path = self.icons_dir / f"{connector_id}.svg"
        return path if path.is_file() else None

    # -- auth schema -------------------------------------------------------

    def auth_schema(self, connector_id: str) -> AuthSchema:
        """Describe every input needed to connect ``connector_id``."""
        connector = self.get(connector_id)
        entry = connector.raw
        mode = connector.auth_mode

        credentials = _fields(entry.get("credentials"), FieldGroup.CREDENTIALS)
        if not credentials:
            credentials = [
                _field_from_default(spec, FieldGroup.CREDENTIALS)
                for spec in _DEFAULT_CREDENTIAL_FIELDS.get(mode, [])
            ]

        connection_config = _fields(entry.get("connection_config"), FieldGroup.CONNECTION_CONFIG)
        # `connection_configuration` lists bare key names that a provider-specific
        # post-connection step fills in, so they are informational, not user input.
        for name in entry.get("connection_configuration") or []:
            if not any(f.name == name for f in connection_config):
                connection_config.append(
                    AuthField(
                        name=name,
                        group=FieldGroup.CONNECTION_CONFIG,
                        title=_titleize(name),
                        description="Derived from the provider after connecting; supply it yourself if you need it.",
                        required=False,
                        automated=True,
                        order=len(connection_config) + 1,
                    )
                )

        return AuthSchema(
            connector_id=connector.id,
            display_name=connector.display_name,
            auth_mode=mode,
            supported=connector.supported,
            self_service=connector.self_service,
            requires_external_oauth=mode in EXTERNAL_OAUTH_MODES,
            unsupported_reason=_UNSUPPORTED_REASONS.get(mode),
            credentials=credentials,
            connection_config=connection_config,
            integration_config=_fields(
                entry.get("integration_config"), FieldGroup.INTEGRATION_CONFIG
            ),
            assertion_option=_fields(entry.get("assertion_option"), FieldGroup.ASSERTION_OPTION),
            default_scopes=list(entry.get("default_scopes") or []),
            authorization_url=entry.get("authorization_url"),
        )

    # -- internals ---------------------------------------------------------

    def _build_connector(self, key: str, entry: dict[str, Any]) -> Connector:
        proxy = entry.get("proxy") or {}
        return Connector(
            id=key,
            display_name=entry.get("display_name") or _titleize(key),
            auth_mode=AuthMode.parse(entry.get("auth_mode")),
            categories=list(entry.get("categories") or []),
            base_url=proxy.get("base_url"),
            alias=entry.get("alias"),
            raw=entry,
            _icon_loader=self.icon,
        )


def _page_bounds(page: int, page_size: int, offset: int | None) -> tuple[int, int, int]:
    """Validate paging arguments and resolve them to ``(page, page_size, offset)``."""
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError(f"page must be an integer >= 1, got {page!r}")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise ValueError(f"page_size must be an integer >= 1, got {page_size!r}")
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be <= {MAX_PAGE_SIZE}, got {page_size}")
    if offset is None:
        offset = (page - 1) * page_size
    elif not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError(f"offset must be an integer >= 0, got {offset!r}")
    else:
        # An explicit offset defines the page, so keep the two consistent.
        page = offset // page_size + 1
    return page, page_size, offset


def _default_source() -> Path:
    """The bundled catalogue: the per-auth-mode directory, else the legacy file."""
    return CONNECTORS_DIR if CONNECTORS_DIR.is_dir() else CONNECTORS_FILE


def _catalogue_files(path: Path) -> list[Path]:
    """Every YAML file making up the catalogue at ``path``.

    ``rglob`` rather than ``glob`` so a bucket that outgrows one file can be
    split into a subdirectory later without a loader change. Sorting keeps the
    merge order deterministic across filesystems.
    """
    if path.is_dir():
        return sorted(path.rglob("*.yaml"))
    return [path]


def _load_definitions(path: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for file in _catalogue_files(path):
        with file.open("r", encoding="utf-8") as handle:
            chunk = yaml.safe_load(handle) or {}
        for key, entry in chunk.items():
            if key in entries:
                # Two files claiming the same id would make the winner depend on
                # filename order, so refuse rather than silently pick one.
                raise ValueError(f"duplicate connector id {key!r} in {file}")
            entries[key] = entry
    return _resolve_aliases(entries)


def _resolve_aliases(entries: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Shallow-merge each alias entry over its target, following alias chains.

    A target may itself be an alias, and after the split the two can live in
    different files, so resolution is recursive and memoised instead of a single
    pass in file order.
    """
    resolved: dict[str, dict[str, Any]] = {}

    def resolve(key: str, pending: frozenset[str]) -> Any:
        if key in resolved:
            return resolved[key]
        entry = entries[key]
        alias = entry.get("alias") if isinstance(entry, dict) else None
        # A dangling or cyclic alias leaves the entry as written rather than
        # blowing up the whole catalogue over one bad row.
        if alias is None or alias not in entries or alias in pending:
            return entry
        target = resolve(str(alias), pending | {key})
        if not isinstance(target, dict):
            return entry
        overrides = {k: v for k, v in entry.items() if k != "alias"}
        merged = {**target, **overrides, "alias": alias}
        resolved[key] = merged
        return merged

    return {key: resolve(key, frozenset()) for key in entries}


def _fields(spec: Any, group: FieldGroup) -> list[AuthField]:
    if not isinstance(spec, dict):
        return []
    out: list[AuthField] = []
    for index, (name, raw) in enumerate(spec.items(), start=1):
        raw = raw if isinstance(raw, dict) else {}
        out.append(
            AuthField(
                name=name,
                group=group,
                title=raw.get("title") or _titleize(name),
                description=raw.get("description") or "",
                type=raw.get("type") or "string",
                required=not _truthy(raw.get("optional")),
                secret=_truthy(raw.get("secret")),
                example=raw.get("example"),
                pattern=raw.get("pattern"),
                format=raw.get("format"),
                default_value=raw.get("default_value"),
                enum=list(raw.get("enum") or []),
                prefix=raw.get("prefix"),
                suffix=raw.get("suffix"),
                order=int(raw.get("order") or index),
                automated=_truthy(raw.get("automated")),
                hidden=_truthy(raw.get("hidden")),
                visible_when=raw.get("visible_when"),
            )
        )
    return out


def _field_from_default(spec: dict[str, Any], group: FieldGroup) -> AuthField:
    return AuthField(
        name=spec["name"],
        group=group,
        title=spec.get("title") or _titleize(spec["name"]),
        description=spec.get("description") or "",
        required=spec.get("required", True),
        secret=spec.get("secret", False),
        order=spec.get("order", 1),
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _titleize(name: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name.replace("_", " ").replace("-", " "))
    return " ".join(part.capitalize() if part.islower() else part for part in spaced.split())
