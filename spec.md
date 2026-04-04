# NPI Tracker — Full-Stack Django Application Specification

## 1. Overview

**NPI Tracker** is a project portfolio management tool for **NPI (New Product Introduction) managers** at an **EMS (Electronics Manufacturing Services)** company. It tracks the full lifecycle of NPI projects — from kickoff through build stages (ETB → PS → FAS) — including task scheduling, issue tracking, NRE cost management, team coordination, and build-stage gate readiness.

**Target users:** NPI Program Managers (PGMs) at SVI Thailand managing multiple customer projects simultaneously.

**Business context:** Each NPI project represents a new product being introduced into manufacturing for a customer. Projects progress through defined build stages (External Test Build → Pre-Series → First Article Sample) before reaching volume production. The manager needs a single dashboard to see all projects' status, financial exposure, and blockers at a glance.

---

## 2. Data Models

### 2.1 Project

The top-level entity. Everything belongs to a project.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| name | string(200) | yes | e.g. "Greenland" |
| pgm | string(100) | yes | Program Manager name |
| customer | string(200) | yes | e.g. "Axis", "Hanwha" |
| start_date | date | yes | Project start |
| end_date | date | yes | Target completion |
| color | string(7) | yes | Hex color for UI (e.g. "#4f7ef8") |
| annual_volume | integer | no | Projected units/year |
| annual_revenue | decimal(14,2) | no | Projected revenue/year |
| currency | string(3) | yes | Default "THB". Choices: THB, USD, EUR |
| created_at | datetime | auto | |
| updated_at | datetime | auto | |

**Derived fields (computed, not stored):**
- `overall_status`: "Planning" / "Active" / "Complete" / "Blocked" — derived from task statuses and whether any critical issues exist.
- `current_stage`: The first stage whose status is `in-progress`, or `ready`, or `planned` (in that priority order).
- `duration_months`: Computed from `end_date - start_date`.
- `task_progress_pct`: `done_tasks / total_tasks * 100`.

### 2.2 BuildStage

Each project has exactly 3 build stages created on project creation: **ETB**, **PS**, **FAS**. Displayed as a left-to-right pipeline.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| project | FK → Project | yes | |
| stage_id | string(10) | yes | "etb", "ps", "fas" |
| name | string(10) | yes | "ETB", "PS", "FAS" |
| full_name | string(100) | yes | "External Test Build", "Pre-Series Build", "First Article Sample" |
| planned_date | date | no | Target build date |
| actual_date | date | no | When it actually happened |
| build_qty | integer | default 0 | Target quantity |
| build_location | string(200) | no | e.g. "SVI Thailand" |
| bom_revision | string(50) | no | e.g. "R2.3" |
| status | string(20) | yes | Choices: `planned`, `ready`, `in-progress`, `completed`, `on-hold` |
| qty_produced | integer | default 0 | Post-build: actual produced |
| qty_passed | integer | default 0 | Post-build: passed QC |
| yield_pct | decimal(5,2) | default 0 | Auto-calculated: `qty_passed / qty_produced * 100` |
| customer_approval | string(20) | default "pending" | Choices: `pending`, `approved`, `conditional`, `rejected` |
| approval_notes | text | no | |
| notes | text | no | |
| sort_order | integer | yes | 1=ETB, 2=PS, 3=FAS |

**Gate readiness** is computed from:
1. **Auto-gates** (3 checks, computed):
   - All tasks for this stage are `done`
   - All NRE items for this stage have a PO (status ≠ `no-po`)
   - No open issues linked to this stage
2. **Manual gate checklist items** (user-created, per-stage)

Overall gate readiness % = average of (auto-gate average + manual checklist %) if manual items exist, otherwise just auto-gate average.

### 2.3 GateChecklistItem

Manual checklist items within a build stage. Users can add/remove/toggle these.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| stage | FK → BuildStage | yes | |
| label | string(200) | yes | e.g. "Customer BOM sign-off" |
| checked | boolean | default false | |
| sort_order | integer | yes | |

### 2.4 Task

Tasks are the core work items. Displayed in Gantt, list, and milestone views. Grouped by `section`.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| project | FK → Project | yes | |
| name | string(300) | yes | e.g. "PCB Production" |
| section | string(200) | yes | Grouping header, e.g. "Pre-req: Main PCBA (Cambodia)", "Build Schedule" |
| remark | text | no | Free-text notes, supplier info, dependencies |
| who | string(200) | yes | Assigned party, e.g. "Axis / SVI" (free text, not FK) |
| days | integer | yes | Duration in calendar days |
| start | date | yes | |
| end | date | yes | |
| status | string(20) | yes | Choices: `open`, `inprogress`, `done`, `blocked` |
| stage | string(10) | no | Nullable. Choices: `etb`, `ps`, `fas`. Links task to a build stage for filtering. |
| sort_order | integer | yes | Within section |

