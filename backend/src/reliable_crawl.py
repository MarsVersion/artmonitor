"""Crawl only Tier-1 reliable HTML institutions into flat Yuranja records."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import crawl_log
import database
import exhibition_records
import export
import extract_content
import fetch_sources
import seed
import url_discovery

RELIABLE_JSON = database.BACKEND_ROOT / "data" / "reliable_html_institutions.json"
CRAWL_REPORT_MD = database.BACKEND_ROOT / "reports" / "crawl_report.md"
CRAWL_REPORT_JSON = database.BACKEND_ROOT / "data" / "crawl_report.json"
EXHIBITIONS_JSON = database.ROOT_DATA_DIR / "exhibitions.json"


def load_reliable_venues() -> list[dict[str, Any]]:
    """Merge reliable list with full seed metadata (address, importance)."""
    if not RELIABLE_JSON.is_file():
        raise FileNotFoundError(f"Missing {RELIABLE_JSON}. Run: python backend/src/main.py cleanup")

    with RELIABLE_JSON.open(encoding="utf-8") as f:
        reliable = json.load(f)

    seed_by_slug = {v["slug"]: v for v in seed.load_seed()}
    pool_path = database.BACKEND_ROOT / "data" / "seed_institutions_pool.json"
    if pool_path.is_file():
        with pool_path.open(encoding="utf-8") as f:
            for item in json.load(f):
                seed_by_slug.setdefault(item["slug"], seed._validate_venue(item))

    venues: list[dict[str, Any]] = []
    for row in reliable:
        if row.get("crawler", "html") != "html":
            continue
        slug = row["slug"]
        base = seed_by_slug.get(slug, {})
        venues.append(
            {
                "slug": slug,
                "name": row.get("name") or base.get("name", ""),
                "city": row.get("city") or base.get("city", ""),
                "country": row.get("country") or base.get("country", ""),
                "address": base.get("address", ""),
                "category": row.get("category") or base.get("category", "museum"),
                "importance": base.get("importance", "national"),
                "website": row.get("website") or base.get("website", ""),
                "exhibitions_url": row.get("exhibitions_url") or base.get("exhibitions_url", ""),
                "crawler": "html",
                "status": "active",
            }
        )
    return venues


def _has_title(record: dict[str, Any]) -> bool:
    t = str(record.get("title") or "").strip()
    if not t or t == "(unavailable)":
        return False
    return True


def _flat_public(record: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields; ensure crawler is html."""
    row = {k: record.get(k, "") for k in export.FLAT_FIELDS}
    row["crawler"] = "html"
    return row


