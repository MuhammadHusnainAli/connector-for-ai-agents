#!/usr/bin/env python3
"""Probe connectors' own hosts for a published OpenAPI specification.

Many providers serve their spec at a conventional URL. This tries a short list
of those, per connector, and records the ones that answer with a real spec --
producing a plan file `generate_from_openapi.py --plan` can consume.

It only ever performs unauthenticated GETs against documented conventions, with
a short timeout and bounded concurrency, and it skips any connector whose base
url is templated (a per-tenant subdomain we cannot resolve).

    python scripts/discover_openapi.py --out plan.json --workers 12
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from connector_manager import ConnectorManager  # noqa: E402

#: Conventional locations, relative to a host root, ordered by how common they are.
CANDIDATES = (
    # Plain conventions.
    "/openapi.json", "/swagger.json", "/openapi.yaml", "/openapi.yml",
    "/spec.json", "/schema.json",
    # Framework defaults: Spring Boot, Django REST, .NET, Rails/rswag.
    "/v3/api-docs", "/api/schema/?format=json", "/swagger/v1/swagger.json",
    "/api-docs", "/apidocs", "/api-docs/v1", "/api/v1/swagger.json",
    # Versioned and nested placements.
    "/v1/openapi.json", "/v2/openapi.json", "/api/openapi.json",
    "/openapi/v1.json", "/docs/openapi.json", "/static/openapi.json",
    "/.well-known/openapi.json",
)

#: Docs hosts providers commonly serve specs from, tried alongside the API host.
HOST_PREFIXES = ("", "docs.", "developer.", "developers.", "api.", "app.")

TIMEOUT = 5


def hosts_for(base_url: str) -> list[str]:
    """Hosts worth probing for a connector, including templated per-tenant urls.

    A base of ``https://${subdomain}.zendesk.com`` names no reachable host, but
    the provider's own docs and api hosts on ``zendesk.com`` are still worth a
    look -- the spec lives there even when the API is per-tenant.
    """
    match = re.match(r"https?://([^/${}]+)", base_url or "")
    if not match:
        # Templated host: fall back to the registrable domain inside the url.
        domain = re.search(r"([a-z0-9][a-z0-9-]*\.[a-z]{2,})(?:[/:]|$)", (base_url or "").lower())
        if not domain:
            return []
        registrable = domain.group(1)
        return [f"{prefix}{registrable}" for prefix in HOST_PREFIXES if prefix] + [registrable]
    host = match.group(1).lower().strip(".")
    parts = host.split(".")
    registrable = ".".join(parts[-2:]) if len(parts) >= 2 else host
    out = []
    for prefix in HOST_PREFIXES:
        candidate = host if prefix == "" else f"{prefix}{registrable}"
        if candidate not in out:
            out.append(candidate)
    return out


def looks_like_spec(payload: bytes) -> bool:
    head = payload[:4000].decode("utf-8", "ignore").lower()
    if '"openapi"' in head or '"swagger"' in head or head.lstrip().startswith("openapi:"):
        return '"paths"' in payload[:200000].decode("utf-8", "ignore").lower() or "paths:" in head
    return False


def probe(url: str) -> bool:
    request = urllib.request.Request(
        url, headers={"User-Agent": "connector-for-ai-agents spec discovery", "Accept": "application/json, application/yaml"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return False
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "html" in ctype:
                return False
            return looks_like_spec(response.read(400000))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        return False


def find_spec(connector_id: str, base_url: str) -> tuple[str, str] | None:
    for host in hosts_for(base_url):
        for path in CANDIDATES:
            url = f"https://{host}{path}"
            if probe(url):
                return connector_id, url
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="where to write the plan JSON")
    parser.add_argument("--workers", type=int, default=10, help="parallel probes (keep this polite)")
    parser.add_argument("--limit", type=int, help="only probe this many connectors")
    args = parser.parse_args()

    manager = ConnectorManager()
    targets = [
        c for c in manager.registry
        if not manager.has_authored_tools(c.id) and c.base_url and "${" not in c.base_url
    ]
    if args.limit:
        targets = targets[: args.limit]
    print(f"probing {len(targets)} connectors...", file=sys.stderr)

    found: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(find_spec, c.id, c.base_url): c.id for c in targets}
        done = 0
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(targets)} probed, {len(found)} found", file=sys.stderr)
            result = future.result()
            if result:
                connector_id, url = result
                found.append({"connector": connector_id, "spec": url})
                print(f"  FOUND {connector_id}: {url}", file=sys.stderr)

    found.sort(key=lambda r: r["connector"])
    args.out.write_text(json.dumps(found, indent=1), encoding="utf-8")
    print(f"\n{len(found)} spec(s) discovered -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
