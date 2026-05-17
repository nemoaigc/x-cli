"""tweet subcommand tests — single / article / batch."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_tweet_single_by_id(cli):
    client = MagicMock()
    client.fetch_tweet_detail.return_value = []
    with patch("x_cli.commands.tweet.build_client", return_value=client):
        result = cli(["tweet", "1234567890"])

    assert result.exit_code == 0, result.stderr
    # tweet ID is normalized (URL → ID extraction); plain digits pass through
    client.fetch_tweet_detail.assert_called_once_with("1234567890", 20)


def test_tweet_single_by_url(cli):
    """A status URL gets normalized to the tail ID before fetching."""
    client = MagicMock()
    client.fetch_tweet_detail.return_value = []
    with patch("x_cli.commands.tweet.build_client", return_value=client):
        cli(["tweet", "https://x.com/karpathy/status/1234567890"])

    client.fetch_tweet_detail.assert_called_once_with("1234567890", 20)


def test_tweet_invalid_id_yields_error_envelope(cli):
    result = cli(["tweet", "not-a-valid-id"])
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "invalid_input"


def test_tweet_article(cli):
    client = MagicMock()
    client.fetch_article.return_value = {}
    with patch("x_cli.commands.tweet.build_client", return_value=client):
        result = cli(["tweet-article", "1234567890"])

    assert result.exit_code == 0
    client.fetch_article.assert_called_once_with("1234567890")


def test_tweet_batch(cli):
    client = MagicMock()
    client.fetch_tweets_by_ids.return_value = []
    with patch("x_cli.commands.tweet.build_client", return_value=client):
        result = cli(["tweet-batch", "111", "222", "333"])

    assert result.exit_code == 0
    client.fetch_tweets_by_ids.assert_called_once_with(["111", "222", "333"])


def test_tweet_batch_requires_at_least_one_id(cli):
    result = cli(["tweet-batch"])
    assert result.exit_code == 2
