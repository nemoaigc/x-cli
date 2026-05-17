"""Post-processing primitives for x-cli read operations.

This module is **configuration-free** by design:
- No hardcoded spam templates, no hardcoded language defaults, no hardcoded
  scoring weights.
- Every filter/scorer requires the caller to pass the values it should use.

This forces the caller (usually an LLM) to **derive values per-domain**:
what counts as spam for crypto is not what counts for AI research; what
"high engagement" means for F1 is different from for a niche research
community; ranking weights depend on what the briefing is optimizing for.

The catalogs of example patterns (spam templates, language sets, weights)
live in `references/spam-patterns.md` and `references/search-plan.md` so
the LLM reads and adapts them, rather than importing a one-size-fits-all
default from code.

Usage (the caller composes explicitly) — see read-mode.md / search-plan.md
for full examples. Minimal shape::

    from scripts._core import rank
    langs          = {"en", "zh"}
    spam_patterns  = [...]   # pick from references/spam-patterns.md
    weights        = {...}   # pick from references/ranking-weights.md
    boosts         = {...}
    clean = rank.filter_stack(tweets, allowed_langs=langs,
                              spam_patterns=spam_patterns, drop_promoted=True)
    score_fn = lambda t: rank.score(t, weights=weights, boosts=boosts)
    top = rank.author_diversity(clean, score_fn=score_fn, decay=0.7, floor=0.3)[:20]
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


# ── Language filter ──────────────────────────────────────────────────────────

def lang_of(tweet: Dict[str, Any]) -> str:
    """Normalized ISO 639-1 language tag; 'und' if missing."""
    raw = (tweet.get("lang") or "").split("-")[0].lower()
    return raw or "und"


def filter_lang(tweets: Iterable[Dict[str, Any]],
                allowed: Set[str],
                include_und: bool = True) -> List[Dict[str, Any]]:
    """Keep tweets whose lang is in `allowed`. Required param — no default.

    `include_und` keeps tweets X failed to tag so a detection miss doesn't
    silently drop real content.
    """
    return [t for t in tweets
            if lang_of(t) in allowed or (include_und and lang_of(t) == "und")]


# ── Spam detection (caller supplies patterns) ────────────────────────────────

def is_template_spam(text: str, patterns: List[str]) -> bool:
    """True if text matches any regex in `patterns` (case-insensitive).

    Patterns are REQUIRED — this module does not ship defaults. Pull from
    `references/spam-patterns.md` by domain (or write your own per-domain
    set). Pass `[]` to disable template matching entirely.
    """
    if not text or not patterns:
        return False
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def is_low_engagement_ratio(metrics: Dict[str, Any],
                            *,
                            min_views_for_like_check: int,
                            min_like_to_view: float,
                            min_likes_for_reply_check: int,
                            min_reply_to_like: float) -> bool:
    """Detect engagement anomalies (paid promo / viral stunt). All thresholds required.

    Domains differ wildly:
      AI / politics / crypto:  views can exceed 1M → threshold 100K is fine
      Mid-tier fandoms:        viral = 500–2K likes → threshold 1K too loose
      Niche academic:          top tweets have 20–200 likes → these checks can't fire
    Caller picks thresholds per-domain.

    Returns True if:
      - views >= min_views_for_like_check AND likes/views < min_like_to_view
        (paid-promo pattern: lots of impressions, barely any real reactions)
      - likes >= min_likes_for_reply_check AND replies/likes < min_reply_to_like
        (viral stunt: likes farm but no real conversation)
    """
    likes = metrics.get("likes", 0) or 0
    views = metrics.get("views", 0) or 0
    replies = metrics.get("replies", 0) or 0
    if views >= min_views_for_like_check and likes / max(views, 1) < min_like_to_view:
        return True
    if likes >= min_likes_for_reply_check and replies / max(likes, 1) < min_reply_to_like:
        return True
    return False


# Note: a `is_likely_spam(tweet, patterns)` combo helper was removed because it
# silently called is_low_engagement_ratio with default AI-sphere thresholds —
# violating the "caller composes" discipline. If you want both checks, call
# them yourself:
#
#   spam = (
#       is_template_spam(t.get("text") or "", patterns)
#       or is_low_engagement_ratio(t.get("metrics") or {},
#                                  min_views_for_like_check=<caller value>,
#                                  min_like_to_view=<caller value>, ...)
#   )


# ── Scoring (caller supplies weights + boosts) ───────────────────────────────

def engagement_score(metrics: Dict[str, Any], weights: Dict[str, float]) -> float:
    """Weighted engagement. `weights` keys: likes, retweets, replies, bookmarks, views_log.

    Missing keys default to 0 (i.e. that signal ignored). `views_log` applies
    to log(views+1) rather than raw views.
    """
    if not metrics:
        return 0.0
    return (
        weights.get("likes", 0) * metrics.get("likes", 0)
        + weights.get("retweets", 0) * metrics.get("retweets", 0)
        + weights.get("replies", 0) * metrics.get("replies", 0)
        + weights.get("bookmarks", 0) * metrics.get("bookmarks", 0)
        + weights.get("views_log", 0) * math.log(max(metrics.get("views", 0) or 1, 1))
    )


def apply_boosts(tweet: Dict[str, Any], base_score: float,
                 boosts: Dict[str, float]) -> float:
    """Multiplicative boosts. Caller supplies the multipliers.

    Recognized keys (all optional):
      you_follow_author: applied if tweet.you_follow_author is True
      is_article:        applied if tweet.is_article is True
      verified_not_followed: applied if author is verified AND not followed
                             (use <1.0 to demote blue-check outside trust net)
    """
    s = base_score
    if boosts.get("you_follow_author") and tweet.get("you_follow_author"):
        s *= boosts["you_follow_author"]
    if boosts.get("is_article") and tweet.get("is_article"):
        s *= boosts["is_article"]
    vnf = boosts.get("verified_not_followed")
    if vnf and tweet.get("author", {}).get("verified") and not tweet.get("you_follow_author"):
        s *= vnf
    return s


def score(tweet: Dict[str, Any], weights: Dict[str, float],
          boosts: Optional[Dict[str, float]] = None) -> float:
    """Full score: engagement_score + boosts. Weights REQUIRED; boosts optional."""
    s = engagement_score(tweet.get("metrics") or {}, weights)
    if boosts:
        s = apply_boosts(tweet, s, boosts)
    return s


# ── Ranking + diversity ──────────────────────────────────────────────────────

def rank_tweets(tweets: Iterable[Dict[str, Any]],
                score_fn: Callable[[Dict[str, Any]], float],
                ) -> List[Dict[str, Any]]:
    """Sort tweets by `score_fn` (desc). `score_fn` required."""
    return sorted(tweets, key=score_fn, reverse=True)


def author_diversity(tweets: Iterable[Dict[str, Any]],
                     score_fn: Callable[[Dict[str, Any]], float],
                     *,
                     decay: float,
                     floor: float,
                     ) -> List[Dict[str, Any]]:
    """Penalize repeated-author scores so top-N isn't dominated by one voice.

    Algorithm:
      1. Pre-sort by `score_fn` (desc) — the 1st tweet per author keeps full
         score; weaker tweets from the same author get penalized.
      2. For the Nth tweet of a given author, multiply score by
         `(1 - floor) * decay^N + floor`.
      3. Re-sort by adjusted score.

    Output: shallow copies of input tweets (no internal keys leaked).
    Borrowed from X's open-source AuthorDiversityScorer.
    """
    scored = [(score_fn(t), t) for t in tweets]
    scored.sort(key=lambda x: x[0], reverse=True)
    counts: Dict[str, int] = {}
    adjusted: List[Tuple[float, Dict[str, Any]]] = []
    for base_score, t in scored:
        aid = (t.get("author") or {}).get("id") or ""
        n = counts.get(aid, 0)
        mult = (1.0 - floor) * (decay ** n) + floor
        counts[aid] = n + 1
        adjusted.append((base_score * mult, dict(t)))
    adjusted.sort(key=lambda pair: pair[0], reverse=True)
    return [t_copy for _, t_copy in adjusted]


# ── Filter composition ───────────────────────────────────────────────────────

def filter_stack(
    tweets: Iterable[Dict[str, Any]],
    *,
    allowed_langs: Optional[Set[str]] = None,
    spam_patterns: Optional[List[str]] = None,
    engagement_thresholds: Optional[Dict[str, float]] = None,
    drop_promoted: bool = False,
    drop_retweets: bool = False,
) -> List[Dict[str, Any]]:
    """Compose the common filter pipeline. Every filter is opt-in via explicit args.

    `allowed_langs`:          if provided, keep only these (+ untagged) langs.
                              None/empty = no lang filter.
    `spam_patterns`:          regex list for template detection. None/empty = no match.
    `engagement_thresholds`:  dict with ALL four keys or None. If provided, drops tweets
                              that match is_low_engagement_ratio (paid-promo / viral-stunt
                              anomalies). Keys:
                                min_views_for_like_check
                                min_like_to_view
                                min_likes_for_reply_check
                                min_reply_to_like
                              None = skip this check (safe for domains with low view
                              counts where the check can't discriminate).
    `drop_promoted`:          drop is_promoted=True.
    `drop_retweets`:          drop is_retweet=True.

    All params are keyword-only so you can't pass them positionally and accidentally
    revive implicit defaults.
    """
    result = list(tweets)
    if allowed_langs:  # None or empty set → no lang filter (intentional: empty = "unset")
        result = filter_lang(result, allowed_langs)
    if spam_patterns:
        result = [t for t in result if not is_template_spam(t.get("text") or "", spam_patterns)]
    if engagement_thresholds:
        et = engagement_thresholds
        result = [t for t in result
                  if not is_low_engagement_ratio(t.get("metrics") or {}, **et)]
    if drop_promoted:
        result = [t for t in result if not t.get("is_promoted")]
    if drop_retweets:
        result = [t for t in result if not t.get("is_retweet")]
    return result
