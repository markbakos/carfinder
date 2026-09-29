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
uv run carfinder profile create "Low-mileage Golf" \
  --filters-json '{"makes":["Volkswagen"],"models":["Golf"]}' \
  --preferences-json '{"mileage_km":{"ideal_max":180000},"equipment":{"prefer":["cruise_control"]}}'
uv run carfinder profile list
uv run carfinder run --profile "Golf 5 Diesel"
uv run carfinder analyze
```

The profile defaults to `seed_only`: deterministic findings are stored on the first scan, while optional LLM analysis is deferred. `analyze_all` runs it for every first-pass result; `analyze_top_n` limits first-pass LLM calls. Later scans process pending analysis. Deterministic analysis always runs without an LLM. To enable the Codex Exec adapter, set `[llm] enabled = true`; `carfinder analyze --force` bypasses the semantic cache. The Polovni browser uses a persistent profile under local app data and request delays default to 2.5 seconds. If the site presents a verification page, the run records the failure and stops; it does not solve or bypass the challenge.

`carfinder run` only writes to SQLite and works while the API/UI is stopped. The UI is optional; retained descriptions redact phone numbers and email addresses.

The local API exposes saved profiles, filtered listings, listing history/matches, shopping state, scraper runs, and summary stats under `/api`. Native hard-filter values within one dimension are ORed; separate dimensions are combined with AND. Preferences are stored separately and do not remove listings from the database.

Market comparisons use active local listings with the same make/model, currency, year within two years, fuel and transmission family. Generation, engine size and mileage are preferred, with any relaxation recorded in the explanation. Values use a robust median/outlier filter; fewer than three retained comparables produces no estimated median, and confidence is based on sample count. Quality dimensions are evidence-based and unsupported dimensions remain unscored. Profile fit is reported separately from quality; rank combines them 70/30 when both scores are available. `/api/listings` supports `minimum_score`, `sort=quality_desc`, and profile-scoped `sort=rank_desc`.

The built local UI includes an overview, searchable/filterable listings, listing history and evidence, saved-search editing, side-by-side comparison, run history, and local settings. `carfinder serve` serves the Vite build and its client-side routes; Node is only needed to build or develop the UI. Prices stay in the listing's original currency; CarFinder does not apply exchange-rate conversions.

## Manually add a listing

Use **Add listing** in the Listings screen, or pipe canonical JSON to the CLI. The source link and details you provide go through the same history, analysis, profile matching, valuation, and scoring flow as discovered listings; CarFinder does not fetch that page or require Facebook access. Phone numbers and email addresses are removed from the imported title and description.

```sh
cat listing.json | uv run carfinder import-json -
```

JSON uses the normalized listing field names, such as `url`, `title`, `description`, `price_amount`, `price_currency`, `make`, `model`, `year`, and `mileage_km`. `url` is required; its SHA-256 digest supplies a stable import identity unless `external_id` is provided.

## Scheduled scans and backups

Generate a systemd user service and timer for the active CarFinder executable:

```sh
uv run carfinder systemd install
systemctl --user daemon-reload
systemctl --user enable --now carfinder.timer
systemctl --user status carfinder.timer
systemctl --user list-timers
journalctl --user -u carfinder.service
```

The default schedule runs at 08:00, 14:00 and 20:00 with a five-minute randomized delay. Change it with `--calendar`, for example `uv run carfinder systemd install --calendar 'daily 09:30'`. Installation only writes the unit files; enable the timer separately. `carfinder doctor` checks provider reachability and, when enabled, exercises the configured LLM's structured-output path with synthetic data. Create a consistent SQLite backup at any time with `uv run carfinder db backup`; use `--output PATH` to choose its destination.

Runtime data uses XDG paths by default. Set `CARFINDER_HOME=./.data` for a disposable development data/config/state tree; this path is ignored by Git.

## Project guidance

The private product and implementation context is in ignored `context/`. Start with `AGENTS.md` and `context/README.md`. Third-party source reuse is recorded in `THIRD_PARTY_NOTICES.md`.

The systemd user timer invokes `carfinder run`; collection continues while the UI is stopped.
