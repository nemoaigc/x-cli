"""Advanced search query builder for x-query.

Composes Twitter search operators into a raw query string for the
SearchTimeline GraphQL endpoint.

Reference: https://help.x.com/en/using-x/x-advanced-search
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Sequence

from .exceptions import InvalidInputError

_LANG_PATTERN = re.compile(r"^[A-Za-z][A-Za-z-]{1,14}$")


def _normalize_handle(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().lstrip("@")
    return text or None


def _normalize_lang(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if not _LANG_PATTERN.match(text):
        raise ValueError("--lang must be an ISO language code like en or zh-cn")
    return text


def _normalize_date(flag_name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("%s must be in YYYY-MM-DD format" % flag_name) from exc
    return text


def build_search_query(
    query: str = "",
    *,
    from_user: Optional[str] = None,
    to_user: Optional[str] = None,
    lang: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    has: Optional[Sequence[str]] = None,
    exclude: Optional[Sequence[str]] = None,
    min_likes: Optional[int] = None,
    min_retweets: Optional[int] = None,
) -> str:
    """Build an advanced search query string."""
    parts: List[str] = []
    query_text = query.strip()
    from_user = _normalize_handle(from_user)
    to_user = _normalize_handle(to_user)
    lang = _normalize_lang(lang)
    since = _normalize_date("--since", since)
    until = _normalize_date("--until", until)

    if min_likes is not None and min_likes < 0:
        raise ValueError("--min-likes must be greater than or equal to 0")
    if min_retweets is not None and min_retweets < 0:
        raise ValueError("--min-retweets must be greater than or equal to 0")
    if since and until and since > until:
        raise ValueError("--since must be on or before --until")

    if query_text:
        parts.append(query_text)
    if from_user:
        parts.append("from:%s" % from_user)
    if to_user:
        parts.append("to:%s" % to_user)
    if lang:
        parts.append("lang:%s" % lang)
    if since:
        parts.append("since:%s" % since)
    if until:
        parts.append("until:%s" % until)
    if has:
        for item in has:
            parts.append("filter:%s" % item.lower())
    if exclude:
        for item in exclude:
            item = item.lower()
            if item == "retweets":
                parts.append("-filter:retweets")
            elif item == "replies":
                parts.append("-filter:replies")
            elif item == "links":
                parts.append("-filter:links")
            else:
                parts.append("-filter:%s" % item)
    if min_likes is not None:
        parts.append("min_faves:%d" % min_likes)
    if min_retweets is not None:
        parts.append("min_retweets:%d" % min_retweets)

    return " ".join(parts)


def _normalize_tweet_id(value: str) -> str:
    """Extract tweet ID from a URL or return the raw value."""
    value = value.strip()
    # Handle URLs like https://x.com/user/status/1234567890
    if "status/" in value:
        value = value.split("status/")[-1].split("?")[0].split("/")[0].strip()
    if not re.fullmatch(r"\d+", value):
        raise InvalidInputError("Tweet ID must be numeric: %r" % value)
    return value
