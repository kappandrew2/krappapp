"""
youtube_delete.py — OAuth-authenticated YouTube comment deletion helper.

Loads credentials from /app/credentials/youtube_oauth_token.json, refreshes
the access token if expired, and calls comments().delete() via the YouTube
Data API v3. Requires the youtube.force-ssl scope on the OAuth credential.

Returns True on success, False on any failure (missing file, bad token,
API error). All failures are logged; none are raised.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

TOKEN_PATH = os.environ.get(
    "YOUTUBE_OAUTH_TOKEN_PATH",
    "/app/credentials/youtube_oauth_token.json",
)


def _build_authed_youtube():
    """Load OAuth credentials and return an authorized YouTube API client."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    with open(TOKEN_PATH) as f:
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
        log.info("OAuth token expired — refreshing")
        creds.refresh(Request())
        # Persist the refreshed token so the next call doesn't need to refresh again
        info["token"] = creds.token
        with open(TOKEN_PATH, "w") as f:
            json.dump(info, f, indent=2)
        log.info("OAuth token refreshed and saved")

    return build("youtube", "v3", credentials=creds)


def delete_youtube_comment(youtube_comment_id: str) -> bool:
    """Delete a YouTube comment by its comment ID via comments().delete().

    Returns True on success, False on any failure.
    Missing token file, expired/invalid credentials, and API errors are all
    caught and logged rather than raised.
    """
    try:
        youtube = _build_authed_youtube()
        youtube.comments().delete(id=youtube_comment_id).execute()
        log.info("Deleted YouTube comment %s", youtube_comment_id)
        return True
    except FileNotFoundError:
        log.error(
            "OAuth token file not found at %s — run the one-time authorization "
            "flow to generate it before using comment deletion",
            TOKEN_PATH,
        )
        return False
    except Exception as e:
        log.error("Failed to delete YouTube comment %s: %s", youtube_comment_id, e)
        return False
