# Art Guide Pulse Monitor — backend

Python pipeline under `backend/` that:

1. Reads the **source registry** CSV (`backend/data/sources.csv`) — no exhibition metadata in this file.
2. Syncs rows into SQLite (`backend/data/pulse.sqlite`) and fetches each **active** source on a schedule.
3. Extracts **rule-based** exhibition hints, optional **visitor** fields, and **placeholder** social signals (no Google Maps / Instagram scraping).
4. Writes **Pulse** scores into `pulse_scores` and exports human-facing CSVs plus an HTML report.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python -m playwright install chromium   # needed only for access_method=playwright
```

Optional: `backend/.env` for `API_KEY` / `PULSE_API_TOKEN` (generic API fetcher) and future vendor keys.

## Commands

```bash
# Fetch + extract + score + export CSVs (respects incremental window)
python backend/src/main.py run

# Ignore last_checked and refetch every active source
python backend/src/main.py run --force

# HTML report for editors (reads pulse_updates.csv)
python backend/src/main.py report
```

## Local dashboard API

```bash
uvicorn backend.src.server:app --reload --port 8000
```

The Vite app (`npm run dev` from repo root) proxies `/api` to this server. Endpoints include `GET /api/status`, `GET /api/pulse-updates`, `GET /api/sources`, `POST /api/run-crawl` (equivalent to `run --force`), `POST /api/generate-report`, and `POST /api/review`.

## Source registry (`backend/data/sources.csv`)

| Column | Notes |
|--------|--------|
| `city` | Display / grouping |
| `source_name` | Institution label |
| `source_url` | Unique key (also used for joins) |
| `source_type` | e.g. `museum` |
| `trust_level` | `high` / `medium` / `low` |
| `access_method` | `web`, `rss`, `api`, `manual`, `playwright` |
| `status` | `active` (fetched), `blocked`, `inactive`, `needs_review` (skipped) |
| `last_checked` | ISO timestamp of last **attempt** (written by `run`) |
| `notes` | Editorial notes only |

**Ethical defaults:** `blocked` / `inactive` sources are never fetched. The crawler does **not** bypass 403/404-style blocks with alternate browsers. `playwright` is only used when explicitly configured — never as an automatic fallback for failed `web` fetches.

## Incremental policy

- Active sources are skipped if `last_checked` (SQLite, falling back to the CSV value) is newer than **`PULSE_RECHECK_HOURS`** (default **24**, overridable via env).
- `--force` ignores that window and refetches all **active** rows.
- `manual` access_method skips network I/O entirely.

## SQLite tables

- **`sources`** — registry mirror + `last_checked`.
- **`exhibitions`** — per-source extracted rows (titles/artists/dates + capped `raw_text` snippet). A non-exported `public_summary` column stores the placeholder blurb for `pulse_updates.csv`.
- **`visitor_info`** — optional fee / audio / amenities when detected in page text.
- **`signals`** — placeholders for ratings/hashtags (`google_rating`, `hashtag_count` empty until manual/API). `mention_count` defaults to `0` as a numeric placeholder.
- **`pulse_scores`** — one primary score row per exhibition (`pulse_label`, `score`, `reason`, `human_review_status`).

## CSV exports (`backend/data/`)

| File | Role |
|------|------|
| `pulse_updates.csv` | **Main editor file** — denormalized join for review |
| `exhibitions.csv` | Structured exhibition rows |
| `visitor_info.csv` | Visitor amenities when found |
| `signals.csv` | Signal placeholders + TODO fields |

## HTML report

`python backend/src/main.py report` writes `backend/reports/pulse_report.html` (cards grouped by city, sorted by pulse label + score).

## Layout

```
backend/
  data/
    sources.csv
    pulse.sqlite
    pulse_updates.csv
    exhibitions.csv
    visitor_info.csv
    signals.csv
  reports/
    pulse_report.html
  src/
    main.py
    database.py
    fetch_sources.py
    extract_content.py
    metadata_extract.py
    summarize.py
    scoring.py
    export.py
    report_html.py
  requirements.txt
```

## TODOs (intentional)

- Replace rule-based `metadata_extract` with AI-assisted structured extraction.
- Wire compliant APIs for ratings/social metrics instead of scraping.
