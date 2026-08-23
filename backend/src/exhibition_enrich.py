"""Enrich flat exhibition rows with visitor info and Yuranja-shaped fields."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import database

INSTITUTION_SUFFIXES = (
    " – nationalgalerie der gegenwart",
    " - nationalgalerie der gegenwart",
    " nationalgalerie der gegenwart",
    " – centre for contemporary art",
    " - centre for contemporary art",
    " museum of art",
    " museum",
    " gallery",
    " galerie",
    " kunsthalle",
    " institute of contemporary arts",
    " (ica london)",
    " (ica)",
)

FREE_HINT = re.compile(r"\bfree\b", re.I)
PRICE_HINT = re.compile(
    r"(€|\$|£|¥|kr|hk\$|chf)\s*[\d,.]+|[\d,.]+\s*(€|\$|£|¥|kr|hk\$|chf)|"
    r"\b(?:eur|usd|gbp|hkd)\s*[\d,.]+\b",
    re.I,
)
RESERVATION_HINT = re.compile(r"\breservation\b", re.I)

ADMISSION_QUERY = re.compile(
    r"\b(?:entrance|entry|admission|ticket)\s+(?:fee|fees|price|cost|prices)\b|"
    r"\b(?:entrance|entry)\s+fee\b|"
    r"\badmission\s+cost\b|"
    r"\bticket\s+price\b|"
    r"\b(?:admission|entrance|entry)\b",
    re.I,
)
FREE_ADMISSION_QUERY = re.compile(
    r"\bfree\s+(?:admission|entrance|entry)\b|\bfree\s+entry\b",
    re.I,
)
PAID_ADMISSION_QUERY = re.compile(
    r"\bpaid\s+(?:admission|entrance|entry)\b|\bpaid\s+admission\b",
    re.I,
)


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_key(value: Any) -> str:
    return normalize_text(value).casefold()


def normalize_institution(name: str) -> str:
    """Lowercase key with punctuation/spacing/suffix normalisation."""
    text = normalize_key(name)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in INSTITUTION_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def normalize_url(url: str) -> str:
    text = normalize_key(url)
    return text.rstrip("/")


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [normalize_text(x) for x in raw if normalize_text(x)]
    text = normalize_text(raw)
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [normalize_text(x) for x in parsed if normalize_text(x)]
        except json.JSONDecodeError:
            pass
    return [text] if text else []


def parse_admission(entry_fee: str, amenities: str = "", last_updated: str = "") -> dict[str, Any]:
    fee = normalize_text(entry_fee)
    fee_lower = fee.casefold()
    amenities_text = normalize_text(amenities)
    reservation_required = bool(RESERVATION_HINT.search(fee) or RESERVATION_HINT.search(amenities_text))

    if not fee or fee_lower in {"unknown", "n/a", "na", "check current admission"}:
        return {
            "status": "unknown",
            "display": "Check current admission",
            "fromPrice": "",
            "reservationRequired": reservation_required,
            "ticketUrl": "",
            "checkedAt": _checked_at(last_updated),
        }

    if FREE_HINT.search(fee) and not PRICE_HINT.search(fee):
        display = fee if fee else "Free admission"
        return {
            "status": "free",
            "display": display,
            "fromPrice": "",
            "reservationRequired": reservation_required,
            "ticketUrl": "",
            "checkedAt": _checked_at(last_updated),
        }

    if "included" in fee_lower:
        price_match = PRICE_HINT.search(fee)
        return {
            "status": "included",
            "display": fee,
            "fromPrice": price_match.group(0) if price_match else "",
            "reservationRequired": reservation_required,
            "ticketUrl": "",
            "checkedAt": _checked_at(last_updated),
        }

    if reservation_required and not PRICE_HINT.search(fee) and not FREE_HINT.search(fee):
        return {
            "status": "reservation-required",
            "display": fee or "Reservation required",
            "fromPrice": "",
            "reservationRequired": True,
            "ticketUrl": "",
            "checkedAt": _checked_at(last_updated),
        }

    price_match = PRICE_HINT.search(fee)
    return {
        "status": "paid",
        "display": fee,
        "fromPrice": price_match.group(0) if price_match else "",
        "reservationRequired": reservation_required,
        "ticketUrl": "",
        "checkedAt": _checked_at(last_updated),
    }


def _checked_at(last_updated: str) -> str:
    text = normalize_text(last_updated)
    if not text:
        return ""
    return text[:10] if len(text) >= 10 else text


def infer_format(artists: list[str], title: str = "") -> str:
    if len(artists) == 1:
        return "solo"
    if len(artists) > 1:
        return "group"
    title_lower = title.casefold()
    if "group exhibition" in title_lower or title_lower.startswith("group "):
        return "group"
    return ""


class VisitorIndex:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.by_url: dict[str, dict[str, Any]] = {}
        self.by_venue_city: dict[tuple[str, str], dict[str, Any]] = {}
        self.by_venue_norm: dict[str, dict[str, Any]] = {}
        for row in rows:
            url = normalize_url(row.get("source_url", ""))
            city = normalize_key(row.get("city"))
            venue_norm = normalize_institution(row.get("institution", ""))
            if url:
                self.by_url[url] = row
            if venue_norm:
                self.by_venue_norm.setdefault(venue_norm, row)
                self.by_venue_city[(venue_norm, city)] = row

    def lookup(self, *, source_url: str, institution: str, city: str, exhibitions_url: str = "") -> dict[str, Any] | None:
        for url in (source_url, exhibitions_url):
            key = normalize_url(url)
            if key and key in self.by_url:
                return self.by_url[key]
        venue_norm = normalize_institution(institution)
        city_key = normalize_key(city)
        if venue_norm:
            match = self.by_venue_city.get((venue_norm, city_key))
            if match:
                return match
            match = self.by_venue_norm.get(venue_norm)
            if match:
                return match
        return None


def load_visitor_index(path: Path | None = None) -> VisitorIndex:
    csv_path = path or database.VISITOR_CSV
    rows: list[dict[str, Any]] = []
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
    return VisitorIndex(rows)


def load_exhibition_rows(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    if conn is not None:
        cur = conn.execute(
            """
            SELECT *
            FROM exhibitions
            ORDER BY city, name, start_date, title
            """
        )
        return [dict(row) for row in cur.fetchall()]

    if database.EXHIBITIONS_CSV.is_file():
        with database.EXHIBITIONS_CSV.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    return []


def enrich_exhibition_row(row: dict[str, Any], visitor_index: VisitorIndex) -> dict[str, Any]:
    institution = normalize_text(row.get("name") or row.get("institution"))
    city = normalize_text(row.get("city"))
    country = normalize_text(row.get("country"))
    source_url = normalize_text(row.get("source_url"))
    exhibitions_url = normalize_text(row.get("exhibitions_url"))
    title = normalize_text(row.get("title") or row.get("exhibition_title"))
    artists = _parse_json_list(row.get("artists") or row.get("artist_names"))
    curators = _parse_json_list(row.get("curators"))
    slug = normalize_text(row.get("id") or row.get("slug"))
    fmt = infer_format(artists, title)

    visitor = visitor_index.lookup(
        source_url=source_url,
        institution=institution,
        city=city,
        exhibitions_url=exhibitions_url,
    )
    entry_fee = normalize_text(
        row.get("admission_display")
        or (visitor.get("entry_fee") if visitor else "")
        or row.get("entry_fee")
    )
    amenities = normalize_text(
        row.get("amenities")
        or (visitor.get("amenities") if visitor else "")
    )
    audio_guide = normalize_text(
        visitor.get("audio_guide_available") if visitor else row.get("audio_guide_available")
    )
    audio_langs = normalize_text(
        visitor.get("audio_guide_languages") if visitor else row.get("audio_guide_languages")
    )
    visitor_checked = normalize_text(
        row.get("admission_checked_at")
        or row.get("date_checked")
        or (visitor.get("last_updated") if visitor else "")
        or row.get("last_updated")
    )
    if normalize_text(row.get("admission_status")):
        admission = {
            "status": normalize_text(row.get("admission_status")),
            "display": entry_fee or "Check current admission",
            "fromPrice": normalize_text(row.get("admission_from_price")),
            "reservationRequired": bool(row.get("admission_reservation_required")),
            "ticketUrl": normalize_text(row.get("admission_ticket_url")),
            "checkedAt": visitor_checked[:10] if visitor_checked else "",
        }
    else:
        admission = parse_admission(entry_fee, amenities, visitor_checked)

    public_summary = normalize_text(row.get("public_summary") or row.get("reason") or row.get("description"))
    yuranja_note = normalize_text(row.get("yuranjaNote") or row.get("yuranja_note"))
    citations_raw = row.get("citations_json") or row.get("citations") or []
    if isinstance(citations_raw, str) and citations_raw.strip().startswith("["):
        try:
            citations = json.loads(citations_raw)
        except json.JSONDecodeError:
            citations = []
    elif isinstance(citations_raw, list):
        citations = citations_raw
    else:
        citations = []

    return {
        "slug": slug,
        "title": title,
        "artists": artists,
        "curators": curators,
        "venue": institution,
        "city": city,
        "country": country,
        "dates": {
            "start": normalize_text(row.get("start_date")),
            "end": normalize_text(row.get("end_date")),
        },
        "address": normalize_text(row.get("address")),
        "openingHours": normalize_text(row.get("opening_hours") or row.get("openingHours")),
        "website": normalize_text(row.get("website")),
        "description": normalize_text(row.get("description")),
        "yuranjaNote": yuranja_note,
        "public_summary": public_summary,
        "format": fmt or normalize_text(row.get("format")),
        "categories": _parse_json_list(row.get("categories")),
        "mediaTypes": _parse_json_list(row.get("media_types") or row.get("mediaTypes")),
        "admission": admission,
        "tags": _parse_json_list(row.get("tags")),
        "amenities": amenities,
        "audio_guide_available": audio_guide,
        "audio_guide_languages": audio_langs,
        "source_url": source_url or exhibitions_url,
        "exhibitions_url": exhibitions_url,
        "exhibitionUrl": normalize_text(row.get("exhibition_url") or source_url or exhibitions_url),
        "status": normalize_text(row.get("status")),
        "category": normalize_text(row.get("category")),
        "importance": normalize_text(row.get("importance")),
        "image_url": normalize_text(row.get("image_url")),
        "fetch_status": normalize_text(row.get("fetch_status")),
        "error_detail": normalize_text(row.get("error_detail")),
        "entry_fee": entry_fee,
        "visitor_last_updated": visitor_checked,
        "pulse_label": normalize_text(row.get("pulse_label")),
        "score": row.get("score"),
        "human_review_status": normalize_text(
            row.get("editorial_status") or row.get("human_review_status")
        ),
        "editorial_status": normalize_text(row.get("editorial_status") or "pending"),
        "archive_status": normalize_text(row.get("archive_status") or "active"),
        "citations": citations,
        "dateChecked": normalize_text(row.get("date_checked") or visitor_checked)[:10],
        "exhibition_id": normalize_text(row.get("exhibition_id") or row.get("id")),
    }


def enrich_rows(rows: list[dict[str, Any]], visitor_index: VisitorIndex | None = None) -> list[dict[str, Any]]:
    index = visitor_index or load_visitor_index()
    return [enrich_exhibition_row(row, index) for row in rows]


def parse_inquiry_intent(query: str) -> dict[str, bool]:
    needle = normalize_text(query).casefold()
    asks_for_admission = bool(ADMISSION_QUERY.search(needle))
    asks_for_free = bool(FREE_ADMISSION_QUERY.search(needle))
    asks_for_paid = bool(PAID_ADMISSION_QUERY.search(needle))
    asks_for_known = asks_for_admission and not asks_for_free and not asks_for_paid
    return {
        "asks_for_admission": asks_for_admission,
        "asks_for_free": asks_for_free,
        "asks_for_paid": asks_for_paid,
        "asks_for_known": asks_for_known,
    }


def admission_status(row: dict[str, Any]) -> str:
    admission = row.get("admission") or {}
    if isinstance(admission, dict):
        return normalize_text(admission.get("status")).casefold() or "unknown"
    return "unknown"


def admission_known(row: dict[str, Any]) -> bool:
    return admission_status(row) not in {"", "unknown"}


def admission_is_free(row: dict[str, Any]) -> bool:
    return admission_status(row) == "free"


def admission_is_paid(row: dict[str, Any]) -> bool:
    return admission_status(row) in {"paid", "included", "reservation-required"}


def admission_reservation_required(row: dict[str, Any]) -> bool:
    admission = row.get("admission") or {}
    if isinstance(admission, dict) and admission.get("reservationRequired"):
        return True
    return admission_status(row) == "reservation-required"


def searchable_text(row: dict[str, Any]) -> str:
    admission = row.get("admission") or {}
    parts = [
        row.get("city"),
        row.get("country"),
        row.get("title"),
        row.get("venue"),
        row.get("format"),
        row.get("category"),
        row.get("public_summary"),
        row.get("description"),
        row.get("yuranjaNote"),
        row.get("entry_fee"),
        row.get("amenities"),
        admission.get("display") if isinstance(admission, dict) else "",
        admission.get("status") if isinstance(admission, dict) else "",
        " ".join(row.get("artists") or []),
        " ".join(row.get("curators") or []),
        " ".join(row.get("categories") or []),
        " ".join(row.get("mediaTypes") or []),
        " ".join(row.get("tags") or []),
    ]
    return " ".join(normalize_text(part) for part in parts if normalize_text(part)).casefold()


def matches_admission_filter(row: dict[str, Any], admission_filter: str) -> bool:
    value = normalize_key(admission_filter)
    if not value or value == "all":
        return True
    if value == "free":
        return admission_is_free(row)
    if value == "paid":
        return admission_is_paid(row)
    if value == "known":
        return admission_known(row)
    if value == "unknown":
        return not admission_known(row)
    if value in {"reservation", "reservation-required", "reservation_required"}:
        return admission_reservation_required(row)
    return True


def matches_inquiry(row: dict[str, Any], query: str) -> bool:
    needle = normalize_text(query).casefold()
    if not needle:
        return True

    intent = parse_inquiry_intent(query)
    if intent["asks_for_free"]:
        return admission_is_free(row)
    if intent["asks_for_paid"]:
        return admission_is_paid(row)
    if intent["asks_for_known"]:
        return admission_known(row)

    haystack = searchable_text(row)
    tokens = [token for token in re.split(r"\s+", needle) if token]
    return all(token in haystack for token in tokens)


def filter_exhibitions(
    rows: list[dict[str, Any]],
    *,
    query: str = "",
    city: str = "",
    admission: str = "all",
) -> list[dict[str, Any]]:
    city_filter = normalize_text(city)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if city_filter and city_filter.casefold() != "all":
            if normalize_text(row.get("city")).casefold() != city_filter.casefold():
                continue
        if not matches_admission_filter(row, admission):
            continue
        if not matches_inquiry(row, query):
            continue
        filtered.append(row)
    return filtered
