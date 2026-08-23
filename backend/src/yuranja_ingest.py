"""City-coverage ingestion: crawl accessible sources, enrich, dedupe, report."""

from __future__ import annotations

import json
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import crawl_log
import database
import exhibition_enrich
import exhibition_records
import export
import extract_content
import fetch_sources
import seed
import yuranja_model

REPORT_MD = database.BACKEND_ROOT / "reports" / "city_ingest_report.md"
REPORT_JSON = database.BACKEND_ROOT / "data" / "city_ingest_report.json"

PRIORITY_CITIES = [
    "Berlin",
    "Hong Kong",
    "Venice",
    "New York",
    "London",
    "Taipei",
    "Seoul",
    "Tokyo",
    "Mexico City",
    "Paris",
    "Brussels",
    "São Paulo",
]


def _flat_from_yuranja(y: dict[str, Any], venue: dict[str, Any]) -> dict[str, Any]:
    admission = y.get("admission") or {}
    return {
        "id": y["id"],
        "venue_slug": venue["slug"],
        "name": y.get("venue") or venue["name"],
        "city": y.get("city") or venue["city"],
        "country": y.get("country") or venue["country"],
        "address": y.get("address") or venue.get("address", ""),
        "category": venue["category"],
        "importance": venue["importance"],
        "website": y.get("website") or venue["website"],
        "exhibitions_url": venue["exhibitions_url"],
        "title": y.get("title", ""),
        "start_date": (y.get("dates") or {}).get("start", ""),
        "end_date": (y.get("dates") or {}).get("end", ""),
        "artists": json.dumps(y.get("artists") or [], ensure_ascii=False),
        "curators": json.dumps(y.get("curators") or [], ensure_ascii=False),
        "status": y.get("status", "current"),
        "image_url": "",
        "source_url": y.get("source_url") or venue["exhibitions_url"],
        "crawler": venue["crawler"],
        "scraped_at": y.get("scraped_at", ""),
        "updated_at": y.get("updated_at", ""),
        "fetch_status": y.get("fetch_status", "ok"),
        "error_detail": y.get("error_detail", ""),
        "opening_hours": y.get("openingHours", ""),
        "description": y.get("description", ""),
        "format": y.get("format", ""),
        "categories": json.dumps(y.get("categories") or [], ensure_ascii=False),
        "media_types": json.dumps(y.get("mediaTypes") or [], ensure_ascii=False),
        "admission_status": admission.get("status", "unknown"),
        "admission_display": admission.get(
            "display",
            "Admission not published — check the official visitor information",
        ),
        "admission_from_price": admission.get("fromPrice", ""),
        "admission_reservation_required": (
            None
            if admission.get("status") == "unknown"
            else bool(admission.get("reservationRequired"))
        ),
        "admission_ticket_url": admission.get("ticketUrl", ""),
        "admission_checked_at": admission.get("checkedAt", ""),
        "admission_information_url": admission.get("informationUrl", ""),
        "admission_information_label": admission.get("informationLabel", ""),
        "exhibition_url": y.get("exhibitionUrl", ""),
        "citations_json": json.dumps(y.get("citations") or [], ensure_ascii=False),
        "dedupe_key": y.get("dedupe_key", ""),
        "is_duplicate": bool(y.get("is_duplicate")),
        "archive_status": y.get("archive_status", "active"),
        "editorial_status": y.get("editorial_status", "pending"),
        "date_checked": y.get("dateChecked", ""),
        "amenities": y.get("amenities", ""),
    }


