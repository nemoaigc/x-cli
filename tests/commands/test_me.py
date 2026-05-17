"""me subcommand tests — self-scoped reads."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_me_status(cli, fake_user):
    client = MagicMock()
    client.fetch_me.return_value = fake_user
    with patch("x_cli.commands.me.build_client", return_value=client):
        result = cli(["me", "status"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    assert data["authenticated"] is True
    assert data["profile"]["screen_name"] == "testuser"


def test_me_health(cli, fake_user):
    """health probe returns status/checked_at/warnings + auth + read flag."""
    client = MagicMock()
    client.fetch_me.return_value = fake_user
    client.fetch_home_timeline.return_value = []
    with patch("x_cli.commands.me.build_client", return_value=client):
        result = cli(["me", "health"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    assert data["status"] in {"ok", "warn", "fail"}
    assert data["authenticated"] is True


def test_me_likes_uses_my_id(cli, fake_user):
    client = MagicMock()
    client.fetch_me.return_value = fake_user
    client.fetch_user_likes.return_value = []
    with patch("x_cli.commands.me.build_client", return_value=client):
        result = cli(["me", "likes", "--max", "10"])

    assert result.exit_code == 0
    client.fetch_user_likes.assert_called_once_with(fake_user.id, count=10)


def test_me_bookmarks_default(cli):
    client = MagicMock()
    client.fetch_bookmarks.return_value = []
    with patch("x_cli.commands.me.build_client", return_value=client):
        result = cli(["me", "bookmarks"])

    assert result.exit_code == 0
    client.fetch_bookmarks.assert_called_once_with()


def test_me_bookmarks_list_folders(cli):
    client = MagicMock()
    client.fetch_bookmark_folders.return_value = []
    with patch("x_cli.commands.me.build_client", return_value=client):
        result = cli(["me", "bookmarks", "--list-folders"])

    assert result.exit_code == 0
    client.fetch_bookmark_folders.assert_called_once_with()


def test_me_bookmarks_by_folder(cli):
    client = MagicMock()
    client.fetch_bookmark_folder_timeline.return_value = []
    with patch("x_cli.commands.me.build_client", return_value=client):
        result = cli(["me", "bookmarks", "--folder", "fid-1"])

    assert result.exit_code == 0
    client.fetch_bookmark_folder_timeline.assert_called_once_with("fid-1")


def test_me_mentions(cli, fake_user):
    """mentions probes notification timeline; on success returns the tweets."""
    client = MagicMock()
    client.fetch_me.return_value = fake_user
    client.fetch_search.return_value = []  # fallback path always works
    with patch("x_cli.commands.me.build_client", return_value=client), \
         patch("x_cli.commands.me._probe_mentions", return_value=[]):
        result = cli(["me", "mentions", "--max", "5"])

    assert result.exit_code == 0, result.stderr
    data = result.json()["data"]
    assert isinstance(data, list)
