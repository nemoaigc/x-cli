---
name: x-cli
description: >
  X/Twitter toolkit for reading tweets, timelines, articles, scanning trends, and writing
  (post/reply/quote/follow/like/block/delete). Load this skill whenever the user mentions
  Twitter, X, tweets, timelines, feeds, following, followers, trending topics, or any
  X-related account — even casually, like "看看X有啥", "scan my timeline", "draft a reply",
  "find someone on Twitter", "what's trending", "帮我发推", or "check what @someone posted".
  Also trigger when the user wants to engage with social media content (like, retweet, bookmark),
  research people/topics via their X presence, or draft social media posts in X's style.
  Three modes: read (search/fetch), trend (discover), write (post/engage). If there's even
  a slight chance the task touches X/Twitter, load this skill — it's cheap to load and
  expensive to skip.
---

# x-cli

X/Twitter toolkit for Claude Code. **Read + write** — but write operations are gated behind `--dry-run`/`--yes` and require user confirmation.

## Pick a mode

**Read mode** — user wants to search / scan / analyze X content (tweets, users, trends).

  Which references to load depends on the task:

  - **Simple lookup** (single user timeline, single tweet/article, follower list): read `references/read-mode.md` — it has the full flag rubric for a single `read.py` call.
  - **Research or multi-source scan** (briefing, topic scan, "what's happening with X"): read `references/search-plan.md` — it covers source selection, probe-first parameter derivation, and the `--product`/time-window decision. Load `references/read-mode.md` only for edge cases or detailed flag reference.
  - **Ranking / filtering**: after fetching, read `references/spam-patterns.md` (domain-bucketed regex catalog) and `references/ranking-weights.md` (per-intent weight rubric) to compose `rank.filter_stack` + `rank.author_diversity` parameters. No defaults — derive everything from domain + intent.

  Anti-pattern: single keyword query → 30 raw results. That loses the follow-circle signal, long-form articles, and trending context.

**Trend mode** — user is discovering: "what's hot right now on X".
  → Read `references/trend-mode.md`.

**Write mode** — user wants to post / reply / quote / delete tweets, or follow / unfollow accounts.
  → Read `references/write-mode.md`. **Always dry-run first; show the user the exact text/target; only `--yes` after explicit human OK.**

Engagement writes (like / retweet / bookmark) live in `me.py` — they're considered low-risk reactions and use the same `--yes` discipline.

Ambiguous case: treat as read mode; note in the report that trend/write modes are available.

## Prerequisites (shared)

- `uv` installed (`brew install uv` or `pip install uv`)
- Active X/Twitter browser session (Vivaldi, Chrome, or Edge) — cookies are read automatically
- First run: `uv run scripts/profile.py status` verifies auth

## Shared output shape

Scripts emit JSON envelopes to stdout, not pretty tables. Final deliverables are Markdown reports written to the current working directory:
- Read mode: `./x-cli-<slug>-<YYYYMMDD>/`
- Trend mode: `./x-trend-<YYYYMMDD>/`
- Write mode: no deliverable file; result is the action confirmation in stdout + audit log entry

## Other docs (load as needed)

- `references/LLMs.md` — full module map, all flags, failure-modes table (rate limit / auth expired / queryId rotated). Read on any non-happy-path error.
- `references/spam-patterns.md` — domain-bucketed regex catalog for `filter_stack`
- `references/ranking-weights.md` — per-intent weight + boost rubric, including `author_diversity` decay/floor guidance
- `references/trend-mode.md` / `references/write-mode.md` — mode details (SKILL.md is just the entry point)

## Skill location

Scripts live at `~/.claude/skills/x-cli/scripts/`. Always invoke via `uv run --project`:

```bash
# Read
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/read.py --query "..." --since YYYY-MM-DD --until YYYY-MM-DD --top 30
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/read.py --recommended-users karpathy --top 10
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/read.py --recommended-users --top 20
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/digest.py --scan

# Self
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/me.py status

# Write (note --dry-run is implicit; only fires with --yes)
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/write.py post --text "Hello"
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/write.py post --text "Hello" --yes
uv run --project ~/.claude/skills/x-cli ~/.claude/skills/x-cli/scripts/write.py follow karpathy --yes
```

## Write-mode discipline (TL;DR)

Never auto-`--yes`. Dry-run → show user verbatim → wait for explicit OK → then `--yes`. Audit log at `~/.config/x-cli/write-log.jsonl`.

**Full discipline + edge cases**: see `references/write-mode.md` (canonical).

## Non-goals

- DM (private messages) — out of scope (privacy/ethics)
- Real-time streaming — batch only
- Communities, Spaces operations — deferred
- Scheduled tweets / bookmark folders — X Premium only, deferred
