#!/usr/bin/env python3
"""digest.py — trend mode entry point for x-query.

Scans X Explore and drills into trends.

Usage:
  uv run scripts/digest.py --scan
  uv run scripts/digest.py --drill <trendId>
  uv run scripts/digest.py --scan-drill-top 3
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
from scripts._core.models import Trend
from scripts._core.explore import fetch_all_tabs, fetch_trend_kols
from scripts._core.exceptions import InvalidInputError, XQueryError

logger = logging.getLogger(__name__)


def _score_trend(t):
    """Compute a sort score. AI trends and high post counts rank higher."""
    return t.post_count * (2 if t.is_ai_trend else 1)


def main():
    parser = argparse.ArgumentParser(
        description="x-query digest mode — scan X Explore trends and drill into them",
    )
    add_common_args(parser)

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true", help="Scan all Explore tabs for trends")
    mode.add_argument("--drill", metavar="TREND_ID", help="Drill into a trend by trendId")
    mode.add_argument("--scan-drill-top", type=int, metavar="N",
                      help="Scan and auto-drill top N trends")

    parser.add_argument("--top", type=int, default=20, metavar="N",
                        help="Max search results per drilled trend (default: 20)")

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        require_positive_int("--top", args.top)
        if args.scan_drill_top is not None:
            require_positive_int("--scan-drill-top", args.scan_drill_top)
        if args.drill is not None:
            args.drill = normalize_required_text("--drill", args.drill)
        client = build_client(args.profile)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("startup_error", str(exc), args.yaml)
        sys.exit(1)

    try:
        if args.scan:
            trends = fetch_all_tabs(client)
            trends.sort(key=_score_trend, reverse=True)
            emit_ok([dataclasses.asdict(t) for t in trends], args.yaml)

        elif args.drill:
            result = _drill(client, args.drill, max_search=args.top)
            emit_ok(result, args.yaml)

        elif args.scan_drill_top is not None:
            trends = fetch_all_tabs(client)
            trends.sort(key=_score_trend, reverse=True)
            top_trends = trends[:args.scan_drill_top]
            drilled = []
            for t in top_trends:
                if not t.trend_id and not t.name:
                    continue
                try:
                    drilled.append(_drill(client, t.trend_id or t.name, max_search=args.top, trend=t))
                except Exception as exc:
                    drilled.append({"trend_id": t.trend_id, "error": str(exc)})
            emit_ok({
                "trends": [dataclasses.asdict(t) for t in trends],
                "drilled": drilled,
            }, args.yaml)

    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("unexpected_error", str(exc), args.yaml)
        sys.exit(1)


def _resolve_trend(client, trend_ref: str) -> Trend:
    trend_ref = trend_ref.strip()
    if trend_ref.isdigit():
        for trend in fetch_all_tabs(client):
            if trend.trend_id == trend_ref:
                return trend
        raise InvalidInputError(
            "Trend ID %s was not found in the current Explore scan. Run --scan or pass the trend name directly."
            % trend_ref
        )

    normalized = trend_ref.lower()
    try:
        for trend in fetch_all_tabs(client):
            if trend.name.strip().lower() == normalized:
                return trend
    except Exception as exc:
        logger.debug("Unable to resolve trend name %r against Explore tabs: %s", trend_ref, exc)
    logger.warning(
        "Trend %r not found in current Explore scan; KOLs will be unavailable. "
        "Search results are still returned.", trend_ref,
    )
    return Trend(name=trend_ref)


def _drill(client, trend_ref: str, max_search: int = 20, trend: Trend | None = None) -> dict:
    """Drill into a trend: fetch KOLs + search discussion."""
    import dataclasses
    from scripts._core.search import build_search_query

    resolved = trend or _resolve_trend(client, trend_ref)
    trend_id = resolved.trend_id
    trend_name = resolved.name

    try:
        kols = fetch_trend_kols(client, trend_id) if trend_id else []
    except Exception as exc:
        logger.warning("TrendRelevantUsers failed for %r: %s — skipping KOLs", trend_id or trend_name, exc)
        kols = []

    search_q = build_search_query(trend_name)
    tweets = client.fetch_search(search_q, count=max_search)

    return {
        "trend_id": trend_id,
        "trend_name": trend_name,
        "kols": [dataclasses.asdict(u) for u in kols],
        "tweets": [dataclasses.asdict(t) for t in tweets],
    }


if __name__ == "__main__":
    main()
