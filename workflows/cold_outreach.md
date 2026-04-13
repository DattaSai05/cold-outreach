# Workflow: Cold Outreach Email Drafting

## Objective
Draft a personalized B2B cold outreach email for a target company, given context about them and the sender's details. Optionally save the draft directly to Gmail Drafts for convenient sending.

## Required Inputs
| Input | Source | Notes |
|---|---|---|
| `company` | User prompt / CLI arg | Name of the target company |
| `context` | User prompt / CLI arg | Recent news, signals, pain points, reason for outreach |
| `sender.name` | `.env` → `SENDER_NAME` | Full name of the person sending |
| `sender.role` | `.env` → `SENDER_ROLE` | Job title (e.g. "Head of Sales") |
| `sender.from` | `.env` → `SENDER_COMPANY` | Sender's company name |
| `sender.product` | `.env` → `SENDER_PRODUCT` | One-line description of what's being offered |

## Tools
| Tool | Purpose |
|---|---|
| `tools/draft_email.py` | Calls Groq API to generate the email (subject + body) |
| `tools/save_to_gmail_drafts.py` | Authenticates with Gmail and saves the email as a draft |

## Expected Output
A Gmail draft containing:
- Subject line (under 50 characters)
- An opening referencing something specific from the context
- A 100–150 word body with value prop and a single CTA
- To field pre-filled if a recipient email was provided

## Steps
1. Collect `company` and `context` from the user (via CLI args or interactive prompt)
2. Load sender details from `.env`; prompt for any that are missing
3. Call `tools/draft_email.py` with all inputs
4. Display the draft to the user
5. Offer options: regenerate, edit context, save to Gmail Drafts, or quit
6. If saving: optionally prompt for recipient email, then call `tools/save_to_gmail_drafts.py`
7. Print the Gmail draft URL on success

## Gmail Setup (one-time)
Gmail access requires a credentials.json from Google Cloud Console. Steps:

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Enable the **Gmail API**: APIs & Services → Enable APIs → search "Gmail API"
4. Create OAuth credentials: APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Desktop app**
   - Download the JSON and save it as `credentials.json` in the project root
5. Add your Gmail address as a test user: APIs & Services → OAuth consent screen → Test users
6. Run `py outreach.py` and hit `[s]` — a browser window opens for one-time consent
7. `token.json` is saved automatically; no login needed on future runs

Note: The OAuth scope is `gmail.compose` only — this does **not** grant read access to your inbox.

## Edge Cases
| Situation | How to handle |
|---|---|
| `GROQ_API_KEY` not set | Exit with clear error pointing to console.groq.com |
| Sender fields missing from `.env` | Prompt interactively; do not skip or use placeholder values |
| Context is vague | Still proceed — richer context produces better output |
| API error (rate limit, timeout) | Surface the error message; do not retry automatically |
| `credentials.json` not found | Print setup instructions pointing to this workflow |
| `token.json` expired | Google auth library refreshes it automatically |
| Recipient left blank | Save draft with empty To field; fill it in Gmail before sending |

## Notes
- Email drafting rules (word count, forbidden phrases, tone) live in the system prompt inside `tools/draft_email.py`.
- Sender details persist in `.env` so they don't need re-entering each run.
- For bulk outreach, create `tools/draft_email_batch.py` rather than modifying the existing tool.
