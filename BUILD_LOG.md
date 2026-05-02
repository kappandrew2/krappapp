# Build log

This file tracks what has been built, tested, and proven. Update it as each component is completed. Claude Code should read this file at the start of each session to understand current project state before taking any action.

---

## How to use this file

- After completing and testing a component, add an entry below
- Mark status clearly: `COMPLETE`, `IN PROGRESS`, or `BLOCKED`
- Note any deviations from the spec docs — if something was built differently than documented, record it here so the docs stay accurate
- Record any discovered constraints or gotchas that future build sessions need to know

---

## Phase 1 — Foundation

### Docker Compose skeleton
**Status:** NOT STARTED

Containers: postgres, streamlit, scheduler, worker
All containers defined, networked, and starting cleanly.
Postgres healthcheck passing.
Streamlit accessible at localhost:8501.

### Database migrations
**Status:** NOT STARTED

Migration 001_init.sql applied.
All tables from DATA_MODEL.md created.
All indexes created.
Schema verified via psql.

### Streamlit shell
**Status:** NOT STARTED

App loads at localhost:8501.
Five tabs visible: Email assistant, YouTube monitor, eBay inventory, Research — strategy, Research — chatter.
Each tab shows placeholder text.
Postgres connection from Streamlit verified.

---

## Phase 2 — eBay inventory

### File watcher
**Status:** NOT STARTED

Worker detects new files in ./data/imports/.
Active vs sold file type detected from filename.
Load history checked before processing.

### CSV/Excel ETL
**Status:** NOT STARTED

Column mapping config created at app/worker/config/ebay_column_map.json.
Actual eBay export column names confirmed.
Validation and normalization working.
Upsert logic tested: insert new, update existing, sold status transition.
Age in days calculated correctly.
Load history recorded.

### Title word extraction
**Status:** NOT STARTED

Stop word list defined.
Word frequency table populated after ETL run.
Correct counts verified.

### Streamlit — eBay tab
**Status:** NOT STARTED

Folder link button opens imports folder in Finder.
Summary bar showing correct counts.
Grid displaying with all columns.
Sort by age in days working.
Filter toggle (All / Active / Sold) working.
Word frequency chart rendering with date range slider.

---

## Phase 3 — YouTube comment monitor

### Scheduler container
**Status:** NOT STARTED

APScheduler running in scheduler container.
Test job fires on schedule and logs output.
Scheduler survives container restart.

### YouTube API connection
**Status:** NOT STARTED

API key configured.
Single video comment fetch working.
Channel video list fetch working.

### Comment processing job
**Status:** NOT STARTED

All channel video IDs fetched.
New comments deduplicated against Postgres.
Sentiment classification working.
Offensive detection working.
Per-video summaries generated.
Comments and summaries saved to Postgres.

### YouTube OAuth (comment deletion)
**Status:** NOT STARTED

OAuth credential file generated.
Comment deletion via API tested.

### Streamlit — YouTube tab
**Status:** NOT STARTED

Video table rendering.
Sort by view count working.
Click-through to flagged comments working.
Remove and Ignore checkboxes functional.
Filter toggle working.

---

## Phase 4 — Email assistant

### Gmail OAuth setup
**Status:** NOT STARTED

Two OAuth credential files generated (eBay account, YouTube account).
Token refresh working.
Read email scopes confirmed.
Send email scopes confirmed.

### Email fetch and deduplication
**Status:** NOT STARTED

Both accounts fetched.
Deduplication against gmail_message_id working.
is_reply detection working.

### AI classification and draft generation
**Status:** NOT STARTED

QA pairs seeded from Excel.
Classification prompt working, returns correct JSON.
High priority detection working.
Draft generation prompt working.

### Twilio SMS
**Status:** NOT STARTED

SMS sends for high priority emails.
Message format confirmed.

### Streamlit — Email tab
**Status:** NOT STARTED

Grid rendering with all columns.
Filter toggle working.
Inline draft editing working.
Approve button triggers send.
Override checkbox working.

---

## Phase 5 — Research agent

### Source scrapers
**Status:** NOT STARTED

RSS feeds (Stereophile, TAS, What Hi-Fi) working.
Reddit API (PRAW) working.
Forum scraping (ASR, Head-Fi, AudiophileStyle) working.
YouTube trending search working.
Normalization producing consistent format.

### Analysis pipeline
**Status:** NOT STARTED

Spike detection working.
Trend detection working.
Evergreen detection working.
Cross-reference with video library working.

### AI synthesis
**Status:** NOT STARTED

Script treatment generation working.
Chatter selection working.
All results saved to Postgres.

### Streamlit — Research tabs
**Status:** NOT STARTED

Strategy tab: all four sections rendering.
Tile click-through working.
History selector working.
Chatter tab rendering with links.

---

## Discovered constraints and gotchas

*Record anything here that future build sessions need to know — API quirks, schema changes, workarounds, etc.*

(none yet)

---

## Schema deviations from DATA_MODEL.md

*If any table or column was built differently than documented, record it here.*

(none yet)
