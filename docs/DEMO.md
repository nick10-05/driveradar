# Demo video script (~3 minutes)

Record on the local app with demo data, so no real student data appears on screen.

## Setup (once)

1. `docker compose up -d db`, then seed a clean demo database (WSL, `backend/`):
   ```bash
   DATABASE_URL=postgresql://driveradar:driveradar@localhost:5432/driveradar_demo uv run alembic upgrade head
   DATABASE_URL=postgresql://driveradar:driveradar@localhost:5432/driveradar_demo \
     DEMO_PASSWORD="$(grep ^DEMO_PASSWORD= .env.demo | cut -d= -f2-)" uv run python -m app.scripts.seed_demo
   ```
   Re-run the seed right before recording: deadlines are relative to now.
2. Start the backend against `driveradar_demo` (the `backend-demo` launch config does this) and the frontend (`npm --prefix frontend run dev`).
3. Phone: open Telegram with your bot ready, for the alert shot. For a real alert, record on the deployed site with your own test account instead of the demo data.
4. Browser at 100% zoom, a narrow window (or devtools mobile view) for the student part.

Accounts: `asha.demo@example.com` (CSE, eligible for most), `ravi.demo@example.com` (ECE, sees reasons), `demo.admin@example.com`. Password: `DEMO_PASSWORD` in `backend/.env.demo`.

## Shots

| # | Time | Screen | Say |
|---|---|---|---|
| 1 | 0:00 | Title / repo README | "Placement notices reach my batch from email, WhatsApp, the portal and Telegram. DriveRadar turns them into one feed, filtered by each student's eligibility." |
| 2 | 0:15 | Log in as Asha → feed | "Eligible drives first, soonest deadline first. Times are IST. Razorpay closes in 17 hours, so it's highlighted." |
| 3 | 0:35 | Log in as Ravi → expand "Not eligible" | "Nothing is hidden silently: every ineligible drive says exactly why. This is a pure Python function, not the AI." |
| 4 | 0:55 | Asha → Zoho drive page → "I applied" → timeline | "The tracker is a state machine. The server sends which moves are allowed; the buttons come from that." |
| 5 | 1:15 | Tracker page | "History stays: offers, rejections, closed and expired drives." |
| 6 | 1:25 | Profile → Telegram card (Connect) | "Students connect Telegram with a one-time link: hashed, single-use, 15 minutes." |
| 7 | 1:40 | Admin → New from notice → paste a notice → Extract (or Fill in manually) → review form | "Admins paste a notice. The AI only extracts fields; every value needs a quote from the notice, and anything unbacked is flagged. With AI off, it's manual entry." |
| 8 | 2:10 | Save as draft → Publish | "A human publishes every drive. Publishing pings eligible students on Telegram." |
| 9 | 2:20 | Phone: the Telegram alert | "That's the real Bot API, sent in a background task, exactly once per student." |
| 10 | 2:30 | GitHub Actions → Reminders run log | "Free hosting sleeps, so a GitHub cron calls the backend every 30 minutes. Deadline windows plus a unique constraint mean a reminder is never sent twice." |
| 11 | 2:45 | CI run (green) + README architecture | "Real Postgres in CI, 99% coverage, typed API client generated from the backend. All of it runs at ₹0 a month." |

Tips: hide the bookmarks bar, close other tabs, no notifications. Re-take a shot rather than editing out mistakes.
