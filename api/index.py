"""
Slack Bot: Cold Outreach
------------------------
Handles /coldreach slash command, modal, and button actions.
Deployed as a serverless function on Vercel.

Setup: see workflows/slack_bot_setup.md
"""

# --- Global SSL patch — must run before any other imports touch SSL ---
import ssl
import certifi
_ssl_ctx = ssl.create_default_context(cafile=certifi.where())
ssl.create_default_context = lambda *args, **kwargs: _ssl_ctx
ssl._create_default_https_context = lambda *args, **kwargs: _ssl_ctx

import json
import os

from dotenv import load_dotenv
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient

load_dotenv()

# --- Slack app setup ---
_web_client = WebClient(
    token=os.environ["SLACK_BOT_TOKEN"],
    ssl=_ssl_ctx,
)
bolt_app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    client=_web_client,
    process_before_response=True,
)
flask_app = Flask(__name__)
handler = SlackRequestHandler(bolt_app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_sender() -> dict:
    return {
        "name":    os.environ.get("SENDER_NAME", ""),
        "role":    os.environ.get("SENDER_ROLE", ""),
        "from":    os.environ.get("SENDER_COMPANY", ""),
        "product": os.environ.get("SENDER_PRODUCT", ""),
    }


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


def _btn_value(company: str, context: str) -> str:
    """Button value payload — stores company + context (stays under Slack's 2000-char limit)."""
    return json.dumps({"company": company, "context": context})


def result_modal(email: str, company: str, context: str) -> dict:
    """Modal view showing the drafted email with action buttons."""
    val = _btn_value(company, context)
    meta = json.dumps({"email": email, "company": company, "context": context})
    return {
        "type": "modal",
        "callback_id": "result_modal",
        "private_metadata": meta,
        "title": {"type": "plain_text", "text": "Cold Outreach"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{email}```"},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Regenerate"},
                        "action_id": "regenerate",
                        "value": val,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit Context"},
                        "action_id": "edit_context",
                        "value": val,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Save to Gmail"},
                        "action_id": "save_to_gmail",
                        "style": "primary",
                        "value": val,
                    },
                ],
            },
        ],
    }


def error_modal(message: str) -> dict:
    """Modal view for displaying an error."""
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Error"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: {message}"},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Handler 1: /coldreach slash command → ephemeral button
# ---------------------------------------------------------------------------

@bolt_app.command("/coldreach")
def handle_coldreach(ack, body):
    ack(
        response_type="ephemeral",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Ready to draft a cold outreach email."},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open Form"},
                        "action_id": "open_draft_modal",
                        "value": body["channel_id"],
                        "style": "primary",
                    }
                ],
            },
        ],
        text="Ready to draft a cold outreach email.",
    )


# ---------------------------------------------------------------------------
# Handler 2: "Open Form" button → open input modal
# ---------------------------------------------------------------------------

@bolt_app.action("open_draft_modal")
def handle_open_modal(ack, body, client):
    ack()
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "draft_email_modal",
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
    except Exception as e:
        print(f"[open_draft_modal] views.open failed: {e}")


# ---------------------------------------------------------------------------
# Handler 3: Modal submit → call Groq → update modal with result
# ---------------------------------------------------------------------------

@bolt_app.view("draft_email_modal")
def handle_modal_submit(ack, body):
    from tools.draft_email import draft_email

    values = body["view"]["state"]["values"]
    company = values["company_block"]["company_input"]["value"]
    context = values["context_block"]["context_input"]["value"]

    try:
        email = draft_email(company, context, get_sender())
        ack(response_action="update", view=result_modal(email, company, context))
    except Exception as e:
        ack(response_action="update", view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Handler 4: "Regenerate" button → re-draft, update modal in-place
# ---------------------------------------------------------------------------

@bolt_app.action("regenerate")
def handle_regenerate(ack, body, client):
    ack()
    from tools.draft_email import draft_email

    val = json.loads(body["actions"][0]["value"])
    view_id = body["view"]["id"]
    try:
        email = draft_email(val["company"], val["context"], get_sender())
        client.views_update(view_id=view_id, view=result_modal(email, val["company"], val["context"]))
    except Exception as e:
        client.views_update(view_id=view_id, view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Handler 5: "Edit Context" button → push pre-filled context modal
# ---------------------------------------------------------------------------

@bolt_app.action("edit_context")
def handle_edit_context(ack, body, client):
    ack()
    val = json.loads(body["actions"][0]["value"])
    try:
        client.views_push(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "edit_context_modal",
                "private_metadata": val["company"],
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
                            "initial_value": val["context"],
                        },
                    }
                ],
            },
        )
    except Exception as e:
        print(f"[edit_context] views.push failed: {e}")


# ---------------------------------------------------------------------------
# Handler 6: Edit Context modal submit → re-draft, update result modal
# ---------------------------------------------------------------------------

@bolt_app.view("edit_context_modal")
def handle_edit_context_submit(ack, body):
    from tools.draft_email import draft_email

    company = body["view"]["private_metadata"]
    context = body["view"]["state"]["values"]["context_block"]["context_input"]["value"]

    try:
        email = draft_email(company, context, get_sender())
        ack(response_action="update", view=result_modal(email, company, context))
    except Exception as e:
        ack(response_action="update", view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Handler 7: "Save to Gmail" button → create Gmail draft, update modal
# ---------------------------------------------------------------------------

@bolt_app.action("save_to_gmail")
def handle_save_to_gmail(ack, body, client):
    ack()
    from tools.save_to_gmail_drafts import save_draft

    meta = json.loads(body["view"]["private_metadata"])
    subject, email_body = parse_email(meta["email"])
    view_id = body["view"]["id"]
    try:
        url = save_draft(subject, email_body)
        client.views_update(
            view_id=view_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Saved!"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f":white_check_mark: Draft saved to Gmail.\n<{url}|Open in Gmail>"},
                    }
                ],
            },
        )
    except Exception as e:
        client.views_update(view_id=view_id, view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Flask route — Vercel entry point
# ---------------------------------------------------------------------------

@flask_app.route("/api/index", methods=["POST"])
def slack_events():
    return handler.handle(request)


app = flask_app  # Vercel looks for `app`
