"""Discover exhibition listing URLs when the configured path moves."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

EXHIBITION_PATH_HINTS = re.compile(
    r"(exhibition|exhibitions|whats-?on|program|programme|calendar|current|projects|on-view)",
    re.I,
)

EXHIBITION_LINK_TEXT = re.compile(
    r"\b(exhibitions?|what'?s on|program|programme|current|on view|projects)\b",
    re.I,
)


def discover_exhibitions_url(
    *,
    website: str,
    current_url: str,
    html: str | None,
    status_code: int | None,
) -> tuple[str, bool]:
    """
    Return (best_url, was_discovered).
    If current_url works (2xx), keep it. Otherwise scan homepage links.
    """
    if status_code and 200 <= status_code < 400 and current_url:
        return current_url, False

    if not html or not website:
        return current_url, False

    base = website.rstrip("/") + "/"
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base, href)
        if urlparse(full).netloc != urlparse(base).netloc:
            continue
        score = _score_exhibition_link(full, a.get_text(" ", strip=True))
        if score > 0:
            candidates.append((score, full))

    if not candidates:
        return current_url, False

    candidates.sort(key=lambda x: (-x[0], len(x[1])))
    return candidates[0][1], True


def _score_exhibition_link(url: str, link_text: str) -> int:
    score = 0
    path = urlparse(url).path.lower()
    if EXHIBITION_PATH_HINTS.search(path):
        score += 3
    if EXHIBITION_LINK_TEXT.search(link_text):
        score += 2
    if path.endswith("/exhibitions") or path.endswith("/exhibitions/"):
        score += 2
    if "current" in path:
        score += 1
    return score


def fetch_homepage_for_discovery(
    website: str,
    *,
    fetch_fn: Any,
    venue_row: dict[str, Any],
) -> dict[str, Any]:
    """Fetch institution homepage to support URL discovery."""
    row = {**venue_row, "source_url": website}
    return fetch_fn(row)
