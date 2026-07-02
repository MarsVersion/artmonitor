"""Load sources.csv, incremental policy, and fetchers (web, rss, api, manual, playwright)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import pandas as pd
import requests

from database import SOURCES_CSV

DEFAULT_HEADERS = {
    "User-Agent": (
        "ArtMonitorPulse/1.1 (+https://example.local; research; contact local@invalid)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

RECHECK_HOURS = float(os.environ.get("PULSE_RECHECK_HOURS", "24"))


def load_sources(path: str | None = None) -> pd.DataFrame:
    csv_path = path or str(SOURCES_CSV)
    df = pd.read_csv(csv_path, dtype=str)
    expected = {
        "city",
        "source_name",
        "source_url",
        "source_type",
        "trust_level",
        "access_method",
        "status",
        "last_checked",
        "notes",
    }
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"sources.csv missing columns: {sorted(missing)}")
    df["last_checked"] = df["last_checked"].fillna("")
    return df


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not str(ts).strip():
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def should_skip_incremental(
    *,
    force: bool,
    csv_last_checked: str,
    db_last_checked: str | None,
) -> bool:
    if force:
        return False
    ts = _parse_iso(db_last_checked) or _parse_iso(csv_last_checked)
    if ts is None:
        return False
    return datetime.now(timezone.utc) - ts < timedelta(hours=RECHECK_HOURS)


def _envelope(
    *,
    kind: str,
    status: str,
    status_code: int | None,
    html: str | None,
    feed: Any,
    error: str | None,
    url: str,
    meta: dict[str, Any],
    skipped: bool = False,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": status,
        "status_code": status_code,
        "html": html,
        "feed": feed,
        "error": error,
        "url": url,
        "meta": meta,
        "skipped": skipped,
        "skip_reason": skip_reason,
    }


def fetch_source(
    row: pd.Series,
    *,
    timeout: int = 45,
    playwright_timeout_ms: int = 60_000,
) -> dict[str, Any]:
    """
    Dispatch by access_method. Never upgrades to Playwright on 403/404 —
    only uses Playwright when access_method is playwright.
    """
    url = str(row["source_url"]).strip()
    meta = {k: ("" if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.items()}
    meta = {k: str(v) if v is not None else "" for k, v in meta.items()}
    method = str(meta.get("access_method") or "web").strip().lower()
    status_reg = str(meta.get("status") or "active").strip().lower()

    if status_reg in ("blocked", "inactive"):
        return _envelope(
            kind="none",
            status="skipped",
            status_code=None,
            html=None,
            feed=None,
            error=f"not fetched (status={status_reg})",
            url=url,
            meta=meta,
            skipped=True,
            skip_reason=f"status:{status_reg}",
        )

    if status_reg == "needs_review":
        return _envelope(
            kind="none",
            status="skipped",
            status_code=None,
            html=None,
            feed=None,
            error="not fetched (needs_review — set status to active after editorial check)",
            url=url,
            meta=meta,
            skipped=True,
            skip_reason="needs_review",
        )

    if status_reg != "active":
        return _envelope(
            kind="none",
            status="skipped",
            status_code=None,
            html=None,
            feed=None,
            error=f"not fetched (status={status_reg})",
            url=url,
            meta=meta,
            skipped=True,
            skip_reason=f"status:{status_reg}",
        )

    if method == "manual":
        return _envelope(
            kind="none",
            status="skipped",
            status_code=None,
            html=None,
            feed=None,
            error="manual access_method — no automatic fetch",
            url=url,
            meta=meta,
            skipped=True,
            skip_reason="manual",
        )

    if method == "rss" or _is_rss_row(row):
        return _fetch_feed(url, meta, timeout=timeout)

    if method == "playwright":
        return _fetch_playwright(url, meta, timeout_ms=playwright_timeout_ms)

    if method == "api":
        return _fetch_api(url, meta, timeout=timeout)

    # default web
    return _fetch_http(url, meta, timeout=timeout)


def _is_rss_row(row: pd.Series) -> bool:
    st = str(row.get("source_type", "")).lower()
    url = str(row.get("source_url", "")).lower()
    if "rss" in st or "feed" in st or "atom" in st:
        return True
    return any(url.endswith(s) for s in (".xml", ".rss", "/feed", "/rss", "/atom"))


def _fetch_http(url: str, meta: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        ok = r.ok
        return _envelope(
            kind="html",
            status="ok" if ok else "error",
            status_code=r.status_code,
            html=r.text if ok else None,
            feed=None,
            error=None if ok else (r.reason or f"HTTP {r.status_code}"),
            url=url,
            meta=meta,
        )
    except requests.RequestException as e:
        return _envelope(
            kind="html",
            status="error",
            status_code=None,
            html=None,
            feed=None,
            error=str(e),
            url=url,
            meta=meta,
        )


def _fetch_api(url: str, meta: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    """Generic GET with optional bearer token — TODO: per-vendor API clients."""
    headers = dict(DEFAULT_HEADERS)
    token = os.environ.get("PULSE_API_TOKEN") or os.environ.get("API_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        ok = r.ok
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ok and "xml" in ctype:
            return _envelope(
                kind="html",
                status="ok",
                status_code=r.status_code,
                html=r.text,
                feed=None,
                error=None,
                url=url,
                meta=meta,
            )
        if ok and "json" in ctype:
            return _envelope(
                kind="html",
                status="ok",
                status_code=r.status_code,
                html=r.text,
                feed=None,
                error=None,
                url=url,
                meta=meta,
            )
        return _envelope(
            kind="html",
            status="ok" if ok else "error",
            status_code=r.status_code,
            html=r.text if ok else None,
            feed=None,
            error=None if ok else (r.reason or f"HTTP {r.status_code}"),
            url=url,
            meta=meta,
        )
    except requests.RequestException as e:
        return _envelope(
            kind="html",
            status="error",
            status_code=None,
            html=None,
            feed=None,
            error=str(e),
            url=url,
            meta=meta,
        )


def _fetch_playwright(url: str, meta: dict[str, Any], *, timeout_ms: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return _envelope(
            kind="html",
            status="error",
            status_code=None,
            html=None,
            feed=None,
            error=f"playwright not installed: {e}",
            url=url,
            meta=meta,
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                resp = page.goto(url, wait_until="networkidle")
                status_code = resp.status if resp else None
                if status_code and status_code >= 400:
                    return _envelope(
                        kind="html",
                        status="error",
                        status_code=status_code,
                        html=None,
                        feed=None,
                        error=f"HTTP {status_code}",
                        url=url,
                        meta=meta,
                    )
                html = page.content()
                return _envelope(
                    kind="html",
                    status="ok",
                    status_code=status_code or 200,
                    html=html,
                    feed=None,
                    error=None,
                    url=url,
                    meta=meta,
                )
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 — surface Playwright failures
        return _envelope(
            kind="html",
            status="error",
            status_code=None,
            html=None,
            feed=None,
            error=str(e),
            url=url,
            meta=meta,
        )


def _fetch_feed(url: str, meta: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    _ = timeout  # feedparser manages its own fetch
    try:
        parsed = feedparser.parse(url)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            err = getattr(parsed, "bozo_exception", None)
            msg = str(err) if err else "feed parse error"
            return _envelope(
                kind="feed",
                status="error",
                status_code=None,
                html=None,
                feed=None,
                error=msg,
                url=url,
                meta=meta,
            )
        return _envelope(
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
        return _envelope(
            kind="feed",
            status="error",
            status_code=None,
            html=None,
            feed=None,
            error=str(e),
            url=url,
            meta=meta,
        )
