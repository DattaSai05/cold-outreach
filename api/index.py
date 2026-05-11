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

def get_senders() -> list[dict]:
    """
    Get the configured sender definitions used for drafting outbound messages.
    
    Reads the SENDERS environment variable (JSON array of sender objects) and merges each entry with shared fields `from` and `product` sourced from SENDER_COMPANY and SENDER_PRODUCT. If SENDERS is unset or cannot be parsed as JSON, falls back to a single sender constructed from SENDER_NAME and SENDER_ROLE plus the shared fields.
    
    Returns:
        list[dict]: List of sender dictionaries with keys `name`, `role`, `from`, and `product`.
    """
    shared = {
        "from":    os.environ.get("SENDER_COMPANY", ""),
        "product": os.environ.get("SENDER_PRODUCT", ""),
    }
    raw = os.environ.get("SENDERS", "")
    if raw:
        try:
            return [{**shared, **s} for s in json.loads(raw)]
        except json.JSONDecodeError:
            pass
    return [{
        "name": os.environ.get("SENDER_NAME", ""),
        "role": os.environ.get("SENDER_ROLE", ""),
        **shared,
    }]


def _sender_options() -> list[dict]:
    """
    Builds Slack static-select option objects representing configured senders.
    
    Returns:
        list[dict]: A list of option dictionaries for a Slack static select, where each option's `text` shows the sender name and `value` is the sender's index in the configured senders list (as a string).
    """
    return [
        {"text": {"type": "plain_text", "text": s["name"]}, "value": str(i)}
        for i, s in enumerate(get_senders())
    ]


def parse_email(email: str) -> tuple[str, str]:
    """
    Parse an email string into its subject and body.
    
    The function finds the first line that begins with "Subject:" (case-insensitive) and extracts the text after that prefix as the subject. The body is the text that appears after the first blank line following that subject line. Trailing whitespace in the body is removed. If no subject line is found, the subject is an empty string; if no body is present, the body is an empty string.
    
    Returns:
        subject (str): The subject text without the "Subject:" prefix.
        body (str): The email body text after the first blank line following the subject.
    """
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


def _btn_value(company: str, context: str, sender_idx: int = 0) -> str:
    """
    Create a JSON-encoded payload used as a Slack button value containing company, context, and sender index.
    
    Parameters:
        company (str): Target company name.
        context (str): Context or prompt for the email.
        sender_idx (int): Index of the selected sender in the configured senders list.
    
    Returns:
        value (str): JSON string with keys "company", "context", and "sender_idx".
    """
    return json.dumps({"company": company, "context": context, "sender_idx": sender_idx})


def result_modal(email: str, company: str, context: str, sender_idx: int = 0) -> dict:
    """
    Builds a Slack modal that displays a drafted email and presents actions to regenerate, edit context, or send it.
    
    Parameters:
        email (str): The full drafted email text to display.
        company (str): Target company name used when drafting the email; stored in the modal metadata.
        context (str): Context used when drafting the email; stored in the modal metadata.
        sender_idx (int): Index of the selected sender (from get_senders()) to include in the modal metadata.
    
    Returns:
        dict: A Slack modal payload containing the displayed email, action buttons, and JSON-encoded private_metadata with `email`, `company`, `context`, and `sender_idx`.
    """
    val = _btn_value(company, context, sender_idx)
    meta = json.dumps({"email": email, "company": company, "context": context, "sender_idx": sender_idx})
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
                        "text": {"type": "plain_text", "text": "Send to Slack"},
                        "action_id": "send_to_slack",
                        "style": "primary",
                        "value": val,
                    },
                ],
            },
        ],
    }


