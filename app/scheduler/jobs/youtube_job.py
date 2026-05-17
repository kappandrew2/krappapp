"""
YouTube comment monitor job.
Fetches comments from all channel videos, classifies them with Claude,
generates per-video summaries, and saves everything to Postgres.
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime

import anthropic as anthropic_sdk
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from db import get_connection

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = (
    "You are a content moderator for a vintage audio equipment YouTube channel. "
    "Classify comments for sentiment and offensive content. "
    "Return only valid JSON with no markdown formatting."
)

CLASSIFY_PROMPT = """\
Classify each YouTube comment below.

For each comment return:
- comment_id: the id field from input, unchanged
- sentiment: "positive", "neutral", or "negative"
- is_offensive: true or false
- offensive_reason: if offensive, one of "spam", "personal_attack", "profanity", \
"harassment", "other". If not offensive, use null.

Return a JSON array — one object per comment, in the same order as input.

Comments to classify:
{comments_json}"""

SUMMARY_SYSTEM = (
    "You are summarizing YouTube comment sections for a vintage audio equipment channel. "
    "Return only valid JSON with no markdown formatting."
)

SUMMARY_PROMPT = """\
Summarize the comment discussion for the video titled "{title}".

Stats: {total} total comments — {positive} positive, {neutral} neutral, \
{negative} negative, {flagged} flagged as offensive.

Sample comments (up to 50):
{sample}

