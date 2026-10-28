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
    "UserByScreenName": "AMIBMjtxEEATh4z8V9GtRg",
    "UserTweets": "YHYMZsaMvzJvb5D2UVVjgw",
    "UserArticlesTweets": "px0ZuoJAreztxT8_nJr9Xg",
    "UserMedia": "eF8kYZ4r9zFLqcYno3I17A",
    "UserTweetsAndReplies": "MbxTcSWPt8RWRFMwenOtyQ",
    "UserHighlightsTweets": "2vCerAWrlID9W2wM0pmuaA",
    "TweetDetail": "gJoREC4Bspo4kJ0ax9C3sQ",
    "Likes": "mzOgReEsktOIIXzWkqf0ig",
    "SearchTimeline": "f7SuGIm11eLbQs7c0K9X9w",
    "Bookmarks": "2neUNDqrrFzbLui8yallcQ",
    "ListLatestTweetsTimeline": "RlZzktZY_9wJynoepm8ZsA",
    "Followers": "KLLQR3852iPAj8J32VMdXQ",
    "Following": "nxiL6UwEf7B1K1JNGPx-Jw",
    # Engagement writes
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A",
    "UnfavoriteTweet": "ZYKSe-w7KEslx3JhSIk5LA",
    "CreateRetweet": "mbRO74GrOvSfRcJnlMapnQ",
    "DeleteRetweet": "ZyZigVsNiFO6v1dEks1eWg",
    "CreateBookmark": "aoDbu3RHznuiSkQ9aNM67Q",
    "DeleteBookmark": "Wlmlj2-xzyS1GN3a6cj-mQ",
    # Content creation / deletion (write mode)
    "CreateTweet": "5CVj-J0FZWyGgJpcjeBJEA",
    "DeleteTweet": "nxpZCY2K-I6QoFHAHeojFQ",
    "CreateNoteTweet": "VtI_DWMLTJzkPVbTsOXMYw",
    # Pin / moderate / hide replies (v1.1)
    "PinTweet": "VIHsNu89pK-kW35JpHq7Xw",
    "UnpinTweet": "BhKei844ypCyLYCg0nwigw",
    "ModerateTweet": "pjFnHGVqCjTcZol0xcBJjw",
    "UnmoderateTweet": "pVSyu6PA57TLvIE4nN2tsA",
    # Single-tweet lookups
    "TweetResultByRestId": "a-Xpq8PjX9K6U5cmc1f05A",
    "TweetResultsByRestIds": "yicqPSziST_OYCvXJH4JbA",
    # Bookmark folders
    "BookmarkFoldersSlice": "i78YDd0Tza-dV4SYs58kRg",
    "BookmarkFolderTimeline": "hNY7X2xE2N7HVF6Qb_mu6w",
    # Explore / trend discovery
    "ExplorePage": "8AOU8kcEUKciZ1LZN1z8gw",
    "GenericTimelineById": "Hf-EsSfAki8uY9Q5ura6zQ",
    "TrendRelevantUsers": "UPgjT1PCj-iiCMMG4E7bkw",
    # Recommended users (Connect tab)
    "ConnectTabTimeline": "G2bOvMxw7fcLJep4_GPpdw",
    # Custom (pinned) timelines
    "PinnedTimelines": "8J1r9u3VjUveEdTY4WUTwQ",
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
        from .constants import HOME_PAGE_URL, get_user_agent
        html = url_fetch_fn(HOME_PAGE_URL, {"user-agent": get_user_agent()})
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
