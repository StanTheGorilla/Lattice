# Lattice — Claude Code Conventions

## Reading order for any session
1. Read `SPEC.md` for current scope
2. Read `PLAN.md` for current phase state
3. Read this file for conventions

## Python (backend, bot)
- Python 3.11+, type hints required on all public functions and class methods
- `uv` for dependency management
- Async-first: FastAPI async routes, SQLAlchemy async sessions, httpx for HTTP
- `ruff` for linting + formatting; `mypy --strict` clean on `lattice/` and `lattice_bot/`
- No global state in `functions/`; pure functions take DB session + params
- Pydantic v2 for all request/response schemas in `schemas/`
- Use `pathlib.Path` for all file paths; never hardcode `/` separators
- Token cache and credential paths use `%USERPROFILE%`; resolve with `Path.home()`
- All datetime values stored in DB as ISO 8601 strings with TZ offset
- Logging via stdlib `logging`, configured in `config.py`, rotating files in `logs/`

## SvelteKit (frontend)
- SvelteKit 5 with runes (`$state`, `$derived`, `$effect`, `$props`)
- No Svelte 4 patterns (`export let`, reactive `$:`, stores-as-default-state)
- TypeScript strict mode
- TailwindCSS 4 utility classes; no custom CSS unless unavoidable
- Component types from `$lib/api/types.ts`, generated to mirror backend Pydantic schemas
- ECharts for charts (SPEC §2); install via `echarts` + a thin Svelte wrapper component
- No third-party UI component libraries; build primitives in `$lib/components/ui/`

## Brand
- **No logo. No SVG mark. No favicon graphic.** Wordmark text "LATTICE" only,
  set in JetBrains Mono with letter-spacing per design tokens. This overrides
  the mockup's diamond/square brand marks.

## Git
- Conventional commits: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`
- One logical change per commit
- Branch off `main`; no PR workflow needed (single dev), commit to `main` directly
- `.gitignore` covers `.env`, `data/`, `logs/`, `__pycache__/`, `node_modules/`, `.venv/`, `dist/`, `.svelte-kit/`, OAuth tokens

## Testing
- pytest for backend; tests live in `backend/tests/` mirroring source structure
- Unit tests required for all F1–F5, F8, F9a rule tables
- Schema round-trip tests for all Pydantic models
- No integration tests against live Garmin/Google/DeepSeek in v1 (manual verification)
- Frontend tests not required in v1

## Error handling
- Integration errors (Garmin, Google, DeepSeek) log at WARNING with full context
- Authentication errors log at ERROR and trigger Discord DM to user
- Never silently swallow exceptions
- HTTP errors return appropriate status codes with structured error bodies:
  `{ "error": "code", "message": "human readable", "details": {...} }`

## File naming
- Python: `snake_case.py`
- Svelte components: `PascalCase.svelte`
- Routes: `+page.svelte`, `+layout.svelte` per SvelteKit convention
- Tests: `test_<module>.py`

## graphify — knowledge graph (always-on)

The project knowledge graph lives in `graphify-out/`:
- `graphify-out/graph.json` — raw graph data (nodes, edges, communities)
- `graphify-out/GRAPH_REPORT.md` — audit report with god nodes, surprising connections, suggested questions
- `graphify-out/obsidian/` — Obsidian vault; open this folder as a vault in Obsidian

### Every session
1. If `graphify-out/graph.json` exists, read `graphify-out/GRAPH_REPORT.md` for context before answering architecture or codebase questions. Cite node labels and source locations when relevant.
2. After any non-trivial code change (new module, refactor, new route), rebuild the graph: run `/graphify F:\Lattice --update` so the graph stays current.
3. When the graph is stale or missing and the question requires architectural understanding, run `/graphify F:\Lattice` to build it fresh.

### Obsidian vault
- Path: `F:\Lattice\graphify-out\obsidian\`
- Open as an Obsidian vault (File → Open vault → select the folder above)
- Graph view and `graph.canvas` are pre-configured; community colors and arrow directions are set
- `GRAPH_REPORT.md` opens by default as the landing note
- Regenerate vault after graph updates: `/graphify F:\Lattice --obsidian --obsidian-dir F:\Lattice\graphify-out\obsidian`
