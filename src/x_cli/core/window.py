"""Adaptive time-window search for x-cli.

X's GraphQL search returns at most ~100-200 tweets per query. For long time
ranges on hot topics, results get silently truncated. This module recursively
splits the time window in half until each sub-window's result count drops
below a saturation threshold, then dedups by tweet ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

from .models import Tweet

logger = logging.getLogger(__name__)

SPLIT_RATIO = 0.85          # if len(results) >= ratio * top, the window is likely saturated
MAX_DEPTH = 6               # cap recursion (worst case: 64 sub-windows)
MIN_WINDOW_SECONDS = 6 * 3600  # don't split below 6 hours


def _parse_date(s: str) -> datetime:
    """Parse YYYY-MM-DD as UTC midnight, or YYYY-MM-DD HH:MM:SS as UTC."""
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d_%H:%M:%S_UTC", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError("Unrecognized date format: %r (use YYYY-MM-DD)" % s)


def _format_date(dt: datetime) -> str:
    """Format a UTC datetime as the X-search 'since:' / 'until:' literal."""
    # X accepts YYYY-MM-DD_HH:MM:SS_UTC, but YYYY-MM-DD is enough for whole-day windows.
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d_%H:%M:%S_UTC")


def adaptive_search(
    base_query: str,
    since: str,
    until: str,
    top: int,
    fetcher: Callable[[str, int], List[Tweet]],
    *,
    split_ratio: float = SPLIT_RATIO,
    max_depth: int = MAX_DEPTH,
    min_window_seconds: int = MIN_WINDOW_SECONDS,
) -> List[Tweet]:
    """Recursively split [since, until] until each sub-query is unsaturated.

    Args:
        base_query: search string without `since:` / `until:` operators.
        since: ISO date string (YYYY-MM-DD).
        until: ISO date string (YYYY-MM-DD), exclusive upper bound on X.
        top: target per-window result cap.
        fetcher: callable taking (query, top) and returning list of Tweet.

    Returns:
        Deduplicated list of tweets (by Tweet.id).
    """
    since_dt = _parse_date(since)
    until_dt = _parse_date(until)
    if until_dt <= since_dt:
        raise ValueError("--until must be after --since: %s vs %s" % (since, until))

    seen_ids = set()  # type: set
    out = []  # type: List[Tweet]

    def _add_unique(tweets: List[Tweet]) -> int:
        added = 0
        for t in tweets:
            if t.id and t.id not in seen_ids:
                seen_ids.add(t.id)
                out.append(t)
                added += 1
        return added

    def _recurse(s_dt: datetime, u_dt: datetime, depth: int) -> None:
        window = u_dt - s_dt
        q = "%s since:%s until:%s" % (base_query, _format_date(s_dt), _format_date(u_dt))
        logger.info(
            "[adaptive depth=%d] %s → %s (%s)",
            depth, _format_date(s_dt), _format_date(u_dt), window,
        )
        try:
            results = fetcher(q, top)
        except Exception as exc:
            logger.warning("[adaptive depth=%d] fetch failed: %s — skipping window", depth, exc)
            return

        added = _add_unique(results)
        saturation = len(results) / float(top) if top > 0 else 0.0
        logger.info(
            "[adaptive depth=%d] got %d (added %d new), saturation=%.2f",
            depth, len(results), added, saturation,
        )

        # Split if saturated and we haven't bottomed out
        if (
            saturation >= split_ratio
            and depth < max_depth
            and window.total_seconds() >= 2 * min_window_seconds
        ):
            mid_dt = s_dt + window / 2
            logger.info("[adaptive depth=%d] splitting at %s", depth, _format_date(mid_dt))
            _recurse(s_dt, mid_dt, depth + 1)
            _recurse(mid_dt, u_dt, depth + 1)

    _recurse(since_dt, until_dt, 0)
    logger.info("[adaptive] total unique tweets: %d", len(out))
    return out


def derive_since_until(since: Optional[str], until: Optional[str], default_lookback_days: int = 90) -> Tuple[str, str]:
    """Fill in missing --since / --until with defaults.

    If neither set: last `default_lookback_days` days.
    If only --since: until = today.
    If only --until: since = until - default_lookback_days.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not since and not until:
        s_dt = datetime.now(timezone.utc) - timedelta(days=default_lookback_days)
        return s_dt.strftime("%Y-%m-%d"), today
    if since and not until:
        return since, today
    if until and not since:
        u_dt = _parse_date(until)
        s_dt = u_dt - timedelta(days=default_lookback_days)
        return s_dt.strftime("%Y-%m-%d"), until
    return since, until  # type: ignore