def run_city_ingest(*, force: bool = True) -> dict[str, Any]:
    conn = database.connect()
    database.init_schema(conn)

    venues = seed.load_seed()
    for v in venues:
        database.upsert_venue(conn, v)
    seed.export_venue_csv(venues, database.SOURCES_CSV)
    seed.export_venue_csv(venues, database.ROOT_DATA_DIR / "sources.csv")
    conn.commit()

    visitor_index = exhibition_enrich.load_visitor_index()
    ts_now = database.now_iso()

    report: dict[str, Any] = {
        "generated_at": ts_now,
        "cities": PRIORITY_CITIES,
        "sources_attempted": 0,
        "sources_successfully_accessed": 0,
        "sources_marked_manual_or_inactive": 0,
        "exhibitions_found": 0,
        "exhibitions_with_verified_dates": 0,
        "exhibitions_with_verified_admission": 0,
        "duplicate_records_removed": 0,
        "missing_required_fields": {},
        "by_city": {},
        "source_results": [],
        "errors": [],
    }

    city_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sources_attempted": 0,
            "sources_ok": 0,
            "sources_manual_or_inactive": 0,
            "exhibitions": 0,
        }
    )

    for venue in venues:
        slug = venue["slug"]
        city = venue["city"]
        status = str(venue.get("status", "active")).strip().lower()
        crawler = str(venue.get("crawler", "html")).strip().lower()

        entry: dict[str, Any] = {
            "slug": slug,
            "name": venue["name"],
            "city": city,
            "status": status,
            "crawler": crawler,
            "url": venue["exhibitions_url"],
            "result": "",
            "exhibitions": 0,
        }

        if status in {"manual", "inactive", "blocked", "removed"} or crawler == "manual":
            report["sources_marked_manual_or_inactive"] += 1
            city_stats[city]["sources_manual_or_inactive"] += 1
            entry["result"] = f"skipped:{status or crawler}"
            report["source_results"].append(entry)
            crawl_log.log_event(
                conn,
                venue_slug=slug,
                institution_name=venue["name"],
                city=city,
                event_type="skipped_manual",
                message=f"status={status} crawler={crawler}",
            )
            continue

        report["sources_attempted"] += 1
        city_stats[city]["sources_attempted"] += 1

        try:
            dbrow = database.get_venue(conn, slug)
            last_checked = str(dbrow["last_checked"] or "") if dbrow else ""
            fetch_row = seed.venue_to_fetch_row(venue)

            if fetch_sources.should_skip_incremental(
                force=force,
                csv_last_checked=last_checked,
                db_last_checked=last_checked,
            ):
                entry["result"] = "skipped:incremental"
                report["source_results"].append(entry)
                continue

            fetch = fetch_sources.fetch_source(fetch_row)
            extracted = extract_content.extract(fetch)
            listing_url = str(fetch.get("final_url") or fetch.get("url") or venue["exhibitions_url"])

            if fetch.get("status") != "ok":
                entry["result"] = f"error:{fetch.get('error') or fetch.get('status')}"
                report["errors"].append(f"{venue['name']}: {entry['result']}")
                report["source_results"].append(entry)
                crawl_log.log_event(
                    conn,
                    venue_slug=slug,
                    institution_name=venue["name"],
                    city=city,
                    event_type="fetch_error",
                    http_status=fetch.get("status_code"),
                    message=str(fetch.get("error") or ""),
                )
                continue

            report["sources_successfully_accessed"] += 1
            city_stats[city]["sources_ok"] += 1
            entry["result"] = "ok"

            flats = exhibition_records.build_flat_records(
                venue,
                extracted,
                fetch,
                scraped_at=ts_now,
                listing_url=listing_url,
            )

            visitor = visitor_index.lookup(
                source_url=listing_url,
                institution=venue["name"],
                city=city,
                exhibitions_url=venue["exhibitions_url"],
            )

            # Replace prior crawl rows for this venue so undated nav junk does not linger
            database.delete_exhibitions_for_venue(conn, slug)

            written = 0
            for flat in flats:
                if flat.get("title") in {"(unavailable)", ""} and flat.get("fetch_status") == "error":
                    continue
                # Prefer dated exhibition candidates; keep undated only when no dated rows exist
                y = yuranja_model.build_yuranja_record(
                    flat,
                    venue=venue,
                    visitor=visitor,
                    checked_at=ts_now,
                    editorial_status="pending",
                )
                db_row = _flat_from_yuranja(y, venue)
                db_row["date_citation"] = str(flat.get("date_citation") or "")
                # Preserve existing editorial status if record already exists under same id
                existing = conn.execute(
                    "SELECT editorial_status FROM exhibitions WHERE id = ?",
                    (db_row["id"],),
                ).fetchone()
                if existing and existing["editorial_status"]:
                    db_row["editorial_status"] = existing["editorial_status"]
                # Never auto-approve; undated remain pending and are excluded from export
                if db_row.get("editorial_status") == "approved" and not (
                    db_row.get("start_date") or db_row.get("end_date")
                ):
                    db_row["editorial_status"] = "pending"
                database.upsert_exhibition(conn, db_row)
                written += 1
                report["exhibitions_found"] += 1
                city_stats[city]["exhibitions"] += 1
                dates = y.get("dates") or {}
                if dates.get("start") or dates.get("end"):
                    report["exhibitions_with_verified_dates"] += 1
                if (y.get("admission") or {}).get("status") != "unknown":
                    report["exhibitions_with_verified_admission"] += 1
                missing = yuranja_model.missing_required_fields(y)
                for field in missing:
                    report["missing_required_fields"][field] = (
                        int(report["missing_required_fields"].get(field, 0)) + 1
                    )

            entry["exhibitions"] = written
            database.update_venue_last_checked(conn, slug, ts_now)
            crawl_log.log_event(
                conn,
                venue_slug=slug,
                institution_name=venue["name"],
                city=city,
                event_type="ingest_ok",
                http_status=fetch.get("status_code"),
                message=f"exhibitions={written}",
            )
            report["source_results"].append(entry)

        except Exception as e:  # noqa: BLE001
            msg = f"{venue['name']}: {e}"
            traceback.print_exc()
            report["errors"].append(msg)
            entry["result"] = f"exception:{e}"
            report["source_results"].append(entry)
            crawl_log.log_event(
                conn,
                venue_slug=slug,
                institution_name=venue["name"],
                city=city,
                event_type="exception",
                message=str(e),
            )

    archived = database.archive_past_exhibitions(conn, ts_now)
    duplicates = database.mark_duplicates(conn)
    report["duplicate_records_removed"] = duplicates
    report["archived_past"] = archived
    report["by_city"] = dict(city_stats)

    conn.commit()
    export.export_all_csvs(conn)
    _write_report(report)
    report["success"] = True
    report["message"] = (
        f"Ingest complete: attempted={report['sources_attempted']} "
        f"ok={report['sources_successfully_accessed']} "
        f"manual/inactive={report['sources_marked_manual_or_inactive']} "
        f"exhibitions={report['exhibitions_found']} "
        f"duplicates={duplicates} archived={archived}"
    )
    print(report["message"])
    print(f"Report: {REPORT_MD}")
    return report


