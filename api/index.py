"""
Agent: Cold Outreach Slack Bot (Serverless / Vercel)
-----------------------------------------------------
Handles Slack slash commands and interactions over HTTP.
Vercel wakes this up on demand — no persistent process needed.

See workflows/slack_bot_setup.md for setup instructions.

Usage in Slack:
  /coldreach  →  opens a modal to enter company + context

Slack app requirements:
  - Socket Mode: OFF
  - Slash command /coldreach → Request URL: https://<your-app>.vercel.app/slack/events
  - Interactivity → Request URL:            https://<your-app>.vercel.app/slack/events
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Fix SSL certificate lookup on Vercel's Lambda runtime — must happen before
# any network imports so Python's ssl module picks up the correct CA bundle.
import ssl
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient

load_dotenv()

# Explicit SSL context passed to WebClient so all Slack API calls use
# certifi's CA bundle — fixes SSL errors on Vercel's Python runtime.
_ssl_ctx = ssl.create_default_context(cafile=certifi.where())
_slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"), ssl=_ssl_ctx)

bolt_app = App(
    client=_slack_client,
    signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(bolt_app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_sender() -> dict:
    return {
        "name":    os.getenv("SENDER_NAME", ""),
        "role":    os.getenv("SENDER_ROLE", ""),
        "from":    os.getenv("SENDER_COMPANY", ""),
        "product": os.getenv("SENDER_PRODUCT", ""),
    }


def format_email_for_slack(email: str) -> str:
    return "\n".join(
        f"*{line}*" if line.lower().startswith("subject:") else line
        for line in email.splitlines()
    )


def parse_email(email: str) -> tuple[str, str]:
    lines = email.splitlines()
    subject, body_lines, in_body = "", [], False
    for line in lines:
        if not in_body and line.lower().startswith("subject:"):
            subject = line[len("subject:"):].strip()
        elif not in_body and subject and not line.strip():
            in_body = True
        elif in_body:
            body_lines.append(line)
    return subject, "\n".join(body_lines).strip()


def email_blocks(email: str, company: str, context: str, approved: bool = False) -> list:
    state = json.dumps({"company": company, "context": context})
    actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Regenerate"},
            "action_id": "regenerate",
            "value": state,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Edit Context"},
            "action_id": "edit_context",
            "value": state,
        },
    ]
    if not approved:
        actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Approve Draft"},
            "action_id": "save_to_gmail",
            "value": state,
            "style": "primary",
        })
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": format_email_for_slack(email)},
        },
        {"type": "divider"},
        {"type": "actions", "block_id": "email_actions", "elements": actions},
    ]
    if approved:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "✓ Draft posted to channel"}],
        })
    return blocks


# ---------------------------------------------------------------------------
# Slack handlers
# ---------------------------------------------------------------------------

@bolt_app.command("/coldreach")
def handle_coldreach(ack, body, client):
    """
    Draft an email inline from the slash command text.
    Usage: /coldreach Company Name | Context about them
    ack() fires immediately — no trigger_id or modal needed.
    """
    ack()
    channel = body["channel_id"]

    text = body.get("text", "").strip()
    if not text or "|" not in text:
        client.chat_postMessage(
            channel=channel,
            text=(
                "*Usage:* `/coldreach Company Name | Context about them`\n"
                "*Example:* `/coldreach Stripe | They just launched Stripe Tax globally`"
            ),
        )
        return

    company, context = [p.strip() for p in text.split("|", 1)]
    if not company or not context:
        client.chat_postMessage(
            channel=channel,
            text="Both company and context are required. Example: `/coldreach Stripe | They just launched Stripe Tax globally`",
        )
        return

    result = client.chat_postMessage(channel=channel, text="Drafting email...")

    try:
        from tools.draft_email import draft_email
        email = draft_email(company, context, get_sender())
        client.chat_update(
            channel=channel,
            ts=result["ts"],
            text=email,
            blocks=email_blocks(email, company, context),
        )
    except Exception as e:
        client.chat_update(channel=channel, ts=result["ts"], text=f"Error drafting email: {e}", blocks=[])


@bolt_app.action("regenerate")
def handle_regenerate(ack, body, client):
    ack()
    from tools.draft_email import draft_email

    state = json.loads(body["actions"][0]["value"])
    company, context = state["company"], state["context"]
    channel, ts = body["channel"]["id"], body["message"]["ts"]

    client.chat_update(channel=channel, ts=ts, text="Regenerating...", blocks=[])
    try:
        email = draft_email(company, context, get_sender())
        client.chat_update(
            channel=channel, ts=ts, text=email,
            blocks=email_blocks(email, company, context),
        )
    except Exception as e:
        client.chat_update(channel=channel, ts=ts, text=f"Error regenerating: {e}", blocks=[])


@bolt_app.action("edit_context")
def handle_edit_context(ack, body, client):
    """Reply with instructions to re-run the command with updated context."""
    ack()
    state = json.loads(body["actions"][0]["value"])
    channel, ts = body["channel"]["id"], body["message"]["ts"]
    email = body["message"]["text"]
    client.chat_postEphemeral(
        channel=channel,
        user=body["user"]["id"],
        text=(
            f"To update context for *{state['company']}*, run:\n"
            f"`/coldreach {state['company']} | <your updated context>`"
        ),
    )
    client.chat_update(
        channel=channel, ts=ts, text=email,
        blocks=email_blocks(email, state["company"], state["context"], approved=False),
    )


@bolt_app.action("save_to_gmail")
def handle_approve_draft(ack, body, client):
    ack()
    state = json.loads(body["actions"][0]["value"])
    channel, ts = body["channel"]["id"], body["message"]["ts"]
    email_text = body["message"]["text"]

    client.chat_postMessage(channel=channel, text=email_text)
    client.chat_update(
        channel=channel, ts=ts, text=email_text,
        blocks=email_blocks(email_text, state["company"], state["context"], approved=True),
    )


# ---------------------------------------------------------------------------
# HTTP route + Vercel entry point
# ---------------------------------------------------------------------------

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


app = flask_app
