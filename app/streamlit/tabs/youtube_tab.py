import os

import pandas as pd
import psycopg2
import streamlit as st


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def _query(sql: str, params=None) -> pd.DataFrame:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        conn.close()


def _scalar(sql: str, params=None):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _execute(sql: str, params=None) -> None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cached data fetchers (TTL 60 s)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def _fetch_videos() -> pd.DataFrame:
    return _query(
        """
        WITH latest_summaries AS (
            SELECT DISTINCT ON (video_id)
                video_id, total_comments, positive_count, run_date
            FROM youtube_video_summaries
            ORDER BY video_id, run_date DESC
        ),
        flagged_counts AS (
            SELECT video_id, COUNT(*) AS pending_flagged
            FROM youtube_comments
            WHERE is_offensive = TRUE AND review_status = 'pending'
            GROUP BY video_id
        )
        SELECT
            v.id,
            v.youtube_video_id,
            v.title,
            v.published_at,
            v.view_count,
            v.comment_count,
            v.last_fetched_at,
            ROUND(
                COALESCE(
                    ls.positive_count::numeric / NULLIF(ls.total_comments, 0) * 100,
                    0
                ), 1
            ) AS sentiment_pct,
            COALESCE(fc.pending_flagged, 0) AS pending_flagged
        FROM youtube_videos v
        LEFT JOIN latest_summaries ls ON ls.video_id = v.id
        LEFT JOIN flagged_counts fc ON fc.video_id = v.id
        ORDER BY v.view_count DESC
        """
    )


@st.cache_data(ttl=60)
def _fetch_summary() -> dict:
    return {
        "video_count": _scalar("SELECT COUNT(*) FROM youtube_videos"),
        "pending_flagged": _scalar(
            "SELECT COUNT(*) FROM youtube_comments "
            "WHERE is_offensive = TRUE AND review_status = 'pending'"
        ),
        "last_run": _scalar("SELECT MAX(last_fetched_at) FROM youtube_videos"),
    }


@st.cache_data(ttl=60)
def _fetch_latest_summary(db_video_id: int) -> dict | None:
    df = _query(
        """
        SELECT total_comments, positive_count, neutral_count, negative_count,
               flagged_count, themes, summary_text, run_date
        FROM youtube_video_summaries
        WHERE video_id = %s
        ORDER BY run_date DESC
        LIMIT 1
        """,
        (db_video_id,),
    )
    return df.iloc[0].to_dict() if not df.empty else None


@st.cache_data(ttl=60)
def _fetch_flagged_comments(db_video_id: int) -> pd.DataFrame:
    return _query(
        """
        SELECT id, youtube_comment_id, author_name, body_text,
               offensive_reason, published_at
        FROM youtube_comments
        WHERE video_id = %s AND is_offensive = TRUE AND review_status = 'pending'
        ORDER BY published_at DESC
        """,
        (db_video_id,),
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _mark_ignored(youtube_comment_id: str) -> None:
    _execute(
        """
        UPDATE youtube_comments
        SET review_status = 'ignored', ignored_at = NOW(), updated_at = NOW()
        WHERE youtube_comment_id = %s
        """,
        (youtube_comment_id,),
    )


# ---------------------------------------------------------------------------
# Sub-renderers
# ---------------------------------------------------------------------------

def _render_video_detail(video_row) -> None:
    db_video_id = int(video_row["id"])

    # Sentiment summary card
    summary = _fetch_latest_summary(db_video_id)
    if summary:
        with st.expander("Sentiment summary", expanded=True):
            total = max(int(summary["total_comments"] or 0), 1)
            c1, c2, c3, c4 = st.columns(4)
            pos = int(summary["positive_count"] or 0)
            neu = int(summary["neutral_count"] or 0)
            neg = int(summary["negative_count"] or 0)
            flg = int(summary["flagged_count"] or 0)
            c1.metric("Positive", f"{pos} ({pos / total * 100:.0f}%)")
            c2.metric("Neutral", str(neu))
            c3.metric("Negative", str(neg))
            c4.metric("Flagged", str(flg))
            if summary.get("summary_text"):
                st.write(summary["summary_text"])
            themes = summary.get("themes")
            if themes:
                st.write("**Topics:** " + " · ".join(themes))
    else:
        st.info("No summary yet — will be generated on the next job run.")

    # Flagged comments
    flagged_df = _fetch_flagged_comments(db_video_id)
    if flagged_df.empty:
        st.success("No pending flagged comments for this video.")
        return

    st.subheader(f"Flagged comments — {len(flagged_df)} pending review")

    for _, comment in flagged_df.iterrows():
        with st.container(border=True):
            col_author, col_text, col_reason, col_date, col_remove, col_ignore = (
                st.columns([2, 5, 2, 2, 1, 1])
            )
            col_author.write(f"**{comment['author_name'] or 'Unknown'}**")
            col_text.write(str(comment["body_text"] or ""))
            col_reason.write(f"`{comment['offensive_reason'] or ''}`")
            pub = comment["published_at"]
            col_date.write(str(pub)[:10] if pub else "")

            with col_remove:
                st.checkbox(
                    "Remove",
                    disabled=True,
                    key=f"remove_{comment['id']}",
                    help="Comment deletion coming in Phase 3 Pass 2",
                )
            with col_ignore:
                if st.checkbox("Ignore", key=f"ignore_{comment['id']}"):
                    _mark_ignored(str(comment["youtube_comment_id"]))
                    st.cache_data.clear()
                    st.rerun()


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render() -> None:
    st.header("YouTube monitor")

    # Summary bar
    s = _fetch_summary()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total videos", s["video_count"] or 0)
    c2.metric("Pending flagged comments", s["pending_flagged"] or 0)
    last_run = s["last_run"]
    c3.metric(
        "Last job run",
        last_run.strftime("%Y-%m-%d %H:%M") if last_run else "Never",
    )

    st.divider()

    df = _fetch_videos()

    if df.empty:
        st.info(
            "No videos found yet. The YouTube job runs every 6 hours — "
            "it will also fire automatically when the scheduler container starts."
        )
        return

    # Filter bar
    filter_choice = st.radio(
        "Show", ["Pending review", "Cleared", "All"], horizontal=True
    )

    if filter_choice == "Pending review":
        filtered = df[df["pending_flagged"] > 0]
    elif filter_choice == "Cleared":
        filtered = df[df["pending_flagged"] == 0]
    else:
        filtered = df

    if filtered.empty:
        st.info("No videos match the selected filter.")
        return

    # Video table
    display_cols = [
        c for c in
        ["title", "published_at", "view_count", "comment_count",
         "sentiment_pct", "pending_flagged", "last_fetched_at"]
        if c in filtered.columns
    ]
    st.dataframe(
        filtered[display_cols],
        use_container_width=True,
        column_config={
            "title":          st.column_config.TextColumn("Title"),
            "published_at":   st.column_config.DatetimeColumn("Published"),
            "view_count":     st.column_config.NumberColumn("Views"),
            "comment_count":  st.column_config.NumberColumn("Comments"),
            "sentiment_pct":  st.column_config.NumberColumn("Positive %", format="%.1f%%"),
            "pending_flagged": st.column_config.NumberColumn("Flagged (pending)"),
            "last_fetched_at": st.column_config.DatetimeColumn("Last updated"),
        },
        hide_index=True,
    )

    st.divider()

    # Video selector + detail panel
    titles = filtered["title"].tolist()
    selected_title = st.selectbox("Select a video to review", options=titles)

    if selected_title:
        row = filtered[filtered["title"] == selected_title].iloc[0]
        _render_video_detail(row)
