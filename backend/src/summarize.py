"""Placeholder summaries until a real model is wired in."""

from __future__ import annotations

from typing import Any

import pandas as pd


def placeholder_summary(
    extracted: dict[str, Any],
    source_row: pd.Series,
) -> str:
    """Deterministic placeholder string for pipeline testing."""
    name = str(source_row.get("source_name", "Source")).strip()
    city = str(source_row.get("city", "")).strip()
    title = str(extracted.get("title") or "").strip() or "(no title)"
    loc = f"{city}, " if city else ""

    if not extracted.get("ok"):
        err = str(extracted.get("error") or "unknown")
        return (
            f"[PLACEHOLDER] {loc}{name}: extraction failed ({err}). "
            "Replace placeholder_summary() with a real summarizer."
        )

    excerpt = str(extracted.get("excerpt", "")).strip()
    clip = excerpt[:220] + ("…" if len(excerpt) > 220 else "")
    return (
        f"[PLACEHOLDER] {loc}{name} — page “{title}”. "
        f"Lead: {clip or '(empty excerpt)'} "
        "(swap in LLM or extractive summary later.)"
    )
