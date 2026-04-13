"""
Tool: save_to_gmail_drafts
--------------------------
Creates a Gmail draft from a subject line, body, and optional recipient.

Authentication (two modes):
  Local:  credentials.json + token.json in the project root.
          On first run a browser window opens for consent; token.json is saved
          and reused automatically on subsequent runs.

  Cloud:  Set GMAIL_TOKEN_JSON env var to the full contents of token.json.
          Used when running on a server (Railway etc.) where file storage and
          browser-based OAuth flows are unavailable.

  Required OAuth scope: https://www.googleapis.com/auth/gmail.compose
  (compose-only — does not allow reading your email)

Inputs (via function call or CLI flags):
  --subject    Email subject line
  --body       Email body text
  --to         Recipient email address (optional — can be filled in Gmail later)

Output:
  Prints the Gmail draft URL on success.

Exit codes:
  0  success
  1  authentication error
  2  API error
"""

import argparse
import base64
import json
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

ROOT = Path(__file__).parent.parent
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"


def get_gmail_service():
    """
    Authenticate and return a Gmail API service object.

    Tries env var GMAIL_TOKEN_JSON first (cloud mode), then falls back to
    local token.json / credentials.json (local mode).
    """
    creds = None

    # --- Cloud mode: token supplied via environment variable ---
    token_json_env = os.getenv("GMAIL_TOKEN_JSON")
    if token_json_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_json_env), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)

    # --- Local mode: token.json / credentials.json on disk ---
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_PATH}\n"
            "  Follow the setup instructions in workflows/cold_outreach.md to create one."
        )

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def save_draft(subject: str, body: str, to: str = "") -> str:
    """
    Create a Gmail draft and return its URL.

    Args:
        subject:  Email subject line.
        body:     Email body (plain text).
        to:       Recipient address (optional).

    Returns:
        URL to the saved draft in Gmail.

    Raises:
        FileNotFoundError if credentials.json is missing (local mode).
        HttpError on Gmail API failures.
    """
    service = get_gmail_service()

    message = MIMEText(body)
    message["subject"] = subject
    if to:
        message["to"] = to

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": encoded}},
    ).execute()

    draft_id = draft["id"]
    return f"https://mail.google.com/mail/u/0/#drafts/{draft_id}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Save an email to Gmail Drafts.")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--body",    required=True, help="Email body text")
    parser.add_argument("--to",      default="",    help="Recipient email (optional)")
    args = parser.parse_args()

    try:
        url = save_draft(args.subject, args.body, args.to)
        print(f"Draft saved: {url}")
    except FileNotFoundError as e:
        print(f"Setup error: {e}", file=sys.stderr)
        sys.exit(1)
    except HttpError as e:
        print(f"Gmail API error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
