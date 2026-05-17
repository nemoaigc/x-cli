"""`x-cli search …` — advanced tweet search and people search.

Two flat top-level commands (typer doesn't cleanly support a positional
arg on a callback that also has subcommands — using `search-users` as a
sibling instead of `search users` subcommand keeps the parser unambiguous):

  x-cli search QUERY [filters]   Advanced tweet search (Top / Latest)
  x-cli search-users QUERY       People-tab search
"""
from __future__ import annotations

import dataclasses
from enum import Enum

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.core.search import build_search_query


class Product(str, Enum):
    top = "Top"
    latest = "Latest"


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _serialize(items):
    return [
        dataclasses.asdict(x) if dataclasses.is_dataclass(x) and not isinstance(x, type) else x
        for x in items
    ]


def register(app: typer.Typer) -> None:
    """Register `search` + `search-users` as top-level commands."""

    @app.command("search")
    def search_cmd(
        ctx: typer.Context,
        query: str = typer.Argument(..., metavar="QUERY",
                                    help="Search query (advanced operators supported)."),
        since: str | None = typer.Option(None, "--since", metavar="YYYY-MM-DD"),
        until: str | None = typer.Option(None, "--until", metavar="YYYY-MM-DD"),
        lang:  str | None = typer.Option(None, "--lang",  metavar="CODE"),
        from_user: str | None = typer.Option(None, "--from-user", metavar="HANDLE"),
        min_likes:    int | None = typer.Option(None, "--min-likes",    metavar="N"),
        min_retweets: int | None = typer.Option(None, "--min-retweets", metavar="N"),
        product: Product = typer.Option(Product.top, "--product", help="Top or Latest"),
        top: int = typer.Option(30, "--top", metavar="N"),
    ) -> None:
        """Advanced tweet search."""
        c = _ctx(ctx)
        try:
            query_str = build_search_query(
                query,
                from_user=from_user,
                lang=lang,
                since=since,
                until=until,
                min_likes=min_likes,
                min_retweets=min_retweets,
            )
            client = build_client(c.profile)
            results = client.fetch_search(query_str, top, product.value)
            emit_ok(_serialize(results), c.use_yaml)
        except (ValueError, InvalidInputError) as exc:
            emit_error("invalid_input", str(exc), c.use_yaml)
            raise typer.Exit(code=2)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)

    @app.command("search-users")
    def search_users_cmd(
        ctx: typer.Context,
        query: str = typer.Argument(..., metavar="QUERY"),
        top: int = typer.Option(30, "--top", metavar="N"),
    ) -> None:
        """Search the People tab."""
        c = _ctx(ctx)
        try:
            client = build_client(c.profile)
            results = client.search_users(query, top)
            emit_ok(_serialize(results), c.use_yaml)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)
