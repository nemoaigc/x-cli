"""feed subcommand tests — `x-cli feed list` + `x-cli feed NAME`."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


# ───────────────────── feed list (pinned timelines) ───────────────────


def test_feed_list_returns_pinned_timelines(cli):
    client = MagicMock()
    client.fetch_pinned_timelines.return_value = [
        {"tag": "abc", "tab_label": "AI", "name": "AI feed"},
        {"tag": "def", "tab_label": "Crypto", "name": "Crypto"},
    ]
    with patch("x_cli.commands.feed.build_client", return_value=client):
        result = cli(["feed", "list"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    assert isinstance(data, list)
    assert data[0]["tab_label"] == "AI"


# ───────────────────── feed for-you / following ──────────────────────


def test_feed_for_you_dispatches_to_home_timeline(cli):
    client = MagicMock()
    client.fetch_home_timeline.return_value = []
    with patch("x_cli.commands.feed.build_client", return_value=client):
        result = cli(["feed", "for-you"])

    assert result.exit_code == 0, result.stderr
    # fetch_home_timeline called once with count=top default (30)
    client.fetch_home_timeline.assert_called_once_with(count=30)


def test_feed_following_dispatches_to_following_feed(cli):
    client = MagicMock()
    client.fetch_following_feed.return_value = []
    with patch("x_cli.commands.feed.build_client", return_value=client):
        cli(["feed", "following", "--top", "50"])

    client.fetch_following_feed.assert_called_once_with(count=50)


# ───────────────────── custom pinned feed by name ────────────────────


def test_feed_custom_resolves_name_to_tag_id(cli):
    """A non-canonical name → look up via pinned_timelines list, match by
    tab_label or name (case-insensitive), then fetch_custom_timeline."""
    client = MagicMock()
    client.fetch_pinned_timelines.return_value = [
        {"tag": "tag-ai", "tab_label": "AI", "name": "AI feed"},
    ]
    client.fetch_custom_timeline.return_value = []
    with patch("x_cli.commands.feed.build_client", return_value=client):
        result = cli(["feed", "ai", "--top", "10"])

    assert result.exit_code == 0, result.stderr
    # Case-insensitive match to tab_label "AI"
    args, kwargs = client.fetch_custom_timeline.call_args
    # Could be called either positionally or by kw; allow both
    if args:
        assert args[0] == "tag-ai"
    else:
        assert kwargs["tag_id"] == "tag-ai"


def test_feed_unknown_name_yields_unknown_feed_error(cli):
    client = MagicMock()
    client.fetch_pinned_timelines.return_value = [
        {"tag": "x", "tab_label": "AI", "name": "AI feed"},
    ]
    with patch("x_cli.commands.feed.build_client", return_value=client):
        result = cli(["feed", "nope"])

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "unknown_feed"
    assert "AI" in body["error"]["message"]
