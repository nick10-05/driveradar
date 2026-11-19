# DriveRadar — Design Doc (v2.2)

Placement-notice tracker for my college batch, with AI-assisted notice extraction. Portfolio project, 10-day roadmap, ₹0/month.
Status: **v2.2, decisions locked** (2026-11-18). Change decisions here first, then in code.

---

## Changelog

### v2.2 notes (Day 5, 2026-11-19)
- §5 F4: `applied → interview` allowed (no test round); only `interested`/`applied` can start tracking; same status = notes-only update, no event. §6: `applications.created_at`, FKs `ON DELETE CASCADE`, `application_events.at DEFAULT clock_timestamp()` (`now()` is frozen per transaction, so two moves in one transaction would tie). §4.9: synthetic notices (labelled `synthetic`) until real ones exist; each notice has an `as_of` date; the eval CLI reads only `LLM_*` (`LlmSettings`) + `DATABASE_URL` and writes no `extraction_runs` rows.

### v2.2 notes (Day 4, 2026-11-19)
- §4.5: "all branches" = no restriction; all-unknown branches flagged as widening. §4.6: partial output only after the one retry; extractor exceptions caught. §6: `extraction_runs.error` (short code); `drives.extraction_run_id ON DELETE SET NULL`. Extraction limit: 30 per hour per admin; `/extract` always returns 200 with a (possibly empty) draft.

### v2.2 notes (Day 3, 2026-11-19)
- §5 F2: allowed drive status changes written down. §6: `drives.created_by` is `ON DELETE SET NULL`; `extraction_run_id` arrives with `extraction_runs` on Day 4. §8: `GET /admin/drives` (+ `/{id}`) added for the admin review screen; feed is 409 until the profile is saved.

### v2.2 (2026-11-18)
- **Roadmap:** milestones M0–M9 are replaced by a **10-day roadmap (Day 1–Day 10)** (§10). A "Day" is a unit of work, not a calendar date. It can take several sittings, and the real dates go in PROGRESS.md.
- **Compression:** drives + eligibility are one day (Day 3), and evals + tracker are one day (Day 5). All major features stay.
- **Schedule rule:** tests, security, AI evidence validation and the deterministic eligibility boundary are never cut to meet the schedule. If a day slips, Day 10 polish gets cut first.
- **Docker fallback:** if local Docker can't be fixed in reasonable time, Postgres 17 in GitHub Actions is the verified integration environment, and local development uses the alternative in §10.2.
- Telegram forward-to-draft stays in the v2 backlog.

### v2.1 (2026-11-18)
- **D2:** development runs in **WSL2 Ubuntu**. Windows Smart App Control blocks the unsigned executables and compiled extensions inside native Python venvs, so native Windows Python is unreliable. WSL also matches CI, Docker and Render (all Linux).
- **Stack:** SQLAlchemy **2.1** (the same 2.0-style API). FastAPI is installed with the `standard-no-fastapi-cloud-cli` extra, which keeps the cloud CLI and sentry-sdk out of the dependencies.

### v2.0 (2026-11-18)
- **AI extraction replaces the regex parser.** An LLM turns notice text into a typed draft through structured output. Pydantic validates it, a deterministic normaliser cleans it up and checks its evidence, and an admin approves it before it's published (§4).
- **Provider-independent LLM, ₹0 by default.** No paid provider or model is built into the architecture. The provider and model are set with env vars (`LLM_PROVIDER`, `LLM_MODEL`, …). The default `none` means manual entry (D10, §4.3).
- **AI boundary is explicit.** The LLM only extracts. Python validates, normalises and decides eligibility. A human approves every drive (D9).
- **Evaluation harness.** A golden set of real notices plus a script that reports per-field accuracy (§4.9).
- **Auth:** opaque DB sessions in a `__Host-session` cookie, a same-origin Vercel proxy and Origin validation. These replace the JWT (D11, §7.3).
- **Passwords:** pwdlib + Argon2. passlib relies on the `crypt` module, which was removed in Python 3.13.
- **Registration:** requires a batch invite code.
- **Branches:** a normalised `branches` lookup, plus `branch_aliases` and a `drive_allowed_branches` join table. These replace the `text[]` column.
- **Drive closure:** `closed` is a manual admin action only. "Expired" is computed from the deadline, never stored.
- **Neon + asyncpg:** use the direct (non-pooler) endpoint, normalise the URL's SSL params, and use pre-ping (§7.4).
- **Engineering:** frontend TS types generated from OpenAPI, httpx for the Telegram Bot API, login rate limiting, structured logs + request IDs, coverage reporting, pre-commit.
- **Process:** a walking-skeleton deploy at M1. Telegram forward-to-draft becomes a stretch goal. Timeline is now 14 days.
- **Ownership (D8):** Claude implements all components and explains the logic, trade-offs and tests so I can defend them.
- **Removed:** JWT / `JWT_SECRET`, the regex parser, storing auto-closed status, and the "LLM fallback" v2 item (AI is now core).

### v1.1 (2026-11-18)
- First locked design.

---

## 0. Finalized decisions

