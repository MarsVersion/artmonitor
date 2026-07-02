"""Heuristic Pulse scores (0–1) from trust metadata and extracted text."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

_BUZZ_WORDS = re.compile(
    r"\b(new|opening|now\s+on|just\s+opened|acquisition|acquired|"
    r"breaking|announce|announcing|limited|sold\s+out|"
    r"biennial|triennial|prize|award|auction)\b",
    re.IGNORECASE,
)


def score_pulse(
    extracted: dict[str, Any],
    summary: str,
    source_row: pd.Series,
) -> dict[str, float]:
    """
    Pulse labels (all 0.0–1.0):
    - pulse_institutional: trust_level + museum-like source
    - pulse_buzz: language + density heuristics
    - pulse_momentum: volume / freshness proxy from text length + buzz
    """
    trust = str(source_row.get("trust_level", "")).lower().strip()
    stype = str(source_row.get("source_type", "")).lower().strip()
    text = (extracted.get("text") or "") if extracted.get("ok") else ""
    low = summary.lower()

    institutional = _institutional_score(trust, stype)
    buzz = _buzz_score(text, low)
    momentum = _momentum_score(text, buzz, extracted.get("ok", False))

    return {
        "pulse_institutional": round(institutional, 3),
        "pulse_buzz": round(buzz, 3),
        "pulse_momentum": round(momentum, 3),
    }


def _institutional_score(trust: str, stype: str) -> float:
    base = 0.45
    if trust == "high":
        base = 0.92
    elif trust == "medium":
        base = 0.72
    elif trust == "low":
        base = 0.48

    if "museum" in stype or "institution" in stype or "gallery" in stype:
        base = min(1.0, base + 0.04)
    return max(0.0, min(1.0, base))


def _buzz_score(text: str, summary_lower: str) -> float:
    hay = f"{text}\n{summary_lower}"
    hits = len(_BUZZ_WORDS.findall(hay))
    density = min(1.0, hits / 6.0)
    length_signal = min(1.0, len(text) / 12000.0)
    return max(0.0, min(1.0, 0.25 + 0.55 * density + 0.2 * length_signal))


def _momentum_score(text: str, buzz: float, ok: bool) -> float:
    if not ok:
        return round(max(0.0, buzz * 0.35), 3)
    length_signal = min(1.0, len(text) / 9000.0)
    return max(0.0, min(1.0, 0.2 * length_signal + 0.45 * buzz + 0.15))


def _primary_label_score(inst: float, buzz: float, mom: float) -> tuple[str, float]:
    pairs = [(inst, "Institutional"), (buzz, "Buzz"), (mom, "Momentum")]
    best = max(s for s, _ in pairs)
    candidates = [(i, s, label) for i, (s, label) in enumerate(pairs) if s == best]
    _i, score, label = min(candidates, key=lambda t: t[0])
    return label, score


def score_pulse_full(
    extracted: dict[str, Any],
    summary: str,
    source_row: pd.Series,
) -> dict[str, Any]:
    """Triplet scores plus primary label/score and a short heuristic reason."""
    base = score_pulse(extracted, summary, source_row)
    label, score = _primary_label_score(
        float(base["pulse_institutional"]),
        float(base["pulse_buzz"]),
        float(base["pulse_momentum"]),
    )
    text = (extracted.get("text") or "") if extracted.get("ok") else ""
    reason = (
        "Heuristic pulse: "
        f"trust_level={source_row.get('trust_level')!s}, "
        f"source_type={source_row.get('source_type')!s}, "
        f"approx_words={len(text.split())}."
    )
    return {
        **base,
        "primary_label": label,
        "primary_score": round(float(score), 3),
        "reason": reason,
    }
