# Ranking Weights — How to Derive, Not What to Default

`rank.score(tweet, weights=..., boosts=...)` takes **no defaults**. Caller supplies the dict each time. This file teaches the LLM how to derive weight dicts per-domain/intent. No single set of weights is "right" — they depend on what you're optimizing for.

## The structure

```python
weights = {
    "likes":      <number>,   # broad-appeal signal
    "retweets":   <number>,   # amplify signal
    "replies":    <number>,   # conversation depth signal
    "bookmarks":  <number>,   # save-for-later quality signal
    "views_log":  <number>,   # eyeball reach (log-damped)
}
boosts = {
    "you_follow_author":      <multiplier>,  # trust net boost
    "is_article":             <multiplier>,  # long-form bonus
    "verified_not_followed":  <multiplier>,  # blue-check outside trust — usually <1
}
```

Unspecified keys default to 0 (ignored). `views_log` uses `log(views+1)`.

---

## Intent → weight rubric

| Intent | likes | retweets | replies | bookmarks | views_log | Rationale |
|---|---|---|---|---|---|---|
| **General high-signal briefing** | 1 | 3 | 2 | 5 | 0.5 | bookmarks are the best "I want to remember this" signal |
| **"What people are talking about"** (discussion) | 1 | 2 | **5** | 1 | 0.3 | replies weighted heavy — real conversation, not passive consumption |
| **"What's spreading"** (virality) | 1 | **5** | 0 | 1 | 1.0 | RT + views, replies ignored (noise) |
| **"What's worth reading"** (depth) | 0 | 1 | 1 | **10** | 0 | bookmarks dominate; likes/views are noise for quality |
| **"Fresh / developing"** (new thread) | 0 | 0 | 3 | 1 | 0 | replies count, ignore accumulated likes |

Use these as **starting points**, not formulas — modify weights based on what comes out of your initial probe.

---

## Boosts rubric

| Boost | Value range | When |
|---|---|---|
| `you_follow_author` | **5–15** | Your curated list is the strongest domain signal. Mid-range anchor: **10**. Raise toward 15 if your follow list is tightly domain-curated; lower toward 5 if broad/mixed. Derive from how selective your follows are. |
| `is_article` | **1.2–1.5** | Articles take effort to write — mild quality prior. Higher for "deep research" intent |
| `verified_not_followed` | **0.5–0.8** | Blue-check outside your trust net is weak/noisy. Demote. Skip this boost entirely if you don't want to penalize verified accounts |

Don't stack more than 3 boosts — hard to interpret the final score.

## author_diversity parameters

`rank.author_diversity(tweets, score_fn, *, decay, floor)` requires both:

| Param | Typical range | How to pick |
|---|---|---|
| `decay` | 0.5–0.8 | Controls how fast repeated-author penalty grows. 0.7 suits most domains. Lower (0.5) for very noisy domains where one person floods the feed. |
| `floor` | 0.2–0.5 | Minimum score multiplier — author's tweets never drop below `floor × original_score`. Raise to 0.5 for **niche communities** with few active voices (otherwise the same author's 3rd tweet gets buried unfairly). |

Starting point: `decay=0.7, floor=0.3`. Adjust based on community size — more voices → can afford lower floor.

---

## Domain calibration

Weights that work for one domain may fail for another.

### High-engagement domains (AI / crypto / politics)
- `likes` are inflated by viral mechanics → down-weight (1.0 is fine)
- `bookmarks` are purer signal → up-weight (5+)
- `views_log` useful because top tweets reach millions

### Mid-engagement domains (specific tools / mid-tier fandoms)
- Everything scales ~10× smaller; don't need to re-tune weights
- But `verified_not_followed` demotion less useful (fewer blue-checks)

### Low-engagement domains (niche research / small communities)
- `views_log` almost useless (most tweets <1000 views)
- Replies become PROPORTIONALLY more signal — a tweet with 20 replies in a small community is big
- Weight `replies` heavier than usual (3–5)

### Non-English domains
- Bookmarks signal may be weaker (cultural differences in saving habits)
- Likes still reliable
- Lower threshold bar across the board

---

## Example composition for a specific call

User asks: "我关注的 AI 研究者最近在辩论什么"

```python
# Intent: "what people are talking about" (discussion-heavy)
weights = {"likes": 1, "retweets": 2, "replies": 5, "bookmarks": 1, "views_log": 0.3}
# Boosts: strongly trust your curated follows (it's "my research network"),
# articles rare in replies so ignore that boost, verified demotion stays
boosts = {"you_follow_author": 12, "verified_not_followed": 0.6}
```

User asks: "Claude Opus 4.7 发布后大家反应如何"

```python
# Intent: virality + sentiment — fresh product launch
weights = {"likes": 1, "retweets": 5, "replies": 2, "bookmarks": 1, "views_log": 1.0}
boosts = {"you_follow_author": 8, "is_article": 1.3}
```

User asks: "帮我找关于 post-training 的深度文章"

```python
# Intent: depth. Bookmarks = the signal.
weights = {"likes": 0, "retweets": 1, "replies": 1, "bookmarks": 10, "views_log": 0}
boosts = {"you_follow_author": 5, "is_article": 1.5}
```

---

## Anti-pattern

❌ **Using the same weight dict for every call.** Every task has a different shape. Take 10 seconds to pick weights per-call.

❌ **Ignoring boosts.** `you_follow_author` is the single biggest quality win for any briefing. Always consider it.

❌ **Scoring without a plan.** If you can't articulate what the score is optimizing for, step back to Step 0 of `search-plan.md`.
