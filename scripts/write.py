#!/usr/bin/env python3
"""write.py — write mode entry point for x-cli.

Every subcommand defaults to --dry-run. Pass --yes to actually call X.
Every --yes call appends to ~/.config/x-cli/write-log.jsonl for audit.

Usage:
  uv run scripts/write.py post --text "Hello"
  uv run scripts/write.py post --text "Hello" --yes
  uv run scripts/write.py post --text "..." --reply-to 12345 --yes
  uv run scripts/write.py delete 12345 --yes
  uv run scripts/write.py follow karpathy --yes
  uv run scripts/write.py mute spammer --yes
  uv run scripts/write.py list-create "My List" --yes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._core.output import (
    add_common_args, build_client, emit_error, emit_ok, setup_logging,
    normalize_handle_arg, normalize_required_text, normalize_numeric_id_arg,
)
from scripts._core.exceptions import InvalidInputError, XQueryError
from scripts._core import paths as _paths

logger = logging.getLogger(__name__)

_AUDIT_LOG = _paths.write_log_path()
_TEXT_MAX = 280        # standard tweet
_LONG_TEXT_MAX = 25000 # X Premium long-form hard cap


def _audit(profile, action, target, result):
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "profile": profile or "<default>",
            "action": action,
            "target": target,
            "result": result,
        }
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Failed to append audit log: %s", exc)


def _validate_post_text(text, allow_long=False):
    text = text.strip()
    if not text:
        raise InvalidInputError("--text must not be empty")
    cap = _LONG_TEXT_MAX if allow_long else _TEXT_MAX
    if len(text) > cap:
        raise InvalidInputError(
            "--text is %d chars; max %d%s" % (
                len(text), cap,
                " (with --long)" if allow_long else
                " (pass --long for Note Tweets up to 25000; requires X Premium)",
            )
        )
    return text


# ── Subcommand registry ──────────────────────────────────────────────────────
#
# Each Command has three callables:
#   add_args(parser)             — register argparse args for this subcommand
#   plan(namespace) -> dict      — validate + normalize into a plan dict
#   do(client, plan) -> payload  — call the client method, return the envelope
#                                  payload (action + relevant fields). --yes
#                                  and dry-run handling is centralized below.
#
# To add a new write op: write three small functions, append one Command.

@dataclass
class Command:
    name: str
    help: str
    add_args: Callable[[argparse.ArgumentParser], None]
    plan: Callable[[argparse.Namespace], Dict[str, Any]]
    do: Callable[[Any, Dict[str, Any]], Dict[str, Any]]


# ── add_args helpers ─────────────────────────────────────────────────────────

def _args_post(p):
    p.add_argument("--text", required=True, help="Tweet text")
    p.add_argument("--reply-to", metavar="ID", help="Reply to a tweet")
    p.add_argument("--quote", metavar="ID", help="Quote-tweet a tweet")
    p.add_argument("--media", metavar="FILE", nargs="+", help="Up to 4 local media files")
    p.add_argument("--long", action="store_true", help="Allow >280 chars (Note Tweet, ≤25000; needs X Premium)")


def _args_tweet_id(p):
    p.add_argument("tweet_id", help="Tweet ID")


def _args_handle(p):
    p.add_argument("handle", help="Screen name (with or without @)")


def _args_list_create(p):
    p.add_argument("name", help="List name (≤25 chars)")
    p.add_argument("--description", default="", help="List description")
    p.add_argument("--public", action="store_true", help="Make list public (default: private)")


def _args_list_with_id(p):
    p.add_argument("list_id", help="List ID")


def _args_list_member(p):
    p.add_argument("list_id", help="List ID")
    p.add_argument("handle", help="Screen name to add/remove")


# ── plan() helpers: validate+normalize into a plan dict ─────────────────────

def _plan_post(a):
    text = _validate_post_text(a.text, allow_long=a.long)
    reply_to = normalize_numeric_id_arg("--reply-to", a.reply_to) if a.reply_to else None
    quote = normalize_numeric_id_arg("--quote", a.quote) if a.quote else None
    if reply_to and quote:
        raise InvalidInputError("--reply-to and --quote are mutually exclusive")
    media = a.media or []
    if len(media) > 4:
        raise InvalidInputError("--media accepts up to 4 files per tweet")
    for m in media:
        if not os.path.isfile(m):
            raise InvalidInputError("--media file not found: %s" % m)
    return {"action": "post", "text": text, "length": len(text),
            "reply_to": reply_to, "quote": quote, "media": media}


def _plan_tweet_id(action_name):
    def fn(a):
        return {"action": action_name, "tweet_id": normalize_numeric_id_arg("tweet_id", a.tweet_id)}
    return fn


def _plan_handle(action_name):
    def fn(a):
        return {"action": action_name, "handle": normalize_handle_arg("handle", a.handle)}
    return fn


def _plan_list_create(a):
    name = normalize_required_text("name", a.name)
    if len(name) > 25:
        raise InvalidInputError("list name must be ≤25 chars")
    return {"action": "list-create", "name": name,
            "description": (a.description or "").strip(),
            "mode": "public" if a.public else "private"}


def _plan_list_delete(a):
    return {"action": "list-delete",
            "list_id": normalize_numeric_id_arg("list_id", a.list_id)}


def _plan_list_member(action_name):
    def fn(a):
        return {"action": action_name,
                "list_id": normalize_numeric_id_arg("list_id", a.list_id),
                "handle": normalize_handle_arg("handle", a.handle)}
    return fn


# ── do() helpers: call client, return payload ───────────────────────────────

def _do_post(client, p):
    media_ids = []
    for m in p.get("media") or []:
        mid = client.upload_media(m)
        media_ids.append(mid)
        logger.info("Uploaded media %s → id=%s", m, mid)
    result = client.create_tweet(
        p["text"], reply_to=p["reply_to"], quote_tweet_id=p["quote"],
        media_ids=media_ids or None,
    )
    tweet_id = result.get("rest_id") or "?"
    return {"action": "post", "tweet_id": tweet_id,
            "url": "https://x.com/i/web/status/%s" % tweet_id,
            "text": p["text"], "media_ids": media_ids or None}


def _do_delete(client, p):
    client.delete_tweet(p["tweet_id"])
    return {"action": "delete", "tweet_id": p["tweet_id"], "deleted": True}


def _do_follow(client, p):
    r = client.follow_user(p["handle"])
    return {"action": "follow", "handle": p["handle"],
            "user_id": r.get("id_str"), "following": r.get("following", True)}


def _do_unfollow(client, p):
    r = client.unfollow_user(p["handle"])
    return {"action": "unfollow", "handle": p["handle"],
            "user_id": r.get("id_str"), "following": r.get("following", False)}


def _do_social(action_name):
    """Factory for block/unblock/mute/unmute."""
    def fn(client, p):
        method = getattr(client, f"{action_name}_user")
        r = method(p["handle"])
        return {"action": action_name, "handle": p["handle"], "user_id": r.get("id_str")}
    return fn


def _do_tweet_action(action_name, method_name=None):
    """Factory for pin/unpin/hide-reply/unhide-reply."""
    method_name = method_name or action_name.replace("-", "_")
    def fn(client, p):
        getattr(client, f"{method_name}_tweet" if method_name in ("pin", "unpin") else method_name)(p["tweet_id"])
        return {"action": action_name, "tweet_id": p["tweet_id"], "ok": True}
    return fn


def _do_list_create(client, p):
    r = client.create_list(p["name"], description=p["description"], mode=p["mode"])
    return {"action": "list-create", "list_id": r.get("id_str"),
            "name": r.get("name"), "mode": r.get("mode")}


def _do_list_delete(client, p):
    client.delete_list(p["list_id"])
    return {"action": "list-delete", "list_id": p["list_id"], "ok": True}


def _do_list_add(client, p):
    client.add_list_member(p["list_id"], p["handle"])
    return {"action": "list-add", "list_id": p["list_id"],
            "handle": p["handle"], "ok": True}


def _do_list_remove(client, p):
    client.remove_list_member(p["list_id"], p["handle"])
    return {"action": "list-remove", "list_id": p["list_id"],
            "handle": p["handle"], "ok": True}


# ── The registry ─────────────────────────────────────────────────────────────

COMMANDS = [
    Command("post",    "Post a tweet (reply/quote/media/long all supported)",
            _args_post, _plan_post, _do_post),
    Command("delete",  "Delete one of your tweets",
            _args_tweet_id, _plan_tweet_id("delete"), _do_delete),
    Command("follow",   "Follow a user",           _args_handle, _plan_handle("follow"),   _do_follow),
    Command("unfollow", "Unfollow a user",         _args_handle, _plan_handle("unfollow"), _do_unfollow),
    Command("block",    "Block a user",            _args_handle, _plan_handle("block"),    _do_social("block")),
    Command("unblock",  "Unblock a user",          _args_handle, _plan_handle("unblock"),  _do_social("unblock")),
    Command("mute",     "Mute a user",             _args_handle, _plan_handle("mute"),     _do_social("mute")),
    Command("unmute",   "Unmute a user",           _args_handle, _plan_handle("unmute"),   _do_social("unmute")),
    Command("pin",      "Pin one of your tweets",  _args_tweet_id, _plan_tweet_id("pin"),    _do_tweet_action("pin")),
    Command("unpin",    "Unpin a pinned tweet",    _args_tweet_id, _plan_tweet_id("unpin"),  _do_tweet_action("unpin")),
    Command("hide-reply",   "Hide a reply to your tweet",
            _args_tweet_id, _plan_tweet_id("hide-reply"),   _do_tweet_action("hide-reply", "hide_reply")),
    Command("unhide-reply", "Unhide a hidden reply",
            _args_tweet_id, _plan_tweet_id("unhide-reply"), _do_tweet_action("unhide-reply", "unhide_reply")),
    Command("list-create", "Create a new X List",
            _args_list_create, _plan_list_create, _do_list_create),
    Command("list-delete", "Delete one of your Lists",
            _args_list_with_id, _plan_list_delete, _do_list_delete),
    Command("list-add",    "Add a user to your List",
            _args_list_member, _plan_list_member("list-add"),    _do_list_add),
    Command("list-remove", "Remove a user from your List",
            _args_list_member, _plan_list_member("list-remove"), _do_list_remove),
]


def _audit_target_for(plan):
    """Pick the primary target string for the audit log entry."""
    if "tweet_id" in plan:
        return plan["tweet_id"]
    if "handle" in plan:
        return plan["handle"]
    if "list_id" in plan:
        return plan.get("list_id") or plan.get("name") or "?"
    return plan.get("name") or "?"


def main():
    parser = argparse.ArgumentParser(
        prog="write.py",
        description="x-cli write mode — all mutating ops. Default --dry-run; pass --yes to execute.",
    )
    add_common_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    cmd_index = {cmd.name: cmd for cmd in COMMANDS}
    for cmd in COMMANDS:
        sp = subparsers.add_parser(cmd.name, help=cmd.help)
        cmd.add_args(sp)
        sp.add_argument("--yes", action="store_true",
                        help="Actually execute (default is dry-run)")

    args = parser.parse_args()
    setup_logging(args.verbose)

    cmd = cmd_index.get(args.command)
    if cmd is None:
        emit_error("invalid_input", "Unknown command: %s" % args.command, args.yaml)
        sys.exit(2)

    # Plan phase (no API calls)
    try:
        plan = cmd.plan(args)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("invalid_input", str(exc), args.yaml)
        sys.exit(2)

    if not args.yes:
        emit_ok({"dry_run": True, "plan": plan,
                 "hint": "Pass --yes to actually execute"}, args.yaml)
        return

    # Execution phase
    try:
        client = build_client(args.profile)
        payload = cmd.do(client, plan)
        _audit(args.profile, plan["action"], _audit_target_for(plan), payload)
        emit_ok(payload, args.yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("write_failed", str(exc), args.yaml)
        sys.exit(1)


if __name__ == "__main__":
    main()
