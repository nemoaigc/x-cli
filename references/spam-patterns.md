# Spam Pattern Catalog — Domain-Adapted

**Purpose**: `rank.is_template_spam` takes a `patterns` list. This catalog is the LLM's reference for composing that list **per-domain**. Do **not** pass everything — pick what matches your domain.

## How to use

1. Identify the domain from user intent (AI / crypto / F1 / design / fashion / academic / politics / …).
2. Start with the **universal** patterns (apply to all domains).
3. Add the **domain-specific** patterns relevant to your current query.
4. Skip patterns that don't apply — extra patterns = false positives.
5. If the domain isn't listed below, scan the top 50 fetched tweets yourself and derive patterns from what looks like template farming.

```python
from scripts._core import rank

patterns = UNIVERSAL + AI_SPHERE  # compose, don't hardcode
clean = rank.filter_stack(tweets, allowed_langs={"en","zh"}, spam_patterns=patterns)
```

---

## Universal (any domain)

These are format/behavior templates, not topic-tied. Most catch "engagement farming" patterns that appear in every domain.

```python
UNIVERSAL = [
    r"🚨\s*breaking",                                      # fake-breaking-news framing
    r"🧵\s*1\s*/",                                         # thread hook
    r"this (will )?blow your mind",
    r"this is insane(\s|!|$)",
    r"99%\s*of\s*(people|devs)\s*don'?t\s*know",
    r"most\s*people\s*don'?t\s*know",
    r"you won'?t believe",
    r"going viral",
    r"(bookmark|retweet|share)\s*this\s*(post|thread)",
    r"save\s*this\s*post",
    r"✨\s*here'?s\s*(how|what)",
    r"here'?s\s*the\s*secret",
    r"\bbanger\b",
    r"\babsolute\s*banging\b",
]
```

---

## AI / LLM / ML sphere

```python
AI_SPHERE = [
    r"instead of (watching|scrolling) .{0,40}(netflix|tiktok|instagram|youtube)",
    r"🔥\s*\d+\s*(free\s*)?(ai\s*)?(tools|tips|prompts)",
    r"\bhere are \d+\s*(ai\s*)?(tools|tips|prompts|ways)",
    r"\b(use|try)\s*this\s*prompt",
    r"steal\s*my\s*(prompt|workflow)",
]
```

## Money / Hustle / Make-money-online (multi-domain but common)

```python
HUSTLE = [
    r"\$\d+\s*(per|a|/)?\s*day",
    r"\$\d+k?\s*(a|per|/)\s*(month|week|day)",
    r"(it cost|it was free|but it'?s free)",
    r"^\s*\d+\.\s*.+\n.*\d+\.\s*",                        # numbered-list thread
    r"passive\s*income",
]
```

## Crypto / Web3

```python
CRYPTO = [
    r"💎\s*\d+\s*x",
    r"\bmoonshot\b",
    r"\bape\s+in\b",
    r"\bNFA\s*DYOR\b",
    r"\b100x\s+gem\b",
    r"\bpresale\s+(live|open)\b",
    r"🔥\s*(early|new)\s*project",
]
```

## Fashion / Lifestyle

```python
FASHION = [
    r"^\s*OOTD\b",
    r"\bhaul\s+\d+\s*items\b",
    r"^\s*get ready with me\b",
    r"\baesthetic\s+vibes\b",
]
```

## Sports (F1 / football / etc.)

```python
SPORTS = [
    r"BREAKING\s*🚨\s*(contract|deal|signing)",
    r"✅\s*confirmed\s*(move|transfer|signing)",
    r"\bexclusive\s*🚨",
    r"\bHERE\s*WE\s*GO\b",                                 # Fabrizio Romano meme hijack
]
```

## Politics / News

```python
POLITICS = [
    r"^\s*BREAKING\s*[:—-]",
    r"\bMUST\s*WATCH\b",
    r"\bRIGHT\s*NOW\b",
    r"the media (won'?t|isn'?t) tell(ing)? you",
]
```

## Self-help / Productivity / Motivation

```python
SELF_HELP = [
    r"wake up at 5am",
    r"^\s*\d+\s*habits\s*of",
    r"unpopular opinion\s*:",
    r"(12|10)\s*things\s*i\s*wish",
]
```

## Chinese-language hustle (跨领域)

```python
CN_HUSTLE = [
    r"核心思路[:：]",            # 极简教程模板
    r"^\s*Step\s*\d+[:：]",       # numbered-tutorial hook
    r"只需\d+步",
    r"小白都能(用|会)",
    r"保姆级(教程|指南)",
    r"收藏了",                    # explicit "bookmark this" nudge
    r"我用[AI|Claude|GPT].{0,20}赚",  # money hustle
]
```

---

## Domains intentionally NOT listed

Academic research, poetry, regional/local news, food/recipe, children's media, photography, independent music — these **don't have stable template-spam signatures**. Passing `patterns=[]` (i.e. skip template check entirely) is correct. For these domains, spam rarely comes from engagement-farming templates; it comes from bots / paid impressions, which `is_low_engagement_ratio` catches better than regex.

If you're querying a domain that has the "feel" of a research / creative / niche community where people post in normal prose — default to **no template patterns**, let engagement-ratio + your own Step 5 LLM read do the filtering.

## Deriving your own (when catalog doesn't cover)

1. Run the search without `spam_patterns` first.
2. Manually eyeball the top 50 by engagement.
3. Look for repeated **structural** signatures across low-content viral tweets (emoji-prefix, "X tricks", "Stop doing Y", numbered hustle lists, thread hooks).
4. Encode 3-8 regex and plug into `patterns`.
5. Re-run to validate — spot-check what got dropped (cheaply: `grep -f` top 50 against the dropped set).

Don't overfit: 3-8 patterns per domain is usually enough. More than 15 starts producing false positives (real content that happens to share surface form).
