import os
import streamlit as st
import psycopg2
from tabs import ebay_tab, email_tab, youtube_tab

st.set_page_config(page_title="eBay / YouTube Assistant", layout="wide")


def get_db_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def db_status_indicator():
    try:
        conn = get_db_connection()
        conn.close()
        st.sidebar.success("Database connected")
    except Exception as e:
        st.sidebar.error(f"Database error: {e}")


db_status_indicator()

st.title("eBay / YouTube Assistant")

tab_email, tab_youtube, tab_ebay, tab_strategy, tab_chatter = st.tabs([
    "Email assistant",
    "YouTube monitor",
    "eBay inventory",
    "Research — strategy",
    "Research — chatter",
])

with tab_email:
    email_tab.render()

with tab_youtube:
    youtube_tab.render()

with tab_ebay:
    ebay_tab.render()

with tab_strategy:
    st.header("Research — strategy")
    st.info("Weekly AI content research and video idea pipeline. Coming in Phase 5.")

with tab_chatter:
    st.header("Research — chatter")
    st.info("Community buzz digest for filming reference. Coming in Phase 5.")
