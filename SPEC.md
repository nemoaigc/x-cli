# SPEC — x-cli command surface (lock — must preserve)

> Frozen 1:1 from the old `scripts/*.py` argparse parsers. NO functional
> regressions allowed in the typer refactor. The only intentional change is
> reshaping subcommands for ergonomics (e.g. `--user-likes HANDLE` →
> `user HANDLE --likes`).

## Global flags (every command)

```
--profile NAME    Named auth profile (or XQ_PROFILE env)
--yaml            Emit YAML instead of JSON
-v / --verbose    DEBUG logging to stderr
```

All commands write a JSON envelope to **stdout**:

```json
{"ok": true,  "data": <...>}
{"ok": false, "error_code": "...", "error": "..."}
```

Non-zero exit on errors (1 = runtime, 2 = invalid input).

---

## auth — was `scripts/profile.py`

```
x-cli auth status                          Show current auth + profile
x-cli auth add NAME [--token T --ct0 C]    Save browser session as profile
x-cli auth list                            List saved profiles
x-cli auth remove NAME                     Delete a profile
x-cli auth use NAME                        Set default profile
```

## user — was `scripts/read.py` --user* + --search-users + --followers + --following + --recommended-users

Default = profile metadata (NEW, but trivially wraps existing `client.fetch_user`).

```
x-cli user HANDLE                       Profile metadata (bio, followers, etc.)
x-cli user HANDLE --tweets [--top N]    User's recent tweets
x-cli user HANDLE --replies [--top N]   Posts+Replies tab
x-cli user HANDLE --media [--top N]     Media tab
x-cli user HANDLE --likes [--top N]     Liked tweets (public)
x-cli user HANDLE --articles [--top N]  Articles tab
x-cli user HANDLE --highlights [--top N]
x-cli user HANDLE --followers [--top N]
x-cli user HANDLE --following [--top N]
x-cli user HANDLE --recommended [--top N]
x-cli user --recommended [--top N]      Recommendations for me (no handle)
x-cli search-users QUERY [--top N]      Search People tab (was --search-users; flat top-level since typer can't cleanly mix subcommands + positional in the parent)
```

Shared `--top` default = 30. Annotation flags (`you_follow_author`) auto-applied
when a default profile is set.

## search — was `scripts/read.py --query`

```
x-cli search QUERY [--since YYYY-MM-DD --until YYYY-MM-DD
                     --lang CODE --from-user HANDLE
                     --min-likes N --min-retweets N
                     --product Top|Latest --top N]
x-cli search-users QUERY [--top N]    People-tab user search (was --search-users)
```

## tweet — was `scripts/read.py --tweet / --article / --batch`

```
x-cli tweet ID_OR_URL                Single tweet + thread
x-cli tweet-article ID_OR_URL        Twitter Article by tweet ID
x-cli tweet-batch ID [ID ...]        Batch fetch
```

## feed — was `scripts/read.py --feed / --feeds`

```
x-cli feed list                      Show available feed names
x-cli feed NAME [--top N]            Read feed (for-you, AI, etc.)
```

## list — was `scripts/read.py --list`

```
x-cli list LIST_ID [--top N]
```

## trend — was `scripts/digest.py`

```
x-cli trend scan [--scan-drill-top N --top N]    Scan all Explore tabs
x-cli trend drill TREND_ID [--top N]              Drill into a trend
```

## me — was `scripts/me.py` (READ subcommands only)

```
x-cli me status                                Auth check + my profile
x-cli me health [--warn-days N]                Session health probe
x-cli me likes [--max N]                       My liked tweets
x-cli me bookmarks [--folder ID --list-folders]
x-cli me mentions [--max N]
```

## engage — was `scripts/me.py` (WRITE subcommands)

Engagement writes execute immediately (preserved from legacy me.py —
they're considered low-risk reactions, no --dry-run/--yes gate).

```
x-cli engage like TWEET_ID
x-cli engage unlike TWEET_ID
x-cli engage retweet TWEET_ID
x-cli engage unretweet TWEET_ID
x-cli engage bookmark TWEET_ID [--folder ID]
x-cli engage unbookmark TWEET_ID
```

## post — was `scripts/write.py` (post + tweet-mutating ops)

All accept `--dry-run` (default) / `--yes` (execute).

```
x-cli post --text TEXT [--reply-to ID --quote ID --media FILE... --long]
x-cli post delete TWEET_ID
x-cli post pin TWEET_ID
x-cli post unpin TWEET_ID
x-cli post hide-reply REPLY_ID
x-cli post unhide-reply REPLY_ID
```

## follow — was `scripts/write.py` (follow / block / mute / unfollow / etc.) + `scripts/follow_queue.py`

```
x-cli follow add HANDLE                 Follow user (was bare `follow HANDLE`;
                                        renamed for typer subgroup compatibility)
x-cli follow remove HANDLE              Unfollow
x-cli follow block HANDLE
x-cli follow unblock HANDLE
x-cli follow mute HANDLE
x-cli follow unmute HANDLE
x-cli follow queue add HANDLE [HANDLE...] [--reason TEXT]
x-cli follow queue list [--status pending|followed|rate_limited|error]
x-cli follow queue tick [--max N --sleep SEC]
x-cli follow queue clear MODE
```

## x-list — was `scripts/write.py` (list-create / list-delete / list-add / list-remove)

```
x-cli x-list create NAME [--description TEXT --public]
x-cli x-list delete LIST_ID
x-cli x-list add LIST_ID HANDLE
x-cli x-list remove LIST_ID HANDLE
```

## Agent skill installer

```text
x-cli skill path
x-cli skill install [--home PATH] [--claude/--no-claude]
                    [--codex/--no-codex] [--copy] [--force]
                    [--check-auth]
```

`x-cli skill install` installs the bundled `x-research` agent skill and the
Claude slash command wrappers `/x`, `/x-research`, and `/x-cli`. It uses symlinks
by default so the skill stays version-synced with the CLI checkout or tool
installation.

---

## Naming changes from old → new (registered for changelog)

| Old (argparse)                            | New (typer)                       |
|-------------------------------------------|-----------------------------------|
| `uv run scripts/read.py --user @h`        | `x-cli user @h --tweets`          |
| `uv run scripts/read.py --user-likes @h`  | `x-cli user @h --likes`           |
| `uv run scripts/read.py --query Q`        | `x-cli search Q`                  |
| `uv run scripts/read.py --tweet ID`       | `x-cli tweet ID`                  |
| `uv run scripts/read.py --batch A B C`    | `x-cli tweet batch A B C`         |
| `uv run scripts/read.py --feed NAME`      | `x-cli feed NAME`                 |
| `uv run scripts/read.py --feeds`          | `x-cli feed list`                 |
| `uv run scripts/read.py --list ID`        | `x-cli list ID`                   |
| `uv run scripts/digest.py --scan`         | `x-cli trend scan`                |
| `uv run scripts/digest.py --drill ID`     | `x-cli trend drill ID`            |
| `uv run scripts/me.py like ID`            | `x-cli engage like ID`            |
| `uv run scripts/write.py post --text T`   | `x-cli post --text T`             |
| `uv run scripts/write.py follow @h`       | `x-cli follow @h`                 |
| `uv run scripts/write.py list-create N`   | `x-cli x-list create N`           |
| `uv run scripts/follow_queue.py add @h`   | `x-cli follow queue add @h`       |
| `uv run scripts/profile.py status`        | `x-cli auth status`               |
