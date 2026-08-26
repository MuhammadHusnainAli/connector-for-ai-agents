"""The CLI must not leak credentials into terminals, logs, or readable files."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from connector_manager.__main__ import REDACTED, _is_secret_key, _redact, main

SECRET = "SG.a-real-looking-secret-value"


def _connect(argv: list[str]) -> int:
    return main(["connect", "sendgrid", "-c", f"apiKey={SECRET}", "--no-verify", *argv])


# -- what counts as a secret ----------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["apiKey", "api_key", "access_token", "authorization", "x-auth-token", "password",
     "clientSecret", "cookie", "PasswordDigest", "session_id"],
)
def test_secret_keys_are_recognised(key: str) -> None:
    assert _is_secret_key(key)


@pytest.mark.parametrize(
    "key",
    ["auth_mode", "token_type", "monkey", "keyboard", "display_name", "base_url", "endpoint"],
)
def test_ordinary_keys_are_left_alone(key: str) -> None:
    """A name that merely contains secret-ish letters is not a secret."""
    assert not _is_secret_key(key)


def test_redact_masks_every_credential_but_keeps_the_shape() -> None:
    payload = {
        "connector_id": "sendgrid",
        "auth_mode": "API_KEY",
        "credentials": {"type": "API_KEY", "apiKey": SECRET, "expires_at": "2026-01-01T00:00:00Z"},
        "metadata": {"raw": {"access_token": SECRET, "scope": "read"}},
    }
    out = _redact(payload)

    assert out["credentials"]["apiKey"] == REDACTED
    assert out["metadata"]["raw"]["access_token"] == REDACTED
    # bookkeeping survives, so a redacted connection is still readable
    assert out["credentials"]["type"] == "API_KEY"
    assert out["credentials"]["expires_at"] == "2026-01-01T00:00:00Z"
    assert out["auth_mode"] == "API_KEY"
    assert out["connector_id"] == "sendgrid"
    # the original is untouched
    assert payload["credentials"]["apiKey"] == SECRET


# -- the CLI --------------------------------------------------------------------


def test_connect_hides_credentials_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    _connect([])
    out = capsys.readouterr()

    assert SECRET not in out.out
    assert json.loads(out.out)["credentials"]["apiKey"] == REDACTED
    assert "--show-secrets" in out.err


def test_show_secrets_opts_back_in(capsys: pytest.CaptureFixture[str]) -> None:
    _connect(["--show-secrets"])
    out = capsys.readouterr()

    assert json.loads(out.out)["credentials"]["apiKey"] == SECRET


def test_dry_run_request_hides_the_authorization_header(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "conn.json"
    _connect(["-o", str(path)])
    capsys.readouterr()

    main(["request", str(path), "GET", "/v3/scopes", "--dry-run"])
    out = capsys.readouterr()

    assert SECRET not in out.out
    assert json.loads(out.out)["headers"]["authorization"] == REDACTED


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_written_connection_is_private_and_usable(tmp_path) -> None:
    path = tmp_path / "conn.json"
    _connect(["-o", str(path)])

    # the file must still hold the real credential for `request` to work ...
    assert json.loads(path.read_text())["credentials"]["apiKey"] == SECRET
    # ... so nobody else may read it
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_an_existing_world_readable_file_is_tightened(tmp_path) -> None:
    path = tmp_path / "conn.json"
    path.write_text("{}")
    path.chmod(0o644)

    _connect(["-o", str(path)])

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
