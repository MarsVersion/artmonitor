"""Build curated Yuranja exhibition candidates from verified Artmonitor records."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import database
import exhibition_enrich
import yuranja_model as ym
from slugs import slugify

PRIORITY_CITIES = [
    "Seoul",
    "Tokyo",
    "Mexico City",
    "Paris",
]

CANDIDATES_PATH = database.ROOT_DATA_DIR / "yuranja_exhibitions_candidates.json"
REVIEW_REPORT_PATH = database.BACKEND_ROOT / "reports" / "yuranja_candidate_review.md"
EXCLUSIONS_REPORT_PATH = database.BACKEND_ROOT / "reports" / "yuranja_candidate_exclusions.md"

SCORE_THRESHOLD = 65
MIN_SCORE_WITH_REASON = 52
MIN_PER_CITY = 0
MAX_PER_CITY = 5

# Commercial / non-editorial shows that should never enter the Yuranja shortlist.
COMMERCIAL_EXCLUDE_RE = re.compile(
    r"\b(?:fate/?grand\s*order|stargazer|apothecary diaries|tv anime|"
    r"football|soccer|iconic moments in the history of football|"
    r"objects of glory|bozar rooftop|festival midis)\b",
    re.I,
)

EMBEDDED_DATE_TAIL_RE = re.compile(
    r"\s+\d{1,2}\.[A-Z]{3}\.?(?:\s*20\d{2})?"
    r"(?:\s*[–\-]\s*\d{1,2}\.[A-Z]{3}\.?(?:\s*20\d{2})?)?\s*$",
    re.I,
)

UPCOMING_PREFIX_RE = re.compile(r"^\s*upcoming\s+exhibition\s+", re.I)
SOLO_URL_RE = re.compile(r"solo[-_]exhibition|/solo[/-]|solo-exhibition", re.I)
GROUP_URL_RE = re.compile(r"group[-_]exhibition|/group[/-]|group-exhibition", re.I)
ARTIST_COLON_RE = re.compile(
    r"^([A-ZÀ-Ÿ][A-Za-zÀ-ÿ.'\-]+(?:\s+(?:af|de|del|della|van|von|der|la|le|y|of|[A-ZÀ-Ÿ][A-Za-zÀ-ÿ.'\-]+)){0,4})\s*:\s+(.+)$"
)
ARTIST_ALONE_RE = re.compile(
    r"^([A-ZÀ-Ÿ][A-Za-zÀ-ÿ.'\-]+(?:\s+(?:af|de|del|della|van|von|der|la|le|y|of|[A-ZÀ-Ÿ][A-Za-zÀ-ÿ.'\-]+)){0,4})$"
)

INVALID_TITLE_EXACT = frozenset(
    {
        "projects",
        "resource",
        "agenda",
        "exhibitions",
        "events",
        "programme",
        "programs",
        "calendar",
        "menu",
        "search",
        "home",
        "about",
        "visit",
        "tickets",
        "news",
        "processing...",
        "upcoming events",
        "museum of contemporary art, taipei",
        "artists space",
    }
)

DATE_TITLE_RE = re.compile(
    r"^(?:\d{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\.\d{1,2}\.\d{4})",
    re.I,
)

COMING_SOON_RE = re.compile(r"^coming soon\b", re.I)

NOT_EXHIBITION_RE = re.compile(
    r"\b(?:screening schedule|collateral events?\s*\(|workshop|talks?\b|"
    r"guided tour|ticket product|education programme|school program|"
    r"art fair\b|festival midis|concert\b|film season\b)\b",
    re.I,
)

FILM_PROGRAM_RE = re.compile(
    r"^(?:[\w\s]+ - )?(?:Hayao Miyazaki|Raoul Peck|Gianfranco Rosi|Lav Diaz|C\. Tangana|"
    r"Yerai Cortés|Jacques Rozier)\b|"
    r"\b(?:film|films by|cinema|screening)\b",
    re.I,
)

FRAGMENT_RE = re.compile(
    r"(?:opening reception:|dates:\s*$|\bPast\s+[A-Z]|"
    r"Exhibitions?\s+(?:Upcoming|Past)\b|"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\]\s*-|"
    r"\b404 not found\b|Contact Jobs|"
    r"^\s*(?:EN|JP|CN)\s+(?:Menu|ARTISTS))",
    re.I,
)

SURVEY_RE = re.compile(
    r"\b(?:survey|retrospective|monograph|biennale|prize|panorama|commission|"
    r"in minor keys|collection exhibition|solo exhibition|group exhibition|"
    r"international art exhibition|new commission)\b",
    re.I,
)

SOLO_HINT_RE = re.compile(
    r"^[A-ZÀ-Ÿ][\w\s.'-]{2,50}(?:\s*[“\"«][^”\"»]+[”\"»])?$",
)


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def _parse_citations(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [dict(c) for c in raw if isinstance(c, dict)]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [dict(c) for c in parsed if isinstance(c, dict)]
    except json.JSONDecodeError:
        pass
    return []


def _row_to_internal(row: Any, visitor_index: exhibition_enrich.VisitorIndex) -> dict[str, Any]:
    data = dict(row)
    return exhibition_enrich.enrich_exhibition_row(data, visitor_index)


def _has_verified_dates(record: dict[str, Any]) -> bool:
    dates = record.get("dates") or {}
    return bool(str(dates.get("start") or "").strip() and str(dates.get("end") or "").strip())


def _exhibition_url(record: dict[str, Any]) -> str:
    return str(record.get("exhibitionUrl") or record.get("source_url") or "").strip()


def _has_exhibition_citation(record: dict[str, Any]) -> bool:
    cites = record.get("citations") or []
    url = _exhibition_url(record)
    if not url:
        return False
    for c in cites:
        field = str(c.get("field") or "").casefold()
        ctype = str(c.get("type") or "").casefold()
        if field in {"title", "dates"} or ctype == "exhibition":
            if str(c.get("url") or "").strip():
                return True
    return bool(url and record.get("title"))


def _clean_title(title: str) -> str:
    t = UPCOMING_PREFIX_RE.sub("", str(title or "").strip())
    t = EMBEDDED_DATE_TAIL_RE.sub("", t).strip(" -–—,")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _artists_from_shojo_title(title: str) -> list[str]:
    # "Shojo Manga Infinity: Moto Hagio, Ryoko Yamagishi, and Waki Yamato"
    if ":" not in title:
        return []
    tail = title.split(":", 1)[1]
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", tail, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def _looks_like_person_name(name: str) -> bool:
    text = (name or "").strip()
    if not text or len(text) > 60:
        return False
    words = text.split()
    if not (1 <= len(words) <= 4):
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    particles = {"af", "de", "del", "della", "van", "von", "der", "la", "le", "y", "of", "du", "des"}
    # Branded concept titles in ALL CAPS with a single token.
    if all(c.isupper() for c in letters) and len(words) == 1 and len(text) >= 8:
        return False
    # Multi-word ALL CAPS alone (no colon) is usually a concept title, not a person.
    if all(c.isupper() for c in letters) and len(words) >= 2:
        return False
    for word in words:
        if word.casefold() in particles:
            continue
        if not word[:1].isupper():
            return False
    return bool(re.match(r"^[A-ZÀ-Ÿ]", text))


def enrich_candidate_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Clean title, infer artists/format from official title/URL only — never invent dates."""
    out = dict(record)
    raw_title = str(out.get("title") or "")
    title = _clean_title(raw_title)
    out["title"] = title
    url = _exhibition_url(out)
    artists = list(out.get("artists") or [])
    fmt = str(out.get("format") or "").strip()

    if SOLO_URL_RE.search(url):
        fmt = fmt or "solo"
    elif GROUP_URL_RE.search(url):
        fmt = fmt or "group"

    if "group-exhibition" in url or "group_exhibition" in url:
        fmt = "group"
        # Group listing URLs should not invent a solo artist from the show title.
        if artists and len(artists) == 1 and artists[0].casefold() == title.casefold():
            artists = []
    if "solo-exhibition" in url or "solo_exhibition" in url:
        fmt = "solo"

    if not artists:
        if "shojo manga" in title.casefold() and ":" in title:
            artists = _artists_from_shojo_title(title)
            fmt = fmt or "group"
        else:
            m = ARTIST_COLON_RE.match(title)
            if m:
                head = m.group(1).strip()
                # Allow ALL-CAPS artist heads before a subtitle (Jumex style).
                head_letters = [c for c in head if c.isalpha()]
                all_caps_head = bool(head_letters) and all(c.isupper() for c in head_letters) and len(head.split()) >= 2
                if _looks_like_person_name(head) or all_caps_head:
                    artists = [head]
                    fmt = fmt or "solo"
            elif ARTIST_ALONE_RE.match(title) and _looks_like_person_name(title):
                artists = [title]
                fmt = fmt or "solo"
            # "François Morellet 100 pour cent" / "Louise Bourgeois. Extrême tension..."
            else:
                m2 = re.match(
                    r"^([A-ZÀ-Ÿ][A-Za-zÀ-ÿ.'\-]+(?:\s+(?:af|de|del|della|van|von|der|la|le|y|of|[A-ZÀ-Ÿ][A-Za-zÀ-ÿ.'\-]+)){0,3})"
                    r"(?:\s+\d|\s+[«\"“]|\.\s+|\s+100\b|\s+et\s+nous\b)",
                    title,
                )
                if m2 and _looks_like_person_name(m2.group(1)):
                    artists = [m2.group(1).strip()]
                    fmt = fmt or "solo"

    # Named prize / survey / concept shows are group programmes when no single artist.
    if re.search(r"\b(?:prix|prize|panorama|biennale)\b", title, re.I):
        fmt = "group"
        if artists and artists[0].casefold().startswith(("prix", "prize")):
            artists = []
    if not artists and re.search(
        r"\b(?:visions|utopia|waves|photoromance)\b",
        title,
        re.I,
    ):
        fmt = fmt or "group"
    if not artists and title.isupper():
        fmt = fmt or "group"

    if not fmt:
        fmt = exhibition_enrich.infer_format(artists, title) or (
            "solo" if artists and _looks_like_person_name(artists[0]) else ""
        )

    out["artists"] = artists
    out["format"] = fmt
    return out


