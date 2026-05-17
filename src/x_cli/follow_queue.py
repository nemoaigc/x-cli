"""follow_queue — JSONL-backed follow scheduler. CLI-agnostic helpers.

Mirrors the logic from legacy `scripts/follow_queue.py`, sans argparse;
the `x-cli follow queue …` subcommands wrap these.

Queue file: `~/.config/x-cli/follow-queue.jsonl`
Entry shape:
  {"handle": "...", "added_at": "...", "status": "pending"|"followed"|...,
   "attempts": int, "reason": str|None, "user_id": str|None,
   "last_attempt_at": "...", "last_error": {"code", "msg"}|None}
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from x_cli.core import paths as _paths
from x_cli.core.exceptions import InvalidInputError
from x_cli.core.output import normalize_handle_arg


logger = logging.getLogger(__name__)

_QUEUE_PATH = _paths.follow_queue_path()
DEFAULT_TICK_MAX = 3


# ───────────────────────── on-disk helpers ────────────────────────────


def _read() -> list[dict]:
    if not _QUEUE_PATH.exists():
        return []
    entries: list[dict] = []
    with open(_QUEUE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed queue line: %s", exc)
    return entries


def _write(entries: list[dict]) -> None:
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _QUEUE_PATH.with_suffix(".jsonl.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, _QUEUE_PATH)


def _audit_follow(profile: str | None, handle: str, user_id: str | None) -> None:
    """Append a queued-follow event to the shared write-log."""
    log_path = _paths.write_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "profile": profile or "<default>",
            "action": "follow",
            "target": handle,
            "result": {"action": "follow", "handle": handle,
                       "user_id": user_id, "via": "follow_queue"},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Audit log append failed: %s", exc)


# ───────────────────────── public API ─────────────────────────────────


def add_entries(handles: list[str], reason: str | None) -> dict[str, Any]:
    entries = _read()
    existing_pending = {e["handle"] for e in entries if e.get("status") == "pending"}
    added: list[str] = []
    skipped: list[str] = []
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for h in handles:
        clean = normalize_handle_arg("handle", h)
        if clean in existing_pending:
            skipped.append(clean)
            continue
        entries.append({
            "handle": clean, "added_at": ts, "status": "pending",
            "attempts": 0, "reason": reason,
        })
        added.append(clean)
    _write(entries)
    return {"added": added, "skipped_already_pending": skipped, "queue_size": len(entries)}


def list_summary(filter_status: str | None = None) -> dict[str, Any]:
    entries = _read()
    if filter_status:
        entries = [e for e in entries if e.get("status") == filter_status]
    by_status: dict[str, int] = {}
    for e in entries:
        s = e.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1
    pending = [e for e in entries if e.get("status") == "pending"][:20]
    return {
        "total": len(entries),
        "by_status": by_status,
        "next_up": [e["handle"] for e in pending],
    }


def clear_queue(mode: str) -> dict[str, Any]:
    entries = _read()
    before = len(entries)
    if mode == "all":
        entries = []
    elif mode == "pending":
        entries = [e for e in entries if e.get("status") != "pending"]
    elif mode == "completed":
        entries = [e for e in entries if e.get("status") == "pending"]
    else:
        raise InvalidInputError("clear mode must be one of: all, pending, completed")
    _write(entries)
    return {"removed": before - len(entries), "remaining": len(entries)}


def _follow_once(client, handle: str) -> dict[str, Any]:
    from x_cli.core.exceptions import RateLimitError, TwitterAPIError
    try:
        result = client.follow_user(handle)
        return {"ok": True, "code": "ok", "msg": "", "data": result}
    except RateLimitError as exc:
        return {"ok": False, "code": "rate_limited", "msg": str(exc)[:200]}
    except TwitterAPIError as exc:
        return {"ok": False, "code": "api_error", "msg": str(exc)[:200]}
    except Exception as exc:
        return {"ok": False, "code": "error", "msg": str(exc)[:200]}


def tick(
    profile: str | None,
    max_follows: int,
    sleep_between_s: float,
    client=None,
) -> dict[str, Any]:
    entries = _read()
    pending = [e for e in entries if e.get("status") == "pending"]
    if not pending:
        return {"processed": 0, "followed": 0, "rate_limited": 0,
                "errors": 0, "remaining_pending": 0}

    if client is None:
        from x_cli.core.output import build_client
        client = build_client(profile)

    processed = followed = rate_limited = errors = 0
    results: list[dict] = []

    for entry in pending:
        if processed >= max_follows:
            break
        processed += 1
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_attempt_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        r = _follow_once(client, entry["handle"])
        if r["ok"]:
            entry["status"] = "followed"
            user_id = (r.get("data") or {}).get("id_str")
            entry["user_id"] = user_id
            followed += 1
            _audit_follow(profile, entry["handle"], user_id)
        elif r["code"] == "rate_limited":
            entry["status"] = "pending"
            rate_limited += 1
        elif r["code"] == "api_error" and "already following" in (r.get("msg") or "").lower():
            entry["status"] = "followed"
            followed += 1
            _audit_follow(profile, entry["handle"], None)
        else:
            entry["status"] = "error"
            entry["last_error"] = {"code": r["code"], "msg": r["msg"]}
            errors += 1
        results.append({"handle": entry["handle"], "status": entry["status"], "code": r["code"]})
        if sleep_between_s > 0 and processed < max_follows:
            time.sleep(sleep_between_s)

    _write(entries)
    remaining = sum(1 for e in entries if e.get("status") == "pending")
    return {
        "processed": processed,
        "followed": followed,
        "rate_limited": rate_limited,
        "errors": errors,
        "remaining_pending": remaining,
        "results": results,
    }
