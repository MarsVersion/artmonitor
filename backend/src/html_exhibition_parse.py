"""Structured HTML / JSON-LD exhibition extraction with cited dates."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import date_extract

_CARD_HINT = re.compile(
    r"exhibition|event|programme|program|whats-on|whats_on|teaser|card|listing|"
    r"current|upcoming|show|expo",
    re.I,
)

_NAV_TITLES = frozenset(
    {
        "exhibitions",
        "exhibition",
        "events",
        "event",
        "programmes",
        "programmes",
        "programs",
        "programme",
        "program",
        "calendar",
        "what's on",
        "whats on",
        "what’s on",
        "current",
        "upcoming",
        "past",
        "archive",
        "about",
        "visit",
        "tickets",
        "news",
        "home",
        "english",
        "italiano",
        "log in",
        "search",
        "menu",
        "more",
        "more info",
        "continue",
        "interactive map",
        "guided tours",
        "current & upcoming exhibitions",
        "current and upcoming",
        "exhibitions & events",
        "exhibitions and events",
        "past programme",
        "past exhibitions",
        "educational program",
        "school program",
        "collateral events",
        "biennale educational",
        "hall rental",
        "today",
        "teens & young adults",
        "rentals & events",
        "panoramas",
        "future",
        "past",
        "현재 전시",
        "과거 전시",
        "예정 전시",
        "now open!",
        "full",
        "book",
        "language",
        "current exhibitions",
        "agenda",
        "collateral events",
        "collateral events (procedure)",
        "screening schedule (public)",
        "screening schedule (pass holders)",
        "exhibitions and activities",
    }
)


def _clean(s: str) -> str:
    s = unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _is_nav_title(title: str) -> bool:
    t = _clean(title).casefold()
    if not t or len(t) < 3:
        return True
    if t in _NAV_TITLES:
        return True
    if t.startswith("rechercher") or t.startswith("프로그램"):
        return True
    return False


def parse_from_html(html: str, base_url: str) -> list[dict[str, Any]]:
    """Extract exhibition candidates from HTML via JSON-LD + DOM heuristics."""
    if not html:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for c in _parse_json_ld(html):
        key = (c.get("title") or "").casefold()
        if key and key not in seen and not _is_nav_title(c.get("title", "")):
            seen.add(key)
            out.append(c)

    for c in _parse_time_blocks(html, base_url):
        key = (c.get("title") or "").casefold()
        if key and key not in seen and not _is_nav_title(c.get("title", "")):
            seen.add(key)
            out.append(c)

    for c in _parse_dom_cards(html, base_url):
        key = (c.get("title") or "").casefold()
        if key and key not in seen and not _is_nav_title(c.get("title", "")):
            seen.add(key)
            out.append(c)

    for c in _parse_heading_date_blocks(html, base_url):
        key = (c.get("title") or "").casefold()
        if key and key not in seen and not _is_nav_title(c.get("title", "")):
            seen.add(key)
            out.append(c)

    for c in _parse_page_level_dates(html, base_url):
        key = (c.get("title") or "").casefold()
        if key and key not in seen and not _is_nav_title(c.get("title", "")):
            seen.add(key)
            out.append(c)

    # Prefer dated candidates; keep undated only when no dated rows exist
    dated = [c for c in out if c.get("start_date") or c.get("end_date")]
    if dated:
        return dated[:25]
    undated = [c for c in out if not (c.get("start_date") or c.get("end_date"))]
    return undated[:10]


def _parse_page_level_dates(html: str, base_url: str) -> list[dict[str, Any]]:
    """Fallback: find dated exhibition titles in flattened page text."""
    soup = BeautifulSoup(html, "html.parser")
    text = _clean(soup.get_text(" ", strip=True))
    out: list[dict[str, Any]] = []
    # Biennale-style: Venice, 9.05 - 22.11 2026 Biennale Arte 2026 …
    for m in re.finditer(
        r"(?:Venice,\s*)?(\d{1,2}\.\d{1,2}\s*[–—\-]\s*\d{1,2}\.\d{1,2}\s*20\d{2})\s+"
        r"(Biennale Arte 20\d{2}(?:\s+\d+(?:st|nd|rd|th)\s+International Art Exhibition)?)",
        text,
        re.I,
    ):
        hit = date_extract.extract_date_range(m.group(1))
        title = _clean(m.group(2))
        if title and (hit["start_date"] or hit["end_date"]):
            out.append(
                _candidate(
                    title=title[:200],
                    start=hit["start_date"],
                    end=hit["end_date"],
                    date_citation=hit["date_citation"],
                    exhibition_url=base_url,
                )
            )
    # Biennale Arte … runs from Saturday 9 May to Sunday 22 November 2026
    for m in re.finditer(
        r"(Biennale Arte 20\d{2}).{0,220}?runs from\s+"
        r"((?:Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday)\s+\d{1,2}\s+[A-Za-z]+\s+to\s+"
        r"(?:Saturday|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday)\s+\d{1,2}\s+[A-Za-z]+\s+20\d{2})",
        text,
        re.I,
    ):
        hit = date_extract.extract_date_range(m.group(2))
        title = _clean(m.group(1))
        if title and (hit["start_date"] or hit["end_date"]):
            out.append(
                _candidate(
                    title=title[:200],
                    start=hit["start_date"],
                    end=hit["end_date"],
                    date_citation=hit["date_citation"],
                    exhibition_url=base_url,
                )
            )
    # MAM-style: Title … 01 July 26 27 set 26
    for m in re.finditer(
        rf"([A-ZÀ-Ÿ][^.]{{6,100}}?)\s+(\d{{1,2}}\s+[A-Za-zÀ-ÿ]+\s+\d{{2}}\s*(?:[–—\-]?\s*)?\d{{1,2}}\s+[A-Za-zÀ-ÿ]+\s+\d{{2}})",
        text,
    ):
        title = _clean(m.group(1))
        if _is_nav_title(title):
            continue
        hit = date_extract.extract_date_range(m.group(2))
        if hit["start_date"] or hit["end_date"]:
            out.append(
                _candidate(
                    title=title[:200],
                    start=hit["start_date"],
                    end=hit["end_date"],
                    date_citation=hit["date_citation"],
                    exhibition_url=base_url,
                )
            )
    return out


def _parse_heading_date_blocks(html: str, base_url: str) -> list[dict[str, Any]]:
    """Pair headings with nearby date text even when links lack exhibition keywords."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        title = _clean(h.get_text(" ", strip=True))
        if _is_nav_title(title) or len(title) < 4 or len(title) > 160:
            continue
        parent = h.find_parent(["article", "li", "div", "section"]) or h.parent
        block = _clean(parent.get_text(" ", strip=True) if parent else title)
        idx = block.casefold().find(title.casefold())
        window = block[idx : idx + 240] if idx >= 0 else block[:240]
        hit = date_extract.extract_date_range(window)
        if not (hit["start_date"] or hit["end_date"]):
            continue
        href = ""
        a = h.find_parent("a", href=True) or (parent.find("a", href=True) if parent else None)
        if a and a.get("href"):
            href = urljoin(base_url, str(a["href"]))
        out.append(
            _candidate(
                title=title,
                start=hit.get("start_date", ""),
                end=hit.get("end_date", ""),
                artists=_artists_from_title(title),
                date_citation=hit.get("date_citation", ""),
                exhibition_url=href,
            )
        )
    return out


