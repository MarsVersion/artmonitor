"""Extract readable text and titles from HTML or RSS payloads."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from bs4 import BeautifulSoup


def _clean_whitespace(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract(fetch: dict[str, Any]) -> dict[str, Any]:
    """
    Return { ok, title, text, excerpt, error }.
    `text` is full stripped plain text used for scoring length signals.
    """
    if fetch.get("skipped") or fetch.get("kind") == "none":
        return {
            "ok": False,
            "title": "",
            "text": "",
            "excerpt": "",
            "error": fetch.get("error") or fetch.get("skip_reason") or "skipped",
        }

    if fetch.get("status") != "ok":
        return {
            "ok": False,
            "title": "",
            "text": "",
            "excerpt": "",
            "error": fetch.get("error") or "fetch failed",
        }

    kind = fetch.get("kind")
    if kind == "html" and fetch.get("html"):
        return _extract_html(fetch["html"], fetch.get("url", ""))

    if kind == "feed" and fetch.get("feed") is not None:
        return _extract_feed(fetch["feed"])

    return {
        "ok": False,
        "title": "",
        "text": "",
        "excerpt": "",
        "error": "empty payload",
    }


def _extract_html(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = _clean_whitespace(soup.title.string)
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = _clean_whitespace(h1.get_text(" ", strip=True)) or title

    main = soup.find("main") or soup.find("article") or soup.body
    if main is None:
        text = _clean_whitespace(soup.get_text(" ", strip=True))
    else:
        text = _clean_whitespace(main.get_text(" ", strip=True))

    excerpt = text[:800] if text else ""
    return {
        "ok": bool(text),
        "title": title or url,
        "text": text,
        "excerpt": excerpt,
        "error": "" if text else "no text extracted",
    }


def _extract_feed(feed: Any) -> dict[str, Any]:
    entries = list(getattr(feed, "entries", []) or [])[:8]
    parts: list[str] = []
    titles: list[str] = []
    for e in entries:
        t = _clean_whitespace(getattr(e, "title", "") or "")
        if t:
            titles.append(t)
        summ = getattr(e, "summary", None) or getattr(e, "description", "") or ""
        if summ:
            soup = BeautifulSoup(summ, "html.parser")
            parts.append(_clean_whitespace(soup.get_text(" ", strip=True)))

    feed_title = _clean_whitespace(getattr(feed.feed, "title", "") or "Feed")
    title = titles[0] if titles else feed_title
    text = " \n".join(parts) if parts else feed_title
    excerpt = text[:800] if text else feed_title
    return {
        "ok": bool(text),
        "title": title,
        "text": text,
        "excerpt": excerpt,
        "error": "" if text else "empty feed text",
    }
