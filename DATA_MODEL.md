# Data model

All use cases share a single PostgreSQL database (`appdb`). Tables are organized by domain. All tables include `created_at` and `updated_at` timestamps. Foreign keys are enforced.

---

## Naming conventions

- Table names: `snake_case`, plural
- Primary keys: `id` (serial or uuid as noted)
- Foreign keys: `{table_singular}_id`
- Status columns: use short string enums, not integers
- Timestamps: always `TIMESTAMPTZ` (timezone-aware)

---

## Domain: Email assistant

### `email_accounts`
Stores the two Gmail accounts being monitored.

```sql
CREATE TABLE email_accounts (
    id          SERIAL PRIMARY KEY,
    label       TEXT NOT NULL,              -- 'ebay' or 'youtube'
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### `emails`
One row per email received across both accounts.

```sql
CREATE TABLE emails (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER REFERENCES email_accounts(id),
    gmail_message_id TEXT NOT NULL UNIQUE,  -- deduplication key
    thread_id       TEXT,
    from_address    TEXT NOT NULL,
    subject         TEXT,
    body_text       TEXT,
    received_at     TIMESTAMPTZ,
    is_reply        BOOLEAN DEFAULT FALSE,
    classification  TEXT,                   -- 'shipping', 'return', 'offer', etc.
    priority        TEXT DEFAULT 'normal',  -- 'normal' or 'high'
    status          TEXT DEFAULT 'new',     -- 'new', 'approved', 'sent', 'overridden'
    ai_draft        TEXT,
    final_reply     TEXT,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### `qa_pairs`
Knowledge base for AI response generation. Loaded from Excel file.

```sql
CREATE TABLE qa_pairs (
    id          SERIAL PRIMARY KEY,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    tags        TEXT[],                     -- optional topic tags
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Domain: YouTube comment monitor

### `youtube_videos`
One row per video on the channel.

```sql
CREATE TABLE youtube_videos (
    id              SERIAL PRIMARY KEY,
    youtube_video_id TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    published_at    TIMESTAMPTZ,
    view_count      BIGINT DEFAULT 0,
    comment_count   INTEGER DEFAULT 0,
    last_fetched_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### `youtube_comments`
One row per comment fetched from the channel.

```sql
CREATE TABLE youtube_comments (
    id                  SERIAL PRIMARY KEY,
    youtube_comment_id  TEXT NOT NULL UNIQUE,   -- deduplication key
    video_id            INTEGER REFERENCES youtube_videos(id),
    author_name         TEXT,
    body_text           TEXT NOT NULL,
    published_at        TIMESTAMPTZ,
    sentiment           TEXT,               -- 'positive', 'neutral', 'negative'
    is_offensive        BOOLEAN DEFAULT FALSE,
    offensive_reason    TEXT,               -- 'spam', 'attack', 'profanity', etc.
    review_status       TEXT DEFAULT 'pending', -- 'pending', 'removed', 'ignored', 'cleared'
    ignored_at          TIMESTAMPTZ,        -- set when marked ignored (misclassification)
    removed_at          TIMESTAMPTZ,        -- set when deleted via API
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### `youtube_video_summaries`
Per-video sentiment summary, one row per fetch run per video.

```sql
CREATE TABLE youtube_video_summaries (
    id              SERIAL PRIMARY KEY,
    video_id        INTEGER REFERENCES youtube_videos(id),
    run_date        DATE NOT NULL,
    total_comments  INTEGER DEFAULT 0,
    positive_count  INTEGER DEFAULT 0,
    neutral_count   INTEGER DEFAULT 0,
    negative_count  INTEGER DEFAULT 0,
    flagged_count   INTEGER DEFAULT 0,
    ignored_count   INTEGER DEFAULT 0,
    themes          TEXT[],                 -- main discussion themes
    summary_text    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Domain: eBay inventory

### `ebay_items`
Single table for both active and sold items. Status column distinguishes them.

```sql
CREATE TABLE ebay_items (
    id              SERIAL PRIMARY KEY,
    ebay_item_id    TEXT NOT NULL UNIQUE,   -- eBay item number — upsert key
    title           TEXT NOT NULL,
    category        TEXT,
    status          TEXT NOT NULL,          -- 'active' or 'sold'
    listing_date    DATE,                   -- original listing date — never overwritten
    sold_date       DATE,                   -- set when status changes to 'sold'
    age_in_days     INTEGER,                -- calculated on each ETL run
    price           NUMERIC(10,2),
    sold_price      NUMERIC(10,2),
    condition       TEXT,
    raw_data        JSONB,                  -- all other columns from CSV stored here
    last_loaded_at  TIMESTAMPTZ,            -- timestamp of most recent file load
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### `ebay_title_words`
Word frequency table built from listing titles during ETL. Powers date-range word analysis.

```sql
CREATE TABLE ebay_title_words (
    id          SERIAL PRIMARY KEY,
    word        TEXT NOT NULL,
    status      TEXT NOT NULL,              -- 'active' or 'sold'
    item_count  INTEGER DEFAULT 0,          -- number of items with this word
    run_date    DATE NOT NULL,              -- date this word count was calculated
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (word, status, run_date)
);
```

### `ebay_load_history`
Audit log of every file load.

```sql
CREATE TABLE ebay_load_history (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL,          -- 'active' or 'sold'
    rows_inserted   INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    rows_unchanged  INTEGER DEFAULT 0,
    loaded_at       TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Domain: Research agent

### `research_runs`
One row per weekly agent execution.

```sql
CREATE TABLE research_runs (
    id          SERIAL PRIMARY KEY,
    run_date    DATE NOT NULL UNIQUE,
    status      TEXT DEFAULT 'pending',     -- 'pending', 'running', 'complete', 'error'
    started_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_text  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### `research_topics`
Individual topics discovered in a run — one row per topic per run.

```sql
CREATE TABLE research_topics (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER REFERENCES research_runs(id),
    title           TEXT NOT NULL,
    teaser          TEXT,                   -- one-sentence summary for tile display
    trend_type      TEXT NOT NULL,          -- 'spiking' or 'steady'
    source_tags     TEXT[],                 -- ['Reddit', 'Head-Fi', 'YouTube', etc.]
    full_summary    TEXT,
    source_links    JSONB,                  -- [{label, url}, ...]
    script_treatment TEXT,                  -- 150-200 word script outline
    format_suggestion TEXT,                 -- 'review', 'comparison', 'how-to', 'teardown'
    evergreen_connection TEXT,              -- reference to related owned video if applicable
    related_video_id INTEGER REFERENCES youtube_videos(id),
    is_covered      BOOLEAN DEFAULT FALSE,  -- true if channel already has this topic
    is_refresh      BOOLEAN DEFAULT FALSE,  -- true if existing video is a refresh candidate
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### `research_chatter`
Current community buzz topics — 3 to 6 per run.

```sql
CREATE TABLE research_chatter (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER REFERENCES research_runs(id),
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,              -- 2-3 sentence community digest
    source_tags TEXT[],
    source_links JSONB,                     -- [{label, url}, ...]
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### `channel_evergreen`
Cached list of your evergreen videos, refreshed on each research run.

```sql
CREATE TABLE channel_evergreen (
    id                  SERIAL PRIMARY KEY,
    video_id            INTEGER REFERENCES youtube_videos(id),
    avg_monthly_views   INTEGER,
    consecutive_months  INTEGER,            -- how many months above threshold
    first_qualified_at  DATE,
    last_evaluated_at   DATE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Indexes

```sql
-- Email
CREATE INDEX idx_emails_status ON emails(status);
CREATE INDEX idx_emails_received ON emails(received_at DESC);
CREATE INDEX idx_emails_account ON emails(account_id);

-- YouTube comments
CREATE INDEX idx_comments_video ON youtube_comments(video_id);
CREATE INDEX idx_comments_status ON youtube_comments(review_status);
CREATE INDEX idx_comments_offensive ON youtube_comments(is_offensive) WHERE is_offensive = TRUE;

-- eBay items
CREATE INDEX idx_items_status ON ebay_items(status);
CREATE INDEX idx_items_age ON ebay_items(age_in_days DESC);
CREATE INDEX idx_items_category ON ebay_items(category);
CREATE INDEX idx_title_words_date ON ebay_title_words(run_date, status);

-- Research
CREATE INDEX idx_topics_run ON research_topics(run_id);
CREATE INDEX idx_topics_trend ON research_topics(trend_type);
CREATE INDEX idx_chatter_run ON research_chatter(run_id);
```

---

## Migration strategy

- Migrations are plain `.sql` files in `app/db/migrations/`, named `001_init.sql`, `002_add_x.sql`, etc.
- Applied in order on container startup via an init script.
- Never modify a migration that has already been applied — always add a new one.
- The `app/db/migrations/` folder is the single source of truth for schema state.
