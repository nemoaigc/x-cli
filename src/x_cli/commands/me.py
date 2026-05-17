"""`x-cli me …` — self-scoped reads.

Subcommands:
  status                                Auth check + my profile
  health [--warn-days N]                Structured cookie health probe
  likes [--max N]                       My liked tweets (default 50)
  bookmarks [--folder ID --list-folders]
  mentions [--max N]                    Mentions of my account (default 20)

(Write actions — like / retweet / bookmark — moved to `x-cli engage`.)
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from typing import Any

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok


logger = logging.getLogger(__name__)

me_app = typer.Typer(
    name="me",
    help="Self-scoped reads (status, health, likes, bookmarks, mentions).",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _serialize_list(items):
    return [dataclasses.asdict(x) if dataclasses.is_dataclass(x) and not isinstance(x, type) else x
            for x in items]


# ───────────────────────── health probe ───────────────────────────────


def _probe_health(client, warn_days: int = 7) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ok",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "warnings": [],
        "errors": [],
    }

    try:
        me = client.fetch_me()
        result["authenticated"] = True
        result["screen_name"] = me.screen_name
        result["user_id"] = me.id
    except Exception as exc:
        result["status"] = "fail"
        result["authenticated"] = False
        result["errors"].append({"type": "auth", "message": str(exc)[:300]})
        return result

    try:
        tweets = client.fetch_home_timeline(count=1)
        result["home_timeline_ok"] = bool(tweets or tweets == [])
    except Exception as exc:
        result["status"] = "warn"
        result["warnings"].append({"type": "read", "message": str(exc)[:200]})

    try:
        from x_cli.core import paths
        profile_name = getattr(client, "_profile_name", None)
        candidates = []
        if profile_name:
            candidates.append(paths.profiles_dir() / f"{profile_name}.json")
            candidates.append(paths.legacy_profiles_dir() / f"{profile_name}.json")
        for p in candidates:
            if p and p.exists():
                age_days = (time.time() - os.path.getmtime(p)) / 86400
                result["profile_file_age_days"] = round(age_days, 1)
                if age_days > 365 - warn_days:
                    result["status"] = result["status"] if result["status"] == "fail" else "warn"
                    result["warnings"].append({
                        "type": "stale_profile",
                        "message": f"Profile file is {age_days:.0f} days old; re-save soon",
                    })
                break
    except Exception:
        pass

    return result


# ───────────────────────── mentions probe ─────────────────────────────


def _probe_mentions(client, max_count: int):
    """Probe notification timeline; fall back to search for @-mentions."""
    candidates = [
        ("NotificationsTimeline", {"count": max_count}),
        ("Notifications", {"count": max_count}),
    ]
    for op_name, variables in candidates:
        try:
            from x_cli.core.graphql import _resolve_query_id
            try:
                _resolve_query_id(op_name, prefer_fallback=True, url_fetch_fn=None)
            except Exception:
                continue
            data = client._graphql_get(op_name, variables, {})
            instructions = (
                data.get("data", {}).get("notification_timeline", {}).get("timeline", {}).get("instructions")
                or data.get("data", {}).get("notifications_timeline", {}).get("timeline", {}).get("instructions")
                or []
            )
            from x_cli.core.parser import parse_timeline_response
            tweets, _ = parse_timeline_response(data, lambda d: instructions)
            if tweets:
                logger.info("mentions: %s returned %d items", op_name, len(tweets))
                return tweets[:max_count]
        except Exception as exc:
            logger.debug("mentions probe %s failed: %s", op_name, exc)
            continue

    # Reliable fallback: search for @<screen_name>
    me = client.fetch_me()
    q = f"to:{me.screen_name} -from:{me.screen_name}"
    return client.fetch_search(q, count=max_count, product="Latest")


# ───────────────────────── subcommands ────────────────────────────────


@me_app.command("status")
def status_cmd(ctx: typer.Context) -> None:
    """Auth check + my profile."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        me = client.fetch_me()
        emit_ok({"authenticated": True, "profile": dataclasses.asdict(me)}, c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@me_app.command("health")
def health_cmd(
    ctx: typer.Context,
    warn_days: int = typer.Option(7, "--warn-days", metavar="N"),
) -> None:
    """Structured cookie health probe (cron / monitoring friendly)."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        emit_ok(_probe_health(client, warn_days), c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@me_app.command("likes")
def likes_cmd(
    ctx: typer.Context,
    max_: int = typer.Option(50, "--max", metavar="N"),
) -> None:
    """My liked tweets."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        me = client.fetch_me()
        tweets = client.fetch_user_likes(me.id, count=max_)
        emit_ok(_serialize_list(tweets), c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@me_app.command("bookmarks")
def bookmarks_cmd(
    ctx: typer.Context,
    folder: str | None = typer.Option(None, "--folder", metavar="FOLDER_ID"),
    list_folders: bool = typer.Option(False, "--list-folders"),
) -> None:
    """My bookmarks (optionally by folder)."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        if list_folders:
            emit_ok(_serialize_list(client.fetch_bookmark_folders()), c.use_yaml)
        elif folder:
            emit_ok(_serialize_list(client.fetch_bookmark_folder_timeline(folder)), c.use_yaml)
        else:
            emit_ok(_serialize_list(client.fetch_bookmarks()), c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@me_app.command("mentions")
def mentions_cmd(
    ctx: typer.Context,
    max_: int = typer.Option(20, "--max", metavar="N"),
) -> None:
    """Mentions of my account."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        tweets = _probe_mentions(client, max_)
        emit_ok(_serialize_list(tweets), c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)
