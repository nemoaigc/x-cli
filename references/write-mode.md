# Write Mode — Post / Delete / Follow / Unfollow

Use when the user wants to create content on X or change their social graph.

## Triggers

"帮我发条推" / "post a tweet" / "回复 @xxx" / "reply to ..." / "转评那条" / "quote that" /
"删那条推" / "delete that tweet" / "关注 @xxx" / "follow ..." / "取关" / "unfollow".

## SAFETY DISCIPLINE — read this first

Every write subcommand defaults to **dry-run**. The script only really executes when `--yes` is passed.

**The LLM caller MUST:**
1. First call **without `--yes`** to get the planned action.
2. **Show the user the exact text/target** that will be sent.
3. **Wait for explicit confirmation** ("OK", "确认", "发", or equivalent).
4. **Only then re-run with `--yes`.**

Never auto-add `--yes`. Never assume previous consent applies to a new action — X write operations are irreversible, and consent is action-scoped: "OK go ahead" on a post does not authorize a follow two turns later, even in the same session.

Every `--yes` call appends an entry to `~/.config/x-cli/write-log.jsonl`.

## Subcommand cheatsheet

```bash
# Post
uv run scripts/write.py post --text "Hello world"                    # dry-run
uv run scripts/write.py post --text "Hello world" --yes              # actually post

# Reply to a tweet
uv run scripts/write.py post --text "Agreed!" --reply-to 12345 --yes

# Quote-tweet
uv run scripts/write.py post --text "Worth reading:" --quote 12345 --yes

# Delete (must be your own tweet)
uv run scripts/write.py delete 12345 --yes

# Follow / Unfollow
uv run scripts/write.py follow karpathy --yes
uv run scripts/write.py unfollow karpathy --yes
```

## Common flow

### Posting
1. Draft text with the user. Confirm length ≤280 for standard tweets, or pass `--long` for Note Tweets (≤25000, requires X Premium on the account).
2. `write.py post --text "<draft>"` → returns dry-run plan
3. Repeat back to user; ask "confirm 发?"
4. On OK: `write.py post --text "<draft>" --yes` → returns `{tweet_id, url}`
5. Show user the URL.

### Replying / quoting
- Always `--reply-to <id>` not `--reply-to <url>`. The `write.py` argparse layer accepts numeric IDs only; strip the `status/<id>` portion out of URLs before passing.
- For `--quote`, same.

### Deleting
- Verify the tweet is yours (`me.py status` shows `id`; the tweet's `author.id` must match) before delete. Otherwise X will reject.
- After successful delete, the tweet's `tweet_results` is `{}` (empty dict — that IS success).

### Follow / unfollow
- Pass `handle` without `@`. The validator strips `@` if present.
- Following count updates with eventual consistency on X — don't validate by polling immediately.

## Error envelope

```json
{"ok": false, "schema_version": "1", "error": {
  "code": "write_failed", "message": "..."
}}
```

Common codes for write mode:
- `invalid_input` — bad text length, missing required, etc.
- `not_authenticated` — cookies expired
- `api_error` — X rejected (likely already in target state, or you don't own the tweet)
- `rate_limit` — backoff already exhausted

## What NOT to do

- Don't auto-confirm `--yes` because the user said "go ahead" earlier on a different action.
- Don't post on behalf of the user without showing the verbatim text.
- Don't loop `write.py follow` on a list of accounts in one shot — X rate-limits follow operations. For batch following (>3 accounts), use `follow_queue.py`: `add` each handle to the queue, then run `tick --max N` periodically (rate-limit-aware, 30–60s between calls). The queue persists across sessions and writes to the same audit log.
- Images / short videos: use `--media <file> [<file> ...]` (up to 4 files per tweet, images ≤5MB, gif ≤15MB, video ≤512MB).
- Don't try to DM via this skill — out of scope.

## Audit log format

`~/.config/x-cli/write-log.jsonl`, one entry per `--yes` call:

```json
{"ts": "2026-04-18T20:04:42+0800", "profile": "<profile>", "action": "post", "target": "<tweet_id>", "result": {...}}
```

Use this to review what was sent. To rotate, just `mv` it.
