"""Structured HTML / JSON-LD exhibition extraction."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_ISO = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
_EU_RANGE = re.compile(
    r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})\s*[–—\-]\s*(\d{1,2})[./](\d{1,2})[./](\d{2,4})"
)
_EN_RANGE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2}),?\s*(20\d{2})\s*[–—\-]\s*(?:([A-Za-z]+)\s+)?(\d{1,2}),?\s*(20\d{2})",
    re.I,
)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_CARD_HINT = re.compile(
    r"exhibition|event|programme|program|whats-on|whats_on|teaser|card|listing",
    re.I,
)


def _clean(s: str) -> str:
    s = unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _norm_year(y: str) -> int:
    yi = int(y)
    if yi < 100:
        return 2000 + yi if yi < 70 else 1900 + yi
    return yi


def _eu_iso(d: str, m: str, y: str) -> str:
    try:
        return f"{_norm_year(y):04d}-{int(m):02d}-{int(d):02d}"
    except ValueError:
        return ""


def _month_num(token: str) -> int | None:
    return _MONTHS.get(token.strip().lower()[:3])


def parse_from_html(html: str, base_url: str) -> list[dict[str, Any]]:
    """Extract exhibition candidates from HTML via JSON-LD + DOM heuristics."""
    if not html:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for c in _parse_json_ld(html):
        key = (c.get("title") or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(c)

    for c in _parse_dom_cards(html, base_url):
        key = (c.get("title") or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(c)

    return out[:20]


def _parse_json_ld(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk_json_ld(data):
            title = _clean(str(node.get("name") or node.get("headline") or ""))
            if not title or len(title) < 3:
                continue
            start = _ld_date(node.get("startDate"))
            end = _ld_date(node.get("endDate"))
            artists = []
            perf = node.get("performer") or node.get("actor")
            if isinstance(perf, dict):
                n = perf.get("name")
                if n:
                    artists.append(str(n))
            elif isinstance(perf, list):
                for p in perf:
                    if isinstance(p, dict) and p.get("name"):
                        artists.append(str(p["name"]))
            img = node.get("image")
            image_url = ""
            if isinstance(img, str):
                image_url = img
            elif isinstance(img, dict):
                image_url = str(img.get("url") or "")
            out.append(
                {
                    "title": title[:200],
                    "start_date": start,
                    "end_date": end,
                    "artists": artists[:5],
                    "curators": [],
                    "image_url": image_url,
                }
            )
    return out


def _walk_json_ld(data: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            nodes.extend(_walk_json_ld(item))
        return nodes
    if not isinstance(data, dict):
        return nodes
    typ = data.get("@type") or ""
    types = typ if isinstance(typ, list) else [typ]
    types_lower = [str(t).lower() for t in types]
    if any(t in ("exhibitionevent", "event", "visualartwork") for t in types_lower):
        nodes.append(data)
    for v in data.values():
        if isinstance(v, (dict, list)):
            nodes.extend(_walk_json_ld(v))
    return nodes


def _ld_date(val: Any) -> str:
    if not val:
        return ""
    s = str(val).strip()
    m = _ISO.search(s)
    return m.group(0) if m else s[:10] if len(s) >= 10 and s[4] == "-" else ""


def _parse_dom_cards(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []

    # Headings linked to exhibition paths
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if not _looks_like_exhibition_link(href):
            continue
        title = _heading_near(a)
        if not title or len(title) < 4:
            continue
        parent = a.find_parent(["article", "li", "div", "section"])
        block = _clean(
            parent.get_text(" ", strip=True) if parent else a.get_text(" ", strip=True)
        )
        start, end = _dates_from_text(block)
        img = a.find("img")
        image_url = ""
        if img and img.get("src"):
            image_url = urljoin(base_url, str(img["src"]))
        out.append(
            {
                "title": title[:200],
                "start_date": start,
                "end_date": end,
                "artists": _artists_from_title(title),
                "curators": [],
                "image_url": image_url,
            }
        )

    # Cards with exhibition-ish class names
    for el in soup.find_all(True, class_=True):
        classes = " ".join(el.get("class") or [])
        if not _CARD_HINT.search(classes):
            continue
        h = el.find(["h1", "h2", "h3", "h4"])
        if not h:
            continue
        title = _clean(h.get_text(" ", strip=True))
        if len(title) < 4:
            continue
        block = _clean(el.get_text(" ", strip=True))
        start, end = _dates_from_text(block)
        out.append(
            {
                "title": title[:200],
                "start_date": start,
                "end_date": end,
                "artists": _artists_from_title(title),
                "curators": [],
                "image_url": "",
            }
        )

    return out


def _looks_like_exhibition_link(href: str) -> bool:
    h = href.lower()
    if any(x in h for x in ("exhibition", "programme", "program", "whats-on", "event", "show")):
        return True
    return False


def _heading_near(a: Any) -> str:
    for tag in ("h1", "h2", "h3", "h4"):
        h = a.find(tag)
        if h and h.get_text(strip=True):
            return _clean(h.get_text(" ", strip=True))
    parent = a.find_parent(["article", "li", "div"])
    if parent:
        h = parent.find(["h1", "h2", "h3", "h4"])
        if h and h.get_text(strip=True):
            return _clean(h.get_text(" ", strip=True))
    text = _clean(a.get_text(" ", strip=True))
    return text if 4 <= len(text) <= 120 else ""


def _dates_from_text(text: str) -> tuple[str, str]:
    for m in _ISO.finditer(text):
        pass  # collect below
    isos = [m.group(0) for m in _ISO.finditer(text)]
    if len(isos) >= 2:
        return isos[0], isos[1]
    if len(isos) == 1:
        return "", isos[0]

    m = _EU_RANGE.search(text)
    if m:
        return (
            _eu_iso(m.group(1), m.group(2), m.group(3)),
            _eu_iso(m.group(4), m.group(5), m.group(6)),
        )

    m = _EN_RANGE.search(text)
    if m:
        m1 = _month_num(m.group(1))
        m2 = _month_num(m.group(4) or m.group(1))
        if m1 and m2:
            return (
                _eu_iso(m.group(2), str(m1), m.group(3)),
                _eu_iso(m.group(5), str(m2), m.group(6)),
            )
    return "", ""


def _artists_from_title(title: str) -> list[str]:
    if "—" in title or "–" in title:
        left = re.split(r"[—–]", title, maxsplit=1)[0].strip()
        if 2 <= len(left.split()) <= 5:
            return [left]
    return []
