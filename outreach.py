"""
Agent: Cold Outreach
--------------------
Orchestrates the cold email drafting workflow.
See workflows/cold_outreach.md for the full SOP.

Usage:
  py outreach.py                                      # interactive mode
  py outreach.py --company "Acme" --context "..."    # pass args directly
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from tools.draft_email import draft_email
from tools.save_to_gmail_drafts import save_draft

load_dotenv()


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def prompt_with_default(label: str, env_key: str) -> str:
    """Prompt the user, showing the .env default in brackets if one exists."""
    env_val = os.getenv(env_key, "")
    display = f"{label} [{env_val}]: " if env_val else f"{label}: "
    while True:
        val = input(display).strip()
        result = val or env_val
        if result:
            return result
        print("  (required — please enter a value)")


def gather_sender() -> dict:
    """Load sender details from .env, prompting for anything missing."""
    if any(not os.getenv(k) for k in ("SENDER_NAME", "SENDER_ROLE", "SENDER_COMPANY", "SENDER_PRODUCT")):
        print("\n--- Your Info (press Enter to use .env values) ---")
    return {
        "name":    prompt_with_default("Your name",    "SENDER_NAME"),
        "role":    prompt_with_default("Your role",    "SENDER_ROLE"),
        "from":    prompt_with_default("Your company", "SENDER_COMPANY"),
        "product": prompt_with_default("What you offer", "SENDER_PRODUCT"),
    }


def gather_inputs_interactive() -> tuple[str, str, dict]:
    print("\n--- Target Company ---")
    company = input("Company name: ").strip()
    while not company:
        print("  (required)")
        company = input("Company name: ").strip()

    context = input("Context (what you know about them, why you're reaching out): ").strip()
    while not context:
        print("  (required)")
        context = input("Context: ").strip()

    sender = gather_sender()
    return company, context, sender


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def display_email(email: str) -> None:
    divider = "─" * 60
    print(f"\n{divider}")
    print(email)
    print(divider)


def parse_email(email: str) -> tuple[str, str]:
    """Split a 'Subject: ...\n\n<body>' string into (subject, body)."""
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
# Main loop
# ---------------------------------------------------------------------------

def handle_save_to_drafts(email: str) -> None:
    """Parse the current draft and save it to Gmail Drafts."""
    subject, body = parse_email(email)
    to = input("Recipient email (leave blank to fill in Gmail later): ").strip()
    print("Saving to Gmail Drafts...", flush=True)
    try:
        url = save_draft(subject, body, to)
        print(f"Draft saved: {url}")
    except FileNotFoundError as e:
        print(f"Setup error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Error saving draft: {e}", file=sys.stderr)


def run(company: str, context: str, sender: dict) -> None:
    """Draft an email, then let the user regenerate, edit, or save until they quit."""
    print("\nDrafting email...", flush=True)
    email = draft_email(company, context, sender)
    display_email(email)

    while True:
        print("\n[r] Regenerate   [e] Edit context   [s] Save to Gmail Drafts   [q] Quit")
        choice = input("Choice: ").strip().lower()

        if choice == "r":
            print("\nRegenerating...", flush=True)
            email = draft_email(company, context, sender)
            display_email(email)

        elif choice == "e":
            print(f"\nCurrent context: {context}")
            new_context = input("New context (leave blank to keep): ").strip()
            if new_context:
                context = new_context
            print("\nRegenerating with updated context...", flush=True)
            email = draft_email(company, context, sender)
            display_email(email)

        elif choice == "s":
            handle_save_to_drafts(email)

        elif choice == "q":
            print("Done.")
            sys.exit(0)

        else:
            print("Invalid choice — use r, e, s, or q.")


def main() -> None:
    if not os.getenv("GROQ_API_KEY"):
        print("Error: GROQ_API_KEY not set.", file=sys.stderr)
        print("  Add your key to .env — get one at https://console.groq.com", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Draft B2B cold outreach emails.")
    parser.add_argument("--company", help="Target company name")
    parser.add_argument("--context", help="Context about the company / reason for outreach")
    args = parser.parse_args()

    if args.company and args.context:
        sender = gather_sender()
        run(args.company, args.context, sender)
    else:
        company, context, sender = gather_inputs_interactive()
        run(company, context, sender)


if __name__ == "__main__":
    main()
