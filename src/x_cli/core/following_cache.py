"""Cache of the current profile's following list (set of author_ids).

Lets tweets be annotated with `you_follow_author`. Cache TTL 24h.
Cache path: ~/.config/x-cli/followcache-<profile>.json
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Iterable, Optional, Set

from . import paths

logger = logging.getLogger(__name__)

_TTL_SECONDS = 24 * 3600


def _cache_path(profile: Optional[str]) -> Path:
    return paths.following_cache_path(profile)


def load_cached(profile: Optional[str]) -> Optional[Set[str]]:
    """Return cached set of followed user_ids if fresh, else None."""
    path = _cache_path(profile)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("timestamp", 0) > _TTL_SECONDS:
            return None
        ids = data.get("following_ids") or []
        if not isinstance(ids, list):
            return None
        return set(str(i) for i in ids)
    except Exception as exc:
        logger.debug("Following cache read failed for profile %s: %s", profile, exc)
        return None


def save_cache(profile: Optional[str], following_ids: Iterable[str]) -> None:
    """Persist the set of user_ids (one-shot, not incremental)."""
    path = _cache_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(str(i) for i in following_ids if i))
    payload = {"timestamp": time.time(), "count": len(ids), "following_ids": ids}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    logger.info("Saved %d following IDs to cache for profile=%s", len(ids), profile or "_default")


def annotate_tweets(tweets, following_ids: Optional[Set[str]]) -> None:
    """Set tweet.you_follow_author on each tweet in-place. No-op if no cache."""
    if not following_ids:
        return
    for t in tweets or []:
        author_id = getattr(getattr(t, "author", None), "id", None)
        if author_id:
            t.you_follow_author = author_id in following_ids
        # Also annotate quoted tweet if present
        qt = getattr(t, "quoted_tweet", None)
        if qt is not None:
            qt_author_id = getattr(getattr(qt, "author", None), "id", None)
            if qt_author_id:
                qt.you_follow_author = qt_author_id in following_ids
