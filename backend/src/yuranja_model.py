"""Yuranja exhibition record shape, citations, and stable dedupe keys."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

from exhibition_enrich import infer_format, parse_admission
from slugs import exhibition_record_id, slugify


def normalize_for_dedupe(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def dedupe_key(institution: str, title: str, start_date: str) -> str:
    start = (start_date or "").strip()[:10] or "unknown"
    return "|".join(
        [
            normalize_for_dedupe(institution),
            normalize_for_dedupe(title),
            start,
        ]
    )


def citation(
    *,
    field: str,
    url: str,
    checked_at: str,
    note: str = "",
) -> dict[str, str]:
    return {
        "field": field,
        "url": (url or "").strip(),
        "checkedAt": (checked_at or "")[:10],
        "note": note,
    }


def _parse_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
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


def _today() -> date:
    return datetime.now(timezone.utc).date()


def lifecycle_status(start_date: str, end_date: str, *, today: date | None = None) -> str:
    today = today or _today()
    try:
        start = date.fromisoformat(start_date[:10]) if start_date else None
    except ValueError:
        start = None
    try:
        end = date.fromisoformat(end_date[:10]) if end_date else None
    except ValueError:
        end = None
    if end and today > end:
        return "past"
    if start and today < start:
        return "upcoming"
    if start or end:
        return "current"
    return "current"


def build_yuranja_record(
    flat: dict[str, Any],
    *,
    venue: dict[str, Any],
    visitor: dict[str, Any] | None = None,
    checked_at: str,
    editorial_status: str = "pending",
) -> dict[str, Any]:
    """Build a Yuranja-shaped exhibition dict from a flat crawl row.

    Missing facts stay empty or unknown — never invented.
    """
    title = str(flat.get("title") or "").strip()
    institution = str(flat.get("name") or venue.get("name") or "").strip()
    city = str(flat.get("city") or venue.get("city") or "").strip()
    country = str(flat.get("country") or venue.get("country") or "").strip()
    address = str(flat.get("address") or venue.get("address") or "").strip()
    start_date = str(flat.get("start_date") or "").strip()
    end_date = str(flat.get("end_date") or "").strip()
    artists = _parse_list(flat.get("artists"))
    curators = _parse_list(flat.get("curators"))
    source_url = str(flat.get("source_url") or venue.get("exhibitions_url") or "").strip()
    website = str(flat.get("website") or venue.get("website") or "").strip()
    exhibition_url = str(flat.get("exhibition_url") or source_url).strip()
    opening_hours = str(flat.get("opening_hours") or flat.get("openingHours") or "").strip()
    description = str(flat.get("description") or "").strip()
    date_citation = str(flat.get("date_citation") or "").strip()
    fmt = str(flat.get("format") or "").strip() or infer_format(artists, title)
    categories = _parse_list(flat.get("categories"))
    media_types = _parse_list(flat.get("media_types") or flat.get("mediaTypes"))

    entry_fee = ""
    amenities = ""
    ticket_url = ""
    visitor_checked = checked_at
    if visitor:
        entry_fee = str(visitor.get("entry_fee") or "").strip()
        amenities = str(visitor.get("amenities") or "").strip()
        ticket_url = str(visitor.get("ticket_url") or "").strip()
        visitor_checked = str(visitor.get("last_updated") or checked_at).strip()

    admission = parse_admission(entry_fee, amenities, visitor_checked)
    if not ticket_url:
        ticket_url = str(admission.get("ticketUrl") or "").strip()

    status = lifecycle_status(start_date, end_date)
    archive_status = "archived" if status == "past" else "active"
    rid = str(flat.get("id") or "").strip() or exhibition_record_id(
        venue.get("slug", slugify(institution)),
        title,
        start_date,
        end_date,
    )
    key = dedupe_key(institution, title, start_date)
    checked = (checked_at or "")[:10]

    citations: list[dict[str, str]] = []
    if title and source_url:
        citations.append(citation(field="title", url=exhibition_url or source_url, checked_at=checked))
    if artists and source_url:
        citations.append(citation(field="artists", url=exhibition_url or source_url, checked_at=checked))
    if curators and source_url:
        citations.append(citation(field="curators", url=exhibition_url or source_url, checked_at=checked))
    if start_date or end_date:
        date_note = date_citation or str(flat.get("date_citation") or "").strip()
        citations.append(
            citation(
                field="dates",
                url=exhibition_url or source_url,
                checked_at=checked,
                note=date_note or "official listing page",
            )
        )
    if address:
        citations.append(
            citation(
                field="address",
                url=website or source_url,
                checked_at=checked,
                note="institution registry / official site",
            )
        )
    if opening_hours:
        citations.append(citation(field="openingHours", url=website or source_url, checked_at=checked))
    if admission.get("status") != "unknown":
        citations.append(
            citation(
                field="admission",
                url=ticket_url or website or source_url,
                checked_at=admission.get("checkedAt") or checked,
                note="verified visitor information",
            )
        )

    return {
        "id": rid,
        "slug": slugify(f"{institution}-{title}")[:80] or rid,
        "title": title,
        "artists": artists,
        "curators": curators,
        "venue": institution,
        "venue_slug": venue.get("slug", ""),
        "city": city,
        "country": country,
        "dates": {"start": start_date, "end": end_date},
        "address": address,
        "openingHours": opening_hours,
        "website": website,
        "description": description,
        "yuranjaNote": "",
        "format": fmt,
        "categories": categories,
        "mediaTypes": media_types,
        "admission": {
            "status": admission.get("status", "unknown"),
            "display": admission.get("display", "Check current admission"),
            "fromPrice": admission.get("fromPrice", ""),
            "reservationRequired": bool(admission.get("reservationRequired")),
            "ticketUrl": ticket_url,
            "checkedAt": admission.get("checkedAt", ""),
        },
        "tags": [],
        "amenities": amenities,
        "exhibitionUrl": exhibition_url,
        "source_url": source_url,
        "status": status,
        "archive_status": archive_status,
        "editorial_status": editorial_status or "pending",
        "dedupe_key": key,
        "is_duplicate": False,
        "citations": citations,
        "dateChecked": checked,
        "fetch_status": str(flat.get("fetch_status") or ""),
        "error_detail": str(flat.get("error_detail") or ""),
        "scraped_at": str(flat.get("scraped_at") or checked_at),
        "updated_at": str(flat.get("updated_at") or checked_at),
    }


def missing_required_fields(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not record.get("title"):
        missing.append("title")
    if not record.get("venue"):
        missing.append("venue")
    if not record.get("city"):
        missing.append("city")
    if not record.get("exhibitionUrl") and not record.get("source_url"):
        missing.append("exhibitionUrl")
    dates = record.get("dates") or {}
    if not dates.get("start") and not dates.get("end"):
        missing.append("dates")
    admission = record.get("admission") or {}
    if admission.get("status") == "unknown":
        missing.append("admission")
    if not record.get("citations"):
        missing.append("citations")
    return missing


def to_export_shape(record: dict[str, Any]) -> dict[str, Any]:
    """Public Yuranja export object — approved records only."""
    return {
        "slug": record.get("slug"),
        "title": record.get("title"),
        "artists": record.get("artists") or [],
        "curators": record.get("curators") or [],
        "venue": record.get("venue"),
        "city": record.get("city"),
        "dates": record.get("dates") or {"start": "", "end": ""},
        "address": record.get("address") or "",
        "openingHours": record.get("openingHours") or "",
        "website": record.get("website") or "",
        "description": record.get("description") or "",
        "yuranjaNote": record.get("yuranjaNote") or "",
        "format": record.get("format") or "",
        "categories": record.get("categories") or [],
        "mediaTypes": record.get("mediaTypes") or [],
        "admission": record.get("admission")
        or {
            "status": "unknown",
            "display": "Check current admission",
        },
        "tags": record.get("tags") or [],
        "citations": record.get("citations") or [],
        "exhibitionUrl": record.get("exhibitionUrl") or record.get("source_url") or "",
        "dateChecked": record.get("dateChecked") or "",
        "country": record.get("country") or "",
    }
