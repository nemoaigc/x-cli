#!/usr/bin/env python3
"""me.py — self-scoped reads and engagement writes for x-query.

Usage:
  uv run scripts/me.py status
  uv run scripts/me.py likes [--max N]
  uv run scripts/me.py bookmarks [--folder FOLDER_ID]
  uv run scripts/me.py mentions [--max N]
  uv run scripts/me.py like <tweet_id_or_url>
  uv run scripts/me.py unlike <tweet_id_or_url>
  uv run scripts/me.py retweet <tweet_id_or_url>
  uv run scripts/me.py unretweet <tweet_id_or_url>
  uv run scripts/me.py bookmark <tweet_id_or_url> [--folder FOLDER_ID]
  uv run scripts/me.py unbookmark <tweet_id_or_url>
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._core.output import add_common_args, build_client, emit_error, emit_ok, setup_logging
from scripts._core.output import normalize_required_text, require_positive_int
from scripts._core.search import _normalize_tweet_id
from scripts._core.exceptions import XQueryError

logger = logging.getLogger(__name__)


def _probe_health(client, warn_days: int = 7) -> dict:
    """Structured cookie health probe for cron / monitoring.

    Returns:
      status: "ok" | "warn" | "fail"
      details: what was checked + any warnings
    """
    import time
    result = {
        "status": "ok",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "warnings": [],
        "errors": [],
    }
    # 1. Can we authenticate?
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

    # 2. Can we do a simple read?
    try:
        tweets = client.fetch_home_timeline(count=1)
        result["home_timeline_ok"] = bool(tweets or tweets == [])
    except Exception as exc:
        result["status"] = "warn"
        result["warnings"].append({"type": "read", "message": str(exc)[:200]})

    # 3. Cookie staleness hint
    # X's auth_token doesn't expose an expiry in the cookie itself, but we can
    # nudge by checking the profile file's mtime (when the user last saved).
    try:
        import os
        from scripts._core import paths
        profile_name = getattr(client, "_profile_name", None)
        candidates = []
        if profile_name:
            candidates.append(paths.profiles_dir() / f"{profile_name}.json")
            candidates.append(paths.legacy_profiles_dir() / f"{profile_name}.json")
        for p in candidates:
            if p and p.exists():
                age_days = (time.time() - os.path.getmtime(p)) / 86400
                result["profile_file_age_days"] = round(age_days, 1)
                # X auth_token typically lasts ~12 months, cookies get refreshed by browser use
                # Warn at 11 months
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


def _probe_mentions(client, max_count: int):
    """Probe for mentions/notifications queryId and return results.

    Tries several candidate operations until one returns a populated response.
    Falls back to search; raises if the fallback itself fails.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Candidate operations to try — probe in order
    candidates = [
        ("NotificationsTimeline", {"count": max_count}),
        ("Notifications", {"count": max_count}),
    ]
    # Also try SearchTimeline for @-mentions as a reliable fallback
    for op_name, variables in candidates:
        try:
            from scripts._core.graphql import FALLBACK_QUERY_IDS, _resolve_query_id
            # Only attempt if we have a fallback or the bundle scan cached it
            try:
                query_id = _resolve_query_id(op_name, prefer_fallback=True, url_fetch_fn=None)
            except Exception:
                continue
            data = client._graphql_get(op_name, variables, {})
            # Walk common instruction paths
            instructions = (
                data.get("data", {}).get("notification_timeline", {}).get("timeline", {}).get("instructions")
                or data.get("data", {}).get("notifications_timeline", {}).get("timeline", {}).get("instructions")
                or []
            )
            from scripts._core.parser import parse_timeline_response, _deep_get
            tweets, _ = parse_timeline_response(data, lambda d: instructions)
            if tweets:
                logger.info("mentions: %s returned %d items", op_name, len(tweets))
                return tweets[:max_count]
        except Exception as exc:
            logger.debug("mentions probe %s failed: %s", op_name, exc)
            continue

    # Reliable fallback: search for @<screen_name> mentions
    try:
        me = client.fetch_me()
        q = "to:%s -from:%s" % (me.screen_name, me.screen_name)
        tweets = client.fetch_search(q, count=max_count, product="Latest")
        return tweets
    except Exception as exc:
        logger.warning("mentions search fallback failed: %s", exc)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="x-query me — self-scoped reads and engagement writes",
    )
    add_common_args(parser)

    subparsers = parser.add_subparsers(dest="subcmd", required=True, metavar="COMMAND")

    # status
    subparsers.add_parser("status", help="Auth check + my profile")

    # health — structured cookie health probe for cron / Hermes
    p_health = subparsers.add_parser(
        "health",
        help="Probe cookie health; emits structured OK / WARN / FAIL + queryIds check",
    )
    p_health.add_argument("--warn-days", type=int, default=7, metavar="N",
                          help="Warn if cookie is believed to be within N days of staleness (default: 7)")

    # likes
    p_likes = subparsers.add_parser("likes", help="My liked tweets")
    p_likes.add_argument("--max", type=int, default=50, metavar="N")

    # bookmarks
    p_bm = subparsers.add_parser("bookmarks", help="My bookmarks (optionally filtered by folder)")
    p_bm.add_argument("--folder", metavar="FOLDER_ID", help="Bookmark folder ID")
    p_bm.add_argument("--list-folders", action="store_true", help="List all bookmark folders")

    # mentions
    p_mentions = subparsers.add_parser("mentions", help="Mentions of my account")
    p_mentions.add_argument("--max", type=int, default=20, metavar="N")

    # like
    p_like = subparsers.add_parser("like", help="Like a tweet")
    p_like.add_argument("tweet", metavar="ID_OR_URL")

    # unlike
    p_unlike = subparsers.add_parser("unlike", help="Un-like a tweet")
    p_unlike.add_argument("tweet", metavar="ID_OR_URL")

    # retweet
    p_rt = subparsers.add_parser("retweet", help="Retweet")
    p_rt.add_argument("tweet", metavar="ID_OR_URL")

    # unretweet
    p_urt = subparsers.add_parser("unretweet", help="Un-retweet")
    p_urt.add_argument("tweet", metavar="ID_OR_URL")

    # bookmark
    p_bookmark = subparsers.add_parser("bookmark", help="Bookmark a tweet")
    p_bookmark.add_argument("tweet", metavar="ID_OR_URL")
    p_bookmark.add_argument("--folder", metavar="FOLDER_ID", help="Add to bookmark folder")

    # unbookmark
    p_ubm = subparsers.add_parser("unbookmark", help="Remove a bookmark")
    p_ubm.add_argument("tweet", metavar="ID_OR_URL")

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        if hasattr(args, "max"):
            require_positive_int("--max", args.max)
            if args.max > 200:
                logger.warning(
                    "--max %d exceeds default per-client cap (200); results will be clamped.",
                    args.max,
                )
        if hasattr(args, "folder") and args.folder is not None:
            args.folder = normalize_required_text("--folder", args.folder)
        client = build_client(args.profile)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("startup_error", str(exc), args.yaml)
        sys.exit(1)

    try:
        if args.subcmd == "status":
            me = client.fetch_me()
            emit_ok({"authenticated": True, "profile": dataclasses.asdict(me)}, args.yaml)

        elif args.subcmd == "health":
            result = _probe_health(client, args.warn_days)
            emit_ok(result, args.yaml)

        elif args.subcmd == "likes":
            me = client.fetch_me()
            tweets = client.fetch_user_likes(me.id, count=args.max)
            emit_ok([dataclasses.asdict(t) for t in tweets], args.yaml)

        elif args.subcmd == "bookmarks":
            if args.list_folders:
                folders = client.fetch_bookmark_folders()
                emit_ok([dataclasses.asdict(f) for f in folders], args.yaml)
            elif args.folder:
                tweets = client.fetch_bookmark_folder_timeline(args.folder)
                emit_ok([dataclasses.asdict(t) for t in tweets], args.yaml)
            else:
                tweets = client.fetch_bookmarks()
                emit_ok([dataclasses.asdict(t) for t in tweets], args.yaml)

        elif args.subcmd == "mentions":
            tweets = _probe_mentions(client, args.max)
            emit_ok([dataclasses.asdict(t) for t in tweets], args.yaml)

        elif args.subcmd == "like":
            tweet_id = _normalize_tweet_id(args.tweet)
            client.like_tweet(tweet_id)
            emit_ok({"success": True, "tweet_id": tweet_id}, args.yaml)

        elif args.subcmd == "unlike":
            tweet_id = _normalize_tweet_id(args.tweet)
            client.unlike_tweet(tweet_id)
            emit_ok({"success": True, "tweet_id": tweet_id}, args.yaml)

        elif args.subcmd == "retweet":
            tweet_id = _normalize_tweet_id(args.tweet)
            client.retweet(tweet_id)
            emit_ok({"success": True, "tweet_id": tweet_id}, args.yaml)

        elif args.subcmd == "unretweet":
            tweet_id = _normalize_tweet_id(args.tweet)
            client.unretweet(tweet_id)
            emit_ok({"success": True, "tweet_id": tweet_id}, args.yaml)

        elif args.subcmd == "bookmark":
            tweet_id = _normalize_tweet_id(args.tweet)
            client.bookmark_tweet(tweet_id, folder_id=getattr(args, "folder", None))
            emit_ok({"success": True, "tweet_id": tweet_id}, args.yaml)

        elif args.subcmd == "unbookmark":
            tweet_id = _normalize_tweet_id(args.tweet)
            client.unbookmark_tweet(tweet_id)
            emit_ok({"success": True, "tweet_id": tweet_id}, args.yaml)

    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("unexpected_error", str(exc), args.yaml)
        sys.exit(1)


if __name__ == "__main__":
    main()
