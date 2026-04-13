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
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Only lightweight imports at module level — keeps cold start fast so
# ack() + views.open() complete within Slack's 3-second trigger_id window.
import certifi
from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient

load_dotenv()

# Use certifi's CA bundle to fix SSL issues on Vercel's Python runtime
ssl_context = ssl.create_default_context(cafile=certifi.where())
slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"), ssl=ssl_context)

bolt_app = App(
    client=slack_client,
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
def handle_coldreach(ack, body, client):
    """Open the input modal — ack + views.open run before any heavy imports."""
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
    """Draft the email on modal submit. Heavy imports happen here, not at startup."""
    ack()
    # Deferred import — only loaded when actually needed
    from tools.draft_email import draft_email

    values = body["view"]["state"]["values"]
    company = values["company_block"]["company_input"]["value"]
    context = values["context_block"]["context_input"]["value"]
    channel = body["view"]["private_metadata"]

    result = client.chat_postMessage(channel=channel, text="Drafting email...")
    try:
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
    """Open edit modal — ack + views.open before any heavy imports."""
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
    ack()
    from tools.draft_email import draft_email

    meta = json.loads(body["view"]["private_metadata"])
    new_context = body["view"]["state"]["values"]["context_block"]["context_input"]["value"]
    channel, ts = meta["channel"], meta["message_ts"]

    client.chat_update(channel=channel, ts=ts, text="Regenerating...", blocks=[])
    try:
        email = draft_email(meta["company"], new_context, get_sender())
        client.chat_update(
            channel=channel, ts=ts, text=email,
            blocks=email_blocks(email, meta["company"], new_context),
        )
    except Exception as e:
        client.chat_update(channel=channel, ts=ts, text=f"Error regenerating: {e}", blocks=[])


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
