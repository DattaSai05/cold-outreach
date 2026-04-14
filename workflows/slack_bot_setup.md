# Workflow: Slack Bot Setup

## Overview
The Slack bot exposes a `/coldreach` slash command that opens a modal form for filling in target company + context. After submission, an ephemeral email draft appears (only visible to you) with buttons to Regenerate, Edit Context, or Save to Gmail.

Hosted on Vercel as a serverless function. Redeploys automatically on every `git push`.

---

## Part 1 — Slack App Setup

**1. Create the app**
- Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
- Name it (e.g. "Cold Outreach") and select your workspace

**2. Disable Socket Mode**
- In the sidebar: **Socket Mode** → toggle **off**

**3. Copy the Signing Secret**
- **Basic Information** → **App Credentials** → copy **Signing Secret**
- Paste into `.env` as `SLACK_SIGNING_SECRET`

**4. Add bot scopes**
- **OAuth & Permissions** → **Bot Token Scopes** → add:
  - `chat:write`
  - `commands`

**5. Install the app to your workspace**
- **OAuth & Permissions** → **Install to Workspace** → **Allow**
- Copy the **Bot User OAuth Token** (`xoxb-...`) → paste into `.env` as `SLACK_BOT_TOKEN`

**6. Create the slash command**
- **Slash Commands** → **Create New Command**
  - Command: `/coldreach`
  - Request URL: `https://<your-app>.vercel.app/slack/events` *(fill in after Vercel deploy)*
  - Short Description: `Draft a cold outreach email`
  - Save

**7. Enable Interactivity**
- **Interactivity & Shortcuts** → toggle **on**
- Request URL: `https://<your-app>.vercel.app/slack/events` *(same URL)*
- Save

**8. Reinstall the app**
- After adding scopes/commands: **OAuth & Permissions** → **Reinstall to Workspace**

---

## Part 2 — Vercel Deployment

**1. Push to GitHub**
- Make sure your repo is on GitHub (Vercel connects to it)

**2. Import to Vercel**
- Go to [vercel.com](https://vercel.com) → **Add New Project** → import your GitHub repo
- Framework preset: **Other** (Vercel auto-detects `vercel.json`)
- Click **Deploy**

**3. Set environment variables**
- In Vercel dashboard: **Project → Settings → Environment Variables**
- Add all variables from your `.env`:
  - `SLACK_BOT_TOKEN`
  - `SLACK_SIGNING_SECRET`
  - `GROQ_API_KEY`
  - `SENDER_NAME`, `SENDER_ROLE`, `SENDER_COMPANY`, `SENDER_PRODUCT`
  - `GMAIL_TOKEN_JSON` (paste the full contents of your local `token.json`)

**4. Copy the Vercel URL back to Slack**
- From the Vercel dashboard, copy your deployment URL (e.g. `https://cold-outreach-abc.vercel.app`)
- Paste it (with `/slack/events`) into both:
  - Slash Commands → Request URL
  - Interactivity → Request URL
- Reinstall the app one more time

---

## Usage

1. In any Slack channel, type `/coldreach`
2. An ephemeral "Open Form" button appears (only you can see it)
3. Click **Open Form** → a modal opens with two fields:
   - **Target Company** — name of the company you're emailing
   - **Context** — what you know about them, why you're reaching out
4. Click **Draft Email** — the modal closes and a draft appears (ephemeral)
5. Use the action buttons:
   - **Regenerate** — get a fresh version of the email with the same inputs
   - **Edit Context** — opens a pre-filled modal to update the context, then regenerates
   - **Save to Gmail** — creates a Gmail draft and returns the link

---

## Edge Cases

| Situation | Fix |
|-----------|-----|
| `dispatch_failed` on slash command | Vercel URL not set in Slack app → update Request URLs |
| Buttons don't respond | Interactivity not enabled or wrong URL → check Interactivity settings |
| Modal doesn't open | Trigger ID expired (>3s) — this flow uses button click to get a fresh trigger ID, so this shouldn't happen |
| Gmail auth fails | `GMAIL_TOKEN_JSON` not set in Vercel env vars → paste full `token.json` contents |
| Token expired | Re-run `py outreach.py` locally, hit `[s]`, complete OAuth → copy new `token.json` to Vercel |
