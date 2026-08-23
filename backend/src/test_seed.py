"""Run temporary test seeds (e.g. Hong Kong) and promote reliable sources."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import crawl_log
import crawler_probe
import database
import exhibition_records
import export
import fetch_sources
import seed
import url_discovery

TEST_SEED_JSON = database.BACKEND_ROOT / "data" / "seed_hongkong_test.json"
TEST_RESULTS_JSON = database.BACKEND_ROOT / "data" / "hongkong_test_results.json"
TEST_EXHIBITIONS_CSV = database.ROOT_DATA_DIR / "hongkong_test_exhibitions.csv"


def load_test_seed(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or TEST_SEED_JSON
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    return [seed._validate_venue({**item, "status": item.get("status", "test")}) for item in raw]


def run_test_seed(
    *,
    test_path: Path | None = None,
    promote: bool = True,
) -> dict[str, Any]:
    """
    Probe each test institution, extract flat records, log failures.
    Promote passing venues to seed_institutions.json when promote=True.
    """
    venues = load_test_seed(test_path)
    conn = database.connect()
    database.init_schema(conn)
    ts = database.now_iso()

    results: list[dict[str, Any]] = []
    promoted: list[str] = []
    all_records: list[dict[str, Any]] = []

    for venue in venues:
        slug = venue["slug"]
        listing_url = venue["exhibitions_url"]

        # Try configured listing URL first; discover from homepage if needed
        probe = crawler_probe.probe_crawler_chain(venue, listing_url=listing_url)

        if not probe["success"]:
            home_row = seed.venue_to_fetch_row({**venue, "exhibitions_url": venue["website"]})
            import pandas as pd

            home_fr = fetch_sources.fetch_source(pd.Series(home_row))
            discovered, was_discovered = url_discovery.discover_exhibitions_url(
                website=venue["website"],
                current_url=listing_url,
                html=home_fr.get("html"),
                status_code=home_fr.get("status_code"),
            )
            if was_discovered and discovered != listing_url:
                listing_url = discovered
                probe = crawler_probe.probe_crawler_chain(venue, listing_url=listing_url)

        if probe["success"]:
            winning_crawler = probe["crawler"]
            venue = {**venue, "exhibitions_url": probe["url"], "crawler": winning_crawler}
            fr = probe["fetch"]
            extracted = probe["extracted"]
            records = exhibition_records.build_flat_records(
                venue,
                extracted,
                fr,
                scraped_at=ts,
                listing_url=probe["url"],
            )
            ok_records = [r for r in records if r.get("fetch_status") == "ok"]
            passed = len(ok_records) > 0

            if passed:
                for rec in ok_records:
                    all_records.append({**rec, "venue_slug": slug})
                if promote:
                    _promote_venue(venue)
                    promoted.append(slug)

            crawl_log.log_event(
                conn,
                venue_slug=slug,
                institution_name=venue["name"],
                city=venue["city"],
                event_type="test_pass" if passed else "test_parse_empty",
                http_status=fr.get("status_code"),
                message=f"crawler={winning_crawler} records={len(ok_records)}",
            )

            results.append(
                {
                    "institution": venue["name"],
                    "slug": slug,
                    "city": venue["city"],
                    "passed": passed,
                    "crawler": winning_crawler,
                    "website": venue["website"],
                    "exhibitions_url": probe["url"],
                    "exhibition_count": len(ok_records),
                    "attempts": probe["attempts"],
                    "timestamp": ts,
                }
            )
        else:
            reason = crawler_probe.classify_error(probe["attempts"])
            err_type = reason
            last_url = probe.get("url") or listing_url
            last_status = probe["attempts"][-1].get("http_status") if probe["attempts"] else None

            crawl_log.log_event(
                conn,
                venue_slug=slug,
                institution_name=venue["name"],
                city=venue["city"],
                event_type="test_fail",
                http_status=last_status,
                message=f"{err_type} | url={last_url} | {probe['attempts'][-1].get('error', '')}",
            )

            results.append(
                {
                    "institution": venue["name"],
                    "slug": slug,
                    "city": venue["city"],
                    "passed": False,
                    "crawler": None,
                    "website": venue["website"],
                    "exhibitions_url": last_url,
                    "error_type": err_type,
                    "http_status": last_status,
                    "reason": probe["attempts"][-1].get("error") if probe["attempts"] else reason,
                    "attempts": probe["attempts"],
                    "timestamp": ts,
                }
            )

    conn.commit()

    summary = {
        "tested": len(venues),
        "passed": sum(1 for r in results if r.get("passed")),
        "failed": sum(1 for r in results if not r.get("passed")),
        "promoted": promoted,
        "timestamp": ts,
        "results": results,
    }

    TEST_RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with TEST_RESULTS_JSON.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
        f.write("\n")

    _export_test_exhibitions(all_records)

    if promote and promoted:
        seed.sync_seed_registry()
        for v in seed.load_seed():
            database.upsert_venue(conn, v)
        conn.commit()
        export.export_all_csvs(conn)

    return summary


def _promote_venue(venue: dict[str, Any]) -> None:
    """Append venue to active seed if not already present."""
    active_path = seed.SEED_JSON
    with active_path.open(encoding="utf-8") as f:
        active = json.load(f)
    slugs = {v["slug"] for v in active}
    if venue["slug"] in slugs:
        return
    promoted = {
        **venue,
        "status": "active",
    }
    active.append(promoted)
    with active_path.open("w", encoding="utf-8") as f:
        json.dump(active, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _export_test_exhibitions(records: list[dict[str, Any]]) -> None:
    import csv

    TEST_EXHIBITIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = export.FLAT_FIELDS
    with TEST_EXHIBITIONS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            row = {k: rec.get(k, "") for k in fields}
            w.writerow(row)
