"""
Probe institution URLs with crawler fallback: html → rss → api → playwright.

Used for temporary test seeds before promotion to the active registry.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import pandas as pd
import requests

import extract_content
import fetch_sources

CRAWLER_ORDER = ("html", "rss", "api", "playwright")

RSS_SUFFIXES = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml")


def _row_for_method(venue: dict[str, Any], method: str, url: str) -> pd.Series:
    access = "web" if method == "html" else method
    return pd.Series(
        {
            "city": venue["city"],
            "source_name": venue["name"],
            "source_url": url,
            "source_type": venue["category"],
            "trust_level": venue["importance"],
            "access_method": access,
            "status": "active",
            "last_checked": "",
            "notes": f"probe:{venue['slug']}:{method}",
        }
    )


def _meaningful_extract(extracted: dict[str, Any]) -> bool:
    if not extracted.get("ok"):
        return False
    text = str(extracted.get("text") or "")
    return len(text) >= 120


def _probe_rss_feeds(website: str, timeout: int = 30) -> list[str]:
    base = website.rstrip("/") + "/"
    candidates = [urljoin(base, s.lstrip("/")) for s in RSS_SUFFIXES]
    return candidates


def _fetch_rss_url(url: str, meta: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        parsed = feedparser.parse(url)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            err = getattr(parsed, "bozo_exception", None)
            return fetch_sources._envelope(
                kind="feed",
                status="error",
                status_code=None,
                html=None,
                feed=None,
                error=str(err) if err else "feed parse error",
                url=url,
                meta=meta,
            )
        return fetch_sources._envelope(
            kind="feed",
            status="ok",
            status_code=200,
            html=None,
            feed=parsed,
            error=None,
            url=url,
            meta=meta,
        )
    except Exception as e:  # noqa: BLE001
        return fetch_sources._envelope(
            kind="feed",
            status="error",
            status_code=None,
            html=None,
            feed=None,
            error=str(e),
            url=url,
            meta=meta,
        )


def probe_crawler_chain(
    venue: dict[str, Any],
    *,
    listing_url: str | None = None,
) -> dict[str, Any]:
    """
    Try crawlers in order. Returns probe result with winning method or failure trail.
    """
    url = listing_url or venue["exhibitions_url"]
    attempts: list[dict[str, Any]] = []

    for method in CRAWLER_ORDER:
        if method == "rss":
            rss_urls = _probe_rss_feeds(venue["website"])
            for rss_url in rss_urls:
                meta = {"slug": venue["slug"], "method": "rss"}
                fr = _fetch_rss_url(rss_url, meta, timeout=30)
                extracted = extract_content.extract(fr)
                ok = fr.get("status") == "ok" and _meaningful_extract(extracted)
                attempts.append(
                    {
                        "crawler": "rss",
                        "url": rss_url,
                        "http_status": fr.get("status_code"),
                        "ok": ok,
                        "error": extracted.get("error") or fr.get("error"),
                        "text_len": len(str(extracted.get("text") or "")),
                    }
                )
                if ok:
                    return {
                        "success": True,
                        "crawler": "rss",
                        "url": rss_url,
                        "fetch": fr,
                        "extracted": extracted,
                        "attempts": attempts,
                    }
            continue

        row = _row_for_method(venue, method, url)
        fr = fetch_sources.fetch_source(row)
        extracted = extract_content.extract(fr)
        ok = fr.get("status") == "ok" and _meaningful_extract(extracted)
        attempts.append(
            {
                "crawler": method,
                "url": url,
                "http_status": fr.get("status_code"),
                "ok": ok,
                "error": extracted.get("error") or fr.get("error"),
                "text_len": len(str(extracted.get("text") or "")),
            }
        )
        if ok:
            return {
                "success": True,
                "crawler": method,
                "url": url,
                "fetch": fr,
                "extracted": extracted,
                "attempts": attempts,
            }

    return {
        "success": False,
        "crawler": None,
        "url": url,
        "fetch": None,
        "extracted": None,
        "attempts": attempts,
    }


def classify_error(attempts: list[dict[str, Any]]) -> str:
    """Summarize failure reason for logging."""
    if not attempts:
        return "no attempts"
    last = attempts[-1]
    err = str(last.get("error") or "").lower()
    code = last.get("http_status")
    if code == 403:
        return "http_403_forbidden"
    if code == 404:
        return "http_404_not_found"
    if code and int(code) >= 500:
        return f"http_{code}_server_error"
    if "ssl" in err or "certificate" in err:
        return "ssl_error"
    if "no text extracted" in err or last.get("text_len", 0) < 120:
        return "empty_text"
    if "playwright" in err:
        return "playwright_unavailable"
    if err:
        return err[:120]
    return "unstable_or_empty_results"
