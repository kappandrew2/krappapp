# Build log

This file tracks what has been built, tested, and proven. Update it as each component is completed. Claude Code should read this file at the start of each session to understand current project state before taking any action.

---

## How to use this file

- After completing and testing a component, add an entry below
- Mark status clearly: `COMPLETE`, `IN PROGRESS`, or `BLOCKED`
- Note any deviations from the spec docs — if something was built differently than documented, record it here so the docs stay accurate
- Record any discovered constraints or gotchas that future build sessions need to know

---

## Phase 1 — Foundation (completed - built and tested 05/02/2026 07:20)

### Docker Compose skeleton
**Status:** COMPLETE

Containers: postgres, streamlit, scheduler, worker — all four defined in `docker-compose.yml`.
Named volume `postgres_data` used for Postgres persistence (bind mount in `PROJECT_OVERVIEW.md` was an oversight — named volume is canonical).
`app_network` bridge network connects all containers.
Postgres healthcheck configured; all three application containers `depends_on: postgres: condition: service_healthy`.

### Database migrations
**Status:** COMPLETE

`app/db/migrations/001_init.sql` applied via `docker-entrypoint-initdb.d` on first Postgres start.
All 14 tables created across four domains: email (3), YouTube (3), eBay (3), research (5).
All indexes from `DATA_MODEL.md` included. Schema matches spec exactly — no deviations.

### Streamlit shell
**Status:** COMPLETE

`app/streamlit/main.py` loads at localhost:8501.
Five tabs: Email assistant, YouTube monitor, eBay inventory, Research — strategy, Research — chatter.
Each tab shows placeholder text indicating which phase delivers its functionality.
Postgres connection tested on startup; result shown as `st.success` / `st.error` in the sidebar.

### Scheduler stub
**Status:** COMPLETE

`app/scheduler/scheduler.py` logs "container started" and sleeps. Container starts cleanly; no real jobs until Phase 3.

### Worker stub
**Status:** COMPLETE

`app/worker/worker.py` logs "container started" and sleeps. Container starts cleanly; real job logic begins in Phase 2.

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

- **Postgres volume:** `PROJECT_OVERVIEW.md` specified a bind mount (`./data/postgres`); `DOCKER_SETUP.md` specified a named volume (`postgres_data`). Named volume is canonical — Docker-managed, safer from accidental deletion. `data/postgres/` is gitignored as belt-and-suspenders but is not the active storage location.
- **Gmail env var names:** `GMAIL_EBAY_TOKEN_PATH` and `GMAIL_YOUTUBE_TOKEN_PATH` are canonical (from `DOCKER_SETUP.md`), superseding the less-descriptive names in `PROJECT_OVERVIEW.md`.
- **Doc file locations:** Docs were in the repo root on initial commit; moved to `docs/` in Phase 1 commit to match the repository structure defined in `PROJECT_OVERVIEW.md`.

---

## Schema deviations from DATA_MODEL.md

(none — schema matches spec exactly)
