"""Per-request signatures for clouds that sign every call rather than send a token.

Two schemes are implemented, each declared on a connector as data:

``proxy.aws_sigv4``
    AWS Signature Version 4. ``{"service": "lambda", "region": "${connectionConfig.region}"}``.
    The access key id and secret come from the connection's ``username`` and
    ``password`` (BASIC), optionally with a ``sessionToken`` credential.

``proxy.acs3``
    Alibaba Cloud ACS3-HMAC-SHA256 (the V3 signature). ``{}`` or
    ``{"version": "2014-05-26"}``. The AccessKey id and secret come from
    ``username`` and ``password``; ``x-acs-action`` is supplied per call as a
    header (a default can be set with ``"action"``), and ``x-acs-version``
    defaults to the declared ``version``.

Both sign the request exactly as it goes on the wire: the body is serialised
here and handed to the transport as raw content, so the bytes hashed are the
bytes sent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

#: Characters RFC 3986 leaves unreserved; both clouds encode everything else.
_UNRESERVED = "-_.~"


def utcnow() -> datetime:
    """Signing clock. Tests replace this to reproduce published vectors."""
    return datetime.now(timezone.utc)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _encode(value: str) -> str:
    return quote(value, safe=_UNRESERVED)


def serialise_body(json_body: Any, content: str | bytes | None) -> bytes:
    """The exact bytes that will be sent, so the payload hash matches the wire."""
    if content is not None:
        return content.encode("utf-8") if isinstance(content, str) else content
    if json_body is not None:
        return json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b""


def canonical_query(url_query: str, params: Mapping[str, str]) -> str:
    pairs = parse_qsl(url_query, keep_blank_values=True) + [(str(k), str(v)) for k, v in params.items()]
    encoded = sorted((_encode(k), _encode(v)) for k, v in pairs)
    return "&".join(f"{k}={v}" for k, v in encoded)


def _wire_path(path: str) -> str:
    """The path percent-encoded once, as it will be sent."""
    return quote(unquote(path or "/"), safe="/" + _UNRESERVED) or "/"


def _canonical_headers(headers: Mapping[str, str], signed: list[str]) -> str:
    return "".join(f"{name}:{' '.join(str(headers[name]).split())}\n" for name in signed)


def sign_aws_sigv4(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    params: Mapping[str, str],
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    session_token: str | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """Return ``(url, headers)`` with an AWS SigV4 ``authorization`` header.

    The returned url carries the path re-encoded exactly as it was signed.
    """
    now = now or utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    parsed = urlparse(url)

    out = {k.lower(): v for k, v in headers.items() if k.lower() != "authorization"}
    out["host"] = parsed.netloc
    out["x-amz-date"] = amz_date
    if session_token:
        out["x-amz-security-token"] = session_token
    payload_hash = _sha256_hex(body)
    if service == "s3":
        # S3 requires the payload hash as a header; other services reject nothing
        # but also need nothing, and leaving it off keeps the published vectors.
        out["x-amz-content-sha256"] = payload_hash

    wire_path = _wire_path(parsed.path)
    # S3 signs the path as sent; every other service signs it encoded twice.
    canonical_uri = wire_path if service == "s3" else quote(wire_path, safe="/" + _UNRESERVED)
    signed = sorted(
        name for name in out if name in ("host", "content-type", "content-md5") or name.startswith("x-amz-")
    )
    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_query(parsed.query, params),
            _canonical_headers(out, signed),
            ";".join(signed),
            payload_hash,
        ]
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )
    key = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    out["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(signed)}, Signature={signature}"
    )
    out.pop("host")  # the transport sets Host from the url; it was signed as that value
    new_url = urlunparse(parsed._replace(path=wire_path))
    return new_url, out


def sign_acs3(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    params: Mapping[str, str],
    body: bytes,
    access_key: str,
    secret_key: str,
    security_token: str | None = None,
    now: datetime | None = None,
    nonce: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Return ``(url, headers)`` signed with Alibaba Cloud ACS3-HMAC-SHA256."""
    now = now or utcnow()
    parsed = urlparse(url)

    out = {k.lower(): v for k, v in headers.items() if k.lower() != "authorization"}
    out["host"] = parsed.netloc
    out["x-acs-date"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["x-acs-signature-nonce"] = nonce or uuid.uuid4().hex
    out["x-acs-content-sha256"] = _sha256_hex(body)
    if security_token:
        out["x-acs-security-token"] = security_token

    wire_path = _wire_path(parsed.path)
    signed = sorted(name for name in out if name in ("host", "content-type") or name.startswith("x-acs-"))
    canonical_request = "\n".join(
        [
            method.upper(),
            wire_path,
            canonical_query(parsed.query, params),
            _canonical_headers(out, signed),
            ";".join(signed),
            out["x-acs-content-sha256"],
        ]
    )
    string_to_sign = "ACS3-HMAC-SHA256\n" + _sha256_hex(canonical_request.encode("utf-8"))
    signature = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    out["authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={access_key},SignedHeaders={';'.join(signed)},Signature={signature}"
    )
    out.pop("host")
    return urlunparse(parsed._replace(path=wire_path)), out
