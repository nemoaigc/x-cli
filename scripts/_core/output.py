"""Machine-readable output helpers for x-query scripts.

All scripts emit JSON/YAML envelopes to stdout.
Envelope: {ok: bool, schema_version: "1", data: ...} on success
          {ok: false, error: {code, message}} on error
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from typing import Any, Optional

from .exceptions import InvalidInputError

_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def _to_serializable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_serializable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj


def emit_ok(data: Any, use_yaml: bool = False) -> None:
    payload = {"ok": True, "schema_version": "1", "data": _to_serializable(data)}
    _emit(payload, use_yaml)


def emit_error(code: str, message: str, use_yaml: bool = False) -> None:
    payload = {"ok": False, "schema_version": "1", "error": {"code": code, "message": message}}
    _emit(payload, use_yaml)


def _emit(payload: Any, use_yaml: bool) -> None:
    if use_yaml:
        try:
            import yaml
            print(yaml.dump(payload, allow_unicode=True, sort_keys=False), end="")
        except ImportError:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def build_client(profile: Optional[str] = None):
    """Build a TwitterClient from cookies (profile → env → browser)."""
    from .auth import get_cookies
    from .client import TwitterClient
    cookies = get_cookies(profile=profile)
    return TwitterClient(
        auth_token=cookies["auth_token"],
        ct0=cookies["ct0"],
        cookie_string=cookies.get("cookie_string"),
    )


def add_common_args(parser: Any) -> None:
    """Add --profile, --yaml, -v flags to an argparse parser."""
    parser.add_argument("--profile", metavar="NAME", help="Named auth profile (or set XQ_PROFILE)")
    parser.add_argument("--yaml", action="store_true", help="Emit YAML instead of JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")


def setup_logging(verbose: bool) -> None:
    import logging
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def normalize_required_text(flag_name: str, value: Optional[str]) -> str:
    text = normalize_optional_text(value)
    if text is None:
        raise InvalidInputError("%s must not be empty" % flag_name)
    return text


def require_positive_int(flag_name: str, value: Optional[int]) -> None:
    if value is not None and value <= 0:
        raise InvalidInputError("%s must be greater than 0" % flag_name)


def normalize_handle_arg(flag_name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise InvalidInputError("%s must not be empty" % flag_name)
    handle = text.lstrip("@")
    if not handle:
        raise InvalidInputError("%s must not be empty" % flag_name)
    if not _HANDLE_PATTERN.fullmatch(handle):
        raise InvalidInputError("%s must be a valid X handle" % flag_name)
    return handle


def normalize_numeric_id_arg(flag_name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise InvalidInputError("%s must not be empty" % flag_name)
    if not re.fullmatch(r"[0-9]+", text):
        raise InvalidInputError("%s must be numeric" % flag_name)
    return text