**Important:** Tasks with `section = "Build Schedule"` are the key milestone tasks (e.g. "ETB Build", "PS Build", "FAS Build") shown in the portfolio-level Gantt. These typically align 1:1 with build stages.

### 2.5 Issue

Tracks risks, blockers, and problems. Can be linked to tasks and build stages.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| project | FK → Project | yes | |
| title | string(300) | yes | |
| desc | text | no | What happened, impact details |
| severity | string(20) | yes | Choices: `critical`, `high`, `medium`, `low` |
| status | string(20) | yes | Choices: `open`, `investigating`, `resolved` |
| owner | string(200) | no | Responsible person (free text) |
| due | date | no | Due/target resolution date |
| impact | string(500) | no | e.g. "PS Build may slip 3 weeks" |
| stage | string(10) | no | Nullable. Choices: `etb`, `ps`, `fas` |
| linked_tasks | M2M → Task | no | Zero or more tasks affected by this issue |

**Display rules:**
- Sorted by: open first (by severity desc), then resolved
- Issues with severity=`critical` cause the project's overall status to show "Blocked"
- Open issue count shown as badge in sidebar, issue tab, and portfolio table
- On Gantt bars, a red dot appears if the task has linked open issues

### 2.6 TeamMember

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| project | FK → Project | yes | |
| name | string(200) | yes | |
| role | string(100) | no | e.g. "PGM", "PCB Engineer", "Customer PM" |
| company | string(200) | no | e.g. "SVI Thailand", "Axis" |
| email | email | no | |
| phone | string(50) | no | |

### 2.7 NREItem (Non-Recurring Engineering Cost)

Tracks tooling, fixtures, stencils, and other one-time costs that need customer PO coverage.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | UUID / auto PK | auto | |
| project | FK → Project | yes | |
| category | string(50) | yes | Choices: `Stencil`, `Jig Fixture`, `Test Fixture`, `Pallet`, `Programming Fixture`, `Tooling`, `Other` |
| desc | string(500) | yes | e.g. "Top-side stencil for Main PCBA" |
| supplier | string(200) | no | default "TBD" |
| cost | decimal(12,2) | yes | Unit cost |
| currency | string(3) | yes | Choices: THB, USD, EUR |
| po_status | string(20) | yes | Choices: `no-po`, `po-requested`, `po-received`, `invoiced`, `paid` |
| po_number | string(100) | no | Customer PO reference |
| due | date | no | "Needed by" date |
| qty | integer | default 1 | |
| notes | text | no | |
| stage | string(10) | no | Nullable. Choices: `etb`, `ps`, `fas` |
| linked_tasks | M2M → Task | no | |

**Derived aggregates (per project):**
- `nre_total`: SUM(cost × qty) across all items
- `nre_no_po_count`: COUNT where po_status = "no-po"
- `nre_no_po_amount`: SUM(cost × qty) where po_status = "no-po"
- `nre_po_covered`: SUM(cost × qty) where po_status ≠ "no-po"
- `nre_paid`: SUM(cost × qty) where po_status = "paid"

**Display:** Items grouped by category in a table. Overdue items (no PO + past due date) get a warning icon.

---

## 3. Application Pages & Views

### 3.1 Portfolio Overview (Home / Dashboard)

**URL:** `/` or `/portfolio/`

This is the landing page. Shows high-level status of all projects for the NPI manager.

#### 3.1.1 Build Plan Gantt (top section)

A horizontal Gantt chart spanning all projects. The purpose is to show at a glance where every project is in its build lifecycle.

- **Y-axis (rows):** One row per project
- **X-axis:** Shared weekly timeline (Monday-aligned ISO weeks), labeled "Wk01", "Wk02", etc. with short date below
- **Left column (sticky):** Project name (clickable → opens project), current stage label + status
- **Bars:** Each project's 3 build stages (ETB, PS, FAS) rendered as short bars at their `planned_date` (or `actual_date` if set), each ~5 days wide
- **Bar colors:** Green = completed, Amber = in-progress, Blue = planned, Purple = ready, Gray = on-hold
- **Current stage indicator:** Thicker border + dot marker on the active stage bar
- **Today line:** Vertical blue line marking today's date
- **Auto-scroll:** On load, scroll horizontally so today is visible (offset by ~3 weeks left)

#### 3.1.2 All Projects Table (below the Gantt)

