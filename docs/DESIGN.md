# DriveRadar — Design Doc (v1.1)

Placement-notice tracker for my college batch. Portfolio project, ~10 days, ₹0/month.
Status: **v1.1, decisions locked** (2026-11-18). Change decisions here first, then in code.

---

## 0. Finalized decisions

| # | Decision |
|---|---|
| **D1 Runtime** | Python 3.13 + FastAPI, with **uv** managing Python, dependencies and the lockfile. If a dependency breaks on 3.13, flag it. Don't switch versions silently. |
| **D2 Dev setup** | Local Windows development with VS Code + Claude Code. GitHub repo named `driveradar`. |
| **D3 Hosting (₹0, no credit card)** | Backend: Render Free. DB: Neon Postgres free. Frontend: Vercel Hobby. If any signup asks for a card, stop and pick another free option. |
| **D4 Ingestion** | Every source (TPO email, WhatsApp, portal, Telegram) goes through one path: paste or forward to the bot → parser → admin review → publish. No scraping. (§4) |
| **D5 Alerts** | Telegram bot in v1. WhatsApp alerts in v2. |
| **D6 v1 scope** | Eligibility filter, deadline reminders, application status tracking. Company history moves to v2. |
| **D7 Users** | The whole batch, with logins. Roles: student and admin. |
| **D8 Way of working** | I write the core logic. Claude scaffolds, writes tests (often first), reviews and explains. (§9) |

**Locked stack:** Python 3.13, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2.0 (async) + asyncpg, Alembic, PostgreSQL 17, pytest + httpx, ruff (lint + format), mypy, Docker Compose (local DB), GitHub Actions CI. Frontend: React + TypeScript + Vite (*to confirm*, §13).

---

## 1. Problem

Placement notices reach the batch from four places: TPO emails, WhatsApp group forwards, the college portal, and Telegram or other channels. Because of this, students:
- miss registration deadlines,
- waste time reading drives they aren't eligible for,
- lose track of where they stand in each drive (applied? test done? result?).

DriveRadar gives the batch **one feed** of drives, **filtered by eligibility**, with **Telegram reminders** before deadlines and a **personal status tracker** for each drive.

## 2. Goals and non-goals

**v1 goals**
1. One place for all drive notices, whatever the source.
2. Eligibility filter (CGPA, branch, backlogs, graduation year).
3. Deadline reminders through a Telegram bot.
4. Status tracking per drive: applied → test → interview → result.

**Not in v1** (see §12)
- Reading WhatsApp groups or email inboxes automatically.
- WhatsApp alerts.
- Company-wise history and analytics.
- A native mobile app. The web app is responsive.

## 3. Users and roles

| Role | Who | Can do |
|---|---|---|
| Student | Batch members (size TBD, §13) | Sign up, fill in profile, see the feed, track applications, link Telegram |
| Admin | Me (later maybe a class placement coordinator) | Paste or forward notices, review the parsed draft, publish, edit or close drives |

## 4. Key decision: one ingestion path for all four sources

Every notice, whatever its source, enters the same way. An admin **pastes the raw text** into an admin form, or **forwards it to the Telegram bot**. A parser pre-fills the fields, the admin checks them, then publishes.

```
TPO email ─┐
WhatsApp ──┤ copy/forward  ┌─────────┐   draft   ┌──────────────┐  publish  ┌──────┐
Portal ────┼──────────────▶│ Parser  │──────────▶│ Admin review │──────────▶│ Feed │
Telegram ──┘               └─────────┘           └──────────────┘           └──────┘
```

**Why (interview answer):**
- WhatsApp has no free, allowed API for reading group messages, so scraping it would be fragile and against its terms.
- Reading Gmail needs OAuth and per-user consent. That's too much for 10 days, and it breaks easily.
- Having a human check each notice keeps the data **correct**. A wrong deadline or eligibility rule does more harm than a slow one.
- Each drive keeps `raw_text` and `source`, so the original notice is always available to compare against.

**Parser (I write this):** a rule-based extractor using regex and keyword lists. It looks for company, role, CTC, deadline, minimum CGPA, branches, backlogs and the apply link. Each field it can't find is left empty for the admin to fill in. No LLM, so it stays ₹0 and predictable. An LLM fallback is a v2 idea.

## 5. Features (v1)

### F1. Auth and student profile
- Email + password (bcrypt hash). Access token is a JWT.
- Profile fields: name, branch, CGPA, active backlogs, graduation year.
- Eligibility depends on these fields, so the feed stays locked until the profile is complete.

### F2. Drives (admin)
- Paste notice → parser → draft → review → publish.
- Drive status: `draft` → `published` → `closed`. A drive closes automatically once its deadline passes.

### F3. Eligibility filter (I write this)
- Pure function: `check_eligibility(profile, rules) -> (eligible: bool, reasons: list[str])`.
- The feed shows eligible drives first. Ineligible drives appear greyed out with reasons, e.g. "Needs CGPA ≥ 7.5 (you: 7.2)". Nothing is hidden silently.
- An empty rule means "no restriction" (e.g. `min_cgpa = NULL`).
- Unit-tested heavily.

