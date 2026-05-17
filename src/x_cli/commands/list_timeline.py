"""`x-cli list LIST_ID` — X List timeline.

Module is named `list_timeline` (not `list`) to avoid shadowing the builtin.
The typer command itself is registered as `list`.

Single-page fetch; mix-gate flags (--min-articles / --min-posts / etc.)
are **not** wired here — legacy `scripts/read.py --list ID` was also
single-page (only `--feed` ran the mix loop), and `TwitterClient.fetch_list_timeline`
does not currently expose a cursor parameter. Don't add these flags
without first extending the underlying GraphQL pagination.
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
    ) -> None:
        """Read an X List timeline (single page; see module docstring)."""
        c = _ctx(ctx)
        opts = TimelineOpts(top=top, expand_articles=expand_articles)

        try:
            client = build_client(c.profile)

            def fetch_page(*, count):
                return client.fetch_list_timeline(list_id, count=count)

            emit_timeline(client, fetch_page, opts,
                          use_yaml=c.use_yaml, profile_name=c.profile)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)
