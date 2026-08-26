"""CLI for exploring the catalogue and creating connections.

    python -m connector_manager list --search slack
    python -m connector_manager show affinity-v2
    python -m connector_manager connect affinity-v2 -c apiKey=... -o conn.json
    python -m connector_manager request conn.json GET /v2/persons
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from .errors import ConnectorError
from .manager import ConnectorManager
from .models import Connection, ConnectorPage
from .registry import DEFAULT_PAGE_SIZE

#: Stand-in printed in place of a secret.
REDACTED = "<redacted>"

#: Key words that mark a value as authenticating. Matched per word, so
#: ``apiKey`` and ``x-auth-token`` hit while ``monkey`` and ``keyboard`` do not.
_SECRET_WORDS = frozenset(
    {
        "auth", "authorization", "bearer", "cookie", "credential", "credentials",
        "hash", "key", "passphrase", "passwd", "password", "salt", "secret",
        "session", "sig", "signature", "token",
    }
)

#: Bookkeeping fields inside ``credentials`` that carry no secret, so a redacted
#: connection still shows what kind of credential it holds and when it expires.
_PUBLIC_CREDENTIAL_KEYS = frozenset(
    {"type", "expires_at", "expires_in", "token_type", "scope", "scopes", "created_at"}
)

#: Names that read as secret-ish but only ever describe an auth scheme.
_PUBLIC_KEYS = frozenset({"auth_mode", "authmode", "auth_type", "authtype", "token_type"})


def _words(key: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()) if w]


def _is_secret_key(key: str) -> bool:
    if key.lower() in _PUBLIC_KEYS:
        return False
    return bool(_SECRET_WORDS.intersection(_words(key)))


def _redact(value: Any, *, in_credentials: bool = False) -> Any:
    """Copy ``value`` with every authenticating field replaced by :data:`REDACTED`.

    Inside a ``credentials`` block everything is a secret unless it is known
    bookkeeping; elsewhere a field is judged by its name, which is what catches
    the ``authorization`` header and an ``api_key`` query parameter.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name == "credentials" and isinstance(item, dict):
                out[key] = _redact(item, in_credentials=True)
            elif in_credentials and name not in _PUBLIC_CREDENTIAL_KEYS:
                out[key] = REDACTED if item not in (None, {}, []) else item
            elif _is_secret_key(name):
                out[key] = REDACTED if item not in (None, {}, []) else item
            else:
                out[key] = _redact(item, in_credentials=in_credentials)
        return out
    if isinstance(value, list):
        return [_redact(item, in_credentials=in_credentials) for item in value]
    return value


