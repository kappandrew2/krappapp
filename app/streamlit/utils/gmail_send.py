"""
gmail_send.py — OAuth-authenticated Gmail send helper for the Streamlit
Approve action.

Loads OAuth credentials from the token file for the account that received
the email, constructs a MIME reply, and sends it via the Gmail API.

Returns True on success, False on any failure. All failures are logged;
none are raised to the caller.
"""

import base64
import json
import logging
import os
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

# Token paths — same env vars used by the scheduler email job
_TOKEN_PATHS = {
    "ebay":    os.environ.get("GMAIL_EBAY_TOKEN_PATH",    "/app/credentials/gmail_ebay_token.json"),
    "youtube": os.environ.get("GMAIL_YOUTUBE_TOKEN_PATH", "/app/credentials/gmail_youtube_token.json"),
}


def _build_gmail_client(token_path: str):
    """Load OAuth credentials and return an authorized Gmail API client."""
    with open(token_path) as f:
        info = json.load(f)

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
            json.dump(info, f, indent=2)
        log.info("Gmail token refreshed and saved")

    return build("gmail", "v1", credentials=creds)


def send_reply(
    account_label: str,
    to_address: str,
    subject: str,
    body_text: str,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
) -> bool:
    """Send an email reply from the given account.

    Args:
        account_label:  'ebay' or 'youtube' — selects which OAuth token to use
        to_address:     recipient email address
        subject:        email subject (will be prefixed with 'Re: ' if not already)
        body_text:      plain text body of the reply
        thread_id:      Gmail thread ID to attach the reply to (optional)
        in_reply_to:    original gmail_message_id for In-Reply-To header (optional)

    Returns True on success, False on any failure.
    """
    token_path = _TOKEN_PATHS.get(account_label)
    if not token_path:
        log.error("Unknown account label '%s' — must be 'ebay' or 'youtube'", account_label)
        return False

    if not os.path.exists(token_path):
        log.error(
            "OAuth token file not found at %s for account '%s'", token_path, account_label
        )
        return False

    try:
        gmail = _build_gmail_client(token_path)
    except Exception as e:
        log.error("Failed to build Gmail client for account '%s': %s", account_label, e)
        return False

    # Construct MIME reply
    re_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg = MIMEText(body_text, "plain", "utf-8")
    msg["To"] = to_address
    msg["Subject"] = re_subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    send_body: dict = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    try:
        gmail.users().messages().send(userId="me", body=send_body).execute()
        log.info("Reply sent via account '%s' to %s", account_label, to_address)
        return True
    except Exception as e:
        log.error(
            "Failed to send reply via account '%s' to %s: %s", account_label, to_address, e
        )
        return False
