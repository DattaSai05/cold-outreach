"""
Tool: draft_email
-----------------
Calls the Groq API to draft a single B2B cold outreach email.
"""

import argparse
import os
import sys

from openai import OpenAI, APIError
from dotenv import load_dotenv

load_dotenv()

MODEL = "llama-3.3-70b-versatile"
BASE_URL = "https://api.groq.com/openai/v1"

SYSTEM_PROMPT = """\
You are an expert B2B sales copywriter specializing in cold outreach emails.
Your emails are concise, human, and highly personalized — never generic.

Rules:
- Subject line: compelling and specific, under 50 characters, no clickbait
- Opening line: reference something concrete about the prospect from the context provided
- Body: 2–3 short paragraphs max. Lead with their pain point or opportunity, then your value prop
- CTA: one clear, low-friction ask (15-min call, a reply, a quick demo)
- Tone: conversational and confident, not salesy or pushy
- Forbidden phrases: "I hope this email finds you well", "reaching out to", "touch base",
  "synergies", "circle back", "per my last email", "as per", "I wanted to"
- Total length: 100–150 words (excluding subject line)

Output format — always use exactly this structure, nothing else:
Subject: <subject line>

<email body>
"""


def build_prompt(company: str, context: str, sender: dict) -> str:
    return (
        f"Draft a cold outreach email with the following details:\n\n"
        f"TARGET COMPANY: {company}\n"
        f"CONTEXT ABOUT THEM: {context}\n\n"
        f"SENDER NAME: {sender['name']}\n"
        f"SENDER ROLE: {sender['role']}\n"
        f"SENDER COMPANY: {sender['from']}\n"
        f"WHAT WE OFFER: {sender['product']}\n"
    )


def draft_email(company: str, context: str, sender: dict, api_key: str | None = None) -> str:
    """
    Generate a single personalized B2B cold outreach email by calling the Groq-hosted OpenAI-compatible chat completions API.
    
    Parameters:
        company (str): Target company name to address in the email.
        context (str): Brief contextual details about the recipient or use case to personalize the email.
        sender (dict): Sender information with keys "name", "role", "from", and "product".
        api_key (str | None): Optional API key to use instead of the GROQ_API_KEY environment variable.
    
    Returns:
        str: The model-generated email text (exactly formatted subject line, a blank line, then the email body), trimmed of surrounding whitespace.
    
    Raises:
        ValueError: If no API key is provided and the GROQ_API_KEY environment variable is not set.
    """
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY is not set")

    client = OpenAI(api_key=key, base_url=BASE_URL)
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_prompt(company, context, sender)},
        ],
    )
    return response.choices[0].message.content.strip()


def main() -> None:
    """
    Run the command-line tool: parse required arguments, build the sender payload, call draft_email, and print the generated email.
    
    Parses required CLI options --company, --context, --name, --role, --from (mapped to `from_company`), and --product; constructs a `sender` dict and prints the email produced by `draft_email`. Exits with status 1 if a ValueError occurs (prints "Error: <msg>" to stderr) and with status 2 if an APIError occurs (prints "API error: <msg>" to stderr).
    """
    parser = argparse.ArgumentParser(description="Draft a B2B cold outreach email via Groq.")
    parser.add_argument("--company",  required=True)
    parser.add_argument("--context",  required=True)
    parser.add_argument("--name",     required=True)
    parser.add_argument("--role",     required=True)
    parser.add_argument("--from",     required=True, dest="from_company")
    parser.add_argument("--product",  required=True)
    args = parser.parse_args()

    sender = {
        "name":    args.name,
        "role":    args.role,
        "from":    args.from_company,
        "product": args.product,
    }

    try:
        email = draft_email(args.company, args.context, sender)
        print(email)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
