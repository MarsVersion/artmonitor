"""SQLite storage: source registry sync, exhibitions, visitor info, signals, pulse scores."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"
SOURCES_CSV = DATA_DIR / "sources.csv"
PULSE_CSV = DATA_DIR / "pulse_updates.csv"
EXHIBITIONS_CSV = DATA_DIR / "exhibitions.csv"
VISITOR_CSV = DATA_DIR / "visitor_info.csv"
SIGNALS_CSV = DATA_DIR / "signals.csv"
DB_PATH = DATA_DIR / "pulse.sqlite"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create v2 schema. Drops legacy v1 tables if present."""
    conn.executescript(
        """
        DROP TABLE IF EXISTS pulse_updates;
        DROP TABLE IF EXISTS runs;

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL UNIQUE,
            source_type TEXT,
            trust_level TEXT,
            access_method TEXT,
            status TEXT,
            last_checked TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS exhibitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            city TEXT,
            institution TEXT,
            exhibition_title TEXT,
            artist_names TEXT,
            start_date TEXT,
            end_date TEXT,
            source_url TEXT,
            raw_text TEXT,
            public_summary TEXT,
            last_updated TEXT,
            fetch_status TEXT,
            error_detail TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS visitor_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution TEXT,
            city TEXT,
            entry_fee TEXT,
            audio_guide_available TEXT,
            audio_guide_languages TEXT,
            amenities TEXT,
            source_url TEXT,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution TEXT,
            city TEXT,
            google_rating TEXT,
            hashtag_count TEXT,
            mention_count TEXT,
            sentiment_score TEXT,
            source_url TEXT,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS pulse_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exhibition_id INTEGER NOT NULL,
            score REAL NOT NULL,
            pulse_label TEXT NOT NULL,
            reason TEXT,
            human_review_status TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (exhibition_id) REFERENCES exhibitions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_exhibitions_source ON exhibitions(source_id);
        CREATE INDEX IF NOT EXISTS idx_pulse_scores_exhibition ON pulse_scores(exhibition_id);
        """
    )
    _migrate_schema(conn)
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns introduced after first deploy (safe no-op if present)."""
    cur = conn.execute("PRAGMA table_info(exhibitions)")
    cols = {r[1] for r in cur.fetchall()}
    if cols and "public_summary" not in cols:
        conn.execute("ALTER TABLE exhibitions ADD COLUMN public_summary TEXT")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_source(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Insert or update a source row from the registry CSV. Returns sources.id."""
    url = str(row.get("source_url", "")).strip()
    conn.execute(
        """
        INSERT INTO sources (
            city, source_name, source_url, source_type, trust_level,
            access_method, status, last_checked, notes
        ) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_url) DO UPDATE SET
            city = excluded.city,
            source_name = excluded.source_name,
            source_type = excluded.source_type,
            trust_level = excluded.trust_level,
            access_method = excluded.access_method,
            status = excluded.status,
            notes = excluded.notes
        """,
        (
            str(row.get("city", "")).strip(),
            str(row.get("source_name", "")).strip(),
            url,
            str(row.get("source_type", "")).strip(),
            str(row.get("trust_level", "")).strip(),
            str(row.get("access_method", "web")).strip().lower(),
            str(row.get("status", "active")).strip().lower(),
            _norm_empty_ts(row.get("last_checked")),
            str(row.get("notes", "") or ""),
        ),
    )
    cur = conn.execute("SELECT id FROM sources WHERE source_url = ?", (url,))
    r = cur.fetchone()
    if not r:
        raise RuntimeError(f"upsert_source failed for {url!r}")
    return int(r[0])


def _norm_empty_ts(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    s = str(v).strip()
    return s or None


def get_source_row(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
    return cur.fetchone()


def update_source_last_checked(conn: sqlite3.Connection, source_id: int, ts: str) -> None:
    conn.execute(
        "UPDATE sources SET last_checked = ? WHERE id = ?",
        (ts, source_id),
    )


def delete_children_for_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM exhibitions WHERE source_id = ?", (source_id,))


def delete_visitor_for_url(conn: sqlite3.Connection, source_url: str) -> None:
    conn.execute("DELETE FROM visitor_info WHERE source_url = ?", (source_url,))


def delete_signals_for_url(conn: sqlite3.Connection, source_url: str) -> None:
    conn.execute("DELETE FROM signals WHERE source_url = ?", (source_url,))


def insert_exhibition(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    city: str,
    institution: str,
    exhibition_title: str,
    artist_names: str,
    start_date: str,
    end_date: str,
    source_url: str,
    raw_text: str,
    public_summary: str,
    last_updated: str,
    fetch_status: str,
    error_detail: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO exhibitions (
            source_id, city, institution, exhibition_title, artist_names,
            start_date, end_date, source_url, raw_text, public_summary,
            last_updated, fetch_status, error_detail
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            source_id,
            city,
            institution,
            exhibition_title,
            artist_names,
            start_date,
            end_date,
            source_url,
            raw_text,
            public_summary,
            last_updated,
            fetch_status,
            error_detail,
        ),
    )
    return int(cur.lastrowid)


def insert_visitor_info(
    conn: sqlite3.Connection,
    *,
    institution: str,
    city: str,
    entry_fee: str,
    audio_guide_available: str,
    audio_guide_languages: str,
    amenities: str,
    source_url: str,
    last_updated: str,
) -> None:
    conn.execute(
        """
        INSERT INTO visitor_info (
            institution, city, entry_fee, audio_guide_available,
            audio_guide_languages, amenities, source_url, last_updated
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            institution,
            city,
            entry_fee,
            audio_guide_available,
            audio_guide_languages,
            amenities,
            source_url,
            last_updated,
        ),
    )


def insert_signals(
    conn: sqlite3.Connection,
    *,
    institution: str,
    city: str,
    google_rating: str | None,
    hashtag_count: str | None,
    mention_count: str | None,
    sentiment_score: str | None,
    source_url: str,
    last_updated: str,
) -> None:
    conn.execute(
        """
        INSERT INTO signals (
            institution, city, google_rating, hashtag_count, mention_count,
            sentiment_score, source_url, last_updated
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            institution,
            city,
            google_rating,
            hashtag_count,
            mention_count,
            sentiment_score,
            source_url,
            last_updated,
        ),
    )


def insert_pulse_score(
    conn: sqlite3.Connection,
    *,
    exhibition_id: int,
    score: float,
    pulse_label: str,
    reason: str,
    human_review_status: str,
    created_at: str,
) -> None:
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
    exhibition_id: int | None = None,
    source_url: str | None = None,
    exhibition_title: str | None = None,
) -> int:
    """Update human_review_status on pulse_scores. Returns rows changed."""
    if exhibition_id is not None:
        cur = conn.execute(
            "UPDATE pulse_scores SET human_review_status = ? WHERE exhibition_id = ?",
            (human_review_status, exhibition_id),
        )
        return int(cur.rowcount or 0)
    if source_url and exhibition_title is not None and str(exhibition_title).strip() != "":
        cur = conn.execute(
            """
            UPDATE pulse_scores SET human_review_status = ?
            WHERE exhibition_id IN (
                SELECT id FROM exhibitions WHERE source_url = ? AND exhibition_title = ?
            )
            """,
            (human_review_status, source_url, exhibition_title),
        )
        return int(cur.rowcount or 0)
    return 0
