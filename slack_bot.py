"""
Agent: Cold Outreach Slack Bot
-------------------------------
Slack interface for the cold outreach workflow.
See workflows/slack_bot_setup.md for setup instructions.

Usage:
  py slack_bot.py

In Slack:
  /outreach  →  opens a modal to enter company + context
               →  posts draft with Regenerate / Edit Context / Save to Gmail buttons
"""

import json
import os
import sys
import uuid

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from tools.draft_email import draft_email
from tools.save_to_gmail_drafts import save_draft

load_dotenv()

# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def check_env() -> None:
    missing = [k for k in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "GROQ_API_KEY") if not os.getenv(k)]
    if missing:
        for k in missing:
            print(f"Error: {k} not set in .env", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# In-memory state: keyed by a UUID stored in button values
# Stores company, context, sender, and the latest drafted email per session
# ---------------------------------------------------------------------------

_state: dict[str, dict] = {}

def get_sender() -> dict:
    return {
        "name":    os.getenv("SENDER_NAME", ""),
        "role":    os.getenv("SENDER_ROLE", ""),
        "from":    os.getenv("SENDER_COMPANY", ""),
        "product": os.getenv("SENDER_PRODUCT", ""),
    }

# ---------------------------------------------------------------------------
# Block Kit helpers
# ---------------------------------------------------------------------------

def email_blocks(email: str, state_id: str) -> list:
    """Build the Block Kit message for a drafted email with action buttons."""
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": email},
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
                    "value": state_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit Context"},
                    "action_id": "edit_context",
                    "value": state_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Save to Gmail Drafts"},
                    "action_id": "save_to_gmail",
                    "value": state_id,
                    "style": "primary",
                },
            ],
        },
    ]


def format_email_for_slack(email: str) -> str:
    """Bold the subject line for Slack's mrkdwn."""
    lines = email.splitlines()
    formatted = []
    for line in lines:
        if line.lower().startswith("subject:"):
            formatted.append(f"*{line}*")
        else:
            formatted.append(line)
    return "\n".join(formatted)


def parse_email(email: str) -> tuple[str, str]:
    """Split 'Subject: ...\n\n<body>' into (subject, body)."""
    lines = email.splitlines()
    subject = ""
    body_lines = []
    in_body = False
    for line in lines:
        if not in_body and line.lower().startswith("subject:"):
            subject = line[len("subject:"):].strip()
        elif not in_body and subject and line.strip() == "":
            in_body = True
        elif in_body:
            body_lines.append(line)
    return subject, "\n".join(body_lines).strip()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = App(token=os.getenv("SLACK_BOT_TOKEN", ""))


@app.command("/outreach")
def handle_outreach_command(ack, body, client):
    """Open the input modal when /outreach is invoked."""
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


@app.view("draft_email_modal")
def handle_modal_submit(ack, body, client):
    """Draft the email and post it to the channel on modal submit."""
    ack()
    values = body["view"]["state"]["values"]
    company = values["company_block"]["company_input"]["value"]
    context = values["context_block"]["context_input"]["value"]
    channel = body["view"]["private_metadata"]
    sender = get_sender()

    # Post a loading message
    result = client.chat_postMessage(channel=channel, text="Drafting email...")

    email = draft_email(company, context, sender)
    formatted = format_email_for_slack(email)

    state_id = str(uuid.uuid4())
    _state[state_id] = {
        "company": company,
        "context": context,
        "sender": sender,
        "email": email,
        "channel": channel,
    }

    client.chat_update(
        channel=channel,
        ts=result["ts"],
        text=email,
        blocks=email_blocks(formatted, state_id),
    )


@app.action("regenerate")
def handle_regenerate(ack, body, client):
    """Regenerate the email draft in place."""
    ack()
    state_id = body["actions"][0]["value"]
    state = _state.get(state_id)
    if not state:
        client.chat_postMessage(channel=body["channel"]["id"], text="Session expired — run /outreach again.")
        return

    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    client.chat_update(channel=channel, ts=message_ts, text="Regenerating...", blocks=[])

    email = draft_email(state["company"], state["context"], state["sender"])
    state["email"] = email
    formatted = format_email_for_slack(email)

    client.chat_update(
        channel=channel,
        ts=message_ts,
        text=email,
        blocks=email_blocks(formatted, state_id),
    )


@app.action("edit_context")
def handle_edit_context(ack, body, client):
    """Open a modal pre-filled with the current context."""
    ack()
    state_id = body["actions"][0]["value"]
    state = _state.get(state_id)
    if not state:
        client.chat_postMessage(channel=body["channel"]["id"], text="Session expired — run /outreach again.")
        return

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "edit_context_modal",
            "private_metadata": json.dumps({
                "state_id": state_id,
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


@app.view("edit_context_modal")
def handle_edit_context_submit(ack, body, client):
    """Update context and regenerate the draft."""
    ack()
    meta = json.loads(body["view"]["private_metadata"])
    state_id = meta["state_id"]
    channel = meta["channel"]
    message_ts = meta["message_ts"]
    state = _state.get(state_id)
    if not state:
        client.chat_postMessage(channel=channel, text="Session expired — run /outreach again.")
        return

    new_context = body["view"]["state"]["values"]["context_block"]["context_input"]["value"]
    state["context"] = new_context

    client.chat_update(channel=channel, ts=message_ts, text="Regenerating...", blocks=[])

    email = draft_email(state["company"], state["context"], state["sender"])
    state["email"] = email
    formatted = format_email_for_slack(email)

    client.chat_update(
        channel=channel,
        ts=message_ts,
        text=email,
        blocks=email_blocks(formatted, state_id),
    )


@app.action("save_to_gmail")
def handle_save_to_gmail(ack, body, client):
    """Save the current draft to Gmail Drafts."""
    ack()
    state_id = body["actions"][0]["value"]
    state = _state.get(state_id)
    if not state:
        client.chat_postMessage(channel=body["channel"]["id"], text="Session expired — run /outreach again.")
        return

    channel = body["channel"]["id"]
    subject, email_body = parse_email(state["email"])

    try:
        url = save_draft(subject, email_body)
        client.chat_postMessage(
            channel=channel,
            text=f"Draft saved to Gmail: {url}",
        )
    except FileNotFoundError:
        client.chat_postMessage(
            channel=channel,
            text="Gmail not set up. Follow the instructions in `workflows/cold_outreach.md`.",
        )
    except Exception as e:
        client.chat_postMessage(channel=channel, text=f"Error saving to Gmail: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    check_env()
    print("Cold Outreach bot is running. Press Ctrl+C to stop.")
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN", "")).start()
