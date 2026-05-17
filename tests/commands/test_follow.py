"""follow subcommand tests:
   follow / follow remove / block / unblock / mute / unmute
   follow queue add / list / tick / clear
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────── direct follow / unfollow ────────────────────


def test_follow_add_dry_run(cli):
    client = MagicMock()
    with patch("x_cli.commands.follow.build_client", return_value=client):
        result = cli(["follow", "add", "karpathy"])
    assert result.exit_code == 0
    body = result.json()["data"]
    assert body["dry_run"] is True
    assert body["plan"]["handle"] == "karpathy"
    client.follow_user.assert_not_called()


def test_follow_add_yes_calls_client_and_audits(cli, tmp_path, monkeypatch):
    client = MagicMock()
    client.follow_user.return_value = {"id_str": "u1", "following": True}
    log_file = tmp_path / "write-log.jsonl"
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", log_file)
    with patch("x_cli.commands.follow.build_client", return_value=client):
        result = cli(["follow", "add", "karpathy", "--yes"])
    assert result.exit_code == 0
    client.follow_user.assert_called_once_with("karpathy")
    assert log_file.exists()


def test_follow_add_normalizes_handle_at_prefix(cli):
    client = MagicMock()
    with patch("x_cli.commands.follow.build_client", return_value=client):
        result = cli(["follow", "add", "@karpathy"])
    assert result.exit_code == 0
    assert result.json()["data"]["plan"]["handle"] == "karpathy"


@pytest.mark.parametrize("sub,client_method", [
    ("remove",  "unfollow_user"),
    ("block",   "block_user"),
    ("unblock", "unblock_user"),
    ("mute",    "mute_user"),
    ("unmute",  "unmute_user"),
])
def test_follow_social_action_yes(cli, sub, client_method, tmp_path, monkeypatch):
    client = MagicMock()
    getattr(client, client_method).return_value = {"id_str": "u1"}
    log_file = tmp_path / "write-log.jsonl"
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", log_file)
    with patch("x_cli.commands.follow.build_client", return_value=client):
        result = cli(["follow", sub, "karpathy", "--yes"])
    assert result.exit_code == 0, result.stderr
    getattr(client, client_method).assert_called_once_with("karpathy")


# ─────────────────────── queue subcommands ───────────────────────────


def _isolate_queue(tmp_path, monkeypatch):
    """Redirect the queue + audit files to tmp_path so tests don't touch
    the user's real ~/.config files."""
    q = tmp_path / "follow-queue.jsonl"
    log = tmp_path / "write-log.jsonl"
    monkeypatch.setattr("x_cli.follow_queue._QUEUE_PATH", q)
    monkeypatch.setattr("x_cli.write_io._AUDIT_LOG", log)
    return q


def test_queue_add(cli, tmp_path, monkeypatch):
    q = _isolate_queue(tmp_path, monkeypatch)
    result = cli(["follow", "queue", "add", "alice", "@bob", "--reason", "ML week"])
    assert result.exit_code == 0, result.stderr
    body = result.json()["data"]
    assert body["added"] == ["alice", "bob"]
    assert body["queue_size"] == 2
    # Persisted
    lines = q.read_text().strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(l) for l in lines]
    assert parsed[0]["handle"] == "alice"
    assert parsed[0]["status"] == "pending"
    assert parsed[0]["reason"] == "ML week"


def test_queue_add_dedupes_existing_pending(cli, tmp_path, monkeypatch):
    _isolate_queue(tmp_path, monkeypatch)
    cli(["follow", "queue", "add", "alice"])
    result = cli(["follow", "queue", "add", "alice"])
    body = result.json()["data"]
    assert body["added"] == []
    assert body["skipped_already_pending"] == ["alice"]


def test_queue_list_summary(cli, tmp_path, monkeypatch):
    _isolate_queue(tmp_path, monkeypatch)
    cli(["follow", "queue", "add", "alice", "bob"])
    result = cli(["follow", "queue", "list"])
    body = result.json()["data"]
    assert body["total"] == 2
    assert body["by_status"]["pending"] == 2
    assert set(body["next_up"]) == {"alice", "bob"}


def test_queue_clear_pending(cli, tmp_path, monkeypatch):
    _isolate_queue(tmp_path, monkeypatch)
    cli(["follow", "queue", "add", "alice"])
    result = cli(["follow", "queue", "clear", "pending"])
    assert result.exit_code == 0
    body = result.json()["data"]
    assert body["removed"] == 1
    assert body["remaining"] == 0


def test_queue_clear_invalid_mode(cli, tmp_path, monkeypatch):
    _isolate_queue(tmp_path, monkeypatch)
    result = cli(["follow", "queue", "clear", "bogus"])
    assert result.exit_code == 2  # click choice error


def test_queue_tick_processes_pending(cli, tmp_path, monkeypatch):
    _isolate_queue(tmp_path, monkeypatch)
    cli(["follow", "queue", "add", "alice", "bob", "carol"])

    client = MagicMock()
    client.follow_user.return_value = {"id_str": "u1", "following": True}
    with patch("x_cli.commands.follow.build_client", return_value=client):
        result = cli(["follow", "queue", "tick", "--max", "2", "--sleep", "0"])

    assert result.exit_code == 0, result.stderr
    body = result.json()["data"]
    assert body["processed"] == 2
    assert body["followed"] == 2
    assert body["remaining_pending"] == 1
