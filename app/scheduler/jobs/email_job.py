"""
email_job.py — Gmail email fetch, classification, and draft generation job.

Runs every 6 hours via APScheduler. For each monitored Gmail account:
  1. Fetch unread emails
  2. Deduplicate against gmail_message_id in Postgres
  3. AI-classify each new email (type + priority)
  4. Send SMS stub alert for high-priority emails
  5. Generate AI draft response
  6. Save to Postgres (status = 'new')
  7. Mark email as read in Gmail

Email accounts monitored:
  - kappandrew@gmail.com        (label: 'ebay')
  - andysaudiokrapp@gmail.com   (label: 'youtube')
"""

import base64
import email as email_lib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import anthropic as anthropic_sdk
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from db import get_connection

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Account configuration
# ---------------------------------------------------------------------------

ACCOUNTS = [
    {
        "label": "ebay",
        "email": "kappandrew@gmail.com",
        "token_path": os.environ.get(
            "GMAIL_EBAY_TOKEN_PATH", "/app/credentials/gmail_ebay_token.json"
        ),
        # Only fetch emails tagged with the eBayMessages Gmail label
        "gmail_query": "label:eBayMessages is:unread",
    },
    {
        "label": "youtube",
        "email": "andysaudiokrapp@gmail.com",
        "token_path": os.environ.get(
            "GMAIL_YOUTUBE_TOKEN_PATH", "/app/credentials/gmail_youtube_token.json"
        ),
        "gmail_query": "is:unread",
    },
]

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = (
    "You are an assistant helping manage a vintage audio eBay store and YouTube channel. "
    "Classify incoming emails using the provided QA knowledge base as context. "
    "Return only valid JSON with no markdown formatting."
)

CLASSIFY_PROMPT = """\
Classify the following email.

Classification types:
- shipping_inquiry — tracking, delivery questions
- item_specs — condition, specifications, testing questions
- availability — is item still available
- offer_negotiation — best offer, price negotiation
- return_request — returns, refunds, disputes
- collaboration — YouTube collaboration requests
- content_question — questions about video content
- spam — obvious spam or unsolicited commercial email
- general — anything that doesn't fit above

Priority rules:
- Set priority to "high" for: return_request, any email with negative sentiment \
(angry, threatening, dispute language)
- Set priority to "normal" for everything else

QA knowledge base (use for context):
{qa_context}

Email to classify:
From: {from_address}
Subject: {subject}
Body:
{body}

Return a JSON object with exactly these fields:
- type: one of the classification types above
- priority: "normal" or "high"
- reasoning: one sentence explaining the classification"""

DRAFT_SYSTEM = (
    "You are a helpful assistant drafting email replies for a vintage audio eBay store "
    "and YouTube channel owner. Write in a friendly, professional tone. "
    "Be concise and directly address the customer's question. "
    "Do not add subject lines, greetings like 'Dear Customer', or sign-offs — "
    "just the body text of the reply."
)

DRAFT_PROMPT = """\
Draft a reply to this email.

Classification: {classification}

QA knowledge base (use to ground your response):
{qa_context}

Original email:
From: {from_address}
Subject: {subject}
Body:
{body}

Write a helpful, concise reply that directly addresses the customer's message. \
Plain text only."""


# ---------------------------------------------------------------------------
# SMS stub
# ---------------------------------------------------------------------------

def send_sms_alert(message: str) -> None:
    """Send an SMS alert for high-priority emails.

    Currently a stub — logs to console. Replace the body of this function
    with real Twilio logic when A2P 10DLC registration is complete.
    Function signature and all call sites remain unchanged.

    Real implementation will use:
        from twilio.rest import Client
        client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
        client.messages.create(
            body=message,
            from_=os.environ["TWILIO_FROM_NUMBER"],
            to=os.environ["TWILIO_TO_NUMBER"],
        )
    """
    log.info("[SMS STUB] Would send: %s", message)


# ---------------------------------------------------------------------------
# Gmail client builder
# ---------------------------------------------------------------------------

