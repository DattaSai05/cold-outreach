# Workflow: Slack Bot Setup & Deployment

## Objective
Run the cold outreach Slack bot 24/7 on Railway so `/outreach` works from Slack at any time, without opening a terminal.

---

## Part 1 — Slack App Setup (one-time)

### Step 1 — Create the Slack App
1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g. "Cold Outreach") and pick your workspace → **Create App**

### Step 2 — Enable Socket Mode
1. Left sidebar → **Socket Mode** → toggle **Enable Socket Mode** on
2. Create an App-Level Token: name it anything, add scope `connections:write` → **Generate**
3. Copy the token (starts with `xapp-`) → save as `SLACK_APP_TOKEN`

### Step 3 — Add Bot Scopes
1. Left sidebar → **OAuth & Permissions** → scroll to **Bot Token Scopes**
2. Add: `chat:write`, `commands`
3. Scroll up → **Install to Workspace** → **Allow**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`) → save as `SLACK_BOT_TOKEN`

### Step 4 — Create the Slash Command
1. Left sidebar → **Slash Commands** → **Create New Command**
2. Command: `/outreach`, Request URL: `https://placeholder.com`, any description
3. **Save**

### Step 5 — Enable Interactivity
1. Left sidebar → **Interactivity & Shortcuts** → toggle on
2. Request URL: `https://placeholder.com`
3. **Save Changes**

### Step 6 — Reinstall the App
Left sidebar → **Install App** → **Reinstall to Workspace** → **Allow**

---

## Part 2 — Deploy to Railway (24/7 hosting)

### Step 1 — Create a GitHub repo
Railway deploys from Git. Push the project to a new GitHub repo:
```bash
git init
git add .
git commit -m "Initial commit"
# Create a new repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/cold-outreach.git
git push -u origin main
```

Note: make sure `.env`, `credentials.json`, and `token.json` are in `.gitignore` — secrets go in Railway env vars, not the repo.

### Step 2 — Create a .gitignore
Create a `.gitignore` in the project root with at minimum:
```
.env
credentials.json
token.json
__pycache__/
.tmp/
```

### Step 3 — Sign up and create a Railway project
1. Go to [railway.app](https://railway.app) → sign up with GitHub
2. **New Project** → **Deploy from GitHub repo** → select your repo
3. Railway will detect `requirements.txt` and `Procfile` automatically

### Step 4 — Add environment variables
In Railway, go to your service → **Variables** tab → add each of these:

| Variable | Value |
|---|---|
| `SLACK_BOT_TOKEN` | Your `xoxb-...` token |
| `SLACK_APP_TOKEN` | Your `xapp-...` token |
| `GROQ_API_KEY` | Your `gsk_...` key |
| `SENDER_NAME` | Your name |
| `SENDER_ROLE` | Your role |
| `SENDER_COMPANY` | Your company |
| `SENDER_PRODUCT` | What you offer |
| `GMAIL_TOKEN_JSON` | Contents of your local `token.json` (see below) |

### Step 5 — Get the GMAIL_TOKEN_JSON value
`token.json` was created on your PC when you first authenticated Gmail. Get its contents:
1. Open `token.json` from the project root in a text editor
2. Copy the entire contents (it's a JSON object)
3. Paste it as the value for `GMAIL_TOKEN_JSON` in Railway

### Step 6 — Set the service type to Worker
Railway may try to run this as a web service and fail because there's no HTTP port.
1. In your service settings → **Settings** tab
2. Under **Deploy** → make sure it's using the `Procfile` (which defines a `worker`)
3. If Railway shows a "No start command" warning, manually set the start command to:
   ```
   python slack_bot.py
   ```

### Step 7 — Deploy
Railway deploys automatically on every push to `main`. Check the **Logs** tab to confirm:
```
Cold Outreach bot is running.
```

---

## Usage (once deployed)

In any Slack channel:
1. Type `/outreach` → a modal opens
2. Fill in **Target Company** and **Context** → click **Draft Email**
3. The bot posts the draft with three buttons:
   - **Regenerate** — fresh draft
   - **Edit Context** — refine context and regenerate
   - **Save to Gmail Drafts** — saves to Gmail and posts the link

---

## Edge Cases

| Situation | How to handle |
|---|---|
| Bot doesn't respond to `/outreach` | Check Railway logs for errors; verify all env vars are set |
| "Session expired" in Slack | State is in-memory — redeploying clears sessions. Run `/outreach` again |
| Gmail save fails on Railway | Check that `GMAIL_TOKEN_JSON` is set and contains valid JSON |
| `GMAIL_TOKEN_JSON` expired | Re-run the Gmail auth locally (`py outreach.py` → hit `s`), copy the new `token.json` contents to Railway |
| Bot crashes on Railway | Check Logs tab; Railway auto-restarts crashed workers |
