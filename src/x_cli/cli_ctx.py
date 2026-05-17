"""Typer global-option context — passed via Context.obj to every command.

`profile` and `use_yaml` are usually the only things subcommands need from
the outer parser. Verbose is set up via setup_logging() at boot.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CliCtx:
    profile: str | None = None
    use_yaml: bool = False
    verbose: bool = False
