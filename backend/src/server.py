"""FastAPI local dashboard API for ZAKPUM Pulse Monitor."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import database
import export
import main as pulse_main

app = FastAPI(title="ZAKPUM Pulse Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_csv_as_json(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    conn = database.connect()
    sources_count = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
    exhibitions_count = int(conn.execute("SELECT COUNT(*) FROM exhibitions").fetchone()[0])
    pulse_count = int(conn.execute("SELECT COUNT(*) FROM pulse_scores").fetchone()[0])
    last = conn.execute(
        "SELECT MAX(last_checked) FROM sources WHERE last_checked IS NOT NULL AND TRIM(last_checked) != ''",
    ).fetchone()[0]
    blocked = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM sources
            WHERE lower(trim(status)) IN ('blocked', 'inactive')
            """,
        ).fetchone()[0],
    )
    with_errors = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM exhibitions
            WHERE COALESCE(trim(error_detail), '') != ''
            """,
        ).fetchone()[0],
    )
    return {
        "database_path": str(database.DB_PATH),
        "sources_count": sources_count,
        "exhibitions_count": exhibitions_count,
        "pulse_updates_count": pulse_count,
        "last_crawl_at": last,
        "blocked_or_inactive_sources": blocked,
        "exhibitions_with_errors": with_errors,
    }


@app.post("/api/run-crawl")
def api_run_crawl() -> dict[str, Any]:
    """Same as `python3 backend/src/main.py run --force`."""
    result = pulse_main.cmd_run(force=True)
    return {
        "success": bool(result.get("success", True)),
        "message": str(result.get("message", "")),
        "sources_processed": int(result.get("sources_processed", 0)),
        "sources_active": int(result.get("sources_active", 0)),
        "sources_skipped_incremental": int(result.get("sources_skipped_incremental", 0)),
        "sources_skipped_registry": int(result.get("sources_skipped_registry", 0)),
        "sources_fetch_skipped": int(result.get("sources_fetch_skipped", 0)),
        "exports": result.get("exports") or {},
        "errors": list(result.get("errors") or []),
    }


@app.post("/api/generate-report")
def api_generate_report() -> dict[str, Any]:
    """Same as `python3 backend/src/main.py report`."""
    try:
        out = pulse_main.cmd_report()
        return {
            "success": bool(out.get("success", True)),
            "message": str(out.get("message", "")),
            "path": str(out.get("path", "")),
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/pulse-updates")
def api_pulse_updates() -> list[dict[str, Any]]:
    return _read_csv_as_json(database.PULSE_CSV)


@app.get("/api/sources")
def api_sources() -> list[dict[str, Any]]:
    return _read_csv_as_json(database.SOURCES_CSV)


class ReviewBody(BaseModel):
    exhibition_id: int | None = Field(default=None)
    source_url: str | None = Field(default=None)
    exhibition_title: str | None = Field(default=None)
    human_review_status: str


REVIEW_VALUES = frozenset({"approved", "rejected", "needs_edit", "pending"})


@app.post("/api/review")
def api_review(body: ReviewBody) -> dict[str, Any]:
    status = body.human_review_status.strip().lower()
    if status not in REVIEW_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"human_review_status must be one of: {', '.join(sorted(REVIEW_VALUES))}",
        )
    if body.exhibition_id is None and (
        not (body.source_url or "").strip() or not (body.exhibition_title or "").strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide exhibition_id or both source_url and exhibition_title.",
        )

    conn = database.connect()
    n = database.update_pulse_review_status(
        conn,
        human_review_status=status,
        exhibition_id=body.exhibition_id,
        source_url=(body.source_url or "").strip() or None,
        exhibition_title=(body.exhibition_title or "").strip() or None,
    )
    if n == 0:
        raise HTTPException(status_code=404, detail="No matching pulse score row was updated.")
    conn.commit()
    export.export_all_csvs(conn)
    return {"success": True, "updated": n, "human_review_status": status}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
