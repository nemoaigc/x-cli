"""`x-cli list LIST_ID` — Twitter Lists timeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_list_basic(cli):
    client = MagicMock()
    client.fetch_list_timeline.return_value = []
    with patch("x_cli.commands.list_timeline.build_client", return_value=client):
        result = cli(["list", "12345"])

    assert result.exit_code == 0, result.stderr
    client.fetch_list_timeline.assert_called_once_with("12345", count=30)


def test_list_top(cli):
    client = MagicMock()
    client.fetch_list_timeline.return_value = []
    with patch("x_cli.commands.list_timeline.build_client", return_value=client):
        cli(["list", "12345", "--top", "50"])

    client.fetch_list_timeline.assert_called_once_with("12345", count=50)


# ─────────────── codex review followups ──────────────────────────────


def test_list_does_not_advertise_mix_gates(cli):
    """Legacy `scripts/read.py --list ID` was single-page only. Mix-gate
    flags were never wired up. Asserting they're absent so the typer
    surface mirrors legacy: --min-articles passing should error, not
    silently TypeError-crash inside the real client."""
    result = cli(["list", "12345", "--min-articles", "2"])
    assert result.exit_code == 2  # no such option


def test_list_supports_expand_articles_flag(cli):
    """Legacy --expand-articles was a tweet-postprocessing flag, valid on
    all timeline-producing commands. list should expose it."""
    client = MagicMock()
    client.fetch_list_timeline.return_value = []
    with patch("x_cli.commands.list_timeline.build_client", return_value=client):
        result = cli(["list", "12345", "--expand-articles"])
    assert result.exit_code == 0


def test_list_emits_content_kind_per_tweet(cli):
    """Every tweet in the envelope must carry the legacy `content_kind`
    field (was added by _tweet_to_dict)."""
    from x_cli.core.models import Tweet, Author, Metrics
    tw = Tweet(id="t1", author=Author(id="u1", name="K", screen_name="k"),
               text="hi", created_at="", metrics=Metrics())
    client = MagicMock()
    client.fetch_list_timeline.return_value = [tw]
    with patch("x_cli.commands.list_timeline.build_client", return_value=client):
        result = cli(["list", "12345"])
    assert result.exit_code == 0
    data = result.json()["data"]
    assert data[0]["content_kind"] == "tweet"