def _candidate(
    *,
    title: str,
    start: str = "",
    end: str = "",
    artists: list[str] | None = None,
    image_url: str = "",
    date_citation: str = "",
    exhibition_url: str = "",
) -> dict[str, Any]:
    return {
        "title": title[:200],
        "start_date": start,
        "end_date": end,
        "artists": artists or [],
        "curators": [],
        "image_url": image_url,
        "date_citation": date_citation,
        "exhibition_url": exhibition_url,
    }


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
            # Some sites concatenate multiple JSON objects
            continue
        for node in _walk_json_ld(data):
            title = _clean(str(node.get("name") or node.get("headline") or ""))
            if not title or _is_nav_title(title):
                continue
            start = _ld_date(node.get("startDate"))
            end = _ld_date(node.get("endDate"))
            citation = ""
            if start or end:
                citation = f"JSON-LD startDate={start or '—'} endDate={end or '—'}"
            artists = _ld_artists(node)
            img = node.get("image")
            image_url = ""
            if isinstance(img, str):
                image_url = img
            elif isinstance(img, dict):
                image_url = str(img.get("url") or "")
            elif isinstance(img, list) and img:
                first = img[0]
                image_url = first if isinstance(first, str) else str((first or {}).get("url") or "")
            url = str(node.get("url") or node.get("@id") or "")
            out.append(
                _candidate(
                    title=title,
                    start=start,
                    end=end,
                    artists=artists[:5],
                    image_url=image_url,
                    date_citation=citation,
                    exhibition_url=url,
                )
            )
    return out


