import datetime
import os
import re

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st

IMPORTS_FOLDER = os.environ.get("EBAY_IMPORT_FOLDER", "/app/imports")

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "nor", "so", "yet",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "as", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall", "can",
    "not", "no", "its", "it", "this", "that", "these", "those",
    "they", "them", "their", "we", "our", "you", "your",
    "he", "she", "him", "her", "his", "hers",
    "who", "which", "what", "when", "where", "why", "how",
    "all", "any", "both", "each", "if", "up", "out", "about",
    "into", "through", "during", "before", "after",
    "above", "below", "between", "over", "under", "again",
    "too", "very", "just", "than", "then", "also",
    "new", "old", "used", "good", "great", "nice", "clean",
    "lot", "set", "kit", "item", "items", "unit", "units",
    "read", "see", "please", "description", "photos",
    "shipping", "free", "sale", "ebay", "buy", "sell", "sold",
    "listing", "listed", "price", "offer", "obo",
    "vintage", "original", "tested", "works", "working",
    "parts", "repair", "only", "one", "two", "rare",
}


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


# ---------------------------------------------------------------------------
# Cached data fetchers
# ---------------------------------------------------------------------------

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
def _fetch_sold_date_range() -> tuple:
    df = _query(
        "SELECT MIN(sold_date)::text AS min_date, MAX(sold_date)::text AS max_date "
        "FROM ebay_items WHERE status = 'sold' AND sold_date IS NOT NULL"
    )
    if df.empty or df.iloc[0]["min_date"] is None:
        return None, None
    return df.iloc[0]["min_date"], df.iloc[0]["max_date"]


@st.cache_data(ttl=60)
def _fetch_sold_with_price(date_from, date_to) -> pd.DataFrame:
    if date_from and date_to:
        return _query(
            "SELECT title, sold_price FROM ebay_items "
            "WHERE status = 'sold' AND sold_date BETWEEN %s AND %s AND sold_price IS NOT NULL",
            (date_from, date_to),
        )
    return _query(
        "SELECT title, sold_price FROM ebay_items WHERE status = 'sold' AND sold_price IS NOT NULL"
    )


@st.cache_data(ttl=60)
def _fetch_all_items_for_sellthrough() -> pd.DataFrame:
    return _query(
        "SELECT title, status FROM ebay_items WHERE status IN ('active', 'sold')"
    )


# ---------------------------------------------------------------------------
# In-memory computation helpers (not cached — operate on DataFrames)
# ---------------------------------------------------------------------------

def _keywords(title: str):
    words = set(re.findall(r"[a-z]+", str(title).lower()))
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}


def _revenue_by_keyword(df: pd.DataFrame) -> pd.DataFrame:
    revenue: dict = {}
    for _, row in df.iterrows():
        price = float(row["sold_price"]) if pd.notna(row["sold_price"]) else 0.0
        for w in _keywords(row["title"]):
            revenue[w] = revenue.get(w, 0.0) + price
    return pd.DataFrame(
        sorted(revenue.items(), key=lambda x: -x[1]),
        columns=["keyword", "revenue"],
    )


