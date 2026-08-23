"""Extract exhibition dates from official page text / HTML without inventing values.

Returns only dates that appear in the source. Each hit includes the exact snippet
used as the citation.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# English + common European / East Asian month tokens (lowercase keys).
_MONTHS: dict[str, int] = {
    # EN
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # DE
    "jän": 1, "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "mai": 5,
    "juni": 6, "juli": 7, "okt": 10, "oktober": 10, "dez": 12, "dezember": 12,
    # FR
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # ES
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
    # PT
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "maio": 5,
    "junho": 6, "julho": 7, "setembro": 9, "set": 9, "outubro": 10, "out": 10,
    "novembro": 11, "dezembro": 12, "dez": 12,
    # IT
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    # NL
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "augustus": 8,
}

_MONTH_ALT = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))

_ISO = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
_DOT_YMD = re.compile(r"\b(20\d{2})\.(0?[1-9]|1[0-2])\.(0?[1-9]|[12]\d|3[01])\b")
_EU_DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2}|\d{2})\b")
_EU_RANGE = re.compile(
    r"(\d{1,2})[./](\d{1,9}|[A-Za-zÀ-ÿ]{3,12})[./]?(\d{2,4})?\s*[–—\-]\s*"
    r"(\d{1,2})[./](\d{1,9}|[A-Za-zÀ-ÿ]{3,12})[./](\d{2,4})",
    re.I,
)
# 10.JUN. - 30.AUG.2026  /  26.SEP.2026 - 07.FEB.2027
_DOT_MON = re.compile(
    rf"(\d{{1,2}})\.({_MONTH_ALT})\.?\s*(20\d{{2}})?\s*[–—\-]\s*"
    rf"(\d{{1,2}})\.({_MONTH_ALT})\.?\s*(20\d{{2}})",
    re.I,
)
# 3.7 - 4.10.2026  /  15.5 - 13.9.2026 (MASP style)
_SHORT_EU = re.compile(
    r"\b(\d{1,2})\.(\d{1,2})\s*[–—\-]\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})\b"
)
# 12 March - 23 August 2026  /  12 March – 23 August 2026
_EN_DAY_MON_RANGE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s*[–—\-]\s*(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}})\b",
    re.I,
)
# June 12 – August 15, 2026  /  December 11, 2025 – February 21, 2026
_EN_MON_DAY_RANGE = re.compile(
    rf"\b({_MONTH_ALT})\s+(\d{{1,2}}),?\s*(20\d{{2}})?\s*[–—\-]\s*"
    rf"({_MONTH_ALT})\s+(\d{{1,2}}),?\s*(20\d{{2}})\b",
    re.I,
)
# June 10 (Wed), 2026 - September 21 (Mon), 2026  (NACT Tokyo)
_EN_MON_DAY_PAREN_RANGE = re.compile(
    rf"\b({_MONTH_ALT})\s+(\d{{1,2}})\s*\([^)]+\),?\s*(20\d{{2}})\s*[–—\-]\s*"
    rf"({_MONTH_ALT})\s+(\d{{1,2}})\s*\([^)]+\),?\s*(20\d{{2}})\b",
    re.I,
)
# Through Jan 10, 2027  /  until 7.9.26  /  jusqu'au 30 août 2026
_THROUGH = re.compile(
    rf"\b(?:through|until|till|bis|jusqu'?au|hasta|até|fino\s+al|dal)\s+"
    rf"(?:(\d{{1,2}})[./](\d{{1,2}})[./](\d{{2,4}})|"
    rf"({_MONTH_ALT})\s+(\d{{1,2}}),?\s*(20\d{{2}})|"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}}))\b",
    re.I,
)
# Opens Jan 30, 2027
_OPENS = re.compile(
    rf"\b(?:opens?|opening|from|ab|desde|a\s+partir\s+de)\s+"
    rf"(?:(\d{{1,2}})[./](\d{{1,2}})[./](\d{{2,4}})|"
    rf"({_MONTH_ALT})\s+(\d{{1,2}}),?\s*(20\d{{2}})|"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}}))\b",
    re.I,
)
# 24 Jun 2026 - 27 Sep 2026  /  20 Jul 2026 - 06 Sep 2026
_EN_DMY_RANGE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}})\s*[–—\-]\s*"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}})\b",
    re.I,
)
# Sat Jun 13—Sun Sep 6 2026  /  Sat Jun 13 - Sun Sep 6, 2026
_WEEKDAY_MON_RANGE = re.compile(
    rf"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*"
    rf"({_MONTH_ALT})\s+(\d{{1,2}})\s*[–—\-]\s*"
    rf"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*"
    rf"({_MONTH_ALT})\s+(\d{{1,2}}),?\s*(20\d{{2}})\b",
    re.I,
)
# 2026 05 / 23 Sat. 2026 08 / 30 Sun.  (MOCA Taipei)
_Y_M_D_SLASH_PAIR = re.compile(
    r"\b(20\d{2})\s+(\d{1,2})\s*/\s*(\d{1,2})\b(?:\s*[A-Za-z.]{0,6})?\s+"
    r"(20\d{2})\s+(\d{1,2})\s*/\s*(\d{1,2})\b"
)
# 9.05 - 22.11 2026  /  9.5 - 22.11.2026
_DM_DM_YEAR = re.compile(
    r"\b(\d{1,2})\.(\d{1,2})\s*[–—\-]\s*(\d{1,2})\.(\d{1,2})\.?\s*(20\d{2})\b"
)
# 01 July 26 - 27 set 26  /  12 set 26 - 24 January 27
_EN_SHORT_YEAR_RANGE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{2}})\s*[–—\-]\s*"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{2}})\b",
    re.I,
)
# 01 July 26 27 set 26 (MAM: dates on adjacent lines, joined without dash)
_EN_SHORT_YEAR_PAIR = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{2}})\s+"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{2}})\b",
    re.I,
)
# Saturday 9 May to Sunday 22 November 2026
_EN_TO_RANGE = re.compile(
    rf"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+to\s+"
    rf"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}})\b",
    re.I,
)
# Now → 23 Aug.'26  /  Now -> 23 Aug 2026
_NOW_ARROW = re.compile(
    rf"\bNow\s*[→\->]+\s*(\d{{1,2}})\s+({_MONTH_ALT})\.?['’]?(20\d{{2}}|\d{{2}})\b",
    re.I,
)
# 25 Apr 2026 30 Aug 2026 (M+ consecutive bare dates)
_TWO_EN_DATES = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}})\s+"
    rf"(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d{{2}})\b",
    re.I,
)
# 2026.10.31 [Sat] - 2027.3.28 [Sun]  /  2026.7.17 [Fri] - 9.14
_JP_DOT_RANGE = re.compile(
    r"\b(20\d{2})\.(\d{1,2})\.(\d{1,2})(?:\s*\[[^\]]+\])?\s*[–—\-]\s*"
    r"(?:(20\d{2})\.)?(\d{1,2})\.(\d{1,2})\b"
)
# 28.8.26 – 1.2.27
_EU_SHORT_YEAR_RANGE = re.compile(
    r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\s*[–—\-]\s*(\d{1,2})\.(\d{1,2})\.(\d{2})\b"
)


def _safe_iso(y: int, m: int, d: int) -> str:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return ""


def _norm_year(y: str | int) -> int:
    yi = int(y)
    if yi < 100:
        return 2000 + yi if yi < 70 else 1900 + yi
    return yi


def _month(token: str) -> int | None:
    t = token.strip().lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    if t in _MONTHS:
        return _MONTHS[t]
    return _MONTHS.get(t[:3])


def _snip(text: str, start: int, end: int, pad: int = 0) -> str:
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def extract_date_range(text: str) -> dict[str, str]:
    """Return start_date, end_date, date_citation from official text only."""
    if not text:
        return {"start_date": "", "end_date": "", "date_citation": ""}

    # Prefer explicit ranges first.
    for rx, handler in (
        (_JP_DOT_RANGE, _handle_jp_dot),
        (_Y_M_D_SLASH_PAIR, _handle_y_m_d_slash),
        (_DOT_MON, _handle_dot_mon),
        (_EU_SHORT_YEAR_RANGE, _handle_eu_short_year),
        (_SHORT_EU, _handle_short_eu),
        (_DM_DM_YEAR, _handle_dm_dm_year),
        (_EN_DMY_RANGE, _handle_en_dmy_range),
        (_EN_SHORT_YEAR_RANGE, _handle_en_short_year_range),
        (_EN_SHORT_YEAR_PAIR, _handle_en_short_year_range),
        (_EN_TO_RANGE, _handle_en_to_range),
        (_WEEKDAY_MON_RANGE, _handle_weekday_mon_range),
        (_EN_DAY_MON_RANGE, _handle_en_day_mon),
        (_EN_MON_DAY_RANGE, _handle_en_mon_day),
        (_EN_MON_DAY_PAREN_RANGE, _handle_en_mon_day_paren),
        (_TWO_EN_DATES, _handle_two_en),
        (_EU_RANGE, _handle_eu_range),
        (_NOW_ARROW, _handle_now_arrow),
    ):
        m = rx.search(text)
        if m:
            start, end = handler(m)
            if start or end:
                return {
                    "start_date": start,
                    "end_date": end,
                    "date_citation": _snip(text, m.start(), m.end()),
                }

    m = _THROUGH.search(text)
    if m:
        end = _single_from_through_groups(m)
        if end:
            return {
                "start_date": "",
                "end_date": end,
                "date_citation": _snip(text, m.start(), m.end()),
            }

    m = _OPENS.search(text)
    if m:
        start = _single_from_through_groups(m)
        if start:
            return {
                "start_date": start,
                "end_date": "",
                "date_citation": _snip(text, m.start(), m.end()),
            }

    # Two ISO dates nearby
    isos = list(_ISO.finditer(text))
    if len(isos) >= 2:
        a, b = isos[0], isos[1]
        if b.start() - a.end() < 80:
            return {
                "start_date": a.group(0),
                "end_date": b.group(0),
                "date_citation": _snip(text, a.start(), b.end()),
            }
    if len(isos) == 1:
        return {
            "start_date": "",
            "end_date": isos[0].group(0),
            "date_citation": _snip(text, isos[0].start(), isos[0].end()),
        }

    dots = list(_DOT_YMD.finditer(text))
    if len(dots) >= 2 and dots[1].start() - dots[0].end() < 80:
        s = _safe_iso(int(dots[0].group(1)), int(dots[0].group(2)), int(dots[0].group(3)))
        e = _safe_iso(int(dots[1].group(1)), int(dots[1].group(2)), int(dots[1].group(3)))
        return {
            "start_date": s,
            "end_date": e,
            "date_citation": _snip(text, dots[0].start(), dots[1].end()),
        }

    eus = list(_EU_DMY.finditer(text))
    if len(eus) >= 2 and eus[1].start() - eus[0].end() < 80:
        s = _safe_iso(_norm_year(eus[0].group(3)), int(eus[0].group(2)), int(eus[0].group(1)))
        e = _safe_iso(_norm_year(eus[1].group(3)), int(eus[1].group(2)), int(eus[1].group(1)))
        return {
            "start_date": s,
            "end_date": e,
            "date_citation": _snip(text, eus[0].start(), eus[1].end()),
        }
    if len(eus) == 1:
        e = _safe_iso(_norm_year(eus[0].group(3)), int(eus[0].group(2)), int(eus[0].group(1)))
        return {
            "start_date": "",
            "end_date": e,
            "date_citation": _snip(text, eus[0].start(), eus[0].end()),
        }

    return {"start_date": "", "end_date": "", "date_citation": ""}


def _single_from_through_groups(m: re.Match[str]) -> str:
    # groups: dmy | Mon d, yyyy | d Mon yyyy
    if m.group(1) and m.group(2) and m.group(3):
        return _safe_iso(_norm_year(m.group(3)), int(m.group(2)), int(m.group(1)))
    if m.group(4) and m.group(5) and m.group(6):
        mm = _month(m.group(4))
        return _safe_iso(int(m.group(6)), mm, int(m.group(5))) if mm else ""
    if m.group(7) and m.group(8) and m.group(9):
        mm = _month(m.group(8))
        return _safe_iso(int(m.group(9)), mm, int(m.group(7))) if mm else ""
    return ""


def _handle_jp_dot(m: re.Match[str]) -> tuple[str, str]:
    y1, mo1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y2 = int(m.group(4)) if m.group(4) else y1
    mo2, d2 = int(m.group(5)), int(m.group(6))
    return _safe_iso(y1, mo1, d1), _safe_iso(y2, mo2, d2)


def _handle_dot_mon(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(2)), _month(m.group(5))
    y2 = _norm_year(m.group(6))
    y1 = _norm_year(m.group(3)) if m.group(3) else y2
    if not m1 or not m2:
        return "", ""
    return _safe_iso(y1, m1, int(m.group(1))), _safe_iso(y2, m2, int(m.group(4)))


def _handle_eu_short_year(m: re.Match[str]) -> tuple[str, str]:
    return (
        _safe_iso(_norm_year(m.group(3)), int(m.group(2)), int(m.group(1))),
        _safe_iso(_norm_year(m.group(6)), int(m.group(5)), int(m.group(4))),
    )


def _handle_short_eu(m: re.Match[str]) -> tuple[str, str]:
    y = int(m.group(5))
    return (
        _safe_iso(y, int(m.group(2)), int(m.group(1))),
        _safe_iso(y, int(m.group(4)), int(m.group(3))),
    )


def _handle_en_day_mon(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(2)), _month(m.group(4))
    y = int(m.group(5))
    if not m1 or not m2:
        return "", ""
    return _safe_iso(y, m1, int(m.group(1))), _safe_iso(y, m2, int(m.group(3)))


def _handle_en_mon_day(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(1)), _month(m.group(4))
    y2 = int(m.group(6))
    y1 = int(m.group(3)) if m.group(3) else y2
    if not m1 or not m2:
        return "", ""
    return _safe_iso(y1, m1, int(m.group(2))), _safe_iso(y2, m2, int(m.group(5)))


def _handle_en_mon_day_paren(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(1)), _month(m.group(4))
    if not m1 or not m2:
        return "", ""
    return (
        _safe_iso(int(m.group(3)), m1, int(m.group(2))),
        _safe_iso(int(m.group(6)), m2, int(m.group(5))),
    )


def _handle_two_en(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(2)), _month(m.group(5))
    if not m1 or not m2:
        return "", ""
    return (
        _safe_iso(int(m.group(3)), m1, int(m.group(1))),
        _safe_iso(int(m.group(6)), m2, int(m.group(4))),
    )


def _handle_en_dmy_range(m: re.Match[str]) -> tuple[str, str]:
    return _handle_two_en(m)


def _handle_en_short_year_range(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(2)), _month(m.group(5))
    if not m1 or not m2:
        return "", ""
    return (
        _safe_iso(_norm_year(m.group(3)), m1, int(m.group(1))),
        _safe_iso(_norm_year(m.group(6)), m2, int(m.group(4))),
    )


def _handle_weekday_mon_range(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(1)), _month(m.group(3))
    y = int(m.group(5))
    if not m1 or not m2:
        return "", ""
    return _safe_iso(y, m1, int(m.group(2))), _safe_iso(y, m2, int(m.group(4)))


def _handle_y_m_d_slash(m: re.Match[str]) -> tuple[str, str]:
    return (
        _safe_iso(int(m.group(1)), int(m.group(2)), int(m.group(3))),
        _safe_iso(int(m.group(4)), int(m.group(5)), int(m.group(6))),
    )


def _handle_dm_dm_year(m: re.Match[str]) -> tuple[str, str]:
    y = int(m.group(5))
    return (
        _safe_iso(y, int(m.group(2)), int(m.group(1))),
        _safe_iso(y, int(m.group(4)), int(m.group(3))),
    )


def _handle_en_to_range(m: re.Match[str]) -> tuple[str, str]:
    m1, m2 = _month(m.group(2)), _month(m.group(4))
    y = int(m.group(5))
    if not m1 or not m2:
        return "", ""
    return _safe_iso(y, m1, int(m.group(1))), _safe_iso(y, m2, int(m.group(3)))


def _handle_now_arrow(m: re.Match[str]) -> tuple[str, str]:
    mm = _month(m.group(2))
    if not mm:
        return "", ""
    end = _safe_iso(_norm_year(m.group(3)), mm, int(m.group(1)))
    return "", end


def _handle_eu_range(m: re.Match[str]) -> tuple[str, str]:
    # may include month names in middle groups
    g2, g5 = m.group(2), m.group(5)
    if g2.isdigit() and g5.isdigit() and m.group(6):
        y2 = _norm_year(m.group(6))
        y1 = _norm_year(m.group(3)) if m.group(3) else y2
        return (
            _safe_iso(y1, int(g2), int(m.group(1))),
            _safe_iso(y2, int(g5), int(m.group(4))),
        )
    mm1, mm2 = _month(g2), _month(g5)
    if mm1 and mm2 and m.group(6):
        y2 = _norm_year(m.group(6))
        y1 = _norm_year(m.group(3)) if m.group(3) else y2
        return (
            _safe_iso(y1, mm1, int(m.group(1))),
            _safe_iso(y2, mm2, int(m.group(4))),
        )
    return "", ""


def dates_from_time_elements(datetimes: list[str], texts: list[str]) -> dict[str, str]:
    """Use <time datetime> attributes when present (e.g. Berlinische Galerie)."""
    isos: list[str] = []
    for raw in datetimes:
        m = _ISO.search(raw or "")
        if m:
            isos.append(m.group(0))
    if len(isos) >= 2:
        return {
            "start_date": isos[0],
            "end_date": isos[1],
            "date_citation": f"time@{isos[0]}–{isos[1]}",
        }
    if len(isos) == 1:
        # Prefer pairing with visible text if it encodes a range
        for t in texts:
            hit = extract_date_range(t)
            if hit["start_date"] or hit["end_date"]:
                if not hit["end_date"]:
                    hit["end_date"] = isos[0]
                if not hit["start_date"] and hit["end_date"] != isos[0]:
                    hit["start_date"] = isos[0]
                hit["date_citation"] = hit["date_citation"] or f"time@{isos[0]}"
                return hit
        return {"start_date": "", "end_date": isos[0], "date_citation": f"time@{isos[0]}"}
    for t in texts:
        hit = extract_date_range(t)
        if hit["start_date"] or hit["end_date"]:
            return hit
    return {"start_date": "", "end_date": "", "date_citation": ""}