def run_reliable_crawl(*, force: bool = True) -> dict[str, Any]:
    """
    Crawl reliable HTML institutions only. Writes JSON, CSV, and crawl report.
    """
    venues = load_reliable_venues()
    conn = database.connect()
    database.init_schema(conn)
    ts = database.now_iso()

    stats: dict[str, Any] = {
        "success": True,
        "total_institutions": len(venues),
        "successful_institutions": 0,
        "failed_institutions": 0,
        "total_exhibitions_extracted": 0,
        "institutions_with_zero_exhibitions": [],
        "errors": [],
        "warnings": [],
        "institution_results": [],
    }

    all_flat: list[dict[str, Any]] = []

    for venue in venues:
        slug = venue["slug"]
        venue["crawler"] = "html"
        database.upsert_venue(conn, venue)

        inst_result: dict[str, Any] = {
            "slug": slug,
            "name": venue["name"],
            "city": venue["city"],
            "success": False,
            "exhibition_count": 0,
            "error": None,
            "warnings": [],
        }

        try:
            fetch_row = seed.venue_to_fetch_row(venue)
            fetch_row["access_method"] = "web"
            fetch_row["crawler"] = "html"

            if not force:
                dbrow = database.get_venue(conn, slug)
                last_checked = str(dbrow["last_checked"] or "") if dbrow else ""
                if fetch_sources.should_skip_incremental(
                    force=False,
                    csv_last_checked=last_checked,
                    db_last_checked=last_checked,
                ):
                    inst_result["warnings"].append("skipped_incremental")
                    stats["warnings"].append(f"{venue['name']}: skipped (incremental window)")
                    stats["institution_results"].append(inst_result)
                    continue

            listing_url = venue["exhibitions_url"]
            fr = fetch_sources.fetch_source(pd.Series(fetch_row))

            if fr.get("status") != "ok":
                home_fr = url_discovery.fetch_homepage_for_discovery(
                    venue["website"],
                    fetch_fn=fetch_sources.fetch_source,
                    venue_row=fetch_row,
                )
                discovered, was_discovered = url_discovery.discover_exhibitions_url(
                    website=venue["website"],
                    current_url=listing_url,
                    html=home_fr.get("html"),
                    status_code=home_fr.get("status_code"),
                )
                if was_discovered:
                    listing_url = discovered
                    venue = {**venue, "exhibitions_url": listing_url}
                    fetch_row = seed.venue_to_fetch_row(venue)
                    fetch_row["access_method"] = "web"
                    fr = fetch_sources.fetch_source(pd.Series(fetch_row))

            extracted = extract_content.extract(fr)
            database.delete_exhibitions_for_venue(conn, slug)

            if fr.get("status") != "ok" or not extracted.get("ok"):
                err = str(fr.get("error") or extracted.get("error") or "fetch failed")
                inst_result["error"] = err
                stats["failed_institutions"] += 1
                stats["errors"].append(f"{venue['name']}: {err}")
                crawl_log.log_event(
                    conn,
                    venue_slug=slug,
                    institution_name=venue["name"],
                    city=venue["city"],
                    event_type="crawl_fail",
                    http_status=fr.get("status_code"),
                    message=err,
                )
                stats["institution_results"].append(inst_result)
                continue

            records = exhibition_records.build_flat_records(
                venue,
                extracted,
                fr,
                scraped_at=ts,
                listing_url=listing_url,
            )

            written = 0
            for rec in records:
                if rec.get("fetch_status") != "ok":
                    continue
                if not _has_title(rec):
                    stats["warnings"].append(f"{venue['name']}: skipped record with empty title")
                    continue
                for opt in ("start_date", "end_date", "artists", "curators", "image_url"):
                    if not str(rec.get(opt) or "").strip() or rec.get(opt) == "[]":
                        inst_result["warnings"].append(f"missing_{opt}")
                rec["crawler"] = "html"
                db_rec = {**rec, "venue_slug": slug}
                database.upsert_exhibition(conn, db_rec)
                all_flat.append(_flat_public(rec))
                written += 1

            if written == 0:
                stats["institutions_with_zero_exhibitions"].append(venue["name"])
                stats["warnings"].append(f"{venue['name']}: zero exhibitions after filtering")
                inst_result["success"] = True
                inst_result["exhibition_count"] = 0
            else:
                stats["successful_institutions"] += 1
                inst_result["success"] = True
                inst_result["exhibition_count"] = written
                stats["total_exhibitions_extracted"] += written

            database.update_venue_last_checked(conn, slug, ts)
            crawl_log.reset_failure(conn, slug)

        except Exception as e:  # noqa: BLE001
            inst_result["error"] = str(e)
            stats["failed_institutions"] += 1
            stats["errors"].append(f"{venue['name']}: {e}")
            crawl_log.log_event(
                conn,
                venue_slug=slug,
                institution_name=venue["name"],
                city=venue["city"],
                event_type="exception",
                message=str(e),
            )

        stats["institution_results"].append(inst_result)

    conn.commit()
    _write_exhibitions_json(all_flat)
    export.export_all_csvs(conn)
    seed.sync_seed_registry()

    stats["timestamp"] = ts
    stats["message"] = (
        f"Crawled {stats['total_institutions']} institutions — "
        f"{stats['successful_institutions']} ok, "
        f"{stats['failed_institutions']} failed, "
        f"{stats['total_exhibitions_extracted']} exhibitions"
    )
    _write_crawl_report(stats)
    return stats


def _write_exhibitions_json(records: list[dict[str, Any]]) -> None:
    EXHIBITIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with EXHIBITIONS_JSON.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _write_crawl_report(stats: dict[str, Any]) -> None:
    CRAWL_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with CRAWL_REPORT_JSON.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
        f.write("\n")

    lines = [
        "# Crawl Report — Reliable HTML Access",
        "",
        f"Generated: {stats.get('timestamp', '')}",
        "",
        "## Summary",
        "",
        f"- **Total institutions crawled:** {stats['total_institutions']}",
        f"- **Successful:** {stats['successful_institutions']}",
        f"- **Failed:** {stats['failed_institutions']}",
        f"- **Total exhibitions extracted:** {stats['total_exhibitions_extracted']}",
        f"- **Institutions with zero exhibitions:** {len(stats['institutions_with_zero_exhibitions'])}",
        "",
    ]

    if stats["institutions_with_zero_exhibitions"]:
        lines.append("### Zero-exhibition institutions")
        for name in stats["institutions_with_zero_exhibitions"]:
            lines.append(f"- {name}")
        lines.append("")

    if stats["errors"]:
        lines.extend(["## Errors", ""])
        for e in stats["errors"]:
            lines.append(f"- {e}")
        lines.append("")

    if stats["warnings"]:
        lines.extend(["## Warnings", ""])
        for w in stats["warnings"][:50]:
            lines.append(f"- {w}")
        if len(stats["warnings"]) > 50:
            lines.append(f"- … and {len(stats['warnings']) - 50} more")
        lines.append("")

    lines.extend(["## Per institution", ""])
    lines.append("| Institution | City | OK | Exhibitions | Error |")
    lines.append("|-------------|------|----|-------------|-------|")
    for r in stats["institution_results"]:
        ok = "yes" if r.get("success") and not r.get("error") else "no"
        err = (r.get("error") or "")[:60]
        lines.append(
            f"| {r['name']} | {r['city']} | {ok} | {r.get('exhibition_count', 0)} | {err} |"
        )

    CRAWL_REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    CRAWL_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