Return a JSON object with exactly these fields:
- themes: array of 3 to 7 short keywords or phrases (main discussion topics)
- summary_text: 2 to 3 sentence natural language summary of the overall discussion"""


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class QuotaExceededError(Exception):
    pass


# ---------------------------------------------------------------------------
# Client builders
# ---------------------------------------------------------------------------

def _build_youtube():
    return build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])


def _build_anthropic():
    return anthropic_sdk.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Step 1 — Channel and video discovery
# ---------------------------------------------------------------------------

def get_uploads_playlist_id(youtube, channel_id: str) -> str:
    response = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"Channel not found or not accessible with API key: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_all_video_ids(youtube, playlist_id: str) -> list[str]:
    """Page through the uploads playlist. Returns all video ID strings."""
    video_ids: list[str] = []
    page_token = None
    while True:
        response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in response.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)
    log.info("Found %d videos in uploads playlist", len(video_ids))
    return video_ids


# ---------------------------------------------------------------------------
# Step 2 — Upsert video metadata
# ---------------------------------------------------------------------------

def upsert_videos(conn, youtube, video_ids: list[str]) -> dict[str, int]:
    """Fetch video stats in batches of 50 and upsert into youtube_videos.
    Returns {youtube_video_id_string: db_integer_id}."""
    id_map: dict[str, int] = {}

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        try:
            response = youtube.videos().list(
                part="snippet,statistics",
                id=",".join(batch),
            ).execute()
        except HttpError as e:
            log.warning("Error fetching video metadata batch at index %d: %s", i, e)
            time.sleep(1)
            continue

        with conn.cursor() as cur:
            for item in response.get("items", []):
                yt_id = item["id"]
                title = item["snippet"]["title"]
                published_raw = item["snippet"].get("publishedAt", "")
                published_at = published_raw.replace("Z", "+00:00") if published_raw else None
                stats = item.get("statistics", {})
                view_count = int(stats.get("viewCount", 0))
                comment_count = int(stats.get("commentCount", 0))

                cur.execute(
                    """
                    INSERT INTO youtube_videos
                        (youtube_video_id, title, published_at, view_count, comment_count,
                         last_fetched_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), NOW())
                    ON CONFLICT (youtube_video_id) DO UPDATE SET
                        title           = EXCLUDED.title,
                        view_count      = EXCLUDED.view_count,
                        comment_count   = EXCLUDED.comment_count,
                        last_fetched_at = NOW(),
                        updated_at      = NOW()
                    RETURNING id
                    """,
                    (yt_id, title, published_at, view_count, comment_count),
                )
                db_id = cur.fetchone()[0]
                id_map[yt_id] = db_id

        conn.commit()
        time.sleep(1)

    log.info("Upserted %d videos", len(id_map))
    return id_map


# ---------------------------------------------------------------------------
# Step 3 — Fetch new comments
# ---------------------------------------------------------------------------

def get_known_comment_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT youtube_comment_id FROM youtube_comments")
        return {row[0] for row in cur.fetchall()}


def fetch_new_comments(youtube, yt_video_id: str, known_ids: set[str]) -> list[dict]:
    """Fetch top-level comments for one video, skipping already-known IDs.
    Returns [] on comments-disabled. Raises QuotaExceededError on quota."""
    comments: list[dict] = []
    page_token = None

    try:
        while True:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=yt_video_id,
                maxResults=100,
                pageToken=page_token,
                textFormat="plainText",
                order="time",
            ).execute()

            for item in response.get("items", []):
                top = item["snippet"]["topLevelComment"]
                comment_id = top["id"]
                if comment_id in known_ids:
                    continue
                snippet = top["snippet"]
                published_raw = snippet.get("publishedAt", "")
                comments.append(
                    {
                        "youtube_comment_id": comment_id,
                        "yt_video_id": yt_video_id,
                        "author_name": snippet.get("authorDisplayName"),
                        "body_text": snippet.get("textDisplay", ""),
                        "published_at": published_raw.replace("Z", "+00:00") if published_raw else None,
                    }
                )

            page_token = response.get("nextPageToken")
            if not page_token:
                break
            time.sleep(1)

    except HttpError as e:
        error_str = str(e)
        status = e.resp.status if hasattr(e, "resp") else 0
        if "commentsDisabled" in error_str:
            log.info("Comments disabled for video %s — skipping", yt_video_id)
        elif "quotaExceeded" in error_str or status == 429:
            log.error("YouTube API quota exceeded — stopping comment fetch")
            raise QuotaExceededError()
        else:
            log.warning(
                "HTTP %s fetching comments for video %s — skipping: %s",
                status, yt_video_id, e,
            )

    return comments


# ---------------------------------------------------------------------------
# Step 4 — AI classification
# ---------------------------------------------------------------------------

def _classify_batch(anthropic_client, batch: list[dict]) -> dict[str, dict]:
    """Call Claude once for a batch of up to 20 comments.
    Returns {youtube_comment_id: result_dict}. Empty dict on failure."""
    items = [
        {"comment_id": c["youtube_comment_id"], "text": c["body_text"][:400]}
        for c in batch
    ]
    prompt = CLASSIFY_PROMPT.format(comments_json=json.dumps(items, ensure_ascii=False))

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            system=CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Handle possible markdown code fences
        match = re.search(r"\[.*\]", text, re.DOTALL)
        results = json.loads(match.group() if match else text)
        return {r["comment_id"]: r for r in results}
    except Exception as e:
        log.error("Classification batch failed: %s", e)
        return {}


def classify_comments(anthropic_client, comments: list[dict]) -> None:
    """Classify all comments in batches of 20. Modifies each dict in place."""
    total = len(comments)
    for i in range(0, total, 20):
        batch = comments[i : i + 20]
        results = _classify_batch(anthropic_client, batch)
        for c in batch:
            r = results.get(c["youtube_comment_id"], {})
            c["sentiment"] = r.get("sentiment", "unknown")
            c["is_offensive"] = bool(r.get("is_offensive", False))
            c["offensive_reason"] = r.get("offensive_reason") or None
        log.info(
            "Classified comments %d–%d of %d",
            i + 1, min(i + 20, total), total,
        )
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Step 5 — Save comments
# ---------------------------------------------------------------------------

def save_comments(conn, comments: list[dict], video_id_map: dict[str, int]) -> int:
    """Insert new comments. ON CONFLICT DO NOTHING for deduplication safety.
    Returns number of rows inserted."""
    inserted = 0
    with conn.cursor() as cur:
        for c in comments:
            db_video_id = video_id_map.get(c["yt_video_id"])
            cur.execute(
                """
                INSERT INTO youtube_comments
                    (youtube_comment_id, video_id, author_name, body_text, published_at,
                     sentiment, is_offensive, offensive_reason, review_status,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
                ON CONFLICT (youtube_comment_id) DO NOTHING
                """,
                (
                    c["youtube_comment_id"],
                    db_video_id,
                    c.get("author_name"),
                    c.get("body_text"),
                    c.get("published_at") or None,
                    c.get("sentiment", "unknown"),
                    c.get("is_offensive", False),
                    c.get("offensive_reason"),
                ),
            )
            if cur.rowcount:
                inserted += 1
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Step 6 — Per-video summary
# ---------------------------------------------------------------------------

def generate_and_save_summary(
    anthropic_client, conn, db_video_id: int, video_title: str, run_date: date
) -> None:
    """Generate a Claude summary for a video and insert into youtube_video_summaries."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT body_text, sentiment, is_offensive FROM youtube_comments "
            "WHERE video_id = %s AND body_text IS NOT NULL",
            (db_video_id,),
        )
        rows = cur.fetchall()

    if not rows:
        return

    total = len(rows)
    positive = sum(1 for r in rows if r[1] == "positive")
    neutral = sum(1 for r in rows if r[1] == "neutral")
    negative = sum(1 for r in rows if r[1] == "negative")
    flagged = sum(1 for r in rows if r[2])
    sample = json.dumps([r[0][:200] for r in rows[:50]], ensure_ascii=False)

    prompt = SUMMARY_PROMPT.format(
        title=video_title,
        total=total,
        positive=positive,
        neutral=neutral,
        negative=negative,
        flagged=flagged,
        sample=sample,
    )

    themes: list[str] = []
    summary_text: str = ""
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=512,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        result = json.loads(match.group() if match else text)
        themes = result.get("themes", [])
        summary_text = result.get("summary_text", "")
    except Exception as e:
        log.error("Summary generation failed for video_id=%d: %s", db_video_id, e)

    with conn.cursor() as cur:
        # Delete any existing row for this video+date before inserting so that
        # re-runs (e.g. after backfill reclassification) overwrite stale data.
        cur.execute(
            "DELETE FROM youtube_video_summaries WHERE video_id = %s AND run_date = %s",
            (db_video_id, run_date),
        )
        cur.execute(
            """
            INSERT INTO youtube_video_summaries
                (video_id, run_date, total_comments, positive_count, neutral_count,
                 negative_count, flagged_count, themes, summary_text, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (db_video_id, run_date, total, positive, neutral, negative, flagged, themes, summary_text),
        )
    conn.commit()
    log.info("Summary saved for video_id=%d run_date=%s", db_video_id, run_date)


# ---------------------------------------------------------------------------
# Backfill — classify any comments saved with sentiment = 'unknown'
# ---------------------------------------------------------------------------

def backfill_unclassified_comments(conn, anthropic_client) -> None:
    """Classify comments that were saved with sentiment='unknown' due to a prior
    API failure. Updates sentiment, is_offensive, and offensive_reason in place.
    Generates fresh per-video summaries for all affected videos.
    Safe to call on every job run — returns immediately when nothing to do."""

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, youtube_comment_id, video_id, body_text "
            "FROM youtube_comments WHERE sentiment = 'unknown' ORDER BY id"
        )
        rows = cur.fetchall()

    total = len(rows)
    if total == 0:
        log.info("Backfill: no unclassified comments — nothing to do")
        return

    log.info("Backfill: %d unclassified comments found — starting classification", total)

    comments = [
        {"youtube_comment_id": row[1], "body_text": row[3] or ""}
        for row in rows
    ]
    # Map comment_id → db video_id so we know which videos to summarise later
    video_id_by_comment: dict[str, int] = {
        row[1]: row[2] for row in rows if row[2] is not None
    }
    affected_video_ids: set[int] = set()

    for i in range(0, total, 20):
        batch = comments[i : i + 20]
        results = _classify_batch(anthropic_client, batch)

        with conn.cursor() as cur:
            for c in batch:
                r = results.get(c["youtube_comment_id"], {})
                sentiment = r.get("sentiment", "unknown")
                if sentiment == "unknown":
                    continue  # batch failed — leave row unchanged, retry next run
                is_offensive = bool(r.get("is_offensive", False))
                offensive_reason = r.get("offensive_reason") or None

                cur.execute(
                    """
                    UPDATE youtube_comments
                    SET sentiment = %s,
                        is_offensive = %s,
                        offensive_reason = %s,
                        updated_at = NOW()
                    WHERE youtube_comment_id = %s
                    """,
                    (sentiment, is_offensive, offensive_reason, c["youtube_comment_id"]),
                )

                vid_id = video_id_by_comment.get(c["youtube_comment_id"])
                if vid_id:
                    affected_video_ids.add(vid_id)

        conn.commit()

        # Log progress at every 100-comment boundary
        if i > 0 and i % 100 == 0:
            log.info("Backfill progress: %d / %d comments processed", i, total)

        time.sleep(0.5)

    log.info(
        "Backfill: classification complete — %d comments processed, %d videos affected",
        total, len(affected_video_ids),
    )

    if not affected_video_ids:
        return

    # Regenerate per-video summaries for every video that received new classifications
    run_date = date.today()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title FROM youtube_videos WHERE id = ANY(%s)",
            (list(affected_video_ids),),
        )
        video_rows = cur.fetchall()

    for db_video_id, title in video_rows:
        generate_and_save_summary(anthropic_client, conn, db_video_id, title, run_date)
        time.sleep(0.5)

    log.info("Backfill: summaries regenerated for %d videos", len(video_rows))

    # ------------------------------------------------------------------
    # Phase 2 — correct any existing summary rows that still have all-zero
    # counts (created before comments were classified).  Reads live counts
    # directly from youtube_comments and UPDATE the offending rows in place.
    # ------------------------------------------------------------------
    log.info("Backfill: scanning for zero-count summary rows to correct")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, video_id
            FROM youtube_video_summaries
            WHERE positive_count = 0
              AND neutral_count  = 0
              AND negative_count = 0
              AND flagged_count  = 0
            """
        )
        zero_summaries = cur.fetchall()

    if not zero_summaries:
        log.info("Backfill: no zero-count summary rows — nothing to correct")
        return

    log.info(
        "Backfill: %d zero-count summary rows found — recalculating from live comments",
        len(zero_summaries),
    )

    with conn.cursor() as cur:
        for summary_id, video_id in zero_summaries:
            cur.execute(
                "SELECT sentiment, is_offensive FROM youtube_comments WHERE video_id = %s",
                (video_id,),
            )
            crows = cur.fetchall()
            if not crows:
                continue
            total_c    = len(crows)
            positive_c = sum(1 for r in crows if r[0] == "positive")
            neutral_c  = sum(1 for r in crows if r[0] == "neutral")
            negative_c = sum(1 for r in crows if r[0] == "negative")
            flagged_c  = sum(1 for r in crows if r[1])
            cur.execute(
                """
                UPDATE youtube_video_summaries
                SET total_comments = %s,
                    positive_count = %s,
                    neutral_count  = %s,
                    negative_count = %s,
                    flagged_count  = %s
                WHERE id = %s
                """,
                (total_c, positive_c, neutral_c, negative_c, flagged_c, summary_id),
            )

    conn.commit()
    log.info("Backfill: corrected counts for %d summary rows", len(zero_summaries))


