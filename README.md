# ZAKPUM Pulse Monitor

Local-first editorial stack: a **Vite + React** dashboard, a **Python** crawl pipeline with **SQLite** + CSV exports, and an optional **HTML** report.

## Prerequisites

- Node 20+ (recommended)
- Python 3.11+
- Playwright browser (only if you use `access_method=playwright` in `backend/data/sources.csv`):

```bash
python3 -m playwright install chromium
```

## Python backend

Install dependencies:

```bash
pip install -r backend/requirements.txt
```

### CLI (unchanged)

```bash
python3 backend/src/main.py run --force
python3 backend/src/main.py report
```

### FastAPI dashboard server

```bash
uvicorn backend.src.server:app --reload --port 8000
```

Endpoints include `GET /api/status`, `GET /api/pulse-updates`, `GET /api/sources`, `POST /api/run-crawl`, `POST /api/generate-report`, and `POST /api/review`.

## Frontend

```bash
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`, so start **uvicorn** first, then open the app URL Vite prints (usually `http://localhost:5173`).

## Data layout

| Path | Role |
|------|------|
| `backend/data/pulse.sqlite` | Canonical store |
| `backend/data/sources.csv` | Source registry |
| `backend/data/pulse_updates.csv` | Denormalized pulse rows for editors + dashboard |
| `backend/reports/pulse_report.html` | Static report from `main.py report` |

See `backend/README.md` for crawl semantics, incremental windows, and schema details.
