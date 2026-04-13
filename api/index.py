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
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

load_dotenv()

bolt_app = App(
    token=os.getenv("SLACK_BOT_TOKEN"),
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


def email_blocks(email: str, company: str, context: str) -> list:
    state = json.dumps({"company": company, "context": context})
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": format_email_for_slack(email)},
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "email_actions",
            "elements": [
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
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Save to Gmail Drafts"},
                    "action_id": "save_to_gmail",
                    "value": state,
                    "style": "primary",
                },
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Slack handlers
# ---------------------------------------------------------------------------

@bolt_app.command("/coldreach")
def handle_coldreach(ack, body, say):
    """
    Draft an email inline from the slash command text.
    Usage: /coldreach Company Name | Context about them
    ack() fires immediately — no trigger_id or modal needed.
    """
    ack()

    text = body.get("text", "").strip()
    if not text or "|" not in text:
        say(
            text="Usage: `/coldreach Company Name | Context about them`",
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Usage:* `/coldreach Company Name | Context about them`\n"
                        "*Example:* `/coldreach Stripe | They just launched Stripe Tax globally`"
                    ),
                },
            }],
        )
        return

    company, context = [p.strip() for p in text.split("|", 1)]
    if not company or not context:
        say(text="Both company and context are required. Example: `/coldreach Stripe | They just launched Stripe Tax globally`")
        return

    say(text="Drafting email...")

    try:
        from tools.draft_email import draft_email
        email = draft_email(company, context, get_sender())
        say(blocks=email_blocks(email, company, context), text=email)
    except Exception as e:
        say(text=f"Error drafting email: {e}")


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
    client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=body["user"]["id"],
        text=(
            f"To update context for *{state['company']}*, run:\n"
            f"`/coldreach {state['company']} | <your updated context>`"
        ),
    )


@bolt_app.action("save_to_gmail")
def handle_save_to_gmail(ack, body, client):
    ack()
    from tools.save_to_gmail_drafts import save_draft

    channel = body["channel"]["id"]
    email_text = body["message"]["text"]
    subject, email_body = parse_email(email_text)

    try:
        url = save_draft(subject, email_body)
        client.chat_postMessage(channel=channel, text=f"Draft saved to Gmail: {url}")
    except FileNotFoundError:
        client.chat_postMessage(
            channel=channel,
            text="Gmail not configured. See `workflows/cold_outreach.md` for setup steps.",
        )
    except Exception as e:
        client.chat_postMessage(channel=channel, text=f"Error saving to Gmail: {e}")


# ---------------------------------------------------------------------------
# HTTP route + Vercel entry point
# ---------------------------------------------------------------------------

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


app = flask_app
