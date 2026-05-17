"""Multi-profile storage for x-cli.

Profiles are stored at ~/.config/x-cli/profiles/<name>.json (chmod 600).
The default profile is tracked in ~/.config/x-cli/default-profile.

Backward compatibility: profiles created under the previous ~/.config/x-query/
path are still readable. New writes always go to the x-cli path.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from . import paths

logger = logging.getLogger(__name__)


def _profile_path(name: str) -> Path:
    return paths.profiles_dir() / ("%s.json" % name)


def _legacy_profile_path(name: str) -> Path:
    return paths.legacy_profiles_dir() / ("%s.json" % name)


def save_profile(name: str, auth_token: str, ct0: str, cookie_string: Optional[str] = None) -> None:
    """Save a profile. Creates or overwrites ~/.config/x-cli/profiles/<name>.json (chmod 600)."""
    _validate_name(name)
    path = _profile_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict = {"auth_token": auth_token, "ct0": ct0}
    if cookie_string:
        data["cookie_string"] = cookie_string
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved profile: %s", name)


def load_profile(name: str) -> Optional[Dict]:
    """Load a profile by name. Checks new path first, then legacy x-query path."""
    _validate_name(name)
    for path in (_profile_path(name), _legacy_profile_path(name)):
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("auth_token") and data.get("ct0"):
                if path != _profile_path(name):
                    logger.info("Loaded profile %s from legacy x-query path", name)
                return data
        except Exception as exc:
            logger.debug("Failed to load profile %s from %s: %s", name, path, exc)
    return None


def list_profiles() -> List[str]:
    """Return sorted list of saved profile names from both new and legacy dirs."""
    names = set()
    for d in (paths.profiles_dir(), paths.legacy_profiles_dir()):
        try:
            if d.exists():
                names.update(p.stem for p in d.glob("*.json"))
        except Exception:
            continue
    return sorted(names)


def remove_profile(name: str) -> bool:
    """Delete a profile from both new and legacy dirs. Returns True if any was deleted."""
    _validate_name(name)
    deleted = False
    for path in (_profile_path(name), _legacy_profile_path(name)):
        if path.exists():
            path.unlink()
            deleted = True
    if deleted and get_default_profile() == name:
        clear_default_profile()
    return deleted


def set_default_profile(name: str) -> None:
    """Set the default profile."""
    _validate_name(name)
    p = paths.default_profile_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(name, encoding="utf-8")


def get_default_profile() -> Optional[str]:
    """Return the default profile name from new path, falling back to legacy."""
    for path in (paths.default_profile_file(), paths.legacy_default_profile_file()):
        if not path.exists():
            continue
        try:
            name = path.read_text(encoding="utf-8").strip()
            if name:
                return name
        except Exception:
            continue
    return None


def clear_default_profile() -> None:
    """Remove the default profile setting from both paths."""
    for path in (paths.default_profile_file(), paths.legacy_default_profile_file()):
        if path.exists():
            path.unlink()


def _validate_name(name: str) -> None:
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Profile name must be alphanumeric (hyphens/underscores allowed): %r" % name)
