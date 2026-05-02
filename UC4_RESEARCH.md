# UC4 — AI research agent

## Purpose

Weekly AI-powered content research assistant for the YouTube channel. Monitors audiophile community sources for emerging and trending topics. Cross-references findings against the channel's existing video library and evergreen performers. Generates strategic video ideas with script treatments. Surfaces community buzz topics for use as on-camera reference material.

---

## Schedule

Every Tuesday, automated run via APScheduler.

---

## Data flow

```
Scheduler trigger (every Tuesday)
  → Scrape sources in parallel:
      → Reddit (r/audiophile, r/vinyl, r/hometheater, r/vintageaudio)
      → Forums (AudioScienceReview, Head-Fi, AudiophileStyle)
      → Publications (Stereophile, The Absolute Sound, What Hi-Fi)
      → YouTube trending (audio/audiophile niche search)
  → Normalize and deduplicate across sources
  → AI analysis — two parallel tracks:
      → Spike detection: topics surging this week vs last week
      → Trend detection: topics appearing consistently across multiple weeks
  → Pull channel evergreen data from Postgres
      → Identify videos: 1,000+ avg monthly views, 6+ consecutive months
      → Update channel_evergreen table
  → Cross-reference discovered topics against existing video library
      → Flag: already covered
      → Flag: refresh candidate (covered 2+ years ago)
  → AI synthesis:
      → Generate script treatment per strategic topic (150-200 words)
      → Suggest video format (review, comparison, how-to, teardown)
      → Note evergreen connection where applicable
  → Select 3-6 current chatter topics
      → Write 2-3 sentence community digest per topic
      → Include source links
  → Save all results to Postgres under new research_run record
  → Streamlit UI reflects new run results
```

---

## Sources

### Reddit
- Subreddits: `r/audiophile`, `r/vinyl`, `r/hometheater`, `r/vintageaudio`
- Use Reddit API (PRAW library) — free, requires app registration
- Fetch: top posts from past 7 days, sorted by upvotes
- Capture: post title, body, comment count, upvote count, URL

### Forums
- **AudioScienceReview** (audiosciencereview.com) — web scraping, recent threads section
- **Head-Fi** (head-fi.org) — web scraping, recent posts
- **AudiophileStyle** (audiophilestyle.com) — web scraping, recent discussions
- Scraping: use `httpx` + `BeautifulSoup`, respect `robots.txt`, 2-second delay between requests
- Capture: thread title, post count, last activity date, URL

### Publications
- **Stereophile** (stereophile.com) — RSS feed available
- **The Absolute Sound** (theabsolutesound.com) — RSS feed available
- **What Hi-Fi** (whathifi.com) — RSS feed available
- Use `feedparser` library — clean, no scraping needed
- Capture: article title, summary, published date, URL

### YouTube trending
- Use YouTube Data API v3 — `search.list` endpoint
- Search terms: `audiophile`, `vintage audio`, `hi-fi`, `turntable setup`, `receiver review`
- Filter: published in last 7 days, ordered by view count
- Capture: video title, channel name, view count, published date, URL

---

## AI analysis

### Spike detection
Compare this week's topic frequency against the stored history of prior weeks.

Prompt input: this week's normalized topic list + last 4 weeks of topic history from Postgres
Prompt output: JSON list of spiking topics with explanation of why they're spiking

### Trend detection
Identify topics that have appeared consistently across 3+ weeks.

Prompt input: last 8 weeks of stored topic data from Postgres
Prompt output: JSON list of steady topics with week-over-week presence count

### Script treatment generation
For each strategic topic (top 3-5 from spike + trend combined):

Prompt input: topic summary + source evidence + relevant evergreen video data
Prompt output:
```json
{
  "title": "suggested video title",
  "hook": "opening line or question",
  "angle": "unique perspective or framing",
  "key_points": ["point 1", "point 2", "point 3"],
  "format": "review | comparison | how-to | teardown",
  "evergreen_connection": "reference to owned video if applicable",
  "script_treatment": "150-200 word narrative treatment"
}
```

### Chatter selection
From all discovered topics, select the 3-6 most conversation-worthy for the chatter tab.

Criteria: high comment/engagement volume, active debate, community controversy (not negative — just energetic discussion), something visually interesting or surprising.

