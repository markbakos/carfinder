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

Create a profile from a search URL copied from PolovniAutomobili, then run it without starting the server:

```sh
uv run carfinder profile create "Golf 5 Diesel" \
  --search-url 'https://www.polovniautomobili.com/auto-oglasi/pretraga?...'
uv run carfinder profile list
uv run carfinder run --profile "Golf 5 Diesel"
```

The profile starts in `seed_only` mode so the first scan can build a local baseline. Change it to `analyze_all` when creating a narrow profile if you want first-pass analysis. The Polovni browser uses a persistent profile under local app data and request delays default to 2.5 seconds. If the site presents a verification page, the run records the failure and stops; it does not solve or bypass the challenge.

`carfinder run` only writes to SQLite and works while the API/UI is stopped. The UI is optional; retained descriptions redact phone numbers and email addresses.

Runtime data uses XDG paths by default. Set `CARFINDER_HOME=./.data` for a disposable development data/config/state tree; this path is ignored by Git.

## Project guidance

The private product and implementation context is in ignored `context/`. Start with `AGENTS.md` and `context/README.md`. Third-party source reuse is recorded in `THIRD_PARTY_NOTICES.md`.

Systemd user units and installation instructions are added with the scheduled-operation phase.
