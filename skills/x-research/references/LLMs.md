# x-cli — quick map for LLM-driven use

Companion to the [x-cli](https://github.com/nemoaigc/x-cli) command-line tool.
This skill is **read + write** (post / reply / quote / delete / like / retweet
/ bookmark / follow). Every command emits a JSON envelope.

## Command map

| Command         | What it does                                                                      |
|-----------------|-----------------------------------------------------------------------------------|
| `auth`          | Profile / cookie session management.                                              |
| `user`          | Profile metadata; user timelines (`--tweets/--replies/--media/--likes/--articles/--highlights`); social graph (`--followers/--following/--recommended`). |
| `search`        | Advanced tweet search. Accepts `--since --until --lang --from-user --min-likes --min-retweets --product Top\|Latest --top`. **For non-trivial research, first read `references/search-plan.md` (multi-source pipeline), then `references/read-mode.md` (single-call flag rubric)**. |
| `search-users`  | People-tab user search.                                                           |
| `tweet`         | Single tweet + thread.                                                            |
| `tweet-article` | Twitter Article body (Draft.js → Markdown).                                       |
| `tweet-batch`   | Bulk fetch by IDs.                                                                |
| `feed`          | `list` / `for-you` / `following` / `<pinned-label>`. Mix-gate flags (`--min-articles --min-posts --max-pages --min-article-likes/...`) trigger multi-page article+post quotas. |
| `list`          | Twitter Lists timeline (same mix-gate flags).                                     |
| `trend`         | `scan [--drill-top N]` / `drill TREND_ID`.                                        |
| `me`            | `status / health / likes / bookmarks / mentions`.                                 |
| `engage`        | `like / unlike / retweet / unretweet / bookmark / unbookmark`. Immediate, no `--yes`. |
| `post`          | Compose tweet / `delete / pin / unpin / hide-reply / unhide-reply`. **Default `--dry-run`; `--yes` to execute.** |
| `follow`        | `add / remove / block / unblock / mute / unmute HANDLE` + `queue add / list / tick / clear`. |
| `x-list`        | Twitter Lists CRUD (`create / delete / add / remove`).                            |

Every command accepts `--profile NAME`, `--yaml`, `-v/--verbose`.

## Output envelope

```json
// Success
{"ok": true, "schema_version": "1", "data": <payload>}

// Error
{"ok": false, "schema_version": "1", "error": {"code": "<error_code>", "message": "<human-readable>"}}
```

Exit codes: `0` = ok · `1` = error · `2` = invalid args.

## Post-processing tweets (rank / filter)

The `x-cli` package exposes `x_cli.core.rank` — `filter_lang`, `is_template_spam`,
`is_low_engagement_ratio`, `score`, `rank_tweets`, `author_diversity`,
`filter_stack`. **No defaults — caller composes patterns / weights / thresholds
per-domain.** See `references/spam-patterns.md` and `references/ranking-weights.md`.

Import path:

```python
from x_cli.core import rank
clean = rank.filter_stack(tweets, allowed_langs={"en", "zh"},
                          spam_patterns=[...], drop_promoted=True)
top = rank.author_diversity(clean, score_fn=lambda t: rank.score(t, weights={...}),
                            decay=0.7, floor=0.3)[:20]
```

## Common failure modes

| Error                                  | Cause                                              | Fix                                                                 |
|----------------------------------------|----------------------------------------------------|----------------------------------------------------------------------|
| `GRAPHQL_VALIDATION_FAILED` / HTTP 404 | queryId rotated — fallback stale                  | x-cli auto-retries with live bundle scan on reads. If it keeps failing, file a bug against x-cli. |
| HTTP 429 / JSON error 88               | Rate limited                                       | Built-in exponential backoff (3 retries). If exhausted, wait 15+ min |
| `not_authenticated`                    | Cookie expired or not found                        | `x-cli auth add NAME` (or refresh `TWITTER_AUTH_TOKEN`/`TWITTER_CT0`) |
| Empty `data[]` on search               | Query too narrow, or X recency lag                | Remove `--min-likes` first; widen query terms; report honestly if no signal |
| `--following` returns `ok: false`      | Rate limit / private / API transient              | Skip that source, continue, note in the report — do not retry        |
| `DeleteTweet failed: missing subkeys`  | Tweet already deleted or not yours                | Check ownership first; idempotent retry won't help                   |
| `Follow X failed: ...`                 | Already following / blocked / suspended           | `x-cli user X` first to check current state                         |

## Non-goals

- DM (private messages) — out of scope (privacy / ethics)
- Real-time streaming — batch only
- Communities / Spaces operations — deferred
- Scheduled tweets — X Premium only, deferred
