"""Load and sync the canonical institution seed list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from database import BACKEND_ROOT, DATA_DIR, ROOT_DATA_DIR

SEED_JSON = BACKEND_ROOT / "data" / "seed_institutions.json"

VENUE_CATEGORIES = frozenset(
    {
        "museum",
        "kunsthalle",
        "non_profit",
        "gallery",
        "residency",
        "biennale",
        "sculpture_park",
    }
)
IMPORTANCE_LEVELS = frozenset({"global", "national", "local"})
CRAWLER_TYPES = frozenset({"html", "playwright", "rss", "api", "manual"})
VENUE_STATUSES = frozenset({"active", "inactive", "manual", "blocked", "removed"})


def load_seed(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or SEED_JSON
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("seed_institutions.json must be a JSON array")
    venues: list[dict[str, Any]] = []
    for item in raw:
        venues.append(_validate_venue(item))
    return venues


def _validate_venue(item: dict[str, Any]) -> dict[str, Any]:
    slug = str(item.get("slug", "")).strip()
    if not slug:
        raise ValueError(f"venue missing slug: {item!r}")
    category = str(item.get("category", "")).strip().lower()
    importance = str(item.get("importance", "")).strip().lower()
    crawler = str(item.get("crawler", "html")).strip().lower()
    if category not in VENUE_CATEGORIES:
        raise ValueError(f"{slug}: invalid category {category!r}")
    if importance not in IMPORTANCE_LEVELS:
        raise ValueError(f"{slug}: invalid importance {importance!r}")
    if crawler not in CRAWLER_TYPES:
        raise ValueError(f"{slug}: invalid crawler {crawler!r}")
    status = str(item.get("status", "active")).strip().lower() or "active"
    if status not in VENUE_STATUSES:
        raise ValueError(f"{slug}: invalid status {status!r}")
    return {
        "slug": slug,
        "name": str(item.get("name", "")).strip(),
        "city": str(item.get("city", "")).strip(),
        "country": str(item.get("country", "")).strip(),
        "address": str(item.get("address", "")).strip(),
        "category": category,
        "importance": importance,
        "website": str(item.get("website", "")).strip().rstrip("/"),
        "exhibitions_url": str(item.get("exhibitions_url", "")).strip(),
        "crawler": crawler,
        "status": status,
    }


def venue_to_fetch_row(venue: dict[str, Any]) -> dict[str, str]:
    """Map seed venue to legacy fetch_sources row shape."""
    crawler = venue["crawler"]
    access = "playwright" if crawler == "playwright" else crawler
    if access == "html":
        access = "web"
    return {
        "city": venue["city"],
        "source_name": venue["name"],
        "source_url": venue["exhibitions_url"],
        "source_type": venue["category"],
        "trust_level": venue["importance"],
        "access_method": access,
        "status": venue.get("status", "active"),
        "last_checked": venue.get("last_checked", "") or "",
        "notes": f"seed:{venue['slug']}",
        "slug": venue["slug"],
        "website": venue["website"],
        "country": venue["country"],
        "address": venue["address"],
        "exhibitions_url": venue["exhibitions_url"],
        "crawler": venue["crawler"],
    }


def export_venue_csv(venues: list[dict[str, Any]], path: Path | None = None) -> Path:
    """Write venue registry for editors (`data/sources.csv`)."""
    import csv

    out = path or (ROOT_DATA_DIR / "sources.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "slug",
        "name",
        "city",
        "country",
        "address",
        "category",
        "importance",
        "website",
        "exhibitions_url",
        "crawler",
        "status",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for v in venues:
            w.writerow({k: v.get(k, "") for k in fields})
    return out


def sync_seed_registry(path: Path | None = None) -> list[dict[str, Any]]:
    """Load seed and refresh root + backend venue CSV snapshots."""
    venues = load_seed(path)
    export_venue_csv(venues, ROOT_DATA_DIR / "sources.csv")
    export_venue_csv(venues, DATA_DIR / "sources.csv")
    return venues