def _build_gmail_client(token_path: str):
    """Load OAuth credentials and return an authorized Gmail API client.
    Auto-refreshes the access token if expired and writes it back to disk."""
    import json as _json

    with open(token_path) as f:
        info = _json.load(f)

    creds = Credentials(
        token=info.get("token"),
        refresh_token=info.get("refresh_token"),
        token_uri=info.get("token_uri"),
        client_id=info.get("client_id"),
        client_secret=info.get("client_secret"),
        scopes=info.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        log.info("Gmail token expired for %s — refreshing", token_path)
        creds.refresh(Request())
        info["token"] = creds.token
        with open(token_path, "w") as f:
            _json.dump(info, f, indent=2)
        log.info("Gmail token refreshed and saved")

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Email body extraction
# ---------------------------------------------------------------------------

def _decode_part(data: str) -> str:
    """Base64url-decode a Gmail message part body."""
    padded = data.replace("-", "+").replace("_", "/")
    padded += "=" * (4 - len(padded) % 4)
    return base64.b64decode(padded).decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    """Strip HTML tags, collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_body(payload: dict) -> str:
    """Recursively extract the best text body from a Gmail message payload.
    Prefers text/plain; falls back to stripped text/html."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return _decode_part(body_data)

    if mime_type == "text/html" and body_data:
        return _strip_html(_decode_part(body_data))

    # Multipart — recurse into parts, prefer plain
    parts = payload.get("parts", [])
    plain = ""
    html = ""
    for part in parts:
        result = _extract_body(part)
        sub_type = part.get("mimeType", "")
        if "plain" in sub_type and result:
            plain = result
        elif "html" in sub_type and result:
            html = result
        elif result:
            plain = plain or result

    return plain or html or ""


def _get_header(headers: list[dict], name: str) -> str:
    """Extract a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _ensure_accounts(conn) -> dict[str, int]:
    """Seed email_accounts if empty. Returns {label: db_id}."""
    with conn.cursor() as cur:
        cur.execute("SELECT label, id FROM email_accounts")
        existing = {row[0]: row[1] for row in cur.fetchall()}

    if existing:
        return existing

    log.info("email_accounts is empty — seeding two accounts")
    id_map: dict[str, int] = {}
    with conn.cursor() as cur:
        for account in ACCOUNTS:
            cur.execute(
                """
                INSERT INTO email_accounts (label, email, created_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (email) DO UPDATE SET label = EXCLUDED.label
                RETURNING id
                """,
                (account["label"], account["email"]),
            )
            id_map[account["label"]] = cur.fetchone()[0]
    conn.commit()
    log.info("email_accounts seeded: %s", id_map)
    return id_map


def _get_known_message_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT gmail_message_id FROM emails")
        return {row[0] for row in cur.fetchall()}


def _load_qa_pairs(conn) -> str:
    """Return active QA pairs formatted as a numbered list for prompts."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT question, answer FROM qa_pairs WHERE active = TRUE ORDER BY id"
        )
        rows = cur.fetchall()

    if not rows:
        return "(No QA pairs available)"

    lines = []
    for i, (q, a) in enumerate(rows, 1):
        lines.append(f"{i}. Q: {q}\n   A: {a}")
    return "\n\n".join(lines)


def _save_email(conn, record: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO emails (
                account_id, gmail_message_id, thread_id, from_address,
                subject, body_text, received_at, is_reply,
                classification, priority, status, ai_draft,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new', %s, NOW(), NOW())
            ON CONFLICT (gmail_message_id) DO NOTHING
            """,
            (
                record["account_id"],
                record["gmail_message_id"],
                record.get("thread_id"),
                record["from_address"],
                record.get("subject", ""),
                record.get("body_text", ""),
                record.get("received_at"),
                record.get("is_reply", False),
                record.get("classification"),
                record.get("priority", "normal"),
                record.get("ai_draft", ""),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# AI classification and draft generation
# ---------------------------------------------------------------------------

def _classify_email(
    anthropic_client, from_address: str, subject: str, body: str, qa_context: str
) -> tuple[str, str]:
    """Classify email. Returns (classification_type, priority)."""
    prompt = CLASSIFY_PROMPT.format(
        qa_context=qa_context,
        from_address=from_address,
        subject=subject,
        body=body[:2000],
    )
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=256,
            system=CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        result = json.loads(match.group() if match else text)
        classification = result.get("type", "general")
        priority = result.get("priority", "normal")
        log.info(
            "Classified email from %s: type=%s priority=%s reasoning=%s",
            from_address, classification, priority, result.get("reasoning", ""),
        )
        return classification, priority
    except Exception as e:
        log.error("Email classification failed for %s: %s", from_address, e)
        return "general", "normal"


def _generate_draft(
    anthropic_client,
    from_address: str,
    subject: str,
    body: str,
    classification: str,
    qa_context: str,
) -> str:
    """Generate a draft reply. Returns plain text or '' on failure."""
    prompt = DRAFT_PROMPT.format(
        classification=classification,
        qa_context=qa_context,
        from_address=from_address,
        subject=subject,
        body=body[:2000],
    )
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=512,
            system=DRAFT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.error("Draft generation failed for email from %s: %s", from_address, e)
        return ""


# ---------------------------------------------------------------------------
# Per-account fetch loop
# ---------------------------------------------------------------------------

def _process_account(
    gmail, account: dict, account_db_id: int, known_ids: set[str],
    anthropic_client, conn, qa_context: str
) -> int:
    """Fetch, classify, and save new emails for one account. Returns insert count."""
    label = account["label"]
    inserted = 0

    # Fetch unread message IDs using the per-account Gmail query
    gmail_query = account.get("gmail_query", "is:unread")
    log.info("[%s] Fetching messages with query: %s", label, gmail_query)
    try:
        result = gmail.users().messages().list(
            userId="me", q=gmail_query, maxResults=50
        ).execute()
    except Exception as e:
        log.error("[%s] Failed to list messages: %s", label, e)
        return 0

    messages = result.get("messages", [])
    if not messages:
        log.info("[%s] No unread messages", label)
        return 0

    log.info("[%s] %d unread messages found", label, len(messages))

    for msg_meta in messages:
        gmail_message_id = msg_meta["id"]

        # Deduplicate
        if gmail_message_id in known_ids:
            # Still mark as read so it doesn't keep appearing
            _mark_read(gmail, gmail_message_id, label)
            continue

        # Fetch full message
        try:
            msg = gmail.users().messages().get(
                userId="me", id=gmail_message_id, format="full"
            ).execute()
        except Exception as e:
            log.error("[%s] Failed to fetch message %s: %s", label, gmail_message_id, e)
            continue

        # Parse headers
        headers = msg.get("payload", {}).get("headers", [])
        from_address = _get_header(headers, "From")
        subject = _get_header(headers, "Subject")
        in_reply_to = _get_header(headers, "In-Reply-To")
        is_reply = bool(in_reply_to)
        thread_id = msg.get("threadId")

        # Parse received_at from internalDate (milliseconds epoch)
        internal_date_ms = int(msg.get("internalDate", 0))
        received_at = datetime.fromtimestamp(
            internal_date_ms / 1000, tz=timezone.utc
        ) if internal_date_ms else None

        # Extract body
        body_text = _extract_body(msg.get("payload", {}))

        # Skip empty or spam-like messages with no body
        if not from_address:
            log.info("[%s] Skipping message %s — no From header", label, gmail_message_id)
            _mark_read(gmail, gmail_message_id, label)
            continue

        # AI classify
        classification, priority = _classify_email(
            anthropic_client, from_address, subject, body_text, qa_context
        )

        # SMS alert for high priority
        if priority == "high":
            sms_message = (
                f"High priority email from {from_address}: {subject}"
            )
            send_sms_alert(sms_message)

        # AI draft
        ai_draft = _generate_draft(
            anthropic_client, from_address, subject, body_text, classification, qa_context
        )

        # Save to DB
        record = {
            "account_id": account_db_id,
            "gmail_message_id": gmail_message_id,
            "thread_id": thread_id,
            "from_address": from_address,
            "subject": subject,
            "body_text": body_text,
            "received_at": received_at,
            "is_reply": is_reply,
            "classification": classification,
            "priority": priority,
            "ai_draft": ai_draft,
        }
        _save_email(conn, record)
        known_ids.add(gmail_message_id)
        inserted += 1

        # Mark as read in Gmail
        _mark_read(gmail, gmail_message_id, label)

        time.sleep(0.5)  # Gentle rate limiting between API calls

    log.info("[%s] %d new emails processed and saved", label, inserted)
    return inserted


def _mark_read(gmail, gmail_message_id: str, label: str) -> None:
    """Remove UNREAD label from a Gmail message."""
    try:
        gmail.users().messages().modify(
            userId="me",
            id=gmail_message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except Exception as e:
        log.warning("[%s] Failed to mark message %s as read: %s", label, gmail_message_id, e)


# ---------------------------------------------------------------------------
# Main job orchestrator
# ---------------------------------------------------------------------------

def run_email_job() -> None:
    started = datetime.utcnow()
    log.info("Email job starting at %s UTC", started.isoformat())

    anthropic_client = anthropic_sdk.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    conn = get_connection()

    try:
        # Ensure email_accounts are seeded
        account_id_map = _ensure_accounts(conn)

        # Load QA pairs once for the whole run
        qa_context = _load_qa_pairs(conn)
        log.info("Loaded QA context (%d chars)", len(qa_context))

        # Load known message IDs for deduplication
        known_ids = _get_known_message_ids(conn)
        log.info("Known gmail_message_ids in DB: %d", len(known_ids))

        total_inserted = 0

        for account in ACCOUNTS:
            label = account["label"]
            token_path = account["token_path"]

            if not os.path.exists(token_path):
                log.warning(
                    "[%s] Token file not found at %s — skipping account", label, token_path
                )
                continue

            try:
                gmail = _build_gmail_client(token_path)
            except Exception as e:
                log.error("[%s] Failed to build Gmail client: %s", label, e)
                continue

            account_db_id = account_id_map.get(label)
            if account_db_id is None:
                log.error("[%s] No DB account ID found — skipping", label)
                continue

            count = _process_account(
                gmail, account, account_db_id, known_ids,
                anthropic_client, conn, qa_context
            )
            total_inserted += count

        elapsed = (datetime.utcnow() - started).total_seconds()
        log.info(
            "Email job complete in %.1fs — %d new emails saved across all accounts",
            elapsed, total_inserted,
        )

    except Exception:
        log.exception("Email job failed")
    finally:
        conn.close()
