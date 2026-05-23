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

### Schema migration
**Status:** COMPLETE

`app/db/migrations/002_add_ebay_fields.sql` adds two columns to `ebay_items`:
- `sold_quantity INTEGER` — units per sold transaction (from `Quantity` column in sold file)
- `end_date DATE` — listing expiry date (useful for per-attempt age analysis)
Apply manually after Phase 1 DB is running: `docker exec -it app_postgres psql -U appuser -d appdb -f /docker-entrypoint-initdb.d/002_add_ebay_fields.sql`

### File watcher
**Status:** COMPLETE

`app/worker/jobs/ebay_etl_job.py` — `watch_imports_folder()` uses `PollingObserver` (60s poll) to detect new files in `/app/imports`.
File type detected from filename: must contain `active` or `sold`.
`scan_existing_files()` runs on worker startup to catch any files dropped while the container was down.
`_already_loaded()` checks `ebay_load_history` before processing — prevents double-loads.
2-second sleep after file creation event to allow OS write completion.

### CSV/Excel ETL
**Status:** COMPLETE

Column mapping config: `app/worker/config/ebay_column_map.json` — editable, keyed on normalized column names (lowercase+underscores), separate sections for `active` and `sold` file types.
Confirmed column names from real eBay exports:
- Active: `Item number`, `Title`, `Current price`, `Start date`, `End date`, `eBay category 1 name`, `Condition`
- Sold: `Item Number`, `Item Title`, `Sold For`, `Sale Date`, `Quantity`
Quirks handled: `skiprows=1` for sold file; `%b-%d-%y` date format for sold dates; `$` stripping for sold prices; all column names normalized before mapping.
Custom descriptor columns (`CD:*`, `P:*`) and all other unmapped columns stored in `raw_data` JSONB.
ETL fails with a clear diff message (expected vs. actual columns) if required columns are missing — logs actual columns found on every run.
Upsert keyed on `ebay_item_id`: `listing_date` and `status` are never overwritten by active-file load; sold-file load sets `status = 'sold'` unconditionally on conflict.
`xmax = 0` trick used to count inserts vs updates in a single pass.

### Age calculation
**Status:** COMPLETE

`calculate_ages()` runs after every upsert: `UPDATE ebay_items SET age_in_days = CURRENT_DATE - listing_date WHERE listing_date IS NOT NULL`.

### Title word extraction
**Status:** COMPLETE

Stop word list: `app/worker/config/stop_words.json` — editable JSON array, seeded with standard English stop words plus audio/eBay noise words.
`extract_title_words()` tokenizes all titles (active and sold separately), drops words < 3 chars and stop words, upserts counts into `ebay_title_words` for `run_date = today`.

### Streamlit — eBay tab
**Status:** COMPLETE

`app/streamlit/tabs/ebay_tab.py` wired into `main.py`.
Summary bar: 4 metrics (active count, sold last 12 months, long-listed ≥365 days, last loaded timestamp).
Filter bar: Active / All / Sold radio; title keyword search.
Main grid: 9 columns, sorted by `age_in_days DESC`, `st.dataframe` with typed column config.
Word frequency chart: Plotly horizontal bar, top 20 words, Active/Sold/Both toggle, date range slider.
Single-date guard: when `ebay_title_words` has only one distinct `run_date`, shows an info message instead of a single-point slider.
All DB reads use `@st.cache_data(ttl=60)` — no in-memory module-level state.
"Open imports folder" button calls `subprocess.run(["open", folder_path])`.

### Streamlit — eBay tab
**Status:** COMPLETE — see details above under "Streamlit — eBay tab"

### Known issues and carry-forward items

**Migration 002 manual apply required** — `app/db/migrations/002_add_ebay_fields.sql` adds `sold_quantity` and `end_date` columns to `ebay_items`. The `docker-entrypoint-initdb.d` mechanism only runs on a fresh empty database. If the database already exists (e.g. after a `docker compose down` without `-v`), this migration must be applied manually:
```
docker exec -it app_postgres psql -U appuser -d appdb
ALTER TABLE ebay_items ADD COLUMN IF NOT EXISTS sold_quantity INTEGER, ADD COLUMN IF NOT EXISTS end_date DATE;
```

