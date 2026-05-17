# x-cli — Codebase Map for AI Agents

x-cli is a Claude Code skill for LLM-native X/Twitter access. It is a **read + write** toolkit (read everything; write = post / reply / quote / delete / like / retweet / bookmark / follow). It is NOT a CLI tool — scripts are invoked via `uv run` and emit JSON/YAML envelopes. It is ported and rewritten from [twitter-cli](https://github.com/public-clis/twitter-cli) by @jackwener (Apache-2.0); see NOTICE.md.

## Module map (`scripts/_core/`)

| File | Purpose |
|---|---|
| `auth.py` | Cookie extraction (browser-cookie3, subprocess fallback, env vars, profile files) |
| `client.py` | `TwitterClient` — GraphQL GET/POST, REST POST (follow), pagination, all writes |
| `graphql.py` | `FALLBACK_QUERY_IDS`, URL builder, JS bundle scanner (with 30s budget), queryId resolver |
| `parser.py` | GraphQL response → `Tweet` / `UserProfile` dataclasses; article Draft.js → Markdown |
| `window.py` | `adaptive_search()` — recursive time-window splitter for `--auto-window` |
| `rank.py` | Post-processing primitives: `filter_lang`, `is_template_spam(text, patterns)`, `is_low_engagement_ratio(metrics, ...thresholds)`, `score(tweet, weights, boosts)`, `rank_tweets(ts, score_fn)`, `author_diversity(ts, score_fn)`, `filter_stack(ts, **)`. **No defaults — caller composes all patterns / weights / thresholds per-domain**. See `references/spam-patterns.md` and `references/ranking-weights.md` |
| `models.py` | `Tweet`, `Author`, `Metrics`, `TweetMedia`, `UserProfile`, `BookmarkFolder`, `Trend` |
| `explore.py` | `fetch_all_tabs()`, `fetch_trend_kols()` for digest/trend mode |
| `profiles.py` | Profile CRUD at `~/.config/x-cli/profiles/<name>.json` (chmod 600); reads legacy `~/.config/x-query/` as fallback |
| `search.py` | `build_search_query()` — advanced X search operator composer |
| `timeutil.py` | Twitter timestamp → ISO 8601 / relative / local time |
| `constants.py` | Bearer token, Chrome UA/sec-ch-ua headers, locale helpers |
| `exceptions.py` | `XQueryError` hierarchy: `AuthenticationError`, `RateLimitError`, `NotFoundError`, … |
| `output.py` | `emit_ok()`, `emit_error()`, `build_client()`, `add_common_args()` + CLI input validators |

## Entry points

| Script | What it does | Key flags |
|---|---|---|
| `scripts/read.py` | Read mode: search, user timelines, tweet/article lookup, batch fetch, list, followers. **For any non-trivial "research" task, first read `references/search-plan.md` (multi-source pipeline design), then `references/read-mode.md` (single-call flag rubric)**. Post-process with `_core/rank.py`. | `--query`, `--user`, `--user-articles`, `--tweet`, `--batch`, `--followers`, `--feed`, `--list`, `--since`, `--until`, `--top`, `--auto-window`, `--expand-articles`, `--min-articles N`, `--min-posts N`, `--max-pages N`, `--product Top/Latest`, `--min-likes N`, `--from-user`, `--lang` |
| `scripts/digest.py` | Trend mode: scan Explore tabs, drill into a trend | `--scan`, `--drill <id_or_name>`, `--scan-drill-top N` |
| `scripts/me.py` | Self-scoped: my profile, likes, bookmarks, mentions + engagement writes + health probe | subcommands: `status`, `health`, `likes`, `bookmarks`, `mentions`, `like`, `unlike`, `retweet`, `unretweet`, `bookmark`, `unbookmark` |
| `scripts/write.py` | **Write mode** (16 subcommands). Default `--dry-run`; `--yes` to execute. New subcommand = 1 Command entry (see COMMANDS registry in write.py) | `post` (text/reply/quote/media/long), `delete`, `follow`/`unfollow`, `block`/`unblock`, `mute`/`unmute`, `pin`/`unpin`, `hide-reply`/`unhide-reply`, `list-create`/`list-delete`/`list-add`/`list-remove` |
| `scripts/follow_queue.py` | Queued rate-limit-aware following | `add`, `list`, `tick --max N`, `clear` |
| `scripts/profile.py` | Multi-account profile management | subcommands: `status`, `add`, `list`, `remove`, `use` |

All scripts accept `--profile NAME`, `--yaml`, `-v/--verbose`.

## Output envelope

```json
// Success
{"ok": true, "schema_version": "1", "data": <payload>}

// Error
{"ok": false, "schema_version": "1", "error": {"code": "<error_code>", "message": "<human-readable>"}}
```

Exit codes: 0 = ok, 1 = error, 2 = invalid args. See `schema.json` for formal contract.

## Adding a new read feature (5-step recipe)

1. **Find the GraphQL operation** in X's JS bundle:
   ```python
   from scripts._core.graphql import _scan_bundles, _cached_query_ids
   from scripts._core.client import _url_fetch
   _scan_bundles(_url_fetch)
   print({k: v for k, v in _cached_query_ids.items() if "keyword" in k.lower()})
   ```

2. **Probe variables live** until you get a populated response:
   ```python
   from scripts._core.output import build_client
   client = build_client()
   data = client._graphql_get("OperationName", {"count": 10}, {})
   print(list(data.get("data", {}).keys()))
   ```

3. **Add queryId** to `FALLBACK_QUERY_IDS` in `scripts/_core/graphql.py`.

4. **Add `fetch_<name>` method** in `scripts/_core/client.py` following the `_fetch_timeline` pattern.

5. **Expose via flag** on the relevant script (`read.py`, `digest.py`, or `me.py`).

## Adding a new write feature

1. Probe the queryId (or REST path) the same way — note that **follow/unfollow are legacy REST**, not GraphQL.
2. Add queryId to `FALLBACK_QUERY_IDS` (or skip for REST).
3. Add a method in `client.py` following:
   - For GraphQL: `create_tweet()` / `delete_tweet()` pattern (`_graphql_post` + `_validate_write_response`)
   - For REST: `follow_user()` pattern (`_legacy_rest_post`)
4. Wire it into `write.py` as a new subcommand with `--yes` guard + audit log entry.
5. Verify with `--dry-run` first, then a manually approved live action when the change affects writes.

**Out of scope**: DMs (rejected — privacy), Communities / Spaces / Bookmark folders / Scheduled tweets (deferred — most require X Premium or behave differently for alt accounts).

## Common failure modes

| Error | Cause | Fix |
|---|---|---|
| `GRAPHQL_VALIDATION_FAILED` / HTTP 404 from X | queryId rotated — fallback is stale | Client auto-retries with live lookup via `_scan_bundles` (read ops only; writes skip refresh to avoid blocking). If it keeps failing, re-probe via `_scan_bundles` and update `FALLBACK_QUERY_IDS` |
| HTTP 429 / JSON error code 88 | Rate limited | Client has exponential backoff (3 retries). If exhausted, wait 15+ min |
| `AuthenticationError` | Cookie expired or not found | Re-login to x.com, or `profile.py add <name>` |
| `not_authenticated` in envelope | Same as above, caught at script level | Same fix |
| Empty `data[]` on search | Query too narrow, or X recency lag | Remove `--min-likes` first; if still 0, widen query terms; if still 0 after `--auto-window`, report "no signal found" |
| `--following` returns `ok: false` | Rate limit, private account, or API transient | Skip Source A; continue with B+C; note "follow-circle signal unavailable" in report — do not retry |
| `--auto-window` returns 0 across all sub-windows | Domain too niche or query too narrow | Remove engagement filters first; if still 0, report honestly rather than widening to unrelated content |
| `DeleteTweet failed: missing subkeys ['tweet_results']` | Tweet was already deleted (or doesn't belong to you) | Check ownership first; idempotent retry won't help |
| `Follow X failed: ...` | Already following / blocked / suspended account | Check current state via `read.py --user X` first |

**Status:** v1.1 — full read + write toolkit: post / reply / quote / delete / follow / unfollow / block / mute / pin / hide-reply / media upload / long-form (Note Tweets, needs Premium) / Lists CRUD. Rate-limit-aware follow queue + scheduled trigger. Cookie health probe for cron.
