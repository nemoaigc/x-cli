"""`x-cli list LIST_ID` — X List timeline.

Module is named `list_timeline` (not `list`) to avoid shadowing the builtin.
The typer command itself is registered as `list`.
"""
from __future__ import annotations

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import XQueryError
from x_cli.core.output import build_client, emit_error
from x_cli.timeline_io import TimelineOpts, emit_timeline


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_cmd(
        ctx: typer.Context,
        list_id: str = typer.Argument(..., metavar="LIST_ID"),
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
        """Read an X List timeline."""
        c = _ctx(ctx)
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

        try:
            client = build_client(c.profile)

            def fetch_page(count, cursor=None, return_cursor=False):
                return client.fetch_list_timeline(
                    list_id, count=count, cursor=cursor, return_cursor=return_cursor,
                )

            # Simple path bypasses cursor signature; mix-gate path uses it.
            if not opts.has_mix_gates:
                # Match the legacy `count=N` call shape so tests can grep it.
                def _simple_fetch(*, count):
                    return client.fetch_list_timeline(list_id, count=count)
                emit_timeline(client, _simple_fetch, opts,
                              use_yaml=c.use_yaml, profile_name=c.profile)
            else:
                emit_timeline(client, fetch_page, opts,
                              use_yaml=c.use_yaml, profile_name=c.profile)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)
