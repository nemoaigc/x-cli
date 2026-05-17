"""search subcommand tests — `x-cli search [QUERY] [filters]` + `search users`."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


# ─────────────────────── tweet search (default) ───────────────────────


def test_search_basic(cli):
    client = MagicMock()
    client.fetch_search.return_value = []
    with patch("x_cli.commands.search.build_client", return_value=client):
        result = cli(["search", "claude code"])

    assert result.exit_code == 0, result.stderr
    # fetch_search is called with the constructed query string + defaults
    args, kwargs = client.fetch_search.call_args
    # build_search_query("claude code") just returns the bare text
    assert args[0] == "claude code"
    # default product=Top, count=30
    assert kwargs.get("product", args[2] if len(args) > 2 else None) == "Top"


def test_search_with_all_filters(cli):
    client = MagicMock()
    client.fetch_search.return_value = []
    with patch("x_cli.commands.search.build_client", return_value=client):
        result = cli([
            "search", "claude code",
            "--since", "2026-05-10",
            "--until", "2026-05-17",
            "--lang", "en",
            "--from-user", "karpathy",
            "--min-likes", "100",
            "--min-retweets", "10",
            "--product", "Latest",
            "--top", "50",
        ])

    assert result.exit_code == 0, result.stderr
    args, kwargs = client.fetch_search.call_args
    query_str = args[0]
    # build_search_query appends operators
    assert "claude code" in query_str
    assert "lang:en" in query_str
    assert "from:karpathy" in query_str
    assert "since:2026-05-10" in query_str
    assert "until:2026-05-17" in query_str
    assert "min_faves:100" in query_str  # X operator name for likes
    assert "min_retweets:10" in query_str
    assert kwargs.get("product") == "Latest" or args[2] == "Latest"


def test_search_invalid_product_rejected(cli):
    result = cli(["search", "x", "--product", "Bogus"])
    assert result.exit_code == 2
    # typer / click prints the choice error to stderr — we just check exit
    # (typer raises before our error envelope path)


def test_search_invalid_date_format_yields_error_envelope(cli):
    result = cli(["search", "x", "--since", "not-a-date"])
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "invalid_input"


def test_search_requires_query(cli):
    result = cli(["search"])
    assert result.exit_code == 2  # click default for missing required arg


# ─────────────────────── user search ──────────────────────────────────


def test_search_users(cli):
    client = MagicMock()
    client.search_users.return_value = []
    with patch("x_cli.commands.search.build_client", return_value=client):
        result = cli(["search-users", "karpathy"])

    assert result.exit_code == 0, result.stderr
    client.search_users.assert_called_once_with("karpathy", 30)


def test_search_users_top(cli):
    client = MagicMock()
    client.search_users.return_value = []
    with patch("x_cli.commands.search.build_client", return_value=client):
        cli(["search-users", "karpathy", "--top", "5"])

    client.search_users.assert_called_once_with("karpathy", 5)
