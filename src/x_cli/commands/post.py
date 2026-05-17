"""`x-cli post …` — compose tweets and mutate own tweets.

Subcommands:
  (root)        --text TEXT [--reply-to ID --quote ID --media FILE... --long]
  delete        TWEET_ID
  pin           TWEET_ID
  unpin         TWEET_ID
  hide-reply    REPLY_ID
  unhide-reply  REPLY_ID

All default to --dry-run; pass --yes to actually execute.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import typer

from x_cli.cli_ctx import CliCtx
from x_cli.core.exceptions import InvalidInputError, XQueryError
from x_cli.core.output import (
    build_client,
    emit_error,
    emit_ok,
    normalize_numeric_id_arg,
)
from x_cli.write_io import (
    LONG_TEXT_MAX,
    TEXT_MAX,
    audit_write,
    dry_run_envelope,
)


logger = logging.getLogger(__name__)

post_app = typer.Typer(
    name="post",
    help="Compose tweets, delete / pin / hide-reply on your own.",
    no_args_is_help=False,        # bare `post --text ...` is the primary cmd
    add_completion=False,
    invoke_without_command=True,  # see callback below
)


def _ctx(ctx: typer.Context) -> CliCtx:
    obj = getattr(ctx, "obj", None)
    return obj if isinstance(obj, CliCtx) else CliCtx()


def _validate_post_text(text: str, *, allow_long: bool = False) -> str:
    text = text.strip()
    if not text:
        raise InvalidInputError("--text must not be empty")
    cap = LONG_TEXT_MAX if allow_long else TEXT_MAX
    if len(text) > cap:
        suffix = (" (with --long)" if allow_long
                  else " (pass --long for Note Tweets up to 25000; requires X Premium)")
        raise InvalidInputError(f"--text is {len(text)} chars; max {cap}{suffix}")
    return text


# ─────────────────────────── post (root) ──────────────────────────────


@post_app.callback(invoke_without_command=True)
def root_cmd(
    ctx: typer.Context,
    text: Optional[str] = typer.Option(None, "--text", help="Tweet text"),
    reply_to: Optional[str] = typer.Option(None, "--reply-to", metavar="ID"),
    quote:    Optional[str] = typer.Option(None, "--quote",    metavar="ID"),
    media:    Optional[list[str]] = typer.Option(None, "--media", metavar="FILE"),
    long:     bool = typer.Option(False, "--long",
                                  help="Allow >280 chars (Note Tweet, needs X Premium)"),
    yes:      bool = typer.Option(False, "--yes", help="Execute (default: dry-run)"),
) -> None:
    """Compose a tweet (use `post <subcommand>` for delete / pin / etc.)."""
    if ctx.invoked_subcommand is not None:
        return
    if text is None:
        ctx.fail("Missing option '--text'.")

    c = _ctx(ctx)
    try:
        validated = _validate_post_text(text, allow_long=long)
        reply_to_id = normalize_numeric_id_arg("--reply-to", reply_to) if reply_to else None
        quote_id    = normalize_numeric_id_arg("--quote",    quote)    if quote    else None
        if reply_to_id and quote_id:
            raise InvalidInputError("--reply-to and --quote are mutually exclusive")
        media_list = media or []
        if len(media_list) > 4:
            raise InvalidInputError("--media accepts up to 4 files per tweet")
        for m in media_list:
            if not os.path.isfile(m):
                raise InvalidInputError(f"--media file not found: {m}")

        plan = {
            "action": "post",
            "text": validated,
            "length": len(validated),
            "reply_to": reply_to_id,
            "quote": quote_id,
            "media": media_list,
        }

        if not yes:
            dry_run_envelope(plan, c.use_yaml)
            return

        client = build_client(c.profile)
        media_ids: list[str] = []
        for m in media_list:
            mid = client.upload_media(m)
            media_ids.append(mid)
            logger.info("Uploaded media %s → id=%s", m, mid)
        result = client.create_tweet(
            validated,
            reply_to=reply_to_id,
            quote_tweet_id=quote_id,
            media_ids=media_ids or None,
        )
        tweet_id = result.get("rest_id") or "?"
        payload = {
            "action": "post",
            "tweet_id": tweet_id,
            "url": f"https://x.com/i/web/status/{tweet_id}",
            "text": validated,
            "media_ids": media_ids or None,
        }
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


# ────────────────── tweet-id actions: delete / pin / unpin / hide / unhide ───


def _tweet_action(action_name: str, client_method: str):
    """Build a typer command for a single-arg tweet-id mutator."""

    def cmd(
        ctx: typer.Context,
        tweet_id: str = typer.Argument(..., metavar="TWEET_ID"),
        yes: bool = typer.Option(False, "--yes"),
    ) -> None:
        c = _ctx(ctx)
        try:
            tid = normalize_numeric_id_arg("tweet_id", tweet_id)
            plan = {"action": action_name, "tweet_id": tid}
            if not yes:
                dry_run_envelope(plan, c.use_yaml)
                return
            client = build_client(c.profile)
            getattr(client, client_method)(tid)
            payload = {"action": action_name, "tweet_id": tid, "ok": True}
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

    cmd.__doc__ = f"{action_name.replace('-', ' ').capitalize()} a tweet."
    return cmd


post_app.command("delete")(_tweet_action("delete", "delete_tweet"))
post_app.command("pin")(_tweet_action("pin", "pin_tweet"))
post_app.command("unpin")(_tweet_action("unpin", "unpin_tweet"))
post_app.command("hide-reply")(_tweet_action("hide-reply", "hide_reply"))
post_app.command("unhide-reply")(_tweet_action("unhide-reply", "unhide_reply"))
