# CarFinder

Local-first used-car discovery and buying intelligence. The Python CLI and SQLite database work independently of the optional local API/UI.

## Development setup

Requirements: Python 3.12+, `uv`, Node.js supported by Vite, and npm.

```sh
uv sync
uv run playwright install chromium
cd frontend
npm install
npm run build
cd ..
uv run carfinder init
uv run carfinder doctor
uv run carfinder serve
```

The local API defaults to `http://127.0.0.1:8420`. During frontend development, use `uv run carfinder serve` in one terminal and `npm run dev` in `frontend/` in another.

Create a native-filter profile, or import a search URL copied from PolovniAutomobili for its full provider-specific filter set:

```sh
uv run carfinder profile create "Golf 5 Diesel" \
  --initial-import-mode analyze_all \
  --filters-json '{"makes":["Volkswagen"],"models":["Golf"],"generations":["Golf V"],"fuel":["diesel"],"year":{"min":2004,"max":2009},"price":{"max":5500},"mileage_km":{"max":250000}}'
uv run carfinder profile create "Advanced Polovni search" \
  --search-url 'https://www.polovniautomobili.com/auto-oglasi/pretraga?...'
uv run carfinder profile list
uv run carfinder run --profile "Golf 5 Diesel"
uv run carfinder analyze
```

The profile defaults to `seed_only`: deterministic findings are stored on the first scan, while optional LLM analysis is deferred. `analyze_all` runs it for every first-pass result; `analyze_top_n` limits first-pass LLM calls. Later scans process pending analysis. Deterministic analysis always runs without an LLM. To enable the Codex Exec adapter, set `[llm] enabled = true`; `carfinder analyze --force` bypasses the semantic cache. The Polovni browser uses a persistent profile under local app data and request delays default to 2.5 seconds. If the site presents a verification page, the run records the failure and stops; it does not solve or bypass the challenge.

`carfinder run` only writes to SQLite and works while the API/UI is stopped. The UI is optional; retained descriptions redact phone numbers and email addresses.

The local API exposes saved profiles, filtered listings, listing history/matches, shopping state, scraper runs, and summary stats under `/api`. Native hard-filter values within one dimension are ORed; separate dimensions are combined with AND. Preferences are stored separately and do not remove listings from the database.

Runtime data uses XDG paths by default. Set `CARFINDER_HOME=./.data` for a disposable development data/config/state tree; this path is ignored by Git.

## Project guidance

The private product and implementation context is in ignored `context/`. Start with `AGENTS.md` and `context/README.md`. Third-party source reuse is recorded in `THIRD_PARTY_NOTICES.md`.

Systemd user units and installation instructions are added with the scheduled-operation phase.
