"""user subcommand tests — `x-cli user HANDLE [--mode] [--top N]`.

Modes are mutually exclusive; default (no mode) = profile metadata.
Every other mode maps 1:1 to a client.fetch_user_* / fetch_followers /
fetch_following / fetch_recommended_users call.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────── default: profile metadata ────────────────────


def test_user_default_returns_profile_metadata(cli, fake_user):
    client = MagicMock()
    client.fetch_user.return_value = fake_user
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "@testuser"])

    assert result.exit_code == 0, result.stderr
    body = result.json()
    assert body["ok"] is True
    profile = body["data"]
    # Handle is normalized — leading @ stripped before the fetch call.
    client.fetch_user.assert_called_once_with("testuser")
    assert profile["screen_name"] == "testuser"
    assert profile["followers_count"] == 42


def test_user_unknown_handle_exits_nonzero(cli):
    from x_cli.core.exceptions import NotFoundError
    client = MagicMock()
    client.fetch_user.side_effect = NotFoundError("User @nobody not found")
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "@nobody"])

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "not_found"


# ─────────────────────── tweets / replies / media / likes / articles / highlights ───


@pytest.mark.parametrize("flag,client_method", [
    ("--tweets",     "fetch_user_tweets"),
    ("--replies",    "fetch_user_replies"),
    ("--media",      "fetch_user_media"),
    ("--likes",      "fetch_user_likes"),
    ("--articles",   "fetch_user_articles"),
    ("--highlights", "fetch_user_highlights"),
])
def test_user_timeline_modes_dispatch_to_correct_client_method(cli, flag, client_method):
    client = MagicMock()
    client.resolve_user_id.return_value = "u123"
    getattr(client, client_method).return_value = []  # empty timeline OK for dispatch check
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "karpathy", flag, "--top", "5"])

    assert result.exit_code == 0, result.stderr
    client.resolve_user_id.assert_called_once_with("karpathy")
    getattr(client, client_method).assert_called_once_with("u123", 5)


def test_user_tweets_default_top_is_30(cli):
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_user_tweets.return_value = []
    with patch("x_cli.commands.user.build_client", return_value=client):
        cli(["user", "karpathy", "--tweets"])

    client.fetch_user_tweets.assert_called_once_with("u1", 30)


def test_user_mutually_exclusive_modes_reject(cli):
    """--tweets and --likes together is an error."""
    result = cli(["user", "karpathy", "--tweets", "--likes"])
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "invalid_input"
    assert "exclusive" in body["error"]["message"].lower() or "one of" in body["error"]["message"].lower()


# ─────────────────────── followers / following / recommended ──────────


def test_user_followers(cli):
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_followers.return_value = []
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "karpathy", "--followers", "--top", "10"])

    assert result.exit_code == 0
    client.fetch_followers.assert_called_once_with("u1", 10)


def test_user_following(cli):
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_following.return_value = []
    with patch("x_cli.commands.user.build_client", return_value=client):
        cli(["user", "karpathy", "--following", "--top", "10"])

    client.fetch_following.assert_called_once_with("u1", 10)


def test_user_recommended_for_specific_handle(cli):
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_recommended_users.return_value = []
    with patch("x_cli.commands.user.build_client", return_value=client):
        cli(["user", "karpathy", "--recommended", "--top", "10"])

    client.fetch_recommended_users.assert_called_once_with(user_id="u1", count=10)


def test_user_recommended_general_no_handle(cli):
    """`x-cli user --recommended` (no HANDLE) → recommendations for me."""
    client = MagicMock()
    client.fetch_recommended_users.return_value = []
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "--recommended", "--top", "20"])

    assert result.exit_code == 0, result.stderr
    client.fetch_recommended_users.assert_called_once_with(user_id=None, count=20)
    # Must NOT have called resolve_user_id (no handle to resolve)
    client.resolve_user_id.assert_not_called()


def test_user_no_handle_without_recommended_is_error(cli):
    """Bare `x-cli user` is invalid — needs either a HANDLE or --recommended."""
    result = cli(["user"])
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "invalid_input"


# ─────────────────────── output shape: tweets ──────────────────────────


def test_user_tweets_returns_tweet_list_in_envelope(cli):
    """Returned tweets are serialised as a JSON list under data."""
    from x_cli.core.models import Tweet, Author, Metrics
    tw = Tweet(
        id="t1",
        author=Author(id="u1", name="K", screen_name="karpathy"),
        text="hello",
        created_at="2026-05-17T00:00:00Z",
        metrics=Metrics(),
    )
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_user_tweets.return_value = [tw]
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "karpathy", "--tweets", "--top", "1"])

    assert result.exit_code == 0
    body = result.json()
    assert body["ok"] is True
    data = body["data"]
    # The shape downstream consumers depend on: list of tweet dicts.
    assert isinstance(data, list) or (isinstance(data, dict) and "tweets" in data)


# ─────────────── codex review followups ──────────────────────────────


def test_user_tweets_emits_content_kind_per_item(cli):
    """`user HANDLE --tweets` must carry the legacy `content_kind` field on
    each tweet (legacy _emit_tweets always added it)."""
    from x_cli.core.models import Tweet, Author, Metrics
    tw = Tweet(id="t1", author=Author(id="u1", name="K", screen_name="k"),
               text="hi", created_at="", metrics=Metrics())
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_user_tweets.return_value = [tw]
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "karpathy", "--tweets"])
    assert result.exit_code == 0
    data = result.json()["data"]
    assert data[0]["content_kind"] == "tweet"


def test_user_tweets_supports_expand_articles_flag(cli):
    """`user HANDLE --tweets --expand-articles` must be accepted (legacy flag)."""
    client = MagicMock()
    client.resolve_user_id.return_value = "u1"
    client.fetch_user_tweets.return_value = []
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "karpathy", "--tweets", "--expand-articles"])
    assert result.exit_code == 0


def test_user_profile_metadata_unaffected_by_timeline_fields(cli, fake_user):
    """Default mode (no --tweets etc.) returns the bare UserProfile dict.
    Don't accidentally attach content_kind / etc. here."""
    client = MagicMock()
    client.fetch_user.return_value = fake_user
    with patch("x_cli.commands.user.build_client", return_value=client):
        result = cli(["user", "@karpathy"])
    assert result.exit_code == 0
    profile = result.json()["data"]
    assert "content_kind" not in profile
    assert profile["screen_name"] == "testuser"
