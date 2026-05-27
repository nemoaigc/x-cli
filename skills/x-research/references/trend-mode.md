# Trend Mode — Explore & Drill

Use when the user wants to discover what's trending on X right now.

## Triggers

"X 今天有啥", "扫一下 X 热点", "what's trending on X", "X 上有什么新鲜事",
"看看今天 X 的热点", "browse X trends", "what's hot on Twitter".

## Step 1: Scan

```bash
x-cli trend scan
```

This pulls ExplorePage (for-you tab) + news / sports / entertainment / trending tabs in parallel,
deduplicates by name, and returns a merged list sorted by `postCount × (2 if isAiTrend else 1)`.

Each trend item: `name`, `trend_id`, `is_ai_trend`, `age_text`, `category`, `post_count`, `facepile_images`.

## Step 2: Present to user

Show 15–20 top trends in a concise list:
- Name, category, post count, whether it's an AI-curated trend
- Call out 3 highest-signal candidates with one sentence of context each

Ask: "Which trend do you want to drill into, or is the overview enough?"

If `trend_id` is empty for a trend (non-AI trends sometimes lack it), note that drill won't work
for that one and suggest searching it in query mode instead.

## Step 3: Drill (on user's choice)

```bash
x-cli trend drill <trend_id>
```

Returns:
- `kols`: list of UserProfile (KOLs relevant to this trend via TrendRelevantUsers)
- `tweets`: top tweets from search on the trend name

For top 3 KOLs, optionally fetch their articles:
```bash
x-cli user <handle> --articles
```

## Step 4: Write deliverables

Output dir: `./x-trend-<YYYYMMDD>/`

- `overview.md` — full trend list summary
- `trend-<slug>.md` — KOLs, top tweets, article links for the drilled trend
- `articles/<id>.md` — expanded article content (if fetched)

## Step 5: Hand off

1. Print path to `overview.md` (and `trend-<slug>.md` if drilled)
2. 2–3 sentence summary of what was found
3. Offer: "Want to drill into another trend, or switch to query mode for a specific topic?"

## Notes

- Scan-only is a valid outcome — not every session needs a drill
- If TrendRelevantUsers returns empty (non-AI trend), fall back to search + top-liked tweets
- `--scan-drill-top N` combines scan + auto-drill in one call (useful for autonomous research)