# ---------------------------------------------------------------------------
# Main job orchestrator
# ---------------------------------------------------------------------------

def run_youtube_job() -> None:
    started = datetime.utcnow()
    log.info("YouTube job starting at %s UTC", started.isoformat())

    channel_id = os.environ["YOUTUBE_CHANNEL_ID"]
    youtube = _build_youtube()
    anthropic_client = _build_anthropic()
    conn = get_connection()

    try:
        # 0. Backfill any comments left unclassified by prior API failures
        backfill_unclassified_comments(conn, anthropic_client)

        # 1. Uploads playlist
        playlist_id = get_uploads_playlist_id(youtube, channel_id)
        log.info("Uploads playlist ID: %s", playlist_id)

        # 2. All video IDs
        video_ids = fetch_all_video_ids(youtube, playlist_id)

        # 3. Upsert video metadata; get {yt_id → db_id} map
        video_id_map = upsert_videos(conn, youtube, video_ids)

        # 4. Known comment IDs for deduplication
        known_ids = get_known_comment_ids(conn)
        log.info("Known comment IDs in DB: %d", len(known_ids))

        # 5. Fetch new comments per video
        all_new: list[dict] = []
        videos_with_new: set[str] = set()

        for yt_video_id in video_ids:
            if yt_video_id not in video_id_map:
                continue
            try:
                new = fetch_new_comments(youtube, yt_video_id, known_ids)
                if new:
                    all_new.extend(new)
                    videos_with_new.add(yt_video_id)
                    known_ids.update(c["youtube_comment_id"] for c in new)
                time.sleep(1)
            except QuotaExceededError:
                log.error("Quota exceeded — stopping comment fetch early")
                break

        log.info(
            "New comments: %d across %d videos", len(all_new), len(videos_with_new)
        )

        # 6. AI classify
        if all_new:
            classify_comments(anthropic_client, all_new)

        # 7. Save comments
        if all_new:
            inserted = save_comments(conn, all_new, video_id_map)
            log.info("Inserted %d new comments", inserted)

        # 8. Per-video summaries for videos with new activity
        run_date = date.today()
        with conn.cursor() as cur:
            cur.execute("SELECT youtube_video_id, id, title FROM youtube_videos")
            title_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        for yt_video_id in videos_with_new:
            if yt_video_id in title_map:
                db_id, title = title_map[yt_video_id]
                generate_and_save_summary(anthropic_client, conn, db_id, title, run_date)
                time.sleep(0.5)

        elapsed = (datetime.utcnow() - started).total_seconds()
        log.info("YouTube job complete in %.1fs", elapsed)

    except Exception:
        log.exception("YouTube job failed")
    finally:
        conn.close()