A data table with one row per project. Columns:

| Column | Content |
|--------|---------|
| Project | Color dot + name (click → open project) + sub-line "PGM: name · customer" |
| Status | Badge: Planning / Active / Complete / Blocked |
| Current Stage | Stage pill (ETB/PS/FAS) with color by stage status + planned date |
| Build Qty (ETB / PS / FAS) | Small badges per stage showing build quantity. Active stage badge highlighted blue. |
| Annual Revenue | Formatted money value (e.g. "฿25.0M") with "currency / yr" sub-label |
| Annual Volume | Formatted number (e.g. "50K") with "units / yr" sub-label |
| Start Date | Project start date |
| Duration | e.g. "9 mo" with compact date range below (e.g. "Oct 2025 → Jun 2026") |
| Issues | Button showing open issue count. Red if has open issues, bold red if has critical. Green "✓ Clear" if none. Click opens Issues Modal. |

#### 3.1.3 Project Issues Modal (popup from portfolio)

Triggered by clicking the Issues button on any project row.

- Modal overlay with project name as title
- Lists all issues for that project, sorted by severity (critical first)
- Each issue card shows: severity badge, status badge, title, description, owner, due date, stage, impact text
- Footer: "Close" button + "Open Project →" button (navigates to project detail)
- Dismissible by clicking overlay background

### 3.2 Project Detail

**URL:** `/project/<id>/`

Shows full detail for a single project. Has a **tab bar** with 7 views:

- **Gantt** (default)
- **Task List**
- **Milestones**
- **Team**
- **Build Stages**
- **NRE Costs**
- **Issues**

Each tab has relevant action buttons in the top bar (e.g. "+ Add Task" on Gantt/List/Milestones).

A **stage filter dropdown** appears on Gantt, List, and Milestones views. Choices: "All Stages", "ETB", "PS", "FAS". Filters tasks by their `stage` field.

#### 3.2.1 Gantt View

Split-panel layout:

**Left panel (fixed 530px):**
- Header: #, Task, Assigned, Days, Status, Issues(⚠)
- Rows grouped by section (section headers are gray uppercase labels)
- Each task row shows: ID, name + stage tag + truncated remark, assigned person pill, duration, status dot, issue chip (red circle with count if linked to open issues, green checkmark if all resolved)
- **Double-click** a row → opens task edit modal

**Right panel (scrollable timeline):**
- Weekly columns (80px each), ISO week numbers + short dates
- Current week column highlighted
- Gantt bars: colored by status (blue=open, amber=in-progress, green=done, red=blocked), positioned by start/end dates
- Bar label: task name (truncated to fit)
- Red dot on bar if linked to open issues
- **Today line:** Vertical blue line
- Auto-scroll to today on render

**Scroll sync:** Left panel vertical scroll syncs with right panel. Right panel horizontal scroll syncs with the week header.

#### 3.2.2 Task List View

Table format with same data as Gantt but in a flat tabular layout.

Columns: #, Task (+ stage tag), Remark, Assigned, Start, End, Status (badge), Issues (⚠ chip)

Grouped by section (section header rows span full width).
Double-click row → edit task modal.

#### 3.2.3 Milestones View

Card-based view grouped by section (task grouping). Each section card shows:

- Section name + overall status badge
- Date range (earliest start → latest end within section)
- Task count + done count
- Progress bar
- All tasks as small pill tags with colored status dots

Purpose: Quick overview of which work streams are complete vs. still active.

#### 3.2.4 Team View

Grid of member cards. Each card shows:
- Avatar (initials with random color from palette)
- Name, role, company
- Email (clickable mailto link), phone
- Count of tasks loosely matched to this member (by name/company in task `who` field)
- Edit / Remove buttons

Empty state: Friendly message + "Add First Member" CTA.

#### 3.2.5 Build Stages View

Horizontal pipeline visualization of ETB → PS → FAS stages with arrow connectors.

Each stage card contains:

**Header:** Stage name (e.g. "ETB"), full name, status badge, Edit button

**Metadata grid:**
- Planned date, actual date
- Build qty, build location
- BOM revision, tasks done count

**Gate Readiness section:**
- Overall gate % with colored progress bar (green ≥100%, amber ≥50%, red <50%)
- **Auto-gates** (3 computed checks):
  - Tasks done: X/Y (green checkmark or empty)
  - NRE with PO: X/Y
  - Open issues: N
- **Manual checklist items:** User-clickable checkboxes (toggle directly on the view, no modal needed for toggling)

**Post-build results** (shown only if stage is completed or has production data):
- Qty produced, qty passed, yield %
- Customer approval badge (Pending/Approved/Conditional/Rejected)
- Approval notes