### F4. Application status tracking (I write the state machine)
```
INTERESTED → APPLIED → TEST → INTERVIEW → OFFER
                │        │        │
                └────────┴────────┴──→ REJECTED
Any non-final state ──→ WITHDRAWN
```
- Allowed transitions live in one dict. Any other move returns HTTP 409.
- Every change is written to `application_events`, giving each drive a timeline.

### F5. Telegram bot alerts
- **Linking:** the profile page shows a "Connect Telegram" deep link (`t.me/<bot>?start=<one-time-token>`). When the bot receives `/start <token>`, it saves that student's `chat_id`.
- **Alerts:** a new drive is published that the student is eligible for, or a deadline is 24 h away, then 3 h away. Deadline alerts are skipped if the student has already marked APPLIED or WITHDRAWN.
- **Admin bonus:** the admin can forward a notice to the bot, which creates a draft (same parser as §4).
- **Scheduling on free hosting (I write the job):** free backends go to sleep, so an in-process scheduler can't be trusted. A **GitHub Actions cron** (every 30 min) calls `POST /internal/run-reminders` with a secret header.
- **No duplicate alerts:** `notifications` has `UNIQUE(student_id, drive_id, kind)`. Insert first, send only if the insert succeeded. A retried cron run never sends the same reminder twice.

## 6. Data model (PostgreSQL)

```sql
users(
  id            uuid PK,
  email         text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role          text NOT NULL CHECK (role IN ('student','admin')),
  name          text NOT NULL,
  created_at    timestamptz DEFAULT now()
)

student_profiles(
  user_id             uuid PK REFERENCES users(id),
  branch              text NOT NULL,
  cgpa                numeric(4,2) NOT NULL,
  active_backlogs     int NOT NULL DEFAULT 0,
  grad_year           int NOT NULL,
  telegram_chat_id    bigint UNIQUE,          -- NULL until linked
  telegram_link_token text UNIQUE             -- one-time, cleared after linking
)

drives(
  id          uuid PK,
  company     text NOT NULL,
  role_title  text NOT NULL,
  ctc_text    text,
  ctc_lpa     numeric(6,2),
  location    text,
  apply_link  text,
  deadline    timestamptz NOT NULL,           -- stored in UTC, shown in IST
  source      text CHECK (source IN ('email','whatsapp','portal','telegram','other')),
  raw_text    text NOT NULL,
  status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','closed')),
  created_by  uuid REFERENCES users(id),
  created_at  timestamptz DEFAULT now()
)

drive_eligibility(
  drive_id            uuid PK REFERENCES drives(id),
  min_cgpa            numeric(4,2),           -- NULL = no limit
  allowed_branches    text[],                 -- NULL/empty = all
  max_active_backlogs int,                    -- NULL = no limit
  grad_years          int[]                   -- NULL/empty = any
)

applications(
  id          uuid PK,
  student_id  uuid REFERENCES users(id),
  drive_id    uuid REFERENCES drives(id),
  status      text NOT NULL,
  notes       text,
  updated_at  timestamptz DEFAULT now(),
  UNIQUE(student_id, drive_id)
)

application_events(
  id             uuid PK,
  application_id uuid REFERENCES applications(id),
  from_status    text,
  to_status      text NOT NULL,
  at             timestamptz DEFAULT now()
)

notifications(
  id         uuid PK,
  student_id uuid REFERENCES users(id),
  drive_id   uuid REFERENCES drives(id),
  kind       text CHECK (kind IN ('new_drive','deadline_24h','deadline_3h')),
  sent_at    timestamptz DEFAULT now(),
  UNIQUE(student_id, drive_id, kind)
)
```

Indexes: `drives(status, deadline)`, `applications(student_id)`.

## 7. Architecture

```
React + TS (Vite)  ──HTTPS/JSON──▶  FastAPI (Python 3.13)  ──▶  PostgreSQL (Neon)
  Vercel                               Render Free
                                          ▲      ▲
                         Telegram webhook ┘      └ GitHub Actions cron (every 30 min)
```

**Repo layout**
```
driveradar/
├── CLAUDE.md                 (local only)
├── docs/DESIGN.md            (pushed)
├── docs/PROGRESS.md          (local only)
├── docker-compose.yml        (local Postgres)
├── .github/workflows/ci.yml
├── backend/
│   ├── pyproject.toml, uv.lock, Dockerfile, alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py           (app factory, lifespan, routers)
│   │   ├── core/config.py    (load_config  ← I write)
│   │   ├── core/db.py        (engine, session, check_database ← I write)
│   │   ├── api/  models/  schemas/
│   │   └── services/         (eligibility, parser, state_machine, reminders ← I write)
│   └── tests/
└── frontend/                 (from M6)
```

Config comes only from env vars (`DATABASE_URL`, `JWT_SECRET`, `TELEGRAM_BOT_TOKEN`, `CRON_SECRET`). There's a `.env.example` in the repo. `.env` is never committed.

## 8. API (v1)