def _sellthrough_by_keyword(df: pd.DataFrame) -> pd.DataFrame:
    active: dict = {}
    sold: dict = {}
    for _, row in df.iterrows():
        target = active if row["status"] == "active" else sold
        for w in _keywords(row["title"]):
            target[w] = target.get(w, 0) + 1
    all_words = set(active) | set(sold)
    rows = []
    for w in all_words:
        a = active.get(w, 0)
        s = sold.get(w, 0)
        total = a + s
        rows.append({
            "keyword": w,
            "active_count": a,
            "sold_count": s,
            "total_count": total,
            "sell_through_pct": s / total * 100 if total > 0 else 0.0,
        })
    return (
        pd.DataFrame(rows)
        .sort_values("total_count", ascending=False)
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render():
    st.header("eBay inventory")

    # Folder link
    st.info(
        "📁 Drop eBay export files into: ~/krappapp/data/imports/\n\n"
        "Rename files to include \"active\" or \"sold\" in the filename.\n\n"
        "File watcher checks every 60 seconds."
    )

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

    # -----------------------------------------------------------------------
    # Section 1 — Revenue by keyword
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("Revenue by keyword")

    min_date_str, max_date_str = _fetch_sold_date_range()
    date_from_str = min_date_str
    date_to_str = max_date_str

    if min_date_str is None:
        st.info("No sold items with sold_date available yet.")
    else:
        if min_date_str == max_date_str:
            st.caption(f"Sold date: {min_date_str}")
        else:
            min_d = datetime.date.fromisoformat(min_date_str)
            max_d = datetime.date.fromisoformat(max_date_str)
            sel_from, sel_to = st.slider(
                "Sold date range",
                min_value=min_d,
                max_value=max_d,
                value=(min_d, max_d),
                key="revenue_date_slider",
            )
            date_from_str = sel_from.isoformat()
            date_to_str = sel_to.isoformat()

        rev_limit = st.radio(
            "Show", ["Top 20", "All keywords"], horizontal=True, key="rev_limit"
        )

        sold_df = _fetch_sold_with_price(date_from_str, date_to_str)
        if sold_df.empty:
            st.info("No sold items with prices in the selected date range.")
        else:
            rev_df = _revenue_by_keyword(sold_df)
            if rev_limit == "Top 20":
                rev_df = rev_df.head(20)

            if rev_df.empty:
                st.info("No keywords found after filtering stop words.")
            else:
                fig = px.bar(
                    rev_df,
                    x="revenue",
                    y="keyword",
                    orientation="h",
                    labels={"revenue": "Total Revenue ($)", "keyword": "Keyword"},
                    title=f"Revenue by keyword — {rev_limit.lower()}",
                )
                fig.update_layout(
                    yaxis={"categoryorder": "total ascending"},
                    xaxis_tickprefix="$",
                    xaxis_tickformat=",.0f",
                )
                st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------------------------
    # Section 2 — Sell-through by keyword
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("Sell-through by keyword")

    st_limit = st.radio(
        "Show", ["Top 20", "All keywords"], horizontal=True, key="st_limit"
    )

    all_items_df = _fetch_all_items_for_sellthrough()

    if all_items_df.empty:
        st.info("No items found.")
    else:
        st_df = _sellthrough_by_keyword(all_items_df)
        plot_df = st_df if st_limit == "All keywords" else st_df.head(20)

        if plot_df.empty:
            st.info("No keywords found after filtering stop words.")
        else:
            # Table with colored sell-through %
            table_df = plot_df[
                ["keyword", "active_count", "sold_count", "total_count", "sell_through_pct"]
            ].copy()
            table_df.columns = ["Keyword", "Listed", "Sold", "Total", "Sell-through %"]

            def _color_st_row(col):
                styles = []
                for val in col:
                    if val >= 60:
                        styles.append("background-color: #c6efce; color: #276221")
                    elif val >= 30:
                        styles.append("background-color: #ffeb9c; color: #9c6500")
                    else:
                        styles.append("background-color: #ffc7ce; color: #9c0006")
                return styles

            styled = (
                table_df.style
                .format({"Sell-through %": "{:.1f}%"})
                .apply(_color_st_row, subset=["Sell-through %"])
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Grouped bar chart — active vs sold count per keyword
            melted = plot_df[["keyword", "active_count", "sold_count"]].melt(
                id_vars="keyword", var_name="status", value_name="count"
            )
            melted["status"] = melted["status"].map(
                {"active_count": "Active", "sold_count": "Sold"}
            )

            fig2 = px.bar(
                melted,
                x="keyword",
                y="count",
                color="status",
                barmode="group",
                labels={"keyword": "Keyword", "count": "Count", "status": "Status"},
                title=f"Active vs sold count by keyword — {st_limit.lower()}",
                color_discrete_map={"Active": "#4e79a7", "Sold": "#f28e2b"},
            )
            fig2.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)
