import os
import streamlit as st
import psycopg2

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
    st.header("Email assistant")
    st.info("Gmail inbox management and AI-assisted draft responses. Coming in Phase 4.")

with tab_youtube:
    st.header("YouTube monitor")
    st.info("Comment sentiment analysis and offensive comment review queue. Coming in Phase 3.")

with tab_ebay:
    st.header("eBay inventory")
    st.info("Inventory ETL, listing age analysis, and word frequency trends. Coming in Phase 2.")

with tab_strategy:
    st.header("Research — strategy")
    st.info("Weekly AI content research and video idea pipeline. Coming in Phase 5.")

with tab_chatter:
    st.header("Research — chatter")
    st.info("Community buzz digest for filming reference. Coming in Phase 5.")