Prompt output: selected topics with 2-3 sentence digest and ranked source links.

---

## Evergreen video detection

Runs as part of each weekly research job.

Logic:
```sql
-- For each video, calculate average monthly views over last 6 months
-- using youtube_video_summaries data
-- If avg >= 1000 AND consecutive qualifying months >= 6:
--   upsert into channel_evergreen
```

The channel_evergreen table is used by the script treatment generator to find relevant owned content.

---

## Streamlit UI spec

### Tab: Research — strategy

**Header:** Run date + "Last updated: Tuesday MM/DD/YYYY"
History selector: dropdown of past run dates — lets you browse prior weeks

**Section 1 — Evergreen performers**
Horizontal scrollable tile row. Each tile:
- Video title
- Avg monthly views
- Months qualifying
- Click → opens YouTube video URL

**Section 2 — Spiking topics**
Tile grid. Each tile:
- Topic title (bold)
- One-sentence teaser
- Source tag badges (Reddit / Head-Fi / YouTube / etc.)
- Trend badge: "Spiking" (coral)
- Click → expands full detail panel below grid

**Section 3 — Steady growers**
Same tile layout as spiking. Trend badge: "Steady" (teal)

**Section 4 — Video ideas**
Same tile layout. Each tile also shows format badge (Review / Comparison / How-to / Teardown)

**Expanded detail panel (on tile click):**
- Full summary
- Source links (clickable)
- Script treatment (full text)
- Format suggestion
- Evergreen connection (if applicable) with link to existing video

---

### Tab: Research — chatter

**Header:** Run date + "Ready for filming reference"
History selector: same dropdown as strategy tab

**Tile grid (3-6 tiles):**
Each tile:
- Topic title
- 2-3 sentence community digest
- Source tag badges
- Source links (2-3 clickable links)

Designed to be opened on filming day as quick reference for "what's the community talking about this week" on-camera segment.

---

## Postgres tables used

- `research_runs` — write (one per weekly run)
- `research_topics` — write (multiple per run)
- `research_chatter` — write (3-6 per run)
- `channel_evergreen` — read/write (updated each run)
- `youtube_videos` — read (for cross-reference and evergreen calculation)
- `youtube_video_summaries` — read (for evergreen view count data)

---

## Worker module

`app/worker/jobs/research_job.py`

Key functions:
- `scrape_reddit(subreddits)` — returns normalized topic list
- `scrape_forums(sites)` — returns normalized topic list
- `scrape_publications(feeds)` — returns normalized topic list
- `scrape_youtube_trending(search_terms)` — returns normalized topic list
- `normalize_sources(raw_lists)` — deduplicates and standardizes format
- `detect_spikes(current_week, history)` — returns spiking topics
- `detect_trends(history)` — returns steady topics
- `update_evergreen()` — recalculates and saves evergreen videos
- `cross_reference_topics(topics)` — flags covered/refresh topics
- `generate_treatments(topics)` — calls Claude for script treatments
- `select_chatter(topics)` — calls Claude for chatter selection
- `save_run_results(run_id, topics, chatter)` — writes to Postgres

---

## Build notes for Phase 5

Build in this order:

1. Prove one source at a time — start with RSS feeds (simplest), then Reddit API, then web scraping
2. Build normalize function early — all downstream logic depends on a clean unified format
3. Build Postgres history before spike/trend detection — detection requires stored history
4. Build evergreen detection using existing YouTube data from Phase 3
5. Build AI synthesis last — all data collection must be reliable first
6. Build Streamlit tabs last

Dependencies to install:
```
praw               # Reddit API
feedparser         # RSS feeds
httpx              # HTTP client for scraping
beautifulsoup4     # HTML parsing
anthropic
```

Reddit API setup: register a script-type app at reddit.com/prefs/apps. Free tier supports read-only access which is all that's needed.

Web scraping note: check each forum's robots.txt before scraping. AudioScienceReview and Head-Fi both allow crawling of public content. Use a descriptive User-Agent string identifying the bot as personal/non-commercial.

The weekly run may take 5-10 minutes to complete depending on source response times. The Streamlit UI should show a "Research running..." status during the run rather than appearing stale.