| # | Decision |
|---|---|
| **D1 Runtime** | Python 3.13 + FastAPI, with **uv** managing Python, dependencies and the lockfile. If a dependency breaks on 3.13, flag it. Don't switch versions silently. |
| **D2 Dev setup** | Windows 11 host, with Python tooling running in **WSL2 Ubuntu** (uv, tests, dev server, Docker CLI, and **git**, so the pre-commit hook can use the Linux venv). The repo lives at `C:\Users\NICK\driveradar` (`/mnt/c/...` in WSL). The venv lives on the Linux filesystem (`UV_PROJECT_ENVIRONMENT=~/.venvs/driveradar-backend`). VS Code + Claude Code. GitHub repo named `driveradar`. |
| **D3 Cost: ₹0, no payment card** | Applies to **everything**, the LLM included. Backend: Render Free. DB: Neon Postgres free. Frontend: Vercel Hobby. LLM: only a free tier that needs no card, a local model, or none. If any signup asks for a card, stop and pick another option. |
| **D4 Ingestion** | Every source (TPO email, WhatsApp, portal, Telegram) goes through one path: paste (or forward to the bot) → AI extraction → validation + normalisation → admin review → publish. No scraping. (§4) |
| **D5 Alerts** | Telegram bot in v1. WhatsApp alerts in v2. |
| **D6 v1 scope** | AI-assisted extraction with an evaluation harness, eligibility filter, deadline reminders, application status tracking. Company history moves to v2. |
| **D7 Users** | The whole batch, with logins, gated by a batch invite code. Roles: student and admin. |
| **D8 Way of working** | Claude implements all components and explains the important logic, alternatives, trade-offs and tests. I review everything and must be able to defend each part. Tests are written alongside or before the code. (§9) |
| **D9 AI boundary** | The LLM **only extracts** fields from notice text. It never decides eligibility, never publishes, never sees student data, and has no tools. Deterministic Python validates and normalises its output, and a human approves every drive. |
| **D10 LLM provider** | Provider-independent behind an `Extractor` interface, chosen by env vars. Default `LLM_PROVIDER=none` → manual entry. Any extractor failure falls back to manual entry. No paid provider or model is hardcoded. (§4.3) |
| **D11 Auth** | Opaque, DB-backed sessions in a `__Host-session` cookie (HttpOnly, Secure, SameSite=Lax). The frontend reaches the API through a same-origin Vercel proxy. Unsafe methods require a valid `Origin`. (§7.3) |

**Locked stack:** Python 3.13, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2.1 (async) + asyncpg, Alembic, PostgreSQL 17, pwdlib[argon2], httpx, structlog, pytest + pytest-cov + httpx + respx, ruff (lint + format), mypy, pre-commit, Docker Compose (local DB), GitHub Actions CI. Frontend: React + TypeScript + Vite, openapi-typescript + openapi-fetch, TanStack Query, React Router.

**Deliberately excluded:** Redis, Celery or any task queue, LangChain or other LLM frameworks, vector databases / RAG, agents, refresh tokens, microservices, vendor LLM SDKs in the core. Each solves a problem this project doesn't have.

---

## 1. Problem

Placement notices reach the batch from four places: TPO emails, WhatsApp group forwards, the college portal, and Telegram or other channels. Because of this, students:
- miss registration deadlines,
- waste time reading drives they aren't eligible for,
- lose track of where they stand in each drive (applied? test done? result?).

The notices themselves are messy, unstructured text, so getting them into a usable form is slow, manual work for whoever posts them.

DriveRadar gives the batch **one feed** of drives, **filtered by eligibility**, with **Telegram reminders** before deadlines and a **personal status tracker** for each drive. **AI-assisted extraction** turns a pasted notice into a reviewed, structured drive in seconds.

## 2. Goals and non-goals

**v1 goals**
1. One place for all drive notices, whatever the source.
2. AI-assisted extraction of notice fields, with measured accuracy and human review.
3. Eligibility filter (CGPA, branch, backlogs, graduation year), done by deterministic code.
4. Deadline reminders through a Telegram bot.
5. Status tracking per drive: applied → test → interview → result.

**Not in v1** (see §12)
- Reading WhatsApp groups or email inboxes automatically.
- An LLM deciding eligibility, or publishing anything without a human.
- Agents, RAG, chat interfaces.
- WhatsApp alerts.
- Company-wise history and analytics.
- A native mobile app. The web app is responsive.

## 3. Users and roles

| Role | Who | Can do |
|---|---|---|
| Student | Batch members with the invite code (size TBD, §13) | Sign up, fill in profile, see the feed, track applications, link Telegram |
| Admin | Me (later maybe a class placement coordinator) | Paste or forward notices, review the extracted draft, publish, edit or close drives |

Admins are created by promoting a user directly in the DB or through a seed script. There's no self-service admin signup.

## 4. Ingestion and AI extraction

### 4.1 One path for all four sources

```
TPO email ─┐
WhatsApp ──┤ paste /      ┌───────────┐  JSON   ┌──────────┐  draft +   ┌──────────────┐ publish ┌──────┐
Portal ────┼─ forward ───▶│ Extractor │───────▶│ Pydantic │──warnings─▶│ Admin review │────────▶│ Feed │
Telegram ──┘              │ (LLM or   │        │ + Python │            └──────────────┘         └──────┘
                          │  none)    │        │normaliser│
                          └───────────┘        └──────────┘
```

**Why one human-reviewed path (interview answer):**
- WhatsApp has no free, allowed API for reading group messages, so scraping it would be fragile and against its terms.
- Reading Gmail needs OAuth and per-user consent. That's too much for this timeline, and it breaks easily.
- Having a human check each notice keeps the data **correct**. A wrong deadline or eligibility rule does more harm than a slow one.
- Each drive keeps `raw_text` and `source`, so the original notice is always available to compare against.

### 4.2 The AI boundary (D9)

> **The LLM only reads notices. Python makes every decision.**

