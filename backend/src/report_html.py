"""Generate a human-readable HTML report from pulse_updates.csv."""

from __future__ import annotations

import csv
import html
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from database import BACKEND_ROOT, PULSE_CSV

REPORTS_DIR = BACKEND_ROOT / "reports"
DEFAULT_OUTPUT = REPORTS_DIR / "pulse_report.html"


def _safe_float(x: str | float | None, default: float = 0.0) -> float:
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _sort_key(row: dict[str, str]) -> tuple[str, float]:
    label = (row.get("pulse_label") or "").strip()
    score = _safe_float(row.get("score"))
    return (label, -score)


def _pct(score: float) -> str:
    return f"{round(score * 100)}%"


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.is_file():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def generate_pulse_report(
    csv_path: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """Read pulse CSV and write standalone HTML. Returns output path."""
    src = Path(csv_path or PULSE_CSV)
    dst = Path(out_path or DEFAULT_OUTPUT)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    rows = _load_rows(src)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    by_city: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        city = (row.get("city") or "Other").strip() or "Other"
        by_city[city].append(row)

    for city in by_city:
        by_city[city].sort(key=_sort_key)

    city_order = sorted(by_city.keys(), key=lambda c: c.lower())

    parts: list[str] = []
    parts.append(_html_header(generated, len(rows), str(src)))

    if not rows:
        parts.append(
            '<p class="empty">No rows found in the CSV. Run '
            "<code>python backend/src/main.py run</code> first.</p>"
        )
    else:
        for city in city_order:
            parts.append(f'<section class="city" aria-labelledby="{_slug(city)}">')
            parts.append(f'  <h2 id="{_slug(city)}">{html.escape(city)}</h2>')
            parts.append('  <div class="cards">')
            for row in by_city[city]:
                parts.append(_render_card(row))
            parts.append("  </div>")
            parts.append("</section>")

    parts.append(_html_footer())
    dst.write_text("".join(parts), encoding="utf-8")
    return dst


def _slug(city: str) -> str:
    s = "".join(c if c.isalnum() else "-" for c in city.lower()).strip("-")
    return f"city-{s or 'other'}"


def _badge_class(label: str) -> str:
    return {
        "Institutional": "badge badge--institutional",
        "Buzz": "badge badge--buzz",
        "Momentum": "badge badge--momentum",
    }.get(label, "badge")


def _render_card(row: dict[str, str]) -> str:
    city = html.escape((row.get("city") or "").strip())
    institution = html.escape((row.get("institution") or "").strip() or "—")
    exhibition = html.escape((row.get("exhibition_title") or "").strip() or "—")
    artists = html.escape((row.get("artist_names") or "").strip() or "—")
    end_date = html.escape((row.get("end_date") or "").strip() or "—")

    label = (row.get("pulse_label") or "").strip() or "Pulse"
    score = _safe_float(row.get("score"))
    badge_cls = _badge_class(label)

    reason = html.escape((row.get("reason") or "").strip())
    reason_block = ""
    if reason:
        reason_block = f'<p class="sub-scores muted">{reason}</p>'

    summary = html.escape((row.get("public_summary") or "").strip() or "—")

    entry_fee = (row.get("entry_fee") or "").strip()
    audio_yes = (row.get("audio_guide_available") or "").strip()
    audio_lang = (row.get("audio_guide_languages") or "").strip()
    amenities = (row.get("amenities") or "").strip()

    visitor_lines: list[str] = []
    if entry_fee:
        visitor_lines.append(
            f"<p><span class=\"field-label\">Entry</span>{html.escape(entry_fee)}</p>"
        )
    if audio_yes or audio_lang:
        bits = []
        if audio_yes:
            bits.append(f"available: {html.escape(audio_yes)}")
        if audio_lang:
            bits.append(html.escape(audio_lang))
        visitor_lines.append(
            "<p><span class=\"field-label\">Audio guide</span>"
            + (" · ".join(bits) if bits else "—")
            + "</p>"
        )
    if amenities:
        visitor_lines.append(
            f"<p><span class=\"field-label\">Amenities</span>{html.escape(amenities)}</p>"
        )
    visitor_block = ""
    if visitor_lines:
        visitor_block = (
            '<div class="field">' + "".join(visitor_lines) + "</div>"
        )

    g = (row.get("google_rating") or "").strip()
    h = (row.get("hashtag_count") or "").strip()
    m = (row.get("mention_count") or "").strip()
    s = (row.get("sentiment_score") or "").strip()
    social_note = ""
    if not any([g, h, s]) and (m in ("", "0")):
        social_note = (
            '<p class="sub-scores muted">Public ratings & hashtags are not collected automatically '
            "(manual entry or approved APIs only).</p>"
        )
    else:
        parts = []
        if g:
            parts.append(f"Google rating: {html.escape(g)}")
        if h:
            parts.append(f"Hashtag count: {html.escape(h)}")
        if m:
            parts.append(f"Mentions: {html.escape(m)}")
        if s:
            parts.append(f"Sentiment: {html.escape(s)}")
        social_note = (
            '<p class="sub-scores muted">' + " · ".join(parts) + "</p>"
        )

    url = (row.get("source_url") or "").strip()
    url_esc = html.escape(url, quote=True)

    fetch_raw = (row.get("fetch_status") or "").strip()
    fetch_disp = fetch_raw.replace("_", " ").title() if fetch_raw else "—"
    fetch_line = html.escape(fetch_disp)

    err = (row.get("error_detail") or "").strip()
    err_block = ""
    if err:
        err_block = (
            '<div class="field error" role="alert">'
            '<span class="field-label">What went wrong</span>'
            f"<p>{html.escape(err)}</p>"
            "</div>"
        )

    review_raw = (row.get("human_review_status") or row.get("human_review") or "").strip()
    if not review_raw:
        review = "pending"
    elif review_raw.lower() == "pending review":
        review = "pending"
    else:
        review = review_raw
    review_esc = html.escape(review)

    link_inner = html.escape(url or "No link provided")
    link_html = (
        f'<a class="source-link" href="{url_esc}" target="_blank" rel="noopener noreferrer">'
        f"{link_inner}</a>"
        if url
        else f'<span class="muted">{link_inner}</span>'
    )

    return f"""    <article class="card">
      <div class="card-top">
        <p class="kicker">{city}</p>
        <h3 class="institution">{institution}</h3>
        <p class="exhibition"><span class="field-label">Exhibition</span><br>{exhibition}</p>
        <p class="exhibition"><span class="field-label">Artists</span><br>{artists}</p>
        <p class="exhibition"><span class="field-label">End date</span><br>{end_date}</p>
        <div class="pulse-row">
          <span class="{_badge_class(label)}" aria-label="Pulse label">{html.escape(label)}</span>
          <span class="score" aria-label="Pulse score">{_pct(score)}</span>
        </div>
        {reason_block}
      </div>
      <div class="field">
        <span class="field-label">Public summary</span>
        <p class="summary">{summary}</p>
      </div>
      {visitor_block}
      <div class="field">
        <span class="field-label">Signals</span>
        {social_note}
      </div>
      <div class="field">
        <span class="field-label">Fetch status</span>
        <p>{fetch_line}</p>
      </div>
      <div class="field">
        <span class="field-label">Source</span>
        <p class="url">{link_html}</p>
      </div>
      {err_block}
      <div class="field review">
        <span class="field-label">Human review</span>
        <p>{review_esc}</p>
      </div>
    </article>
"""


def _html_header(generated: str, count: int, source_path: str) -> str:
    title = "Art Guide Pulse Monitor — Report"
    entry_word = "entry" if count == 1 else "entries"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #faf9f7;
      --card: #ffffff;
      --text: #1c1b19;
      --muted: #5c5852;
      --line: #e6e3dd;
      --accent: #2c5282;
      --inst: #2d3748;
      --buzz: #9b2c2c;
      --mom: #276749;
      --error-bg: #fff5f5;
      --error-border: #feb2b2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Georgia", "Times New Roman", serif;
      font-size: 17px;
      line-height: 1.55;
      color: var(--text);
      background: var(--bg);
    }}
    main {{ max-width: 52rem; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
    header {{
      border-bottom: 1px solid var(--line);
      background: var(--card);
      padding: 2rem 1.25rem;
    }}
    header .inner {{ max-width: 52rem; margin: 0 auto; }}
    h1 {{
      font-size: 1.65rem;
      font-weight: 500;
      letter-spacing: 0.02em;
      margin: 0 0 0.35rem;
    }}
    .meta {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .meta code {{ font-size: 0.8rem; }}
    h2 {{
      font-size: 1.2rem;
      font-weight: 600;
      margin: 2.25rem 0 1rem;
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .cards {{
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 1.35rem 1.4rem 1.5rem;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }}
    .kicker {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      margin: 0 0 0.35rem;
    }}
    .institution {{
      font-size: 1.35rem;
      font-weight: 500;
      margin: 0 0 0.75rem;
      line-height: 1.25;
    }}
    .exhibition {{
      margin: 0 0 1rem;
      color: var(--text);
    }}
    .field-label {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      display: block;
      margin-bottom: 0.25rem;
    }}
    .pulse-row {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
      margin-bottom: 0.35rem;
    }}
    .badge {{
      display: inline-block;
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 0.35rem 0.65rem;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f4f2ee;
      color: var(--text);
    }}
    .badge--institutional {{ border-color: #cbd5e0; background: #edf2f7; color: var(--inst); }}
    .badge--buzz {{ border-color: #fbb6b6; background: #fff5f5; color: var(--buzz); }}
    .badge--momentum {{ border-color: #9ae6b4; background: #f0fff4; color: var(--mom); }}
    .score {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 1.35rem;
      font-weight: 700;
      color: var(--accent);
    }}
    .sub-scores {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 0.8rem;
      margin: 0 0 1rem;
    }}
    .muted {{ color: var(--muted); }}
    .field {{ margin-top: 1rem; }}
    .field:first-of-type {{ margin-top: 0; }}
    .summary {{ margin: 0; white-space: pre-wrap; }}
    .url {{ margin: 0; word-break: break-word; }}
    .source-link {{
      color: var(--accent);
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    .source-link:hover {{ text-decoration-thickness: 2px; }}
    .error {{
      margin-top: 1rem;
      padding: 0.85rem 1rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: 8px;
    }}
    .error p {{ margin: 0.35rem 0 0; }}
    .review {{
      margin-top: 1.1rem;
      padding-top: 1rem;
      border-top: 1px dashed var(--line);
    }}
    .empty {{
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      color: var(--muted);
      padding: 2rem 0;
    }}
  </style>
</head>
<body>
  <header>
    <div class="inner">
      <h1>{html.escape(title)}</h1>
      <p class="meta">{count} {entry_word} · Generated {html.escape(generated)} · Source <code>{html.escape(source_path)}</code></p>
    </div>
  </header>
  <main>
"""


def _html_footer() -> str:
    return """
  </main>
</body>
</html>
"""
