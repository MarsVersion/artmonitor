"""Export flat exhibition records and pulse joins to CSV."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from database import (
    EXHIBITIONS_CSV,
    FLAT_EXHIBITIONS_CSV,
    PULSE_CSV,
    ROOT_DATA_DIR,
    SOURCES_CSV,
)

FLAT_FIELDS = [
    "id",
    "name",
    "city",
    "country",
    "address",
    "category",
    "importance",
    "website",
    "exhibitions_url",
    "title",
    "start_date",
    "end_date",
    "artists",
    "curators",
    "status",
    "image_url",
    "source_url",
    "crawler",
    "scraped_at",
    "updated_at",
]


def _write_query_csv(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple,
    path: Path,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(list(r))
    return len(rows)


def export_all_csvs(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}

    flat_sql = f"""
        SELECT {", ".join(FLAT_FIELDS)}
        FROM exhibitions
        ORDER BY city, name, start_date, title
    """
    counts["exhibitions"] = _write_query_csv(conn, flat_sql, (), EXHIBITIONS_CSV)
    counts["flat_exhibitions"] = _write_query_csv(
        conn, flat_sql, (), FLAT_EXHIBITIONS_CSV
    )

    counts["pulse_updates"] = _write_query_csv(
        conn,
        """
        SELECT
            e.id AS exhibition_id,
            e.title AS exhibition_title,
            e.name AS institution,
            e.city,
            e.country,
            e.category,
            e.importance,
            e.title,
            e.start_date,
            e.end_date,
            e.artists,
            e.curators,
            e.status,
            e.image_url,
            e.source_url,
            e.exhibitions_url,
            e.website,
            e.crawler,
            e.scraped_at,
            e.updated_at,
            e.fetch_status,
            e.error_detail,
            ps.pulse_label,
            ps.score,
            ps.reason,
            ps.human_review_status
        FROM pulse_scores ps
        JOIN exhibitions e ON e.id = ps.exhibition_id
        ORDER BY e.city, ps.pulse_label, ps.score DESC, e.name
        """,
        (),
        PULSE_CSV,
    )

    _export_venues(conn, ROOT_DATA_DIR / "sources.csv")
    _export_venues(conn, SOURCES_CSV)
    return counts


def _export_venues(conn: sqlite3.Connection, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = conn.execute(
        """
        SELECT slug, name, city, country, address, category, importance,
               website, exhibitions_url, crawler, status
        FROM venues
        WHERE lower(COALESCE(status, 'active')) IN ('active', 'manual')
        ORDER BY city, name
        """
    )
    rows = cur.fetchall()
    fields = [d[0] for d in cur.description] if cur.description else []
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(dict(r))
