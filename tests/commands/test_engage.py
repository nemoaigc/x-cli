"""engage subcommand tests — like/unlike/retweet/unretweet/bookmark/unbookmark."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.parametrize("subcmd,client_method", [
    ("like",       "like_tweet"),
    ("unlike",     "unlike_tweet"),
    ("retweet",    "retweet"),
    ("unretweet",  "unretweet"),
    ("unbookmark", "unbookmark_tweet"),
])
def test_engage_actions_call_client_method(cli, subcmd, client_method):
    client = MagicMock()
    with patch("x_cli.commands.engage.build_client", return_value=client):
        result = cli(["engage", subcmd, "1234567890"])

    assert result.exit_code == 0, result.stderr
    getattr(client, client_method).assert_called_once_with("1234567890")
    body = result.json()["data"]
    assert body == {"success": True, "tweet_id": "1234567890"}


def test_engage_bookmark_default_no_folder(cli):
    client = MagicMock()
    with patch("x_cli.commands.engage.build_client", return_value=client):
        result = cli(["engage", "bookmark", "111"])

    assert result.exit_code == 0
    client.bookmark_tweet.assert_called_once_with("111", folder_id=None)


def test_engage_bookmark_with_folder(cli):
    client = MagicMock()
    with patch("x_cli.commands.engage.build_client", return_value=client):
        result = cli(["engage", "bookmark", "111", "--folder", "fid-1"])

    assert result.exit_code == 0
    client.bookmark_tweet.assert_called_once_with("111", folder_id="fid-1")


def test_engage_normalizes_tweet_url(cli):
    client = MagicMock()
    with patch("x_cli.commands.engage.build_client", return_value=client):
        cli(["engage", "like", "https://x.com/foo/status/9999"])

    client.like_tweet.assert_called_once_with("9999")
