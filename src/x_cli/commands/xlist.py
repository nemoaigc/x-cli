"""`x-cli x-list …` — Twitter Lists CRUD.

Subcommands:
  create NAME [--description --public]
  delete LIST_ID
  add LIST_ID HANDLE
  remove LIST_ID HANDLE

All default to --dry-run; pass --yes to execute.
"""
from __future__ import annotations

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import (
    build_client,
    emit_error,
    emit_ok,
    normalize_handle_arg,
    normalize_numeric_id_arg,
    normalize_required_text,
)
from x_cli.write_io import audit_write, dry_run_envelope


xlist_app = typer.Typer(
    name="x-list",
    help="Twitter Lists CRUD.",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _execute(ctx: typer.Context, plan: dict, yes: bool, action_fn) -> None:
    """plan → optional dry-run gate → execute → audit → envelope."""
    c = _ctx(ctx)
    try:
        if not yes:
            dry_run_envelope(plan, c.use_yaml)
            return
        client = build_client(c.profile)
        payload = action_fn(client)
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


@xlist_app.command("create")
def create_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., metavar="NAME"),
    description: str = typer.Option("", "--description"),
    public: bool = typer.Option(False, "--public", help="Make list public (default: private)."),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Create a new X List."""
    try:
        clean = normalize_required_text("name", name)
        if len(clean) > 25:
            raise InvalidInputError("list name must be ≤25 chars")
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), _ctx(ctx).use_yaml)
        raise typer.Exit(code=2)

    plan = {
        "action": "list-create",
        "name": clean,
        "description": (description or "").strip(),
        "mode": "public" if public else "private",
    }

    def do(client):
        r = client.create_list(plan["name"], description=plan["description"], mode=plan["mode"])
        return {
            "action": "list-create",
            "list_id": (r or {}).get("id_str"),
            "name": (r or {}).get("name"),
            "mode": (r or {}).get("mode"),
        }

    _execute(ctx, plan, yes, do)


@xlist_app.command("delete")
def delete_cmd(
    ctx: typer.Context,
    list_id: str = typer.Argument(..., metavar="LIST_ID"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Delete one of your X Lists."""
    try:
        lid = normalize_numeric_id_arg("list_id", list_id)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), _ctx(ctx).use_yaml)
        raise typer.Exit(code=2)
    plan = {"action": "list-delete", "list_id": lid}

    def do(client):
        client.delete_list(lid)
        return {"action": "list-delete", "list_id": lid, "ok": True}

    _execute(ctx, plan, yes, do)


@xlist_app.command("add")
def add_cmd(
    ctx: typer.Context,
    list_id: str = typer.Argument(..., metavar="LIST_ID"),
    handle: str = typer.Argument(..., metavar="HANDLE"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Add a user to your List."""
    try:
        lid = normalize_numeric_id_arg("list_id", list_id)
        h = normalize_handle_arg("handle", handle)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), _ctx(ctx).use_yaml)
        raise typer.Exit(code=2)
    plan = {"action": "list-add", "list_id": lid, "handle": h}

    def do(client):
        client.add_list_member(lid, h)
        return {"action": "list-add", "list_id": lid, "handle": h, "ok": True}

    _execute(ctx, plan, yes, do)


@xlist_app.command("remove")
def remove_cmd(
    ctx: typer.Context,
    list_id: str = typer.Argument(..., metavar="LIST_ID"),
    handle: str = typer.Argument(..., metavar="HANDLE"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Remove a user from your List."""
    try:
        lid = normalize_numeric_id_arg("list_id", list_id)
        h = normalize_handle_arg("handle", handle)
    except (ValueError, InvalidInputError) as exc:
        emit_error("invalid_input", str(exc), _ctx(ctx).use_yaml)
        raise typer.Exit(code=2)
    plan = {"action": "list-remove", "list_id": lid, "handle": h}

    def do(client):
        client.remove_list_member(lid, h)
        return {"action": "list-remove", "list_id": lid, "handle": h, "ok": True}

    _execute(ctx, plan, yes, do)