def check_editorial_quality(record: dict[str, Any]) -> str | None:
    """Extra editorial gate after technical eligibility."""
    title = str(record.get("title") or "")
    if COMMERCIAL_EXCLUDE_RE.search(title):
        return "insufficient editorial distinctiveness"
    url = _exhibition_url(record)
    if COMMERCIAL_EXCLUDE_RE.search(url):
        return "insufficient editorial distinctiveness"
    # Require a dedicated exhibition path (not bare homepage).
    try:
        from urllib.parse import urlparse

        path = (urlparse(url).path or "/").rstrip("/")
    except Exception:
        path = ""
    if not path or path in {"", "/en", "/fr", "/jp", "/es"}:
        return "incomplete source record"
    return None


def _title_is_valid(title: str, venue: str) -> str | None:
    t = (title or "").strip()
    if len(t) < 4:
        return "title invalid"
    if len(t) > 180:
        return "title invalid"
    if t.casefold() in INVALID_TITLE_EXACT:
        return "not an exhibition"
    if ym.normalize_for_dedupe(t) == ym.normalize_for_dedupe(venue):
        return "title invalid"
    if FRAGMENT_RE.search(t):
        return "title invalid"
    if DATE_TITLE_RE.search(t):
        return "title invalid"
    if COMING_SOON_RE.search(t):
        return "title invalid"
    if re.search(r"\bToday\s*$", t):
        return "title invalid"
    if NOT_EXHIBITION_RE.search(t):
        return "not an exhibition"
    if FILM_PROGRAM_RE.search(t) and "exhibition" not in t.casefold():
        return "not an exhibition"
    # Crawler breadcrumb / page chrome
    if t.count("|") >= 2 or "Menu " in t[-40:]:
        return "title invalid"
    word_count = len(t.split())
    if word_count > 18 and not SURVEY_RE.search(t):
        return "title invalid"
    return None