| Step | Done by | Trusted? |
|---|---|---|
| Read the text, propose field values + evidence quotes | LLM | No: treated like user input |
| Check types, ranges and required shape | Pydantic | Yes |
| Convert dates to UTC, map branches to codes, verify evidence, sanity checks | Python normaliser | Yes |
| Approve, correct, publish | Admin | Yes |
| Decide eligibility | `check_eligibility()` over reviewed DB rows | Yes |

### 4.3 Extractor interface and providers (D10)

```python
class Extractor(Protocol):
    async def extract(self, raw_text: str) -> ExtractionResult: ...
```

| `LLM_PROVIDER` | Implementation | Use |
|---|---|---|
| `none` (default) | `ManualExtractor`: returns an empty draft, status `disabled` | Production when no free API is available. The app is fully usable. |
| `openai_compatible` | `HttpJsonExtractor`: one `POST {LLM_BASE_URL}/chat/completions` through **httpx**, with a JSON-schema response format built from `ExtractedNotice.model_json_schema()` | Any provider or local server that speaks this widely used HTTP shape: a free-tier hosted API (no card, D3) or a local model server (e.g. Ollama) for ₹0 development and evals |
| (tests) | `FakeExtractor`: canned responses | Unit tests and CI. **CI never calls a real LLM.** |

- Config: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY` (optional), `LLM_MODEL`, `LLM_JSON_MODE` (`schema` | `object`, for providers without JSON-schema support), `LLM_TIMEOUT_SECONDS`.
- No vendor SDK in the core. Adding a provider means adding one adapter class, without touching the pipeline. A vendor-specific adapter can be added later if the budget ever allows (§12).
- The prompt lives in `services/extraction/prompt.py` with a `PROMPT_VERSION` constant that is recorded on every run.

### 4.4 Output schema

`ExtractedNotice` (Pydantic). **Every field is nullable.** The prompt says: "Use null if the notice doesn't state it. Never guess."

| Field | Type | Notes |
|---|---|---|
| `company`, `role_title` | `str \| None` | |
| `ctc_text` | `str \| None` | Verbatim, e.g. "6–8 LPA + bonus" |
| `ctc_lpa` | `float \| None` | Lower bound in LPA, if a number is stated |
| `location`, `apply_link` | `str \| None` | `apply_link` must be http(s) |
| `deadline_text` | `str \| None` | Verbatim |
| `deadline_local` | `str \| None` | ISO-8601 datetime as the model reads it. Timezone optional |
| `min_cgpa` | `float \| None` | |
| `branches_raw` | `list[str] \| None` | As written ("CSE", "IT", "ECE") |
| `max_active_backlogs` | `int \| None` | |
| `grad_years` | `list[int] \| None` | |
| `evidence` | `dict[field, str]` | Short verbatim quote supporting each non-null key field |

### 4.5 Normaliser and evidence check (deterministic Python)

Pure functions, unit-tested heavily. Input: validated `ExtractedNotice` + `raw_text`. Output: `DraftDrive` + `issues: list[FieldIssue]`, which the review UI shows next to each field.

1. **Evidence check:** each non-null key field (company, deadline, min_cgpa, branches, backlogs, grad_years, ctc) must have an evidence quote that appears in `raw_text`, after normalising whitespace and case. If it doesn't, the field gets a `verify` flag. This is a cheap guard against hallucinated values.
2. **Deadline:** parse `deadline_local`. If there's no timezone, assume **IST**. Convert to **UTC**. A deadline in the past or more than a year ahead gets flagged.
3. **Branches:** map each `branches_raw` entry through `branch_aliases` to a branch code. Unknown names get flagged and are never silently dropped. "All branches" / "any branch" means no restriction. If **no** name can be mapped, the flag says so explicitly: an empty list would mean "all branches" and silently widen the drive.
4. **Sanity checks:** CGPA between 0 and 10, backlogs ≥ 0, grad years within ±2 years of now, `ctc_lpa` in a plausible range, `apply_link` is http(s).
5. **Pass-through:** fields that fail validation are set to null + flagged. A bad field never blocks the rest of the draft.

### 4.6 Failure handling and manual fallback

| Situation | Result |
|---|---|
| `LLM_PROVIDER=none` | Empty draft, status `disabled` |
| Timeout, network error, HTTP 4xx/5xx, rate limit (429) | Empty draft, status `error` |
| Output isn't valid JSON or fails Pydantic | **One** retry with the validation error included in the request. If that fails too, empty draft, status `invalid` |
| Partially valid output | Same one retry first. If the retry is a JSON object with some wrongly-typed fields: valid fields kept, the rest null + flagged |
| Unexpected exception inside an extractor | Caught by the pipeline: empty draft, status `error` (`error = 'unexpected'`) |

In every case the admin can still enter a drive manually in the same form. **AI speeds up the workflow. It is never a single point of failure.**

### 4.7 Safety and cost controls

- **Prompt injection:** notice text is untrusted. The model has no tools and no actions, its output is constrained to a schema and validated, and a human approves every draft. A malicious notice can at worst produce a wrong draft that the admin then sees.
- **No student data goes to the LLM.** Only notice text, which is meant for the whole batch anyway. That matters because free tiers may keep or train on inputs.
- **Limits:** `raw_text` ≤ 8,000 characters; extraction endpoint is admin-only and rate-limited, which also protects free-tier quotas; httpx timeout from config.

### 4.8 Audit: `extraction_runs`

Every extraction attempt is stored: provider, model, prompt version, status, output JSON, issues, latency, token counts if the provider returns them. A published drive links to the run it came from. Comparing the run output with the final published fields gives the **per-field admin edit rate**, a live accuracy metric.

### 4.9 Evaluation harness

- `backend/evals/golden/`: 20–30 real notices, anonymised (personal names, phone numbers and emails removed), each with hand-labelled expected fields.
- `uv run python -m evals.run`: runs the configured extractor + normaliser over the golden set and prints per-field metrics:
  - exact match for scalars after normalisation (deadline compared as a UTC datetime),
  - precision/recall for branch sets,
  - **abstention accuracy**: returned null when the notice really doesn't say,
  - evidence-check pass rate, invalid-output rate, mean latency.
- Results are saved to `evals/results/<date>-<provider>-<model>-<prompt_version>.md` and summarised in the README.
- Run by hand (₹0 with a local model or free tier). CI runs the harness against `FakeExtractor` only, to test the harness code itself.
- Baseline row: `none` (manual entry, nothing pre-filled), so the README can show what AI adds.
- Until real notices arrive, the set holds hand-written `synthetic-*.json` notices (`"synthetic": true`), each targeting one rule (percentage instead of CGPA, "all branches", unknown branch, explicit timezone, no deadline, prompt-injection line). Reports state the synthetic/real count and never present synthetic scores as real accuracy.
- Each notice has an `as_of` date used as "today" (prompt) and `now` (normaliser), so re-runs give the same expectations.
- Field outcomes: correct / missed / wrong (stated in the notice) and abstained / hallucinated (not stated). Headline numbers: stated-field accuracy and hallucination rate, reported separately.
- The CLI loads only `LlmSettings` (the `LLM_*` variables) and `DATABASE_URL` (for real branch aliases). It calls the extractor + normaliser directly and writes no `extraction_runs` rows.

## 5. Features (v1)

### F1. Auth and student profile
- Register with email, password, name and the **batch invite code** (`BATCH_INVITE_CODE`, compared in constant time).
- Passwords hashed with **Argon2** through pwdlib.
- Login creates an **opaque session** (§7.3). Logout deletes it.
- **Login rate limit** keyed by email and by IP (§7.5).
- Profile fields: name, branch (code from `branches`), CGPA, active backlogs, graduation year.
- Eligibility depends on these fields, so the feed stays locked until the profile is complete.

### F2. Drives (admin)
- Paste notice → extract → draft + flagged fields → review/correct → save draft → publish.
- Stored `status`: `draft` → `published` → `closed`. **`closed` is set only by an admin** (cancelled, filled, withdrawn).
- Allowed status changes (Day 3): draft → published (only with a future deadline, else 422), published → closed (sets `closed_at`). Anything else is 409. A closed drive is final and read-only. Create always makes a draft.
- **Expired is computed, never stored:** `status = 'published' AND deadline <= now()`. Extending a deadline reopens a drive automatically, and there's no closing job to fail or run late.
- Feed and reminders show only open drives (`published` and deadline in the future). Expired drives stay visible in the tracker history.

### F3. Eligibility filter (deterministic)
- Pure function: `check_eligibility(profile, rules) -> (eligible: bool, reasons: list[str])`.
- Branch rules compare **branch codes**, never free text.
- The feed shows eligible drives first. Ineligible drives appear greyed out with reasons, e.g. "Needs CGPA ≥ 7.5 (you: 7.2)". Nothing is hidden silently.
- An empty rule means "no restriction" (e.g. `min_cgpa = NULL`, no rows in `drive_allowed_branches`).
- Unit-tested heavily, including boundary values (CGPA exactly at the minimum).

### F4. Application status tracking (state machine)
```
INTERESTED → APPLIED → (TEST →) INTERVIEW → OFFER
                │        │          │
                └────────┴──────────┴──→ REJECTED
