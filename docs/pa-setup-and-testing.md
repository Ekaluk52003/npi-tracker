# NPI Tracker — Power Automate Setup & Testing Guide

## Overview

```
Outlook Email
    ↓  (Power Automate)
OneDrive: NPI-Queue/inbound/*.json
    ↓  (Django: poll_onedrive)
AI Agent (OpenAI GPT-4o)
    ↓  (function calling)
NPI Tracker Database  →  Issues / Tasks / Stage updates
```

### How it works — full call chain

```
python scripts/run_pipeline.py          ← plain Python script (recommended)
  OR
python manage.py poll_onedrive          ← Django management command (same result)
        │
        ▼
poll_onedrive.py / run_pipeline.py  ← entry point, handles CLI flags (--loop, --dry-run, --file)
        │
        ▼
email_queue.py            ← pipeline orchestrator — controls the full flow
  │
  ├─ 1. onedrive.py: list_folder("NPI-Queue/inbound")
  │         asks OneDrive: what .json files are waiting?
  │
  ├─ FOR EACH file:
  │
  │   ├─ 2. onedrive.py: read_file_content(filename)
  │   │         downloads the JSON written by Power Automate
  │   │         { "subject": "...", "body": "...", "project_name": "Voltaren" }
  │   │
  │   ├─ 3. _resolve_project_from_email()
  │   │         finds the matching Project in the database
  │   │         tries: project_id → project_name → subject/body scan
  │   │
  │   ├─ 4. _clean_email()
  │   │         strips any HTML tags from the body so the AI reads clean text
  │   │
  │   ├─ 5. ai_agent.py: process_email(email, project)   ← KEY STEP
  │   │   │
  │   │   ├─ get_project_context(project)
  │   │   │       builds a text summary of current stages, open tasks, open issues
  │   │   │
  │   │   ├─ build_user_message(email, context)
  │   │   │       combines email + project context into the prompt
  │   │   │
  │   │   ├─ openai_chat(messages, tools)
  │   │   │       HTTP POST → api.openai.com
  │   │   │       sends: system prompt + email + 6 tool definitions
  │   │   │       returns: { tool_call: "create_issue", args: { title: "...", severity: "high" } }
  │   │   │
  │   │   └─ inbound.py: _HANDLERS[tool_name](project, args)
  │   │           executes the AI decision against the Django database:
  │   │           create_issue       → Issue.objects.create(...)
  │   │           update_issue       → issue.save(...)
  │   │           create_task        → Task.objects.create(...)
  │   │           update_task_status → task.status = new; task.save(...)
  │   │           update_stage_status→ stage.status = new; stage.save(...)
  │   │
  │   ├─ 6. onedrive.py: write_file("NPI-Queue/outbound", result)
  │   │         saves the action result so Power Automate can read it back
  │   │
  │   └─ 7. onedrive.py: move_file(file, "NPI-Queue/processed")
  │             archives the file so it is not processed again
  │
  └─ returns summary of all processed files
```

### The 4 OneDrive operations

| Operation | Folder | When |
|---|---|---|
| `list_folder` | `inbound/` | Start of each poll — get waiting files |
| `read_file_content` | `inbound/` | Per file — download JSON written by PA |
| `write_file` | `outbound/` | After AI runs — save action result |
| `move_file` | `processed/` | After success — archive so it won't run again |

---

## Part 1 — One-Time Backend Setup

### 1.1 Install dependencies
```bash
pip install -r requirements.txt
```

### 1.2 Configure `.env`
Ensure these variables are set in your `.env` file:
```env
ONEDRIVE_CLIENT_ID=<your Azure app client ID>
ONEDRIVE_TENANT_ID=<your Azure AD tenant ID>
ONEDRIVE_CLIENT_SECRET=<your Azure app client secret>
ONEDRIVE_REFRESH_TOKEN=<your OAuth refresh token>

OPENAI_API_KEY=<your OpenAI API key>
OPENAI_MODEL=gpt-4o
AI_AGENT_ENABLED=True
```

### 1.3 Verify OneDrive + create folders (run once)
```bash
python scripts/test_onedrive.py
```
This checks your token, creates all `NPI-Queue/` subfolders automatically, and confirms read/write access.

### 1.4 Seed sample data (optional)
```bash
python manage.py seed_data
```
Creates 3 sample projects: **Greenland**, **Voltaren**, **Sentinel**.

---

## Part 2 — Power Automate Flow Setup

### 2.1 Create a new flow

