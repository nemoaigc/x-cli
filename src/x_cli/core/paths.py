"""Centralized config path resolver for x-cli.

All modules read paths through this single source of truth. Override for testing
or running an isolated instance by setting XCLI_CONFIG_DIR in the environment.

Primary base:   $XCLI_CONFIG_DIR  or  ~/.config/x-cli/
Legacy base:    ~/.config/x-query/  (read-only, for profiles migrated from x-query)
"""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """Primary config directory. Creates it on first access."""
    env = os.environ.get("XCLI_CONFIG_DIR")
    base = Path(env) if env else Path.home() / ".config" / "x-cli"
    base.mkdir(parents=True, exist_ok=True)
    return base


def legacy_config_dir() -> Path:
    """Legacy x-query config directory. Does NOT auto-create."""
    return Path.home() / ".config" / "x-query"


def profiles_dir() -> Path:
    d = config_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_profile_file() -> Path:
    return config_dir() / "default-profile"


def legacy_profiles_dir() -> Path:
    return legacy_config_dir() / "profiles"


def legacy_default_profile_file() -> Path:
    return legacy_config_dir() / "default-profile"


def transaction_cache_path() -> Path:
    return config_dir() / "transaction_cache.json"


def write_log_path() -> Path:
    return config_dir() / "write-log.jsonl"


def follow_queue_path() -> Path:
    return config_dir() / "follow-queue.jsonl"


def following_cache_path(profile_name: str | None) -> Path:
    tag = profile_name or "_default"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)
    return config_dir() / f"followcache-{safe}.json"
