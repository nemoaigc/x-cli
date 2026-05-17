"""`x-cli engage …` — engagement writes (like / retweet / bookmark).

These execute immediately — no --dry-run/--yes gate (preserved from
the legacy `scripts/me.py` design: "low-risk reactions").
"""
from __future__ import annotations

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.core.search import _normalize_tweet_id


engage_app = typer.Typer(
    name="engage",
    help="Engagement writes (like / retweet / bookmark).",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _run(ctx: typer.Context, action, tweet: str, **kwargs) -> None:
    """Common: normalize ID → call action(client, tid, **kwargs) → emit envelope."""
    c = _ctx(ctx)
    try:
        tid = _normalize_tweet_id(tweet)
        client = build_client(c.profile)
        action(client, tid, **kwargs)
        emit_ok({"success": True, "tweet_id": tid}, c.use_yaml)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), c.use_yaml)
        raise typer.Exit(code=2)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@engage_app.command("like")
def like_cmd(ctx: typer.Context, tweet: str = typer.Argument(..., metavar="ID_OR_URL")) -> None:
    """Like a tweet."""
    _run(ctx, lambda c, tid: c.like_tweet(tid), tweet)


@engage_app.command("unlike")
def unlike_cmd(ctx: typer.Context, tweet: str = typer.Argument(..., metavar="ID_OR_URL")) -> None:
    """Un-like a tweet."""
    _run(ctx, lambda c, tid: c.unlike_tweet(tid), tweet)


@engage_app.command("retweet")
def retweet_cmd(ctx: typer.Context, tweet: str = typer.Argument(..., metavar="ID_OR_URL")) -> None:
    """Retweet."""
    _run(ctx, lambda c, tid: c.retweet(tid), tweet)


@engage_app.command("unretweet")
def unretweet_cmd(ctx: typer.Context, tweet: str = typer.Argument(..., metavar="ID_OR_URL")) -> None:
    """Un-retweet."""
    _run(ctx, lambda c, tid: c.unretweet(tid), tweet)


@engage_app.command("bookmark")
def bookmark_cmd(
    ctx: typer.Context,
    tweet: str = typer.Argument(..., metavar="ID_OR_URL"),
    folder: str | None = typer.Option(None, "--folder", metavar="FOLDER_ID"),
) -> None:
    """Bookmark a tweet (optionally to a folder)."""
    _run(ctx, lambda c, tid: c.bookmark_tweet(tid, folder_id=folder), tweet)


@engage_app.command("unbookmark")
def unbookmark_cmd(ctx: typer.Context, tweet: str = typer.Argument(..., metavar="ID_OR_URL")) -> None:
    """Remove a bookmark."""
    _run(ctx, lambda c, tid: c.unbookmark_tweet(tid), tweet)
