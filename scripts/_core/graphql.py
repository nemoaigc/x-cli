"""GraphQL infrastructure for x-query.

Handles queryId resolution, URL building, JS bundle scanning,
and feature flag management.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Optional  # noqa: F401

from .exceptions import QueryIdError

logger = logging.getLogger(__name__)

TWITTER_OPENAPI_URL = (
    "https://raw.githubusercontent.com/fa0311/"
    "twitter-openapi/refs/heads/main/src/config/placeholder.json"
)

# Read-only queryIds + engagement-write queryIds (no content-creation or social-graph)
FALLBACK_QUERY_IDS = {
    "HomeTimeline": "Yf4WJo0fW46TnqrHUw_1Ow",
    "HomeLatestTimeline": "BKB7oi212Fi7kQtCBGE4zA",
    "UserByScreenName": "1VOOyvKkiI3FMmkeDNxM9A",
    "UserTweets": "q6xj5bs0hapm9309hexA_g",
    "UserArticlesTweets": "b6vrYvHHxBdaq5hzyq2zDw",
    "UserMedia": "Uqb0z_IFBrxmPUhQ7pz6GQ",
    "UserTweetsAndReplies": "J1_6xm8Paoy-0DOlAEEAfg",
    "UserHighlightsTweets": "TU9RCRxFltsXUxA-9n1f0w",
    "TweetDetail": "xd_EMdYvB9hfZsZ6Idri0w",
    "Likes": "lIDpu_NWL7_VhimGGt0o6A",
    "SearchTimeline": "VhUd6vHVmLBcw0uX-6jMLA",
    "Bookmarks": "2neUNDqrrFzbLui8yallcQ",
    "ListLatestTweetsTimeline": "RlZzktZY_9wJynoepm8ZsA",
    "Followers": "IOh4aS6UdGWGJUYTqliQ7Q",
    "Following": "zx6e-TLzRkeDO_a7p4b3JQ",
    # Engagement writes
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A",
    "UnfavoriteTweet": "ZYKSe-w7KEslx3JhSIk5LA",
    "CreateRetweet": "mbRO74GrOvSfRcJnlMapnQ",
    "DeleteRetweet": "ZyZigVsNiFO6v1dEks1eWg",
    "CreateBookmark": "aoDbu3RHznuiSkQ9aNM67Q",
    "DeleteBookmark": "Wlmlj2-xzyS1GN3a6cj-mQ",
    # Content creation / deletion (write mode)
    "CreateTweet": "c50A_puUoQGK_4SXseYz3A",
    "DeleteTweet": "nxpZCY2K-I6QoFHAHeojFQ",
    "CreateNoteTweet": "af8H4woJ-v1hWD4HwrDJbw",
    # Pin / moderate / hide replies (v1.1)
    "PinTweet": "VIHsNu89pK-kW35JpHq7Xw",
    "UnpinTweet": "BhKei844ypCyLYCg0nwigw",
    "ModerateTweet": "pjFnHGVqCjTcZol0xcBJjw",
    "UnmoderateTweet": "pVSyu6PA57TLvIE4nN2tsA",
    # Single-tweet lookups
    "TweetResultByRestId": "7xflPyRiUxGVbJd4uWmbfg",
    "TweetResultsByRestIds": "i_WLNEi4e2JidkqGBR3ZIw",
    # Bookmark folders
    "BookmarkFoldersSlice": "i78YDd0Tza-dV4SYs58kRg",
    "BookmarkFolderTimeline": "hNY7X2xE2N7HVF6Qb_mu6w",
    # Explore / trend discovery
    "ExplorePage": "Zl-E3GE1UplQV-gLArsNCw",
    "GenericTimelineById": "23uIIth19xjoWPrqcRtlig",
    "TrendRelevantUsers": "2fBdtS8def6wxCDM3xAXXw",
    # Recommended users (Connect tab)
    "ConnectTabTimeline": "lq02A-gEzbLefqTgD_PFzQ",
    # Custom (pinned) timelines
    "PinnedTimelines": "SnNm4YWv4Xu26VSx-MIYlw",
}

_DEFAULT_FEATURES = {
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_media_download_video_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "responsive_web_enhance_cards_enabled": False,
}

FEATURES = dict(_DEFAULT_FEATURES)

_cached_query_ids: Dict[str, str] = {}
_bundles_scanned = False


def _build_graphql_url(query_id, operation_name, variables, features, field_toggles=None):
    # type: (str, str, Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]) -> str
    url = "https://x.com/i/api/graphql/%s/%s?variables=%s&features=%s" % (
        query_id,
        operation_name,
        urllib.parse.quote(json.dumps(variables, separators=(",", ":"))),
        urllib.parse.quote(json.dumps(features, separators=(",", ":"))),
    )
    if field_toggles:
        url += "&fieldToggles=%s" % urllib.parse.quote(
            json.dumps(field_toggles, separators=(",", ":"))
        )
    return url


_BUNDLE_SCAN_BUDGET_SECONDS = 30.0


def _scan_bundles(url_fetch_fn):
    # type: (Any) -> None
    global _bundles_scanned
    if _bundles_scanned:
        return
    _bundles_scanned = True

    import time
    deadline = time.monotonic() + _BUNDLE_SCAN_BUDGET_SECONDS

    try:
        from .constants import get_user_agent
        html = url_fetch_fn("https://x.com", {"user-agent": get_user_agent()})
        script_pattern = re.compile(
            r'(?:src|href)=["\']'
            r'(https://abs\.twimg\.com/responsive-web/client-web[^"\']+'
            r'\.js)'
            r'["\']'
        )
        script_urls = script_pattern.findall(html)
    except Exception as exc:
        logger.warning("Failed to scan JS bundles: %s", exc)
        return

    op_pattern = re.compile(
        r'queryId:\s*"([A-Za-z0-9_-]+)"[^}]{0,200}'
        r'operationName:\s*"([^"]+)"'
    )
    scanned = 0
    for script_url in script_urls:
        if time.monotonic() >= deadline:
            logger.warning(
                "Bundle scan budget (%.0fs) exhausted after %d/%d bundles",
                _BUNDLE_SCAN_BUDGET_SECONDS, scanned, len(script_urls),
            )
            break
        try:
            bundle = url_fetch_fn(script_url)
            for match in op_pattern.finditer(bundle):
                query_id, operation_name = match.group(1), match.group(2)
                _cached_query_ids.setdefault(operation_name, query_id)
            scanned += 1
        except Exception:
            continue

    logger.info("Scanned %d/%d JS bundles, cached %d query IDs",
                scanned, len(script_urls), len(_cached_query_ids))


def _update_features_from_html(html):
    # type: (str) -> None
    try:
        feature_pattern = re.compile(
            r'"([a-z][a-z0-9_]+)":\s*\{\s*"value"\s*:\s*(true|false)',
            re.IGNORECASE,
        )
        found = 0
        for match in feature_pattern.finditer(html):
            key = match.group(1)
            value = match.group(2).lower() == "true"
            if key in FEATURES and FEATURES[key] != value:
                FEATURES[key] = value
                found += 1
        if found:
            logger.info("Updated %d feature flags from x.com", found)
    except Exception as exc:
        logger.debug("Feature extraction from HTML failed: %s", exc)


def _fetch_from_github(url_fetch_fn, operation_name):
    # type: (Any, str) -> Optional[str]
    try:
        payload = url_fetch_fn(TWITTER_OPENAPI_URL)
        parsed = json.loads(payload)
        operation = parsed.get(operation_name, {})
        query_id = operation.get("queryId")
        if isinstance(query_id, str) and query_id:
            return query_id
    except Exception as exc:
        logger.debug("GitHub queryId lookup failed: %s", exc)
    return None


def _invalidate_query_id(operation_name):
    # type: (str) -> None
    _cached_query_ids.pop(operation_name, None)


def _resolve_query_id(operation_name, prefer_fallback=True, url_fetch_fn=None, allow_bundle_scan=True):
    # type: (str, bool, Any, bool) -> str
    cached = _cached_query_ids.get(operation_name)
    if cached:
        return cached

    fallback = FALLBACK_QUERY_IDS.get(operation_name)
    if prefer_fallback and fallback:
        _cached_query_ids[operation_name] = fallback
        return fallback

    if url_fetch_fn:
        github_query_id = _fetch_from_github(url_fetch_fn, operation_name)
        if github_query_id:
            _cached_query_ids[operation_name] = github_query_id
            return github_query_id

        if allow_bundle_scan:
            _scan_bundles(url_fetch_fn)
            cached = _cached_query_ids.get(operation_name)
            if cached:
                return cached

    if fallback:
        # Don't re-cache when caller explicitly wanted a fresh ID — the fallback
        # just round-tripped through invalidation, so caching it would make the
        # next call hit the same stale ID without retrying GitHub/bundle.
        if prefer_fallback:
            _cached_query_ids[operation_name] = fallback
        return fallback

    raise QueryIdError('Cannot resolve queryId for "%s"' % operation_name)
