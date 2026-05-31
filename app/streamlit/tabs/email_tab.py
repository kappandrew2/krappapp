"""
email_tab.py — Streamlit Email assistant tab.

Displays emails from both Gmail accounts with AI-generated draft responses.
Users can edit drafts inline, approve (sends via Gmail API), or override
(marks as handled externally).

Filter bar: New | Replied | Overridden | All  (default: New)
Sort: newest to oldest (received_at DESC)
"""

import os

import pandas as pd
import psycopg2
import streamlit as st

from utils import gmail_send


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
def _fetch_emails(status_filter: str) -> pd.DataFrame:
    """Fetch emails joined with account label. Filtered by status."""
    if status_filter == "New":
        where = "WHERE e.status = 'new'"
    elif status_filter == "Replied":
        where = "WHERE e.status = 'sent'"
    elif status_filter == "Overridden":
        where = "WHERE e.status = 'overridden'"
    else:
        where = ""

    return _query(
        f"""
        SELECT
            e.id,
            e.gmail_message_id,
            e.thread_id,
            e.from_address,
            e.subject,
            e.body_text,
            e.received_at,
            e.is_reply,
            e.classification,
            e.priority,
            e.status,
            e.ai_draft,
            e.final_reply,
            e.sent_at,
            COALESCE(a.label, 'unknown') AS account_label
        FROM emails e
        LEFT JOIN email_accounts a ON a.id = e.account_id
        {where}
        ORDER BY e.received_at DESC NULLS LAST
        """
    )


@st.cache_data(ttl=60)
def _fetch_summary() -> dict:
    return {
        "total_new":       _scalar("SELECT COUNT(*) FROM emails WHERE status = 'new'"),
        "total_high":      _scalar("SELECT COUNT(*) FROM emails WHERE priority = 'high' AND status = 'new'"),
        "last_fetched":    _scalar("SELECT MAX(received_at) FROM emails"),
    }


# ---------------------------------------------------------------------------
# DB actions
# ---------------------------------------------------------------------------

def _mark_sent(email_id: int, final_reply: str) -> None:
    _execute(
        """
        UPDATE emails
        SET status = 'sent', final_reply = %s, sent_at = NOW(), updated_at = NOW()
        WHERE id = %s
        """,
        (final_reply, email_id),
    )


def _mark_overridden(email_id: int) -> None:
    _execute(
        """
        UPDATE emails
        SET status = 'overridden', updated_at = NOW()
        WHERE id = %s
        """,
        (email_id,),
    )


# ---------------------------------------------------------------------------
# Sub-renderers
# ---------------------------------------------------------------------------

def _priority_badge(priority: str) -> str:
    """Return a colored markdown badge string."""
    if priority == "high":
        return "🔴 **HIGH**"
    return "⚪ normal"


def _render_email_card(row: pd.Series) -> None:
    """Render one email as a bordered card with expander for body and actions."""
    email_id       = int(row["id"])
    gmail_msg_id   = str(row["gmail_message_id"])
    thread_id      = row.get("thread_id") or None
    from_addr      = str(row["from_address"] or "")
    subject        = str(row["subject"] or "(no subject)")
    body_text      = str(row["body_text"] or "")
    received_at    = row["received_at"]
    is_reply       = bool(row["is_reply"])
    classification = str(row["classification"] or "—")
    priority       = str(row["priority"] or "normal")
    status         = str(row["status"] or "new")
    ai_draft       = str(row["ai_draft"] or "")
    account_label  = str(row["account_label"] or "unknown")

    date_str = received_at.strftime("%Y-%m-%d %H:%M") if received_at else "—"
    email_type = "Reply" if is_reply else "New email"
    account_display = "📦 eBay" if account_label == "ebay" else "▶️ YouTube"

    with st.container(border=True):
        # Header row
        h1, h2, h3, h4, h5 = st.columns([2, 1.5, 3, 2, 1.5])
        h1.caption(date_str)
        h2.caption(account_display)
        h3.write(f"**{from_addr}**")
        h4.caption(f"{email_type} · `{classification}`")
        h5.markdown(_priority_badge(priority))

        st.write(f"**{subject}**")

        # Full body expander
        with st.expander("Show full email", expanded=False):
            st.text(body_text)

        # Draft editing and actions
        if status == "new":
            draft_key = f"draft_{email_id}"
            # Initialize session state with ai_draft if not yet edited
            if draft_key not in st.session_state:
                st.session_state[draft_key] = ai_draft

            edited_draft = st.text_area(
                "Draft response",
                value=st.session_state[draft_key],
                key=f"textarea_{email_id}",
                height=150,
            )
            st.session_state[draft_key] = edited_draft

            col_approve, col_override = st.columns([1, 1])

            with col_approve:
                approve_disabled = not edited_draft.strip()
                if st.button(
                    "✅ Approve & Send",
                    key=f"approve_{email_id}",
                    disabled=approve_disabled,
                    help="Send this draft via Gmail" if not approve_disabled else "Draft is empty",
                ):
                    success = gmail_send.send_reply(
                        account_label=account_label,
                        to_address=from_addr,
                        subject=subject,
                        body_text=edited_draft,
                        thread_id=thread_id,
                        in_reply_to=gmail_msg_id,
                    )
                    if success:
                        _mark_sent(email_id, edited_draft)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Failed to send reply — check logs")

            with col_override:
                if st.checkbox(
                    "Override (handled externally)",
                    key=f"override_{email_id}",
                ):
                    _mark_overridden(email_id)
                    st.cache_data.clear()
                    st.rerun()

        elif status == "sent":
            st.success("✅ Replied")
            if row.get("final_reply"):
                with st.expander("Sent reply", expanded=False):
                    st.text(str(row["final_reply"]))

        elif status == "overridden":
            st.info("↩️ Handled externally (overridden)")


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render() -> None:
    st.header("Email assistant")

    # Summary bar
    s = _fetch_summary()
    c1, c2, c3 = st.columns(3)
    c1.metric("New emails", s["total_new"] or 0)
    c2.metric("High priority (new)", s["total_high"] or 0)
    last = s["last_fetched"]
    c3.metric(
        "Most recent email",
        last.strftime("%Y-%m-%d %H:%M") if last else "Never",
    )

    st.divider()

    # Filter bar
    filter_choice = st.radio(
        "Show", ["New", "Replied", "Overridden", "All"], horizontal=True
    )

    df = _fetch_emails(filter_choice)

    if df.empty:
        st.info(
            "No emails found. The email job runs every 6 hours — "
            "it fires automatically when the scheduler container starts."
            if filter_choice == "All"
            else f"No emails with status '{filter_choice.lower()}'."
        )
        return

    st.caption(f"{len(df)} email{'s' if len(df) != 1 else ''} shown")
    st.divider()

    for _, row in df.iterrows():
        _render_email_card(row)
        st.write("")  # vertical breathing room between cards