def _write_report(report: dict[str, Any]) -> None:
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    lines = [
        "# City ingest report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Sources attempted: **{report['sources_attempted']}**",
        f"- Sources successfully accessed: **{report['sources_successfully_accessed']}**",
        f"- Sources marked manual or inactive: **{report['sources_marked_manual_or_inactive']}**",
        f"- Exhibitions found: **{report['exhibitions_found']}**",
        f"- Exhibitions with verified dates: **{report['exhibitions_with_verified_dates']}**",
        f"- Exhibitions with verified admission: **{report['exhibitions_with_verified_admission']}**",
        f"- Duplicate records removed: **{report['duplicate_records_removed']}**",
        f"- Past exhibitions archived: **{report.get('archived_past', 0)}**",
        "",
        "## Missing required fields",
        "",
    ]
    missing = report.get("missing_required_fields") or {}
    if missing:
        for field, count in sorted(missing.items()):
            lines.append(f"- `{field}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Coverage by city", ""])
    for city in PRIORITY_CITIES:
        stats = (report.get("by_city") or {}).get(city) or {}
        lines.append(
            f"- **{city}**: attempted={stats.get('sources_attempted', 0)}, "
            f"ok={stats.get('sources_ok', 0)}, "
            f"manual/inactive={stats.get('sources_manual_or_inactive', 0)}, "
            f"exhibitions={stats.get('exhibitions', 0)}"
        )

    lines.extend(["", "## Source results", ""])
    for row in report.get("source_results") or []:
        lines.append(
            f"- `{row['city']}` / {row['name']}: {row['result']} "
            f"(exhibitions={row.get('exhibitions', 0)}, status={row.get('status')})"
        )

    if report.get("errors"):
        lines.extend(["", "## Errors", ""])
        for err in report["errors"]:
            lines.append(f"- {err}")

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
