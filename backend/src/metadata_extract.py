"""
Rule-based extraction of exhibitions and visitor amenities from page text.

TODO: Swap in an LLM or structured extractor with DOM hints + museum-specific
templates for reliable titles, artists, and ISO dates.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import pandas as pd

# Do not persist full article bodies — keep snippets for internal review only.
RAW_TEXT_CAP = 2000

_UNTIL = re.compile(
    r"(?P<title>[A-Za-z0-9À-Ÿ\"«»].{6,140}?)\s+until\s+(?P<d>\d{1,2})[./](?P<m>\d{1,2})[./](?P<y>\d{2,4})",
    re.IGNORECASE,
)

_ARTIST_HINT = re.compile(
    r"^([A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,4})\s*[,\u2013\-]",
)


def _norm_year(y: str) -> str:
    y = y.strip()
    if len(y) == 2:
        yi = int(y)
        return str(2000 + yi if yi < 70 else 1900 + yi)
    return y


def _to_iso(d: str, m: str, y: str) -> str:
    yy = _norm_year(y)
    try:
        return f"{int(yy):04d}-{int(m):02d}-{int(d):02d}"
    except ValueError:
        return ""


def _clean(s: str) -> str:
    s = unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_exhibitions(
    extracted: dict[str, Any],
    fetch: dict[str, Any],
    source_row: pd.Series,
) -> list[dict[str, Any]]:
    """
    Return a list of exhibition dicts ready for DB insert (without source_id / timestamps).
    """
    city = str(source_row.get("city", "")).strip()
    institution = str(source_row.get("source_name", "")).strip()
    url = str(source_row.get("source_url", "")).strip()
    fetch_ok = fetch.get("status") == "ok"
    text_ok = bool(extracted.get("ok"))
    base_status = "ok" if fetch_ok and text_ok else "error"
    err_parts: list[str] = []
    if not fetch_ok:
        err_parts.append(str(fetch.get("error") or "fetch failed"))
    if fetch_ok and not text_ok:
        err_parts.append(str(extracted.get("error") or "extract failed"))

    text = str(extracted.get("text") or "")
    raw_snippet = text[:RAW_TEXT_CAP]

    if not fetch_ok or not text_ok:
        return [
            {
                "city": city,
                "institution": institution,
                "exhibition_title": str(extracted.get("title") or "").strip() or "(unavailable)",
                "artist_names": "",
                "start_date": "",
                "end_date": "",
                "source_url": url,
                "raw_text": raw_snippet,
                "fetch_status": base_status,
                "error_detail": " · ".join(err_parts) if err_parts else "",
            }
        ]

    candidates: list[dict[str, Any]] = []
    for m in _UNTIL.finditer(text):
        title = _clean(m.group("title"))
        end = _to_iso(m.group("d"), m.group("m"), m.group("y"))
        if not title:
            continue
        artists = ""
        am = _ARTIST_HINT.match(title)
        if am:
            artists = am.group(1).strip()
            title = title[am.end() :].strip(" ,–-")
        candidates.append(
            {
                "city": city,
                "institution": institution,
                "exhibition_title": title[:200],
                "artist_names": artists[:300],
                "start_date": "",
                "end_date": end,
                "source_url": url,
                "raw_text": raw_snippet,
                "fetch_status": "ok",
                "error_detail": "",
            }
        )

    # TODO: AI-assisted segmentation for dense listing pages (split stacked cards).
    if candidates:
        return candidates[:12]

    page_title = str(extracted.get("title") or "").strip()
    # TODO: Parse schema.org / JSON-LD ExhibitionEvent blocks when present.

    return [
        {
            "city": city,
            "institution": institution,
            "exhibition_title": page_title or institution,
            "artist_names": "",
            "start_date": "",
            "end_date": "",
            "source_url": url,
            "raw_text": raw_snippet,
            "fetch_status": "ok",
            "error_detail": "",
        }
    ]


def extract_visitor_info(
    extracted: dict[str, Any],
    source_row: pd.Series,
) -> dict[str, str] | None:
    """Return visitor fields or None when page text is unusable."""
    if not extracted.get("ok"):
        return None
    text_raw = str(extracted.get("text") or "")
    text = text_raw.lower()

    entry_fee = ""
    if re.search(r"\bfree\s+(admission|entry)\b", text):
        entry_fee = "Free"
    m = re.search(r"€\s*[\d,.]+", text_raw)
    if m and not entry_fee:
        entry_fee = m.group(0).replace(" ", "")
    m2 = re.search(r"\b(?:EUR|USD)\s*[\d,.]+\b", text_raw, re.I)
    if m2 and not entry_fee:
        entry_fee = m2.group(0)

    audio = ""
    langs = ""
    if re.search(r"\baudio\s+guide\b", text):
        audio = "yes"
        lm = re.search(
            r"audio\s+guide[^.]{0,120}(?:languages?|available)[^.]{0,160}",
            text,
            re.I,
        )
        if lm:
            langs = _clean(lm.group(0))[:200]

    amenities: list[str] = []
    pairs = [
        ("cafe", "Café"),
        ("coffee", "Coffee"),
        ("restaurant", "Restaurant"),
        ("museum shop", "Museum shop"),
        ("gift shop", "Gift shop"),
        ("wheelchair", "Wheelchair access"),
        ("accessibility", "Accessibility"),
        ("cloakroom", "Cloakroom"),
        ("coat check", "Coat check"),
        ("family room", "Family room"),
        ("stroller", "Stroller-friendly"),
    ]
    for needle, label in pairs:
        if needle in text and label not in amenities:
            amenities.append(label)

    if not any([entry_fee, audio, amenities]):
        return None

    return {
        "institution": str(source_row.get("source_name", "")).strip(),
        "city": str(source_row.get("city", "")).strip(),
        "entry_fee": entry_fee,
        "audio_guide_available": audio,
        "audio_guide_languages": langs,
        "amenities": "; ".join(amenities),
        "source_url": str(source_row.get("source_url", "")).strip(),
    }


def build_signals_placeholder(source_row: pd.Series) -> dict[str, str]:
    """
    Placeholder social / ratings row — do not scrape Google Maps or Instagram.

    TODO: Integrate Google Places Details API with billing + policy review.
    TODO: Integrate Instagram Graph API or a compliant social-data vendor.
    """
    return {
        "institution": str(source_row.get("source_name", "")).strip(),
        "city": str(source_row.get("city", "")).strip(),
        "google_rating": "",
        "hashtag_count": "",
        "mention_count": "0",
        "sentiment_score": "",
        "source_url": str(source_row.get("source_url", "")).strip(),
    }
