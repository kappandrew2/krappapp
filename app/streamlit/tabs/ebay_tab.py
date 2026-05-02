import os
import subprocess

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st

IMPORTS_FOLDER = os.environ.get("EBAY_IMPORT_FOLDER", "/app/imports")


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


@st.cache_data(ttl=60)
def _fetch_items(status_filter: str) -> pd.DataFrame:
    if status_filter == "All":
        return _query(
            "SELECT * FROM ebay_items ORDER BY age_in_days DESC NULLS LAST"
        )
    return _query(
        "SELECT * FROM ebay_items WHERE status = %s ORDER BY age_in_days DESC NULLS LAST",
        (status_filter.lower(),),
    )


@st.cache_data(ttl=60)
def _fetch_summary() -> dict:
    return {
        "active": _scalar("SELECT COUNT(*) FROM ebay_items WHERE status = 'active'"),
        "sold": _scalar(
            "SELECT COUNT(*) FROM ebay_items "
            "WHERE status = 'sold' AND sold_date >= CURRENT_DATE - INTERVAL '1 year'"
        ),
        "long_listed": _scalar(
            "SELECT COUNT(*) FROM ebay_items WHERE status = 'active' AND age_in_days >= 365"
        ),
        "last_loaded": _scalar("SELECT MAX(loaded_at) FROM ebay_load_history"),
    }


@st.cache_data(ttl=60)
def _fetch_word_data() -> pd.DataFrame:
    return _query(
        "SELECT word, status, item_count, run_date FROM ebay_title_words ORDER BY run_date, status, item_count DESC"
    )


def render():
    st.header("eBay inventory")

    # Folder link
    if st.button("Open imports folder"):
        subprocess.run(["open", IMPORTS_FOLDER])

    # Summary bar
    s = _fetch_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active listings", s["active"] or 0)
    c2.metric("Sold (last 12 months)", s["sold"] or 0)
    c3.metric("Long-listed (365+ days)", s["long_listed"] or 0)
    c4.metric(
        "Last loaded",
        s["last_loaded"].strftime("%Y-%m-%d %H:%M") if s["last_loaded"] else "Never",
    )

    st.divider()

    # Filter + search
    status_filter = st.radio("Show", ["Active", "All", "Sold"], horizontal=True)
    search = st.text_input("Search title", placeholder="keyword…")

    df = _fetch_items(status_filter)

    if search:
        df = df[df["title"].str.contains(search, case=False, na=False)]

    display_cols = [
        c for c in
        ["ebay_item_id", "title", "category", "status",
         "listing_date", "sold_date", "age_in_days", "price", "sold_price"]
        if c in df.columns
    ]

    st.dataframe(
        df[display_cols],
        use_container_width=True,
        column_config={
            "ebay_item_id":  st.column_config.TextColumn("Item ID"),
            "title":         st.column_config.TextColumn("Title"),
            "category":      st.column_config.TextColumn("Category"),
            "status":        st.column_config.TextColumn("Status"),
            "listing_date":  st.column_config.DateColumn("Listed"),
            "sold_date":     st.column_config.DateColumn("Sold date"),
            "age_in_days":   st.column_config.NumberColumn("Age (days)"),
            "price":         st.column_config.NumberColumn("Price", format="$%.2f"),
            "sold_price":    st.column_config.NumberColumn("Sold price", format="$%.2f"),
        },
        hide_index=True,
    )

    st.divider()

    # Word frequency section
    st.subheader("Title word frequency")

    word_df = _fetch_word_data()

    if word_df.empty:
        st.info("No word data yet. Drop an eBay export into the imports folder to generate it.")
        return

    word_df["run_date"] = pd.to_datetime(word_df["run_date"]).dt.date
    distinct_dates = sorted(word_df["run_date"].unique())

    word_status = st.radio("Items", ["Active", "Sold", "Both"], horizontal=True, key="word_status")

    if len(distinct_dates) < 2:
        st.info(f"Word data available for {distinct_dates[0]}. More dates appear after future loads.")
        filtered = word_df
    else:
        start_d, end_d = st.slider(
            "Date range",
            min_value=distinct_dates[0],
            max_value=distinct_dates[-1],
            value=(distinct_dates[0], distinct_dates[-1]),
        )
        filtered = word_df[
            (word_df["run_date"] >= start_d) & (word_df["run_date"] <= end_d)
        ]

    if word_status != "Both":
        filtered = filtered[filtered["status"] == word_status.lower()]

    if filtered.empty:
        st.info("No word data for the selected filters.")
        return

    agg = (
        filtered.groupby("word")["item_count"]
        .sum()
        .reset_index()
        .sort_values("item_count", ascending=False)
        .head(20)
    )

    fig = px.bar(
        agg,
        x="item_count",
        y="word",
        orientation="h",
        labels={"item_count": "Count", "word": "Word"},
        title="Top 20 words in listing titles",
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)