def _kv(pairs: Sequence[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"expected key=value, got '{pair}'")
        out[key.strip()] = value
    return out


def _dump(value: Any, *, redact: bool = False) -> None:
    print(json.dumps(_redact(value) if redact else value, indent=2, default=str))


def _load_connection(path: str) -> Connection:
    return Connection.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _write_private_json(path: Path, payload: Any) -> None:
    """Write JSON that only the current user can read.

    A connection file holds live credentials, so it is created 0600 and an
    existing file is tightened to 0600 before anything is written to it.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, default=str))
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - filesystems without POSIX modes
        pass


def _save_connection(connection: Connection, path: str | None, *, show_secrets: bool = False) -> None:
    payload = connection.to_dict()
    if path:
        _write_private_json(Path(path), payload)
        print(f"connection written to {path} (holds credentials; mode 0600)", file=sys.stderr)
        return
    _dump(payload, redact=not show_secrets)
    if not show_secrets:
        print(
            "credentials hidden -- write the usable connection with -o FILE, "
            "or pass --show-secrets to print them",
            file=sys.stderr,
        )


def _listing_row(connector) -> str:
    if connector.self_service:
        flag = ""
    elif connector.requires_external_oauth:
        flag = "  (needs external OAuth)"
    else:
        flag = "  (auth mode not implemented)"
    return f"{connector.id:<40} {connector.auth_mode.value:<14} {connector.display_name}{flag}"


def _page_footer(page: ConnectorPage) -> str:
    """`showing 21-40 of 957 · page 2/20 · next: --offset 40`"""
    if not page.count:
        return "no connectors matched"
    parts = [
        f"showing {page.first_index}-{page.last_index} of {page.total}",
        f"page {page.page}/{page.pages}",
    ]
    if page.has_next:
        parts.append(f"next: --offset {page.next_offset}")
    return "\n" + " · ".join(parts)


def _add_show_secrets(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="print credentials instead of hiding them (they are hidden by default)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="connector_manager", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list connectors")
    listing.add_argument("--search")
    listing.add_argument("--category")
    listing.add_argument("--auth-mode")
    listing.add_argument("--supported-only", action="store_true")
    listing.add_argument(
        "--self-service-only",
        action="store_true",
        help="only connectors that connect without an external OAuth flow",
    )
    listing.add_argument("--page", type=int, default=1, help="1-based page number (default 1)")
    listing.add_argument(
        "--page-size", type=int, default=DEFAULT_PAGE_SIZE, help=f"items per page (default {DEFAULT_PAGE_SIZE})"
    )
    listing.add_argument("--offset", type=int, help="start at this item instead of a page number")
    listing.add_argument("--all", action="store_true", help="page through the whole listing")
    listing.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="show a connector and everything it needs to authenticate")
    show.add_argument("connector_id")
    show.add_argument("--json", action="store_true")

    icon = sub.add_parser("icon", help="print a connector's SVG logo")
    icon.add_argument("connector_id")
    icon.add_argument("-o", "--output")

    sub.add_parser("stats", help="catalogue totals by auth mode and category")

    connect = sub.add_parser("connect", help="authenticate a connector and emit the connection")
    connect.add_argument("connector_id")
    connect.add_argument("-c", "--credential", action="append", metavar="KEY=VALUE")
    connect.add_argument("-x", "--config", action="append", metavar="KEY=VALUE")
    connect.add_argument("-i", "--integration-config", action="append", metavar="KEY=VALUE")
    connect.add_argument("--no-verify", action="store_true")
    connect.add_argument("-o", "--output", help="write the connection JSON here")
    _add_show_secrets(connect)

    for name, help_text in (
        ("verify", "re-run verification for a stored connection"),
        ("refresh", "refresh a stored connection's token"),
    ):
        action = sub.add_parser(name, help=help_text)
        action.add_argument("connection_file")
        action.add_argument("-o", "--output")
        _add_show_secrets(action)

    request = sub.add_parser("request", help="make an authenticated API call")
    request.add_argument("connection_file")
    request.add_argument("method")
    request.add_argument("endpoint")
    request.add_argument("-q", "--param", action="append", metavar="KEY=VALUE")
    request.add_argument("-d", "--data", help="JSON request body")
    request.add_argument("--dry-run", action="store_true", help="print the prepared request only")
    _add_show_secrets(request)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    with ConnectorManager() as manager:
        try:
            return _run(manager, args)
        except ConnectorError as err:
            print(json.dumps(err.to_dict(), indent=2, default=str), file=sys.stderr)
            return 1


def _run(manager: ConnectorManager, args: argparse.Namespace) -> int:
    if args.command == "list":
        filters = {
            "search": args.search,
            "category": args.category,
            "auth_mode": args.auth_mode,
            "supported_only": args.supported_only,
            "self_service_only": args.self_service_only,
        }
        if args.all:
            pages = manager.iter_connector_pages(page_size=args.page_size, **filters)
        else:
            pages = [
                manager.paginate_connectors(
                    page=args.page, page_size=args.page_size, offset=args.offset, **filters
                )
            ]

        for page in pages:
            if args.json:
                _dump(page.to_dict())
            else:
                for connector in page:
                    print(_listing_row(connector))
                print(_page_footer(page), file=sys.stderr)
        return 0

    if args.command == "show":
        connector = manager.get_connector(args.connector_id)
        schema = manager.get_auth_schema(args.connector_id)
        if args.json:
            _dump({"connector": connector.to_dict(), "auth": schema.to_dict()})
            return 0
        print(f"{connector.display_name}  [{connector.id}]")
        print(f"  auth mode   : {schema.auth_mode.value}")
        print(f"  categories  : {', '.join(connector.categories) or '-'}")
        print(f"  base url    : {connector.base_url or '-'}")
        if schema.requires_external_oauth:
            print("  note        : run the OAuth flow in your own auth layer, then import the tokens")
        if schema.unsupported_reason:
            print(f"  unsupported : {schema.unsupported_reason}")
        print("  fields:")
        for field in schema.user_fields():
            marks = ",".join(
                filter(None, ["required" if field.required else "optional", "secret" if field.secret else ""])
            )
            print(f"    - [{field.group.value}] {field.name} ({marks}): {field.title}")
            if field.description:
                print(f"        {field.description}")
            if field.enum:
                print(f"        one of: {', '.join(field.enum)}")
            if field.example:
                print(f"        e.g. {field.example}")
        return 0

    if args.command == "icon":
        icon = manager.get_icon(args.connector_id)
        if icon is None:
            print(f"no icon bundled for '{args.connector_id}'", file=sys.stderr)
            return 1
        if args.output:
            Path(args.output).write_text(icon, encoding="utf-8")
        else:
            print(icon)
        return 0

    if args.command == "stats":
        _dump(
            {
                "connectors": len(manager),
                "auth_modes": manager.auth_modes(),
                "categories": manager.categories(),
            }
        )
        return 0

    if args.command == "connect":
        connection = manager.connect(
            args.connector_id,
            credentials=_kv(args.credential),
            connection_config=_kv(args.config),
            integration_config=_kv(args.integration_config),
            verify=not args.no_verify,
        )
        _save_connection(connection, args.output, show_secrets=args.show_secrets)
        return 0 if (connection.verified or args.no_verify) else 2

    if args.command in ("verify", "refresh"):
        connection = _load_connection(args.connection_file)
        if args.command == "verify":
            result = manager.verify(connection)
            connection.verified = result.verified
            connection.metadata["verification"] = result.to_dict()
            _dump(result.to_dict())
            if args.output:
                _save_connection(connection, args.output, show_secrets=args.show_secrets)
            return 0 if result.verified else 2
        manager.refresh(connection)
        _save_connection(
            connection, args.output or args.connection_file, show_secrets=args.show_secrets
        )
        return 0

    if args.command == "request":
        connection = _load_connection(args.connection_file)
        body = json.loads(args.data) if args.data else None
        if args.dry_run:
            # The prepared request carries the authorization header and any
            # key-bearing query parameter, so hide them unless asked.
            _dump(
                manager.prepare_request(
                    connection, args.method, args.endpoint, params=_kv(args.param), body=body
                ).to_dict(),
                redact=not args.show_secrets,
            )
            return 0
        response = manager.request(
            connection,
            args.method,
            args.endpoint,
            params=_kv(args.param),
            json_body=body,
        )
        print(f"HTTP {response.status}", file=sys.stderr)
        _dump(response.body())
        return 0 if response.ok else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
