"""
Parse crawled pages into flat exhibition records (one exhibition = one row).

Venue fields are repeated on every record. Artists and curators are JSON arrays.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from html import unescape
from typing import Any

from slugs import exhibition_record_id, slugify

import date_extract
import html_exhibition_parse

RAW_TEXT_CAP = 2000

# Title until DD.MM.YY or Month D – Month D, YYYY
_UNTIL_EU = re.compile(
    r"(?P<title>[A-Za-z0-9À-Ÿ\"«»'''].{4,120}?)\s+until\s+"
    r"(?P<d>\d{1,2})[./](?P<m>\d{1,2})[./](?P<y>\d{2,4})",
    re.IGNORECASE,
)

_TITLE_BEFORE_RANGE = re.compile(
    r"(?P<title>[A-ZÀ-Ÿ][^\n]{3,100}?)\s+"
    r"(?P<range>"
    r"\d{1,2}\s+[A-Za-zÀ-ÿ]+\s*[–—\-]\s*\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+20\d{2}|"
    r"[A-Za-zÀ-ÿ]+\s+\d{1,2},?\s*(?:20\d{2})?\s*[–—\-]\s*[A-Za-zÀ-ÿ]+\s+\d{1,2},?\s*20\d{2}|"
    r"\d{1,2}\.\d{1,2}\.\d{2,4}\s*[–—\-]\s*\d{1,2}\.\d{1,2}\.\d{2,4}|"
    r"through\s+[A-Za-zÀ-ÿ]+\s+\d{1,2},?\s*20\d{2}|"
    r"\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+20\d{2}\s+\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+20\d{2}|"
    r"20\d{2}\.\d{1,2}\.\d{1,2}.*?[–—\-].*?\d{1,2}\.\d{1,2}"
    r")",
    re.I,
)

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _clean(s: str) -> str:
    s = unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _norm_year(y: str) -> str:
    y = y.strip()
    if len(y) == 2:
        yi = int(y)
        return str(2000 + yi if yi < 70 else 1900 + yi)
    return y


def _to_iso(d: str, m: str, y: str) -> str:
    try:
        yy = int(_norm_year(y))
        mm = int(m)
        dd = int(d)
        return date(yy, mm, dd).isoformat()
    except ValueError:
        return ""


def _month_num(token: str) -> int | None:
    return _MONTHS.get(token.strip().lower()[:3])


def _exhibition_status(start: str, end: str, *, today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    s = _parse_date(start)
    e = _parse_date(end)
    if s and today < s:
        return "upcoming"
    if e and today > e:
        return "past"
    if s or e:
        return "current"
    return "current"


def _parse_date(iso: str) -> date | None:
    if not iso or not str(iso).strip():
        return None
    try:
        return date.fromisoformat(str(iso).strip()[:10])
    except ValueError:
        return None


def _split_names(raw: str) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    parts = re.split(r"\s*[,;]\s*|\s+and\s+", raw)
    return [_clean(p) for p in parts if _clean(p)]


def _venue_base(venue: dict[str, Any], *, source_url: str, scraped_at: str) -> dict[str, Any]:
    return {
        "name": venue["name"],
        "city": venue["city"],
        "country": venue["country"],
        "address": venue["address"],
        "category": venue["category"],
        "importance": venue["importance"],
        "website": venue["website"],
        "exhibitions_url": venue.get("exhibitions_url") or venue.get("source_url", ""),
        "crawler": venue["crawler"],
        "source_url": source_url,
        "scraped_at": scraped_at,
        "updated_at": scraped_at,
    }


def build_flat_records(
    venue: dict[str, Any],
    extracted: dict[str, Any],
    fetch: dict[str, Any],
    *,
    scraped_at: str,
    listing_url: str,
) -> list[dict[str, Any]]:
    """Return flat exhibition dicts ready for DB insert / CSV export."""
    fetch_ok = fetch.get("status") == "ok"
    text_ok = bool(extracted.get("ok"))
    base = _venue_base(venue, source_url=listing_url, scraped_at=scraped_at)

    if not fetch_ok or not text_ok:
        err = fetch.get("error") or extracted.get("error") or "fetch/extract failed"
        rid = exhibition_record_id(venue["slug"], "(unavailable)")
        return [
            {
                "id": rid,
                **base,
                "title": str(extracted.get("title") or "").strip() or "(unavailable)",
                "start_date": "",
                "end_date": "",
                "artists": "[]",
                "curators": "[]",
                "status": "current",
                "image_url": "",
                "fetch_status": "error",
                "error_detail": str(err),
            }
        ]

    text = str(extracted.get("text") or "")
    html = str(fetch.get("html") or "")
    candidates = _parse_candidates(text)
    if html:
        structured = html_exhibition_parse.parse_from_html(html, listing_url)
        candidates = _merge_candidates(structured, candidates)

    if not candidates:
        title = str(extracted.get("title") or venue["name"]).strip()
        rid = exhibition_record_id(venue["slug"], title)
        status = _exhibition_status("", "")
        return [
            {
                "id": rid,
                **base,
                "title": title[:200],
                "start_date": "",
                "end_date": "",
                "artists": "[]",
                "curators": "[]",
                "status": status,
                "image_url": "",
                "fetch_status": "ok",
                "error_detail": "",
            }
        ]

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in candidates[:15]:
        title = c["title"][:200]
        rid = exhibition_record_id(
            venue["slug"],
            title,
            c.get("start_date", ""),
            c.get("end_date", ""),
        )
        if rid in seen:
            continue
        seen.add(rid)
        status = _exhibition_status(c.get("start_date", ""), c.get("end_date", ""))
        records.append(
            {
                "id": rid,
                **base,
                "title": title,
                "start_date": c.get("start_date", ""),
                "end_date": c.get("end_date", ""),
                "artists": json.dumps(c.get("artists") or [], ensure_ascii=False),
                "curators": json.dumps(c.get("curators") or [], ensure_ascii=False),
                "status": status,
                "image_url": c.get("image_url", ""),
                "exhibition_url": c.get("exhibition_url", "") or listing_url,
                "date_citation": c.get("date_citation", ""),
                "fetch_status": "ok",
                "error_detail": "",
            }
        )
    return records


def _parse_candidates(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for m in _UNTIL_EU.finditer(text):
        title = _clean(m.group("title"))
        end = _to_iso(m.group("d"), m.group("m"), m.group("y"))
        artists = _guess_artists_from_title(title)
        if title and not html_exhibition_parse._is_nav_title(title):
            out.append(
                {
                    "title": title,
                    "start_date": "",
                    "end_date": end,
                    "artists": artists,
                    "curators": [],
                    "image_url": "",
                    "date_citation": _clean(m.group(0))[:160],
                }
            )

    for m in _TITLE_BEFORE_RANGE.finditer(text):
        title = _clean(m.group("title"))
        if html_exhibition_parse._is_nav_title(title):
            continue
        hit = date_extract.extract_date_range(m.group("range"))
        if not (hit["start_date"] or hit["end_date"]):
            continue
        out.append(
            {
                "title": title,
                "start_date": hit["start_date"],
                "end_date": hit["end_date"],
                "artists": _guess_artists_from_title(title),
                "curators": [],
                "image_url": "",
                "date_citation": hit["date_citation"] or _clean(m.group("range"))[:160],
            }
        )

    return out


def _merge_candidates(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer structured/HTML hits; fill gaps from regex text parsing."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for c in primary + secondary:
        key = (c.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        if html_exhibition_parse._is_nav_title(key):
            continue
        seen.add(key)
        merged.append(c)
    # Prefer dated records first; if any dated exist, drop undated noise
    dated = [c for c in merged if c.get("start_date") or c.get("end_date")]
    undated = [c for c in merged if not (c.get("start_date") or c.get("end_date"))]
    return dated + undated if not dated else dated


def _guess_artists_from_title(title: str) -> list[str]:
    """Heuristic: 'Artist Name — Exhibition Title' or leading proper name."""
    if "—" in title or "–" in title:
        left = re.split(r"[—–]", title, maxsplit=1)[0].strip()
        if 2 <= len(left.split()) <= 5:
            return [left]
    m = re.match(r"^([A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){0,3})\s", title)
    if m:
        return [m.group(1).strip()]
    return []
