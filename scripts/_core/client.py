"""Twitter GraphQL API client for x-cli.

Read-only + engagement writes (like/retweet/bookmark).
Content-creation and social-graph writes are out of scope.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

import bs4
from curl_cffi import requests as _cffi_requests
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import generate_headers as _gen_ct_headers, get_ondemand_file_url

from .constants import (
    BEARER_TOKEN,
    SEC_CH_UA_BITNESS,
    SEC_CH_UA_MOBILE,
    SEC_CH_UA_MODEL,
    get_accept_language,
    get_sec_ch_ua_arch,
    get_sec_ch_ua,
    get_sec_ch_ua_full_version,
    get_sec_ch_ua_full_version_list,
    get_sec_ch_ua_platform,
    get_sec_ch_ua_platform_version,
    get_twitter_client_language,
    get_user_agent,
    sync_chrome_version,
)
from .exceptions import NetworkError, NotFoundError, RateLimitError, TwitterAPIError
from .graphql import (
    FALLBACK_QUERY_IDS,
    FEATURES,
    _build_graphql_url,
    _invalidate_query_id,
    _resolve_query_id,
    _update_features_from_html,
)
from .models import BookmarkFolder, UserProfile
from .parser import (
    _deep_get,
    _parse_int,
    parse_timeline_response,
    parse_tweet_result,
    parse_user_result,
)

if TYPE_CHECKING:
    from typing import Dict, List, Optional, Set, Tuple  # noqa: F401
    from .models import Tweet  # noqa: F401

logger = logging.getLogger(__name__)

_cffi_session = None
_cffi_session_lock = threading.Lock()
TimelineInstructionGetter = Callable[[Any], Any]
_ABSOLUTE_MAX_COUNT = 500


def _best_chrome_target():
    # type: () -> str
    try:
        from curl_cffi.requests import BrowserType
        available = {e.value for e in BrowserType}
    except ImportError:
        available = set()
    for target in ("chrome133", "chrome133a", "chrome136", "chrome131", "chrome130"):
        if target in available:
            return target
    chrome_targets = sorted(
        [v for v in available if v.startswith("chrome") and v.replace("chrome", "").isdigit()],
        key=lambda x: int(x.replace("chrome", "")),
        reverse=True,
    )
    return chrome_targets[0] if chrome_targets else "chrome131"


def _get_cffi_session():
    # type: () -> Any
    global _cffi_session
    if _cffi_session is not None:
        return _cffi_session
    with _cffi_session_lock:
        if _cffi_session is None:
            proxy = os.environ.get("TWITTER_PROXY", "")
            target = _best_chrome_target()
            sync_chrome_version(target)
            _cffi_session = _cffi_requests.Session(
                impersonate=cast(Any, target),
                proxies={"https": proxy, "http": proxy} if proxy else None,
            )
            logger.info("curl_cffi impersonating %s", target)
    return _cffi_session


def _url_fetch(url, headers=None):
    # type: (str, Optional[Dict[str, str]]) -> str
    session = _get_cffi_session()
    resp = session.get(url, headers=headers or {}, timeout=30)
    resp.raise_for_status()
    return resp.text


class TwitterClient:
    """Twitter GraphQL API client. Read-only + engagement writes."""

    def __init__(self, auth_token, ct0, rate_limit_config=None, cookie_string=None):
        # type: (str, str, Optional[Dict[str, Any]], Optional[str]) -> None
        self._auth_token = auth_token
        self._ct0 = ct0
        self._cookie_string = cookie_string
        rl = rate_limit_config or {}
        self._request_delay = float(rl.get("requestDelay", 2.5))
        self._max_retries = int(rl.get("maxRetries", 3))
        self._retry_base_delay = float(rl.get("retryBaseDelay", 5.0))
        self._max_count = min(int(rl.get("maxCount", 200)), _ABSOLUTE_MAX_COUNT)
        self._write_delay_min = float(rl.get("writeDelayMin", 1.5))
        self._write_delay_max = float(rl.get("writeDelayMax", 4.0))
        self._client_transaction = None  # type: Optional[Any]
        self._ct_init_attempted = False
        self._ensure_client_transaction()

    # ── Read operations ──────────────────────────────────────────────

    def fetch_home_timeline(self, count=20, include_promoted=False, cursor=None, return_cursor=False):
        # type: (int, bool, Optional[str], bool) -> Any
        return self._fetch_timeline(
            "HomeTimeline",
            count,
            lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
            include_promoted=include_promoted,
            start_cursor=cursor,
            return_cursor=return_cursor,
        )

    def fetch_following_feed(self, count=20, include_promoted=False, cursor=None, return_cursor=False):
        # type: (int, bool, Optional[str], bool) -> Any
        return self._fetch_timeline(
            "HomeLatestTimeline",
            count,
            lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
            include_promoted=include_promoted,
            start_cursor=cursor,
            return_cursor=return_cursor,
        )

    def fetch_pinned_timelines(self):
        # type: () -> List[Dict[str, str]]
        """Return list of user's pinned (custom) timelines.

        Each item has: name, tab_label, tag, description, icon_name, typename.
        ``tag`` is the ID passed to fetch_custom_timeline().
        """
        data = self._graphql_get("PinnedTimelines", variables={}, features={})
        items = _deep_get(data, "data", "pinned_timelines", "pinned_timelines") or []
        result = []
        for item in items:
            typename = item.get("__typename", "")
            if typename == "TagPinnedTimeline":
                result.append({
                    "typename": typename,
                    "name": item.get("name", ""),
                    "tab_label": item.get("tab_label") or item.get("name", ""),
                    "tag": str(item.get("tag", "")),
                    "description": item.get("description", ""),
                    "icon_name": item.get("icon_name", ""),
                })
            elif typename == "ListPinnedTimeline":
                lst = item.get("list") or {}
                result.append({
                    "typename": typename,
                    "name": item.get("name") or lst.get("name", ""),
                    "tab_label": item.get("tab_label") or item.get("name") or lst.get("name", ""),
                    "tag": str(lst.get("id_str", "")),
                    "description": lst.get("description", ""),
                    "icon_name": "list",
                })
            else:
                logger.debug("fetch_pinned_timelines: unknown __typename %r, skipping", typename)
        return result

    def fetch_custom_timeline(self, tag_id, count=20, cursor=None, return_cursor=False):
        # type: (str, int, Optional[str], bool) -> Any
        """Fetch a custom (pinned) tag-based home timeline by its tag ID.

        tag_id is the numeric string from fetch_pinned_timelines()["tag"].
        """
        if not tag_id:
            raise ValueError("fetch_custom_timeline: tag_id must not be empty")
        return self._fetch_timeline(
            "HomeTimeline",
            count,
            lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
            extra_variables={"tag": tag_id, "withCommunity": True},
            start_cursor=cursor,
            return_cursor=return_cursor,
        )

    def fetch_bookmarks(self, count=50):
        # type: (int) -> List[Tweet]
        def get_instructions(data):
            instructions = _deep_get(data, "data", "bookmark_timeline", "timeline", "instructions")
            if instructions is None:
                instructions = _deep_get(data, "data", "bookmark_timeline_v2", "timeline", "instructions")
            return instructions
        return self._fetch_timeline("Bookmarks", count, get_instructions)

    def fetch_bookmark_folders(self):
        # type: () -> List[BookmarkFolder]
        folders = []  # type: List[BookmarkFolder]
        cursor = None  # type: Optional[str]
        for _ in range(10):
            variables = {}  # type: Dict[str, Any]
            if cursor:
                variables["cursor"] = cursor
            data = self._graphql_get("BookmarkFoldersSlice", variables, FEATURES)
            slice_data = _deep_get(
                data, "data", "viewer", "user_results", "result", "bookmark_collections_slice",
            )
            if not isinstance(slice_data, dict):
                break
            for item in slice_data.get("items", []):
                folder_id = item.get("id")
                folder_name = item.get("name", "")
                if folder_id:
                    folders.append(BookmarkFolder(id=folder_id, name=folder_name))
            next_cursor = _deep_get(slice_data, "slice_info", "next_cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return folders

    def fetch_bookmark_folder_timeline(self, folder_id, count=50):
        # type: (str, int) -> List[Tweet]
        def get_instructions(data):
            return _deep_get(data, "data", "bookmark_collection_timeline", "timeline", "instructions")
        return self._fetch_timeline(
            "BookmarkFolderTimeline",
            count,
            get_instructions,
            extra_variables={"bookmark_collection_id": folder_id, "includePromotedContent": False},
            override_base_variables=True,
        )

    def resolve_user_id(self, identifier):
        # type: (str) -> str
        if identifier.isdigit():
            return identifier
        profile = self.fetch_user(identifier)
        return profile.id

    def fetch_user(self, screen_name):
        # type: (str) -> UserProfile
        variables = {"screen_name": screen_name, "withSafetyModeUserFields": True}
        features = {
            "hidden_profile_subscriptions_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        }
        data = self._graphql_get("UserByScreenName", variables, features)
        result = _deep_get(data, "data", "user", "result")
        if not result:
            raise NotFoundError("User @%s not found" % screen_name)
        legacy = result.get("legacy", {})
        core = result.get("core", {})
        avatar = result.get("avatar", {})
        location_obj = result.get("location", {})
        return UserProfile(
            id=result.get("rest_id", ""),
            name=core.get("name") or legacy.get("name", ""),
            screen_name=core.get("screen_name") or legacy.get("screen_name", screen_name),
            bio=legacy.get("description", ""),
            location=location_obj.get("location") or legacy.get("location", ""),
            url=_deep_get(legacy, "entities", "url", "urls", 0, "expanded_url") or "",
            followers_count=_parse_int(legacy.get("followers_count"), 0),
            following_count=_parse_int(legacy.get("friends_count"), 0),
            tweets_count=_parse_int(legacy.get("statuses_count"), 0),
            likes_count=_parse_int(legacy.get("favourites_count"), 0),
            verified=bool(result.get("is_blue_verified") or legacy.get("verified", False)),
            profile_image_url=avatar.get("image_url") or legacy.get("profile_image_url_https", ""),
            created_at=core.get("created_at") or legacy.get("created_at", ""),
        )

    def fetch_user_tweets(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "UserTweets",
            count,
            lambda data: (
                _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions")
                or _deep_get(data, "data", "user", "result", "timeline_v2", "timeline", "instructions")
            ),
            extra_variables={
                "userId": user_id,
                "includePromotedContent": True,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True,
            },
        )

    def fetch_user_replies(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "UserTweetsAndReplies",
            count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
            extra_variables={
                "userId": user_id,
                "includePromotedContent": True,
                "withCommunity": True,
                "withVoice": True,
                "withV2Timeline": True,
            },
        )

    def fetch_user_media(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "UserMedia",
            count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
            extra_variables={
                "userId": user_id,
                "includePromotedContent": False,
                "withClientEventToken": False,
                "withBirdwatchNotes": False,
                "withVoice": True,
                "withV2Timeline": True,
            },
        )

    def fetch_user_highlights(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "UserHighlightsTweets",
            count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
            extra_variables={
                "userId": user_id,
                "includePromotedContent": False,
                "withVoice": True,
            },
        )

    def fetch_user_articles(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "UserArticlesTweets",
            count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
            extra_variables={
                "userId": user_id,
                "includePromotedContent": False,
                "withVoice": False,
                "withV2Timeline": True,
                "withSuperFollowsUserFields": True,
                "withDownvotePerspective": False,
                "withBirdwatchNotes": False,
                "withSuperFollowsTweetFields": True,
                "withReactionsMetadata": False,
                "withReactionsPerspective": False,
                "withClientEventToken": False,
            },
        )

    def fetch_user_likes(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        def get_likes_instructions(data):
            instructions = _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions")
            if instructions is None:
                instructions = _deep_get(data, "data", "user", "result", "timeline_v2", "timeline", "instructions")
            return instructions
        return self._fetch_timeline(
            "Likes",
            count,
            get_likes_instructions,
            extra_variables={
                "userId": user_id,
                "includePromotedContent": False,
                "withClientEventToken": False,
                "withBirdwatchNotes": False,
                "withVoice": True,
            },
            override_base_variables=True,
        )

    def fetch_search(self, query, count=20, product="Top"):
        # type: (str, int, str) -> List[Tweet]
        return self._fetch_timeline(
            "SearchTimeline",
            count,
            lambda data: _deep_get(
                data, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions",
            ),
            extra_variables={
                "rawQuery": query,
                "querySource": "typed_query",
                "product": product,
            },
            override_base_variables=True,
            use_post=True,
        )

    def search_users(self, query, count=20):
        # type: (str, int) -> List[UserProfile]
        if count <= 0:
            return []
        count = min(count, self._max_count)
        users = []  # type: List[UserProfile]
        seen_ids = set()  # type: Set[str]
        cursor = None  # type: Optional[str]
        attempts = 0
        max_attempts = int(math.ceil(count / 20.0)) + 2
        while len(users) < count and attempts < max_attempts:
            attempts += 1
            variables = {
                "rawQuery": query,
                "querySource": "typed_query",
                "product": "People",
                "count": min(count - len(users) + 5, 40),
                "includePromotedContent": False,
            }  # type: Dict[str, Any]
            if cursor:
                variables["cursor"] = cursor
            data = self._graphql_post("SearchTimeline", variables, FEATURES)
            instructions = _deep_get(
                data, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions",
            ) or []
            new_users = []  # type: List[UserProfile]
            next_cursor = None  # type: Optional[str]
            for instruction in instructions:
                for entry in instruction.get("entries", []):
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if entry_type == "TimelineTimelineItem":
                        item = content.get("itemContent", {})
                        if item.get("itemType") != "TimelineUser":
                            continue
                        ur = _deep_get(item, "user_results", "result")
                        if ur:
                            user = parse_user_result(ur)
                            if user:
                                new_users.append(user)
                    elif entry_type == "TimelineTimelineCursor":
                        if content.get("cursorType") == "Bottom":
                            next_cursor = content.get("value")
            added_users = 0
            for user in new_users:
                if user.id and user.id not in seen_ids:
                    seen_ids.add(user.id)
                    users.append(user)
                    added_users += 1
            if not next_cursor or next_cursor == cursor or not new_users or added_users == 0:
                break
            cursor = next_cursor
            if len(users) < count and self._request_delay > 0:
                time.sleep(self._request_delay * random.uniform(0.7, 1.5))
        return users[:count]

    def fetch_tweet_detail(self, tweet_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "TweetDetail",
            count,
            lambda data: (
                _deep_get(data, "data", "tweetResult", "result", "timeline", "instructions")
                or _deep_get(data, "data", "threaded_conversation_with_injections_v2", "instructions")
            ),
            extra_variables={
                "focalTweetId": tweet_id,
                "referrer": "tweet",
                "with_rux_injections": False,
                "includePromotedContent": True,
                "rankingMode": "Relevance",
                "withCommunity": True,
                "withQuickPromoteEligibilityTweetFields": True,
                "withBirdwatchNotes": True,
                "withVoice": True,
            },
            override_base_variables=True,
            field_toggles={
                "withArticleRichContentState": True,
                "withArticlePlainText": False,
                "withGrokAnalyze": False,
                "withDisallowedReplyControls": False,
            },
        )

    def fetch_tweets_by_ids(self, tweet_ids):
        # type: (Any) -> List[Tweet]
        if not tweet_ids:
            return []
        seen = set()  # type: Set[str]
        ids = [x for x in tweet_ids if not (x in seen or seen.add(x))]
        data = self._graphql_get(
            "TweetResultsByRestIds",
            variables={
                "tweetIds": ids,
                "includePromotedContent": False,
                "withCommunity": False,
                "withVoice": False,
            },
            features={
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "longform_notetweets_rich_text_read_enabled": True,
                "longform_notetweets_inline_media_enabled": True,
                "articles_preview_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
            },
        )
        results = _deep_get(data, "data", "tweetResult") or []
        tweets = []  # type: List[Tweet]
        for item in results:
            if not isinstance(item, dict):
                continue
            result = item.get("result")
            if not result:
                continue
            tweet = parse_tweet_result(result)
            if tweet:
                tweets.append(tweet)
        return tweets

    def fetch_article(self, tweet_id):
        # type: (str) -> Tweet
        data = self._graphql_get(
            "TweetResultByRestId",
            variables={
                "tweetId": tweet_id,
                "withCommunity": False,
                "includePromotedContent": False,
                "withVoice": False,
            },
            features={
                "longform_notetweets_consumption_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "longform_notetweets_rich_text_read_enabled": True,
                "longform_notetweets_inline_media_enabled": True,
                "articles_preview_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
            },
            field_toggles={
                "withArticleRichContentState": True,
                "withArticlePlainText": True,
            },
        )
        result = _deep_get(data, "data", "tweetResult", "result")
        if not result:
            raise NotFoundError("Article not found: tweet_id=%s" % tweet_id)
        tweet = parse_tweet_result(result)
        if tweet is None or (tweet.article_title is None and tweet.article_text is None):
            raise NotFoundError("Tweet %s has no article content" % tweet_id)
        return tweet

    def fetch_list_timeline(self, list_id, count=20):
        # type: (str, int) -> List[Tweet]
        return self._fetch_timeline(
            "ListLatestTweetsTimeline",
            count,
            lambda data: _deep_get(data, "data", "list", "tweets_timeline", "timeline", "instructions"),
            extra_variables={"listId": list_id},
            override_base_variables=True,
        )

    def fetch_followers(self, user_id, count=20):
        # type: (str, int) -> List[UserProfile]
        return self._fetch_user_list(
            "Followers", user_id, count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
            use_post=True,
        )

    def fetch_following(self, user_id, count=20):
        # type: (str, int) -> List[UserProfile]
        return self._fetch_user_list(
            "Following", user_id, count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions"),
            use_post=True,
        )

    def fetch_recommended_users(self, user_id=None, count=20):
        # type: (Optional[str], int) -> List[UserProfile]
        """Fetch recommended users from X's Connect tab.

        If *user_id* is provided, returns users contextually related to that
        user (similar accounts).  Without it, returns the caller's general
        "who to follow" suggestions.
        """
        import json as _json
        if count <= 0:
            return []
        count = min(count, self._max_count)
        users = []  # type: List[UserProfile]
        seen_ids = set()  # type: Set[str]
        cursor = None  # type: Optional[str]
        attempts = 0
        max_attempts = int(math.ceil(count / 20.0)) + 2
        while len(users) < count and attempts < max_attempts:
            attempts += 1
            context_value = None  # type: Optional[str]
            if user_id:
                context_value = _json.dumps({"contextualUserId": user_id})
            variables = {
                "count": min(count - len(users) + 5, 40),
                "context": context_value,
                "includePromotedContent": False,
            }  # type: Dict[str, Any]
            if cursor:
                variables["cursor"] = cursor
            data = self._graphql_post("ConnectTabTimeline", variables, FEATURES)
            # Response path: data.connect_tab_timeline.timeline.instructions
            instructions = _deep_get(
                data, "data", "connect_tab_timeline", "timeline", "instructions",
            )
            if not instructions:
                # Fallback path in case X changes structure
                instructions = _deep_get(
                    data, "data", "timeline", "timeline", "instructions",
                )
            if not instructions:
                break
            new_users = []  # type: List[UserProfile]
            next_cursor = None  # type: Optional[str]
            for instruction in instructions:
                entries = instruction.get("entries", [])
                # Also check "moduleItems" for Connect tab
                for entry in entries:
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if entry_type == "TimelineTimelineItem":
                        item = content.get("itemContent", {})
                        user_results = _deep_get(item, "user_results", "result")
                        if user_results:
                            user = parse_user_result(user_results)
                            if user:
                                new_users.append(user)
                    elif entry_type == "TimelineTimelineModule":
                        # Connect tab wraps users in modules
                        for module_item in content.get("items", []):
                            mi = module_item.get("item", {}).get("itemContent", {})
                            user_results = _deep_get(mi, "user_results", "result")
                            if user_results:
                                user = parse_user_result(user_results)
                                if user:
                                    new_users.append(user)
                    elif entry_type == "TimelineTimelineCursor":
                        if content.get("cursorType") == "Bottom":
                            next_cursor = content.get("value")
            added_users = 0
            for user in new_users:
                if user.id and user.id not in seen_ids:
                    seen_ids.add(user.id)
                    users.append(user)
                    added_users += 1
            if not next_cursor or next_cursor == cursor or not new_users or added_users == 0:
                break
            cursor = next_cursor
            if len(users) < count and self._request_delay > 0:
                time.sleep(self._request_delay * random.uniform(0.7, 1.5))
        return users[:count]

    def fetch_all_following_ids(self, user_id, max_count=2000):
        # type: (str, int) -> Set[str]
        """Fetch up to max_count of the user's followed accounts, return set of user IDs.

        Used to build the following cache for you_follow_author annotation.
        """
        profiles = self.fetch_following(user_id, count=max_count)
        return {p.id for p in profiles if p.id}

    def fetch_me(self):
        # type: () -> UserProfile
        url = "https://x.com/i/api/1.1/account/multi/list.json"
        data = self._api_get(url)
        screen_name = None
        if isinstance(data, dict) and "users" in data:
            users = data["users"]
            if isinstance(users, list) and users:
                screen_name = users[0].get("screen_name")
        elif isinstance(data, list) and data:
            user_data = data[0].get("user", {})
            if user_data:
                sn = user_data.get("screen_name", "")
                if user_data.get("followers_count") is not None:
                    return UserProfile(
                        id=str(user_data.get("id_str", "")),
                        name=user_data.get("name", ""),
                        screen_name=sn,
                        bio=user_data.get("description", ""),
                        location=user_data.get("location", ""),
                        url=_deep_get(user_data, "entities", "url", "urls", 0, "expanded_url") or "",
                        followers_count=_parse_int(user_data.get("followers_count"), 0),
                        following_count=_parse_int(user_data.get("friends_count"), 0),
                        tweets_count=_parse_int(user_data.get("statuses_count"), 0),
                        likes_count=_parse_int(user_data.get("favourites_count"), 0),
                        verified=bool(user_data.get("verified", False)),
                        profile_image_url=user_data.get("profile_image_url_https", ""),
                        created_at=user_data.get("created_at", ""),
                    )
                screen_name = sn
        if screen_name:
            return self.fetch_user(screen_name)
        raise TwitterAPIError(0, "Failed to fetch current user info")

    # ── Engagement write operations ─────────────────────────────────

    def _write_delay(self):
        # type: () -> None
        lo, hi = self._write_delay_min, self._write_delay_max
        if hi <= lo:
            hi = lo
        time.sleep(random.uniform(lo, hi) if hi > 0 else 0)

    def _validate_write_response(self, operation_name, response_key, response, expected_value=None, required_subkeys=None):
        # type: (str, str, Dict[str, Any], Optional[str], Optional[List[str]]) -> None
        data = response.get("data") if isinstance(response, dict) else None
        value = data.get(response_key) if isinstance(data, dict) else None

        def _fail(reason):
            detail = "null" if value is None else json.dumps(value, ensure_ascii=False)[:200]
            raise TwitterAPIError(0, "%s failed: %s in data.%s (%s)" % (
                operation_name, reason, response_key, detail,
            ))

        if value is None:
            _fail("missing key")

        # Reject embedded errors at any level
        if isinstance(value, dict) and value.get("errors"):
            _fail("API returned errors")

        if expected_value is not None:
            if value != expected_value:
                _fail("unexpected value (wanted %r)" % expected_value)
            return

        if required_subkeys:
            if not isinstance(value, dict):
                _fail("expected dict")
            missing = [k for k in required_subkeys if not value.get(k)]
            if missing:
                _fail("missing subkeys %s" % missing)
            return

        if not value:
            _fail("empty response")

    def like_tweet(self, tweet_id):
        # type: (str) -> bool
        response = self._graphql_post("FavoriteTweet", {"tweet_id": tweet_id}, allow_bundle_scan=False)
        self._validate_write_response("FavoriteTweet", "favorite_tweet", response, expected_value="Done")
        self._write_delay()
        return True

    def unlike_tweet(self, tweet_id):
        # type: (str) -> bool
        response = self._graphql_post(
            "UnfavoriteTweet", {"tweet_id": tweet_id, "dark_request": False}, allow_bundle_scan=False,
        )
        self._validate_write_response("UnfavoriteTweet", "unfavorite_tweet", response, expected_value="Done")
        self._write_delay()
        return True

    def retweet(self, tweet_id):
        # type: (str) -> bool
        response = self._graphql_post(
            "CreateRetweet", {"tweet_id": tweet_id, "dark_request": False}, allow_bundle_scan=False,
        )
        self._validate_write_response(
            "CreateRetweet", "create_retweet", response, required_subkeys=["retweet_results"],
        )
        self._write_delay()
        return True

    def unretweet(self, tweet_id):
        # type: (str) -> bool
        response = self._graphql_post(
            "DeleteRetweet", {"source_tweet_id": tweet_id, "dark_request": False}, allow_bundle_scan=False,
        )
        # X returns either {"unretweet": {...}} (current) or {"delete_retweet": {...}} (older).
        # Accept either; also accept null/empty as idempotent success.
        data = response.get("data") if isinstance(response, dict) else None
        value = None
        if isinstance(data, dict):
            for k in ("unretweet", "delete_retweet"):
                if k in data:
                    value = data[k]
                    break
            else:
                raise TwitterAPIError(
                    0,
                    "DeleteRetweet failed: neither 'unretweet' nor 'delete_retweet' in response (%s)"
                    % str(data)[:200],
                )
        if isinstance(value, dict) and value.get("errors"):
            raise TwitterAPIError(0, "DeleteRetweet errors: %s" % str(value["errors"])[:200])
        self._write_delay()
        return True

    def bookmark_tweet(self, tweet_id, folder_id=None):
        # type: (str, Optional[str]) -> bool
        variables = {"tweet_id": tweet_id}  # type: Dict[str, Any]
        if folder_id:
            variables["bookmark_collection_id"] = folder_id
        response = self._graphql_post("CreateBookmark", variables, allow_bundle_scan=False)
        self._validate_write_response("CreateBookmark", "tweet_bookmark_put", response, expected_value="Done")
        self._write_delay()
        return True

    def unbookmark_tweet(self, tweet_id):
        # type: (str) -> bool
        response = self._graphql_post("DeleteBookmark", {"tweet_id": tweet_id}, allow_bundle_scan=False)
        self._validate_write_response("DeleteBookmark", "tweet_bookmark_delete", response, expected_value="Done")
        self._write_delay()
        return True

    # ── Content creation / deletion ─────────────────────────────────

    _STANDARD_TWEET_MAX = 280

    def create_tweet(self, text, reply_to=None, quote_tweet_id=None, media_ids=None):
        # type: (str, Optional[str], Optional[str], Optional[List[str]]) -> Dict[str, Any]
        """Post a new tweet, optionally as a reply or with a quoted tweet.

        Auto-dispatches to CreateNoteTweet (long-form) when text exceeds 280 chars.
        Note: CreateNoteTweet requires the account to have X Premium.

        Returns the created tweet's API result dict (containing rest_id, etc.)
        """
        media_entities = []
        if media_ids:
            for mid in media_ids:
                media_entities.append({"media_id": mid, "tagged_users": []})
        is_note = len(text) > self._STANDARD_TWEET_MAX
        variables: Dict[str, Any] = {
            "tweet_text": text,
            "dark_request": False,
            "media": {"media_entities": media_entities, "possibly_sensitive": False},
            "semantic_annotation_ids": [],
            "disallowed_reply_options": None,
        }
        if is_note:
            variables["richtext_options"] = {"richtext_tags": []}
        if reply_to:
            variables["reply"] = {
                "in_reply_to_tweet_id": reply_to,
                "exclude_reply_user_ids": [],
            }
        if quote_tweet_id:
            variables["attachment_url"] = "https://twitter.com/i/web/status/%s" % quote_tweet_id

        features = {
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_jetfuel_frame": False,
            "responsive_web_grok_analysis_button_from_backend": True,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }
        op = "CreateNoteTweet" if is_note else "CreateTweet"
        response_key = "notetweet_create" if is_note else "create_tweet"
        response = self._graphql_post(op, variables, features=features)
        self._validate_write_response(
            op, response_key, response, required_subkeys=["tweet_results"],
        )
        self._write_delay()
        result = response["data"][response_key]["tweet_results"].get("result") or {}
        return result

    def delete_tweet(self, tweet_id):
        # type: (str) -> bool
        variables = {"tweet_id": tweet_id, "dark_request": False}
        response = self._graphql_post("DeleteTweet", variables)
        # Success: {"data": {"delete_tweet": {"tweet_results": {}}}} — empty dict IS success.
        # We just check for nested errors.
        data = response.get("data") if isinstance(response, dict) else None
        value = data.get("delete_tweet") if isinstance(data, dict) else None
        if value is None or not isinstance(value, dict) or "tweet_results" not in value:
            raise TwitterAPIError(0, "DeleteTweet failed: %s" % json.dumps(value)[:200])
        if value.get("errors"):
            raise TwitterAPIError(0, "DeleteTweet errors: %s" % json.dumps(value["errors"])[:200])
        self._write_delay()
        return True

    # ── Social-graph writes (legacy REST) ───────────────────────────

    def _legacy_rest_post(self, path, data):
        # type: (str, Dict[str, str]) -> Dict[str, Any]
        """POST to the legacy REST API (used for follow/unfollow/block/mute)."""
        url = "https://api.x.com/1.1/%s" % path.lstrip("/")
        headers = self._build_headers()
        # REST endpoints expect form-encoded, not JSON
        headers["content-type"] = "application/x-www-form-urlencoded"
        from urllib.parse import urlencode
        body = urlencode(data)
        if not self._ct_init_attempted:
            self._init_client_transaction()
        if self._client_transaction is not None:
            try:
                tid = self._client_transaction.generate_transaction_id(method="POST", path="/1.1/%s" % path.lstrip("/"))
                if tid:
                    headers["x-client-transaction-id"] = tid
            except Exception:
                pass
        session = _get_cffi_session()
        cookies = {"auth_token": self._auth_token, "ct0": self._ct0}
        if self._cookie_string:
            for piece in self._cookie_string.split(";"):
                if "=" in piece:
                    k, v = piece.strip().split("=", 1)
                    cookies.setdefault(k, v)
        for attempt in range(self._max_retries + 1):
            try:
                resp = session.post(url, headers=headers, cookies=cookies, data=body, timeout=30)
                if resp.status_code == 429:
                    if attempt < self._max_retries:
                        delay = self._retry_base_delay * (2 ** attempt) * random.uniform(0.8, 1.2)
                        logger.warning("Rate limited on %s, sleeping %.1fs", path, delay)
                        time.sleep(delay)
                        continue
                    raise RateLimitError("Rate limited on REST %s after %d retries" % (path, self._max_retries))
                if resp.status_code >= 400:
                    raise TwitterAPIError(resp.status_code, "REST %s failed: %s" % (path, resp.text[:300]))
                try:
                    return resp.json() if resp.text else {}
                except Exception:
                    return {"raw": resp.text}
            except (RateLimitError, TwitterAPIError):
                raise
            except Exception as exc:
                if attempt < self._max_retries:
                    time.sleep(self._retry_base_delay * (attempt + 1))
                    continue
                raise NetworkError("REST %s network error: %s" % (path, exc))
        raise NetworkError("REST %s exhausted retries" % path)

    def follow_user(self, screen_name):
        # type: (str) -> Dict[str, Any]
        """Follow a user by handle (legacy REST endpoint)."""
        result = self._legacy_rest_post(
            "friendships/create.json",
            {"screen_name": screen_name, "include_profile_interstitial_type": "1",
             "include_blocking": "1", "include_blocked_by": "1", "include_followed_by": "1",
             "include_want_retweets": "1", "include_mute_edge": "1", "include_can_dm": "1",
             "include_can_media_tag": "1", "include_ext_is_blue_verified": "1",
             "skip_status": "1"},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "Follow %s failed: %s" % (screen_name, str(result)[:200]))
        self._write_delay()
        return result

    def unfollow_user(self, screen_name):
        # type: (str) -> Dict[str, Any]
        """Unfollow a user by handle."""
        result = self._legacy_rest_post(
            "friendships/destroy.json",
            {"screen_name": screen_name, "include_profile_interstitial_type": "1",
             "include_blocking": "1", "include_blocked_by": "1", "include_followed_by": "1",
             "skip_status": "1"},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "Unfollow %s failed: %s" % (screen_name, str(result)[:200]))
        self._write_delay()
        return result

    # ── Block / Mute (legacy REST) ──────────────────────────────────

    def block_user(self, screen_name):
        # type: (str) -> Dict[str, Any]
        """Block a user by handle."""
        result = self._legacy_rest_post(
            "blocks/create.json",
            {"screen_name": screen_name, "skip_status": "1"},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "Block %s failed: %s" % (screen_name, str(result)[:200]))
        self._write_delay()
        return result

    def unblock_user(self, screen_name):
        # type: (str) -> Dict[str, Any]
        """Unblock a user."""
        result = self._legacy_rest_post(
            "blocks/destroy.json",
            {"screen_name": screen_name, "skip_status": "1"},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "Unblock %s failed: %s" % (screen_name, str(result)[:200]))
        self._write_delay()
        return result

    def mute_user(self, screen_name):
        # type: (str) -> Dict[str, Any]
        """Mute a user by handle."""
        result = self._legacy_rest_post(
            "mutes/users/create.json",
            {"screen_name": screen_name, "skip_status": "1"},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "Mute %s failed: %s" % (screen_name, str(result)[:200]))
        self._write_delay()
        return result

    def unmute_user(self, screen_name):
        # type: (str) -> Dict[str, Any]
        """Unmute a user by handle."""
        result = self._legacy_rest_post(
            "mutes/users/destroy.json",
            {"screen_name": screen_name, "skip_status": "1"},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "Unmute %s failed: %s" % (screen_name, str(result)[:200]))
        self._write_delay()
        return result

    # ── Pin / Unpin own tweet (GraphQL, legacy REST for pinning) ─────

    def pin_tweet(self, tweet_id):
        # type: (str) -> bool
        """Pin one of your own tweets to your profile."""
        # X uses the legacy REST /1.1/account/pin_tweet.json endpoint
        result = self._legacy_rest_post(
            "account/pin_tweet.json",
            {"tweet_mode": "extended", "id": tweet_id},
        )
        self._write_delay()
        return bool(result)

    def unpin_tweet(self, tweet_id):
        # type: (str) -> bool
        """Unpin a pinned tweet."""
        result = self._legacy_rest_post(
            "account/unpin_tweet.json",
            {"tweet_mode": "extended", "id": tweet_id},
        )
        self._write_delay()
        return bool(result)

    # ── Hide / Unhide reply to your tweet (GraphQL) ──────────────────

    def hide_reply(self, tweet_id):
        # type: (str) -> bool
        """Hide a reply to one of your tweets from the default reply view."""
        response = self._graphql_post("ModerateTweet", {"tweetId": tweet_id})
        self._validate_write_response(
            "ModerateTweet", "tweet_moderate_put", response,
            required_subkeys=["tweet_results"],
        )
        self._write_delay()
        return True

    def unhide_reply(self, tweet_id):
        # type: (str) -> bool
        """Un-hide a previously hidden reply."""
        response = self._graphql_post("UnmoderateTweet", {"tweetId": tweet_id})
        self._validate_write_response(
            "UnmoderateTweet", "unmoderate_tweet", response,
            required_subkeys=["tweet_results"],
        )
        self._write_delay()
        return True

    # ── Lists CRUD (legacy REST) ────────────────────────────────────

    def create_list(self, name, description="", mode="private"):
        # type: (str, str, str) -> Dict[str, Any]
        """Create a new X List. mode: 'public' or 'private'."""
        if mode not in ("public", "private"):
            raise ValueError("mode must be 'public' or 'private'")
        result = self._legacy_rest_post(
            "lists/create.json",
            {"name": name, "mode": mode, "description": description},
        )
        if not result or not result.get("id_str"):
            raise TwitterAPIError(0, "create_list failed: %s" % str(result)[:200])
        self._write_delay()
        return result

    def delete_list(self, list_id):
        # type: (str) -> Dict[str, Any]
        """Delete a list you own."""
        result = self._legacy_rest_post("lists/destroy.json", {"list_id": list_id})
        self._write_delay()
        return result or {}

    def add_list_member(self, list_id, screen_name):
        # type: (str, str) -> Dict[str, Any]
        """Add a user to one of your lists."""
        result = self._legacy_rest_post(
            "lists/members/create.json",
            {"list_id": list_id, "screen_name": screen_name},
        )
        self._write_delay()
        return result or {}

    def remove_list_member(self, list_id, screen_name):
        # type: (str, str) -> Dict[str, Any]
        """Remove a user from one of your lists."""
        result = self._legacy_rest_post(
            "lists/members/destroy.json",
            {"list_id": list_id, "screen_name": screen_name},
        )
        self._write_delay()
        return result or {}

    # ── Media upload (legacy 3-step v1.1) ───────────────────────────

    _MEDIA_MIME = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
        ".mp4": "video/mp4",
    }
    _MEDIA_MAX_BYTES_IMAGE = 5 * 1024 * 1024   # 5MB (X limit for images via web)
    _MEDIA_MAX_BYTES_GIF = 15 * 1024 * 1024    # 15MB
    _MEDIA_MAX_BYTES_VIDEO = 512 * 1024 * 1024 # 512MB per docs
    _MEDIA_APPEND_CHUNK = 1 * 1024 * 1024      # 1MB per APPEND call

    def upload_media(self, path):
        # type: (str) -> str
        """Upload a local file (image or short video) and return its media_id.

        Uses X's legacy 3-step endpoint on upload.x.com: INIT → APPEND → FINALIZE.
        For images, one APPEND chunk is enough. For videos, chunks sequentially.
        """
        import mimetypes
        if not os.path.isfile(path):
            raise ValueError("Media file not found: %s" % path)
        size = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        mime = self._MEDIA_MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"

        is_video = mime.startswith("video/")
        is_gif = mime == "image/gif"
        cap = (self._MEDIA_MAX_BYTES_VIDEO if is_video
               else self._MEDIA_MAX_BYTES_GIF if is_gif
               else self._MEDIA_MAX_BYTES_IMAGE)
        if size > cap:
            raise ValueError(
                "Media too large: %d bytes (cap %d for %s)" % (size, cap, mime)
            )

        media_category = (
            "tweet_video" if is_video else
            "tweet_gif" if is_gif else
            "tweet_image"
        )

        upload_base = "https://upload.x.com/1.1/media/upload.json"

        # ── INIT ──
        init_resp = self._upload_post(
            upload_base,
            data={
                "command": "INIT",
                "total_bytes": str(size),
                "media_type": mime,
                "media_category": media_category,
            },
        )
        media_id = init_resp.get("media_id_string") or init_resp.get("media_id")
        if not media_id:
            raise TwitterAPIError(0, "upload INIT failed: %s" % str(init_resp)[:200])
        media_id = str(media_id)

        # ── APPEND (chunked) ──
        with open(path, "rb") as f:
            seg = 0
            while True:
                chunk = f.read(self._MEDIA_APPEND_CHUNK)
                if not chunk:
                    break
                self._upload_post(
                    upload_base,
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(seg),
                    },
                    files={"media": ("blob", chunk, "application/octet-stream")},
                    expect_json=False,
                )
                seg += 1

        # ── FINALIZE ──
        fin_resp = self._upload_post(
            upload_base,
            data={"command": "FINALIZE", "media_id": media_id},
        )
        # Video may return processing_info; poll if so
        proc = fin_resp.get("processing_info") if isinstance(fin_resp, dict) else None
        while proc and proc.get("state") in ("pending", "in_progress"):
            time.sleep(proc.get("check_after_secs", 2))
            st_resp = self._upload_post(
                upload_base, data={"command": "STATUS", "media_id": media_id},
                method="GET",
            )
            proc = st_resp.get("processing_info") if isinstance(st_resp, dict) else None
        if proc and proc.get("state") == "failed":
            raise TwitterAPIError(0, "Media processing failed: %s" % proc)

        return media_id

    def _upload_post(self, url, data=None, files=None, method="POST", expect_json=True):
        # type: (str, Optional[Dict[str, str]], Optional[Dict[str, Any]], str, bool) -> Dict[str, Any]
        """POST to upload.x.com. Uses bearer + ct0 + cookies, not GraphQL headers."""
        session = _get_cffi_session()
        headers = {
            "authorization": "Bearer %s" % BEARER_TOKEN,
            "x-csrf-token": self._ct0,
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "user-agent": get_user_agent(),
        }
        cookies = {"auth_token": self._auth_token, "ct0": self._ct0}
        if self._cookie_string:
            for piece in self._cookie_string.split(";"):
                if "=" in piece:
                    k, v = piece.strip().split("=", 1)
                    cookies.setdefault(k, v)

        if method == "GET":
            resp = session.get(url, params=data, headers=headers, cookies=cookies, timeout=60)
        elif files:
            # curl_cffi uses CurlMime for multipart — build explicitly.
            from curl_cffi import CurlMime
            mp = CurlMime()
            for field_name, (filename, content, ctype) in files.items():
                mp.addpart(name=field_name, filename=filename, data=content, content_type=ctype)
            for k, v in (data or {}).items():
                mp.addpart(name=k, data=str(v))
            resp = session.post(url, multipart=mp, headers=headers, cookies=cookies, timeout=120)
        else:
            resp = session.post(url, data=data, headers=headers, cookies=cookies, timeout=60)

        if resp.status_code >= 400:
            raise TwitterAPIError(resp.status_code, "upload %s: %s" % (
                (data or {}).get("command", "?"), resp.text[:300]
            ))
        if not expect_json:
            return {}
        try:
            return resp.json() if resp.text else {}
        except Exception:
            return {"raw": resp.text}

    # ── Internal: timeline / user list fetchers ──────────────────────

    def _fetch_timeline(
        self, operation_name, count, get_instructions,
        extra_variables=None, override_base_variables=False,
        field_toggles=None, use_post=False, include_promoted=False,
        start_cursor=None, return_cursor=False,
    ):
        # type: (str, int, Callable[[Any], Any], Optional[Dict[str, Any]], bool, Optional[Dict[str, Any]], bool, bool, Optional[str], bool) -> Any
        if count <= 0:
            return [] if not return_cursor else ([], None)
        count = min(count, self._max_count)
        tweets = []  # type: List[Tweet]
        seen_ids = set()  # type: Set[str]
        cursor = start_cursor  # type: Optional[str]
        continuation_cursor = None  # type: Optional[str]
        attempts = 0
        max_attempts = int(math.ceil(count / 20.0)) + 2
        while len(tweets) < count and attempts < max_attempts:
            attempts += 1
            variables: Dict[str, Any]
            if override_base_variables:
                variables = {"count": min(count - len(tweets) + 5, 40)}
            else:
                variables = {
                    "count": min(count - len(tweets) + 5, 40),
                    "includePromotedContent": include_promoted,
                    "requestContext": "launch",
                }
            if extra_variables:
                variables.update(extra_variables)
            if cursor:
                variables["cursor"] = cursor
            if use_post:
                data = self._graphql_post(operation_name, variables, FEATURES)
            else:
                data = self._graphql_get(operation_name, variables, FEATURES, field_toggles=field_toggles)
            new_tweets, next_cursor = parse_timeline_response(data, get_instructions)
            added_tweets = 0
            for tweet in new_tweets:
                if tweet.id and tweet.id not in seen_ids:
                    seen_ids.add(tweet.id)
                    tweets.append(tweet)
                    added_tweets += 1
            if new_tweets and added_tweets == 0:
                continuation_cursor = None
                break
            if not next_cursor:
                continuation_cursor = None
                break
            if next_cursor == cursor:
                continuation_cursor = None
                break
            continuation_cursor = next_cursor
            cursor = next_cursor
            if len(tweets) < count and self._request_delay > 0:
                time.sleep(self._request_delay * random.uniform(0.7, 1.5))
        if return_cursor:
            return tweets[:count], continuation_cursor
        return tweets[:count]

    def _fetch_user_list(self, operation_name, user_id, count, get_instructions, use_post=False):
        # type: (str, str, int, Callable[[Any], Any], bool) -> List[UserProfile]
        if count <= 0:
            return []
        count = min(count, self._max_count)
        users = []  # type: List[UserProfile]
        seen_ids = set()  # type: Set[str]
        cursor = None  # type: Optional[str]
        attempts = 0
        max_attempts = int(math.ceil(count / 20.0)) + 2
        while len(users) < count and attempts < max_attempts:
            attempts += 1
            variables = {
                "userId": user_id,
                "count": min(count - len(users) + 5, 40),
                "includePromotedContent": False,
            }  # type: Dict[str, Any]
            if cursor:
                variables["cursor"] = cursor
            if use_post:
                data = self._graphql_post(operation_name, variables, FEATURES)
            else:
                data = self._graphql_get(operation_name, variables, FEATURES)
            instructions = get_instructions(data)
            if not instructions:
                break
            new_users = []  # type: List[UserProfile]
            next_cursor = None  # type: Optional[str]
            for instruction in instructions:
                for entry in instruction.get("entries", []):
                    content = entry.get("content", {})
                    entry_type = content.get("entryType", "")
                    if entry_type == "TimelineTimelineItem":
                        item = content.get("itemContent", {})
                        user_results = _deep_get(item, "user_results", "result")
                        if user_results:
                            user = parse_user_result(user_results)
                            if user:
                                new_users.append(user)
                    elif entry_type == "TimelineTimelineCursor":
                        if content.get("cursorType") == "Bottom":
                            next_cursor = content.get("value")
            added_users = 0
            for user in new_users:
                if user.id and user.id not in seen_ids:
                    seen_ids.add(user.id)
                    users.append(user)
                    added_users += 1
            if not next_cursor or next_cursor == cursor or not new_users or added_users == 0:
                break
            cursor = next_cursor
            if len(users) < count and self._request_delay > 0:
                time.sleep(self._request_delay * random.uniform(0.7, 1.5))
        return users[:count]

    # ── Internal: GraphQL request methods ────────────────────────────

    def _graphql_get(self, operation_name, variables, features, field_toggles=None):
        # type: (str, Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]) -> Dict[str, Any]
        query_id = _resolve_query_id(operation_name, prefer_fallback=True, url_fetch_fn=_url_fetch)
        using_fallback = query_id == FALLBACK_QUERY_IDS.get(operation_name)
        url = _build_graphql_url(query_id, operation_name, variables, features, field_toggles)
        try:
            return self._api_get(url)
        except TwitterAPIError as exc:
            if exc.status_code in (404, 422) and using_fallback:
                logger.info("Retrying %s with live queryId after %d", operation_name, exc.status_code)
                _invalidate_query_id(operation_name)
                refreshed = _resolve_query_id(operation_name, prefer_fallback=False, url_fetch_fn=_url_fetch)
                retry_url = _build_graphql_url(refreshed, operation_name, variables, features, field_toggles)
                return self._api_get(retry_url)
            raise

    def _graphql_post(self, operation_name, variables, features=None, allow_bundle_scan=True):
        # type: (str, Dict[str, Any], Optional[Dict[str, Any]], bool) -> Dict[str, Any]
        query_id = _resolve_query_id(
            operation_name, prefer_fallback=True, url_fetch_fn=_url_fetch, allow_bundle_scan=allow_bundle_scan,
        )
        using_fallback = query_id == FALLBACK_QUERY_IDS.get(operation_name)

        def _do_post(qid):
            url = "https://x.com/i/api/graphql/%s/%s" % (qid, operation_name)
            body = {"variables": variables, "queryId": qid}  # type: Dict[str, Any]
            if features:
                body["features"] = features
            return self._api_request(url, method="POST", body=body)

        try:
            return _do_post(query_id)
        except TwitterAPIError as exc:
            if exc.status_code in (404, 422) and using_fallback:
                _invalidate_query_id(operation_name)
                refreshed = _resolve_query_id(
                    operation_name,
                    prefer_fallback=False,
                    url_fetch_fn=_url_fetch,
                    allow_bundle_scan=allow_bundle_scan,
                )
                if refreshed == query_id:
                    raise
                return _do_post(refreshed)
            raise

    def _api_get(self, url):
        # type: (str) -> Dict[str, Any]
        return self._api_request(url, method="GET")

    def _api_request(self, url, method="GET", body=None):
        # type: (str, str, Optional[Dict[str, Any]]) -> Dict[str, Any]
        headers = self._build_headers(url=url, method=method)
        session = _get_cffi_session()
        for attempt in range(self._max_retries + 1):
            try:
                if method == "POST":
                    response = session.post(url, headers=headers, json=body, timeout=30)
                else:
                    response = session.get(url, headers=headers, timeout=30)
                status_code = response.status_code
                if status_code == 429 and attempt < self._max_retries:
                    wait = self._retry_base_delay * (2 ** attempt) + random.uniform(0, 2)
                    logger.warning("Rate limited (429), retrying in %.1fs", wait)
                    time.sleep(wait)
                    continue
                if status_code >= 400:
                    raise TwitterAPIError(status_code, "Twitter API error %d: %s" % (status_code, response.text[:500]))
                payload = response.text
            except TwitterAPIError:
                raise
            except Exception as exc:
                raise TwitterAPIError(0, "Twitter API network error: %s" % exc)
            try:
                parsed = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                raise TwitterAPIError(0, "Twitter API returned invalid JSON")
            if isinstance(parsed, dict) and parsed.get("errors"):
                err_msg = parsed["errors"][0].get("message", "Unknown error")
                err_code = parsed["errors"][0].get("code", 0)
                if err_code == 88 and attempt < self._max_retries:
                    wait = self._retry_base_delay * (2 ** attempt) + random.uniform(0, 2)
                    logger.warning("Rate limited (code 88), retrying in %.1fs", wait)
                    time.sleep(wait)
                    continue
                if err_code in (348, 349):
                    raise TwitterAPIError(429, "Rate limited: %s" % err_msg)
                raise TwitterAPIError(0, "Twitter API returned errors: %s" % err_msg)
            if isinstance(parsed, dict) and "data" in parsed:
                data_obj = parsed["data"]
                if isinstance(data_obj, dict):
                    for key, val in data_obj.items():
                        if isinstance(val, dict) and val.get("errors"):
                            inner_errors = val["errors"]
                            if inner_errors:
                                inner_msg = inner_errors[0].get("message", "Unknown error")
                                raise TwitterAPIError(0, "Twitter API: %s" % inner_msg)
            return parsed
        raise TwitterAPIError(429, "Rate limited after %d retries" % self._max_retries)

    # ── Internal: Anti-detection / headers ───────────────────────────

    @staticmethod
    def _ct_cache_path():
        # type: () -> str
        from . import paths
        return str(paths.transaction_cache_path())

    def _load_ct_cache(self):
        # type: () -> bool
        try:
            cache_path = self._ct_cache_path()
            if not os.path.exists(cache_path):
                return False
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if time.time() - cache.get("created_at", 0) > 3600:
                return False
            home_html = cache.get("home_html", "")
            ondemand_text = cache.get("ondemand_text", "")
            if not home_html or not ondemand_text:
                return False
            home_page_response = bs4.BeautifulSoup(home_html, "html.parser")
            self._client_transaction = ClientTransaction(
                home_page_response=home_page_response,
                ondemand_file_response=ondemand_text,
            )
            _update_features_from_html(home_html)
            return True
        except Exception as exc:
            logger.debug("Failed to load CT cache: %s", exc)
            return False

    def _save_ct_cache(self, home_html, ondemand_text):
        # type: (str, str) -> None
        try:
            cache_path = self._ct_cache_path()
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            fd = os.open(cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"home_html": home_html, "ondemand_text": ondemand_text, "created_at": time.time()}, f)
        except Exception as exc:
            logger.debug("Failed to save CT cache: %s", exc)

    def _ensure_client_transaction(self):
        # type: () -> None
        if self._ct_init_attempted:
            return
        self._ct_init_attempted = True
        if self._load_ct_cache():
            return
        try:
            cffi_session = _get_cffi_session()
            ct_headers = _gen_ct_headers()
            home_page = cffi_session.get("https://x.com", headers=ct_headers, timeout=10)
            home_page_response = bs4.BeautifulSoup(home_page.content, "html.parser")
            ondemand_url = get_ondemand_file_url(response=home_page_response)
            if not ondemand_url:
                raise ValueError("Failed to extract ondemand file URL")
            ondemand_file = cffi_session.get(ondemand_url, headers=ct_headers, timeout=10)
            self._client_transaction = ClientTransaction(
                home_page_response=home_page_response,
                ondemand_file_response=ondemand_file.text,
            )
            _update_features_from_html(home_page.text)
            self._save_ct_cache(home_page.text, ondemand_file.text)
        except Exception as exc:
            logger.warning("Failed to init ClientTransaction: %s", exc)

    def _build_headers(self, url="", method="GET"):
        # type: (str, str) -> Dict[str, str]
        headers = {
            "Authorization": "Bearer %s" % BEARER_TOKEN,
            "Cookie": self._cookie_string or "auth_token=%s; ct0=%s" % (self._auth_token, self._ct0),
            "X-Csrf-Token": self._ct0,
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Auth-Type": "OAuth2Session",
            "X-Twitter-Client-Language": get_twitter_client_language(),
            "User-Agent": get_user_agent(),
            "Origin": "https://x.com",
            "Referer": "https://x.com/",
            "Accept": "*/*",
            "Accept-Language": get_accept_language(),
            "sec-ch-ua": get_sec_ch_ua(),
            "sec-ch-ua-mobile": SEC_CH_UA_MOBILE,
            "sec-ch-ua-platform": get_sec_ch_ua_platform(),
            "sec-ch-ua-arch": get_sec_ch_ua_arch(),
            "sec-ch-ua-bitness": SEC_CH_UA_BITNESS,
            "sec-ch-ua-full-version": get_sec_ch_ua_full_version(),
            "sec-ch-ua-full-version-list": get_sec_ch_ua_full_version_list(),
            "sec-ch-ua-model": SEC_CH_UA_MODEL,
            "sec-ch-ua-platform-version": get_sec_ch_ua_platform_version(),
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
            headers["Referer"] = "https://x.com/compose/post"
            headers["Priority"] = "u=1, i"
        if self._client_transaction and url:
            try:
                path = urllib.parse.urlparse(url).path
                tid = self._client_transaction.generate_transaction_id(method=method, path=path)
                headers["X-Client-Transaction-Id"] = tid
            except Exception as exc:
                logger.debug("Failed to generate transaction id: %s", exc)
        return headers
