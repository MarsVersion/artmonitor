"""Export approved Yuranja exhibition records for the public site."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import database
import yuranja_model
from slugs import slugify

EXPORT_PATH = database.ROOT_DATA_DIR / "yuranja_exhibitions.json"


def _row_to_record(row: Any) -> dict[str, Any]:
    citations = []
    raw_citations = row["citations_json"] if "citations_json" in row.keys() else ""
    if raw_citations:
        try:
            citations = json.loads(raw_citations)
        except json.JSONDecodeError:
            citations = []

    def _list(raw: Any) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                pass
        return [text]

    admission = {
        "status": str(row["admission_status"] or "unknown"),
        "display": str(row["admission_display"] or "Check current admission"),
        "fromPrice": str(row["admission_from_price"] or ""),
        "reservationRequired": bool(row["admission_reservation_required"]),
        "ticketUrl": str(row["admission_ticket_url"] or ""),
        "checkedAt": str(row["admission_checked_at"] or ""),
    }
    return {
        "id": row["id"],
        "slug": slugify(f"{row['name']}-{row['title']}")[:80],
        "title": row["title"],
        "artists": _list(row["artists"]),
        "curators": _list(row["curators"]),
        "venue": row["name"],
        "city": row["city"],
        "country": row["country"],
        "dates": {"start": row["start_date"] or "", "end": row["end_date"] or ""},
        "address": row["address"] or "",
        "openingHours": row["opening_hours"] or "",
        "website": row["website"] or "",
        "description": row["description"] or "",
        "yuranjaNote": "",
        "format": row["format"] or "",
        "categories": _list(row["categories"]),
        "mediaTypes": _list(row["media_types"]),
        "admission": admission,
        "tags": [],
        "citations": citations,
        "exhibitionUrl": row["exhibition_url"] or row["source_url"] or "",
        "source_url": row["source_url"] or "",
        "dateChecked": row["date_checked"] or "",
        "status": row["status"] or "",
        "archive_status": row["archive_status"] or "active",
        "editorial_status": row["editorial_status"] or "pending",
        "is_duplicate": bool(row["is_duplicate"]),
    }


def export_yuranja(*, path: Path | None = None) -> dict[str, Any]:
    out = path or EXPORT_PATH
    conn = database.connect()
    database.init_schema(conn)

    rows = conn.execute(
        """
        SELECT *
        FROM exhibitions
        WHERE lower(COALESCE(editorial_status, 'pending')) = 'approved'
          AND lower(COALESCE(archive_status, 'active')) = 'active'
          AND COALESCE(is_duplicate, 0) = 0
          AND lower(COALESCE(status, '')) IN ('current', 'upcoming')
          AND COALESCE(trim(title), '') NOT IN ('', '(unavailable)')
        ORDER BY city, name, start_date, title
        """
    ).fetchall()

    exhibitions = [yuranja_model.to_export_shape(_row_to_record(row)) for row in rows]
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": database.now_iso(),
        "count": len(exhibitions),
        "exhibitions": exhibitions,
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    msg = f"Exported {len(exhibitions)} approved exhibitions to {out}"
    print(msg)
    return {"success": True, "message": msg, "path": str(out), "count": len(exhibitions)}
