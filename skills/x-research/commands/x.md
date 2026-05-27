---
description: "Research or act on X/Twitter with planning, x-cli execution, and safe write flows"
argument-hint: "[调研今天的 agent 新闻 / user karpathy / trend scan / draft reply...]"
---

Use the `x-research` skill and the installed `x-cli` binary for this X/Twitter task:

`$ARGUMENTS`

Default behavior:
- If this is a broad research request, load `references/search-plan.md`, derive the time window, choose follow-circle/keyword/trend/article sources, run the needed `x-cli` probes, and synthesize the findings.
- If the user asks for papers, extract paper/project links from X results and verify them with web/arXiv search when available.
- If this is a single account, tweet, search, list, like/bookmark/mention, or trend request, use the narrowest matching `x-cli` command.
- If this is a post/reply/follow/delete/list-change request, dry-run first and wait for explicit OK before any `--yes`.

If no argument was provided, offer examples:
- `/x 去 X 调研下今天的 agent 新闻，有啥论文也拿过来`
- `/x 看 @karpathy 这周发了什么`
- `/x trend scan`
