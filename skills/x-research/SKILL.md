---
name: x-research
description: >
  Use for any X/Twitter task, especially Chinese requests like "去 X 上调研一下",
  "看看 X 今天 agent/AI/crypto/design 圈发生了什么", "搜一下推特", "看某账号最近发了啥",
  "找 X 上的论文/项目/新闻线索", "帮我写/发/回复一条推". This is an agent-facing
  X research and action workflow: plan the source mix, derive the time window,
  choose keywords/accounts/trends, call the installed x-cli binary, then synthesize
  a report. Also use for timelines, tweets, feeds, follows/followers, trending topics,
  likes/retweets/bookmarks, posts, replies, quotes, follows, deletes, and X-style drafts.
---

# X Research

Agent skill for researching and acting on X/Twitter. The installed
[`x-cli`](https://github.com/nemoaigc/x-cli) binary is only the execution engine;
this skill owns the planning: source selection, time window, keyword/account
choice, trend checks, ranking/filtering, synthesis, and write safety.

## Default behavior

When the user asks to "go to X", "search Twitter", "look up tweets", "check an
account", "research today's news", "find papers from X", or similar, load this
skill and proceed. Do not ask whether to use `x-cli` when the X/Twitter intent is
clear.

For broad research requests, first state a compact execution plan, then run it:

0. If no topic/account/domain/time window is provided, ask for the missing
   research target. Never invent a default topic.
1. Resolve the domain and time window from the prompt.
   - "today" = current local date.
   - "this week" = last 7 days unless the user gives exact dates.
   - "recent/latest" = last 2-7 days, adjusted by domain velocity.
2. Load `references/search-plan.md`.
3. Write a short research plan before executing. Include:
   - Objective and scope
   - Time window, with exact dates when relative dates are used
   - Source mix: follow-circle, keyword search, trend scan, long-form/articles
   - Candidate queries/accounts/trends to probe
   - Paper/project verification path when relevant
   - Deliverable shape
4. Probe sources before committing to thresholds: follow-circle, keyword search,
   trend scan, and long-form/articles when relevant.
5. Synthesize topics semantically. Do not dump raw tweets.
6. If the user asks for papers, extract arXiv/OpenReview/PDF/project links from X
   results and verify them with web/arXiv search when available.

If the user asks for a plan, strategy, or "先写计划", stop after the plan and
wait for approval. Otherwise proceed after showing the compact plan.

Only ask a clarifying question when the domain is genuinely ambiguous enough that
running would likely collect the wrong corpus.

## Pick a mode

**Read mode** — user wants to search / scan / analyze X content.

  Which references to load depends on the task:

  - **Simple lookup** (single user timeline, single tweet/article, follower list):
    read `references/read-mode.md` — flag rubric for a single `x-cli` call.
- **Research or multi-source scan** (briefing, topic scan, "what's happening with X"):
    read `references/search-plan.md` — source selection, probe-first parameter derivation,
    `--product`/time-window decision. Load `references/read-mode.md` only for edge-case flags.
    Always write the compact research plan before the first `x-cli` data command.
  - **Ranking / filtering**: after fetching, read `references/spam-patterns.md`
    (domain-bucketed regex catalog) and `references/ranking-weights.md`
    (per-intent weight rubric) to compose `rank.filter_stack` + `rank.author_diversity`
    parameters. No defaults — derive from domain + intent.

  Anti-pattern: single keyword query → 30 raw results. Loses the follow-circle signal,
  long-form articles, and trending context.

**Trend mode** — user is discovering: "what's hot right now on X".
  → Read `references/trend-mode.md`.

**Write mode** — user wants to post / reply / quote / delete tweets, or follow / unfollow accounts.
  → Read `references/write-mode.md`. **Always dry-run first; show the user the exact
  text/target; only `--yes` after explicit human OK.**

Engagement writes (`x-cli engage like/retweet/bookmark`) execute immediately — they're
low-risk reactions, no `--yes` gate.

Ambiguous case: treat as read mode and mention trend/write modes only if useful.

## Prerequisites

- `x-cli` installed: `pip install -e .` from [github.com/nemoaigc/x-cli](https://github.com/nemoaigc/x-cli)
- Auth: either a saved profile (`x-cli auth add NAME`) or `TWITTER_AUTH_TOKEN` +
  `TWITTER_CT0` env vars
- First run: `x-cli auth status` verifies auth

## Output shape

Every `x-cli` invocation emits JSON to stdout:

```json
{"ok": true,  "schema_version": "1", "data": {...}}
{"ok": false, "schema_version": "1", "error": {"code": "...", "message": "..."}}
```

Final deliverables for the skill are Markdown reports written to the working directory:
- Read mode: `./x-research-<slug>-<YYYYMMDD>/`
- Trend mode: `./x-trend-<YYYYMMDD>/`
- Write mode: no deliverable file; result is the action confirmation in stdout + audit log

## Other docs (load as needed)

- `references/LLMs.md` — full command map, all flags, failure-modes table.
  Read on any non-happy-path error.
- `references/spam-patterns.md` — domain-bucketed regex catalog
- `references/ranking-weights.md` — per-intent weight + boost rubric, including
  `author_diversity` decay/floor guidance
- `references/trend-mode.md` / `references/write-mode.md` — mode-specific details

## Quick-reference invocation cheatsheet

```bash
# Read
x-cli search "claude code" --since 2026-05-10 --until 2026-05-17 --top 30
x-cli user karpathy --recommended --top 10
x-cli user --recommended --top 20            # general recs (no handle)
x-cli trend scan

# Self
x-cli me status
x-cli me health
x-cli me likes --max 50

# Write (--dry-run is the default; --yes actually executes)
x-cli post --text "Hello"
x-cli post --text "Hello" --yes
x-cli follow add karpathy --yes
x-cli engage like 1234567890                # no --yes gate (immediate)
```

## Write-mode discipline (TL;DR)

Never auto-`--yes` on `post`/`follow`/`x-list`. Dry-run → show user verbatim → wait
for explicit OK → then `--yes`. Audit log at `~/.config/x-cli/write-log.jsonl`.

Full discipline + edge cases: see `references/write-mode.md`.

## Non-goals

- DM (private messages) — out of scope (privacy/ethics)
- Real-time streaming — batch only
- Communities, Spaces operations — deferred
- Scheduled tweets / bookmark folders — X Premium only, deferred
