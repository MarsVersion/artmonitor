# Yuranja Art Monitor

Local-first editorial stack: a **Vite + React** dashboard, a **Python** crawl pipeline with **SQLite** + CSV exports, and a **Yuranja export** for approved exhibitions. The dashboard supports inquiries across city, venue, exhibition, artist, curator, admission and visitor amenities.

## Prerequisites

- Node 20+ (recommended)
- Python 3.11+
- Playwright browser (only if you use `crawler=playwright`):

```bash
python3 -m playwright install chromium
```

## Python backend

```bash
cd ~/Projects/artmonitor
python3 -m pip install -r backend/requirements.txt
```

### CLI

```bash
# Sync institution seed → SQLite + sources.csv
python3 backend/src/main.py seed-sync

# Crawl all active city sources (≥2 institutions × 12 cities)
python3 backend/src/main.py ingest-cities --force

# Export approved current/upcoming exhibitions for Yuranja
python3 backend/src/main.py export-yuranja

# Legacy pulse crawl / HTML report
python3 backend/src/main.py run --force
python3 backend/src/main.py report
```

### FastAPI dashboard server

```bash
python3 -m uvicorn backend.src.server:app --reload --port 8000
```

Endpoints include `GET /api/status`, `GET /api/exhibitions`, `GET /api/pulse-updates`, `GET /api/sources`, `POST /api/run-crawl`, `POST /api/generate-report`, and `POST /api/review` (Approve / Needs editing / Reject / Pending).

## Frontend

```bash
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. Start **uvicorn** first, then open `http://localhost:5173`.

## Editorial workflow

1. `ingest-cities` writes every new exhibition as **pending**.
2. Review in the dashboard: **Approve**, **Needs editing**, or **Reject**.
3. `export-yuranja` writes only **approved**, **current/upcoming**, non-duplicate, non-archived rows to `data/yuranja_exhibitions.json` with official citations.
4. Missing admission is exported as `unknown` / “Check current admission” — never invented as free.

## Data layout

| Path | Role |
|------|------|
| `backend/data/pulse.sqlite` | Canonical store |
| `backend/data/seed_institutions.json` | Institution registry (12 cities) |
| `backend/data/sources.csv` | Active + manual venue registry |
| `backend/data/visitor_info.csv` | Verified visitor / admission facts |
| `backend/reports/city_ingest_report.md` | Coverage + quality report |
| `data/yuranja_exhibitions.json` | Approved export for Yuranja |

See `backend/README.md` for crawl semantics and schema details.
