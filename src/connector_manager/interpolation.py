"""Template interpolation engine for connector definitions.

Connector definitions use ``${...}`` placeholders with a small expression
language, so urls, headers and token params can be declared as data.

Supported forms::

    ${apiKey}                       flat key lookup
    ${connectionConfig.domain}      dot path lookup
    ${credentials.clientId}         dot path lookup
    ${a} || ${b}                    fallback (left wins if it resolved)
    ${base64(${user}:${pass})}      base64 of the resolved inner expression
    ${sha256Hex(${body})}           hex sha256
    ${hmacSha1Hex(${msg}, ${key})}  hex hmac-sha1, key is the last argument
    ${fingerprint(${privateKey})}   SHA256:<base64> of the public key SPKI
    ${now}                          ISO-8601 timestamp
    ${now:YYYY-MM-DD}               formatted timestamp
    ${now+7:days:YYYY-MM-DD}        offset then formatted
    ${random}                       uuid4
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .errors import InterpolationError

PLACEHOLDER_RE = re.compile(r"\$\{([^{}]*)\}")
_BASE64_RE = re.compile(r"\$\{base64\((.*?)\)\}")
_SHA256_RE = re.compile(r"\$\{sha256Hex\((.*?)\)\}")
_HMAC_SHA1_RE = re.compile(r"\$\{hmacSha1Hex\(([\s\S]*?)\)\}")
_FINGERPRINT_RE = re.compile(r"\$\{fingerprint\((.*?)\)\}")
_NOW_OFFSET_RE = re.compile(r"^now([+-]\d+):([a-zA-Z]+):(.+)$")
_NOW_FORMAT_RE = re.compile(r"^now:(.+)$")
_STEP_RE = re.compile(r"\$\{step(\d+)\..*?\}")

# Mapping from the moment.js style date tokens used in definitions to strftime.
_MOMENT_TOKENS = [
    ("YYYY", "%Y"),
    ("MM", "%m"),
    ("DD", "%d"),
    ("HH", "%H"),
    ("mm", "%M"),
    ("ss", "%S"),
    ("SSS", "%f"),
    ("X", "%s"),
]

_UNIT_ALIASES = {
    "day": "days",
    "days": "days",
    "d": "days",
    "hour": "hours",
    "hours": "hours",
    "h": "hours",
    "minute": "minutes",
    "minutes": "minutes",
    "m": "minutes",
    "second": "seconds",
    "seconds": "seconds",
    "s": "seconds",
    "week": "weeks",
    "weeks": "weeks",
    "w": "weeks",
}


def has_placeholder(value: str) -> bool:
    return "${" in value


def is_unresolved(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value))


def strip_credential(value: Any) -> Any:
    """Drop the ``credentials.`` prefix so ``${credentials.x}`` resolves as ``${x}``."""
    if isinstance(value, str):
        return value.replace("credentials.", "")
    if isinstance(value, dict):
        return {k: strip_credential(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_credential(v) for v in value]
    return value


def strip_step_response(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"step\d+\.", "", value)
    if isinstance(value, dict):
        return {k: strip_step_response(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_step_response(v) for v in value]
    return value


def extract_step_number(value: str) -> int | None:
    match = _STEP_RE.search(value)
    return int(match.group(1)) if match else None


def extract_value_by_path(obj: Any, path: str) -> Any:
    """Resolve a lodash-style ``a.b[0].c`` path."""
    current = obj
    for part in re.split(r"\.|\[|\]", path):
        if part == "":
            continue
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return None
            current = current[int(part)]
        else:
            return None
    return current


def _now(replacers: dict[str, Any]) -> datetime:
    iso = replacers.get("now")
    if isinstance(iso, str) and iso:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _moment_format(dt: datetime, fmt: str) -> str:
    if fmt == "X":
        return str(int(dt.timestamp()))
    out = fmt
    for token, strf in _MOMENT_TOKENS:
        out = out.replace(token, strf)
    rendered = dt.strftime(out)
    if "%f" in out:
        # strftime gives microseconds; moment's SSS is milliseconds.
        rendered = re.sub(r"(\d{3})\d{3}", r"\1", rendered)
    return rendered


def _resolve_now(expression: str, replacers: dict[str, Any]) -> str | None:
    if expression == "now":
        iso = replacers.get("now")
        if isinstance(iso, str) and iso:
            return iso
        return _now(replacers).isoformat().replace("+00:00", "Z")

    offset = _NOW_OFFSET_RE.match(expression)
    if offset:
        amount, unit, fmt = offset.groups()
        unit_key = _UNIT_ALIASES.get(unit.lower(), "days")
        return _moment_format(_now(replacers) + timedelta(**{unit_key: int(amount)}), fmt)

    formatted = _NOW_FORMAT_RE.match(expression)
    if formatted:
        return _moment_format(_now(replacers), formatted.group(1))

    return None


def _resolve_key(key: str, replacers: dict[str, Any]) -> Any:
    if key in replacers:
        return replacers[key]
    current: Any = replacers
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def format_pem(pem: str, kind: str = "PRIVATE KEY") -> str:
    """Normalise a possibly single-line / header-less PEM blob."""
    if not pem or not isinstance(pem, str):
        raise InterpolationError("Invalid PEM input: must be a non-empty string")
    body = pem.replace("\\n", "\n")
    body = re.sub(r"-----(BEGIN|END) [^-]+-----", "", body)
    body = re.sub(r"\s+", "", body.strip())
    if not body:
        raise InterpolationError("PEM content is empty after normalization")
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", body):
        raise InterpolationError("PEM contains invalid characters (must be base64)")
    chunks = [body[i : i + 64] for i in range(0, len(body), 64)]
    return f"-----BEGIN {kind}-----\n" + "\n".join(chunks) + f"\n-----END {kind}-----\n"


def pem_kind(pem: str, default: str = "PRIVATE KEY") -> str:
    match = re.search(r"-----BEGIN ([A-Z0-9 ]+)-----", pem or "")
    return match.group(1) if match else default


def _fingerprint(private_key_pem: str) -> str:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        format_pem(private_key_pem, pem_kind(private_key_pem)).encode(), password=None
    )
    der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode()


def _split_top_level_args(inner: str) -> list[str]:
    args: list[str] = []
    depth = 0
    start = 0
    for i, char in enumerate(inner):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(inner[start:i].strip())
            start = i + 1
    args.append(inner[start:].strip())
    return args


def _apply_functions(value: str, resolve_inner: Callable[[str], str]) -> str:
    value = _HMAC_SHA1_RE.sub(lambda m: _hmac_sha1(m, resolve_inner), value)
    value = _BASE64_RE.sub(
        lambda m: base64.b64encode(resolve_inner(m.group(1)).encode()).decode(), value
    )
    value = _SHA256_RE.sub(
        lambda m: hashlib.sha256(resolve_inner(m.group(1)).encode()).hexdigest(), value
    )
    value = _FINGERPRINT_RE.sub(lambda m: _fingerprint(resolve_inner(m.group(1))), value)
    return value


def _hmac_sha1(match: re.Match[str], resolve_inner: Callable[[str], str]) -> str:
    inner = match.group(1)
    last_comma = inner.rfind(",")
    if last_comma == -1:
        return match.group(0)
    message = resolve_inner(inner[:last_comma])
    key = resolve_inner(inner[last_comma + 1 :].strip())
    return hmac.new(key.encode(), message.encode(), hashlib.sha1).hexdigest()


def interpolate(value: str, replacers: dict[str, Any]) -> str:
    """Resolve every placeholder in ``value`` against ``replacers``.

    Unresolvable placeholders are left in place so callers can detect them with
    :func:`is_unresolved`.
    """
    if not isinstance(value, str) or "${" not in value:
        return value

    value = _apply_functions(value, lambda inner: interpolate(inner, replacers))

    if "||" in value:
        left, _, right = value.partition("||")
        left, right = left.strip(), right.strip()
        if left:
            resolved = interpolate(left, replacers)
            if resolved and not is_unresolved(resolved):
                return resolved
        return interpolate(right, replacers) if right else ""

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        now_value = _resolve_now(key, replacers)
        if now_value is not None:
            return now_value
        if key == "random":
            return str(replacers.get("random") or uuid.uuid4())
        resolved = _resolve_key(key, replacers)
        if resolved is None or isinstance(resolved, (dict, list, bool)):
            return match.group(0)
        return str(resolved)

    return PLACEHOLDER_RE.sub(substitute, value)


def interpolate_deep(value: Any, replacers: dict[str, Any]) -> Any:
    """Interpolate every string leaf of a nested structure."""
    if isinstance(value, str):
        return interpolate(value, replacers)
    if isinstance(value, dict):
        return {k: interpolate_deep(v, replacers) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate_deep(v, replacers) for v in value]
    return value


def stable_replacers(values: list[str]) -> dict[str, Any]:
    """Freeze ``${now}`` / ``${random}`` so they are identical across one request."""
    joined = "".join(v for v in values if isinstance(v, str))
    out: dict[str, Any] = {}
    if "${random}" in joined:
        out["random"] = str(uuid.uuid4())
    if "${now}" in joined or "${now:" in joined or "${now+" in joined:
        out["now"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return out


def make_url(template: str, config: dict[str, Any]) -> str:
    """Resolve a URL template, raising when placeholders remain."""
    cleaned = template.replace("connectionConfig.", "").replace("credentials.", "")
    resolved = interpolate(cleaned, _drop_empty(config))
    if is_unresolved(resolved):
        raise InterpolationError(
            f"Failed to interpolate URL template: {template}. Missing config parameters.",
            template=template,
            resolved=resolved,
        )
    return resolved


def _drop_empty(obj: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in obj.items():
        if value in ("", None):
            continue
        cleaned[key] = _drop_empty(value) if isinstance(value, dict) else value
    return cleaned
