"""Time formatting utilities for x-query.

Converts Twitter API timestamps (e.g. "Sat Mar 08 12:00:00 +0000 2026")
into human-friendly local time and relative time strings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_TWITTER_TIME_FORMAT = "%a %b %d %H:%M:%S %z %Y"


def _parse_twitter_time(created_at: str) -> Optional[datetime]:
    if not created_at:
        return None
    try:
        return datetime.strptime(created_at, _TWITTER_TIME_FORMAT)
    except (ValueError, TypeError):
        logger.debug("Failed to parse Twitter timestamp: %s", created_at)
        return None


def format_local_time(created_at: str) -> str:
    dt = _parse_twitter_time(created_at)
    if dt is None:
        return created_at
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def format_relative_time(created_at: str) -> str:
    dt = _parse_twitter_time(created_at)
    if dt is None:
        return created_at
    now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "%ds ago" % seconds
    minutes = seconds // 60
    if minutes < 60:
        return "%dm ago" % minutes
    hours = minutes // 60
    if hours < 24:
        return "%dh ago" % hours
    days = hours // 24
    if days < 30:
        return "%dd ago" % days
    months = days // 30
    if months < 12:
        return "%dmo ago" % months
    years = days // 365
    return "%dy ago" % years


def format_iso8601(created_at: str) -> str:
    dt = _parse_twitter_time(created_at)
    if dt is None:
        return created_at
    return dt.isoformat()
