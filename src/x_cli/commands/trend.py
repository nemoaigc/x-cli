"""`x-cli trend …` — scan Explore tabs + drill into trends.

Subcommands:
  scan [--drill-top N --top N]    Scan all Explore tabs; optionally
                                  auto-drill top N trends
  drill TREND_ID_OR_NAME [--top]  Fetch KOLs + search discussion for a trend
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.explore import fetch_all_tabs, fetch_trend_kols
from x_cli.core.models import Trend
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.core.search import build_search_query


logger = logging.getLogger(__name__)

trend_app = typer.Typer(
    name="trend",
    help="Scan Explore trends and drill into them.",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _score_trend(t: Trend) -> int:
    """AI trends + high post counts score higher."""
    return t.post_count * (2 if t.is_ai_trend else 1)


@trend_app.command("scan")
def scan_cmd(
    ctx: typer.Context,
    drill_top: int | None = typer.Option(
        None, "--drill-top", "--scan-drill-top", metavar="N",
        help="After scanning, auto-drill top N trends. `--scan-drill-top` is "
             "the legacy alias preserved from scripts/digest.py.",
    ),
    top: int = typer.Option(
        20, "--top", metavar="N",
        help="Max search results per drilled trend (only with --drill-top).",
    ),
) -> None:
    """Scan all Explore tabs; output sorted trends. With --drill-top, also drills."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        trends = fetch_all_tabs(client)
        trends.sort(key=_score_trend, reverse=True)

        if drill_top is None:
            emit_ok([dataclasses.asdict(t) for t in trends], c.use_yaml)
            return

        if drill_top <= 0:
            emit_error("invalid_input", "--drill-top must be greater than 0", c.use_yaml)
            raise typer.Exit(code=2)

        top_trends = trends[:drill_top]
        drilled: list[dict] = []
        for t in top_trends:
            if not t.trend_id and not t.name:
                continue
            try:
                drilled.append(_drill(client, t.trend_id or t.name, max_search=top, trend=t))
            except Exception as exc:
                drilled.append({"trend_id": t.trend_id, "error": str(exc)})

        emit_ok(
            {
                "trends": [dataclasses.asdict(t) for t in trends],
                "drilled": drilled,
            },
            c.use_yaml,
        )
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@trend_app.command("drill")
def drill_cmd(
    ctx: typer.Context,
    trend_ref: str = typer.Argument(..., metavar="TREND_ID_OR_NAME"),
    top: int = typer.Option(
        20, "--top", metavar="N",
        help="Max search results.",
    ),
) -> None:
    """Drill into a single trend: KOLs + search discussion."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        result = _drill(client, trend_ref.strip(), max_search=top)
        emit_ok(result, c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


# ───────────────────────── internals ──────────────────────────────────


def _resolve_trend(client: Any, trend_ref: str) -> Trend:
    if trend_ref.isdigit():
        for t in fetch_all_tabs(client):
            if t.trend_id == trend_ref:
                return t
        raise InvalidInputError(
            f"Trend ID {trend_ref} was not found in the current Explore scan. "
            "Run `trend scan` or pass the trend name directly.",
        )

    normalized = trend_ref.lower()
    try:
        for t in fetch_all_tabs(client):
            if t.name.strip().lower() == normalized:
                return t
    except Exception as exc:
        logger.debug("Unable to resolve trend %r via Explore tabs: %s", trend_ref, exc)
    logger.warning(
        "Trend %r not found in current Explore scan; KOLs will be unavailable.",
        trend_ref,
    )
    return Trend(name=trend_ref)


def _drill(client: Any, trend_ref: str, *, max_search: int = 20,
           trend: Trend | None = None) -> dict[str, Any]:
    resolved = trend or _resolve_trend(client, trend_ref)
    trend_id = resolved.trend_id
    trend_name = resolved.name

    try:
        kols = fetch_trend_kols(client, trend_id) if trend_id else []
    except Exception as exc:
        logger.warning(
            "TrendRelevantUsers failed for %r: %s — skipping KOLs",
            trend_id or trend_name, exc,
        )
        kols = []

    tweets = client.fetch_search(build_search_query(trend_name), count=max_search)

    return {
        "trend_id": trend_id,
        "trend_name": trend_name,
        "kols": [dataclasses.asdict(u) for u in kols],
        "tweets": [dataclasses.asdict(t) for t in tweets],
    }
