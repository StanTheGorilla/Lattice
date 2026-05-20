# Lattice

Personal optimization system. Single user. Windows-native.
Aggregates Garmin biometrics, Google Calendar, and manual life-logging behind
deterministic scoring functions (F1–F5, F8, F9a). Surfaces them through a
SvelteKit web UI and a chat-first Discord bot powered by DeepSeek.

See `SPEC.md` for the spec, `PLAN.md` for phase status, `CLAUDE.md` for
conventions.

## Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy async + aiosqlite, Alembic, APScheduler
- **Bot**: discord.py 2.x, APScheduler (briefings)
- **Frontend**: SvelteKit 5 (runes), TypeScript strict, TailwindCSS 4, ECharts
- **LLM**: DeepSeek (OpenAI-compatible), native tool calling
- **Storage**: SQLite (`data/lattice.db`)

## Setup

Prereqs: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bat
copy .env.example .env
:: fill values per "Environment" below

cd backend  && uv sync && uv run alembic upgrade head
cd ..\bot   && uv sync
cd ..\frontend && npm install
```

## Run

```bat
start.bat
```

Opens three terminals:

| Process  | Port  | Notes |
|----------|-------|-------|
| Backend  | 8000  | uvicorn `lattice.main:app --reload`, binds 127.0.0.1 only |
| Frontend | 5173  | Vite dev server, proxies `/api/*` → backend |
| Bot      | —     | Discord gateway; exits cleanly if `DISCORD_BOT_TOKEN` unset |

Open `http://localhost:5173`. If `WEB_UI_PASSWORD` is empty the login form
accepts any password (dev-permissive — backend is loopback-only).

## Environment

All values live in `.env` (gitignored). See `.env.example` for the full list.

| Variable | Required for | Notes |
|---|---|---|
| `TIMEZONE` | always | IANA tz, default `Europe/Warsaw` |
| `LATTICE_DISABLE_SCHEDULER` | dev | Must be `true` when running uvicorn `--reload` (reload spawns duplicate schedulers). Set `false` in prod-mode runs. |
| `WEB_UI_PASSWORD` | optional | If empty, web UI is dev-permissive. Otherwise required to log in. |
| `BOT_SHARED_SECRET` | bot | `X-Bot-Token` header sent from bot to backend. |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Garmin sync | Token cached under `%USERPROFILE%/.garminconnect/`. |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | reference only | Actual OAuth flow reads `backend/lattice/integrations/credentials.json`. Token cached at `%USERPROFILE%/.lattice/google_token.json`. |
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
  this once from the same machine.
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

```bat
:: backend
cd backend && uv run pytest

:: bot
cd ..\bot && uv run pytest

:: frontend types
cd ..\frontend && npm run check
```

Full cold-start smoke test: see [`SMOKE_TEST.md`](SMOKE_TEST.md).

## Layout

```
backend/      FastAPI + SQLAlchemy + APScheduler
bot/          discord.py + APScheduler (briefings)
frontend/     SvelteKit 5 + Tailwind 4
data/         SQLite database (gitignored)
logs/         Rotating log files (gitignored)
UI_REFERENCE/ Original design mockup (HTML)
```

## License

Private — single-user personal project.
