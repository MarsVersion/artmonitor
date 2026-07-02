"""Export SQLite snapshots to CSV files under backend/data/."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from database import (
    EXHIBITIONS_CSV,
    PULSE_CSV,
    SIGNALS_CSV,
    VISITOR_CSV,
)


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
    """
    Write exhibitions, visitor_info, signals, and denormalized pulse_updates CSVs.
    """
    counts: dict[str, int] = {}

    counts["exhibitions"] = _write_query_csv(
        conn,
        """
        SELECT
            id, source_id, city, institution, exhibition_title, artist_names,
            start_date, end_date, source_url,
            SUBSTR(raw_text, 1, 1200) AS raw_text,
            last_updated, fetch_status, error_detail
        FROM exhibitions
        ORDER BY city, institution, id
        """,
        (),
        EXHIBITIONS_CSV,
    )

    counts["visitor_info"] = _write_query_csv(
        conn,
        """
        SELECT
            id, institution, city, entry_fee, audio_guide_available,
            audio_guide_languages, amenities, source_url, last_updated
        FROM visitor_info
        ORDER BY city, institution, id
        """,
        (),
        VISITOR_CSV,
    )

    counts["signals"] = _write_query_csv(
        conn,
        """
        SELECT
            id, institution, city, google_rating, hashtag_count, mention_count,
            sentiment_score, source_url, last_updated
        FROM signals
        ORDER BY city, institution, id
        """,
        (),
        SIGNALS_CSV,
    )

    counts["pulse_updates"] = _write_query_csv(
        conn,
        """
        SELECT
            e.id AS exhibition_id,
            e.city,
            e.institution,
            e.exhibition_title,
            e.artist_names,
            e.start_date,
            e.end_date,
            ps.pulse_label,
            ps.score,
            ps.reason,
            ps.human_review_status,
            e.public_summary,
            v.entry_fee,
            v.audio_guide_available,
            v.audio_guide_languages,
            v.amenities,
            s.google_rating,
            s.hashtag_count,
            s.mention_count,
            s.sentiment_score,
            e.fetch_status,
            e.error_detail,
            e.source_url
        FROM pulse_scores ps
        JOIN exhibitions e ON e.id = ps.exhibition_id
        LEFT JOIN visitor_info v
            ON v.source_url = e.source_url
            AND v.institution = e.institution
            AND v.city = e.city
        LEFT JOIN signals s
            ON s.source_url = e.source_url
            AND s.institution = e.institution
            AND s.city = e.city
        ORDER BY e.city, ps.pulse_label, ps.score DESC, e.institution
        """,
        (),
        PULSE_CSV,
    )

    return counts
