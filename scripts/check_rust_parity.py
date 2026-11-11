#!/usr/bin/env python3
"""Check that the Rust crate behaves exactly like the Python package.

    python scripts/check_rust_parity.py            # build the crate, compare everything
    python scripts/check_rust_parity.py --quick    # a sample of each kind of case

Both libraries read the same data directory, so they must agree on every
connector. This script builds each case with the Python package, has the Rust
CLI (`connectors parity`) build the same case, and compares the results:

* every connector's auth schema (``describe_auth``);
* every connector's tool list, generated tools included;
* a request through every connector, with a placeholder connection;
* every hand-authored tool, with synthetic arguments.

The placeholder connections and arguments come from the test suite's own
helpers, so the inputs are the ones ``pytest`` already exercises. Header values
that change on every build (nonces, timestamps, signatures) are found by
building each request twice in Python and compared by name only.
"""

from __future__ import annotations

import argparse
import base64
import email
import email.policy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

REPO_ROOT = Path(__file__).resolve().parent.parent
CRATE = REPO_ROOT / "src" / "connector_manager_rs"
sys.path.insert(0, str(REPO_ROOT / "src"))

from connector_manager import ConnectorError, ConnectorManager  # noqa: E402
from connector_manager.tools import ToolExecutor  # noqa: E402


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tests" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    return value


