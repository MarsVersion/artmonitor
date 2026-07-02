"""CLI entrypoint for the Art Monitor pulse backend."""

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


def cmd_run(*, force: bool) -> dict[str, Any]:
    """
    Run the crawl pipeline (same as `python backend/src/main.py run [--force]`).
    Returns a JSON-serializable summary for the dashboard API.
    """
    load_dotenv(database.BACKEND_ROOT / ".env")

    import export
    import extract_content
    import fetch_sources
    import metadata_extract
    import scoring
    import summarize

    stats: dict[str, Any] = {
        "success": True,
        "message": "",
        "sources_active": 0,
        "sources_skipped_incremental": 0,
        "sources_skipped_registry": 0,
        "sources_fetch_skipped": 0,
        "sources_processed": 0,
        "errors": [],
    }

    try:
        conn = database.connect()
        database.init_schema(conn)

        df = fetch_sources.load_sources()
        df = df.fillna("")

        for _, row in df.iterrows():
            if str(row.get("status") or "").strip().lower() == "active":
                stats["sources_active"] += 1

        # Sync registry into SQLite (does not touch last_checked on conflict).
        for _, row in df.iterrows():
            database.upsert_source(conn, row.to_dict())
        conn.commit()

        ts_now = database.now_iso()

        for idx, row in df.iterrows():
            status = str(row.get("status") or "").strip().lower()
            if status != "active":
                stats["sources_skipped_registry"] += 1
                continue

            try:
                sid = database.upsert_source(conn, row.to_dict())
                dbrow = database.get_source_row(conn, sid)
                db_lc = str(dbrow["last_checked"] or "") if dbrow else ""
                csv_lc = str(row.get("last_checked") or "")

                if fetch_sources.should_skip_incremental(
                    force=force,
                    csv_last_checked=csv_lc,
                    db_last_checked=db_lc,
                ):
                    print(f"[skip] incremental recheck window: {row.get('source_name')}")
                    stats["sources_skipped_incremental"] += 1
                    continue

                fr = fetch_sources.fetch_source(row)
                if fr.get("skipped"):
                    print(f"[skip] {fr.get('skip_reason')}: {row.get('source_name')}")
                    stats["sources_fetch_skipped"] += 1
                    continue

                stats["sources_processed"] += 1

                extracted = extract_content.extract(fr)
                summary = summarize.placeholder_summary(extracted, row)

                url = str(row.get("source_url") or "").strip()
                database.delete_children_for_source(conn, sid)
                database.delete_visitor_for_url(conn, url)
                database.delete_signals_for_url(conn, url)

                exhibitions = metadata_extract.extract_exhibitions(extracted, fr, row)
                for ex in exhibitions:
                    mini = {
                        **extracted,
                        "ok": True,
                        "text": (
                            f"{ex.get('exhibition_title', '')} "
                            f"{ex.get('artist_names', '')} "
                            f"{ex.get('end_date', '')}\n"
                            f"{(extracted.get('text') or '')[:4000]}"
                        ),
                    }
                    scores = scoring.score_pulse_full(mini, summary, row)

                    eid = database.insert_exhibition(
                        conn,
                        source_id=sid,
                        city=str(ex.get("city") or ""),
                        institution=str(ex.get("institution") or ""),
                        exhibition_title=str(ex.get("exhibition_title") or ""),
                        artist_names=str(ex.get("artist_names") or ""),
                        start_date=str(ex.get("start_date") or ""),
                        end_date=str(ex.get("end_date") or ""),
                        source_url=str(ex.get("source_url") or ""),
                        raw_text=str(ex.get("raw_text") or ""),
                        public_summary=summary,
                        last_updated=ts_now,
                        fetch_status=str(ex.get("fetch_status") or "ok"),
                        error_detail=str(ex.get("error_detail") or ""),
                    )
                    database.insert_pulse_score(
                        conn,
                        exhibition_id=eid,
                        score=float(scores["primary_score"]),
                        pulse_label=str(scores["primary_label"]),
                        reason=str(scores["reason"]),
                        human_review_status="pending",
                        created_at=ts_now,
                    )

                visitor = metadata_extract.extract_visitor_info(extracted, row)
                if visitor and fr.get("status") == "ok" and extracted.get("ok"):
                    database.insert_visitor_info(
                        conn,
                        institution=visitor["institution"],
                        city=visitor["city"],
                        entry_fee=visitor["entry_fee"],
                        audio_guide_available=visitor["audio_guide_available"],
                        audio_guide_languages=visitor["audio_guide_languages"],
                        amenities=visitor["amenities"],
                        source_url=visitor["source_url"],
                        last_updated=ts_now,
                    )

                if fr.get("status") == "ok" and extracted.get("ok"):
                    sig = metadata_extract.build_signals_placeholder(row)
                    database.insert_signals(
                        conn,
                        institution=sig["institution"],
                        city=sig["city"],
                        google_rating=sig["google_rating"] or None,
                        hashtag_count=sig["hashtag_count"] or None,
                        mention_count=sig["mention_count"] or None,
                        sentiment_score=sig["sentiment_score"] or None,
                        source_url=sig["source_url"],
                        last_updated=ts_now,
                    )

                database.update_source_last_checked(conn, sid, ts_now)
                df.at[idx, "last_checked"] = ts_now

            except Exception as e:  # noqa: BLE001 — keep batch resilient
                msg = f"{row.get('source_name')!s}: {e}"
                print(f"[error] {msg}")
                traceback.print_exc()
                stats["errors"].append(msg)

        conn.commit()

        col_order = [
            "city",
            "source_name",
            "source_url",
            "source_type",
            "trust_level",
            "access_method",
            "status",
            "last_checked",
            "notes",
        ]
        df[col_order].to_csv(database.SOURCES_CSV, index=False)

        counts = export.export_all_csvs(conn)
        stats["exports"] = counts
        stats["message"] = (
            "Run complete — CSV exports: "
            + ", ".join(f"{k}={v}" for k, v in counts.items())
        )
        print(stats["message"])
        return stats

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {
            "success": False,
            "message": str(e),
            "sources_active": stats.get("sources_active", 0),
            "sources_skipped_incremental": stats.get("sources_skipped_incremental", 0),
            "sources_skipped_registry": stats.get("sources_skipped_registry", 0),
            "sources_fetch_skipped": stats.get("sources_fetch_skipped", 0),
            "sources_processed": stats.get("sources_processed", 0),
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
            "Usage: python backend/src/main.py run [--force] | report",
            file=sys.stderr,
        )
        sys.exit(1)

    if cmd == "run":
        result = cmd_run(force=force)
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
            f"Unknown command: {cmd!r}. Expected: run | report",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
