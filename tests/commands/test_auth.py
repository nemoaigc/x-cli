"""auth subcommand tests — TDD spec for `x-cli auth …`.

Envelope shape (locked from `core/output.py`):
  ok:    {"ok": true,  "schema_version": "1", "data": {...}}
  err:   {"ok": false, "schema_version": "1", "error": {"code": str, "message": str}}
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


# ─────────────────────────── auth status ──────────────────────────────


def test_auth_status_authenticated(cli, fake_user):
    """`auth status` with a working session yields the live /me payload
    inside an envelope with default_profile context."""
    client = MagicMock()
    client.fetch_me.return_value = fake_user
    with patch("x_cli.commands.auth.build_client", return_value=client), \
         patch("x_cli.commands.auth.get_default_profile", return_value="default"):
        result = cli(["auth", "status"])

    assert result.exit_code == 0, result.stderr
    body = result.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["authenticated"] is True
    assert data["default_profile"] == "default"
    profile = data["profile"]
    assert profile["id"] == "123"
    assert profile["screen_name"] == "testuser"
    assert profile["followers_count"] == 42


def test_auth_status_not_authenticated_exits_nonzero(cli):
    from x_cli.core.exceptions import AuthenticationError
    with patch(
        "x_cli.commands.auth.build_client",
        side_effect=AuthenticationError("no cookies"),
    ):
        result = cli(["auth", "status"])

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["ok"] is False
    assert body["error"]["code"] == "not_authenticated"
    assert "no cookies" in body["error"]["message"]


# ─────────────────────────── auth list ────────────────────────────────


def test_auth_list_returns_profile_names_and_default(cli):
    with patch("x_cli.commands.auth.list_profiles", return_value=["alice", "bob"]), \
         patch("x_cli.commands.auth.get_default_profile", return_value="alice"):
        result = cli(["auth", "list"])

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    assert body["data"] == {"profiles": ["alice", "bob"], "default": "alice"}


# ─────────────────────────── auth add ─────────────────────────────────


def test_auth_add_with_explicit_token_and_ct0_saves_profile(cli):
    with patch("x_cli.commands.auth.save_profile") as save:
        result = cli([
            "auth", "add", "ci-bot",
            "--token", "abc", "--ct0", "def",
        ])

    save.assert_called_once_with("ci-bot", auth_token="abc", ct0="def")
    assert result.exit_code == 0
    body = result.json()
    assert body["data"] == {"saved": "ci-bot"}


def test_auth_add_rejects_token_without_ct0(cli):
    result = cli(["auth", "add", "broken", "--token", "abc"])
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_input"
    assert "ct0" in body["error"]["message"].lower()


def test_auth_add_without_token_extracts_from_browser(cli):
    cookies = {"auth_token": "T", "ct0": "C", "cookie_string": "T=...; C=..."}
    with patch(
        "x_cli.commands.auth.extract_from_browser",
        return_value=(cookies, {}),
    ), patch("x_cli.commands.auth.save_profile") as save:
        result = cli(["auth", "add", "ci-bot"])

    save.assert_called_once_with(
        "ci-bot",
        auth_token="T",
        ct0="C",
        cookie_string="T=...; C=...",
    )
    assert result.exit_code == 0


def test_auth_add_no_cookies_found_exits_nonzero(cli):
    with patch(
        "x_cli.commands.auth.extract_from_browser",
        return_value=({}, {"reason": "no browser cookies"}),
    ):
        result = cli(["auth", "add", "ci-bot"])

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "not_authenticated"


# ─────────────────────────── auth remove ──────────────────────────────


def test_auth_remove_existing_profile(cli):
    with patch("x_cli.commands.auth.remove_profile", return_value=True):
        result = cli(["auth", "remove", "alice"])
    assert result.exit_code == 0
    assert result.json()["data"] == {"removed": "alice"}


def test_auth_remove_missing_profile_exits_nonzero(cli):
    with patch("x_cli.commands.auth.remove_profile", return_value=False):
        result = cli(["auth", "remove", "nope"])
    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "not_found"


# ─────────────────────────── auth use ─────────────────────────────────


def test_auth_use_sets_default(cli):
    with patch("x_cli.commands.auth.load_profile", return_value={"name": "alice"}), \
         patch("x_cli.commands.auth.set_default_profile") as setdef:
        result = cli(["auth", "use", "alice"])

    setdef.assert_called_once_with("alice")
    assert result.exit_code == 0
    assert result.json()["data"] == {"default": "alice"}


def test_auth_use_unknown_profile_exits_nonzero(cli):
    with patch("x_cli.commands.auth.load_profile", return_value=None):
        result = cli(["auth", "use", "nope"])
    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "not_found"


# ─────────────────────────── YAML flag ────────────────────────────────


def test_yaml_flag_emits_yaml_envelope(cli):
    """--yaml on the root parser switches output format."""
    with patch("x_cli.commands.auth.list_profiles", return_value=["a"]), \
         patch("x_cli.commands.auth.get_default_profile", return_value="a"):
        result = cli(["--yaml", "auth", "list"])

    assert result.exit_code == 0
    assert "ok: true" in result.stdout
    assert "profiles:" in result.stdout
