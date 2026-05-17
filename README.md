# x-cli

X/Twitter command-line toolkit — read, search, post, engage. Cookie-based
auth, JSON output, scriptable from any shell or backend.

```bash
pip install -e .                                # or: uv pip install -e .
x-cli auth status
x-cli user @karpathy
x-cli user @karpathy --tweets --top 20
x-cli search "claude code" --since 2026-05-10 --product Latest
x-cli post --text "hello world" --yes
x-cli engage like 1234567890
```

Every command emits a JSON envelope on stdout:

```json
{"ok": true,  "schema_version": "1", "data": {...}}
{"ok": false, "schema_version": "1", "error": {"code": "...", "message": "..."}}
```

Exit codes: `0` = success · `1` = runtime / API error · `2` = invalid input.

## Install

```bash
git clone https://github.com/nemoaigc/x-cli && cd x-cli
uv sync                          # or: pip install -e .
x-cli --help
```

## Auth

Three credential sources, tried in order by every command:

1. `--profile NAME` (or `XQ_PROFILE` env) — picks a saved profile under
   `~/.config/x-cli/profiles/<name>.json`.
2. Environment vars `TWITTER_AUTH_TOKEN` + `TWITTER_CT0` (raw cookie values).
   Use this for headless deploys (CI, Railway, Docker).
3. Automatic extraction from a local browser (Vivaldi / Chrome / Edge) via
   `browser-cookie3`. The default on a desktop.

Desktop setup:

```bash
x-cli auth add personal        # extracts from your default browser
x-cli auth use personal        # mark as default
x-cli auth status              # verify; prints your @screen_name
```

Headless / server:

```bash
# from devtools while logged in at x.com, copy these cookies
export TWITTER_AUTH_TOKEN=...
export TWITTER_CT0=...
x-cli auth status              # authenticated: true
```

## Commands

| Group           | Subcommands                                                                  |
|-----------------|------------------------------------------------------------------------------|
| `auth`          | `status` `add NAME` `list` `remove NAME` `use NAME`                          |
| `user`          | `HANDLE [--tweets / --replies / --media / --likes / --articles / --highlights / --followers / --following / --recommended] [--top N]` |
| `search`        | `QUERY [--since --until --lang --from-user --min-likes --min-retweets --product Top\|Latest --top N]` |
| `search-users`  | `QUERY [--top N]`                                                            |
| `tweet`         | `ID_OR_URL [--top N]`                                                        |
| `tweet-article` | `ID_OR_URL`                                                                  |
| `tweet-batch`   | `ID [ID ...]`                                                                |
| `feed`          | `list \| for-you \| following \| <pinned-label>  [--top --expand-articles --min-articles --min-posts --max-pages ...]` |
| `list`          | `LIST_ID [--top --expand-articles --min-articles --min-posts ...]`           |
| `trend`         | `scan [--drill-top N]` · `drill TREND_ID [--top]`                            |
| `me`            | `status` · `health [--warn-days]` · `likes [--max]` · `bookmarks [--folder / --list-folders]` · `mentions [--max]` |
| `engage`        | `like / unlike / retweet / unretweet / bookmark [--folder] / unbookmark TWEET_ID` |
| `post`          | `--text TEXT [--reply-to --quote --media --long] [--yes]` · `delete / pin / unpin / hide-reply / unhide-reply TWEET_ID [--yes]` |
| `follow`        | `add / remove / block / unblock / mute / unmute HANDLE [--yes]` · `queue add / list / tick / clear` |
| `x-list`        | `create NAME [--description --public] [--yes]` · `delete LIST_ID [--yes]` · `add / remove LIST_ID HANDLE [--yes]` |

All write commands default to `--dry-run`; pass `--yes` to execute.
Engagement writes (`engage *`) are immediate — they're low-risk reactions.

See [`SPEC.md`](./SPEC.md) for the formal command surface and the changelog
from the legacy `scripts/*.py` layout.

## Output

Default JSON on stdout. Pass `--yaml` on any command for YAML. Verbose logs
go to stderr with `-v`.

## Use from other code

x-cli is a normal subprocess target:

```python
import json, subprocess

out = subprocess.run(
    ["x-cli", "user", "karpathy", "--tweets", "--top", "10"],
    check=True, capture_output=True, text=True,
)
data = json.loads(out.stdout)["data"]
```

Backend integrations: install the package into the same image and shell out.
Or import `x_cli.core.client.TwitterClient` directly if you want fewer process
spawns (advanced; the `core` module is private API).

## Companion Claude Skill

For Claude Code users, the [`x-cli-skill`](https://github.com/nemoaigc/x-cli-skill)
package wraps this CLI with prompt-driven mode selection (read / trend / write)
and reference guides for ranking, spam filtering, and search planning. It
shells out to `x-cli` — no logic duplication.

## Tests

```bash
uv sync --extra dev
uv run pytest        # 102 tests, no network, no real cookies needed
```

## License & credits

Apache-2.0. Derivative of [twitter-cli](https://github.com/public-clis/twitter-cli)
by @jackwener — see [`NOTICE.md`](./NOTICE.md).
