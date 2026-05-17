"""Shared write-command helpers — used by post / follow / x-list.

Encapsulates the dry-run / execute / audit cycle from the legacy
`scripts/write.py`:

    plan = build_plan(...)        # validates input, no API calls
    if not yes:                   # default: dry-run
        emit_dry_run(plan)
    else:
        payload = do(client, plan)
        audit(profile, plan, payload)
        emit_ok(payload)

Usage:

    plan = {"action": "follow", "handle": "karpathy"}
    if not yes:
        dry_run_envelope(plan, c.use_yaml)
        return
    payload = client.follow_user(plan["handle"])
    audit_write(c.profile, plan, payload)
    emit_ok(payload, c.use_yaml)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from x_cli.core import paths as _paths
from x_cli.core.output import emit_ok


logger = logging.getLogger(__name__)

_AUDIT_LOG = _paths.write_log_path()

TEXT_MAX = 280          # standard tweet
LONG_TEXT_MAX = 25_000  # X Premium long-form cap


def audit_write(profile: str | None, plan: dict, result: dict) -> None:
    """Append one JSONL entry to the write log. Failures are warnings only."""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "profile": profile or "<default>",
            "action": plan.get("action"),
            "target": audit_target_for(plan),
            "result": result,
        }
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Failed to append audit log: %s", exc)


def audit_target_for(plan: dict) -> Any:
    """Pick the primary target string for the audit entry."""
    if "tweet_id" in plan:
        return plan["tweet_id"]
    if "handle" in plan:
        return plan["handle"]
    if "list_id" in plan:
        return plan.get("list_id") or plan.get("name") or "?"
    return plan.get("name") or "?"


def dry_run_envelope(plan: dict, use_yaml: bool = False) -> None:
    emit_ok(
        {
            "dry_run": True,
            "plan": plan,
            "hint": "Pass --yes to actually execute",
        },
        use_yaml,
    )
