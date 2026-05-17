"""x-list subcommand tests — create / delete / add / remove."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_xlist_create_dry_run(cli):
    client = MagicMock()
    with patch("x_cli.commands.xlist.build_client", return_value=client):
        result = cli(["x-list", "create", "My List"])
    assert result.exit_code == 0
    body = result.json()["data"]
    assert body["dry_run"] is True
    assert body["plan"] == {
        "action": "list-create",
        "name": "My List",
        "description": "",
        "mode": "private",
    }
    client.create_list.assert_not_called()


def test_xlist_create_yes(cli, tmp_path, monkeypatch):
    client = MagicMock()
    client.create_list.return_value = {"id_str": "L1", "name": "My List", "mode": "public"}
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", tmp_path / "log.jsonl")
    with patch("x_cli.commands.xlist.build_client", return_value=client):
        result = cli(["x-list", "create", "My List", "--description", "hi", "--public", "--yes"])
    assert result.exit_code == 0
    client.create_list.assert_called_once_with("My List", description="hi", mode="public")
    body = result.json()["data"]
    assert body["list_id"] == "L1"


def test_xlist_create_name_too_long(cli):
    result = cli(["x-list", "create", "x" * 26])
    assert result.exit_code == 2
    body = json.loads(result.stdout)
    assert body["error"]["code"] == "invalid_input"
    assert "25" in body["error"]["message"]


def test_xlist_delete_yes(cli, tmp_path, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", tmp_path / "log.jsonl")
    with patch("x_cli.commands.xlist.build_client", return_value=client):
        result = cli(["x-list", "delete", "123", "--yes"])
    assert result.exit_code == 0
    client.delete_list.assert_called_once_with("123")


def test_xlist_add_dry_run_and_yes(cli, tmp_path, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", tmp_path / "log.jsonl")
    with patch("x_cli.commands.xlist.build_client", return_value=client):
        dr = cli(["x-list", "add", "123", "@alice"])
        assert dr.exit_code == 0 and dr.json()["data"]["dry_run"] is True
        client.add_list_member.assert_not_called()

        ok = cli(["x-list", "add", "123", "@alice", "--yes"])
    assert ok.exit_code == 0
    client.add_list_member.assert_called_once_with("123", "alice")


def test_xlist_remove_yes(cli, tmp_path, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", tmp_path / "log.jsonl")
    with patch("x_cli.commands.xlist.build_client", return_value=client):
        result = cli(["x-list", "remove", "123", "@alice", "--yes"])
    assert result.exit_code == 0
    client.remove_list_member.assert_called_once_with("123", "alice")
