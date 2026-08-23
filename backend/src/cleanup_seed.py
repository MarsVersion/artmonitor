"""Audit seed venues: strict reliable tier + relaxed HTML-access tier."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import crawler_probe
import database
import exhibition_records
import export
import seed

POOL_JSON = database.BACKEND_ROOT / "data" / "seed_institutions_pool.json"
REPORT_MD = database.BACKEND_ROOT / "reports" / "reliable_html_institutions.md"
RELIABLE_JSON = database.BACKEND_ROOT / "data" / "reliable_html_institutions.json"
HTML_ACCESS_JSON = database.BACKEND_ROOT / "data" / "html_access_institutions.json"
RELIABLE_CSV = database.ROOT_DATA_DIR / "reliable_html_institutions.csv"
HTML_ACCESS_CSV = database.ROOT_DATA_DIR / "html_access_institutions.csv"

GENERIC_TITLES = frozenset(
    {
        "exhibitions",
        "programmes",
        "programs",
        "what's on",
        "whats on",
        "current exhibitions",
        "projects",
        "exhibitions 展覽",
        "para site",
    }
)


def _is_generic_title(title: str, institution_name: str) -> bool:
    t = (title or "").strip().lower()
    n = (institution_name or "").strip().lower()
    if not t or t == n or t in GENERIC_TITLES:
        return True
    if t.endswith("exhibitions") and len(t) < 30:
        return True
    return False


def load_pool(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or POOL_JSON
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    return [seed._validate_venue(item) for item in raw]


def audit_venue(venue: dict[str, Any]) -> dict[str, Any]:
    """Probe HTML access and evaluate extraction quality."""
    base = {
        "slug": venue["slug"],
        "name": venue["name"],
        "city": venue["city"],
        "country": venue["country"],
        "category": venue["category"],
        "website": venue["website"],
        "exhibitions_url": venue["exhibitions_url"],
        "crawler": venue.get("crawler", "html"),
    }

    if venue.get("crawler", "html") != "html":
        return {
            **base,
            "tier": "remove",
            "verdict": "remove",
            "reason": "playwright_or_non_html_crawler",
            "exhibition_count": 0,
            "last_successful_crawl": None,
        }

    probe = crawler_probe.probe_crawler_chain(venue)
    if not probe["success"]:
        return {
            **base,
            "tier": "remove",
            "verdict": "remove",
            "reason": crawler_probe.classify_error(probe.get("attempts", [])),
            "http_status": probe["attempts"][-1].get("http_status") if probe.get("attempts") else None,
            "exhibition_count": 0,
            "last_successful_crawl": None,
        }

    if probe["crawler"] != "html":
        return {
            **base,
            "tier": "remove",
            "verdict": "remove",
            "reason": f"requires_{probe['crawler']}",
            "exhibition_count": 0,
            "last_successful_crawl": None,
        }

    ts = database.now_iso()
    records = exhibition_records.build_flat_records(
        venue,
        probe["extracted"],
        probe["fetch"],
        scraped_at=ts,
        listing_url=probe["url"],
    )
    ok = [r for r in records if r.get("fetch_status") == "ok"]
    dated = [r for r in ok if r.get("start_date") or r.get("end_date")]
    named = [r for r in ok if not _is_generic_title(r.get("title", ""), venue["name"])]
    text_len = len(str(probe["extracted"].get("text") or ""))

    if text_len < 120:
        tier, reason = "remove", "empty_text"
    elif not ok:
        tier, reason = "remove", "no_records_extracted"
    elif named or dated:
        tier, reason = "reliable", "html_ok_parsed"
    else:
        tier, reason = "html_access", "html_ok_access_only"

    return {
        **base,
        "exhibitions_url": probe["url"],
        "tier": tier,
        "verdict": "keep" if tier != "remove" else "remove",
        "reason": reason,
        "exhibition_count": len(ok),
        "named_exhibition_count": len(named),
        "dated_exhibition_count": len(dated),
        "text_len": text_len,
        "last_successful_crawl": ts if tier != "remove" else None,
        "http_status": probe["attempts"][0].get("http_status") if probe.get("attempts") else None,
    }


def _row_from_audit(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": a["name"],
        "city": a["city"],
        "country": a["country"],
        "category": a["category"],
        "website": a["website"],
        "exhibitions_url": a["exhibitions_url"],
        "crawler": a["crawler"],
        "last_successful_crawl": a["last_successful_crawl"],
        "exhibition_count": a["exhibition_count"],
        "named_exhibition_count": a.get("named_exhibition_count", 0),
        "dated_exhibition_count": a.get("dated_exhibition_count", 0),
        "tier": a["tier"],
        "reason": a["reason"],
        "slug": a["slug"],
    }


def _write_json_csv(
    rows: list[dict[str, Any]],
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")

    fields = [
        "name",
        "city",
        "country",
        "category",
        "website",
        "exhibitions_url",
        "crawler",
        "last_successful_crawl",
        "exhibition_count",
        "named_exhibition_count",
        "dated_exhibition_count",
        "tier",
        "reason",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def cleanup_seed(*, write_report: bool = True, use_pool: bool = True) -> dict[str, Any]:
    """
    Audit institutions from pool (default) or active seed.
    Active seed = reliable + html_access tiers.
    """
    venues = load_pool() if use_pool else seed.load_seed()
    audits = [audit_venue(v) for v in venues]

    kept_audits = [a for a in audits if a["verdict"] == "keep"]
    removed = [a for a in audits if a["verdict"] == "remove"]
    reliable = [_row_from_audit(a) for a in kept_audits if a["tier"] == "reliable"]
    html_access = [_row_from_audit(a) for a in kept_audits if a["tier"] == "html_access"]

    kept_slugs = {a["slug"] for a in kept_audits}
    kept_venues = [v for v in venues if v["slug"] in kept_slugs]
    for v in kept_venues:
        v["status"] = "active"

    with seed.SEED_JSON.open("w", encoding="utf-8") as f:
        json.dump(kept_venues, f, indent=2, ensure_ascii=False)
        f.write("\n")

    _write_json_csv(reliable, RELIABLE_JSON, RELIABLE_CSV)
    _write_json_csv(html_access, HTML_ACCESS_JSON, HTML_ACCESS_CSV)

    conn = database.connect()
    database.init_schema(conn)
    all_slugs = {v["slug"] for v in venues}
    for slug in all_slugs - kept_slugs:
        conn.execute(
            "DELETE FROM pulse_scores WHERE exhibition_id IN (SELECT id FROM exhibitions WHERE venue_slug = ?)",
            (slug,),
        )
        conn.execute("DELETE FROM exhibitions WHERE venue_slug = ?", (slug,))
        conn.execute("DELETE FROM venues WHERE slug = ?", (slug,))

    for v in kept_venues:
        database.upsert_venue(conn, v)
    conn.commit()

    seed.sync_seed_registry()
    export.export_all_csvs(conn)

    summary = {
        "audited": len(venues),
        "kept": len(kept_venues),
        "reliable_count": len(reliable),
        "html_access_count": len(html_access),
        "removed": len(removed),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reliable_institutions": reliable,
        "html_access_institutions": html_access,
        "kept_institutions": reliable + html_access,
        "removed_institutions": removed,
    }

    if write_report:
        _write_markdown_report(summary)

    return summary


def _write_markdown_report(summary: dict[str, Any]) -> None:
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Reliable HTML Access Institutions",
        "",
        f"Generated: {summary['timestamp']}",
        "",
        f"**Audited:** {summary['audited']} · **Active seed:** {summary['kept']} · "
        f"**Reliable (parsed):** {summary['reliable_count']} · "
        f"**HTML access only:** {summary['html_access_count']} · "
        f"**Removed:** {summary['removed']}",
        "",
        "## Tier 1 — Reliable HTML + parsed exhibitions",
        "",
        "| Name | City | Category | Exhibitions | Named | Dated | Last crawl |",
        "|------|------|----------|-------------|-------|-------|------------|",
    ]
    for r in summary["reliable_institutions"]:
        lines.append(
            f"| {r['name']} | {r['city']} | {r['category']} | {r['exhibition_count']} | "
            f"{r['named_exhibition_count']} | {r['dated_exhibition_count']} | "
            f"{(r['last_successful_crawl'] or '')[:10]} |"
        )

    lines.extend(
        [
            "",
            "## Tier 2 — HTML access (page loads; parsing pending improvement)",
            "",
            "| Name | City | Category | Exhibitions | Last crawl | Reason |",
            "|------|------|----------|-------------|------------|--------|",
        ]
    )
    for r in summary["html_access_institutions"]:
        lines.append(
            f"| {r['name']} | {r['city']} | {r['category']} | {r['exhibition_count']} | "
            f"{(r['last_successful_crawl'] or '')[:10]} | {r['reason']} |"
        )

    lines.extend(["", "## URLs (all active)", ""])
    for r in summary["kept_institutions"]:
        lines.append(f"### {r['name']} ({r['tier']})")
        lines.append(f"- Website: {r['website']}")
        lines.append(f"- Exhibitions: {r['exhibitions_url']}")
        lines.append("")

    if summary["removed_institutions"]:
        lines.extend(["## Removed (failed access)", ""])
        lines.append("| Name | City | Reason |")
        lines.append("|------|------|--------|")
        for r in summary["removed_institutions"]:
            lines.append(f"| {r['name']} | {r['city']} | {r['reason']} |")

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = cleanup_seed()
    print(
        f"Cleanup: active={result['kept']} "
        f"(reliable={result['reliable_count']}, html_access={result['html_access_count']}), "
        f"removed={result['removed']}"
    )
