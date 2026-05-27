---
description: "Alias for /x: research or act on X/Twitter using the X skill"
argument-hint: "[search, user, tweet, trend, draft, post, follow, like...]"
---

Use the `x-research` skill and the installed `x-cli` binary to handle this X/Twitter task:

`$ARGUMENTS`

Routing:
- For broad research, load `references/search-plan.md`, derive the time window, probe sources, then synthesize a report.
- For search, accounts, timelines, tweets, lists, likes, bookmarks, or mentions, use read mode.
- For current topics or discovery, use trend mode.
- For posts, replies, quotes, follows, deletes, or list changes, use write mode.

Rules:
- Prefer the existing authenticated profile unless the user names another profile.
- Keep all write actions dry-run first. Show the exact text, target, and command before using `--yes`.
- `engage like`, `engage retweet`, and `engage bookmark` execute immediately, so only run them when the user explicitly requests that action.
- If no argument was provided, show three concise examples for `/x` and ask what X/Twitter task to run.