Any non-final state ──→ WITHDRAWN
```
- Allowed transitions live in one dict. Any other move returns HTTP 409. `APPLIED → INTERVIEW` skips the test (many drives have none). Tracking starts at INTERESTED or APPLIED. OFFER, REJECTED, WITHDRAWN are final.
- Only published drives can be tracked (a draft is 404). Same status again = notes update, no event. Concurrent first clicks are safe: `INSERT … ON CONFLICT DO NOTHING`, then the row is locked `FOR UPDATE`.
- Every change is written to `application_events`, giving each drive a timeline.

### F5. Telegram bot alerts
- **Transport:** plain **httpx** calls to the Bot API (`sendMessage`, webhook). One shared `AsyncClient` created in the lifespan, with timeouts. A 429 is handled using Telegram's `retry_after`. Tests mock it with respx. No bot framework.
- **Linking:** the profile page shows a "Connect Telegram" deep link (`t.me/<bot>?start=<token>`). The token is random, **stored hashed**, single-use and expires after 15 minutes. When the bot receives `/start <token>`, it saves that student's `chat_id` and clears the token.
- **Webhook security:** Telegram's `X-Telegram-Bot-Api-Secret-Token` header must match `TELEGRAM_WEBHOOK_SECRET`.
- **Alerts:** a new drive is published that the student is eligible for, or a deadline is 24 h away, then 3 h away. Deadline alerts are skipped if the student has already marked APPLIED or WITHDRAWN.
- **Scheduling on free hosting:** free backends go to sleep, so an in-process scheduler can't be trusted. A **GitHub Actions cron** (every 30 min) calls `POST /internal/run-reminders` with a secret header. Cron runs can be late, so the job selects deadlines **inside a time window** ("due within the next 24 h and not yet sent"), never at an exact time. The same job deletes expired sessions.
- **No duplicate alerts:** `notifications` has `UNIQUE(student_id, drive_id, kind)`. Insert first, send only if the insert succeeded. A retried cron run never sends the same reminder twice.
- **v2 (§12):** the admin forwards a notice to the bot, and the same extraction pipeline (§4) creates a draft in a background task.

## 6. Data model (PostgreSQL)

```sql
users(
  id            uuid PK,
  email         text UNIQUE NOT NULL,          -- stored lower-cased, CHECK (email = lower(email))
  password_hash text NOT NULL,                 -- Argon2 (pwdlib)
  role          text NOT NULL CHECK (role IN ('student','admin')),
  name          text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
)

