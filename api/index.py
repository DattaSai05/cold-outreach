"""
Agent: Cold Outreach Slack Bot (Serverless / Vercel)
-----------------------------------------------------
Handles Slack slash commands and interactions over HTTP.
Vercel wakes this up on demand — no persistent process needed.

See workflows/slack_bot_setup.md for Slack app and Vercel setup.

Slack app requirements:
  - Socket Mode: OFF
  - Slash command /outreach → Request URL: https://<your-app>.vercel.app/slack/events
  - Interactivity → Request URL:           https://<your-app>.vercel.app/slack/events
"""

import json
import os
import sys
from pathlib import Path

# Make tools/ importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

from tools.draft_email import draft_email
from tools.save_to_gmail_drafts import save_draft

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
    """Bold the subject line for Slack mrkdwn."""
    return "\n".join(
        f"*{line}*" if line.lower().startswith("subject:") else line
        for line in email.splitlines()
    )


def parse_email(email: str) -> tuple[str, str]:
    """Split 'Subject: ...\n\n<body>' into (subject, body)."""
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
    """
    Build Block Kit blocks for a drafted email.
    State (company + context) is encoded in button values — no server-side storage needed.
    """
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
def handle_outreach(ack, body, client):
    """Open the input modal when /coldreach is used."""
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "draft_email_modal",
            "private_metadata": body["channel_id"],
            "title": {"type": "plain_text", "text": "Cold Outreach"},
            "submit": {"type": "plain_text", "text": "Draft Email"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "company_block",
                    "label": {"type": "plain_text", "text": "Target Company"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "company_input",
                        "placeholder": {"type": "plain_text", "text": "e.g. Stripe"},
                    },
                },
                {
                    "type": "input",
                    "block_id": "context_block",
                    "label": {"type": "plain_text", "text": "Context"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "context_input",
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "What you know about them, why you're reaching out...",
                        },
                    },
                },
            ],
        },
    )


@bolt_app.view("draft_email_modal")
def handle_modal_submit(ack, body, client):
    """Draft the email and post it to the channel on modal submit."""
    ack()
    values = body["view"]["state"]["values"]
    company = values["company_block"]["company_input"]["value"]
    context = values["context_block"]["context_input"]["value"]
    channel = body["view"]["private_metadata"]

    result = client.chat_postMessage(channel=channel, text="Drafting email...")
    email = draft_email(company, context, get_sender())
    client.chat_update(
        channel=channel,
        ts=result["ts"],
        text=email,
        blocks=email_blocks(email, company, context),
    )


@bolt_app.action("regenerate")
def handle_regenerate(ack, body, client):
    """Regenerate the draft in place."""
    ack()
    state = json.loads(body["actions"][0]["value"])
    company, context = state["company"], state["context"]
    channel, ts = body["channel"]["id"], body["message"]["ts"]

    client.chat_update(channel=channel, ts=ts, text="Regenerating...", blocks=[])
    email = draft_email(company, context, get_sender())
    client.chat_update(
        channel=channel, ts=ts, text=email,
        blocks=email_blocks(email, company, context),
    )


@bolt_app.action("edit_context")
def handle_edit_context(ack, body, client):
    """Open a modal pre-filled with current context."""
    ack()
    state = json.loads(body["actions"][0]["value"])
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "edit_context_modal",
            "private_metadata": json.dumps({
                "company": state["company"],
                "channel": body["channel"]["id"],
                "message_ts": body["message"]["ts"],
            }),
            "title": {"type": "plain_text", "text": "Edit Context"},
            "submit": {"type": "plain_text", "text": "Regenerate"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "context_block",
                    "label": {"type": "plain_text", "text": "Context"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "context_input",
                        "multiline": True,
                        "initial_value": state["context"],
                    },
                },
            ],
        },
    )


@bolt_app.view("edit_context_modal")
def handle_edit_context_submit(ack, body, client):
    """Update context and regenerate the draft."""
    ack()
    meta = json.loads(body["view"]["private_metadata"])
    new_context = body["view"]["state"]["values"]["context_block"]["context_input"]["value"]
    channel, ts = meta["channel"], meta["message_ts"]

    client.chat_update(channel=channel, ts=ts, text="Regenerating...", blocks=[])
    email = draft_email(meta["company"], new_context, get_sender())
    client.chat_update(
        channel=channel, ts=ts, text=email,
        blocks=email_blocks(email, meta["company"], new_context),
    )


@bolt_app.action("save_to_gmail")
def handle_save_to_gmail(ack, body, client):
    """Parse the email from the posted message and save it to Gmail Drafts."""
    ack()
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


# Vercel picks this up as the WSGI app
app = flask_app