**Notes:** Free text at bottom of card if present.

#### 3.2.6 NRE Costs View

**Summary stats** (top): 4 stat cards:
- Total Estimated NRE (blue)
- Covered by PO (green)
- Missing PO count (red)
- Paid amount (purple)

**Table:** Grouped by category (Stencil, Jig Fixture, Test Fixture, etc.)

Columns: #, Description + linked task tags, Supplier, Qty, Cost (formatted with currency symbol), PO Status (colored badge), PO Number, Needed By date (red + ⚠ if overdue and no PO), Actions (Edit/Delete)

Category header rows span full width with item count.

Double-click row → edit NRE modal.

#### 3.2.7 Issues View

List of issue cards sorted by: open issues first (by severity desc), then resolved (dimmed).

Each issue card:
- Left border colored by severity (critical=red, high=amber, medium=blue, low=gray)
- Header: severity badge + status badge + title + Edit/Delete buttons
- Description text
- Impact tag (if present, red-ish highlight)
- Owner + due date
- Linked tasks (clickable tags that navigate to Gantt)

Resolved issues shown at bottom under "Resolved" section header with reduced opacity.

Empty state: Green checkmark + friendly message + "Log First Issue" CTA.

---

## 4. CRUD Operations & Modals

All create/edit operations use modal overlays (dark backdrop with blur). Modals dismiss on overlay click, Cancel button, or after save.

### 4.1 Task Modal

**Fields:**
- Task Name (text, required)
- Section / Category (text, required, default "General")
- Remark / Notes (textarea)
- Assigned To (text)
- Duration in days (number)
- Start Date (date picker)
- End Date (date picker)
- Status (select: Open, In Progress, Done, Blocked)
- Build Stage (select: None, ETB, PS, FAS)

**Operations:** Create new task, Edit existing task (double-click from Gantt/List), Save, Cancel.

### 4.2 Team Member Modal

**Fields:**
- Name (text, required)
- Role (text)
- Company / Site (text)
- Email (email)
- Phone / Line ID (text)

**Operations:** Add member, Edit member, Save, Cancel. Delete is a separate confirmation dialog from the Team view.

### 4.3 Issue Modal

**Fields:**
- Issue Title (text, required)
- Description (textarea)
- Severity (select: Critical, High, Medium, Low)
- Status (select: Open, Investigating, Resolved)
- Owner (text)
- Due Date (date picker)
- Build Stage (select: None, ETB, PS, FAS)
- Impact Description (text)
- Linked Tasks (multi-select pill selector showing all project tasks as toggleable pills with "#id name" labels)

**Operations:** Add issue, Edit issue, Save, Cancel. Delete is a separate confirmation dialog.

### 4.4 Build Stage Modal

**Fields:**
- Stage (read-only, e.g. "ETB — External Test Build")
- Status (select: Planned, Ready, In Progress, Completed, On Hold)
- Planned Date (date)
- Actual Date (date)
- Build Qty (number)
- Build Location (text)
- BOM Revision (text)
- Customer Approval (select: Pending, Approved, Conditional, Rejected)
- Post-Build Results section:
  - Qty Produced (number)
  - Qty Passed (number)
  - *(Yield % is auto-calculated on save)*
- Approval Notes (text)
- Notes (textarea)
- Manual Gate Checklist:
  - List of existing items with checkboxes + delete buttons
  - Text input + "Add" button to create new checklist items

**Operations:** Edit stage (stages are auto-created with project, never manually created or deleted), Save, Cancel.

### 4.5 NRE Item Modal

**Fields:**
- Category (select: Stencil, Jig Fixture, Test Fixture, Pallet, Programming Fixture, Tooling, Other)
- Supplier (text)
- Description (text, required)
- Estimated Cost (number, per unit)
- Currency (select: THB, USD, EUR)
- PO Status (select: No PO, PO Requested, PO Received, Invoiced, Paid)
- PO Number (text)
- Needed By Date (date)
- Quantity (number, default 1)
- Build Stage (select: None, ETB, PS, FAS)
- Notes (textarea)
- Linked Tasks (multi-select pill selector, same as Issue modal)

**Operations:** Add NRE item, Edit NRE item, Save, Cancel. Delete is a separate confirmation dialog.

### 4.6 New Project Modal

**Fields:**
- Project Name (text, required)
- PGM / PM (text)
- Customer (text)
- Start Date (date)
- Target End Date (date)

**On create:** Auto-generates 3 build stages (ETB, PS, FAS) with all default/empty values. Navigates to the new project's detail view.

