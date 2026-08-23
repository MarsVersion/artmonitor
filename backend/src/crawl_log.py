"""Structured crawl error and removal logging."""

from __future__ import annotations

import sqlite3
from typing import Any

from database import now_iso


def log_event(
    conn: sqlite3.Connection,
    *,
    venue_slug: str,
    institution_name: str,
    city: str,
    event_type: str,
    http_status: int | None = None,
    message: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_logs (
            venue_slug, institution_name, city, event_type,
            http_status, message, logged_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            venue_slug,
            institution_name,
            city,
            event_type,
            http_status,
            message[:2000],
            now_iso(),
        ),
    )


def log_removal(
    conn: sqlite3.Connection,
    *,
    venue_slug: str,
    institution_name: str,
    city: str,
    reason: str,
    http_status: int | None = None,
) -> None:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO removed_institutions (
            venue_slug, institution_name, city, reason, http_status, removed_at
        ) VALUES (?,?,?,?,?,?)
        ON CONFLICT(venue_slug) DO UPDATE SET
            reason = excluded.reason,
            http_status = excluded.http_status,
            removed_at = excluded.removed_at
        """,
        (venue_slug, institution_name, city, reason[:2000], http_status, ts),
    )
    log_event(
        conn,
        venue_slug=venue_slug,
        institution_name=institution_name,
        city=city,
        event_type="removal",
        http_status=http_status,
        message=reason,
    )


def increment_failure(conn: sqlite3.Connection, venue_slug: str) -> int:
    conn.execute(
        """
        UPDATE venues SET consecutive_failures = COALESCE(consecutive_failures, 0) + 1
        WHERE slug = ?
        """,
        (venue_slug,),
    )
    cur = conn.execute(
        "SELECT consecutive_failures FROM venues WHERE slug = ?",
        (venue_slug,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 1


def reset_failure(conn: sqlite3.Connection, venue_slug: str) -> None:
    conn.execute(
        "UPDATE venues SET consecutive_failures = 0 WHERE slug = ?",
        (venue_slug,),
    )
