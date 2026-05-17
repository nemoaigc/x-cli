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


def test_list_mix_gates_trigger_paging(cli):
    """When --min-articles or --min-posts is set, the mix-gate paging loop
    runs (calls fetch with cursor + return_cursor=True)."""
    client = MagicMock()
    client.fetch_list_timeline.return_value = ([], None)  # mix-gate signature
    with patch("x_cli.commands.list_timeline.build_client", return_value=client):
        result = cli(["list", "12345", "--top", "10", "--min-articles", "2"])

    assert result.exit_code == 0
    # First call must use cursor+return_cursor (mix mode)
    args, kwargs = client.fetch_list_timeline.call_args
    assert kwargs.get("return_cursor") is True or (len(args) >= 3 and args[2] is True)
