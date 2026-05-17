"""x-cli — typer entry point.

Global options (`--profile`, `--yaml`, `-v`) are parsed by the root
callback and stuffed into `ctx.obj` (a CliCtx). Subcommands read from
there. Subcommands themselves live in `x_cli.commands.<group>`.
"""
from __future__ import annotations

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.output import setup_logging
from x_cli.commands.auth import auth_app
from x_cli.commands.trend import trend_app
from x_cli.commands import feed as feed_cmd
from x_cli.commands import list_timeline as list_cmd
from x_cli.commands import search as search_cmds
from x_cli.commands import tweet as tweet_cmds
from x_cli.commands import user as user_cmd

app = typer.Typer(
    name="x-cli",
    help="X/Twitter command-line toolkit.",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(auth_app, name="auth", help="Manage authentication profiles.")
app.add_typer(trend_app, name="trend", help="Scan Explore trends and drill into them.")
user_cmd.register(app)
search_cmds.register(app)
tweet_cmds.register(app)
feed_cmd.register(app)
list_cmd.register(app)


@app.callback()
def _root(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None, "--profile", metavar="NAME",
        help="Named auth profile (or set XQ_PROFILE).",
    ),
    use_yaml: bool = typer.Option(
        False, "--yaml",
        help="Emit YAML instead of JSON.",
    ),
    verbose: bool = typer.Option(
        False, "-v", "--verbose",
        help="DEBUG logging to stderr.",
    ),
) -> None:
    setup_logging(verbose)
    ctx.obj = CliCtx(profile=profile, use_yaml=use_yaml, verbose=verbose)


if __name__ == "__main__":
    app()