def _schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Field values the Rust model stores as text, normalised to text."""
    for group in ("credentials", "connection_config", "integration_config", "assertion_option"):
        for field in schema[group]:
            for key in ("example", "pattern", "format", "default_value", "prefix", "suffix"):
                field[key] = _scalar(field[key])
            field["enum"] = [_scalar(e) for e in field["enum"]]
    return schema


def _request(request: Any) -> dict[str, Any]:
    content = request.content
    if isinstance(content, bytes):
        content = content.decode("utf-8", "replace")
    return {
        "method": request.method,
        "url": request.url,
        "headers": dict(request.headers),
        "params": {k: str(v) for k, v in request.params.items()},
        "json_body": request.json_body,
        "content": content,
    }


def _content(text: str | None) -> Any:
    """A body in a form that ignores serialisation details (spacing, key order, %-escapes)."""
    if text is None:
        return None
    try:
        return ("json", json.loads(text))
    except ValueError:
        pass
    if "=" in text and "\n" not in text and " " not in text:
        return ("form", sorted(parse_qsl(text, keep_blank_values=True)))
    return ("text", text)


#: Header values that are a reading of the clock. Two builds a minute apart
#: differ in these, and in any signature computed over them.
_TIMESTAMP = re.compile(
    r"\d{8}T\d{6}Z|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|\b1[6-9]\d{8}\b|(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} \w{3} \d{4}"
)
_SIGNED = ("authorization", "signature", "x-wsse")


def _mime(raw: str) -> Any:
    """A Gmail ``raw`` message as headers plus each part's type and content.

    Python's email package and the Rust builder pick different boundaries and
    line endings; the message they describe is what has to match.
    """
    message = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=email.policy.default)
    headers = {k: message[k] for k in ("To", "Subject", "Cc", "Bcc", "From", "Reply-To", "In-Reply-To", "References") if message[k]}
    parts = []
    for part in message.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True) or b""
        parts.append((part.get_content_type(), part.get_filename(), payload.replace(b"\r\n", b"\n").strip()))
    return headers, sorted(parts, key=repr)


def _bodies(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (_mime(v) if k == "raw" and isinstance(v, str) else _bodies(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_bodies(v) for v in value]
    return value


def _python_case(build: Any) -> dict[str, Any]:
    try:
        first = _request(build())
    except ConnectorError as err:
        return {"error": type(err).__name__}
    second = _request(build())
    volatile = sorted(k for k in first["headers"] if second["headers"].get(k) != first["headers"][k])
    clocked = [k for k, v in first["headers"].items() if _TIMESTAMP.search(str(v))]
    if clocked:
        volatile += clocked + [k for k in first["headers"] if any(word in k for word in _SIGNED)]
    if first["url"] != second["url"]:
        volatile.append("<url>")
    first["volatile"] = volatile
    return {"ok": first}


def _compare(expected: dict[str, Any], actual: dict[str, Any]) -> str | None:
    if "error" in expected or "error" in actual:
        if expected.get("error") != actual.get("error"):
            return f"python {expected.get('error') or 'ok'} vs rust {actual.get('error') or 'ok'} ({actual.get('message', '')})"
        return None
    exp, act = expected["ok"], actual["ok"]
    if not isinstance(exp, dict) or "method" not in exp:
        return None if exp == act else f"python {json.dumps(exp)[:300]} vs rust {json.dumps(act)[:300]}"
    volatile = set(exp.pop("volatile", []))
    if exp["method"] != act["method"]:
        return f"method {exp['method']} vs {act['method']}"
    if "<url>" not in volatile:
        if exp["url"].split("?")[0] != act["url"].split("?")[0]:
            return f"url {exp['url']} vs {act['url']}"
        exp_q = sorted(parse_qsl(exp["url"].partition("?")[2], keep_blank_values=True))
        act_q = sorted(parse_qsl(act["url"].partition("?")[2], keep_blank_values=True))
        if exp_q != act_q:
            return f"url query {exp_q} vs {act_q}"
    if exp["params"] != act["params"]:
        return f"params {exp['params']} vs {act['params']}"
    if set(exp["headers"]) != set(act["headers"]):
        return f"header names {sorted(exp['headers'])} vs {sorted(act['headers'])}"
    for key, value in exp["headers"].items():
        if key not in volatile and act["headers"][key] != value:
            return f"header {key}: {value!r} vs {act['headers'][key]!r}"
    if _bodies(exp["json_body"]) != _bodies(act["json_body"]):
        return f"json body {json.dumps(exp['json_body'])[:300]} vs {json.dumps(act['json_body'])[:300]}"
    if _content(exp["content"]) != _content(act["content"]) and not volatile:
        return f"content {str(exp['content'])[:200]!r} vs {str(act['content'])[:200]!r}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="compare a sample rather than everything")
    parser.add_argument("--show", type=int, default=20, help="mismatches to print (default 20)")
    args = parser.parse_args()

    proxy_tests = _load("test_proxy")
    pack_tests = _load("test_tool_packs")
    manager = ConnectorManager()
    registry = manager.registry
    connectors = [c.id for c in registry]
    if args.quick:
        connectors = connectors[::25]

    cases: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for cid in connectors:
        cases.append((f"schema {cid}", {"kind": "schema", "connector_id": cid}, {"ok": _schema(manager.describe_auth(cid))}))
        cases.append((f"tools {cid}", {"kind": "tools", "connector_id": cid}, {"ok": [t.name for t in manager.list_tools(cid)]}))
        if cid in proxy_tests.CANNOT_BUILD_FROM_SCHEMA_ALONE:
            continue
        connection = proxy_tests._placeholder_connection(manager, cid)
        cases.append((
            f"request {cid}",
            {"kind": "request", "connection": connection.to_dict(), "method": "GET", "endpoint": "/ping"},
            _python_case(lambda c=connection: manager.prepare_request(c, "GET", "/ping")),
        ))

    packs = manager.tools.packs
    if args.quick:
        packs = packs[::10]
    for pack in packs:
        provider = registry.raw(pack.connector_id)
        connection = pack_tests._connection(registry, pack.connector_id)
        for tool in pack.tools.values():
            arguments = pack_tests._arguments(tool)
            executor = ToolExecutor(provider, tool, connection)
            cases.append((
                f"tool {tool.qualified_name}",
                {"kind": "tool", "connection": connection.to_dict(), "tool": tool.name, "arguments": arguments},
                _python_case(lambda e=executor, a=arguments: e.build(a)),
            ))

    print(f"built {len(cases)} cases in Python; running the Rust crate...", file=sys.stderr)
    stdin = "\n".join(json.dumps(case, default=str) for _, case, _ in cases)
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--release", "--bin", "connectors", "--", "parity"],
        cwd=CRATE, input=stdin, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != len(cases):
        print(f"rust answered {len(rows)} of {len(cases)} cases", file=sys.stderr)
        return 2

    mismatches = []
    for (label, _, expected), actual in zip(cases, rows):
        problem = _compare(expected, actual)
        if problem:
            mismatches.append(f"{label}: {problem}")
    by_kind: dict[str, int] = {}
    for line in mismatches:
        by_kind[line.split()[0]] = by_kind.get(line.split()[0], 0) + 1
    for line in mismatches[: args.show]:
        print(line)
    print(f"\n{len(cases) - len(mismatches)}/{len(cases)} cases match" + (f"; mismatches by kind: {by_kind}" if by_kind else ""))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
