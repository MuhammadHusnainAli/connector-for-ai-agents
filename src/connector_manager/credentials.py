"""Parsing of provider token responses into credential dicts.

Providers express token lifetimes in wildly different ways (``expires_in``
seconds or milliseconds, ``expires_at`` dates, ISO durations, JWT ``exp``
claims, ``"177:05:38"`` strings). This module normalises all of them.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .errors import TokenExchangeError
from .interpolation import extract_value_by_path
from .models import AuthMode

#: Fallback lifetime for client-credentials tokens without expiry info (55 min).
DEFAULT_OAUTH_CC_EXPIRES_IN_MS = 55 * 60 * 1000
#: Sentinel "never expires" horizon used for TWO_STEP tokens (10 years).
DEFAULT_INFINITE_EXPIRES_IN_MS = 10 * 365 * 24 * 60 * 60 * 1000
#: Refresh a JWT-derived token this long before its own ``exp``.
REFRESH_MARGIN_MS = 15 * 60 * 1000

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|seconds?|m|mins?|minutes?|h|hrs?|hours?|d|days?|w|weeks?|y|years?)$", re.I)
_DAY_HOUR_MINUTE_RE = re.compile(r"^\d+:\d{2}:\d{2}$")

_DURATION_UNITS_MS = {
    "ms": 1,
    "s": 1000,
    "sec": 1000,
    "secs": 1000,
    "second": 1000,
    "seconds": 1000,
    "m": 60_000,
    "min": 60_000,
    "mins": 60_000,
    "minute": 60_000,
    "minutes": 60_000,
    "h": 3_600_000,
    "hr": 3_600_000,
    "hrs": 3_600_000,
    "hour": 3_600_000,
    "hours": 3_600_000,
    "d": 86_400_000,
    "day": 86_400_000,
    "days": 86_400_000,
    "w": 604_800_000,
    "week": 604_800_000,
    "weeks": 604_800_000,
    "y": 31_536_000_000,
    "year": 31_536_000_000,
    "years": 31_536_000_000,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def in_ms(milliseconds: float) -> datetime:
    return utcnow() + timedelta(milliseconds=milliseconds)


def parse_duration_ms(value: Any) -> int | None:
    """Parse ``"3600"``, ``"1h"``, ``"30 minutes"`` into milliseconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(float(value) * 1000)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text) * 1000
    match = _DURATION_RE.match(text)
    if not match:
        return None
    amount, unit = match.groups()
    unit_ms = _DURATION_UNITS_MS.get(unit.lower())
    return int(float(amount) * unit_ms) if unit_ms else None


def parse_expiration(value: Any) -> datetime | None:
    """Best-effort parse of an expiry expressed as date, epoch or duration."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Values that look like milliseconds when read as seconds land before 1972.
        as_seconds = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
        if as_seconds.year > 1971:
            return as_seconds
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    if text.replace(".", "", 1).isdigit():
        return parse_expiration(float(text))
    if _DAY_HOUR_MINUTE_RE.match(text):
        days, hours, minutes = (int(part) for part in text.split(":"))
        return utcnow() + timedelta(days=days, hours=hours, minutes=minutes)
    return None


def decode_jwt_exp(token: Any) -> datetime | None:
    """Read ``exp`` out of a JWT without verifying it."""
    if not isinstance(token, str) or token.count(".") != 2:
        return None
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None
    exp = payload.get("exp") if isinstance(payload, dict) else None
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(float(exp), tz=timezone.utc)


def parse_raw_credentials(
    raw: dict[str, Any], auth_mode: AuthMode, provider: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Turn a provider token response into a credentials dict."""
    provider = provider or {}

    if auth_mode is AuthMode.OAUTH2:
        return _parse_oauth2(raw, provider)
    if auth_mode is AuthMode.OAUTH2_CC:
        return _parse_oauth2_cc(raw, provider)
    if auth_mode is AuthMode.TWO_STEP:
        return _parse_two_step(raw, provider)
    if auth_mode is AuthMode.OAUTH1:
        if not raw.get("oauth_token") or not raw.get("oauth_token_secret"):
            raise TokenExchangeError("incomplete_raw_credentials", auth_mode=auth_mode.value)
        return {
            "type": AuthMode.OAUTH1.value,
            "oauth_token": raw["oauth_token"],
            "oauth_token_secret": raw["oauth_token_secret"],
            "raw": raw,
        }
    raise TokenExchangeError(
        f"Cannot parse credentials for auth mode {auth_mode.value}", auth_mode=auth_mode.value
    )


