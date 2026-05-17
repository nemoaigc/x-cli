# NOTICE

x-query
Copyright 2026 nemoaigc

This product includes software developed by jackwener as part of the
[twitter-cli](https://github.com/public-clis/twitter-cli) project.

Portions of this work are derivative of twitter-cli:

  twitter-cli
  Copyright jackwener <jakevingoo@gmail.com>
  Licensed under the Apache License, Version 2.0 (the "License");
  see the accompanying LICENSE file.

## Summary of modifications from upstream

### Inherited fixes (from x-cli, which is also a derivative)

- Adapted parser/client to Twitter API schema migration of April 2026:
  user fields moved from `legacy{}` to top-level objects (`core{}`,
  `avatar{}`, `location{}`); 15 of 20 fallback queryIds refreshed.
- Added `UserArticlesTweets`, `UserTweetsAndReplies`, `UserMedia`,
  `UserHighlightsTweets`, `SearchTimeline` (People product) support.
- `isArticle` / `isNoteTweet` fields on `Tweet`.

### New functionality in x-query

- Rewritten as a Claude Code skill (no CLI binary, invoked via `uv run`).
- Replaced Click+Rich with argparse + JSON/YAML machine output.
- Added `explore.py` for X Explore/Trends scraping (ExplorePage + GenericTimelineById).
- Added `profiles.py` for multi-account cookie management.
- Added `digest.py` entry point (trend scan + drill).
- Added `me.py` entry point (self-scoped reads + engagement writes).
- Engagement writes in scope: like/unlike, retweet/unretweet, bookmark/unbookmark.
- Content-creation writes (post/reply/quote/delete) and social-graph writes (follow/unfollow) are out of scope.
