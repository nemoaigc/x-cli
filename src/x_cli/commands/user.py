"""`x-cli user [HANDLE] [--mode] [--top N]` — single-user reads.

Modes (mutually exclusive):
  (none)         Profile metadata (UserProfile)
  --tweets       Recent tweets
  --replies      Posts + Replies tab
  --media        Media tab
  --likes        Liked tweets (public)
  --articles     Articles tab
  --highlights   Highlights tab
  --followers    Followers list
  --following    Following list
  --recommended  "Who to follow" recommendations (HANDLE optional;
                 omitting gives recommendations for the logged-in user)

Tweet-list modes route through `emit_timeline` so they pick up:
  - `content_kind` per tweet
  - `you_follow_author` follow annotation when auth is available
  - `--expand-articles` post-processing

User-list modes (--followers / --following / --recommended) emit a list of
UserProfile dicts directly — no tweet-specific enrichment applies.
"""
from __future__ import annotations

import dataclasses
from typing import Any

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.timeline_io import TimelineOpts, emit_timeline


# Tweet-list modes — route through emit_timeline.
_TWEET_MODES: dict[str, str] = {
    "tweets":     "fetch_user_tweets",
    "replies":    "fetch_user_replies",
    "media":      "fetch_user_media",
    "likes":      "fetch_user_likes",
    "articles":   "fetch_user_articles",
    "highlights": "fetch_user_highlights",
}

# User-list modes — emit UserProfile list directly.
_USER_LIST_MODES: dict[str, str] = {
    "followers":  "fetch_followers",
    "following":  "fetch_following",
}


def _serialize_users(items: list[Any]) -> list[dict]:
    return [
        dataclasses.asdict(x) if dataclasses.is_dataclass(x) and not isinstance(x, type) else x
        for x in items
    ]


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def register(app: typer.Typer) -> None:
    """Register `user` as a top-level command on the given Typer app."""

    @app.command("user")
    def user_cmd(
        ctx: typer.Context,
        handle: str | None = typer.Argument(
            None,
            metavar="HANDLE",
            help="X handle (with or without leading @). Omit only with --recommended.",
        ),
        tweets:      bool = typer.Option(False, "--tweets",      help="Recent tweets"),
        replies:     bool = typer.Option(False, "--replies",     help="Posts + Replies tab"),
        media:       bool = typer.Option(False, "--media",       help="Media tab"),
        likes:       bool = typer.Option(False, "--likes",       help="Public likes"),
        articles:    bool = typer.Option(False, "--articles",    help="Articles tab"),
        highlights:  bool = typer.Option(False, "--highlights",  help="Highlights tab"),
        followers:   bool = typer.Option(False, "--followers",   help="Followers list"),
        following:   bool = typer.Option(False, "--following",   help="Following list"),
        recommended: bool = typer.Option(False, "--recommended", help='"Who to follow" recs'),
        top:         int  = typer.Option(30, "--top", metavar="N", help="Max results"),
        expand_articles: bool = typer.Option(
            False, "--expand-articles",
            help="For tweet-list modes: replace article tweets with their full body.",
        ),
    ) -> None:
        c = _ctx(ctx)

        selected = [
            name for name, on in [
                ("tweets", tweets), ("replies", replies), ("media", media),
                ("likes", likes), ("articles", articles), ("highlights", highlights),
                ("followers", followers), ("following", following),
                ("recommended", recommended),
            ] if on
        ]
        if len(selected) > 1:
            emit_error(
                "invalid_input",
                f"Modes are mutually exclusive; got: {', '.join('--' + s for s in selected)}",
                c.use_yaml,
            )
            raise typer.Exit(code=2)

        norm = handle.lstrip("@").strip() if handle else None
        if not norm and not recommended:
            emit_error(
                "invalid_input",
                "HANDLE is required (or pass --recommended for general recs).",
                c.use_yaml,
            )
            raise typer.Exit(code=2)

        try:
            client = build_client(c.profile)

            # ── general recommendations (no handle) ──
            if recommended and not norm:
                users = client.fetch_recommended_users(user_id=None, count=top)
                emit_ok(_serialize_users(users), c.use_yaml)
                return

            # ── per-handle recommended ──
            if recommended:
                user_id = client.resolve_user_id(norm)
                users = client.fetch_recommended_users(user_id=user_id, count=top)
                emit_ok(_serialize_users(users), c.use_yaml)
                return

            # ── user-list modes (followers / following) ──
            if selected and selected[0] in _USER_LIST_MODES:
                mode = selected[0]
                user_id = client.resolve_user_id(norm)
                users = getattr(client, _USER_LIST_MODES[mode])(user_id, top)
                emit_ok(_serialize_users(users), c.use_yaml)
                return

            # ── tweet-list modes — go through emit_timeline ──
            if selected and selected[0] in _TWEET_MODES:
                mode = selected[0]
                user_id = client.resolve_user_id(norm)
                method = getattr(client, _TWEET_MODES[mode])

                def fetch_page(*, count):
                    return method(user_id, count)

                emit_timeline(
                    client,
                    fetch_page,
                    TimelineOpts(top=top, expand_articles=expand_articles),
                    use_yaml=c.use_yaml,
                    profile_name=c.profile,
                )
                return

            # ── default: profile metadata ──
            profile = client.fetch_user(norm)
            emit_ok(
                dataclasses.asdict(profile) if dataclasses.is_dataclass(profile) else profile,
                c.use_yaml,
            )
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)
