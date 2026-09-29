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

At the current foundation stage, `carfinder run` is present but provider ingestion arrives in Phase 1. The React app is optional; collection will not depend on the server or UI.

Runtime data uses XDG paths by default. Set `CARFINDER_HOME=./.data` for a disposable development data/config/state tree; this path is ignored by Git.

## Project guidance

The private product and implementation context is in ignored `context/`. Start with `AGENTS.md` and `context/README.md`. Third-party source reuse is recorded in `THIRD_PARTY_NOTICES.md`.

Systemd user units and installation instructions are added with the scheduled-operation phase.
