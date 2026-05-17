"""`x-cli auth …` — manage cookie-based auth profiles.

Subcommands:
  status       Auth check + my profile (fetches /me)
  add NAME     Save credentials (browser extract by default, or --token/--ct0)
  list         List saved profiles + which is default
  remove NAME  Delete a profile
  use NAME     Set default profile
"""
from __future__ import annotations

import dataclasses
import sys

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.auth import extract_from_browser
from x_cli.core.exceptions import XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok
from x_cli.core.profiles import (
    get_default_profile,
    list_profiles,
    load_profile,
    remove_profile,
    save_profile,
    set_default_profile,
)


auth_app = typer.Typer(
    name="auth",
    help="Manage authentication profiles (cookie-based).",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    """Best-effort fetch of the root context; defaults if running outside it."""
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


@auth_app.command("status")
def status_cmd(ctx: typer.Context) -> None:
    """Show current auth state and the logged-in profile."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        me = client.fetch_me()
        emit_ok(
            {
                "authenticated": True,
                "default_profile": get_default_profile(),
                "profile": dataclasses.asdict(me),
            },
            c.use_yaml,
        )
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@auth_app.command("add")
def add_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name."),
    token: str | None = typer.Option(None, "--token", metavar="AUTH_TOKEN"),
    ct0: str | None = typer.Option(None, "--ct0", metavar="CT0"),
) -> None:
    """Save a session under NAME. Without --token/--ct0, extracts from browser."""
    c = _ctx(ctx)
    if bool(token) != bool(ct0):
        emit_error("invalid_input", "--token and --ct0 must be provided together", c.use_yaml)
        raise typer.Exit(code=2)

    try:
        if token and ct0:
            save_profile(name, auth_token=token, ct0=ct0)
        else:
            print("Extracting cookies from browser...", file=sys.stderr)
            cookies, _diagnostics = extract_from_browser()
            if not cookies:
                emit_error(
                    "not_authenticated",
                    "No cookies found. Log into x.com first, or use --token/--ct0.",
                    c.use_yaml,
                )
                raise typer.Exit(code=1)
            save_profile(
                name,
                auth_token=cookies["auth_token"],
                ct0=cookies["ct0"],
                cookie_string=cookies.get("cookie_string"),
            )
        emit_ok({"saved": name}, c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@auth_app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List all saved profiles + the current default."""
    c = _ctx(ctx)
    emit_ok(
        {"profiles": list_profiles(), "default": get_default_profile()},
        c.use_yaml,
    )


@auth_app.command("remove")
def remove_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name to remove."),
) -> None:
    """Delete a saved profile."""
    c = _ctx(ctx)
    if not remove_profile(name):
        emit_error("not_found", f"Profile not found: {name}", c.use_yaml)
        raise typer.Exit(code=1)
    emit_ok({"removed": name}, c.use_yaml)


@auth_app.command("use")
def use_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile to mark as default."),
) -> None:
    """Set the default profile."""
    c = _ctx(ctx)
    if not load_profile(name):
        emit_error("not_found", f"Profile not found: {name}", c.use_yaml)
        raise typer.Exit(code=1)
    set_default_profile(name)
    emit_ok({"default": name}, c.use_yaml)
