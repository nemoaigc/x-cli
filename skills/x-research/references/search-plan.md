# Search Plan — Multi-Source Pipeline + Domain Adaptation

**Core principle**: any "search" task = multi-source combination + domain-relevant filtering + LLM semantic synthesis. Whether the domain is AI / F1 / design / crypto / fashion / academia — the process is the same, but the specific values must be derived fresh each time.

This is the decision process to run for every search task.

---

## Four signal sources (domain-agnostic — always these 4)

| Source | Command | Signal | Blind spot |
|---|---|---|---|
| **A. Follow-circle** | `x-cli user <handle>` × N | Trusted voices, authentic takes, in-community reactions | People you don't follow; follow list itself is biased |
| **B. Keyword** | `x-cli search "<term>"` | What the broader network is discussing | Wrong keyword = missed signal; viral noise |
| **C. Trending** | `x-cli trend scan` → `--drill` | Algorithm-surfaced topics + KOLs | Personalized; coarse granularity |
| **D. Long-form** | `x-cli user <handle>` | Articles with highest signal density | Few people write articles; low frequency |

Each source has fixed blind spots. Any single source misses the other three.

---

## Step 0: Identify the domain (adaptive — this step is the key)

Extract from the user's question:
- **What domain?** (AI / F1 / crypto / design / photography / literature / football / ...)
- **Who are the domain insiders?** (don't assume — derive from the domain)
- **What are the domain's "hot topics/products" called?** (what terms did the user mention? if none, infer from recent events)
- **What's the rough engagement heat in this domain on X?**
  - Ultra-hot (AI / politics / crypto): viral = 5K–100K likes
  - Hot (mainstream products / top-tier sports): viral = 1K–10K
  - Medium (niche tech / second-tier hobby): viral = 100–1K
  - Cold (niche communities / professional): viral = 10–100
  - Ultra-cold (indie / academic niche): viral < 10 or no threshold

If the domain is unclear, **ask one clarifying question** before running: "Did you mean X or Y? Any example accounts?" Don't guess and run the wrong domain.

---

## Step 1: Identify domain-relevant follows (adaptive)

Not everyone you follow is in this domain. Run a follow-list filter:

```bash
# Check current profile (no --profile needed if using default)
x-cli auth list
# Pull follow list with bios; add --profile NAME only for multi-account setups
x-cli user <my_screen_name> --following --top 200 > /tmp/follows.json
```

Then read each follow's bio and pick the domain-relevant subset. Examples:
- AI domain: bio contains "researcher", "AI", "LLM", "ML", "Anthropic/OpenAI/Google DeepMind"
- F1 domain: bio contains "F1", "Formula", "motorsport", "paddock", team names
- Crypto: bio contains "crypto", "DeFi", "Bitcoin", "Ethereum", "Web3"
- Design: bio contains "designer", "UX", "UI", "brand", "visual"

Select top 5–15 relevant handles for Source A in Step 3.

**If the filter returns 0 handles**: your follow list doesn't cover this domain. Skip A, use B+C instead.

**If `--following` returns `ok: false`** (rate limit / private account / API transient): also skip A. Don't retry or stall — continue with B+C and note "follow-circle signal unavailable, reason: ..." in the report.

---

## Step 2: Pick the source combination

| Intent × domain heat | Which sources |
|---|---|
| Daily briefing ("what's happening in X today") | **A + C** (if hot, add B for new product names) |
| Weekly scan ("this week's big stories in X") | **B + A** (7-day window, higher threshold) |
| Deep research (full picture of a topic) | **B + D** (with `--auto-window`) |
| Single account activity | `--user` directly |
| What's trending right now | **C only** + drill |

No hard rules — judge by domain characteristics:
- Hot domain (AI): A alone is too narrow, add B to catch viral-that-escaped-the-circle
- Cold domain (academic): A is enough, B will filter out the niche results nobody engaged with

---

## Step 3: Derive parameters adaptively (not by lookup)

### 3a. How to pick keywords

Derive terms from the domain — don't copy examples verbatim:
- **Product / person names** have better recency signal than **technical terms**. "Claude Design" > "AI UI generator". "Hamilton" > "F1 driver".
- Pre-filter ambiguous terms ("Gemini" = constellation vs model; "Rust" = language vs corrosion)
- Mix English + the domain's local language

### 3b. How to set `--min-likes` (adaptive, not table lookup)

**Never use a fixed value.** Two steps:

```bash
# 1. Probe first — no --min-likes, see the actual engagement distribution
x-cli search "<core term>" --since <today> --top 30

# 2. Inspect likes p50/p90, then set threshold
# p90 at 10K+ → set --min-likes near p50 (usually 500–5K)
# p90 at 200–1K → set to 1.5–2× p50 (usually 30–200)
# p90 < 100 → niche/academic, don't set or set 5–10, use --top for volume control
# p90 = 0 / <5 results → query too narrow, restart from Step 0
```

### 3c. `--product` and time window

Pick based on the intent from Step 0:

| Intent | `--product` | Time window | Notes |
|---|---|---|---|
| Realtime (what's being said now) | `Latest` | 1–2d | Time-sorted, no engagement filter |
| Briefing / news scan | `Top` | 7–30d | Engagement-ranked |
| Deep research | `Top` | 30–180d + `--auto-window` | Window splitter avoids empty gaps |
| Single user / article | N/A | Use `--user` / `--user-articles` | No `--product` needed |
| Event reaction | `Top` then `Latest` | From event date | Two passes: viral + chronological |

Add `--auto-window` whenever the span exceeds 30 days. `read-mode.md` has the full flag rubric for edge cases — load it if the above table doesn't cover the situation.

---

## Step 4: Merge + filter + rank

→ Follow **`read-mode.md` Step 5** for the full ranking composition (filter_stack + author_diversity).
Pick `allowed_langs`, `spam_patterns`, `weights`, `boosts`, `decay`, `floor` from domain + intent — no code defaults. See `ranking-weights.md` for starting-point anchors.

---

## Step 5: LLM semantic synthesis (the most adaptive step)

This step cannot be done by heuristics — the LLM must read the content:

1. **Topic clustering**: merge multiple tweets about the same event into one bucket. Judge by content semantics, not keyword matching.
2. **Domain relevance filter**: even a trusted follow might post off-topic today (a CEO talking about childhood games). Remove.
3. **Pick the strongest per bucket**: prefer ⭐ followed authors + high engagement + actual opinion.
4. **Rank topics by importance**: official announcements > community commentary > viral > humor.
5. **Write the briefing**: each topic = 1 headline + 2–3 sentences + 2–3 tweet links.

---

## Worked Example 1:"今天 AI 圈发生了啥"

```
Step 0: 领域=AI,热度=超热(viral 10k+),语言=en+zh
Step 1: 从你的关注列表筛 bio 含 "AI/ML/LLM/research/Anthropic/OpenAI" 的
        → 实际数量运行时确定,挑 bio 匹配领域的子集
Step 2: 源 A(top 20 相关 follow 的 timeline)+ C(trend scan)
        + B(2-3 个今天的产品名:"Claude Design" "Opus 4.7")
Step 3: min-likes 先不设探测,看了 p90 后定 500;lang={"en","zh"}
Step 4: merge + rank.filter_stack + author_diversity → top 25
Step 5: LLM 读,聚主题(Claude Design / Opus 4.7 评价 / Codex / 其它),
        每主题 1-3 条,排序输出 markdown
```

## Worked Example 2:"这周 F1 圈在讨论什么"

```
Step 0: 领域=F1,热度=热(viral 5k+),语言=en 主 + es/pt/it 副(车手粉丝多语)
Step 1: 从关注列表筛 bio 含 "F1/Formula/motorsport/paddock/racing/MotoGP"
        → 如果我没关注 F1 人 → Step 1 筛出 0 个 → 跳过源 A,改用 B+C
Step 2: 源 B(关键词:"F1", "Grand Prix", 当前活跃车手名 "Leclerc" "Norris",
        近期话题 "contract" "penalty" "fastest lap")+ C(scan 看有无 F1 trend)
Step 3: --product Top,--since 7 days,先探测 min-likes(F1 p90 通常 2K+)
        lang 查询时不传,Step 4 再过滤
Step 4: rank.filter_stack(langs={"en","es","pt","it"},
                           spam_patterns=UNIVERSAL + SPORTS)
        SPORTS 已覆盖 "BREAKING 🚨 contract/deal/signing" 这类转会标题
Step 5: LLM 读,主题聚类(车手动态 / 车队 / 比赛事件 / 转会),
        剔除明显非 F1 内容,按重要性排
```

---

## Worked Example 3:"我关注的设计师最近在吐槽什么"

```
Step 0: 领域=设计,热度=中(viral 100-500),language=en+zh
Step 1: 筛 bio 含 "designer/UX/UI/Figma/brand/visual" → 可能 5-10 个
Step 2: 源 A 专用(用户明说"我关注的",别混 B)
Step 3: 不设 min-likes(设计圈互动不高),--since 7 days,--product Latest
Step 4: merge + rank.filter_stack(langs={"en","zh"})
Step 5: LLM 筛真"吐槽"语气的,按对象分桶(Figma / Adobe / AI 工具 / 客户 / 行业)
```

## Worked Example 4:"这周日语圈在讨论什么 AI 工具"(非英文 + 跨文化)

```
Step 0: 领域=AI 工具但**日语圈**视角。热度=中高(日语圈 viral 1K–5K likes,不是全球英文的那种 10K+)
Step 1: 筛 bio 里含日语 / "エンジニア" / "AI" / "デザイナー" 的关注者
        — 如果你的关注列表没覆盖日语圈 → 源 A = 0,转纯 B
Step 2: 源 B 为主,用日语 + 英文双语关键词("Claude 使い方", "GPT 活用", 英文产品名)
        + 源 C(scan 看 trending 里有没有日语 AI 相关)
Step 3: `--lang` 查询时不传(X 识别经常误把混合日英文标成 en),靠 Step 4 过滤
        min_likes 探测后可能设 200-500(日语圈比全球英文门槛低)
        窗口 7 天
Step 4: rank.filter_stack(langs={"ja"}),spam_patterns 只用 UNIVERSAL
        (日语圈没有稳定的 hustle 模板目录 — 别乱套英文的)
Step 5: LLM 读日语内容,主题聚类。注意:日语用户 "感想" 语气和英文 "Hot take" 不同
        权威性判断要按日语圈本地规范(职位头衔、公司归属等)
```

## Worked Example 5:"这个月学术圈在聊什么 post-training 新论文"(低热 + 深度)

```
Step 0: 领域=ML 学术研究。热度=冷(top 论文推通常 100-500 likes)。语言=en
Step 1: 筛 bio 含 "researcher/PhD/ICML/NeurIPS/@university" 的关注者 — 精而不是广
Step 2: 源 A(学术圈子)+ 源 D(Articles — 博客/论文解读)+ B("post-training" / "SFT" /
        "DPO" / 具体论文 ID)
Step 3: **不设 min-likes**(学者发论文解读可能 20-50 likes 就是 niche 顶部)
        --product Top,窗口 30 天
Step 4: rank.filter_stack(langs={"en"},spam_patterns=[]) ← 学术圈不要套模板过滤
        engagement_thresholds=None ← 学术推永远打不到 100K views,检查不起作用
        score weights 向 bookmarks 倾斜(研究者爱收藏论文推)
Step 5: LLM 按"论文 → 作者 → 机构"聚类,不按"热度"
```

---

## Anti-patterns (avoid in all domains)

❌ Single keyword query → 30 raw results — misses follow-circle, articles, and trending signals  
❌ Copy AI-sphere handles as default — breaks every other domain  
❌ Fixed `--min-likes 500` — filters out everything in niche domains  
❌ Skip `rank.filter_stack` — spam gets through  
❌ Skip Step 5 LLM synthesis — dumps 300 raw tweets at the user  
❌ Skip Step 0 clarification and just run — wrong domain means everything restarts