def _ld_artists(node: dict[str, Any]) -> list[str]:
    artists: list[str] = []
    for key in ("performer", "actor", "creator", "author"):
        perf = node.get(key)
        if isinstance(perf, dict) and perf.get("name"):
            artists.append(str(perf["name"]))
        elif isinstance(perf, list):
            for p in perf:
                if isinstance(p, dict) and p.get("name"):
                    artists.append(str(p["name"]))
                elif isinstance(p, str) and p.strip():
                    artists.append(p.strip())
    return artists


def _walk_json_ld(data: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            nodes.extend(_walk_json_ld(item))
        return nodes
    if not isinstance(data, dict):
        return nodes
    if "@graph" in data:
        nodes.extend(_walk_json_ld(data["@graph"]))
    typ = data.get("@type") or ""
    types = typ if isinstance(typ, list) else [typ]
    types_lower = [str(t).lower() for t in types]
    interesting = {
        "exhibitionevent",
        "event",
        "visualartwork",
        "exhibition",
        "creativework",
    }
    if any(t in interesting for t in types_lower) or (
        data.get("startDate") and data.get("name")
    ):
        nodes.append(data)
    for key, val in data.items():
        if key in {"@graph", "@context"}:
            continue
        if isinstance(val, (dict, list)):
            nodes.extend(_walk_json_ld(val))
    return nodes


def _ld_date(val: Any) -> str:
    if not val:
        return ""
    s = str(val).strip()
    hit = date_extract.extract_date_range(s)
    if hit["start_date"]:
        return hit["start_date"]
    if hit["end_date"]:
        return hit["end_date"]
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", s)
    return m.group(1) if m else ""


def _parse_time_blocks(html: str, base_url: str) -> list[dict[str, Any]]:
    """Associate <time datetime> with nearby headings (Berlinische Galerie, etc.)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for time_el in soup.find_all("time"):
        dt = str(time_el.get("datetime") or "")
        parent = time_el.find_parent(["article", "li", "div", "section", "figure"])
        if not parent:
            continue
        title = ""
        for tag in ("h1", "h2", "h3", "h4", "h5"):
            h = parent.find(tag)
            if h and h.get_text(strip=True):
                title = _clean(h.get_text(" ", strip=True))
                break
        if not title:
            link = parent.find("a", href=True)
            if link:
                title = _clean(link.get_text(" ", strip=True))
        if not title or _is_nav_title(title):
            continue
        times = parent.find_all("time")
        datetimes = [str(t.get("datetime") or "") for t in times]
        texts = [t.get_text(" ", strip=True) for t in times]
        block_text = _clean(parent.get_text(" ", strip=True))
        hit = date_extract.dates_from_time_elements(datetimes, texts)
        if not (hit["start_date"] or hit["end_date"]):
            hit = date_extract.extract_date_range(block_text)
        if not (hit["start_date"] or hit["end_date"]) and dt:
            hit = {
                "start_date": "",
                "end_date": _ld_date(dt),
                "date_citation": f"time@{dt}",
            }
        href = ""
        a = parent.find("a", href=True)
        if a:
            href = urljoin(base_url, str(a["href"]))
        out.append(
            _candidate(
                title=title,
                start=hit.get("start_date", ""),
                end=hit.get("end_date", ""),
                artists=_artists_from_title(title),
                date_citation=hit.get("date_citation", ""),
                exhibition_url=href,
            )
        )
    return out


def _parse_dom_cards(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if not _looks_like_exhibition_link(href):
            continue
        title = _heading_near(a)
        if not title or _is_nav_title(title) or len(title) < 4:
            continue
        parent = a.find_parent(["article", "li", "div", "section"])
        block = _clean(
            parent.get_text(" ", strip=True) if parent else a.get_text(" ", strip=True)
        )
        # Prefer a compact window around the title for date citation accuracy
        window = block
        idx = block.casefold().find(title.casefold())
        if idx >= 0:
            window = block[idx : idx + max(220, len(title) + 160)]
        # Also scan following siblings for date-only lines (common on listing cards)
        if parent is not None:
            sib_bits: list[str] = []
            for sib in list(parent.next_siblings)[:6]:
                if getattr(sib, "get_text", None):
                    sib_bits.append(_clean(sib.get_text(" ", strip=True)))
                elif isinstance(sib, str):
                    sib_bits.append(_clean(sib))
            if sib_bits:
                window = f"{window} {' '.join(sib_bits)}"
        hit = date_extract.extract_date_range(window)
        if not (hit["start_date"] or hit["end_date"]):
            hit = date_extract.extract_date_range(block)
        img = a.find("img")
        image_url = ""
        if img and img.get("src"):
            image_url = urljoin(base_url, str(img["src"]))
        out.append(
            _candidate(
                title=title,
                start=hit.get("start_date", ""),
                end=hit.get("end_date", ""),
                artists=_artists_from_title(title),
                image_url=image_url,
                date_citation=hit.get("date_citation", ""),
                exhibition_url=urljoin(base_url, href),
            )
        )

    for el in soup.find_all(True, class_=True):
        classes = " ".join(el.get("class") or [])
        if not _CARD_HINT.search(classes):
            continue
        h = el.find(["h1", "h2", "h3", "h4", "h5"])
        if not h:
            continue
        title = _clean(h.get_text(" ", strip=True))
        if _is_nav_title(title) or len(title) < 4:
            continue
        block = _clean(el.get_text(" ", strip=True))
        hit = date_extract.extract_date_range(block)
        href = ""
        a = el.find("a", href=True)
        if a:
            href = urljoin(base_url, str(a["href"]))
        out.append(
            _candidate(
                title=title,
                start=hit.get("start_date", ""),
                end=hit.get("end_date", ""),
                artists=_artists_from_title(title),
                date_citation=hit.get("date_citation", ""),
                exhibition_url=href,
            )
        )

    return out


def _looks_like_exhibition_link(href: str) -> bool:
    h = href.lower()
    keys = (
        "exhibition",
        "exhibitions",
        "programme",
        "program",
        "whats-on",
        "whatson",
        "event",
        "show",
        "expo",
        "expositions",
        "exposiciones",
        "ausstellung",
        "calendar",
        "agenda",
        "on-view",
        "current",
    )
    return any(x in h for x in keys)


def _heading_near(a: Any) -> str:
    for tag in ("h1", "h2", "h3", "h4", "h5"):
        h = a.find(tag)
        if h and h.get_text(strip=True):
            return _clean(h.get_text(" ", strip=True))
    parent = a.find_parent(["article", "li", "div"])
    if parent:
        h = parent.find(["h1", "h2", "h3", "h4", "h5"])
        if h and h.get_text(strip=True):
            return _clean(h.get_text(" ", strip=True))
    text = _clean(a.get_text(" ", strip=True))
    return text if 4 <= len(text) <= 160 else ""


def _artists_from_title(title: str) -> list[str]:
    if "—" in title or "–" in title:
        left = re.split(r"[—–]", title, maxsplit=1)[0].strip()
        if 2 <= len(left.split()) <= 5:
            return [left]
    return []
