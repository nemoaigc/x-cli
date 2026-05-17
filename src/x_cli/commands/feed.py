"""`x-cli feed NAME` — read a home / pinned timeline feed.

`NAME` values:
  list             → list all pinned (custom) timelines
  for-you          → home (For You)
  following        → following feed
  <tab_label>      → custom pinned timeline (case-insensitive match)
"""
from __future__ import annotations

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.timeline_io import TimelineOpts, emit_timeline


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def register(app: typer.Typer) -> None:
    @app.command("feed")
    def feed_cmd(
        ctx: typer.Context,
        name: str = typer.Argument(..., metavar="NAME",
                                    help='Feed: "list" / "for-you" / "following" / pinned-label.'),
        top: int = typer.Option(30, "--top", metavar="N"),
        expand_articles: bool = typer.Option(False, "--expand-articles"),
        min_articles: int = typer.Option(0, "--min-articles", metavar="N"),
        min_posts:    int = typer.Option(0, "--min-posts",    metavar="N"),
        max_pages:    int = typer.Option(5, "--max-pages",    metavar="N"),
        min_article_likes:     int | None = typer.Option(None, "--min-article-likes",     metavar="N"),
        min_article_retweets:  int | None = typer.Option(None, "--min-article-retweets",  metavar="N"),
        min_article_bookmarks: int | None = typer.Option(None, "--min-article-bookmarks", metavar="N"),
        min_post_likes:        int | None = typer.Option(None, "--min-post-likes",        metavar="N"),
        min_post_retweets:     int | None = typer.Option(None, "--min-post-retweets",     metavar="N"),
        min_post_bookmarks:    int | None = typer.Option(None, "--min-post-bookmarks",    metavar="N"),
    ) -> None:
        c = _ctx(ctx)
        try:
            client = build_client(c.profile)

            # Special: `feed list` → enumerate pinned timelines.
            if name.lower() == "list":
                emit_ok(client.fetch_pinned_timelines(), c.use_yaml)
                return

            fetch_page = _resolve_feed(client, name, c.use_yaml)
            if fetch_page is None:
                raise typer.Exit(code=1)

            opts = TimelineOpts(
                top=top, expand_articles=expand_articles,
                min_articles=min_articles, min_posts=min_posts, max_pages=max_pages,
                article_likes=min_article_likes,
                article_retweets=min_article_retweets,
                article_bookmarks=min_article_bookmarks,
                post_likes=min_post_likes,
                post_retweets=min_post_retweets,
                post_bookmarks=min_post_bookmarks,
            )
            emit_timeline(client, fetch_page, opts,
                          use_yaml=c.use_yaml, profile_name=c.profile)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)


def _resolve_feed(client, name: str, use_yaml: bool):
    lower = name.lower()
    if lower == "for-you":
        return client.fetch_home_timeline
    if lower == "following":
        return client.fetch_following_feed

    pinned = client.fetch_pinned_timelines()
    match = next(
        (p for p in pinned if p.get("tab_label", "").lower() == lower
         or p.get("name", "").lower() == lower),
        None,
    )
    if match is None:
        available = ", ".join(f'"{p["tab_label"]}"' for p in pinned) or "(none)"
        emit_error(
            "unknown_feed",
            f'Unknown feed "{name}". Available custom timelines: {available}',
            use_yaml,
        )
        return None

    def fetch_page(count, cursor=None, return_cursor=False):
        return client.fetch_custom_timeline(
            match["tag"], count=count, cursor=cursor, return_cursor=return_cursor,
        )
    return fetch_page
