"""Stable slug and record-id generation."""

from __future__ import annotations

import re
import unicodedata


def slugify(text: str, *, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "untitled"


def exhibition_record_id(
    venue_slug: str,
    title: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """venue-slug + exhibition-slug + start-year (or end-year fallback)."""
    year = ""
    for d in (start_date, end_date):
        if d and len(d) >= 4:
            year = d[:4]
            break
    if not year:
        year = "unknown"
    ex_slug = slugify(title)[:60]
    return f"{venue_slug}-{ex_slug}-{year}"
