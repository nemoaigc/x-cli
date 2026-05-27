# Read Mode — Search, Timelines, Articles

Use when the user wants to pull tweets from X for reading / analysis — by topic, user, list, or thread.

## Triggers

"X 上 XXX 话题", "scan X for XXX", "analyze discussion of XXX on X", "collect X articles about XXX",
"看看 X 上 XXX", "X 上最近 XXX 怎么说的", "抓一下 XXX 话题", "X 今天在聊啥", "@user 最近发了啥",
any X search-box style query + optional time range.

---

## Step 0 — Understand user intent(THE IMPORTANT STEP)

Before touching any flag, classify the request into one of these intents. Each intent has different correct filter values.

| Intent | 例 | Time window | `--product` | `--min-likes` | Sort by |
|---|---|---|---|---|---|
| **A. 重大新闻扫描** (what matters this week/month) | "本周 AI 圈大事"/"Anthropic 这个月的新闻" | 7–30d | `Top` | **500–2000** for hot domains,**50–200** for niche | Engagement × log(age-decay) |
| **B. 实时感知** (what's being said right now) | "X 现在在聊 XXX"/"今天的讨论"/"最新态度" | 1–2d | `Latest` | **低 / 不设** | Time DESC |
| **C. 深度话题研究** (gather all signal over period) | "过去 3 个月 AI Agent 讨论全貌" | 30–180d + `--auto-window` | `Top` | **50–200** | Engagement + article boost |
| **D. 某个人/账号** | "karpathy 最近说啥"/"@xxx 的 articles"/"karpathy 最近点赞了啥" | N/A | N/A | N/A | Use `--user` / `--user-articles` / `--user-likes` |
| **E. 跟踪特定热点** | "Opus 4.7 发布后的反应" | 从事件开始日期 | `Top` 或 `Latest` 两轮 | **100–500** | 按时间 chunks 看演变 |
| **F. 圈内视角优先** (你关注的人在说啥) | "我订阅的 AI 圈怎么看 XXX" | 任意 | `Top` | **低**(别漏了) | 后处理 filter `you_follow_author=True` |
| **G. Custom Timeline** (X 算法策展的话题 feed) | "我的 AI timeline 最近有啥"/"看看 Software feed" | N/A | N/A | N/A | Use `--feed AI` / `--feed Software`; 先 `--feeds` 查可用列表 |

**If intent is ambiguous, ask one clarifying question before running.** Example: "Do you want the most influential posts this week, or what's actively being discussed right now?"

---

## Step 1 — Choose `--min-likes` by **probing, not by lookup**

This is the highest-leverage signal-to-noise control. **Always probe first, never look up from a table.**

### Protocol

```bash
# 1. Probe without --min-likes to see the actual engagement distribution
x-cli search "<term>" --since <today> --until <tomorrow> --top 30
```

Inspect the returned `likes` distribution:

```python
import json
d = json.load(open("probe.json"))
likes = sorted([t["metrics"]["likes"] for t in d["data"]], reverse=True)
# p50 = typical; p90 = how hot this topic actually is right now
```

Decision:
- p90 ≥ 10K → genuinely viral, set `--min-likes` near **p50** (usually 500–5K)
- p90 200–1K → medium heat, set to **1.5–2× p50** (usually 30–200)
- p90 < 100 → niche / academic, **don't set or set 5–10**, use `--top` for volume control
- p90 = 0 / fewer than 5 results → query too narrow, restart from Step 0

### Reference anchors (rough priors only — probe results take precedence)

| p90 量级 | 建议初始 min-likes | 说明 |
|---|---|---|
| 10K+ | p50 附近 | viral 话题 |
| 200–1000 | p50 × 1.5 | 常见热话题 |
| 20–200 | 5–30 或不设 | 细分 / 爱好 / 专业 |
| <20 | **不设** | niche / 学术 / 个人 |

**Anti-pattern**: searching for "a scholar's recent tweets" with `--min-likes 100` — most academic tweets get under 100 likes and will be filtered out entirely. Probe first, then decide.

---

## Step 2 — Choose `--product`

| 选 | 语义 | 用在 |
|---|---|---|
| `Top`(默认) | X 算法认为"相关 + 重要"的推文,通常是高互动量的,即便是 3 天前的 | 本周热点 / 某话题的代表性讨论 / 深度研究 |
| `Latest` | 严格按时间倒序,最新的在前 | 实时感知 / "刚刚发生了什么" / 事件发酵中 |

**组合技**:同一话题跑两遍(`Top` 拿代表性 + `Latest` 拿最新态度),合并去重。

---

## Step 3 — Choose time window

**转换用户的相对时间描述为 `--since` / `--until`**:

| 用户说 | --since | --until |
|---|---|---|
| "今天" / "现在" / "正在聊" | 前 1 天 | 今天 |
| "昨天" | 前 2 天 | 今天 |
| "本周" / "最近一周" / "近期" | 前 7 天 | 今天 |
| "过去一个月" / "最近" | 前 30 天 | 今天 |
| "过去三个月" / "Q1" | 前 90 天 | 今天 |
| "今年以来" | 当年 1-1 | 今天 |
| "X 事件之后" | 事件发生日 | 今天 |

**跨度 >30 天一定加 `--auto-window`** — 否则 X 单查询硬上限 100 会漏掉大量内容。

---

## Step 4 — Run the query

```bash
x-cli read \
  --query "<query verbatim>" \
  --since YYYY-MM-DD \
  --until YYYY-MM-DD \
  --top 30 \
  [--product Top|Latest] \
  [--min-likes N] \
  [--lang zh] \
  [--from-user HANDLE] \
  [--auto-window]
```

Other `x-cli` (read commands) modes (no `--query` needed):
- `--user HANDLE` 用户最新推文
- `--user-likes HANDLE` 用户点赞的推文
- `--user-articles HANDLE` 用户 Articles 标签页(长文)
- `--user-replies HANDLE` 用户 replies
- `--user-media HANDLE` 用户媒体
- `--user-highlights HANDLE` 用户高亮
- `--tweet ID` 单条 + 主线程
- `--article ID` 展开某 Article 正文
- `--batch ID1 ID2 ...` 按 ID 批量拉
- `--expand-articles` 对列表结果中的 `is_article=True` 条目补取完整 article title/text；默认不启用，避免普通扫描变慢
- `--followers HANDLE` / `--following HANDLE` 粉丝 / 关注
- `--list LIST_ID` list 时间线
- `--feed for-you|following|<custom_name>` 主时间线或自定义 timeline（如 `--feed AI`）
- `--feed ... --min-articles 3 --min-posts 2 --max-pages 5 --expand-articles` 从 timeline 抓候选时使用：Article 不够就自动翻页；只返回凑齐配额的候选集；`--min-posts` 统计非 Article 的普通 Post/Note；`--max-pages` 防止无限翻
- `--feeds` 列出当前账号所有 pinned custom timelines

---

## Step 5 — Rank and filter (post-processing quality layer)

**⚡ rank.py has no defaults.** Every call requires you to compose `spam_patterns` / `weights` / `boosts` from the domain + intent. Reference catalogs:
- `references/spam-patterns.md` — domain-bucketed regex catalog
- `references/ranking-weights.md` — per-intent weight rubric (discussion vs virality vs depth)

Minimal composition:

```python
from scripts._core import rank
# 这 4 个 dict 每次按领域/意图重写,不是"默认":
allowed_langs  = {"en", "zh"}
spam_patterns  = UNIVERSAL + AI_SPHERE     # 从 spam-patterns.md 按领域挑
weights        = {"likes": 1, "retweets": 3, "replies": 2, "bookmarks": 5, "views_log": 0.5}
boosts         = {"you_follow_author": 10, "is_article": 1.3}

clean = rank.filter_stack(tweets, allowed_langs=allowed_langs,
                          spam_patterns=spam_patterns, drop_promoted=True)
score_fn = lambda t: rank.score(t, weights=weights, boosts=boosts)
top = rank.rank_tweets(clean, score_fn=score_fn)[:15]
# 可选:同作者衰减
diverse = rank.author_diversity(clean, score_fn=score_fn, decay=0.7, floor=0.3)[:15]
# niche domains (few active voices): raise floor to 0.5 to avoid over-penalizing
```

Tweet object structure:
```
id, text, author.{id,name,screen_name,verified}, metrics.{likes,retweets,replies,views,bookmarks},
created_at, content_kind, is_article, is_note_tweet, article_title, article_text, urls, lang,
you_follow_author  ← True/False/None,表示当前 profile 是否关注该作者

`content_kind` 是输出层派生字段：`tweet` / `note_tweet` / `article`。用于下游展示和筛选，不要用账号、标题或 URL 硬编码判断类型。
```

### 5a. Language filter

Passing `--lang` to X search is occasionally inaccurate (X misidentifies languages). More reliable: **don't pass `--lang` at query time, filter locally after fetching.** `filter_lang` retains `und` (unidentified by X) by default to avoid false drops.

How to pick the language set:
- English-sphere products (AI / crypto / SaaS): `{"en"}` or `{"en","zh"}`
- Chinese community: `{"zh"}`
- Cross-cultural sports / multi-national fanbase: `{"en","es","pt","it","ja"}` — pick by community
- If unsure: don't filter first; inspect the returned `lang` distribution, then decide

### 5b. Quality filter (spam + engagement ratio)

Two independent primitives — **compose them yourself** (no combined `is_likely_spam` helper — removed to prevent implicit defaults):

- `rank.is_template_spam(text, patterns)` — patterns 必传(空 list = 跳过)
- `rank.is_low_engagement_ratio(metrics, *, min_views_for_like_check, min_like_to_view, min_likes_for_reply_check, min_reply_to_like)` — 4 个阈值全必传

组合示例:
```python
is_spam = (
    rank.is_template_spam(t.get("text") or "", patterns)
    or rank.is_low_engagement_ratio(t.get("metrics") or {}, **thresholds)
)
```

More commonly, use `rank.filter_stack(..., spam_patterns=..., engagement_thresholds=...)` in one call.

Pick 3–8 patterns from `references/spam-patterns.md` per domain — don't pass everything (causes false drops). For thresholds: set `engagement_thresholds=None` for academic / niche domains where views never reach 100K.

### 5c. Scoring and weights

- `rank.score(tweet, weights=..., boosts=...)` — weights required
- See `references/ranking-weights.md` for per-intent rubric (discussion / virality / depth use different weights)
- One near-universal heuristic: if the user has a follow list, set `boosts["you_follow_author"]` to 5–15; if they don't, skip this boost

### 5d. Topic deduplication (prevent one event flooding the top)

The same topic often appears in 5–10 paraphrase tweets occupying top positions. Read top-30 texts yourself and merge semantically equivalent ones into one bucket, keeping only the strongest per bucket.

**Don't bucket by keyword** — "Claude Design" and "Claude Opus 4.7" both contain "Claude" but belong in different buckets. LLM semantic reading is more accurate.

### 5e. Intent-based secondary filter

- Keep only `you_follow_author=True`: follow-circle perspective (Intent F)
- Keep only `is_article=True`: long-form only
- Drop retweets (`is_retweet=False`)
- Drop `is_promoted=True` (X ad slots)

---

## Step 6 — Write deliverables

Default output dir: `./x-cli-<slug>-<YYYYMMDD>/` (slug = first few words of query, spaces removed).

Files:
- `report.md` — briefing containing:
  - Meta: query, time window, filters applied, total returned, post-dedup count, followed-author ratio
  - **Topic groups**: classified by LLM reading content (not keyword matching — "Claude Design launch" tweets should not be grouped into the "Claude Opus" bucket)
  - **Top 10–20 ranked**: each with engagement metrics + followed-author flag + text + link
  - Optional: fetch key tweet's thread context
- `articles/<id>.md` — each expanded long-form article
- `raw/*.json` — raw API responses (for inspection)

---

## Edge cases

- **0 results**: query too narrow / window too short / `--min-likes` too high. Remove `--min-likes` first, then widen the query.
- **Too much noise**: `--min-likes` too low or query too broad. Raise threshold / add `from:` / add `-filter:retweets`.
- **Rate limit**: script has exponential backoff. If exhausted, wait 10–15 min.
- **Non-ASCII**: pass Chinese/Japanese/Korean directly — X supports native Unicode.

---

## Summary for LLM caller

Before every `x-cli` (read commands) call, answer three questions:

1. **Does the user want "what mattered this week" or "what's being discussed right now"?** → decides `--product` and time window
2. **How hot is the topic?** → decides `--min-likes` (probe first per Step 1)
3. **Time span > 30 days?** → must add `--auto-window`

When unsure, **ask one clarifying question** rather than guessing.
