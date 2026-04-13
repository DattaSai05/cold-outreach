# Workflow: Slack Bot Setup & Deployment

## Objective
Deploy the cold outreach Slack bot to Vercel so `/outreach` works 24/7 in Slack — no terminal, no persistent process. Vercel wakes the bot only when you use it.

---

## Part 1 — Slack App Setup (one-time)

### Step 1 — Create the Slack App
1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g. "Cold Outreach") and pick your workspace → **Create App**

### Step 2 — Disable Socket Mode
1. Left sidebar → **Socket Mode**
2. Make sure it is toggled **OFF** (we use HTTP now, not a persistent connection)

### Step 3 — Get your Signing Secret
1. Left sidebar → **Basic Information** → scroll to **App Credentials**
2. Copy **Signing Secret** → paste into `.env` as `SLACK_SIGNING_SECRET`

### Step 4 — Add Bot Scopes
1. Left sidebar → **OAuth & Permissions** → scroll to **Bot Token Scopes**
2. Add: `chat:write`, `commands`
3. Scroll up → **Install to Workspace** → **Allow**
4. Copy the **Bot User OAuth Token** (`xoxb-...`) → already in `.env` as `SLACK_BOT_TOKEN`

### Step 5 — Create the Slash Command
1. Left sidebar → **Slash Commands** → **Create New Command**
2. Fill in:
   - Command: `/outreach`
   - Request URL: `https://<your-app>.vercel.app/slack/events` *(fill in after Vercel deployment)*
   - Short description: `Draft a cold outreach email`
3. **Save**

### Step 6 — Enable Interactivity
1. Left sidebar → **Interactivity & Shortcuts** → toggle **ON**
2. Request URL: `https://<your-app>.vercel.app/slack/events` *(same URL as above)*
3. **Save Changes**

### Step 7 — Reinstall the App
Left sidebar → **Install App** → **Reinstall to Workspace** → **Allow**

---

## Part 2 — Deploy to Vercel

### Step 1 — Sign up for Vercel
1. Go to [vercel.com](https://vercel.com) → **Sign Up** with GitHub

### Step 2 — Import the GitHub repo
1. In Vercel dashboard → **Add New Project** → **Import Git Repository**
2. Select your `cold-outreach` repo → **Import**
3. Leave all settings as default — Vercel detects `vercel.json` automatically
4. Click **Deploy**

### Step 3 — Add environment variables
In Vercel → your project → **Settings** → **Environment Variables** → add each:

| Variable | Value |
|---|---|
| `SLACK_BOT_TOKEN` | Your `xoxb-...` token |
| `SLACK_SIGNING_SECRET` | From Basic Information → App Credentials |
| `GROQ_API_KEY` | Your `gsk_...` key |
| `SENDER_NAME` | Your name |
| `SENDER_ROLE` | Your role |
| `SENDER_COMPANY` | Your company |
| `SENDER_PRODUCT` | What you offer |
| `GMAIL_TOKEN_JSON` | Full contents of your local `token.json` |

After adding variables → **Redeploy** (Deployments tab → the latest deploy → three-dot menu → Redeploy).

### Step 4 — Copy the Vercel URL back to Slack
1. In Vercel, copy your deployment URL (e.g. `https://cold-outreach-abc123.vercel.app`)
2. Go back to your Slack app settings:
   - **Slash Commands** → edit `/outreach` → update Request URL to `https://cold-outreach-abc123.vercel.app/slack/events`
   - **Interactivity & Shortcuts** → update Request URL to the same URL
3. Save both

---

## Usage

In any Slack channel:
1. Type `/outreach` → a modal opens
2. Fill in **Target Company** and **Context** → **Draft Email**
3. The bot posts the draft with three buttons:
   - **Regenerate** — fresh draft
   - **Edit Context** — refine context and regenerate in place
   - **Save to Gmail Drafts** — saves directly to Gmail and posts the link

---

## Future deploys
Every `git push` to your repo automatically redeploys to Vercel. No manual steps needed.

---

## Edge Cases

| Situation | How to handle |
|---|---|
| `/outreach` gives "dispatch_failed" | Request URL not set in Slack app, or Vercel deploy failed — check Vercel logs |
| Buttons do nothing | Interactivity URL not set in Slack app settings |
| Gmail save fails | Check that `GMAIL_TOKEN_JSON` env var is set in Vercel and contains valid JSON |
| `GMAIL_TOKEN_JSON` expired | Re-run Gmail auth locally (`py outreach.py` → `s`), copy new `token.json` contents to Vercel env vars, redeploy |
| Need to update sender details | Change env vars in Vercel Settings → redeploy |
