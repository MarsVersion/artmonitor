"""SQLite storage: venues, flat exhibition records, crawl logs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"
ROOT_DATA_DIR = BACKEND_ROOT.parent / "data"
SOURCES_CSV = DATA_DIR / "sources.csv"
PULSE_CSV = DATA_DIR / "pulse_updates.csv"
EXHIBITIONS_CSV = DATA_DIR / "exhibitions.csv"
FLAT_EXHIBITIONS_CSV = ROOT_DATA_DIR / "exhibitions.csv"
VISITOR_CSV = DATA_DIR / "visitor_info.csv"
SIGNALS_CSV = DATA_DIR / "signals.csv"
DB_PATH = DATA_DIR / "pulse.sqlite"

FAILURE_THRESHOLD = 3


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS venues (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            country TEXT NOT NULL,
            address TEXT,
            category TEXT NOT NULL,
            importance TEXT NOT NULL,
            website TEXT NOT NULL,
            exhibitions_url TEXT NOT NULL,
            crawler TEXT NOT NULL DEFAULT 'html',
            status TEXT NOT NULL DEFAULT 'active',
            last_checked TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS exhibitions (
            id TEXT PRIMARY KEY,
            venue_slug TEXT NOT NULL,
            name TEXT,
            city TEXT,
            country TEXT,
            address TEXT,
            category TEXT,
            importance TEXT,
            website TEXT,
            exhibitions_url TEXT,
            title TEXT,
            start_date TEXT,
            end_date TEXT,
            artists TEXT,
            curators TEXT,
            status TEXT,
            image_url TEXT,
            source_url TEXT,
            crawler TEXT,
            scraped_at TEXT,
            updated_at TEXT,
            fetch_status TEXT,
            error_detail TEXT,
            FOREIGN KEY (venue_slug) REFERENCES venues(slug) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS crawl_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_slug TEXT,
            institution_name TEXT,
            city TEXT,
            event_type TEXT NOT NULL,
            http_status INTEGER,
            message TEXT,
            logged_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS removed_institutions (
            venue_slug TEXT PRIMARY KEY,
            institution_name TEXT NOT NULL,
            city TEXT NOT NULL,
            reason TEXT NOT NULL,
            http_status INTEGER,
            removed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pulse_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exhibition_id TEXT NOT NULL,
            score REAL NOT NULL,
            pulse_label TEXT NOT NULL,
            reason TEXT,
            human_review_status TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (exhibition_id) REFERENCES exhibitions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_exhibitions_venue ON exhibitions(venue_slug);
        CREATE INDEX IF NOT EXISTS idx_exhibitions_status ON exhibitions(status);
        CREATE INDEX IF NOT EXISTS idx_crawl_logs_venue ON crawl_logs(venue_slug);
        """
    )
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_venue(conn: sqlite3.Connection, venue: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO venues (
            slug, name, city, country, address, category, importance,
            website, exhibitions_url, crawler, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(slug) DO UPDATE SET
            name = excluded.name,
            city = excluded.city,
            country = excluded.country,
            address = excluded.address,
            category = excluded.category,
            importance = excluded.importance,
            website = excluded.website,
            exhibitions_url = excluded.exhibitions_url,
            crawler = excluded.crawler,
            status = CASE
                WHEN venues.status = 'removed' THEN venues.status
                ELSE excluded.status
            END
        """,
        (
            venue["slug"],
            venue["name"],
            venue["city"],
            venue["country"],
            venue.get("address", ""),
            venue["category"],
            venue["importance"],
            venue["website"],
            venue["exhibitions_url"],
            venue["crawler"],
            venue.get("status", "active"),
        ),
    )


def get_venue(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM venues WHERE slug = ?", (slug,))
    return cur.fetchone()


def update_venue_exhibitions_url(conn: sqlite3.Connection, slug: str, url: str) -> None:
    conn.execute(
        "UPDATE venues SET exhibitions_url = ? WHERE slug = ?",
        (url, slug),
    )


def update_venue_last_checked(conn: sqlite3.Connection, slug: str, ts: str) -> None:
    conn.execute(
        "UPDATE venues SET last_checked = ? WHERE slug = ?",
        (ts, slug),
    )


def set_venue_status(conn: sqlite3.Connection, slug: str, status: str) -> None:
    conn.execute("UPDATE venues SET status = ? WHERE slug = ?", (status, slug))


def delete_exhibitions_for_venue(conn: sqlite3.Connection, venue_slug: str) -> None:
    conn.execute("DELETE FROM exhibitions WHERE venue_slug = ?", (venue_slug,))


def upsert_exhibition(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO exhibitions (
            id, venue_slug, name, city, country, address, category, importance,
            website, exhibitions_url, title, start_date, end_date, artists, curators,
            status, image_url, source_url, crawler, scraped_at, updated_at,
            fetch_status, error_detail
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            artists = excluded.artists,
            curators = excluded.curators,
            status = excluded.status,
            image_url = excluded.image_url,
            source_url = excluded.source_url,
            exhibitions_url = excluded.exhibitions_url,
            scraped_at = excluded.scraped_at,
            updated_at = excluded.updated_at,
            fetch_status = excluded.fetch_status,
            error_detail = excluded.error_detail
        """,
        (
            record["id"],
            record["venue_slug"],
            record["name"],
            record["city"],
            record["country"],
            record.get("address", ""),
            record["category"],
            record["importance"],
            record["website"],
            record["exhibitions_url"],
            record["title"],
            record.get("start_date", ""),
            record.get("end_date", ""),
            record.get("artists", "[]"),
            record.get("curators", "[]"),
            record.get("status", ""),
            record.get("image_url", ""),
            record["source_url"],
            record["crawler"],
            record["scraped_at"],
            record["updated_at"],
            record.get("fetch_status", "ok"),
            record.get("error_detail", ""),
        ),
    )


def insert_pulse_score(
    conn: sqlite3.Connection,
    *,
    exhibition_id: str,
    score: float,
    pulse_label: str,
    reason: str,
    human_review_status: str,
    created_at: str,
) -> None:
    conn.execute(
        "DELETE FROM pulse_scores WHERE exhibition_id = ?",
        (exhibition_id,),
    )
    conn.execute(
        """
        INSERT INTO pulse_scores (
            exhibition_id, score, pulse_label, reason, human_review_status, created_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (exhibition_id, score, pulse_label, reason, human_review_status, created_at),
    )


def update_pulse_review_status(
    conn: sqlite3.Connection,
    *,
    human_review_status: str,
    exhibition_id: str | None = None,
    source_url: str | None = None,
    exhibition_title: str | None = None,
) -> int:
    if exhibition_id:
        cur = conn.execute(
            "UPDATE pulse_scores SET human_review_status = ? WHERE exhibition_id = ?",
            (human_review_status, exhibition_id),
        )
        return int(cur.rowcount or 0)
    if source_url and exhibition_title:
        cur = conn.execute(
            """
            UPDATE pulse_scores SET human_review_status = ?
            WHERE exhibition_id IN (
                SELECT id FROM exhibitions WHERE source_url = ? AND title = ?
            )
            """,
            (human_review_status, source_url, exhibition_title),
        )
        return int(cur.rowcount or 0)
    return 0