def check_eligibility(record: dict[str, Any]) -> str | None:
    """Return exclusion reason or None if eligible."""
    status = str(record.get("status") or "").casefold()
    if status not in {"current", "upcoming"}:
        return "expired"
    if str(record.get("archive_status") or "active").casefold() == "archived":
        return "expired"
    if str(record.get("editorial_status") or "").casefold() == "rejected":
        return "expired"
    if record.get("is_duplicate"):
        return "duplicate"
    if not _has_verified_dates(record):
        return "missing official citation"
    if not record.get("title"):
        return "title invalid"
    if not record.get("venue"):
        return "incomplete source record"
    if not record.get("city"):
        return "incomplete source record"
    title_reason = _title_is_valid(record.get("title", ""), record.get("venue", ""))
    if title_reason:
        return title_reason
    if not _exhibition_url(record):
        return "missing official citation"
    if not _has_exhibition_citation(record):
        return "missing official citation"
    quality = check_editorial_quality(record)
    if quality:
        return quality
    return None


def _optional_missing(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not (record.get("description") or "").strip():
        missing.append("description")
    if not (record.get("curators") or []):
        missing.append("curators")
    if not (record.get("openingHours") or "").strip():
        missing.append("openingHours")
    if not (record.get("format") or "").strip():
        missing.append("format")
    if not (record.get("categories") or []):
        missing.append("categories")
    admission = record.get("admission") or {}
    if admission.get("status") == "unknown":
        missing.append("admission")
    if not (record.get("artists") or []):
        missing.append("artists")
    return missing


def _normalize_title_for_dedupe(title: str, venue: str) -> str:
    t = ym.normalize_for_dedupe(title)
    venue_key = ym.normalize_for_dedupe(venue)
    if t.startswith(venue_key):
        t = t[len(venue_key) :].strip(" -|")
    return t


def _title_suggests_solo(title: str, artists: list[str]) -> bool:
    if artists:
        return len(artists) == 1 and artists[0].casefold() not in {"group exhibition", "collection exhibition"}
    words = title.strip().split()
    if 1 <= len(words) <= 5 and title[:1].isupper() and ":" not in title:
        return True
    if ":" in title:
        head = title.split(":", 1)[0].strip()
        return 1 <= len(head.split()) <= 4
    return False


def score_editorial(record: dict[str, Any], venue_meta: dict[str, Any] | None = None) -> tuple[int, str]:
    """Return (score 0-100, selectionReason). Based on structured data only."""
    venue_meta = venue_meta or {}
    title = str(record.get("title") or "")
    artists = record.get("artists") or []
    curators = record.get("curators") or []
    description = str(record.get("description") or "")
    fmt = str(record.get("format") or "") or exhibition_enrich.infer_format(artists, title)
    if not fmt and _title_suggests_solo(title, artists):
        fmt = "solo"
    categories = record.get("categories") or []
    media = record.get("mediaTypes") or []
    importance = str(venue_meta.get("importance") or record.get("importance") or "")
    category = str(venue_meta.get("category") or record.get("category") or "")
    ex_url = _exhibition_url(record)

    curatorial = 0
    artistic = 0
    relevance = 0
    visitor = 0
    completeness = 0
    reasons: list[str] = []

    if curators:
        curatorial += 10
        reasons.append("named curators")
    if SURVEY_RE.search(title):
        curatorial += 12
        reasons.append("survey or biennial programme")
    if fmt == "solo":
        curatorial += 10
        reasons.append("solo presentation")
    elif fmt == "group" and len(title.split()) >= 4:
        curatorial += 7
        reasons.append("concept-led group exhibition")
    if categories or media:
        curatorial += min(8, len(categories) * 3 + len(media) * 2)
    if any(x in categories for x in ("installation", "performance", "media")):
        curatorial += 5

    if fmt == "solo" and artists and (
        _looks_like_person_name(artists[0])
        or (
            ":" in title
            and 2 <= len(artists[0].split()) <= 4
            and all(c.isupper() for c in artists[0] if c.isalpha())
        )
    ):
        artistic += 12
        reasons.append("single-artist focus")
    elif fmt == "solo" and _looks_like_person_name(title):
        artistic += 10
        reasons.append("single-artist focus")
    if "retrospective" in title.casefold() or "survey" in title.casefold():
        artistic += 8
    if ":" in title and len(title.split()) >= 3:
        artistic += 4
    if importance == "global":
        artistic += 6
    elif importance == "national":
        artistic += 3
    # Prefer named museum solos even when artist field was empty in the crawl.
    if category in {"museum", "kunsthalle"} and (
        (artists and (_looks_like_person_name(artists[0]) or ":" in title))
        or _looks_like_person_name(title)
    ):
        artistic += 4
        relevance += 2

    if category in {"museum", "kunsthalle", "biennale"}:
        relevance += 12
        reasons.append("major art institution")
    elif category in {"gallery", "non_profit"}:
        relevance += 7
    if category == "biennale" or "biennale" in title.casefold():
        relevance += 6
    if len(description) >= 60:
        relevance += 4

    if _has_verified_dates(record):
        visitor += 6
    admission = record.get("admission") or {}
    if admission.get("status") != "unknown":
        visitor += 4
    if (record.get("address") or "").strip():
        visitor += 3
    if (record.get("openingHours") or "").strip():
        visitor += 2

    if artists:
        completeness += 5
    if ex_url and any(part in ex_url.casefold() for part in ("/exhibition", "/exhibitions/", "/detail/", "/show/", "/en/archives/")):
        completeness += 5
    cites = record.get("citations") or []
    if any(c.get("field") == "dates" and c.get("note") for c in cites):
        completeness += 5
    if description:
        completeness += 4
    if curators:
        completeness += 3

    score = min(100, curatorial + artistic + relevance + visitor + completeness)
    reason = "; ".join(reasons[:4]) if reasons else "verified current exhibition with complete source record"
    return score, reason


def _dedupe_eligible(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the strongest row per dedupe key / normalised title."""
    best: dict[str, dict[str, Any]] = {}
    for record in records:
        title_key = _normalize_title_for_dedupe(record.get("title", ""), record.get("venue", ""))
        start = (record.get("dates") or {}).get("start", "")
        key = f"{ym.normalize_for_dedupe(record.get('venue', ''))}|{title_key}|{start}"
        existing = best.get(key)
        if not existing:
            best[key] = record
            continue
        v = venues_dummy_score(record)
        if v > venues_dummy_score(existing):
            best[key] = record
    return list(best.values())


def venues_dummy_score(record: dict[str, Any]) -> int:
    url = _exhibition_url(record)
    return (
        len(str(record.get("description") or ""))
        + 10 * len(record.get("artists") or [])
        + len(url)
        + (5 if record.get("format") else 0)
    )


def _trim_words(text: str, *, min_words: int = 40, max_words: int = 90) -> str:
    words = re.split(r"\s+", text.strip())
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).rstrip(".,;") + "."


def _build_description(record: dict[str, Any]) -> str:
    existing = str(record.get("description") or "").strip()
    if existing:
        cleaned = re.sub(r"\s+", " ", existing)
        # Skip weak template stubs from earlier crawls.
        if "exhibition exhibition" not in cleaned.casefold() and len(cleaned.split()) >= 12:
            return _trim_words(cleaned)
    title = record.get("title") or "This exhibition"
    venue = record.get("venue") or "the institution"
    artists = record.get("artists") or []
    fmt = record.get("format") or ""
    dates = record.get("dates") or {}
    start = dates.get("start", "")
    end = dates.get("end", "")
    fmt_label = {"solo": "solo", "group": "group"}.get(fmt, "")
    if artists and artists[0].casefold() not in {"group exhibition", "collection exhibition"}:
        artist_text = ", ".join(artists[:4])
        if fmt_label == "solo" and len(artists) == 1:
            base = (
                f"{title} at {venue} is a solo exhibition by {artist_text}. "
                f"It is on view from {start} to {end}."
            )
        else:
            base = (
                f"{title} at {venue} presents work by {artist_text}. "
                f"The exhibition runs from {start} to {end}."
            )
    elif fmt_label == "group":
        base = (
            f"{title} is a group exhibition at {venue}, "
            f"on view from {start} to {end}."
        )
    else:
        base = (
            f"{title} is presented at {venue} "
            f"from {start} to {end}."
        )
    return _trim_words(base, min_words=20, max_words=90)


def _yuranja_citations(record: dict[str, Any], *, checked_at: str) -> list[dict[str, Any]]:
    publisher = str(record.get("venue") or "")
    ex_url = _exhibition_url(record)
    cites: list[dict[str, Any]] = []
    raw = record.get("citations") or []
    date_note = ""
    for c in raw:
        if c.get("field") == "dates" and c.get("note"):
            date_note = str(c["note"])
            break

    supports = ["title", "dates"]
    if record.get("artists"):
        supports.append("artists")
    if record.get("description"):
        supports.append("description")
    cites.append(
        {
            "type": "exhibition",
            "url": ex_url,
            "publisher": publisher,
            "supports": supports,
            "checkedAt": checked_at,
            "note": date_note,
        }
    )

    admission = record.get("admission") or {}
    ticket_url = str(admission.get("ticketUrl") or record.get("website") or "").strip()
    if admission.get("status") != "unknown" and ticket_url:
        cites.append(
            {
                "type": "admission",
                "url": ticket_url,
                "publisher": publisher,
                "supports": ["admission", "reservationRequired"],
                "checkedAt": str(admission.get("checkedAt") or checked_at),
            }
        )
    return cites


def _stable_slug(record: dict[str, Any], used: set[str]) -> str:
    title = str(record.get("title") or "")
    dates = record.get("dates") or {}
    year = (dates.get("start") or dates.get("end") or "")[:4]
    base = slugify(title)[:70] or slugify(record.get("venue", "exhibition"))[:40]
    slug = base
    if year:
        slug = f"{base}-{year}" if base else year
    n = 2
    while slug in used:
        slug = f"{base}-{year}-{n}" if year else f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def _admission_for_candidate(record: dict[str, Any]) -> dict[str, Any]:
    admission = dict(record.get("admission") or {})
    status = str(admission.get("status") or "unknown")
    if status == "unknown":
        return {
            "status": "unknown",
            "display": "Check current admission",
            "fromPrice": "",
            "reservationRequired": admission.get("reservationRequired") if "reservationRequired" in admission else None,
            "ticketUrl": "",
            "checkedAt": admission.get("checkedAt") or "",
        }
    out = {
        "status": status,
        "display": admission.get("display") or "Check current admission",
        "fromPrice": admission.get("fromPrice") or "",
        "reservationRequired": bool(admission.get("reservationRequired")),
        "ticketUrl": admission.get("ticketUrl") or "",
        "checkedAt": admission.get("checkedAt") or "",
    }
    return out


def to_candidate_shape(
    record: dict[str, Any],
    *,
    editorial_score: int,
    selection_reason: str,
    slug: str,
    human_review_status: str = "pending",
) -> dict[str, Any]:
    checked = str(record.get("dateChecked") or _today_iso())[:10]
    return {
        "slug": slug,
        "id": record.get("exhibition_id") or record.get("id") or slug,
        "title": record.get("title") or "",
        "artists": record.get("artists") or [],
        "curators": record.get("curators") or [],
        "venue": record.get("venue") or "",
        "city": record.get("city") or "",
        "country": record.get("country") or "",
        "dates": record.get("dates") or {"start": "", "end": ""},
        "address": record.get("address") or "",
        "openingHours": record.get("openingHours") or "",
        "website": _exhibition_url(record),
        "description": _build_description(record),
        "yuranjaNote": "",
        "format": record.get("format") or "",
        "categories": record.get("categories") or [],
        "mediaTypes": record.get("mediaTypes") or [],
        "admission": _admission_for_candidate(record),
        "tags": record.get("tags") or [],
        "citations": _yuranja_citations(record, checked_at=checked),
        "editorialScore": editorial_score,
        "selectionReason": selection_reason,
        "humanReviewStatus": human_review_status,
        "status": record.get("status") or "",
        "missingOptionalFields": _optional_missing(record),
    }


def _select_city_candidates(
    scored: list[tuple[dict[str, Any], int, str]],
) -> tuple[list[tuple[dict[str, Any], int, str]], list[tuple[dict[str, Any], int, str, str]]]:
    """Return (selected, excluded_for_score)."""
    selected: list[tuple[dict[str, Any], int, str]] = []
    excluded: list[tuple[dict[str, Any], int, str, str]] = []
    scored_sorted = sorted(scored, key=lambda x: (-x[1], x[0].get("title", "")))

    for record, score, reason in scored_sorted:
        if len(selected) >= MAX_PER_CITY:
            excluded.append((record, score, reason, "insufficient editorial distinctiveness"))
            continue
        if score >= SCORE_THRESHOLD:
            selected.append((record, score, reason))
        elif score >= MIN_SCORE_WITH_REASON:
            selected.append(
                (
                    record,
                    score,
                    f"{reason}; retained below {SCORE_THRESHOLD} with documented editorial case",
                )
            )
        else:
            excluded.append((record, score, reason, "insufficient editorial distinctiveness"))
    return selected, excluded


def yuranja_citations(record: dict[str, Any], *, checked_at: str) -> list[dict[str, Any]]:
    return _yuranja_citations(record, checked_at=checked_at)


def build_description(record: dict[str, Any]) -> str:
    return _build_description(record)


def _write_review_report(
    *,
    city_stats: dict[str, dict[str, Any]],
    candidates_by_city: dict[str, list[dict[str, Any]]],
    path: Path,
) -> None:
    lines = [
        "# Yuranja candidate review",
        "",
        f"Generated: **{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}**",
        "",
        "## Summary by city",
        "",
        "| City | Crawled | Eligible | Selected | Excluded | Approved | Needs editing | Rejected |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for city in PRIORITY_CITIES:
        st = city_stats.get(city, {})
        lines.append(
            f"| {city} | {st.get('crawled', 0)} | {st.get('eligible', 0)} | "
            f"{st.get('selected', 0)} | {st.get('excluded', 0)} | "
            f"{st.get('approved', 0)} | {st.get('needs_edit', 0)} | {st.get('rejected', 0)} |"
        )

    for city in PRIORITY_CITIES:
        items = candidates_by_city.get(city, [])
        if not items and not city_stats.get(city, {}).get("eligible"):
            continue
        lines.extend(["", f"## {city}", ""])
        if not items:
            lines.append("_No candidates selected for this city._")
            continue
        for c in items:
            dates = c.get("dates") or {}
            admission = c.get("admission") or {}
            ex_cite = next((x for x in c.get("citations", []) if x.get("type") == "exhibition"), {})
            ad_cite = next((x for x in c.get("citations", []) if x.get("type") == "admission"), {})
            missing = c.get("missingOptionalFields") or []
            lines.extend(
                [
                    f"### {c.get('title', '—')}",
                    "",
                    f"- **Slug:** `{c.get('slug')}`",
                    f"- **Artists:** {', '.join(c.get('artists') or []) or '—'}",
                    f"- **Institution:** {c.get('venue', '—')}",
                    f"- **Dates:** {dates.get('start', '—')} → {dates.get('end', '—')}",
                    f"- **Status:** {c.get('status', '—')}",
                    f"- **Admission:** {admission.get('display', '—')} ({admission.get('status', 'unknown')})",
                    f"- **Editorial score:** {c.get('editorialScore', 0)}",
                    f"- **Selection reason:** {c.get('selectionReason', '—')}",
                    f"- **Review status:** {c.get('humanReviewStatus', 'pending')}",
                    f"- **Missing optional fields:** {', '.join(missing) if missing else 'none'}",
                    f"- **Exhibition citation:** [{ex_cite.get('url', '—')}]({ex_cite.get('url', '')})",
                    f"- **Admission citation:** "
                    + (
                        f"[{ad_cite.get('url')}]({ad_cite.get('url')})"
                        if ad_cite.get("url")
                        else "none verified"
                    ),
                    "",
                ]
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_exclusions_report(exclusions: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Yuranja candidate exclusions",
        "",
        f"Generated: **{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}**",
        "",
        f"Total excluded: **{len(exclusions)}**",
        "",
    ]
    by_reason: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ex in exclusions:
        by_reason[ex["reason"]].append(ex)

    for reason in sorted(by_reason):
        lines.extend([f"## {reason}", ""])
        for ex in by_reason[reason]:
            lines.extend(
                [
                    f"### {ex.get('title', '—')}",
                    "",
                    f"- **Institution:** {ex.get('venue', '—')}",
                    f"- **City:** {ex.get('city', '—')}",
                    f"- **Source:** [{ex.get('url', '—')}]({ex.get('url', '')})",
                    "",
                ]
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_build_yuranja_candidates(*, path: Path | None = None) -> dict[str, Any]:
    out_path = path or CANDIDATES_PATH
    conn = database.connect()
    database.init_schema(conn)
    visitor_index = exhibition_enrich.load_visitor_index()

    venues = {
        row["slug"]: dict(row)
        for row in conn.execute("SELECT * FROM venues").fetchall()
    }
    existing_review: dict[str, str] = {}
    for row in conn.execute("SELECT id, editorial_status FROM exhibitions").fetchall():
        existing_review[str(row["id"])] = str(row["editorial_status"] or "pending")

    rows = conn.execute("SELECT * FROM exhibitions ORDER BY city, name, start_date, title").fetchall()
    evaluated = len(rows)
    exclusions: list[dict[str, Any]] = []
    eligible_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    crawled_by_city: Counter[str] = Counter()
    editorial_by_city: Counter[str] = Counter()

    for row in rows:
        internal = enrich_candidate_fields(_row_to_internal(row, visitor_index))
        internal["is_duplicate"] = bool(row["is_duplicate"])
        city = internal.get("city") or "Unknown"
        crawled_by_city[city] += 1
        est = str(internal.get("editorial_status") or "pending").casefold()
        if est == "approved":
            editorial_by_city[f"{city}:approved"] += 1
        elif est == "needs_edit":
            editorial_by_city[f"{city}:needs_edit"] += 1
        elif est == "rejected":
            editorial_by_city[f"{city}:rejected"] += 1

        # Only evaluate curated cities for selection; still count exclusions for them.
        if city not in PRIORITY_CITIES:
            continue

        reason = check_eligibility(internal)
        if reason:
            exclusions.append(
                {
                    "title": internal.get("title") or "—",
                    "venue": internal.get("venue") or "—",
                    "city": city,
                    "reason": reason,
                    "url": _exhibition_url(internal) or internal.get("source_url") or "",
                    "id": internal.get("exhibition_id"),
                }
            )
            continue
        eligible_by_city[city].append(internal)

    candidates: list[dict[str, Any]] = []
    candidates_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    city_stats: dict[str, dict[str, Any]] = {}
    used_slugs: set[str] = set()
    score_exclusions: list[dict[str, Any]] = []

    for city in PRIORITY_CITIES:
        eligible = _dedupe_eligible(eligible_by_city.get(city, []))
        scored: list[tuple[dict[str, Any], int, str]] = []
        venue_slug_map = {v["name"]: v for v in venues.values()}

        for record in eligible:
            venue = venue_slug_map.get(record.get("venue", ""), {})
            score, sel_reason = score_editorial(record, venue)
            scored.append((record, score, sel_reason))

        selected, low_scored = _select_city_candidates(scored)
        for record, score, reason, ex_reason in low_scored:
            score_exclusions.append(
                {
                    "title": record.get("title") or "—",
                    "venue": record.get("venue") or "—",
                    "city": city,
                    "reason": ex_reason,
                    "url": _exhibition_url(record) or "",
                    "score": score,
                    "selectionReason": reason,
                }
            )

        city_candidates: list[dict[str, Any]] = []
        for record, score, sel_reason in selected:
            ex_id = str(record.get("exhibition_id") or "")
            review = existing_review.get(ex_id, "pending")
            if review not in {"approved", "rejected", "needs_edit", "pending"}:
                review = "pending"
            slug = _stable_slug(record, used_slugs)
            candidate = to_candidate_shape(
                record,
                editorial_score=score,
                selection_reason=sel_reason,
                slug=slug,
                human_review_status=review,
            )
            city_candidates.append(candidate)
            candidates.append(candidate)

            database.update_exhibition_candidate_meta(
                conn,
                exhibition_id=ex_id,
                editorial_score=score,
                selection_reason=sel_reason,
                is_yuranja_candidate=1,
                candidate_slug=slug,
            )

        candidates_by_city[city] = city_candidates
        city_stats[city] = {
            "crawled": crawled_by_city.get(city, 0),
            "eligible": len(eligible),
            "selected": len(city_candidates),
            "excluded": crawled_by_city.get(city, 0) - len(eligible) + len(low_scored),
            "approved": editorial_by_city.get(f"{city}:approved", 0),
            "needs_edit": editorial_by_city.get(f"{city}:needs_edit", 0),
            "rejected": editorial_by_city.get(f"{city}:rejected", 0),
        }

    # Clear candidate flag for records no longer selected
    selected_ids = {c["id"] for c in candidates}
    for row in conn.execute("SELECT id FROM exhibitions WHERE COALESCE(is_yuranja_candidate, 0) = 1"):
        if str(row["id"]) not in selected_ids:
            database.update_exhibition_candidate_meta(
                conn,
                exhibition_id=str(row["id"]),
                editorial_score=0,
                selection_reason="",
                is_yuranja_candidate=0,
                candidate_slug="",
            )

    conn.commit()
    exclusions.extend(score_exclusions)

    payload = {
        "generated_at": database.now_iso(),
        "count": len(candidates),
        "threshold": SCORE_THRESHOLD,
        "candidates": candidates,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    _write_review_report(
        city_stats=city_stats,
        candidates_by_city=candidates_by_city,
        path=REVIEW_REPORT_PATH,
    )
    _write_exclusions_report(exclusions, EXCLUSIONS_REPORT_PATH)

    missing_admission = sum(
        1 for c in candidates if (c.get("admission") or {}).get("status") == "unknown"
    )
    missing_optional = sum(1 for c in candidates if c.get("missingOptionalFields"))

    by_reason = Counter(ex["reason"] for ex in exclusions)
    per_city = {city: len(candidates_by_city.get(city, [])) for city in PRIORITY_CITIES}

    msg = (
        f"Built {len(candidates)} Yuranja candidates from {evaluated} source records "
        f"({sum(len(v) for v in eligible_by_city.values())} eligible)"
    )
    print(msg)
    print(f"Candidates file: {out_path}")
    print(f"Review report: {REVIEW_REPORT_PATH}")
    print(f"Exclusions report: {EXCLUSIONS_REPORT_PATH}")

    return {
        "success": True,
        "message": msg,
        "evaluated": evaluated,
        "eligible": sum(len(v) for v in eligible_by_city.values()),
        "candidates": len(candidates),
        "candidates_per_city": per_city,
        "exclusions_by_reason": dict(by_reason),
        "missing_admission": missing_admission,
        "missing_optional_fields": missing_optional,
        "path": str(out_path),
    }