---

## 5. Navigation & Layout

### 5.1 Sidebar (left, 220px)

- **Logo:** "NPI Tracker"
- **"All Projects" link** → Portfolio Overview
- **Projects section:** List of all projects, each with:
  - Color dot
  - Project name (truncated with ellipsis)
  - Red badge with open issue count (if any)
  - Active state highlight when selected
- **"+ New Project" button** at bottom

Sidebar collapses off-screen on mobile (≤1024px) with hamburger toggle.

### 5.2 Top Bar

- Hamburger button (mobile only)
- Page title (dynamic: "Portfolio Overview" or project name)
- **Tab buttons** (only visible when inside a project): Gantt, Task List, Milestones, Team, Build Stages, NRE Costs, Issues
  - Issues tab shows open count badge
  - NRE tab shows no-PO count badge
- Spacer
- **Theme toggle** (dark/light mode, persisted to localStorage)
- Context-sensitive action buttons (hidden/shown based on current tab):
  - "+ Add Task" on Gantt / Task List / Milestones
  - "+ Add Member" on Team
  - "+ Add Issue" on Issues
  - "+ Add NRE Item" on NRE Costs

### 5.3 Theme Support

Two themes: **dark** (default) and **light**. Toggled via button in top bar, persisted in localStorage under key `npi-theme`.

