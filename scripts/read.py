#!/usr/bin/env python3
"""read.py — read-mode entry point for x-cli.

Reads tweets from X's various surfaces and emits JSON/YAML.

Usage examples:
  uv run scripts/read.py --query "claude code" --since 2026-04-15 --until 2026-04-18 --top 30
  uv run scripts/read.py --user elonmusk --top 20
  uv run scripts/read.py --user-likes karpathy --top 20
  uv run scripts/read.py --user-articles outsource_
  uv run scripts/read.py --tweet 1234567890
  uv run scripts/read.py --batch 111 222 333
  uv run scripts/read.py --feed for-you
  uv run scripts/read.py --feed AI --top 50
  uv run scripts/read.py --feeds
  uv run scripts/read.py --recommended-users karpathy --top 10
  uv run scripts/read.py --recommended-users --top 20
"""

from __future__ import annotations

import argparse
import sys
import os

# Allow running as `uv run scripts/research.py` from skill root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._core.output import add_common_args, build_client, emit_error, emit_ok, setup_logging
from scripts._core.output import (
    normalize_handle_arg,
    normalize_numeric_id_arg,
    normalize_required_text,
    require_positive_int,
)
from scripts._core.search import build_search_query, _normalize_tweet_id
from scripts._core.exceptions import XQueryError
from scripts._core.exceptions import InvalidInputError
from scripts._core import following_cache


# Populated in main() so _tweet_list_to_dicts can auto-annotate.
_annotation_client = None  # type: ignore
_annotation_profile = None  # type: ignore


def _annotate_follow(tweets, client, profile):
    """In-place set you_follow_author on each tweet using cached following list."""
    try:
        ids = following_cache.load_cached(profile)
        if ids is None:
            me = client.fetch_me()
            ids = client.fetch_all_following_ids(me.id)
            following_cache.save_cache(profile, ids)
        following_cache.annotate_tweets(tweets, ids)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("Follow annotation skipped: %s", exc)


def _tweet_list_to_dicts(tweets):
    if _annotation_client is not None and tweets:
        _annotate_follow(tweets, _annotation_client, _annotation_profile)
    return [_tweet_to_dict(t) for t in tweets]


def _content_kind(tweet):
    if getattr(tweet, "is_article", False):
        return "article"
    if getattr(tweet, "is_note_tweet", False):
        return "note_tweet"
    return "tweet"


def _tweet_to_dict(tweet):
    import dataclasses
    data = dataclasses.asdict(tweet)
    data["content_kind"] = _content_kind(tweet)
    return data


def _expand_articles(tweets, client):
    expanded = []
    for tweet in tweets:
        if not getattr(tweet, "is_article", False):
            expanded.append(tweet)
            continue
        try:
            expanded.append(client.fetch_article(tweet.id))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug("Article expansion skipped for %s: %s", tweet.id, exc)
            expanded.append(tweet)
    return expanded


def _count_mix(tweets):
    articles = sum(1 for tweet in tweets if _content_kind(tweet) == "article")
    posts = sum(1 for tweet in tweets if _content_kind(tweet) != "article")
    return articles, posts


def _needs_more_mix(tweets, min_articles, min_posts):
    articles, posts = _count_mix(tweets)
    return articles < min_articles or posts < min_posts


def _metric_value(tweet, name):
    metrics = getattr(tweet, "metrics", None)
    return getattr(metrics, name, 0) if metrics is not None else 0


def _passes_any_threshold(tweet, thresholds):
    active = [(name, value) for name, value in thresholds.items() if value is not None]
    if not active:
        return True
    return any(_metric_value(tweet, name) >= value for name, value in active)


def _passes_mix_threshold(tweet, article_thresholds, post_thresholds):
    if _content_kind(tweet) == "article":
        return _passes_any_threshold(tweet, article_thresholds)
    return _passes_any_threshold(tweet, post_thresholds)


