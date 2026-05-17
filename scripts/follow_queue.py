#!/usr/bin/env python3
"""follow_queue.py — queued, rate-limit-aware follow scheduler for x-cli.

Workflow:
  1. `add`    — append handles to the queue
  2. `tick`   — pop up to N pending handles, try to follow each via write.py,
                update status (follows what succeeded, keeps rate-limited for retry)
  3. `list`   — inspect queue state
  4. `clear`  — drop pending / all entries

Designed to be invoked by launchd / cron every few hours. Each `tick` defaults
to at most 3 follows (safe for small / new accounts); X's burst threshold
kicks in well before the documented daily ~400 cap.

Queue file: ~/.config/x-cli/follow-queue.jsonl (one JSON object per line)
Status values: pending | followed | rate_limited | error | skipped
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._core.output import (
    add_common_args, emit_error, emit_ok, setup_logging,
    normalize_handle_arg, require_positive_int,
)
from scripts._core.exceptions import InvalidInputError, XQueryError
from scripts._core import paths as _paths

logger = logging.getLogger(__name__)

_QUEUE_PATH = _paths.follow_queue_path()
_PROJECT = Path(__file__).resolve().parent.parent
_DEFAULT_TICK_MAX = 3  # safe for small accounts; tune via --max


def _audit_follow(profile: Optional[str], handle: str, user_id: Optional[str]) -> None:
    """Append a follow action to the shared write-log.jsonl (same format as write.py)."""
    log_path = _paths.write_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "profile": profile or "<default>",
            "action": "follow",
            "target": handle,
            "result": {"action": "follow", "handle": handle, "user_id": user_id,
                       "via": "follow_queue"},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Audit log append failed: %s", exc)


def _read_queue() -> List[Dict]:
    if not _QUEUE_PATH.exists():
        return []
    entries = []
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


def _write_queue(entries: List[Dict]) -> None:
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _QUEUE_PATH.with_suffix(".jsonl.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, _QUEUE_PATH)


def _add_entries(handles: List[str], reason: Optional[str]) -> Dict:
    entries = _read_queue()
    existing_pending = {e["handle"]: i for i, e in enumerate(entries) if e.get("status") == "pending"}
    added, skipped = [], []
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
    _write_queue(entries)
    return {"added": added, "skipped_already_pending": skipped, "queue_size": len(entries)}


def _list_summary(filter_status: Optional[str] = None) -> Dict:
    entries = _read_queue()
    if filter_status:
        entries = [e for e in entries if e.get("status") == filter_status]
    by_status: Dict[str, int] = {}
    for e in entries:
        s = e.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1
    pending = [e for e in entries if e.get("status") == "pending"][:20]
    return {
        "total": len(entries),
        "by_status": by_status,
        "next_up": [e["handle"] for e in pending],
    }


def _clear_queue(mode: str) -> Dict:
    entries = _read_queue()
    before = len(entries)
    if mode == "all":
        entries = []
    elif mode == "pending":
        entries = [e for e in entries if e.get("status") != "pending"]
    elif mode == "completed":
        entries = [e for e in entries if e.get("status") == "pending"]
    else:
        raise InvalidInputError("clear mode must be one of: all, pending, completed")
    _write_queue(entries)
    return {"removed": before - len(entries), "remaining": len(entries)}


def _follow_once(client, handle: str) -> Dict:
    """Call client.follow_user directly. Returns {'ok', 'code', 'msg', 'data'}.

    Maps TwitterAPIError / RateLimitError into the same shape write.py's audit
    entries use, so downstream logs stay homogeneous.
    """
    from scripts._core.exceptions import RateLimitError, TwitterAPIError

    try:
        result = client.follow_user(handle)
        return {"ok": True, "code": "ok", "msg": "", "data": result}
    except RateLimitError as exc:
        return {"ok": False, "code": "rate_limited", "msg": str(exc)[:200]}
    except TwitterAPIError as exc:
        msg = str(exc)
        code = "api_error"
        return {"ok": False, "code": code, "msg": msg[:200]}
    except Exception as exc:
        return {"ok": False, "code": "unexpected", "msg": str(exc)[:200]}


def _tick(profile: Optional[str], max_follows: int, sleep_between_s: float, client=None) -> Dict:
    entries = _read_queue()
    pending = [e for e in entries if e.get("status") == "pending"]
    if not pending:
        return {"processed": 0, "followed": 0, "rate_limited": 0, "errors": 0, "remaining_pending": 0}

    if client is None:
        from scripts._core.output import build_client
        client = build_client(profile)

    processed = 0
    followed = 0
    rate_limited = 0
    errors = 0
    results: List[Dict] = []

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
            entry["status"] = "pending"  # retry next tick
            rate_limited += 1
        elif r["code"] == "api_error" and "already following" in (r.get("msg") or "").lower():
            entry["status"] = "followed"  # idempotent: X says already following
            followed += 1
            _audit_follow(profile, entry["handle"], None)
        else:
            entry["status"] = "error"
            entry["last_error"] = {"code": r["code"], "msg": r["msg"]}
            errors += 1
        results.append({"handle": entry["handle"], "status": entry["status"], "code": r["code"]})
        if sleep_between_s > 0 and processed < max_follows:
            time.sleep(sleep_between_s)

    _write_queue(entries)
    remaining = sum(1 for e in entries if e.get("status") == "pending")
    return {
        "processed": processed,
        "followed": followed,
        "rate_limited": rate_limited,
        "errors": errors,
        "remaining_pending": remaining,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="follow_queue.py",
        description="Queued, rate-limit-aware follow scheduler.",
    )
    add_common_args(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Append handles to the queue (pending)")
    p_add.add_argument("handles", nargs="+", help="Handles to enqueue (with or without @)")
    p_add.add_argument("--reason", default=None, help="Optional tag for this batch")

    p_list = sub.add_parser("list", help="Show queue state")
    p_list.add_argument("--status", choices=["pending", "followed", "rate_limited", "error"], default=None)

    p_tick = sub.add_parser("tick", help="Pop N pending handles and try to follow each")
    p_tick.add_argument("--max", type=int, default=_DEFAULT_TICK_MAX, metavar="N",
                        help="Max follows this tick (default: %d)" % _DEFAULT_TICK_MAX)
    p_tick.add_argument("--sleep", type=float, default=3.0, metavar="SEC",
                        help="Sleep seconds between follows (default: 3.0)")

    p_clear = sub.add_parser("clear", help="Remove queue entries")
    p_clear.add_argument("mode", choices=["pending", "completed", "all"])

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        if args.cmd == "add":
            result = _add_entries(args.handles, args.reason)
            emit_ok(result, args.yaml)
        elif args.cmd == "list":
            emit_ok(_list_summary(args.status), args.yaml)
        elif args.cmd == "tick":
            require_positive_int("--max", args.max)
            result = _tick(args.profile, args.max, args.sleep)
            emit_ok(result, args.yaml)
        elif args.cmd == "clear":
            emit_ok(_clear_queue(args.mode), args.yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("queue_failed", str(exc), args.yaml)
        sys.exit(1)


if __name__ == "__main__":
    main()