def _parse_oauth2(raw: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    access_token = raw.get("access_token")
    context: dict[str, Any] = raw

    alternate_path = provider.get("alternate_access_token_response_path")
    if not access_token and alternate_path:
        alternate = extract_value_by_path(raw, alternate_path)
        if isinstance(alternate, dict):
            context = alternate
            access_token = context.get("access_token")
        else:
            access_token = alternate

    if not access_token:
        raise TokenExchangeError("incomplete_raw_credentials", auth_mode="OAUTH2")

    expires_at = parse_expiration(context.get("expires_at"))
    if expires_at is None and context.get("expires_in") is not None:
        expires_at = in_ms(float(context["expires_in"]) * 1000)

    return {
        "type": AuthMode.OAUTH2.value,
        "access_token": access_token,
        "refresh_token": context.get("refresh_token"),
        "expires_at": iso(expires_at),
        "raw": raw,
    }


def _parse_oauth2_cc(raw: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    token = raw.get("access_token") or (data or {}).get("token") or raw.get("jwt")
    if not token:
        raise TokenExchangeError("incomplete_raw_credentials", auth_mode="OAUTH2_CC")

    expires_at = parse_expiration(raw.get("expires_at"))
    if expires_at is None and raw.get("expires_in") is not None:
        multiplier = 1 if provider.get("expires_in_unit") == "milliseconds" else 1000
        expires_at = in_ms(float(raw["expires_in"]) * multiplier)
    if expires_at is None:
        expires_at = in_ms(DEFAULT_OAUTH_CC_EXPIRES_IN_MS)

    return {
        "type": AuthMode.OAUTH2_CC.value,
        "token": token,
        "expires_at": iso(expires_at),
        "raw": raw,
    }


def _parse_two_step(raw: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    token_response = provider.get("token_response")
    if not isinstance(token_response, dict):
        raise TokenExchangeError("Token response structure is missing for TWO_STEP")

    token_path = token_response.get("token")
    refresh_path = token_response.get("refresh_token")
    expiration_path = token_response.get("token_expiration")
    strategy = token_response.get("token_expiration_strategy") or "expireAt"

    token = extract_value_by_path(raw, token_path) if token_path else raw
    refresh_token = extract_value_by_path(raw, refresh_path) if refresh_path else None
    expiration = extract_value_by_path(raw, expiration_path) if expiration_path else None

    if not token:
        raise TokenExchangeError("incomplete_raw_credentials", auth_mode="TWO_STEP")

    expires_at: datetime | None
    if strategy == "expireAt" and expiration:
        expires_at = parse_expiration(expiration)
    elif strategy == "expireIn" and expiration:
        duration_ms = parse_duration_ms(expiration)
        if duration_ms is None:
            raise TokenExchangeError(f"Unsupported expiration format: {expiration}")
        expires_at = in_ms(duration_ms)
    elif provider.get("token_expires_in_ms") is not None:
        configured = float(provider["token_expires_in_ms"])
        expires_at = in_ms(configured) if configured > 0 else None
    else:
        expires_at = in_ms(DEFAULT_INFINITE_EXPIRES_IN_MS)

    # A JWT's own `exp` wins when it is sooner than whatever we derived above.
    if not expiration:
        jwt_exp = decode_jwt_exp(token)
        if jwt_exp is not None:
            candidate = jwt_exp - timedelta(milliseconds=REFRESH_MARGIN_MS)
            if expires_at is None or candidate < expires_at:
                expires_at = candidate
    if refresh_token:
        refresh_exp = decode_jwt_exp(refresh_token)
        if refresh_exp is not None:
            candidate = refresh_exp - timedelta(milliseconds=REFRESH_MARGIN_MS)
            if expires_at is None or candidate < expires_at:
                expires_at = candidate

    return {
        "type": AuthMode.TWO_STEP.value,
        "token": token,
        "refresh_token": refresh_token,
        "expires_at": iso(expires_at),
        "raw": raw,
    }
