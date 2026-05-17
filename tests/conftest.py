"""Shared pytest fixtures.

CliRunner gives us in-process invocation + stdout/stderr capture without
spawning a subprocess. Auth and X API calls are stubbed so tests are
fully hermetic — no network, no real cookies needed.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from x_cli.__main__ import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli(runner: CliRunner):
    """Invoke the root `x-cli` typer app with the given argv list.

    Returns a `Result`. Parsed-JSON helper is on the returned object via
    `.json` (lazy) for convenience.
    """
    def _invoke(args: list[str]):
        result = runner.invoke(app, args, catch_exceptions=False)

        def _json():
            return json.loads(result.stdout)
        result.json = _json  # type: ignore[attr-defined]
        return result

    return _invoke


@pytest.fixture
def fake_user():
    """A canned UserProfile-shape dict that fetch_me / fetch_user can return."""
    from x_cli.core.models import UserProfile
    return UserProfile(
        id="123",
        name="Test User",
        screen_name="testuser",
        bio="A test account.",
        followers_count=42,
        following_count=10,
        tweets_count=99,
        verified=False,
        profile_image_url="https://x.com/img.jpg",
    )