**Date range slider not implemented** — the word frequency chart in the eBay inventory tab renders correctly but the date range slider specified in `UC3_EBAY.md` was not built. Low priority — carry forward to a cleanup pass after all phases are complete.

**Sold items missing listing dates on first load** — sold items that were no longer active at the time of the first export have null `listing_date` and `age_in_days`. This is a timing artifact of the initial load and will self-correct as weekly loads are added over time. No code change required.

---

## Phase 3 — YouTube comment monitor (Pass 1)

### Scheduler container
**Status:** COMPLETE

`app/scheduler/scheduler.py` replaced with real APScheduler (`BlockingScheduler`, UTC timezone).
YouTube monitor job registered with `IntervalTrigger(hours=6)` and `next_run_time=datetime.utcnow()` — fires immediately on container start, then every 6 hours.
`app/scheduler/requirements.txt` updated: added `google-api-python-client==2.131.0`, `google-auth==2.29.0`, `anthropic==0.28.0`.
`docker-compose.yml` updated: scheduler service now receives `ANTHROPIC_API_KEY`, `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_ID` env vars.
`.env.example` updated: added `YOUTUBE_CHANNEL_ID` with instructions.

### YouTube API connection
**Status:** COMPLETE

`app/scheduler/jobs/youtube_job.py` — `get_uploads_playlist_id()` uses `channels.list?part=contentDetails&id=CHANNEL_ID` (API key only, no OAuth required).
Video IDs fetched via `playlistItems.list` on the uploads playlist (50 per page, 1 quota unit/page) — far cheaper than `search.list` (100 units/call).
Video metadata (title, published_at, view_count, comment_count) fetched via `videos.list` in batches of 50.
Comments fetched via `commentThreads.list` (100 per page, 1 unit/page).
1-second delay between all API calls.
Comments-disabled videos: log and skip — no crash.
Quota exceeded: raises `QuotaExceededError`, caught in orchestrator — stops fetch loop cleanly.

### Comment processing job
**Status:** COMPLETE

`run_youtube_job()` orchestrates the full pipeline in `app/scheduler/jobs/youtube_job.py`:
1. Fetch all video IDs via uploads playlist
2. Upsert video metadata (ON CONFLICT UPDATE view/comment counts)
3. Load known comment IDs from DB for deduplication
4. Fetch new comments per video; skip known IDs
5. AI classify in batches of 20 — single Claude call per batch returning `[{comment_id, sentiment, is_offensive, offensive_reason}]`; fallback to `sentiment='unknown'` / `is_offensive=false` on error
6. Save new comments with `ON CONFLICT DO NOTHING`
7. Generate per-video Claude summary only for videos with new comments; save to `youtube_video_summaries`
`app/scheduler/db.py` — DB connection helper for scheduler container.

### YouTube OAuth (comment deletion)
**Status:** COMPLETE

`credentials/youtube_oauth_token.json` loaded by `app/streamlit/utils/youtube_delete.py` via `google.oauth2.credentials.Credentials`.
Token auto-refreshes on expiry and is written back to disk — no manual renewal needed.
`delete_youtube_comment(youtube_comment_id)` calls `youtube.comments().delete(id=...)` via the YouTube Data API v3.
Missing token file, expired credentials, and API errors are all caught and logged; none propagate to the UI as exceptions.

### Streamlit — YouTube tab
**Status:** COMPLETE

`app/streamlit/tabs/youtube_tab.py` wired into `main.py`.
Summary bar: 3 metrics (total videos, pending flagged comments, last job run from MAX(last_fetched_at)).
Filter bar: Pending review / Cleared / All — "Pending review" = videos with ≥1 offensive pending comment; "Cleared" = no pending offensive comments; derived UI state, not a DB value.
Video table: 7 columns sorted by view_count DESC; `st.dataframe` with typed column config.
Video selectbox below table — populated with titles from filtered view.
Detail panel: sentiment summary card from latest `youtube_video_summaries` row + flagged comment list.
Remove checkbox: visible, `disabled=True`, tooltip "Comment deletion coming in Phase 3 Pass 2".
Ignore checkbox: functional — sets `review_status='ignored'`, `ignored_at=NOW()`; clears cache and reruns.
All DB reads use `@st.cache_data(ttl=60)`.

