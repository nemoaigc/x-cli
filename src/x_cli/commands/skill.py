"""`x-cli skill ...` — install the bundled x-research agent skill."""
from __future__ import annotations

import os
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.output import build_client, emit_error, emit_ok


SKILL_NAME = "x-research"
COMMAND_NAMES = ("x", "x-research", "x-cli")
BLOCKED_STATUSES = {"exists", "refused_directory"}

skill_app = typer.Typer(
    name="skill",
    help="Install and inspect the bundled x-research agent skill.",
    no_args_is_help=True,
    add_completion=False,
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _repo_root_skill_dir() -> Path | None:
    # src/x_cli/commands/skill.py -> repo root is parents[3] in editable/source checkouts.
    candidate = Path(__file__).resolve().parents[3] / "skills" / SKILL_NAME
    return candidate if (candidate / "SKILL.md").exists() else None


def bundled_skill_dir() -> Path:
    repo_skill = _repo_root_skill_dir()
    if repo_skill is not None:
        return repo_skill

    candidate = resources.files("x_cli").joinpath("skills", SKILL_NAME)
    path = Path(str(candidate))
    if not (path / "SKILL.md").exists():
        raise FileNotFoundError("bundled x-research skill was not found")
    return path


def _same_symlink(dst: Path, src: Path) -> bool:
    if not dst.is_symlink():
        return False
    target = Path(os.readlink(dst))
    if not target.is_absolute():
        target = (dst.parent / target).resolve()
    return target == src.resolve()


def _link_or_copy(src: Path, dst: Path, *, copy: bool, force: bool) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() or dst.is_symlink():
        if not copy and _same_symlink(dst, src):
            return {"path": str(dst), "status": "already_installed", "target": str(src)}
        if not force:
            return {"path": str(dst), "status": "exists", "target": str(src)}
        if dst.is_dir() and not dst.is_symlink():
            return {"path": str(dst), "status": "refused_directory", "target": str(src)}
        dst.unlink()

    if copy:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"path": str(dst), "status": "copied", "target": str(src)}

    dst.symlink_to(src)
    return {"path": str(dst), "status": "linked", "target": str(src)}


def install_skill(
    *,
    home: Path,
    install_claude: bool,
    install_codex: bool,
    copy: bool,
    force: bool,
) -> dict[str, Any]:
    skill_dir = bundled_skill_dir().resolve()
    results: dict[str, Any] = {"skill_dir": str(skill_dir), "installs": []}

    if install_claude:
        claude_skill = home / ".claude" / "skills" / SKILL_NAME
        results["installs"].append({
            "kind": "claude_skill",
            **_link_or_copy(skill_dir, claude_skill, copy=copy, force=force),
        })
        for command in COMMAND_NAMES:
            src = skill_dir / "commands" / f"{command}.md"
            dst = home / ".claude" / "commands" / f"{command}.md"
            results["installs"].append({
                "kind": "claude_command",
                "name": command,
                **_link_or_copy(src, dst, copy=copy, force=force),
            })

    if install_codex:
        codex_skill = home / ".codex" / "skills" / SKILL_NAME
        results["installs"].append({
            "kind": "codex_skill",
            **_link_or_copy(skill_dir, codex_skill, copy=copy, force=force),
        })

    return results


def blocked_installs(data: dict[str, Any]) -> list[dict[str, Any]]:
    installs = data.get("installs", [])
    return [
        item for item in installs
        if item.get("status") in BLOCKED_STATUSES
    ]


@skill_app.command("path")
def path_cmd(ctx: typer.Context) -> None:
    """Show the bundled x-research skill path."""
    c = _ctx(ctx)
    try:
        emit_ok({"name": SKILL_NAME, "path": str(bundled_skill_dir().resolve())}, c.use_yaml)
    except FileNotFoundError as exc:
        emit_error("not_found", str(exc), c.use_yaml)
        raise typer.Exit(code=1)


@skill_app.command("install")
def install_cmd(
    ctx: typer.Context,
    home: Path = typer.Option(
        Path.home(),
        "--home",
        help="Home directory containing .claude/.codex.",
    ),
    install_claude: bool = typer.Option(
        True,
        "--claude/--no-claude",
        help="Install ~/.claude skill and slash commands.",
    ),
    install_codex: bool = typer.Option(
        True,
        "--codex/--no-codex",
        help="Install ~/.codex skill link.",
    ),
    copy: bool = typer.Option(
        False,
        "--copy",
        help="Copy files instead of creating symlinks.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace existing symlinks or files. Real directories are never removed.",
    ),
    check_auth: bool = typer.Option(
        False,
        "--check-auth",
        help="Also verify the active X auth profile after installing.",
    ),
) -> None:
    """Install bundled x-research skill links for Claude/Codex."""
    c = _ctx(ctx)
    try:
        data = install_skill(
            home=home.expanduser(),
            install_claude=install_claude,
            install_codex=install_codex,
            copy=copy,
            force=force,
        )
        if check_auth:
            me = build_client(c.profile).fetch_me()
            data["auth"] = {"authenticated": True, "screen_name": me.screen_name}
        blocked = blocked_installs(data)
        if blocked:
            emit_error(
                "install_blocked",
                "Some targets were not installed: %s" % ", ".join(
                    "%s=%s" % (item.get("kind"), item.get("path"))
                    for item in blocked
                ),
                c.use_yaml,
            )
            raise typer.Exit(code=1)
        emit_ok(data, c.use_yaml)
    except FileNotFoundError as exc:
        emit_error("not_found", str(exc), c.use_yaml)
        raise typer.Exit(code=1)
    except OSError as exc:
        emit_error("install_failed", str(exc), c.use_yaml)
        raise typer.Exit(code=1)