def error_modal(message: str) -> dict:
    """
    Builds a Slack modal payload that displays an error message.
    
    Parameters:
        message (str): The error text to show in the modal.
    
    Returns:
        modal (dict): A Slack modal view payload containing a single section with the warning emoji and the provided message.
    """
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
    """
    Open and present the "Cold Outreach" modal for drafting an email.
    
    The modal contains a sender static select (preselected to the first configured sender), a single-line "Target Company" input, and a multiline "Context" input. On failure to open the modal, an error is printed to stdout.
    """
    ack()
    senders = get_senders()
    sender_block = {
        "type": "input",
        "block_id": "sender_block",
        "label": {"type": "plain_text", "text": "Sender"},
        "element": {
            "type": "static_select",
            "action_id": "sender_input",
            "placeholder": {"type": "plain_text", "text": "Select a sender"},
            "options": _sender_options(),
            "initial_option": _sender_options()[0],
        },
    }
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
                    sender_block,
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
    """
    Handle submission of the "Cold Outreach" modal: generate a draft email from the submitted form values and replace the modal with the drafted result or an error modal.
    
    Reads sender index, company, and context from the view state, generates an email using those values, and calls the acknowledgement callback to update the modal to show the draft. If generation fails, updates the modal to show the error message.
    
    Parameters:
        body (dict): The Slack view payload; expected to contain
            `view.state.values` with keys:
              - "sender_block" -> "sender_input" -> "selected_option" -> "value" (sender index)
              - "company_block" -> "company_input" -> "value" (company name)
              - "context_block" -> "context_input" -> "value" (context text)
    """
    from tools.draft_email import draft_email

    values = body["view"]["state"]["values"]
    sender_idx = int(values["sender_block"]["sender_input"]["selected_option"]["value"])
    company = values["company_block"]["company_input"]["value"]
    context = values["context_block"]["context_input"]["value"]
    sender = get_senders()[sender_idx]

    try:
        email = draft_email(company, context, sender)
        ack(response_action="update", view=result_modal(email, company, context, sender_idx))
    except Exception as e:
        ack(response_action="update", view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Handler 4: "Regenerate" button → re-draft, update modal in-place
# ---------------------------------------------------------------------------

@bolt_app.action("regenerate")
def handle_regenerate(ack, body, client):
    """
    Regenerate a drafted email from the action payload and update the originating modal with the new draft.
    
    Reads `sender_idx`, `company`, and `context` from the triggering action's `value`, invokes the email generator with the selected sender, and replaces the current modal view with the generated draft. If generation fails, replaces the view with an error modal showing the exception message.
    
    Parameters:
        body (dict): Slack action payload containing the triggering view and the action `value` JSON.
        client (WebClient): Slack client used to update the modal view.
    """
    ack()
    from tools.draft_email import draft_email

    val = json.loads(body["actions"][0]["value"])
    sender_idx = val.get("sender_idx", 0)
    sender = get_senders()[sender_idx]
    view_id = body["view"]["id"]
    try:
        email = draft_email(val["company"], val["context"], sender)
        client.views_update(
            view_id=view_id,
            view=result_modal(email, val["company"], val["context"], sender_idx),
        )
    except Exception as e:
        client.views_update(view_id=view_id, view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Handler 5: "Edit Context" button → push pre-filled context modal
# ---------------------------------------------------------------------------

@bolt_app.action("edit_context")
def handle_edit_context(ack, body, client):
    """
    Open and push an "Edit Context" modal pre-filled with the current context, storing the company and sender index in the modal's private metadata so the updated context can be used to regenerate the draft.
    
    Parameters:
        body (dict): Slack interaction payload containing `actions` (with the encoded value carrying `company`, `context`, and optional `sender_idx`) and `trigger_id` used to open the modal.
    
    Notes:
        - Acknowledges the interaction immediately via `ack()`.
        - On failure to push the view, an error message is printed.
    """
    ack()
    val = json.loads(body["actions"][0]["value"])
    # Carry both company and sender_idx through the edit flow
    meta = json.dumps({"company": val["company"], "sender_idx": val.get("sender_idx", 0)})
    try:
        client.views_push(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "edit_context_modal",
                "private_metadata": meta,
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
    """
    Update the current modal by regenerating the draft email using the edited context.
    
    Reads `company` and optional `sender_idx` from the view's `private_metadata` and the new `context` from the submitted view state, generates a new email draft, and updates the modal to display the regenerated draft. If generation fails, replaces the modal with an error view.
    
    Parameters:
        body (dict): The Slack view submission payload containing `view.private_metadata` (JSON with `company` and optional `sender_idx`) and `view.state.values.context_block.context_input.value` with the updated context.
    """
    from tools.draft_email import draft_email

    meta = json.loads(body["view"]["private_metadata"])
    company = meta["company"]
    sender_idx = meta.get("sender_idx", 0)
    context = body["view"]["state"]["values"]["context_block"]["context_input"]["value"]
    sender = get_senders()[sender_idx]

    try:
        email = draft_email(company, context, sender)
        ack(response_action="update", view=result_modal(email, company, context, sender_idx))
    except Exception as e:
        ack(response_action="update", view=error_modal(str(e)))


# ---------------------------------------------------------------------------
# Handler 7: "Send to Slack" button → post draft to channel, update modal
# ---------------------------------------------------------------------------

@bolt_app.action("send_to_slack")
def handle_send_to_slack(ack, body, client):
    ack()
    meta = json.loads(body["view"]["private_metadata"])
    subject, email_body = parse_email(meta["email"])
    channel = os.environ.get("SLACK_CHANNEL", "#cold-outreach-testing")
    view_id = body["view"]["id"]
    try:
        client.chat_postMessage(
            channel=channel,
            text=f"*Subject: {subject}*\n\n{email_body}",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Subject: {subject}*\n\n{email_body}"},
                }
            ],
        )
        client.views_update(
            view_id=view_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Sent!"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f":white_check_mark: Draft posted to {channel}."},
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