```
GET    /healthz                  -> process is up (no DB call)
GET    /readyz                   -> DB reachable (check_database), else 503

POST   /auth/register            POST /auth/login
GET    /me                       PUT  /me/profile
POST   /me/telegram-link         -> returns deep link

GET    /drives                   -> published drives + eligibility result per drive
GET    /drives/{id}

POST   /admin/drives/parse       -> raw_text in, draft fields out (no save)
POST   /admin/drives             -> create draft
PATCH  /admin/drives/{id}        -> edit / publish / close

PUT    /drives/{id}/application  -> create or move status (state machine)
GET    /me/applications          -> my tracker, with timeline

POST   /telegram/webhook         -> bot updates (secret token checked)
POST   /internal/run-reminders   -> cron only (CRON_SECRET header)
```

## 9. Who writes what

| I write (core logic, interview material) | Claude helps with |
|---|---|
| `load_config()` and `check_database()` (M0) | Scaffolding, config files, CI, Dockerfile |
| `check_eligibility()` | Alembic setup and models boilerplate |
| Notice parser (regex rules) | Frontend pages and components |
| Application state machine | Tests (often first) and extra test cases |
| Telegram link-token flow + reminder job with idempotency | Reviews, debugging, deployment, README |

For my pieces, Claude gives hints or pseudocode only, never the full implementation unless I say "write it for me".

## 10. Milestones (~10 days)

| M | Day | Build | Done when |
|---|---|---|---|
| **M0 Foundation** | 1 | See §10.1 | CI green, `/healthz` + `/readyz` work locally and in Docker |
| M1 Auth + profile | 2 | Register, login, JWT, profile | Register → login → update profile works, tests pass |
| M2 Drives | 3 | Models + migrations for drives/eligibility, admin CRUD | Admin can create/publish a drive |
| M3 Eligibility | 4 | **check_eligibility** + tests, `GET /drives` with reasons | Feed shows reasons, tests pass |
| M4 Parser | 5 | **Parser** + admin paste-and-review screen | Pasting a real notice pre-fills most fields |
| M5 Tracker | 6 | **State machine**, applications, events | Illegal move → 409, timeline recorded |
| M6 Frontend | 7 | Feed, drive page, my tracker | Usable end-to-end on mobile |
| M7 Telegram | 8 | Linking, new-drive alert, forward-to-draft | Publishing pings eligible students |
| M8 Reminders | 9 | **Reminder cron** + idempotency, deploy to Render/Neon/Vercel | Running cron twice sends one message |
| M9 Polish | 10 | Seed demo data, README + screenshots, demo video | Repo ready to share |

### 10.1 M0 — Foundation (Day 1)

1. Repo layout as in §7. `uv init` the backend, pin Python 3.13 (`.python-version`).
2. Tooling: ruff (lint + format), mypy (strict on `app/`), pytest. Config lives in `pyproject.toml`. Add `.gitignore`, `.gitattributes` (LF endings) and `.editorconfig`.
3. Local Postgres 17 through `docker-compose.yml`, plus `.env.example`.
4. SQLAlchemy async engine + Alembic wired up, with an empty initial migration that runs cleanly.
5. Settings: **`load_config()`** (I write it) reads env vars through pydantic-settings, validates them, and **fails fast at startup** with a clear message when something is missing or invalid.
6. `/healthz` (process up) and `/readyz`, which uses **`check_database()`** (I write it): a `SELECT 1` with a short timeout, returning 503 if the DB can't be reached.
7. Graceful shutdown through the FastAPI lifespan, which disposes of the DB engine.
8. GitHub Actions CI: ruff, mypy and pytest against a Postgres service container.
9. Backend `Dockerfile` (slim image, non-root user, uv for installing).
10. Check that every dependency installs and runs on Python 3.13 on Windows.
11. Side task: sign up for Render, Neon and Vercel. **If any asks for a card, stop** and we pick another option.

Tests for `load_config` and `check_database` are written **first**. I implement until they pass.

## 11. Interview talking points

1. **Ingestion trade-off:** human-checked pasting instead of scraping WhatsApp and Gmail (terms of service, fragility, correctness).
2. **Eligibility as a pure function:** easy to test, returns reasons rather than a bare yes/no.
3. **State machine:** explicit allowed transitions, an audit trail, 409 on invalid moves.
4. **Reliable reminders on free hosting:** external cron + a DB unique constraint gives exactly-once alerts. This is idempotency in practice.
5. **Fail-fast config + health vs readiness:** why `/healthz` and `/readyz` are separate endpoints.
6. **Time zones:** store UTC, show IST.
7. **Cost:** the whole system runs at ₹0/month, and I can explain what changes at 10× the users.

## 12. v2 backlog

- WhatsApp alerts (check the WhatsApp Business Cloud API's current pricing and template-approval rules first).
- Company-wise history: past drives, packages, rounds, offers.
- Email ingestion through a forwarding address.
- LLM fallback for fields the parser can't extract.
- Calendar export (.ics) for deadlines.
- Placement stats dashboard.

## 13. Open questions

1. Frontend: confirm React + TypeScript + Vite (assumed; needed by M6).
2. Batch size (for the README).
3. Exact branch codes used by my college (needed by M2/M4).
