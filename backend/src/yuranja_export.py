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
import admission_links
import yuranja_candidates as yc
import yuranja_model as ym
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

    status = str(row["admission_status"] or "unknown")
    reservation_raw = row["admission_reservation_required"] if "admission_reservation_required" in row.keys() else None
    if status.casefold() == "unknown":
        reservation_value = None
    else:
        reservation_value = bool(reservation_raw)

    info_url = ""
    info_label = ""
    if "admission_information_url" in row.keys():
        info_url = str(row["admission_information_url"] or "")
    if "admission_information_label" in row.keys():
        info_label = str(row["admission_information_label"] or "")

    admission = {
        "status": status,
        "display": str(
            row["admission_display"]
            or "Admission not published — check the official visitor information"
        ),
        "fromPrice": str(row["admission_from_price"] or ""),
        "reservationRequired": reservation_value,
        "ticketUrl": str(row["admission_ticket_url"] or ""),
        "informationUrl": info_url,
        "informationLabel": info_label,
        "checkedAt": str(row["admission_checked_at"] or ""),
    }
    ex_url = str(row["exhibition_url"] or row["source_url"] or "").strip()
    website = str(row["website"] or "").strip()
    admission = admission_links.ensure_admission_links(
        admission,
        exhibition_url=ex_url,
        website=website,
        checked_at=str(row["date_checked"] or ""),
        validate_reachability=True,
    )
    slug = str(row["candidate_slug"] or "").strip() or slugify(f"{row['name']}-{row['title']}")[:80]
    record = {
        "id": row["id"],
        "slug": slug,
        "title": row["title"],
        "artists": _list(row["artists"]),
        "curators": _list(row["curators"]),
        "venue": row["name"],
        "city": row["city"],
        "country": row["country"],
        "dates": {"start": row["start_date"] or "", "end": row["end_date"] or ""},
        "address": row["address"] or "",
        "openingHours": row["opening_hours"] or "",
        "website": ex_url,
        "description": row["description"] or "",
        "yuranjaNote": "",
        "format": row["format"] or "",
        "categories": _list(row["categories"]),
        "mediaTypes": _list(row["media_types"]),
        "admission": admission,
        "tags": [],
        "citations": yc.yuranja_citations(
            {
                "venue": row["name"],
                "title": row["title"],
                "artists": _list(row["artists"]),
                "description": row["description"],
                "exhibitionUrl": ex_url,
                "website": website,
                "admission": admission,
                "citations": citations,
                "dateChecked": row["date_checked"] or "",
            },
            checked_at=str(row["date_checked"] or "")[:10] or yc._today_iso(),
        ),
        "exhibitionUrl": ex_url,
        "source_url": row["source_url"] or "",
        "dateChecked": row["date_checked"] or "",
        "status": row["status"] or "",
        "archive_status": row["archive_status"] or "active",
        "editorial_status": row["editorial_status"] or "pending",
        "is_duplicate": bool(row["is_duplicate"]),
    }
    if not record["description"]:
        record["description"] = yc.build_description(record)
    return record


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
          AND COALESCE(trim(start_date), '') != ''
          AND COALESCE(trim(end_date), '') != ''
          AND COALESCE(trim(exhibition_url), '') != ''
        ORDER BY city, name, start_date, title
        """
    ).fetchall()

    exhibitions: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        record = _row_to_record(row)
        if not ym.export_eligible(record):
            skipped += 1
            continue
        exhibitions.append(ym.to_export_shape(record))

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": database.now_iso(),
        "count": len(exhibitions),
        "exhibitions": exhibitions,
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    msg = f"Exported {len(exhibitions)} approved exhibitions to {out}"
    if skipped:
        msg += f" ({skipped} approved rows failed export validation)"
    print(msg)
    return {
        "success": True,
        "message": msg,
        "path": str(out),
        "count": len(exhibitions),
        "skipped": skipped,
    }