sessions(
  id          uuid PK,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  text UNIQUE NOT NULL,            -- SHA-256 of the cookie token
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL
)

branches(
  code  text PK,                               -- e.g. 'CSE'
  name  text NOT NULL                          -- e.g. 'Computer Science and Engineering'
)

branch_aliases(
  alias        text PK,                        -- lower-cased, e.g. 'cs', 'computer science'
  branch_code  text NOT NULL REFERENCES branches(code)
)

student_profiles(
  user_id                  uuid PK REFERENCES users(id) ON DELETE CASCADE,
  branch_code              text NOT NULL REFERENCES branches(code),
  cgpa                     numeric(4,2) NOT NULL CHECK (cgpa BETWEEN 0 AND 10),
  active_backlogs          int NOT NULL DEFAULT 0 CHECK (active_backlogs >= 0),
  grad_year                int NOT NULL,
  telegram_chat_id         bigint UNIQUE,      -- NULL until linked
  telegram_link_token_hash text UNIQUE,        -- one-time, cleared after linking
  telegram_link_expires_at timestamptz
)

extraction_runs(
  id              uuid PK,
  created_by      uuid REFERENCES users(id),
  raw_text        text NOT NULL,
  provider        text NOT NULL,               -- 'none', 'openai_compatible', ...
  model           text,                        -- NULL when provider = 'none'
  prompt_version  text NOT NULL,
  status          text NOT NULL CHECK (status IN ('ok','invalid','error','disabled')),
  error           text,                        -- short code: 'timeout', 'http_429', 'invalid_output', ...
  output_json     jsonb,                       -- normalised draft
  issues          jsonb NOT NULL DEFAULT '[]', -- per-field flags
  latency_ms      int,
  input_tokens    int,                         -- NULL if provider doesn't report
  output_tokens   int,
  created_at      timestamptz NOT NULL DEFAULT now()
)

drives(
  id                 uuid PK,
  company            text NOT NULL,
  role_title         text NOT NULL,
  ctc_text           text,
  ctc_lpa            numeric(6,2),
  location           text,
  apply_link         text,
  deadline           timestamptz NOT NULL,     -- stored in UTC, shown in IST
  source             text CHECK (source IN ('email','whatsapp','portal','telegram','other')),
  raw_text           text NOT NULL,
  status             text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','closed')),
  closed_at          timestamptz,              -- set only by a manual close
  extraction_run_id  uuid REFERENCES extraction_runs(id) ON DELETE SET NULL,  -- NULL = manual entry
  created_by         uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
)

drive_eligibility(
  drive_id            uuid PK REFERENCES drives(id) ON DELETE CASCADE,
  min_cgpa            numeric(4,2),            -- NULL = no limit
  max_active_backlogs int,                     -- NULL = no limit
  grad_years          int[]                    -- NULL/empty = any
)

drive_allowed_branches(                        -- no rows = all branches
  drive_id     uuid REFERENCES drives(id) ON DELETE CASCADE,
  branch_code  text REFERENCES branches(code),
  PRIMARY KEY (drive_id, branch_code)
)

applications(
  id          uuid PK,
  student_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  drive_id    uuid NOT NULL REFERENCES drives(id) ON DELETE CASCADE,
  status      text NOT NULL CHECK (status IN (...F4 statuses...)),
  notes       text,                          -- ≤ 2000 chars (API)
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE(student_id, drive_id)
)

application_events(
  id             uuid PK,
  application_id uuid NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  from_status    text,                       -- NULL = tracking started
  to_status      text NOT NULL,
  at             timestamptz NOT NULL DEFAULT clock_timestamp()
)

