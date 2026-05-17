"""`x-cli follow …` — direct follow/unfollow/block/etc. and queue ops.

Subcommands:
  follow HANDLE                              Default; follow a user
  follow remove HANDLE                       Unfollow
  follow block / unblock / mute / unmute HANDLE
  follow queue add HANDLE [...] [--reason]   Enqueue handles
  follow queue list [--status STATUS]
  follow queue tick [--max N --sleep SEC]
  follow queue clear MODE                    MODE: pending | completed | all
"""
from __future__ import annotations

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import build_client, emit_error, emit_ok, normalize_handle_arg
from x_cli.follow_queue import (
    DEFAULT_TICK_MAX,
    add_entries,
    clear_queue,
    list_summary,
    tick,
)
from x_cli.write_io import audit_write, dry_run_envelope


follow_app = typer.Typer(
    name="follow",
    help="Follow / unfollow / block / mute / queue management.",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _social(ctx: typer.Context, action: str, client_method: str,
            handle: str, yes: bool) -> None:
    c = _ctx(ctx)
    try:
        clean = normalize_handle_arg("handle", handle)
        plan = {"action": action, "handle": clean}
        if not yes:
            dry_run_envelope(plan, c.use_yaml)
            return
        client = build_client(c.profile)
        r = getattr(client, client_method)(clean)
        payload = {
            "action": action, "handle": clean,
            "user_id": (r or {}).get("id_str"),
        }
        if action in ("follow", "unfollow"):
            payload["following"] = (r or {}).get("following",
                                                 action == "follow")
        audit_write(c.profile, plan, payload)
        emit_ok(payload, c.use_yaml)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), c.use_yaml)
        raise typer.Exit(code=2)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)
    except Exception as exc:
        emit_error("write_failed", str(exc), c.use_yaml)
        raise typer.Exit(code=1)


# ────────── named social actions ─────────────────────────────────────


def _make_social_cmd(action: str, client_method: str):
    def cmd(
        ctx: typer.Context,
        handle: str = typer.Argument(..., metavar="HANDLE"),
        yes: bool = typer.Option(False, "--yes"),
    ) -> None:
        _social(ctx, action, client_method, handle, yes)
    cmd.__doc__ = f"{action.capitalize()} a user."
    return cmd


follow_app.command("add")(_make_social_cmd("follow", "follow_user"))
follow_app.command("remove")(_make_social_cmd("unfollow", "unfollow_user"))
follow_app.command("block")(_make_social_cmd("block", "block_user"))
follow_app.command("unblock")(_make_social_cmd("unblock", "unblock_user"))
follow_app.command("mute")(_make_social_cmd("mute", "mute_user"))
follow_app.command("unmute")(_make_social_cmd("unmute", "unmute_user"))


# ────────── queue subgroup ───────────────────────────────────────────


queue_app = typer.Typer(
    name="queue",
    help="Queued / rate-limit-aware follow scheduler.",
    no_args_is_help=True,
    add_completion=False,
)


@queue_app.command("add")
def queue_add_cmd(
    ctx: typer.Context,
    handles: list[str] = typer.Argument(..., metavar="HANDLE..."),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    """Append handles to the queue (status=pending)."""
    c = _ctx(ctx)
    try:
        emit_ok(add_entries(handles, reason), c.use_yaml)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), c.use_yaml)
        raise typer.Exit(code=2)


@queue_app.command("list")
def queue_list_cmd(
    ctx: typer.Context,
    status: str | None = typer.Option(
        None, "--status",
        help="Filter: pending|followed|rate_limited|error",
    ),
) -> None:
    """Show queue summary."""
    c = _ctx(ctx)
    emit_ok(list_summary(status), c.use_yaml)


@queue_app.command("tick")
def queue_tick_cmd(
    ctx: typer.Context,
    max_: int = typer.Option(DEFAULT_TICK_MAX, "--max", metavar="N"),
    sleep: float = typer.Option(3.0, "--sleep", metavar="SEC"),
) -> None:
    """Pop pending handles and follow them. Audits each success."""
    c = _ctx(ctx)
    try:
        client = build_client(c.profile)
        emit_ok(tick(c.profile, max_, sleep, client=client), c.use_yaml)
    except XQueryError as exc:
        emit_error(exc.error_code, str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@queue_app.command("clear")
def queue_clear_cmd(
    ctx: typer.Context,
    mode: str = typer.Argument(..., metavar="MODE",
                                help="MODE: pending | completed | all"),
) -> None:
    """Remove queue entries. MODE: pending | completed | all."""
    c = _ctx(ctx)
    try:
        emit_ok(clear_queue(mode), c.use_yaml)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), c.use_yaml)
        raise typer.Exit(code=2)


follow_app.add_typer(queue_app, name="queue", help="Follow queue subcommands.")
