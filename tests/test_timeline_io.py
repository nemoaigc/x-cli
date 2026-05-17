"""Unit tests for x_cli.timeline_io — covers behavior the per-command
tests don't catch (follow annotation across profile-name modes,
content_kind enrichment, mix-gate vs simple paging dispatch)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from x_cli.core.models import Author, Metrics, Tweet
from x_cli.timeline_io import TimelineOpts, emit_timeline


def _tweet(tid="t1", **overrides):
    return Tweet(
        id=tid, author=Author(id="u1", name="K", screen_name="k"),
        text="hi", created_at="", metrics=Metrics(), **overrides,
    )


def test_emit_timeline_annotates_when_profile_is_none(capsys):
    """codex P2: when the user is on the default profile (profile_name=None),
    annotation must still run — following_cache supports the None key.
    Previously the `if profile_name and tweets:` guard skipped this and
    default-profile users silently lost `you_follow_author`."""
    client = MagicMock()
    client.fetch_me.return_value = MagicMock(id="me1")
    client.fetch_all_following_ids.return_value = ["u1"]
    opts = TimelineOpts(top=5)

    def fetch_page(*, count):
        return [_tweet()]

    with patch("x_cli.timeline_io.following_cache.load_cached", return_value=None) as lc, \
         patch("x_cli.timeline_io.following_cache.save_cache") as sc, \
         patch("x_cli.timeline_io.following_cache.annotate_tweets") as annot:
        emit_timeline(client, fetch_page, opts, profile_name=None)

    # The whole follow-cache pipeline ran exactly once, with profile=None.
    lc.assert_called_once_with(None)
    client.fetch_me.assert_called_once()
    client.fetch_all_following_ids.assert_called_once_with("me1")
    sc.assert_called_once_with(None, ["u1"])
    annot.assert_called_once()


def test_emit_timeline_skips_annotation_when_no_tweets(capsys):
    """Empty timelines must NOT trigger fetch_me / fetch_all_following_ids —
    that's wasteful network on an empty payload."""
    client = MagicMock()

    def fetch_page(*, count):
        return []

    with patch("x_cli.timeline_io.following_cache.load_cached") as lc:
        emit_timeline(client, fetch_page, TimelineOpts(top=5), profile_name="alice")

    lc.assert_not_called()
    client.fetch_me.assert_not_called()


def test_emit_timeline_adds_content_kind_field(capsys):
    """Each tweet dict in the envelope must have a synthesized
    content_kind field ('tweet' | 'note_tweet' | 'article')."""
    import json

    client = MagicMock()
    client.fetch_me.return_value = MagicMock(id="me1")
    client.fetch_all_following_ids.return_value = []

    def fetch_page(*, count):
        return [_tweet("t1"), _tweet("t2")]

    emit_timeline(client, fetch_page, TimelineOpts(top=5), profile_name=None)
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert all("content_kind" in t for t in out["data"])
    assert out["data"][0]["content_kind"] == "tweet"