### Phase 3 Pass 2 — YouTube comment deletion
**Status:** COMPLETE

`app/streamlit/utils/youtube_delete.py` *(new)* — OAuth moderation helper; loads token, refreshes if expired, calls `comments().setModerationStatus(moderationStatus='rejected')` to hide the comment from public view.
`app/streamlit/utils/__init__.py` *(new)* — package marker.
`app/streamlit/requirements.txt` updated: added `google-api-python-client==2.131.0`, `google-auth==2.29.0`.
`app/streamlit/tabs/youtube_tab.py` updated:
- Reject checkbox (formerly Remove) enabled — calls `youtube_delete.delete_youtube_comment()`, on success sets `review_status='removed'` / `removed_at=NOW()`; on failure shows `st.error` and resets checkbox.
- `_mark_removed()` DB helper added alongside `_mark_ignored()`.
- `_fetch_videos()` query extended with `removed_count` and `ignored_count` CTEs.
- Filter bar updated to full UC2 spec: `Pending review | Removed | Ignored | All` (replaces `Pending review | Cleared | All`).
`removed_at` column confirmed present in `001_init.sql` — no migration required.
**Rebuild required:** `docker compose build streamlit && docker compose up -d streamlit` after deploying this commit.
**API note:** `comments().delete()` returns `processingFailure 400` for publicly visible comments — a known YouTube Data API v3 limitation. `comments().setModerationStatus('rejected')` is used instead; it hides the comment from public view, which achieves the same result. Returns HTTP 204 No Content on success (execute() returns None — treated as success).

### Known issues and carry-forward items (Phase 3)

**Comment deletion not implemented** — Remove checkbox is visible but disabled. Requires OAuth 2.0 credentials tied to the channel owner account. Scheduled for Phase 3 Pass 2.

**Summary zero-count bug fixed** — Summaries were initially generated when all comments had `sentiment = 'unknown'`. Fixed by making summary generation idempotent (delete-then-insert) and adding Phase 2 backfill to correct zero-count rows.

**Anthropic API credits required** — The scheduler container requires a funded Anthropic API account separate from the Claude.ai subscription. Credits are loaded at console.anthropic.com.

**`datetime.utcnow()` deprecation warning** — Harmless warning in scheduler logs. Carry forward to a cleanup pass after all phases are complete.

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
- **PollingObserver required for watchdog:** inotify-style file events are unreliable across Docker/Mac bind mount boundary. Always use `watchdog.observers.polling.PollingObserver`.
- **Sold file has blank header row:** `skiprows=1` required when reading `sold_listings.csv` with pandas.
- **Sold file date format:** `May-01-26` — parse with `strptime` format `%b-%d-%y`. Active file dates are standard and inferred automatically by pandas.
- **eBay column casing is inconsistent:** `Item number` (active, lowercase n) vs `Item Number` (sold, uppercase N). Normalize ALL column names immediately after read via `re.sub(r"[^a-z0-9]+", "_", col.strip().lower()).strip("_")`.
- **`002_add_ebay_fields.sql` must be applied manually** to an already-running database: `docker exec -it app_postgres psql -U appuser -d appdb -f /docker-entrypoint-initdb.d/002_add_ebay_fields.sql`. The `docker-entrypoint-initdb.d` hook only runs on first container initialization.

---

## Schema deviations from DATA_MODEL.md

- **`ebay_items` gained two columns not in the original spec:** `sold_quantity INTEGER` (units per sold transaction) and `end_date DATE` (listing expiry). Added in `002_add_ebay_fields.sql`.
- **Stop word list is a config file** (`app/worker/config/stop_words.json`), not a hardcoded constant — keeps it tunable without code changes.
