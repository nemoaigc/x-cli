"""Shared timeline fetch + serialise logic — used by feed / list / user.

Encapsulates:
  • the optional "mix gate" page-and-filter loop (--min-articles/--min-posts
    with per-kind metric thresholds), originally `_fetch_timeline_mix` in
    `scripts/read.py`;
  • article-expansion (replace article-tweets with the full body), originally
    `_expand_articles`;
  • per-tweet serialisation including the synthesized `content_kind` field;
  • the optional you_follow_author annotation when a profile is set.

Public surface:
  • `TimelineOpts` — dataclass of every flag a timeline command needs
  • `add_timeline_options(...)` — typer-style helper (unused for now; commands
    pass each flag explicitly so help text stays scoped per command)
  • `emit_timeline(client, fetch_page, opts, use_yaml)` — drive the fetch loop
    and emit the JSON envelope. `fetch_page` is `(count, cursor, return_cursor)
    → (tweets, cursor)` if mix gates active, otherwise `(count=N) → tweets`.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from x_cli.core import following_cache
from x_cli.core.output import emit_ok


@dataclass
class TimelineOpts:
    """Every flag a timeline-emitting command consumes."""
    top: int = 30                          # --top: results per page / cap
    expand_articles: bool = False          # --expand-articles
    # Mix gates (any of these triggers the multi-page mix loop):
    min_articles: int = 0                  # --min-articles
    min_posts: int = 0                     # --min-posts
    max_pages: int = 5                     # --max-pages
    article_likes: int | None = None       # --min-article-likes
    article_retweets: int | None = None    # --min-article-retweets
    article_bookmarks: int | None = None   # --min-article-bookmarks
    post_likes: int | None = None          # --min-post-likes
    post_retweets: int | None = None       # --min-post-retweets
    post_bookmarks: int | None = None      # --min-post-bookmarks

    @property
    def has_mix_gates(self) -> bool:
        return bool(self.min_articles or self.min_posts)


# ───────────────────────── per-tweet helpers ──────────────────────────


def _content_kind(tweet: Any) -> str:
    if getattr(tweet, "is_article", False):
        return "article"
    if getattr(tweet, "is_note_tweet", False):
        return "note_tweet"
    return "tweet"


def _tweet_to_dict(tweet: Any) -> dict[str, Any]:
    if not dataclasses.is_dataclass(tweet) or isinstance(tweet, type):
        return tweet
    data = dataclasses.asdict(tweet)
    data["content_kind"] = _content_kind(tweet)
    return data


def _expand_articles(tweets: list[Any], client: Any) -> list[Any]:
    out: list[Any] = []
    for tweet in tweets:
        if not getattr(tweet, "is_article", False):
            out.append(tweet)
            continue
        try:
            out.append(client.fetch_article(tweet.id))
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "Article expansion skipped for %s: %s", tweet.id, exc,
            )
            out.append(tweet)
    return out


# ───────────────────────── mix-gate paging ────────────────────────────


def _metric_value(tweet: Any, name: str) -> int:
    metrics = getattr(tweet, "metrics", None)
    return getattr(metrics, name, 0) if metrics is not None else 0


def _passes_any_threshold(tweet: Any, thresholds: dict[str, int | None]) -> bool:
    active = [(k, v) for k, v in thresholds.items() if v is not None]
    if not active:
        return True
    return any(_metric_value(tweet, k) >= v for k, v in active)


def _passes_mix_threshold(tweet, article_t, post_t) -> bool:
    if _content_kind(tweet) == "article":
        return _passes_any_threshold(tweet, article_t)
    return _passes_any_threshold(tweet, post_t)


def _count_mix(tweets) -> tuple[int, int]:
    articles = sum(1 for t in tweets if _content_kind(t) == "article")
    posts = len(tweets) - articles
    return articles, posts


def _needs_more_mix(tweets, min_articles, min_posts) -> bool:
    a, p = _count_mix(tweets)
    return a < min_articles or p < min_posts


def _select_mix(tweets, min_articles, min_posts):
    selected_ids: set[str] = set()
    article_count = 0
    post_count = 0
    for t in tweets:
        kind = _content_kind(t)
        if kind == "article" and article_count < min_articles:
            selected_ids.add(t.id)
            article_count += 1
        elif kind != "article" and post_count < min_posts:
            selected_ids.add(t.id)
            post_count += 1
    return [t for t in tweets if t.id in selected_ids]


def _fetch_timeline_mix(
    fetch_page: Callable,
    *,
    page_size: int,
    min_articles: int,
    min_posts: int,
    max_pages: int,
    article_thresholds: dict[str, int | None],
    post_thresholds: dict[str, int | None],
) -> list[Any]:
    tweets: list[Any] = []
    seen: set[str] = set()
    cursor = None
    pages = 0

    while pages < max_pages and _needs_more_mix(tweets, min_articles, min_posts):
        page, cursor = fetch_page(count=page_size, cursor=cursor, return_cursor=True)
        pages += 1
        added = 0
        for tw in page:
            if tw.id and tw.id not in seen:
                seen.add(tw.id)
                if _passes_mix_threshold(tw, article_thresholds, post_thresholds):
                    tweets.append(tw)
                added += 1
        if not cursor or added == 0:
            break

    return _select_mix(tweets, min_articles, min_posts)


# ───────────────────────── follow annotation ──────────────────────────


def _annotate(tweets, client, profile_name) -> None:
    """Mutates each tweet in-place: sets `you_follow_author`."""
    try:
        ids = following_cache.load_cached(profile_name)
        if ids is None:
            me = client.fetch_me()
            ids = client.fetch_all_following_ids(me.id)
            following_cache.save_cache(profile_name, ids)
        following_cache.annotate_tweets(tweets, ids)
    except Exception as exc:
        logging.getLogger(__name__).debug("Follow annotation skipped: %s", exc)


# ───────────────────────── public entry ───────────────────────────────


def emit_timeline(
    client: Any,
    fetch_page: Callable,
    opts: TimelineOpts,
    *,
    use_yaml: bool = False,
    profile_name: str | None = None,
) -> None:
    """Drive a timeline fetch + emit JSON envelope.

    `fetch_page` shape:
      - Mix gates active: callable(count, cursor, return_cursor) → (tweets, cursor)
      - Otherwise:        callable(count=N) → list[tweets]
    """
    if opts.has_mix_gates:
        tweets = _fetch_timeline_mix(
            fetch_page,
            page_size=opts.top,
            min_articles=opts.min_articles,
            min_posts=opts.min_posts,
            max_pages=opts.max_pages,
            article_thresholds={
                "likes": opts.article_likes,
                "retweets": opts.article_retweets,
                "bookmarks": opts.article_bookmarks,
            },
            post_thresholds={
                "likes": opts.post_likes,
                "retweets": opts.post_retweets,
                "bookmarks": opts.post_bookmarks,
            },
        )
    else:
        tweets = fetch_page(count=opts.top)

    if opts.expand_articles:
        tweets = _expand_articles(tweets, client)
    if profile_name and tweets:
        _annotate(tweets, client, profile_name)

    emit_ok([_tweet_to_dict(t) for t in tweets], use_yaml)
