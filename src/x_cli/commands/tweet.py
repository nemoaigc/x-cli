"""`x-cli tweet …` — fetch single / article / batch tweets."""
from __future__ import annotations

import dataclasses
from typing import Any

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.core.search import _normalize_tweet_id


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _serialize(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    return obj


def register(app: typer.Typer) -> None:
    @app.command("tweet")
    def tweet_cmd(
        ctx: typer.Context,
        id_or_url: str = typer.Argument(..., metavar="ID_OR_URL",
                                        help="Tweet ID or status URL."),
        top: int = typer.Option(20, "--top", metavar="N",
                                help="Max replies/thread items to include."),
    ) -> None:
        """Fetch a single tweet + its thread."""
        c = _ctx(ctx)
        try:
            tid = _normalize_tweet_id(id_or_url)
            client = build_client(c.profile)
            results = client.fetch_tweet_detail(tid, top)
            emit_ok(_serialize(results), c.use_yaml)
        except (ValueError, InvalidInputError) as exc:
            emit_error("invalid_input", str(exc), c.use_yaml)
            raise typer.Exit(code=2)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)

    @app.command("tweet-article")
    def tweet_article_cmd(
        ctx: typer.Context,
        id_or_url: str = typer.Argument(..., metavar="ID_OR_URL"),
    ) -> None:
        """Fetch a Twitter Article by tweet ID / URL."""
        c = _ctx(ctx)
        try:
            tid = _normalize_tweet_id(id_or_url)
            client = build_client(c.profile)
            results = client.fetch_article(tid)
            emit_ok(_serialize(results), c.use_yaml)
        except (ValueError, InvalidInputError) as exc:
            emit_error("invalid_input", str(exc), c.use_yaml)
            raise typer.Exit(code=2)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)

    @app.command("tweet-batch")
    def tweet_batch_cmd(
        ctx: typer.Context,
        ids: list[str] = typer.Argument(..., metavar="ID...",
                                        help="One or more tweet IDs / URLs."),
    ) -> None:
        """Batch-fetch multiple tweets."""
        c = _ctx(ctx)
        try:
            normalized = [_normalize_tweet_id(x) for x in ids]
            client = build_client(c.profile)
            results = client.fetch_tweets_by_ids(normalized)
            emit_ok(_serialize(results), c.use_yaml)
        except (ValueError, InvalidInputError) as exc:
            emit_error("invalid_input", str(exc), c.use_yaml)
            raise typer.Exit(code=2)
        except XQueryError as exc:
            emit_error(exc.error_code, str(exc), c.use_yaml)
            raise typer.Exit(code=1)
