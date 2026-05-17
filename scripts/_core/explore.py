"""Trend exploration helpers for x-query.

Wraps ExplorePage and GenericTimelineById GraphQL operations,
plus TrendRelevantUsers for KOL discovery.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .models import Trend, UserProfile
from .parser import _deep_get, parse_user_result

if TYPE_CHECKING:
    from .client import TwitterClient  # noqa: F401

logger = logging.getLogger(__name__)


def _parse_trend_item(item: Dict[str, Any], category: str = "") -> Optional[Trend]:
    """Parse a TimelineTrend or legacy trend item."""
    name = item.get("name") or item.get("trendName") or item.get("trend_name")
    if not name:
        return None
    trend_id = item.get("trendId") or item.get("trend_id") or item.get("id") or ""
    is_ai = bool(item.get("isAiTrend") or item.get("is_ai_trend"))
    age_text = item.get("ageText") or item.get("age_text") or ""

    # TimelineTrend puts category in trend_metadata.domain_context
    meta = item.get("trend_metadata") or {}
    resolved_category = category or meta.get("domain_context") or item.get("category") or ""

    post_count_raw = item.get("postCount") or item.get("post_count") or item.get("tweetCount") or 0
    try:
        post_count = int(post_count_raw)
    except (TypeError, ValueError):
        post_count = 0

    facepile: List[str] = []
    for face in item.get("facepileImages") or item.get("facepile_images") or []:
        if isinstance(face, dict):
            url = face.get("url") or face.get("image_url") or ""
            if url:
                facepile.append(url)
        elif isinstance(face, str):
            facepile.append(face)

    return Trend(
        name=name,
        trend_id=trend_id,
        is_ai_trend=is_ai,
        age_text=age_text,
        category=resolved_category,
        post_count=post_count,
        facepile_images=facepile,
    )


def _extract_trends_from_instructions(instructions: List[Any], category: str = "") -> List[Trend]:
    """Walk timeline instructions and extract trend items."""
    trends = []
    for instruction in instructions:
        entries = instruction.get("entries") or []
        for entry in entries:
            content = entry.get("content") or {}
            item_content = content.get("itemContent") or {}
            typename = item_content.get("__typename") or item_content.get("itemType") or ""
            if "Trend" in typename or item_content.get("name") or item_content.get("trendName"):
                t = _parse_trend_item(item_content, category)
                if t:
                    trends.append(t)
            # Module / carousel items
            for nested in content.get("items") or []:
                nc = (nested.get("item") or {}).get("itemContent") or nested.get("itemContent") or {}
                typename_n = nc.get("__typename") or nc.get("itemType") or ""
                if "Trend" in typename_n or nc.get("name") or nc.get("trendName"):
                    t = _parse_trend_item(nc, category)
                    if t:
                        trends.append(t)
    return trends


def _read_tab_ids(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Extract (slug, base64_timeline_id) pairs from an ExplorePage response.

    Returns list of (tab_slug, timeline_id) tuples ready for GenericTimelineById.
    """
    body = _deep_get(data, "data", "explore_page", "body") or {}
    timelines = body.get("timelines") or []
    result = []
    for tab in timelines:
        slug = tab.get("id") or ""
        tl = tab.get("timeline") or {}
        tl_id = tl.get("id") or ""
        if tl_id:
            result.append((slug, tl_id))
    return result


def fetch_explore_page(client: "TwitterClient") -> Dict[str, Any]:
    """Call ExplorePage and return the raw response for tab-ID extraction."""
    return client._graphql_get("ExplorePage", variables={}, features={})


def fetch_generic_timeline(client: "TwitterClient", timeline_id: str, category: str = "") -> List[Trend]:
    """Fetch a specific tab timeline via GenericTimelineById.

    Actual response path: data.timeline.timeline.instructions
    """
    data = client._graphql_get(
        "GenericTimelineById",
        variables={"timelineId": timeline_id},
        features={},
    )
    instructions = _deep_get(data, "data", "timeline", "timeline", "instructions") or []
    return _extract_trends_from_instructions(instructions, category=category or timeline_id)


def fetch_all_tabs(client: "TwitterClient") -> List[Trend]:
    """Fetch ExplorePage to discover tab IDs, then fetch each tab via GenericTimelineById.

    Deduplicates by name; tabs are fetched in order (for_you first).
    """
    all_trends: List[Trend] = []
    seen_names: set = set()

    def _add(trends: List[Trend]) -> None:
        for t in trends:
            key = t.name.lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                all_trends.append(t)

    try:
        explore_data = fetch_explore_page(client)
        tab_ids = _read_tab_ids(explore_data)
        logger.info("ExplorePage: discovered %d tabs: %s", len(tab_ids), [s for s, _ in tab_ids])
    except Exception as exc:
        logger.warning("ExplorePage failed: %s", exc)
        tab_ids = []

    for slug, tl_id in tab_ids:
        try:
            tab_trends = fetch_generic_timeline(client, tl_id, category=slug)
            _add(tab_trends)
            logger.info("Tab %s (%s): %d trends", slug, tl_id[:20], len(tab_trends))
        except Exception as exc:
            logger.warning("Tab %s failed: %s", slug, exc)

    return all_trends


def fetch_trend_kols(client: "TwitterClient", trend_id: str) -> List[UserProfile]:
    """Fetch KOLs relevant to a trend via TrendRelevantUsers."""
    data = client._graphql_get(
        "TrendRelevantUsers",
        variables={"trendId": trend_id},
        features={},
    )
    instructions = (
        _deep_get(data, "data", "ai_trend_by_rest_id", "result", "trend_relevant_users", "timeline", "instructions")
        or []
    )
    users = []
    for instruction in instructions:
        for entry in instruction.get("entries") or []:
            content = entry.get("content") or {}
            item_content = content.get("itemContent") or {}
            user_result = _deep_get(item_content, "user_results", "result")
            if user_result:
                user = parse_user_result(user_result)
                if user:
                    users.append(user)
            for nested in content.get("items") or []:
                nc = (nested.get("item") or {}).get("itemContent") or nested.get("itemContent") or {}
                ur = _deep_get(nc, "user_results", "result")
                if ur:
                    user = parse_user_result(ur)
                    if user:
                        users.append(user)
    return users
