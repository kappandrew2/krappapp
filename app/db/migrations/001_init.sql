-- ============================================================
-- 001_init.sql — full schema for all domains
-- ============================================================

-- ============================================================
-- Domain: Email assistant
-- ============================================================

CREATE TABLE email_accounts (
    id          SERIAL PRIMARY KEY,
    label       TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE emails (
    id                  SERIAL PRIMARY KEY,
    account_id          INTEGER REFERENCES email_accounts(id),
    gmail_message_id    TEXT NOT NULL UNIQUE,
    thread_id           TEXT,
    from_address        TEXT NOT NULL,
    subject             TEXT,
    body_text           TEXT,
    received_at         TIMESTAMPTZ,
    is_reply            BOOLEAN DEFAULT FALSE,
    classification      TEXT,
    priority            TEXT DEFAULT 'normal',
    status              TEXT DEFAULT 'new',
    ai_draft            TEXT,
    final_reply         TEXT,
    sent_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE qa_pairs (
    id          SERIAL PRIMARY KEY,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    tags        TEXT[],
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Domain: YouTube comment monitor
-- ============================================================

CREATE TABLE youtube_videos (
    id                  SERIAL PRIMARY KEY,
    youtube_video_id    TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    published_at        TIMESTAMPTZ,
    view_count          BIGINT DEFAULT 0,
    comment_count       INTEGER DEFAULT 0,
    last_fetched_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE youtube_comments (
    id                  SERIAL PRIMARY KEY,
    youtube_comment_id  TEXT NOT NULL UNIQUE,
    video_id            INTEGER REFERENCES youtube_videos(id),
    author_name         TEXT,
    body_text           TEXT NOT NULL,
    published_at        TIMESTAMPTZ,
    sentiment           TEXT,
    is_offensive        BOOLEAN DEFAULT FALSE,
    offensive_reason    TEXT,
    review_status       TEXT DEFAULT 'pending',
    ignored_at          TIMESTAMPTZ,
    removed_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

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
    themes          TEXT[],
    summary_text    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Domain: eBay inventory
-- ============================================================

CREATE TABLE ebay_items (
    id              SERIAL PRIMARY KEY,
    ebay_item_id    TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    category        TEXT,
    status          TEXT NOT NULL,
    listing_date    DATE,
    sold_date       DATE,
    age_in_days     INTEGER,
    price           NUMERIC(10,2),
    sold_price      NUMERIC(10,2),
    condition       TEXT,
    raw_data        JSONB,
    last_loaded_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ebay_title_words (
    id          SERIAL PRIMARY KEY,
    word        TEXT NOT NULL,
    status      TEXT NOT NULL,
    item_count  INTEGER DEFAULT 0,
    run_date    DATE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (word, status, run_date)
);

CREATE TABLE ebay_load_history (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    rows_inserted   INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    rows_unchanged  INTEGER DEFAULT 0,
    loaded_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Domain: Research agent
-- ============================================================

CREATE TABLE research_runs (
    id              SERIAL PRIMARY KEY,
    run_date        DATE NOT NULL UNIQUE,
    status          TEXT DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_text      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE research_topics (
    id                      SERIAL PRIMARY KEY,
    run_id                  INTEGER REFERENCES research_runs(id),
    title                   TEXT NOT NULL,
    teaser                  TEXT,
    trend_type              TEXT NOT NULL,
    source_tags             TEXT[],
    full_summary            TEXT,
    source_links            JSONB,
    script_treatment        TEXT,
    format_suggestion       TEXT,
    evergreen_connection    TEXT,
    related_video_id        INTEGER REFERENCES youtube_videos(id),
    is_covered              BOOLEAN DEFAULT FALSE,
    is_refresh              BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE research_chatter (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER REFERENCES research_runs(id),
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    source_tags TEXT[],
    source_links JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE channel_evergreen (
    id                  SERIAL PRIMARY KEY,
    video_id            INTEGER REFERENCES youtube_videos(id),
    avg_monthly_views   INTEGER,
    consecutive_months  INTEGER,
    first_qualified_at  DATE,
    last_evaluated_at   DATE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Indexes
-- ============================================================

-- Email
CREATE INDEX idx_emails_status   ON emails(status);
CREATE INDEX idx_emails_received ON emails(received_at DESC);
CREATE INDEX idx_emails_account  ON emails(account_id);

-- YouTube comments
CREATE INDEX idx_comments_video     ON youtube_comments(video_id);
CREATE INDEX idx_comments_status    ON youtube_comments(review_status);
CREATE INDEX idx_comments_offensive ON youtube_comments(is_offensive) WHERE is_offensive = TRUE;

-- eBay items
CREATE INDEX idx_items_status      ON ebay_items(status);
CREATE INDEX idx_items_age         ON ebay_items(age_in_days DESC);
CREATE INDEX idx_items_category    ON ebay_items(category);
CREATE INDEX idx_title_words_date  ON ebay_title_words(run_date, status);

-- Research
CREATE INDEX idx_topics_run    ON research_topics(run_id);
CREATE INDEX idx_topics_trend  ON research_topics(trend_type);
CREATE INDEX idx_chatter_run   ON research_chatter(run_id);