def _fetch_timeline_mix(
    fetch_page,
    page_size,
    min_articles,
    min_posts,
    max_pages,
    article_thresholds,
    post_thresholds,
):
    tweets = []
    seen_ids = set()
    cursor = None
    pages = 0

    while pages < max_pages and _needs_more_mix(tweets, min_articles, min_posts):
        page, cursor = fetch_page(count=page_size, cursor=cursor, return_cursor=True)
        pages += 1
        added = 0
        for tweet in page:
            if tweet.id and tweet.id not in seen_ids:
                seen_ids.add(tweet.id)
                if _passes_mix_threshold(tweet, article_thresholds, post_thresholds):
                    tweets.append(tweet)
                added += 1
        if not cursor or added == 0:
            break

    return _select_mix(tweets, min_articles, min_posts)


def _select_mix(tweets, min_articles, min_posts):
    selected_ids = set()
    selected = []
    article_count = 0
    post_count = 0

    for tweet in tweets:
        if _content_kind(tweet) == "article" and article_count < min_articles:
            selected_ids.add(tweet.id)
            selected.append(tweet)
            article_count += 1
        elif _content_kind(tweet) != "article" and post_count < min_posts:
            selected_ids.add(tweet.id)
            selected.append(tweet)
            post_count += 1

    # Preserve the original timeline order after selecting category quotas.
    return [tweet for tweet in tweets if tweet.id in selected_ids]


def _emit_tweets(tweets, args, client):
    if args.expand_articles:
        tweets = _expand_articles(tweets, client)
    emit_ok(_tweet_list_to_dicts(tweets), args.yaml)


def _emit_timeline(fetch_page, args, client):
    if args.min_articles or args.min_posts:
        tweets = _fetch_timeline_mix(
            fetch_page,
            page_size=args.top,
            min_articles=args.min_articles,
            min_posts=args.min_posts,
            max_pages=args.max_pages,
            article_thresholds={
                "likes": args.min_article_likes,
                "retweets": args.min_article_retweets,
                "bookmarks": args.min_article_bookmarks,
            },
            post_thresholds={
                "likes": args.min_post_likes,
                "retweets": args.min_post_retweets,
                "bookmarks": args.min_post_bookmarks,
            },
        )
    else:
        tweets = fetch_page(count=args.top)
    _emit_tweets(tweets, args, client)


def _user_list_to_dicts(users):
    import dataclasses
    return [dataclasses.asdict(u) for u in users]