Dark theme uses deep blue-gray backgrounds (#0f1117, #1a1d27). Light theme uses white/gray (#f0f2f5, #ffffff). All component colors use CSS variables.

### 5.4 Responsive Behavior

Three breakpoints:
- **≤1024px:** Sidebar becomes overlay (hamburger toggle), gantt left panel narrows to 340px
- **≤768px:** Top bar wraps, smaller tab buttons, gantt left panel 260px, assigned/duration columns hidden
- **≤480px:** Gantt left panel 200px, issue indicators hidden, team grid single column

---

## 6. Django Implementation Guidance

### 6.1 Tech Stack (already scaffolded)

The project is already scaffolded with:

- **Backend:** Django 4.2 (`config/` project, `core/` app)
- **Database:** SQLite (dev), migrate to PostgreSQL for production
- **Frontend tooling:** Vite 5 + django-vite for HMR and asset bundling
- **CSS:** Tailwind CSS v4 (via `@tailwindcss/vite` plugin)
- **JS frameworks:** Alpine.js 3.x (client-side reactivity) + htmx 2.x (server-driven HTML swaps)
- **Static serving:** WhiteNoise (compressed manifest storage)
- **Authentication:** Django's built-in auth (add login_required as needed)

**Existing file structure:**
```
config/settings.py          — Django settings (DJANGO_VITE configured)
config/urls.py              — Root URL conf → includes core.urls
core/models.py              — Empty, models to be built
core/views.py               — Single index view
core/urls.py                — Single "/" route
templates/base.html         — Base template with {% vite_hmr_client %} and {% vite_asset %}
templates/index.html        — Placeholder extending base.html
static/src/main.js          — Vite entry: imports Alpine, htmx, style.css
static/src/style.css        — Tailwind import + @source for templates
vite.config.js              — Vite config (base: /static/, outDir: ./assets, tailwind plugin)
package.json                — vite, tailwindcss, alpinejs, htmx.org
requirements.txt            — Django, django-vite, whitenoise
```

### 6.2 Architecture: Django + HTMX + Alpine.js

This is NOT a SPA. Every page is server-rendered by Django templates. Interactive behavior is split between:

- **HTMX** — handles all server communication. Modals, CRUD forms, tab switching, filter changes, and live updates all use `hx-get`, `hx-post`, `hx-swap`, `hx-target`, `hx-trigger`. No fetch() or XMLHttpRequest. No DRF serializers — views return HTML partials.
- **Alpine.js** — handles client-only UI state: sidebar toggle, theme toggle, dropdown menus, modal open/close, form validation feedback, Gantt scroll sync. Anything that doesn't need the server.
- **Vanilla JS** (in `main.js` or a dedicated module) — handles the Gantt chart rendering. The Gantt is complex enough that it should be rendered client-side from JSON data embedded in the template (via `{{ data|json_script:"gantt-data" }}`). HTMX is not suitable for the Gantt's pixel-level bar positioning and scroll sync.

**Pattern for each view:**

```
Full page load:  GET /project/<id>/gantt/  → returns full page (extends base.html)
Tab switch:      hx-get="/project/<id>/gantt/" hx-target="#content" hx-push-url="true"
                 → returns #content partial only (detected via request.htmx)
Modal open:      hx-get="/project/<id>/tasks/<tid>/edit/" hx-target="#modal-container"
                 → returns modal HTML partial, Alpine.js opens it
Modal save:      hx-post="/project/<id>/tasks/<tid>/edit/" hx-target="#content"
                 → validates, saves, returns updated view partial
Delete:          hx-delete="/project/<id>/tasks/<tid>/" hx-confirm="Delete this task?"
                 → deletes, returns updated view partial
```

Use `django-htmx` middleware to detect `request.htmx` and return partials vs. full pages.

### 6.3 URL Structure

All URLs live under `core/urls.py`. No `/api/` prefix — every endpoint returns HTML.

```python
# Portfolio
path("", views.portfolio, name="portfolio"),

# Project detail — each tab is a separate URL for bookmarkability
path("project/<int:pk>/", views.project_detail, name="project-detail"),  # redirects to gantt
path("project/<int:pk>/gantt/", views.project_gantt, name="project-gantt"),
path("project/<int:pk>/list/", views.project_list, name="project-list"),
path("project/<int:pk>/milestones/", views.project_milestones, name="project-milestones"),
path("project/<int:pk>/team/", views.project_team, name="project-team"),
path("project/<int:pk>/stages/", views.project_stages, name="project-stages"),
path("project/<int:pk>/nre/", views.project_nre, name="project-nre"),
path("project/<int:pk>/issues/", views.project_issues, name="project-issues"),

# CRUD endpoints (return HTML partials for HTMX)
path("project/create/", views.project_create, name="project-create"),

path("project/<int:pk>/tasks/create/", views.task_create, name="task-create"),
path("project/<int:pk>/tasks/<int:tid>/edit/", views.task_edit, name="task-edit"),
path("project/<int:pk>/tasks/<int:tid>/delete/", views.task_delete, name="task-delete"),

path("project/<int:pk>/issues/create/", views.issue_create, name="issue-create"),
path("project/<int:pk>/issues/<int:iid>/edit/", views.issue_edit, name="issue-edit"),
path("project/<int:pk>/issues/<int:iid>/delete/", views.issue_delete, name="issue-delete"),

path("project/<int:pk>/team/create/", views.member_create, name="member-create"),
path("project/<int:pk>/team/<int:mid>/edit/", views.member_edit, name="member-edit"),
path("project/<int:pk>/team/<int:mid>/delete/", views.member_delete, name="member-delete"),

path("project/<int:pk>/nre/create/", views.nre_create, name="nre-create"),
path("project/<int:pk>/nre/<int:nid>/edit/", views.nre_edit, name="nre-edit"),
path("project/<int:pk>/nre/<int:nid>/delete/", views.nre_delete, name="nre-delete"),

path("project/<int:pk>/stages/<str:stage_id>/edit/", views.stage_edit, name="stage-edit"),
path("project/<int:pk>/stages/<str:stage_id>/gate/<int:gid>/toggle/", views.gate_toggle, name="gate-toggle"),

# Portfolio issues modal (returns partial)
path("project/<int:pk>/issues-modal/", views.project_issues_modal, name="project-issues-modal"),
```

### 6.4 Template Structure

```
templates/
├── base.html                          — Full page shell: <html>, vite assets, sidebar, topbar, #content
├── components/
│   ├── sidebar.html                   — Sidebar partial (project list, active state)
│   ├── topbar.html                    — Top bar with tabs, action buttons
│   ├── modal_form.html                — Reusable modal wrapper
│   └── stage_filter.html              — Stage filter dropdown (ETB/PS/FAS)
├── portfolio/
│   ├── portfolio.html                 — Full page: extends base.html
│   ├── _build_plan_gantt.html         — Partial: portfolio-level build Gantt (rendered client-side from JSON)
│   ├── _projects_table.html           — Partial: all-projects table
│   └── _issues_modal.html             — Partial: project issues popup
├── project/
│   ├── detail.html                    — Full page: extends base.html, includes active tab partial
│   ├── _gantt.html                    — Partial: Gantt view (data passed as JSON for client-side rendering)
│   ├── _list.html                     — Partial: task list table
│   ├── _milestones.html               — Partial: milestone cards
│   ├── _team.html                     — Partial: team member grid
│   ├── _stages.html                   — Partial: build stages pipeline
│   ├── _nre.html                      — Partial: NRE costs table + stats
│   └── _issues.html                   — Partial: issues list
├── forms/
│   ├── _task_form.html                — Task create/edit modal form
│   ├── _issue_form.html               — Issue create/edit modal form
│   ├── _member_form.html              — Team member create/edit form
│   ├── _nre_form.html                 — NRE item create/edit form
│   ├── _stage_form.html               — Build stage edit form
│   └── _project_form.html             — New project form
```

**Partial naming convention:** Files prefixed with `_` are HTMX partials (never rendered as full pages). Views check `request.htmx` — if true, return the partial; if false (direct URL visit), return the full page wrapping the partial.

### 6.5 Key Business Logic (Server-Side)

1. **Project overall status** — computed property on the model:
   ```python
   @property
   def overall_status(self):
       if self.issues.filter(severity="critical").exclude(status="resolved").exists():
           return "blocked"
       if self.tasks.filter(status="inprogress").exists():
           return "inprogress"
       if self.tasks.exists() and not self.tasks.exclude(status="done").exists():
           return "done"
       return "open"
   ```

2. **Current stage** — first stage with status `in-progress`, else `ready`, else `planned`:
   ```python
   @property
   def current_stage(self):
       for status in ["in-progress", "ready", "planned"]:
           stage = self.stages.filter(status=status).order_by("sort_order").first()
           if stage:
               return stage
       return None
   ```

3. **Yield auto-calculation** — in BuildStage.save():
   ```python
   def save(self, *args, **kwargs):
       self.yield_pct = round(self.qty_passed / self.qty_produced * 100, 2) if self.qty_produced > 0 else 0
       super().save(*args, **kwargs)
   ```

4. **Gate readiness** — computed on read (model method, not stored):
   - Auto-gates: tasks completion %, NRE PO coverage %, open issue count
   - Manual gates: checklist checked %
   - Overall: average of (auto-gate avg + manual %) if manual items exist

5. **On project creation** — use a post_save signal or override `save()` to auto-create 3 BuildStage records (ETB sort_order=1, PS sort_order=2, FAS sort_order=3).

6. **NRE overdue** — in template or model method: `po_status == "no-po" and due and due < today`.

### 6.6 Gantt Chart Rendering

The Gantt chart (both portfolio-level and project-level) is too complex for server-rendered HTML — it requires pixel-level bar positioning, scroll synchronization between panels, and a today-line overlay.

**Approach:** Render the Gantt client-side in a dedicated JS module (`static/src/gantt.js`), fed by JSON data embedded in the template:

```html
<!-- In _gantt.html partial -->
{{ gantt_data|json_script:"gantt-data" }}
<div id="gantt-container"></div>

<script type="module">
  import { renderGantt } from '/static/src/gantt.js';
  const data = JSON.parse(document.getElementById('gantt-data').textContent);
  renderGantt(document.getElementById('gantt-container'), data);
</script>
```

The view serializes the needed data (tasks, issues, stages, date ranges) as a Python dict and passes it to the template context. The JS module handles all rendering, scroll sync, and today-line logic.

For the portfolio Gantt, same pattern — the view passes all projects' stage data as JSON.

### 6.7 HTMX Interaction Patterns

**Tab switching (no full page reload):**
```html
<button class="tab-btn"
        hx-get="{% url 'project-gantt' project.pk %}"
        hx-target="#content"
        hx-push-url="true"
        hx-swap="innerHTML">
  Gantt
</button>
```

**Modal open → submit → close + refresh:**
```html
<!-- Open modal -->
<button hx-get="{% url 'task-edit' project.pk task.pk %}"
        hx-target="#modal-container"
        hx-swap="innerHTML">
  Edit
</button>

<!-- Modal container (in base.html, always present) -->
<div id="modal-container"></div>

<!-- The returned partial includes Alpine.js to auto-open -->
<div x-data="{ open: true }" x-show="open" @keydown.escape.window="open = false"
     class="modal-overlay">
  <form hx-post="{% url 'task-edit' project.pk task.pk %}"
        hx-target="#content" hx-swap="innerHTML"
        @htmx:after-request="if(event.detail.successful) open = false">
    {% csrf_token %}
    <!-- form fields -->
    <button type="submit">Save</button>
  </form>
</div>
```

**Inline toggle (gate checklist):**
```html
<div hx-post="{% url 'gate-toggle' project.pk stage.stage_id item.pk %}"
     hx-target="#stages-content"
     hx-swap="innerHTML"
     class="gate-item">
  {% csrf_token %}
  <span class="gate-check {% if item.checked %}checked{% endif %}">{% if item.checked %}✓{% endif %}</span>
  {{ item.label }}
</div>
```

**Stage filter:**
```html
<select hx-get="{% url 'project-gantt' project.pk %}"
        hx-target="#content"
        hx-swap="innerHTML"
        name="stage">
  <option value="">All Stages</option>
  <option value="etb">ETB</option>
  <option value="ps">PS</option>
  <option value="fas">FAS</option>
</select>
```

### 6.8 Alpine.js Patterns

**Theme toggle (persisted to localStorage):**
```html
<div x-data="{ theme: localStorage.getItem('npi-theme') || 'dark' }"
     x-init="document.documentElement.setAttribute('data-theme', theme)"
     @click="theme = theme === 'dark' ? 'light' : 'dark';
             localStorage.setItem('npi-theme', theme);
             document.documentElement.setAttribute('data-theme', theme)">
</div>
```

**Mobile sidebar:**
```html
<nav x-data="{ open: false }" :class="{ 'open': open }">
  <button @click="open = !open">☰</button>
  <div class="sidebar-overlay" x-show="open" @click="open = false"></div>
</nav>
```

### 6.9 Vite Integration Notes

The project already has Vite configured (`vite.config.js`) with:
- Entry point: `static/src/main.js` (imports Alpine, htmx, Tailwind CSS)
- Output: `./assets/` directory with `manifest.json`
- Dev server: `localhost:5173` with CORS enabled
- `django-vite` reads the manifest for production, proxies to dev server in DEBUG mode

**Dev workflow:** Run `npm run dev` (Vite) and `python manage.py runserver` simultaneously. Vite serves JS/CSS with HMR; Django serves HTML templates.

**Build for production:** `npm run build` → assets compiled to `./assets/`, WhiteNoise serves them.

**Adding new JS modules** (e.g. `gantt.js`): Import from `main.js` or add as a separate Vite entry in `rollupOptions.input`. For the Gantt module, importing from main.js is simpler:
```js
// static/src/main.js
import './gantt.js';
```

### 6.10 Tailwind CSS v4 Notes

The project uses Tailwind v4 with the Vite plugin (`@tailwindcss/vite`). Configuration is done via CSS, not `tailwind.config.js`:

```css
/* static/src/style.css */
@import "tailwindcss";
@source "../../templates/**/*.html";  /* scans templates for class usage */
```

The existing prototype uses custom CSS variables for theming (dark/light). Convert these to Tailwind's `@theme` directive or keep as CSS custom properties alongside Tailwind utilities. The dark/light theme toggle uses `[data-theme="light"]` attribute on `<html>` — define theme variants in CSS accordingly.

### 6.11 Additional Dependencies to Add

```
# requirements.txt (add these)
django-htmx>=1.17.0          # request.htmx detection, HTMX middleware
```

```
# Already installed (no changes needed):
# django-vite, whitenoise — already in requirements.txt
# htmx.org, alpinejs, tailwindcss — already in package.json
```

---

## 7. Sample Data for Seeding

The prototype includes 3 projects with realistic sample data that should be used as Django fixtures/seed data:

### Project 1: Greenland
- Customer: Axis, PGM: Ekaluk
- Date range: Oct 2025 → Jun 2026
- Annual volume: 50,000 units, Revenue: ฿25M
- 23 tasks across 7 sections, 3 issues (1 critical), 8 NRE items
- ETB stage: completed (yield 90%, 10 units, customer approved)
- PS stage: in-progress (blocked by long-lead IC shortage)
- FAS stage: planned

### Project 2: Voltaren
- Customer: Hanwha, PGM: Natthida
- Date range: Jan 2026 → Sep 2026
- Annual volume: 20,000 units, Revenue: ฿12M
- 8 tasks, 1 issue, 3 NRE items
- All stages planned (ETB blocked by BOM approval)

### Project 3: Sentinel
- Customer: Bosch, PGM: Somchai
- Date range: Mar 2026 → Dec 2026
- Annual volume: 30,000 units, Revenue: ฿18M
- 5 tasks, 0 issues, 1 NRE item
- All stages planned (early phase)

---

## 8. Enum / Choice Reference

For quick reference, all choice fields:

| Field | Values |
|-------|--------|
| Task status | `open`, `inprogress`, `done`, `blocked` |
| Issue severity | `critical`, `high`, `medium`, `low` |
| Issue status | `open`, `investigating`, `resolved` |
| Build stage ID | `etb`, `ps`, `fas` |
| Stage status | `planned`, `ready`, `in-progress`, `completed`, `on-hold` |
| Customer approval | `pending`, `approved`, `conditional`, `rejected` |
| NRE category | `Stencil`, `Jig Fixture`, `Test Fixture`, `Pallet`, `Programming Fixture`, `Tooling`, `Other` |
| PO status | `no-po`, `po-requested`, `po-received`, `invoiced`, `paid` |
| Currency | `THB`, `USD`, `EUR` |
