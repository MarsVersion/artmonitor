"""Official admission / visitor-information URL resolution for Yuranja."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

UNKNOWN_DISPLAY = "Admission not published — check the official visitor information"
UNKNOWN_DISPLAY_SHORT = "Admission not published"

THIRD_PARTY_HOST_HINTS = (
    "google.",
    "tripadvisor.",
    "facebook.",
    "instagram.",
    "twitter.",
    "x.com",
    "tiktok.",
    "youtube.",
    "yelp.",
    "timeout.",
    "eventbrite.",
    "viator.",
    "getyourguide.",
    "tiqets.",
    "feverup.",
    "meetup.",
    "linkedin.",
)

TICKET_PATH_HINT = re.compile(
    r"/(?:ticket|tickets|admission|visit|visitor|plan-your-visit|plan-your|"
    r"prices|pricing|buy-tickets|get-tickets|billets|tarif|tarifs|"
    r"entrada|entradas|visitas?)\b",
    re.I,
)
VISIT_PATH_HINT = re.compile(
    r"/(?:visit|visitor|plan-your-visit|plan-your|hours|opening|"
    r"pratique|informations-pratiques|acceso|acceso-y-horarios)\b",
    re.I,
)
EXHIBITION_PATH_HINT = re.compile(
    r"/(?:exhibition|exhibitions|expo|exposition|exposicion|exposiciones|"
    r"program|programme|calendar|event|archives?)\b",
    re.I,
)


def normalize_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    return text.rstrip()


def host_of(url: str) -> str:
    try:
        return (urlparse(normalize_url(url)).hostname or "").casefold()
    except Exception:
        return ""


def is_third_party_url(url: str) -> bool:
    host = host_of(url)
    if not host:
        return True
    return any(hint in host for hint in THIRD_PARTY_HOST_HINTS)


def is_official_http_url(url: str) -> bool:
    text = normalize_url(url)
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    if is_third_party_url(text):
        return False
    return True


def is_ticket_or_admission_url(url: str) -> bool:
    """True when the path looks like a genuine ticket/admission page."""
    text = normalize_url(url)
    if not is_official_http_url(text):
        return False
    path = (urlparse(text).path or "").casefold()
    query = (urlparse(text).query or "").casefold()
    hay = f"{path}?{query}"
    return bool(TICKET_PATH_HINT.search(hay) or "ticket" in hay or "admission" in hay or "billet" in hay)


def classify_information_url(url: str) -> str:
    """Return informationLabel for a non-ticket official URL."""
    text = normalize_url(url)
    if not text:
        return ""
    path = (urlparse(text).path or "/").rstrip("/") or "/"
    if VISIT_PATH_HINT.search(path):
        return "Official visitor information"
    if EXHIBITION_PATH_HINT.search(path) or path.count("/") >= 2:
        # Dedicated exhibition/detail paths
        if EXHIBITION_PATH_HINT.search(path):
            return "Official exhibition page"
        # Deep paths that aren't bare homepage
        if path not in {"", "/", "/en", "/fr", "/jp", "/es", "/de", "/ko", "/zh"}:
            # Prefer exhibition label when path suggests a show page
            if any(x in path for x in ("/event", "/detail", "/show", "/expo")):
                return "Official exhibition page"
    if path in {"", "/", "/en", "/fr", "/jp", "/es", "/de", "/ko", "/zh"} or path.count("/") <= 1:
        return "Institution website"
    if VISIT_PATH_HINT.search(path):
        return "Official visitor information"
    return "Official visitor information"


def url_reachable(url: str, *, timeout: float = 6.0) -> bool:
    """Lightweight reachability check; rejects clearly broken URLs."""
    text = normalize_url(url)
    if not is_official_http_url(text):
        return False
    try:
        import requests

        response = requests.head(
            text,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "ArtMonitorAdmissionCheck/1.0"},
        )
        if response.status_code in {405, 403, 401}:
            response = requests.get(
                text,
                timeout=timeout,
                allow_redirects=True,
                headers={"User-Agent": "ArtMonitorAdmissionCheck/1.0"},
                stream=True,
            )
            response.close()
        return 200 <= int(response.status_code) < 400
    except Exception:
        return False


def resolve_admission_links(
    *,
    ticket_url: str = "",
    exhibition_url: str = "",
    website: str = "",
    visitor_ticket_url: str = "",
    visitor_info_url: str = "",
    validate_reachability: bool = False,
) -> dict[str, str]:
    """Pick ticketUrl / informationUrl / informationLabel from official sources only.

    Priority for informationUrl:
    1. Official ticket/admission page (also usable as lookup destination)
    2. Official visitor-information page
    3. Official exhibition page
    4. Official institution homepage
    """
    candidates_ticket = [
        normalize_url(ticket_url),
        normalize_url(visitor_ticket_url),
    ]
    # A visit-path website may itself be a ticket/admission page.
    website_n = normalize_url(website)
    if website_n and is_ticket_or_admission_url(website_n):
        candidates_ticket.append(website_n)

    ticket = ""
    for cand in candidates_ticket:
        if cand and is_ticket_or_admission_url(cand) and is_official_http_url(cand):
            if validate_reachability and not url_reachable(cand):
                continue
            ticket = cand
            break

    info_candidates: list[tuple[str, str]] = []

    def _add(url: str, label: str) -> None:
        u = normalize_url(url)
        if u and is_official_http_url(u):
            info_candidates.append((u, label))

    # 1) Ticket/admission page as strongest lookup destination
    if ticket:
        _add(ticket, "Official visitor information")

    # 2) Explicit visitor-info URL
    visit = normalize_url(visitor_info_url)
    if visit:
        _add(visit, classify_information_url(visit) or "Official visitor information")

    # Website only if it looks like a visit/admission page (not bare homepage)
    if website_n and (
        is_ticket_or_admission_url(website_n) or VISIT_PATH_HINT.search(urlparse(website_n).path or "")
    ):
        _add(website_n, "Official visitor information")

    # 3) Exhibition page
    ex = normalize_url(exhibition_url)
    if ex:
        _add(ex, "Official exhibition page")

    # 4) Institution homepage last
    if website_n:
        _add(website_n, "Institution website")

    information_url = ""
    information_label = ""
    seen: set[str] = set()
    for cand, label in info_candidates:
        key = cand.casefold().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        if validate_reachability and not url_reachable(cand):
            continue
        information_url = cand
        information_label = label
        break

    return {
        "ticketUrl": ticket,
        "informationUrl": information_url,
        "informationLabel": information_label,
    }


def complete_unknown_admission(
    admission: dict[str, Any],
    *,
    exhibition_url: str = "",
    website: str = "",
    visitor: dict[str, Any] | None = None,
    checked_at: str = "",
    validate_reachability: bool = False,
) -> dict[str, Any]:
    """Ensure unknown admission carries an official information URL."""
    visitor = visitor or {}
    links = resolve_admission_links(
        ticket_url=str(admission.get("ticketUrl") or ""),
        exhibition_url=exhibition_url,
        website=website,
        visitor_ticket_url=str(visitor.get("ticket_url") or ""),
        visitor_info_url=str(
            visitor.get("visitor_info_url")
            or visitor.get("visit_url")
            or visitor.get("website")
            or ""
        ),
        validate_reachability=validate_reachability,
    )
    out = dict(admission)
    out["status"] = "unknown"
    out["display"] = UNKNOWN_DISPLAY
    out["fromPrice"] = ""
    out["reservationRequired"] = None
    # Never put a general homepage in ticketUrl
    ticket = links["ticketUrl"]
    if ticket and is_ticket_or_admission_url(ticket):
        out["ticketUrl"] = ticket
    else:
        out["ticketUrl"] = ""
    out["informationUrl"] = links["informationUrl"]
    out["informationLabel"] = links["informationLabel"] or (
        "Official visitor information" if links["informationUrl"] else ""
    )
    if checked_at and not out.get("checkedAt"):
        out["checkedAt"] = checked_at[:10]
    return out


def ensure_admission_links(
    admission: dict[str, Any],
    *,
    exhibition_url: str = "",
    website: str = "",
    visitor: dict[str, Any] | None = None,
    checked_at: str = "",
    validate_reachability: bool = False,
) -> dict[str, Any]:
    """Normalize admission object for both known and unknown statuses."""
    status = str(admission.get("status") or "unknown").casefold() or "unknown"
    if status == "unknown":
        return complete_unknown_admission(
            admission,
            exhibition_url=exhibition_url,
            website=website,
            visitor=visitor,
            checked_at=checked_at,
            validate_reachability=validate_reachability,
        )

    links = resolve_admission_links(
        ticket_url=str(admission.get("ticketUrl") or ""),
        exhibition_url=exhibition_url,
        website=website,
        visitor_ticket_url=str((visitor or {}).get("ticket_url") or ""),
        visitor_info_url=str(
            (visitor or {}).get("visitor_info_url")
            or (visitor or {}).get("visit_url")
            or ""
        ),
        validate_reachability=validate_reachability,
    )
    out = dict(admission)
    out["status"] = status
    if links["ticketUrl"]:
        out["ticketUrl"] = links["ticketUrl"]
    elif out.get("ticketUrl") and not is_ticket_or_admission_url(str(out.get("ticketUrl"))):
        # Demote non-ticket URLs out of ticketUrl into informationUrl
        demoted = normalize_url(str(out.get("ticketUrl")))
        out["ticketUrl"] = ""
        if demoted and not out.get("informationUrl"):
            out["informationUrl"] = demoted
            out["informationLabel"] = classify_information_url(demoted)
    if not out.get("informationUrl"):
        out["informationUrl"] = links["informationUrl"]
        out["informationLabel"] = links["informationLabel"]
    elif not out.get("informationLabel"):
        out["informationLabel"] = classify_information_url(str(out["informationUrl"]))
    if out.get("reservationRequired") is None:
        pass
    elif status == "unknown":
        out["reservationRequired"] = None
    if checked_at and not out.get("checkedAt"):
        out["checkedAt"] = checked_at[:10]
    return out


def has_usable_admission_link(admission: dict[str, Any]) -> bool:
    ticket = normalize_url(str(admission.get("ticketUrl") or ""))
    info = normalize_url(str(admission.get("informationUrl") or ""))
    return bool(
        (ticket and is_official_http_url(ticket))
        or (info and is_official_http_url(info))
    )


def admission_lookup_citation(
    *,
    admission: dict[str, Any],
    publisher: str,
    checked_at: str,
) -> dict[str, Any] | None:
    url = normalize_url(str(admission.get("informationUrl") or admission.get("ticketUrl") or ""))
    if not url:
        return None
    return {
        "type": "admission_lookup",
        "url": url,
        "publisher": publisher,
        "supports": ["admissionLookup"],
        "checkedAt": (checked_at or "")[:10],
    }


def information_link_kind(admission: dict[str, Any]) -> str:
    """Dashboard/report link kind: visitor | exhibition | institution | ticket."""
    label = str(admission.get("informationLabel") or "")
    if "exhibition" in label.casefold():
        return "exhibition"
    if "institution" in label.casefold() or "website" in label.casefold():
        return "institution"
    if admission.get("ticketUrl") and not admission.get("informationUrl"):
        return "ticket"
    return "visitor"
