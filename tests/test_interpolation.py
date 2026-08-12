"""Provider template engine."""

from __future__ import annotations

import base64
import hashlib
import re

import pytest

from connector_manager.errors import InterpolationError
from connector_manager.interpolation import (
    extract_step_number,
    extract_value_by_path,
    interpolate,
    interpolate_deep,
    is_unresolved,
    make_url,
    strip_credential,
    strip_step_response,
)


def test_flat_and_dotted_lookups() -> None:
    replacers = {"apiKey": "abc", "connectionConfig": {"domain": "acme.io"}}
    assert interpolate("Bearer ${apiKey}", replacers) == "Bearer abc"
    assert interpolate("https://${connectionConfig.domain}/v1", replacers) == "https://acme.io/v1"


def test_unresolved_placeholders_are_left_in_place() -> None:
    resolved = interpolate("${missing}/path", {})
    assert resolved == "${missing}/path"
    assert is_unresolved(resolved)


def test_fallback_operator_prefers_the_left_side() -> None:
    assert interpolate("${a} || ${b}", {"a": "left", "b": "right"}) == "left"
    assert interpolate("${a} || ${b}", {"b": "right"}) == "right"
    assert interpolate("${a} || fallback", {}) == "fallback"


def test_base64_and_hash_helpers() -> None:
    creds = {"username": "u", "password": "p"}
    assert interpolate("${base64(${username}:${password})}", creds) == base64.b64encode(b"u:p").decode()
    assert interpolate("${sha256Hex(${username})}", creds) == hashlib.sha256(b"u").hexdigest()
    assert re.fullmatch(r"[0-9a-f]{40}", interpolate("${hmacSha1Hex(${username}, ${password})}", creds))


def test_now_and_random_helpers() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", interpolate("${now:YYYY-MM-DD}", {}))
    assert interpolate("${now:YYYY-MM-DD}", {"now": "2024-03-04T05:06:07Z"}) == "2024-03-04"
    assert interpolate("${now+7:days:YYYY-MM-DD}", {"now": "2024-03-04T00:00:00Z"}) == "2024-03-11"
    assert len(interpolate("${random}", {})) == 36


def test_strip_helpers() -> None:
    assert strip_credential("${credentials.clientId}") == "${clientId}"
    assert strip_step_response("${step1.token}") == "${token}"
    assert extract_step_number("${step2.access_token}") == 2
    assert extract_step_number("${token}") is None


def test_extract_value_by_path() -> None:
    payload = {"data": {"items": [{"token": "t1"}]}}
    assert extract_value_by_path(payload, "data.items[0].token") == "t1"
    assert extract_value_by_path(payload, "data.missing") is None


def test_interpolate_deep() -> None:
    template = {"outer": {"inner": "${key}", "list": ["${key}"]}, "untouched": 3}
    assert interpolate_deep(template, {"key": "v"}) == {
        "outer": {"inner": "v", "list": ["v"]},
        "untouched": 3,
    }


def test_make_url_requires_full_resolution() -> None:
    assert make_url("https://${connectionConfig.domain}/api", {"domain": "acme.io"}) == "https://acme.io/api"
    with pytest.raises(InterpolationError):
        make_url("https://${connectionConfig.domain}/api", {})