notifications(
  id         uuid PK,
  student_id uuid NOT NULL REFERENCES users(id),
  drive_id   uuid NOT NULL REFERENCES drives(id),
  kind       text NOT NULL CHECK (kind IN ('new_drive','deadline_24h','deadline_3h')),
  sent_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE(student_id, drive_id, kind)
)
```

Indexes: `drives(status, deadline)`, `applications(student_id)`, `sessions(user_id)`, `sessions(expires_at)`.

**Why a join table for branches:** Postgres arrays can't have foreign keys, so a `text[]` of branch codes could hold typos or deleted codes. `grad_years` stays an array because there's nothing for it to reference.

## 7. Architecture

```
Browser ──HTTPS──▶ Vercel (React + TS)
                     │  /api/*  same-origin rewrite
                     ▼
                  Render Free: FastAPI (Python 3.13) ──▶ Neon Postgres (direct endpoint)
                     ▲      ▲                    │
    Telegram webhook ┘      └ GitHub Actions     └─▶ LLM provider (optional, free / local / none)
                              cron (30 min)
```

### 7.1 Repo layout
```
driveradar/
├── CLAUDE.md                 (local only)
├── docs/DESIGN.md            (pushed)
├── docs/PROGRESS.md          (local only)
├── docker-compose.yml        (local Postgres)
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml, reminders.yml
├── backend/
│   ├── pyproject.toml, uv.lock, Dockerfile, alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py           (app factory, lifespan, routers, middleware)
│   │   ├── core/             (config, db, logging, security, rate_limit)
│   │   ├── api/  models/  schemas/
│   │   ├── services/
│   │   │   ├── extraction/   (schema, prompt, extractors, normaliser, evidence)
│   │   │   ├── eligibility.py, state_machine.py, reminders.py, telegram.py
│   │   └── scripts/          (export_openapi, seed)
│   ├── evals/                (golden/, results/, run.py)
│   └── tests/
└── frontend/                 (from Day 6; vercel.json holds the /api rewrite)
```

### 7.2 Configuration

Config comes only from env vars, loaded and validated once at startup by `load_config()` (pydantic-settings). Startup **fails fast** with a clear message if anything is missing or invalid. There's a `.env.example` in the repo. `.env` is never committed.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Normalised for asyncpg (§7.4) |
| `ENVIRONMENT` | yes | `dev` / `test` / `prod`. Controls cookie flags and log format |
| `ALLOWED_ORIGINS` | yes | Comma-separated, used for Origin validation |
| `BATCH_INVITE_CODE` | yes | |
| `SESSION_TTL_HOURS` | no (default 168) | |
| `SESSION_COOKIE_SECURE` | no (default `true`) | `false` only allowed in `dev`; the cookie is then named `session` instead of `__Host-session` (§7.3) |
| `CRON_SECRET` | yes | Header for `/internal/run-reminders` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | from Day 8 | |
| `LLM_PROVIDER` | no (default `none`) | `none` \| `openai_compatible` |
| `LLM_BASE_URL`, `LLM_MODEL` | if provider ≠ `none` | |
| `LLM_API_KEY` | optional | Some local servers need none |
| `LLM_JSON_MODE`, `LLM_TIMEOUT_SECONDS` | no | Defaults `schema`, 30 |
| `LOG_LEVEL` | no | Default `INFO` |

### 7.3 Authentication and CSRF (D11)

- **Same-origin proxy:** `*.vercel.app` and `*.onrender.com` are different sites, so a cookie from Render would be a third-party cookie, which Safari and Firefox block by default. A Vercel rewrite sends `/api/:path*` to the Render backend, so the browser only ever talks to the frontend's origin. In local dev, the Vite dev server proxies `/api` the same way. **No CORS configuration is needed.**
- **Sessions:** on login, generate a 256-bit random token (`secrets.token_urlsafe(32)`), send it in the cookie, and store only its **SHA-256 hash** with an expiry. A fast hash is enough because the token is long and random, unlike a password. Each request looks up the hash. Logout deletes the row, and "log out everywhere" deletes all of a user's rows.
- **Cookie:** `__Host-session`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no `Domain`. The `__Host-` prefix makes the browser enforce `Secure`, `Path=/` and no `Domain`. In `ENVIRONMENT=dev` over plain http, the name and `Secure` flag are configurable in case a browser refuses Secure cookies on `localhost`.
- **CSRF:** `SameSite=Lax` blocks cross-site POST/PUT/PATCH/DELETE. As a second layer, any unsafe method must carry an `Origin` header listed in `ALLOWED_ORIGINS`, otherwise 403. A missing `Origin` is rejected too (fail closed), and login/register are covered (blocks login CSRF). GET handlers never change state. The Telegram webhook and cron endpoint aren't cookie-authenticated (they use secret headers), so the Origin rule doesn't apply to them.
- **Why not a JWT:** the API serves one first-party frontend on the same origin, so a stateless token adds nothing and makes revocation hard. The cost of DB sessions is one indexed lookup per request.

### 7.4 Database connection (Neon + asyncpg)

- Use Neon's **direct** host, not the `-pooler` one. PgBouncer in transaction mode conflicts with asyncpg's prepared-statement cache.
- Neon URLs include `sslmode=require&channel_binding=require`. asyncpg accepts neither as URL parameters. `load_config()` rewrites the scheme to `postgresql+asyncpg://`, removes those params, and the engine passes `ssl` in `connect_args`.
- Small pool (`pool_size≈5`), `pool_pre_ping=True` and a short `pool_recycle`, because Neon suspends idle compute and drops connections.
- `check_database()` runs `SELECT 1` with a short timeout for `/readyz`.
- Alembic uses the same normalised URL. The container start command runs `alembic upgrade head` before starting the server, so every deploy migrates first.

### 7.5 Operational practices

- **Logging:** structlog. JSON in prod, readable console output in dev. Passwords, cookies, tokens, API keys and `Authorization` headers are redacted. Raw notice text isn't logged at INFO.
- **Request IDs:** middleware accepts an incoming `X-Request-ID` (if it's well-formed) or generates one, binds it to every log line through contextvars, and returns it in the response.
- **Rate limiting:** a small in-memory sliding-window limiter. Login: 5 failed attempts per 15 min per email, plus 30 per 15 min per IP. Register: 10 wrong invite codes per hour per IP. Attempts are counted before the password check (parallel requests can't slip through) and successes are un-counted (a class sharing one Wi-Fi IP isn't blocked). Extraction: per-admin limit. The client IP comes from `X-Forwarded-For` behind the proxies, which can be faked, so email is the primary key. **Known limitation:** state is per process and resets on restart. That's acceptable for one Render instance. Redis would be the fix at scale.
- **Graceful shutdown:** the FastAPI lifespan closes the httpx clients and disposes of the DB engine.
- **Health vs readiness:** `/healthz` = the process is up (no DB call). `/readyz` = the DB is reachable, otherwise 503.

### 7.6 Quality gates

- **pre-commit:** ruff (lint), ruff-format, trailing whitespace / end-of-file, check-yaml, detect-private-key. mypy runs in CI only, because it's too slow for every commit.
- **CI (GitHub Actions):** ruff, ruff format --check, mypy (strict on `app/`), pytest with **pytest-cov** against a Postgres 17 service container. Coverage minimum 80% overall, 90% on `services/`. OpenAPI drift check: the exported `openapi.json` must match the committed one. LLM calls are always faked. Migrations are checked from an empty database (`upgrade head` → `downgrade base` → `upgrade head`), plus `alembic check` for model/migration drift. A separate job runs every pre-commit hook. Third-party actions are pinned to full commit SHAs (a tag can be moved; a SHA can't), with a read-only token, and Dependabot proposes weekly updates for actions and Python dependencies.
- **Frontend types:** `uv run python -m app.scripts.export_openapi` writes `openapi.json` without a running server. `openapi-typescript` generates TS types from it, and `openapi-fetch` gives a typed client. An API change that breaks the frontend fails the type check.

## 8. API (v1)

Browser calls go through `/api/*` on the frontend origin (Vercel strips the `/api` prefix). The webhook and cron call Render directly.

```
GET    /healthz                  -> process is up (no DB call)
GET    /readyz                   -> DB reachable (check_database), else 503

POST   /auth/register            -> email, password, name, invite_code
POST   /auth/login               -> sets __Host-session (rate-limited)
POST   /auth/logout              -> deletes the session
GET    /me                       PUT  /me/profile
POST   /me/telegram-link         -> returns deep link (15-min one-time token)
GET    /branches                 -> branch codes + names

GET    /drives                   -> open drives + eligibility result per drive (409 until profile saved)
GET    /drives/{id}              -> published or closed drive + notice text (drafts: 404)

POST   /admin/drives/extract     -> raw_text in; draft fields + per-field issues + extraction_run_id out (no drive saved)
GET    /admin/drives             -> every drive, drafts included (for the review screen)
GET    /admin/drives/{id}
POST   /admin/drives             -> create draft (optionally linked to an extraction run)
PATCH  /admin/drives/{id}        -> edit / publish / close (only the fields sent change)

PUT    /drives/{id}/application  -> create or move status (state machine)
GET    /me/applications          -> my tracker, with timeline

POST   /telegram/webhook         -> bot updates (secret-token header checked)
POST   /internal/run-reminders   -> cron only (CRON_SECRET header)
```

## 9. Who writes what

Claude implements all components (D8). For every important piece, Claude also explains the logic, the alternatives considered, the trade-offs and the tests, and asks "explain it back" questions at the end of each day so I can defend it in interviews.

| Piece | Interview focus |
|---|---|
| `load_config()`, `check_database()` | Fail-fast config, Neon URL normalisation, health vs readiness |
| Auth: sessions, Argon2, invite code, Origin check, rate limit | Cookie security, CSRF, why not JWT |
| Extraction: schema, prompt, extractors, normaliser, evidence check | AI boundary, structured output, hallucination guards, fallback |
| Evaluation harness | Measuring an LLM feature, metrics choice |
| `check_eligibility()` | Pure functions, reasons over booleans, boundary tests |
| State machine | Explicit transitions, audit trail, 409 |
| Telegram link flow, reminder job | One-time tokens, idempotency via unique constraint |
| Frontend, CI, Docker, deploy | Typed API contract, same-origin proxy, ₹0 hosting |

## 10. 10-day roadmap

**Rules**
- A **Day** is a unit of work, not a calendar date. A day can take several sittings, and PROGRESS.md records the real dates.
- A day is finished only when **every** "done when" check is verified. Then the next day starts.
- Never cut to meet the schedule: tests, security, AI evidence validation, the deterministic eligibility boundary. If a day slips, Day 10 polish items get cut first.
- Each day ends with 3–5 "explain it back" questions and a PROGRESS.md entry.
- Commit messages stay conventional (`feat:`, `chore:` …) and name the day in the body, e.g. `Day 3`.

| Day | Focus | Build | Done when |
|---|---|---|---|
| **1** | Foundation | See §10.1 | All §10.1 checks verified: CI green incl. Postgres 17 integration tests; `/healthz` + `/readyz` work against a real DB and in the Docker image |
| **2** | Auth + profile + first deploy | Branches + aliases + seed, invite code, Argon2, DB sessions, Origin check, login rate limit, profile. **First deploy: Render + Neon** | Register → login → profile works locally and deployed |
| **3** | Drives + eligibility | Drives, eligibility rules, branch join table, admin CRUD, manual close vs computed expiry; `check_eligibility` + tests; `GET /drives` with reasons | Admin publishes a drive; feed shows eligible/ineligible with reasons |
| **4** | AI extraction | Schema, prompt, `Extractor` (manual/HTTP/fake), normaliser + evidence check, `extraction_runs`, extract endpoint | A pasted notice gives a flagged draft; manual fallback works with `LLM_PROVIDER=none` |
| **5** | Evals + tracker | Golden set + `evals.run`; state machine, applications, events | Eval results recorded; illegal move → 409, timeline recorded |
| **6** | Frontend I | Vite app, generated types, `/api` proxy, login / profile / feed | A student logs in and sees their filtered feed |
| **7** | Frontend II | Drive page, tracker, admin extract-and-review; deploy on Vercel | Usable end-to-end on mobile, deployed |
| **8** | Telegram | httpx client, link flow, webhook secret, new-drive alert | Publishing pings eligible students |
| **9** | Reminders + hardening | Reminder cron (time windows) + idempotency + session cleanup; fix issues found in the deployed app | Running cron twice sends one message |
| **10** | Polish | Demo data, README (architecture, AI boundary, eval results, trade-offs) + screenshots, demo video | Repo ready to share |

### 10.1 Day 1 — Foundation

1. Repo layout as in §7.1. `uv init` the backend, pin Python 3.13 (`.python-version`).
2. Tooling: ruff (lint + format), mypy (strict on `app/`), pytest + pytest-cov. Config lives in `pyproject.toml`. Add `.gitignore`, `.gitattributes` (LF endings), `.editorconfig` and `.pre-commit-config.yaml`.
3. Local Postgres 17 through `docker-compose.yml`, plus `.env.example`.
4. SQLAlchemy async engine + Alembic wired up, with an empty initial migration that runs cleanly.
5. Settings: **`load_config()`** reads env vars through pydantic-settings, validates them, normalises `DATABASE_URL` for asyncpg (§7.4), and **fails fast at startup** with a clear message.
6. `/healthz` (process up) and `/readyz`, which uses **`check_database()`**: a `SELECT 1` with a short timeout, returning 503 if the DB can't be reached.
7. structlog setup + request-ID middleware.
8. Graceful shutdown through the FastAPI lifespan, which disposes of the DB engine.
9. GitHub Actions CI: ruff, mypy and pytest with coverage against a Postgres 17 service container (integration tests included), plus a Docker image build and `/healthz` smoke test.
10. Backend `Dockerfile` (slim image, non-root user, uv for installing, migrations on start).
11. Check that every dependency installs and runs on Python 3.13 in WSL2 Ubuntu.
12. Side task: sign up for Render, Neon and Vercel. **If any asks for a card, stop** and we pick another option. Optionally look for a no-card free LLM tier; otherwise use `none` in prod and a local model for evals.

Tests for `load_config` and `check_database` are written **first**.

**Required checks before Day 1 is done**
- ruff, ruff format, mypy strict, pytest with coverage ≥ 80%: green locally (WSL) and in CI.
- Integration tests (real `SELECT 1`, `alembic upgrade head` from empty) green against Postgres 17.
- `/healthz` = 200 and `/readyz` = 200 with the DB up, 503 with it down.
- Every log line is JSON in prod, has a request ID, and the response carries `X-Request-ID`.
- The Docker image builds, runs as a non-root user, applies migrations on start, and serves `/healthz`.

### 10.2 Docker fallback

Local Docker problems must not block development indefinitely. If Docker Desktop's WSL integration can't be fixed in reasonable time:
- **Verified integration environment:** GitHub Actions. CI runs the integration tests against a `postgres:17` service container, and builds and smoke-tests the Docker image (start it, call `/healthz`). These CI results count as Day 1's integration and Docker checks.
- **Local development alternative:** install PostgreSQL 17 directly in WSL Ubuntu from the official PostgreSQL apt repository (apt.postgresql.org). Create the same `driveradar` user and database as `docker-compose.yml`, then point `DATABASE_URL` / `TEST_DATABASE_URL` at it. Unit tests never need a database.
- `docker-compose.yml` stays the preferred local setup, and we switch back once Docker works.

## 11. Interview talking points

1. **AI boundary:** "The LLM only reads notices. Python makes every decision." Structured output, Pydantic validation, deterministic normalisation, human approval.
2. **Hallucination guard:** the evidence check verifies that each extracted value is backed by a quote that really appears in the notice.
3. **Measured AI:** a golden set with per-field accuracy and abstention accuracy, plus the live admin edit rate from `extraction_runs`.
4. **Provider independence and graceful degradation:** one interface, config-selected adapter, manual entry whenever AI is unavailable. Runs at ₹0.
5. **Ingestion trade-off:** human-checked pasting instead of scraping WhatsApp and Gmail (terms of service, fragility, correctness).
6. **Eligibility as a pure function:** easy to test, returns reasons rather than a bare yes/no, compares normalised branch codes.
7. **State machine:** explicit allowed transitions, an audit trail, 409 on invalid moves.
8. **Reliable reminders on free hosting:** external cron + time windows + a DB unique constraint gives exactly-once alerts. This is idempotency in practice.
9. **Auth on split hosting:** third-party cookie blocking, a same-origin proxy, opaque sessions vs JWT, SameSite + Origin checks against CSRF.
10. **Fail-fast config + health vs readiness:** why `/healthz` and `/readyz` are separate endpoints.
11. **Time zones:** store UTC, show IST, and assume IST when a notice gives no timezone.
12. **Cost:** the whole system runs at ₹0/month, and I can explain what changes at 10× the users (Redis for rate limits, pooled connections, a paid LLM tier, a queue for extraction).

## 12. v2 backlog

- WhatsApp alerts (check the WhatsApp Business Cloud API's current pricing and template-approval rules first).
- Company-wise history: past drives, packages, rounds, offers.
- Email ingestion through a forwarding address.
- Vendor-specific extractor adapters (e.g. a native SDK) if a budget becomes available. The interface stays the same.
- Telegram forward-to-draft: forward a notice to the bot to create a draft through the same extraction pipeline.
- Calendar export (.ics) for deadlines.
- Placement stats dashboard.

## 13. Open questions

1. Batch size (for the README).
2. Exact branch codes and common aliases used by my college (needed by the Day 2 seed / Day 4 normaliser).
3. Which no-card free LLM tier, if any, is usable on Day 4. Fallback: `none` in prod + a local model for evals.
4. Vercel's external-rewrite timeout vs Render's cold start: check on Day 7. Mitigation: the frontend shows a "waking server…" state and retries.
5. Real notices for the golden set: collect 20–30 and anonymise them before committing.
