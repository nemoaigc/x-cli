#!/usr/bin/env python3
"""profile.py — multi-account profile management for x-query.

Usage:
  uv run scripts/profile.py status [--json]
  uv run scripts/profile.py add <name>
  uv run scripts/profile.py add <name> --token <auth_token> --ct0 <ct0>
  uv run scripts/profile.py list
  uv run scripts/profile.py remove <name>
  uv run scripts/profile.py use <name>
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._core.output import add_common_args, build_client, emit_error, emit_ok, setup_logging
from scripts._core.output import normalize_optional_text
from scripts._core.profiles import (
    save_profile, load_profile, list_profiles, remove_profile,
    set_default_profile, get_default_profile,
)
from scripts._core.auth import extract_from_browser
from scripts._core.exceptions import InvalidInputError, XQueryError


def main():
    parser = argparse.ArgumentParser(
        description="x-query profile — manage multi-account auth profiles",
    )
    add_common_args(parser)

    subparsers = parser.add_subparsers(dest="subcmd", required=True, metavar="COMMAND")

    # status
    subparsers.add_parser("status", help="Check current auth and display profile")

    # add
    p_add = subparsers.add_parser("add", help="Save current browser session as a named profile")
    p_add.add_argument("name", metavar="NAME")
    p_add.add_argument("--token", metavar="AUTH_TOKEN", help="Provide auth_token manually")
    p_add.add_argument("--ct0", metavar="CT0", help="Provide ct0 manually")

    # list
    subparsers.add_parser("list", help="List all saved profiles")

    # remove
    p_rm = subparsers.add_parser("remove", help="Delete a saved profile")
    p_rm.add_argument("name", metavar="NAME")

    # use
    p_use = subparsers.add_parser("use", help="Set the default profile")
    p_use.add_argument("name", metavar="NAME")

    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        if hasattr(args, "token"):
            args.token = normalize_optional_text(args.token)
        if hasattr(args, "ct0"):
            args.ct0 = normalize_optional_text(args.ct0)
        if args.subcmd == "add" and bool(args.token) != bool(args.ct0):
            raise InvalidInputError("--token and --ct0 must be provided together")

        if args.subcmd == "status":
            try:
                client = build_client(args.profile)
                me = client.fetch_me()
                default = get_default_profile()
                emit_ok({
                    "authenticated": True,
                    "default_profile": default,
                    "profile": dataclasses.asdict(me),
                }, args.yaml)
            except XQueryError as exc:
                emit_error(exc.error_code, str(exc), args.yaml)
                sys.exit(1)

        elif args.subcmd == "add":
            if args.token and args.ct0:
                save_profile(args.name, auth_token=args.token, ct0=args.ct0)
            else:
                # Extract from browser
                import sys as _sys
                print("Extracting cookies from browser...", file=_sys.stderr)
                cookies, diagnostics = extract_from_browser()
                if not cookies:
                    emit_error(
                        "not_authenticated",
                        "No cookies found. Log into x.com first, or use --token/--ct0.",
                        args.yaml,
                    )
                    sys.exit(1)
                save_profile(
                    args.name,
                    auth_token=cookies["auth_token"],
                    ct0=cookies["ct0"],
                    cookie_string=cookies.get("cookie_string"),
                )
            emit_ok({"saved": args.name}, args.yaml)

        elif args.subcmd == "list":
            names = list_profiles()
            default = get_default_profile()
            emit_ok({
                "profiles": names,
                "default": default,
            }, args.yaml)

        elif args.subcmd == "remove":
            removed = remove_profile(args.name)
            if not removed:
                emit_error("not_found", "Profile not found: %s" % args.name, args.yaml)
                sys.exit(1)
            emit_ok({"removed": args.name}, args.yaml)

        elif args.subcmd == "use":
            if not load_profile(args.name):
                emit_error("not_found", "Profile not found: %s" % args.name, args.yaml)
                sys.exit(1)
            set_default_profile(args.name)
            emit_ok({"default": args.name}, args.yaml)

    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), args.yaml)
        sys.exit(1)
    except Exception as exc:
        emit_error("unexpected_error", str(exc), args.yaml)
        sys.exit(1)


if __name__ == "__main__":
    main()
