"""CLI entrypoint for Yuranja Art Monitor."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

import database


def _parse_argv() -> tuple[str | None, bool]:
    argv = sys.argv[1:]
    if not argv:
        return None, False
    cmd = argv[0].strip().lower()
    force = "--force" in argv[1:]
    return cmd, force


def cmd_seed_sync() -> dict[str, Any]:
    """Load seed_institutions.json into DB and export venue CSVs."""
    import seed

    conn = database.connect()
    database.init_schema(conn)
    venues = seed.sync_seed_registry()
    for v in venues:
        if v.get("status", "active") == "active":
            database.upsert_venue(conn, v)
    conn.commit()
    msg = f"Synced {len(venues)} venues from seed_institutions.json"
    print(msg)
    return {"success": True, "message": msg, "venues": len(venues)}


def cmd_run(*, force: bool) -> dict[str, Any]:
    load_dotenv(database.BACKEND_ROOT / ".env")

    import crawl_log
    import exhibition_records
    import export
    import extract_content
    import fetch_sources
    import scoring
    import seed
    import summarize
    import url_discovery

    stats: dict[str, Any] = {
        "success": True,
        "message": "",
        "venues_active": 0,
        "venues_skipped_incremental": 0,
        "venues_skipped_inactive": 0,
        "venues_processed": 0,
        "venues_removed": 0,
        "exhibitions_written": 0,
        "errors": [],
    }

    try:
        conn = database.connect()
        database.init_schema(conn)

        venues = seed.load_seed()
        for v in venues:
            database.upsert_venue(conn, v)
        conn.commit()

        ts_now = database.now_iso()

        for venue in venues:
            slug = venue["slug"]
            status = str(venue.get("status", "active")).strip().lower()
            if status != "active":
                stats["venues_skipped_inactive"] += 1
                continue

            stats["venues_active"] += 1

            try:
                dbrow = database.get_venue(conn, slug)
                last_checked = str(dbrow["last_checked"] or "") if dbrow else ""

                fetch_row = seed.venue_to_fetch_row(venue)
                if fetch_sources.should_skip_incremental(
                    force=force,
                    csv_last_checked=last_checked,
                    db_last_checked=last_checked,
                ):
                    print(f"[skip] incremental: {venue['name']}")
                    stats["venues_skipped_incremental"] += 1
                    continue

                listing_url = venue["exhibitions_url"]
                fr = fetch_sources.fetch_source(fetch_row)

                # URL discovery when listing page fails
                if fr.get("status") != "ok":
                    crawl_log.log_event(
                        conn,
                        venue_slug=slug,
                        institution_name=venue["name"],
                        city=venue["city"],
                        event_type="fetch_error",
                        http_status=fr.get("status_code"),
                        message=str(fr.get("error") or "listing fetch failed"),
                    )
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
                    if was_discovered and discovered != listing_url:
                        print(f"[discover] {venue['name']}: {discovered}")
                        crawl_log.log_event(
                            conn,
                            venue_slug=slug,
                            institution_name=venue["name"],
                            city=venue["city"],
                            event_type="url_discovered",
                            message=discovered,
                        )
                        listing_url = discovered
                        database.update_venue_exhibitions_url(conn, slug, listing_url)
                        venue = {**venue, "exhibitions_url": listing_url}
                        fetch_row = seed.venue_to_fetch_row(venue)
                        fr = fetch_sources.fetch_source(fetch_row)

                if fr.get("skipped"):
                    print(f"[skip] {fr.get('skip_reason')}: {venue['name']}")
                    continue

                stats["venues_processed"] += 1
                extracted = extract_content.extract(fr)
                summary = summarize.placeholder_summary(extracted, fetch_row)

                database.delete_exhibitions_for_venue(conn, slug)

                records = exhibition_records.build_flat_records(
                    venue,
                    extracted,
                    fr,
                    scraped_at=ts_now,
                    listing_url=listing_url,
                )

                fetch_failed = fr.get("status") != "ok" or not extracted.get("ok")
                if fetch_failed:
                    failures = crawl_log.increment_failure(conn, slug)
                    crawl_log.log_event(
                        conn,
                        venue_slug=slug,
                        institution_name=venue["name"],
                        city=venue["city"],
                        event_type="parse_error",
                        http_status=fr.get("status_code"),
                        message=str(
                            extracted.get("error") or fr.get("error") or "parse failed"
                        ),
                    )
                    if failures >= database.FAILURE_THRESHOLD:
                        reason = (
                            f"Removed after {failures} consecutive failures: "
                            f"{extracted.get('error') or fr.get('error')}"
                        )
                        database.set_venue_status(conn, slug, "removed")
                        crawl_log.log_removal(
                            conn,
                            venue_slug=slug,
                            institution_name=venue["name"],
                            city=venue["city"],
                            reason=reason,
                            http_status=fr.get("status_code"),
                        )
                        stats["venues_removed"] += 1
                        print(f"[removed] {venue['name']}: {reason}")
                else:
                    crawl_log.reset_failure(conn, slug)

                for rec in records:
                    db_rec = {**rec, "venue_slug": slug}
                    database.upsert_exhibition(conn, db_rec)
                    stats["exhibitions_written"] += 1

                    if rec.get("fetch_status") == "ok":
                        mini = {
                            **extracted,
                            "ok": True,
                            "text": (
                                f"{rec.get('title', '')} {rec.get('artists', '')} "
                                f"{rec.get('end_date', '')}\n"
                                f"{(extracted.get('text') or '')[:4000]}"
                            ),
                        }
                        scores = scoring.score_pulse_full(mini, summary, fetch_row)
                        database.insert_pulse_score(
                            conn,
                            exhibition_id=rec["id"],
                            score=float(scores["primary_score"]),
                            pulse_label=str(scores["primary_label"]),
                            reason=str(scores["reason"]),
                            human_review_status="pending",
                            created_at=ts_now,
                        )

                database.update_venue_last_checked(conn, slug, ts_now)

            except Exception as e:  # noqa: BLE001
                msg = f"{venue['name']}: {e}"
                print(f"[error] {msg}")
                traceback.print_exc()
                stats["errors"].append(msg)
                crawl_log.log_event(
                    conn,
                    venue_slug=slug,
                    institution_name=venue["name"],
                    city=venue["city"],
                    event_type="exception",
                    message=str(e),
                )

        conn.commit()
        counts = export.export_all_csvs(conn)
        stats["exports"] = counts
        stats["message"] = (
            "Run complete — "
            + ", ".join(f"{k}={v}" for k, v in counts.items())
        )
        print(stats["message"])
        return stats

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {
            "success": False,
            "message": str(e),
            **{k: stats.get(k, 0) for k in stats if k != "errors"},
            "errors": [*stats.get("errors", []), str(e)],
        }


def cmd_report() -> dict[str, Any]:
    load_dotenv(database.BACKEND_ROOT / ".env")
    import report_html

    path = report_html.generate_pulse_report()
    msg = f"Report written to {path}"
    print(msg)
    return {"success": True, "message": msg, "path": str(path)}


def main() -> None:
    cmd, force = _parse_argv()
    if cmd is None:
        print(
            "Usage: python backend/src/main.py run [--force] | crawl-reliable | seed-sync | cleanup | test-hongkong | report",
            file=sys.stderr,
        )
        sys.exit(1)

    if cmd == "run":
        result = cmd_run(force=force)
        if result.get("message"):
            print(result["message"])
    elif cmd == "seed-sync":
        result = cmd_seed_sync()
        if result.get("message"):
            print(result["message"])
    elif cmd == "crawl-reliable":
        load_dotenv(database.BACKEND_ROOT / ".env")
        import reliable_crawl

        result = reliable_crawl.run_reliable_crawl(force=True)
        print(result.get("message", ""))
        if result.get("errors"):
            for e in result["errors"]:
                print(f"  [error] {e}")
    elif cmd == "cleanup":
        load_dotenv(database.BACKEND_ROOT / ".env")
        import cleanup_seed

        result = cleanup_seed.cleanup_seed()
        print(
            f"Cleanup: active={result['kept']} "
            f"(reliable={result['reliable_count']}, html_access={result['html_access_count']}), "
            f"removed={result['removed']}"
        )
        for r in result["reliable_institutions"]:
            print(f"  [RELIABLE] {r['name']} — {r['exhibition_count']} exhibitions")
        for r in result["html_access_institutions"]:
            print(f"  [HTML ACCESS] {r['name']} — {r['reason']}")
        for r in result["removed_institutions"]:
            print(f"  [REMOVED] {r['name']} — {r['reason']}")
        print("Report: backend/reports/reliable_html_institutions.md")
    elif cmd == "test-hongkong":
        load_dotenv(database.BACKEND_ROOT / ".env")
        import test_seed

        result = test_seed.run_test_seed(promote=True)
        print(
            f"Hong Kong test: {result['passed']}/{result['tested']} passed, "
            f"{result['failed']} failed, promoted: {', '.join(result['promoted']) or 'none'}"
        )
        for r in result["results"]:
            status = "PASS" if r["passed"] else "FAIL"
            crawler = r.get("crawler") or r.get("error_type", "?")
            print(f"  [{status}] {r['institution']} — {crawler}")
        if result.get("message"):
            print(result["message"])
    elif cmd == "report":
        if force:
            print("note: --force applies only to run", file=sys.stderr)
        result = cmd_report()
        if result.get("message"):
            print(result["message"])
    else:
        print(
            f"Unknown command: {cmd!r}. Expected: run | crawl-reliable | seed-sync | cleanup | test-hongkong | report",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
