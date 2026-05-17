"""trend subcommand tests — `x-cli trend scan / drill`."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _make_trend(trend_id="100", name="AI", post_count=1000, is_ai_trend=True):
    """Trend factory. `trend_id` must be all-digits for the id-lookup path
    (mirrors the legacy `isdigit()` check in digest._resolve_trend)."""
    from x_cli.core.models import Trend
    return Trend(name=name, trend_id=trend_id, post_count=post_count, is_ai_trend=is_ai_trend)


# ────────────────────────── trend scan ───────────────────────────────


def test_trend_scan_returns_sorted_trends(cli):
    client = MagicMock()
    trends = [_make_trend("200", "Crypto", 500, False), _make_trend("100", "AI", 1000, True)]
    with patch("x_cli.commands.trend.build_client", return_value=client), \
         patch("x_cli.commands.trend.fetch_all_tabs", return_value=trends):
        result = cli(["trend", "scan"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    # AI weighted ×2 → first
    assert data[0]["name"] == "AI"


# ────────────────────────── trend drill ──────────────────────────────


def test_trend_drill_by_id(cli):
    client = MagicMock()
    client.fetch_search.return_value = []
    trend = _make_trend("100", "AI")
    with patch("x_cli.commands.trend.build_client", return_value=client), \
         patch("x_cli.commands.trend.fetch_all_tabs", return_value=[trend]), \
         patch("x_cli.commands.trend.fetch_trend_kols", return_value=[]):
        result = cli(["trend", "drill", "100", "--top", "5"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    assert data["trend_id"] == "100"
    assert data["trend_name"] == "AI"
    assert "kols" in data
    assert "tweets" in data
    # Search was called with top=5
    client.fetch_search.assert_called_once()
    args, kwargs = client.fetch_search.call_args
    assert kwargs.get("count", args[1] if len(args) > 1 else None) == 5


def test_trend_drill_unknown_id_yields_error(cli):
    client = MagicMock()
    with patch("x_cli.commands.trend.build_client", return_value=client), \
         patch("x_cli.commands.trend.fetch_all_tabs", return_value=[]):
        result = cli(["trend", "drill", "999"])

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "invalid_input"


# ─────────────────────── trend scan-drill-top ────────────────────────


def test_trend_scan_drill_top(cli):
    """`trend scan --drill-top N` = scan + auto-drill top N trends."""
    client = MagicMock()
    client.fetch_search.return_value = []
    trends = [_make_trend("100", "AI", 1000), _make_trend("200", "Crypto", 500, False)]
    with patch("x_cli.commands.trend.build_client", return_value=client), \
         patch("x_cli.commands.trend.fetch_all_tabs", return_value=trends), \
         patch("x_cli.commands.trend.fetch_trend_kols", return_value=[]):
        result = cli(["trend", "scan", "--drill-top", "1", "--top", "10"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    assert "trends" in data
    assert "drilled" in data
    assert len(data["drilled"]) == 1
    assert data["drilled"][0]["trend_id"] == "100"