1. Go to [make.powerautomate.com](https://make.powerautomate.com)
2. Click **Create** → **Automated cloud flow**
3. Name it: `NPI Email to OneDrive`
4. Trigger: search **"When a new email arrives (V3)"** → Office 365 Outlook
5. Click **Create**

---

### 2.2 Configure the trigger

| Setting | Value |
|---|---|
| **Folder** | `Inbox` |
| **Include Attachments** | No |
| **Subject Filter** | `NPI` *(optional)* |
| **Only with Attachments** | No |

---

### 2.3 Action 1 — Initialize variable (filename)

Click **+ New step** → search **Initialize variable**

| Field | Value |
|---|---|
| **Name** | `filename` |
| **Type** | String |
| **Value** | `email_@{formatDateTime(utcNow(),'yyyyMMdd_HHmmss')}_@{rand(1000,9999)}.json` |

---

### 2.4 Action 2 — Compose (build email JSON)

Click **+ New step** → search **Compose** → select **Data Operation: Compose**

Click inside the **Inputs** field (text mode, NOT the `fx` bar) and paste:

```
{
  "type": "email",
  "subject": "@{replace(triggerBody()?['subject'],'"',' ')}",
  "from": "@{triggerBody()?['from']}",
  "to": "@{triggerBody()?['toRecipients']}",
  "body": "@{replace(replace(triggerBody()?['bodyPreview'],'"',' '),decodeUriComponent('%0A'),' ')}",
  "received_at": "@{triggerBody()?['receivedDateTime']}",
  "message_id": "@{triggerBody()?['id']}",
  "project_name": "@{if(contains(toLower(triggerBody()?['subject']),'greenland'),'Greenland',if(contains(toLower(triggerBody()?['subject']),'voltaren'),'Voltaren',if(contains(toLower(triggerBody()?['subject']),'sentinel'),'Sentinel',if(contains(toLower(triggerBody()?['bodyPreview']),'greenland'),'Greenland',if(contains(toLower(triggerBody()?['bodyPreview']),'voltaren'),'Voltaren',if(contains(toLower(triggerBody()?['bodyPreview']),'sentinel'),'Sentinel','Unknown'))))))}"
}
```

> **After pasting:** Each `@{...}` block should turn into a **colored chip**.
> You should see **7 colored chips** total. A red chip means an expression error.

> **To add your own projects:** extend the `if(contains(...))` chain with your project names.

---

### 2.5 Action 3 — Create file (OneDrive for Business)

Click **+ New step** → search **Create file** → select **OneDrive for Business: Create file**

| Field | Value |
|---|---|
| **Site Address** | Your OneDrive / SharePoint site |
| **Folder Path** | `/NPI-Queue/inbound` |
| **File Name** | `@{variables('filename')}` |
| **File Content** | `@{outputs('Compose')}` |

> **Common mistake:** Do not put the Compose output in the File Name field.
> File Name = the variable. File Content = the Compose output.

---

### 2.6 Save and enable

1. Click **Save**
2. Click **Test** → **Manually** → **Run flow**
3. Send a test email with `NPI Voltaren` in the subject
4. Check the flow run history — all 3 steps should show green ticks
5. Open OneDrive → `NPI-Queue/inbound/` — a `.json` file should appear

---

## Part 3 — Testing the Backend

Run these in order. Each test builds on the previous one.

---

### Test 1 — Verify OneDrive connection
```bash
python scripts/test_onedrive.py
```
**Expected:**
```
✓ Token OK
✓ All NPI-Queue folders exist or created
✓ Test file written
✓ Test file read back correctly
✓ Inbound folder listed
```

---

### Test 2 — AI agent dry run (no OneDrive, no DB changes)
```bash
python scripts/test_ai_agent.py --project Voltaren
```
**Expected:** Shows what tool calls the AI *would* make for 4 test scenarios.

Run a single scenario only:
```bash
python scripts/test_ai_agent.py --project Voltaren --test 1
```

| Test # | Email scenario | Expected AI action |
|---|---|---|
| 1 | PCB design issue found | `create_issue` (severity: critical) |
| 2 | Stencil order shipped | `update_task_status` (done) |
| 3 | Need ICT fixture task | `create_task` |
| 4 | FYI customer visit | `no_action` |

---

### Test 3 — AI agent execute (writes to DB)
```bash
python scripts/test_ai_agent.py --project Voltaren --test 1 --execute
```
**Expected:**
```
✓ Action OK : {'issue_id': 22, 'action': 'create_issue'}
```
Open the Voltaren project in the UI → **Issues tab** to verify the new issue.

---

### Test 4 — Write sample emails to OneDrive
```bash
python scripts/test_write_sample_email.py
```
**Expected:** 4 `.json` files appear in `NPI-Queue/inbound/` on OneDrive.

---

### Test 5 — Full pipeline dry run
```bash
python scripts/run_pipeline.py --dry-run
```
**Expected:**
```
DRY RUN — no changes will be made
Checking OneDrive inbound folder...  [14:05:00]
  OK   email_20260415_XXXXXX.json → Voltaren — 1 action(s)
  Done: 1 OK, 0 error(s)
```

---

### Test 6 — Full pipeline execute
```bash
python scripts/run_pipeline.py
```
**Expected:**
```
Checking OneDrive inbound folder...  [14:05:00]
  OK   email_20260415_XXXXXX.json → Voltaren — 1 action(s)
  Done: 1 OK, 0 error(s) out of 1 file(s)
```
After running:
- File moves: `NPI-Queue/inbound/` → `NPI-Queue/processed/`
- Result written to `NPI-Queue/outbound/`
- Issue/task created in NPI Tracker

---

### Test 7 — Process a single named file
```bash
python scripts/run_pipeline.py --file email_20260415_153103_9941.json
```

---

### Test 8 — Live end-to-end (full PA + backend)
1. Send a real email to your Outlook inbox:
   - **Subject:** `NPI Voltaren — stencil delayed`
   - **Body:** `Hi team, the stencil for Voltaren ETB has been delayed by 2 weeks due to supplier issue. High severity.`
2. Wait ~30 seconds for PA flow to trigger
3. Check OneDrive `NPI-Queue/inbound/` — new `.json` file should appear
4. Run the pipeline:
   ```bash
   python scripts/run_pipeline.py
   ```
5. Open the Voltaren project → **Issues tab** — new AI-created issue appears

---

## Part 4 — Automate Polling

### Option A — Built-in loop (simplest)
Run the script with `--loop` and it polls continuously until you press Ctrl+C:

```bash
# Poll every 5 minutes (default)
python scripts/run_pipeline.py --loop

# Poll every 60 seconds (faster for testing)
python scripts/run_pipeline.py --loop --interval 60

# Poll every 30 seconds, dry run
python scripts/run_pipeline.py --loop --interval 30 --dry-run
```

Output example:
```
Loop mode — polling every 300s. Press Ctrl+C to stop.

Checking OneDrive inbound folder...  [14:05:00]
  No new files.
  Next poll in 300s...

Checking OneDrive inbound folder...  [14:10:01]
  OK  email_xxx.json → Voltaren — 1 action(s)
  Next poll in 300s...
```

---

### Option B — Windows Task Scheduler (runs in background)
Create a scheduled task that fires every 5 minutes even when no terminal is open:

| Setting | Value |
|---|---|
| **Program** | `D:\npi-tracker\venv\Scripts\python.exe` |
| **Arguments** | `D:\npi-tracker\scripts\run_pipeline.py` |
| **Start in** | `D:\npi-tracker` |
| **Schedule** | Every 5 minutes |

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `400 Bad Request` on list folder | `$orderby` not supported | Already fixed in `onedrive.py` |
| `project_name: ""` in JSON | PA expression saved as plain text | Re-paste Compose block; confirm colored chips appear |
| `Could not resolve project` | Project name not in DB | Run `python scripts/run_pipeline.py` after seeding data |
| `formatDateTime null` error | Wrong trigger field | Use `utcNow()` in the filename variable |
| `AI_AGENT_ENABLED is False` | Flag not set in `.env` | Set `AI_AGENT_ENABLED=True` in `.env` |
| Token expired / 401 error | Refresh token rotated | Run `python scripts/get_onedrive_token.py` |

---

## Script Reference

| Script | Command | What it does |
|---|---|---|
| `test_onedrive.py` | `python scripts/test_onedrive.py` | Verify token + create OneDrive folders |
| `test_ai_agent.py` | `python scripts/test_ai_agent.py --project Voltaren` | Test AI decisions — **no OneDrive needed** |
| `test_ai_agent.py` | `python scripts/test_ai_agent.py --project Voltaren --test 1` | Test single scenario only |
| `test_ai_agent.py` | `python scripts/test_ai_agent.py --project Voltaren --execute` | Test AI + write to DB |
| `test_write_sample_email.py` | `python scripts/test_write_sample_email.py` | Write 4 sample emails to OneDrive |
| `run_pipeline.py` | `python scripts/run_pipeline.py --dry-run` | Preview pipeline (no DB changes) |
| `run_pipeline.py` | `python scripts/run_pipeline.py` | Run full pipeline once |
| `run_pipeline.py` | `python scripts/run_pipeline.py --file name.json` | Process one specific file |
| `run_pipeline.py` | `python scripts/run_pipeline.py --loop` | Poll every 5 min continuously |
| `run_pipeline.py` | `python scripts/run_pipeline.py --loop --interval 60` | Poll every 60s continuously |
