# x-cli

An X/Twitter skill for agents.

Ask your agent to use the `x-cli` skill for X/Twitter tasks: reading timelines,
searching posts, fetching X Articles, scanning trends, or drafting guarded write
actions. In normal use, the agent loads `SKILL.md` and calls the bundled scripts
internally.

This project is derived from
[twitter-cli](https://github.com/public-clis/twitter-cli) by
[@jackwener](https://github.com/jackwener), licensed under Apache-2.0. See
`NOTICE.md`.

## Install

Put this folder in your agent's skills directory as `x-cli`.

For example:

```bash
~/.claude/skills/x-cli/
```

Then ask the agent for X/Twitter work directly, such as:

- "Use x-cli to see what my AI timeline is discussing."
- "Search X for today's OpenAI news."
- "Draft a reply to this tweet."
- "Scan current X trends."

## Authentication

x-cli uses your X/Twitter web session. It supports:

- automatic browser cookie extraction from Vivaldi, Chrome, or Edge
- saved local profiles under `~/.config/x-cli/profiles/`
- manual `auth_token` + `ct0` values when needed

The usual setup is:

1. Log in to `x.com` in a supported browser.
2. Ask your agent to verify x-cli auth.
3. Optionally ask it to save the current browser session as a named profile.

Manual token setup is only for advanced users. If used, save `auth_token` and
`ct0` locally as a profile; never paste real cookie values into prompts,
documents, issues, or commits.

## Safety

Write actions dry-run first and require explicit approval before execution.

Do not share saved profiles, `.env` files, browser cookie databases, or other
local auth/cache state.