def main():
    parser = argparse.ArgumentParser(
        description="x-query research mode — read tweets and user data from X/Twitter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_args(parser)

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query", metavar="Q", help="Search query (advanced search operators supported)")
    mode.add_argument("--feed", metavar="NAME",
                      help='Home timeline feed: "for-you", "following", or a custom timeline name (e.g. "AI")')
    mode.add_argument("--feeds", action="store_true",
                      help="List all pinned (custom) timelines for this account")
    mode.add_argument("--user", metavar="HANDLE", help="User's recent tweets")
    mode.add_argument("--user-likes", metavar="HANDLE",
                      help="User's liked tweets (may be empty — X made likes private by default)")
    mode.add_argument("--user-articles", metavar="HANDLE", help="User's Articles tab")
    mode.add_argument("--user-replies", metavar="HANDLE", help="User's Posts+Replies tab")
    mode.add_argument("--user-media", metavar="HANDLE", help="User's Media tab")
    mode.add_argument("--user-highlights", metavar="HANDLE", help="User's Highlights tab")
    mode.add_argument("--search-users", metavar="Q", help="Search users (People tab)")
    mode.add_argument("--tweet", metavar="ID_OR_URL", help="Single tweet + thread")
    mode.add_argument("--article", metavar="ID_OR_URL", help="Twitter Article by tweet ID")
    mode.add_argument("--batch", metavar="ID", nargs="+", help="Batch-fetch multiple tweet IDs")
    mode.add_argument("--followers", metavar="HANDLE", help="Followers of a user")
    mode.add_argument("--following", metavar="HANDLE", help="Users that HANDLE is following")
    mode.add_argument("--list", metavar="LIST_ID", help="X List timeline")
    mode.add_argument("--recommended-users", nargs="?", const="__general__", metavar="HANDLE",
                      help="Recommended/similar users (Connect tab). Pass a HANDLE for similar accounts, omit for general suggestions.")

    # Search options
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="Start date for --query")
    parser.add_argument("--until", metavar="YYYY-MM-DD", help="End date for --query")
    parser.add_argument("--lang", metavar="CODE", help="Language filter (e.g. en, zh)")
    parser.add_argument("--from-user", metavar="HANDLE", help="Only tweets from this user")
    parser.add_argument("--min-likes", type=int, metavar="N", help="Minimum likes for --query")
    parser.add_argument("--min-retweets", type=int, metavar="N", help="Minimum retweets for --query")
    parser.add_argument("--product", choices=["Top", "Latest"], default="Top",
                        help="Search tab (default: Top)")

    # Output options
    parser.add_argument("--top", type=int, default=30, metavar="N", help="Max results per window (default: 30)")
    parser.add_argument(
        "--auto-window", action="store_true",
        help="Adaptively split [--since, --until] into sub-windows when results saturate, "
             "deduplicate, and merge. For long ranges on hot topics. Implies --since defaults "
             "to 90 days ago if unset.",
    )
    parser.add_argument(
        "--expand-articles",
        action="store_true",
        help="Fetch full article content for article tweets in list outputs.",
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=0,
        metavar="N",
        help="For timeline feeds, keep paging until at least N Article items are collected.",
    )
    parser.add_argument(
        "--min-posts",
        type=int,
        default=0,
        metavar="N",
        help="For timeline feeds, keep paging until at least N non-Article post items are collected.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        metavar="N",
        help="Maximum timeline pages to scan for --min-articles/--min-posts (default: 5).",
    )
    parser.add_argument("--min-article-likes", type=int, metavar="N", help="Timeline mix gate: Article likes threshold.")
    parser.add_argument("--min-article-retweets", type=int, metavar="N", help="Timeline mix gate: Article retweets threshold.")
    parser.add_argument("--min-article-bookmarks", type=int, metavar="N", help="Timeline mix gate: Article bookmarks threshold.")
    parser.add_argument("--min-post-likes", type=int, metavar="N", help="Timeline mix gate: non-Article post likes threshold.")
    parser.add_argument("--min-post-retweets", type=int, metavar="N", help="Timeline mix gate: non-Article post retweets threshold.")
    parser.add_argument("--min-post-bookmarks", type=int, metavar="N", help="Timeline mix gate: non-Article post bookmarks threshold.")

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        require_positive_int("--top", args.top)
        if args.min_articles < 0:
            raise InvalidInputError("--min-articles must be >= 0")
        if args.min_posts < 0:
            raise InvalidInputError("--min-posts must be >= 0")
        require_positive_int("--max-pages", args.max_pages)
        for flag_name in (
            "min_article_likes",
            "min_article_retweets",
            "min_article_bookmarks",
            "min_post_likes",
            "min_post_retweets",
            "min_post_bookmarks",
        ):
            value = getattr(args, flag_name)
            if value is not None and value < 0:
                raise InvalidInputError("--%s must be >= 0" % flag_name.replace("_", "-"))
        args.query = normalize_required_text("--query", args.query) if args.query is not None else None
        args.search_users = (
            normalize_required_text("--search-users", args.search_users)
            if args.search_users is not None else None
        )
        args.from_user = normalize_handle_arg("--from-user", args.from_user)
        args.user = normalize_handle_arg("--user", args.user)
        args.user_likes = normalize_handle_arg("--user-likes", args.user_likes)
        args.user_articles = normalize_handle_arg("--user-articles", args.user_articles)
        args.user_replies = normalize_handle_arg("--user-replies", args.user_replies)
        args.user_media = normalize_handle_arg("--user-media", args.user_media)
        args.user_highlights = normalize_handle_arg("--user-highlights", args.user_highlights)
        args.followers = normalize_handle_arg("--followers", args.followers)
        args.following = normalize_handle_arg("--following", args.following)
        if args.recommended_users and args.recommended_users != "__general__":
            args.recommended_users = normalize_handle_arg("--recommended-users", args.recommended_users)
        args.list = normalize_numeric_id_arg("--list", args.list)
        client = build_client(args.profile)
        global _annotation_client, _annotation_profile
        _annotation_client = client
        _annotation_profile = args.profile
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("startup_error", str(exc), args.yaml)
        sys.exit(1)

    try:
        if args.query:
            if args.auto_window:
                from scripts._core.window import adaptive_search, derive_since_until
                since, until = derive_since_until(args.since, args.until)
                base_q = build_search_query(
                    args.query,
                    lang=args.lang,
                    from_user=args.from_user,
                    min_likes=args.min_likes,
                    min_retweets=args.min_retweets,
                )
                tweets = adaptive_search(
                    base_q, since, until, args.top,
                    fetcher=lambda q, n: client.fetch_search(q, count=n, product=args.product),
                )
            else:
                q = build_search_query(
                    args.query,
                    lang=args.lang,
                    since=args.since,
                    until=args.until,
                    from_user=args.from_user,
                    min_likes=args.min_likes,
                    min_retweets=args.min_retweets,
                )
                tweets = client.fetch_search(q, count=args.top, product=args.product)
            _emit_tweets(tweets, args, client)

        elif args.feeds:
            pinned = client.fetch_pinned_timelines()
            emit_ok(pinned, args.yaml)

        elif args.feed:
            feed_lower = args.feed.lower()
            if feed_lower == "for-you":
                fetch_page = client.fetch_home_timeline
            elif feed_lower == "following":
                fetch_page = client.fetch_following_feed
            else:
                # Custom (pinned) timeline — resolve name → tag ID dynamically
                pinned = client.fetch_pinned_timelines()
                match = next(
                    (p for p in pinned if p["tab_label"].lower() == feed_lower
                     or p["name"].lower() == feed_lower),
                    None,
                )
                if match is None:
                    available = ", ".join(
                        f'"{p["tab_label"]}"' for p in pinned
                    ) or "(none)"
                    emit_error(
                        "unknown_feed",
                        f'Unknown feed "{args.feed}". Available custom timelines: {available}',
                        args.yaml,
                    )
                    sys.exit(1)
                fetch_page = lambda count, cursor=None, return_cursor=False: client.fetch_custom_timeline(
                    match["tag"], count=count, cursor=cursor, return_cursor=return_cursor
                )
            _emit_timeline(fetch_page, args, client)

        elif args.user:
            user_id = client.resolve_user_id(args.user)
            tweets = client.fetch_user_tweets(user_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.user_likes:
            user_id = client.resolve_user_id(args.user_likes)
            tweets = client.fetch_user_likes(user_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.user_articles:
            user_id = client.resolve_user_id(args.user_articles)
            tweets = client.fetch_user_articles(user_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.user_replies:
            user_id = client.resolve_user_id(args.user_replies)
            tweets = client.fetch_user_replies(user_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.user_media:
            user_id = client.resolve_user_id(args.user_media)
            tweets = client.fetch_user_media(user_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.user_highlights:
            user_id = client.resolve_user_id(args.user_highlights)
            tweets = client.fetch_user_highlights(user_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.search_users:
            users = client.search_users(args.search_users, count=args.top)
            emit_ok(_user_list_to_dicts(users), args.yaml)

        elif args.tweet:
            tweet_id = _normalize_tweet_id(args.tweet)
            tweets = client.fetch_tweet_detail(tweet_id, count=args.top)
            _emit_tweets(tweets, args, client)

        elif args.article:
            tweet_id = _normalize_tweet_id(args.article)
            tweet = client.fetch_article(tweet_id)
            emit_ok(_tweet_to_dict(tweet), args.yaml)

        elif args.batch:
            ids = [_normalize_tweet_id(x) for x in args.batch]
            tweets = client.fetch_tweets_by_ids(ids)
            _emit_tweets(tweets, args, client)

        elif args.followers:
            user_id = client.resolve_user_id(args.followers)
            users = client.fetch_followers(user_id, count=args.top)
            emit_ok(_user_list_to_dicts(users), args.yaml)

        elif args.following:
            user_id = client.resolve_user_id(args.following)
            users = client.fetch_following(user_id, count=args.top)
            emit_ok(_user_list_to_dicts(users), args.yaml)

        elif args.recommended_users:
            user_id = None
            if args.recommended_users != "__general__":
                user_id = client.resolve_user_id(args.recommended_users)
            users = client.fetch_recommended_users(user_id=user_id, count=args.top)
            emit_ok(_user_list_to_dicts(users), args.yaml)

        elif args.list:
            tweets = client.fetch_list_timeline(args.list, count=args.top)
            _emit_tweets(tweets, args, client)

    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("unexpected_error", str(exc), args.yaml)
        sys.exit(1)


if __name__ == "__main__":
    main()
