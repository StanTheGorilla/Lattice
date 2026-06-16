```
██╗      █████╗ ████████╗████████╗██╗ ██████╗███████╗
██║     ██╔══██╗╚══██╔══╝╚══██╔══╝██║██╔════╝██╔════╝
██║     ███████║   ██║      ██║   ██║██║     █████╗
██║     ██╔══██║   ██║      ██║   ██║██║     ██╔══╝
███████╗██║  ██║   ██║      ██║   ██║╚██████╗███████╗
╚══════╝╚═╝  ╚═╝   ╚═╝      ╚═╝   ╚═╝ ╚═════╝╚══════╝
```

> A single-user personal optimization system with an AI brain.

![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![SvelteKit](https://img.shields.io/badge/SvelteKit-5-FF3E00?logo=svelte&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-data-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/license-private-lightgrey)

Lattice aggregates **Garmin biometrics**, **Google Calendar**, and **manual
life-logging** behind deterministic scoring functions, then puts an LLM in the
driver's seat as the single "brain" that reasons over that data, talks to you on
Discord, and acts on your behalf. It runs headless on a Raspberry Pi and serves
its web UI on the local network.

See [`SPEC.md`](SPEC.md) for the spec, [`PLAN.md`](PLAN.md) for phase status,
and [`CLAUDE.md`](CLAUDE.md) for conventions.

## Features

- **AI-as-brain chat** — a DeepSeek agent with native tool calling owns a
  keyed `recommendations` store and can read every metric, write plans, run
  custom algorithms, and trigger syncs. Primary interface is a Discord DM.
- **Persistent memory** — durable `user_memory` facts plus open-commitment
  tracking (`pending_actions`), both re-injected every turn so resumed
  conversations don't forget plans or unfinished asks.
- **Self-improving journal** — the agent writes forward-looking soft-guidance
  notes to an `ai_journal` (observations + corrections), reinforces repeats, and
  consolidates weekly. Behavior shaped by your in-the-moment instruction always
  wins.
- **Deterministic scoring** — readiness, work window, training recommendation,
  sleep window, caffeine cutoff, and habit adherence are pure, tested functions
  (F1–F5, F8, F9a) — the AI reasons *over* them, it doesn't invent the numbers.
- **User-configurable routines & alerts** — scheduled agent runs (morning /
  evening briefings, weekly review) and threshold alerts, all editable.
- **Web dashboard** — SvelteKit 5 UI with ECharts cards, memory/journal
  inspectors, usage + cost observability, and a chat console.

## Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy async + aiosqlite, Alembic, APScheduler
- **Bot**: discord.py 2.x, APScheduler (briefings)
- **Frontend**: SvelteKit 5 (runes), TypeScript strict, TailwindCSS 4, ECharts
- **LLM**: DeepSeek (OpenAI-compatible), native tool calling
- **Storage**: SQLite (`data/lattice.db`)
- **Host**: Raspberry Pi (systemd services, autostart on boot)

## Setup

Prereqs: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env
# fill values per "Environment" below

cd backend   && uv sync && uv run alembic upgrade head
cd ../bot    && uv sync
cd ../frontend && npm install && npm run build
```

## Run

**Production (Raspberry Pi).** The frontend is a static build served by the
backend; backend and bot run as systemd services that autostart on boot. To
(re)start on demand — also rebuilds the frontend if it hasn't been built:

```bash
./start.sh
```

```
UI:     http://<pi-ip>:8000/
Health: http://<pi-ip>:8000/api/health
Logs:   journalctl -u lattice-backend -f   (or -u lattice-bot)
Stop:   sudo systemctl stop lattice-backend lattice-bot
```

**Development.** Run the pieces directly for hot reload:

| Process  | Port  | Command |
|----------|-------|---------|
| Backend  | 8000  | `cd backend && uv run uvicorn lattice.main:app --reload` |
| Frontend | 5173  | `cd frontend && npm run dev` (proxies `/api/*` → backend) |
| Bot      | —     | `cd bot && uv run python -m lattice_bot` |

Set `LATTICE_DISABLE_SCHEDULER=true` under `--reload` (reload spawns duplicate
schedulers). If `WEB_UI_PASSWORD` is empty the login form is dev-permissive.

## Environment

All values live in `.env` (gitignored). See `.env.example` for the full list.

| Variable | Required for | Notes |
|---|---|---|
| `TIMEZONE` | always | IANA tz, default `Europe/Warsaw` |
| `LATTICE_DISABLE_SCHEDULER` | dev | Must be `true` when running uvicorn `--reload` (reload spawns duplicate schedulers). Set `false` in prod-mode runs. |
| `WEB_UI_PASSWORD` | optional | If empty, web UI is dev-permissive. Otherwise required to log in. |
| `BOT_SHARED_SECRET` | bot | `X-Bot-Token` header sent from bot to backend. |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Garmin sync | Token cached under `~/.garminconnect/`. |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | reference only | Actual OAuth flow reads `backend/lattice/integrations/credentials.json`. Token cached at `~/.lattice/google_token.json`. |
| `DISCORD_BOT_TOKEN` | bot | Bot token from Discord dev portal (Bot tab, **not** OAuth2 client secret). |
| `DISCORD_OWNER_ID` | bot | Your numeric Discord user id. Non-owner DMs are dropped. |
| `DEEPSEEK_API_KEY` | chat agent + F7 | OpenAI-compatible. |

Privileged intents: the Discord bot requires **Message Content Intent**
enabled on the bot's Discord dev portal page.

## Integrations — first-run

- **Garmin**: first `POST /api/sync/garmin` walks the garminconnect auth flow
  and caches credentials. No browser needed.
- **Google Calendar**: first `POST /api/calendar/sync` opens a browser tab via
  `InstalledAppFlow.run_local_server(port=0)` and writes the token cache. Do
  this once from a machine with a browser.
- **Discord**: invite the bot to your account's DMs via the OAuth2 URL
  generator in the dev portal (scope `bot`). Bot only listens to DMs from
  `DISCORD_OWNER_ID`.
- **DeepSeek**: just set `DEEPSEEK_API_KEY`. No first-run handshake.

## Scheduled jobs

When `LATTICE_DISABLE_SCHEDULER=false`:

| Job | Schedule | Source |
|---|---|---|
| `garmin_sync` | hourly :05 | `backend/lattice/sync/scheduler.py` |
| `readiness_compute` | daily 06:00 | persists F1 readiness as a metric |
| `weekly_report` | Sun 22:00 | F7 generation, UPSERT by ISO week |
| `conversation_prune` | daily 03:00 | trims `conversations` older than 30 days |
| `calendar_cache_prune` | hourly :15 | drops events ending >1 day ago |
| `morning_brief` (bot) | daily 07:30 | `bot/lattice_bot/briefings.py` |
| `evening_brief` (bot) | daily 21:00 | same |

## Verify

```bash
cd backend   && uv run pytest      # backend
cd ../bot    && uv run pytest      # bot
cd ../frontend && npm run check    # frontend types
```

Full cold-start smoke test: see [`SMOKE_TEST.md`](SMOKE_TEST.md).

## Layout

```
backend/    FastAPI + SQLAlchemy + APScheduler
bot/        discord.py + APScheduler (briefings)
frontend/   SvelteKit 5 + Tailwind 4 (static build served by backend)
data/       SQLite database (gitignored)
logs/       Rotating log files (gitignored)
```

## License

Private — single-user personal project.
