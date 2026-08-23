"""Tests for exhibition enrichment and inquiry filtering."""

from __future__ import annotations

import unittest

import exhibition_enrich as enrich


def _row(
    *,
    slug: str = "sample",
    title: str = "Sample Show",
    venue: str = "Sample Museum",
    city: str = "Berlin",
    country: str = "Germany",
    artists: list[str] | None = None,
    entry_fee: str = "",
    amenities: str = "",
    format_value: str = "",
    categories: list[str] | None = None,
) -> dict:
    artists = artists or ["Carol Bove"]
    return enrich.enrich_exhibition_row(
        {
            "id": slug,
            "title": title,
            "name": venue,
            "city": city,
            "country": country,
            "artists": artists,
            "curators": [],
            "entry_fee": entry_fee,
            "amenities": amenities,
            "format": format_value,
            "categories": categories or [],
            "source_url": "https://example.org/exhibitions/sample",
        },
        enrich.VisitorIndex([]),
    )


class ExhibitionEnrichTests(unittest.TestCase):
    def test_entrance_fee_query_returns_known_admission_only(self) -> None:
        rows = [
            _row(slug="free-show", entry_fee="Free"),
            _row(slug="paid-show", entry_fee="From €14"),
            _row(slug="unknown-show", entry_fee=""),
        ]
        result = enrich.filter_exhibitions(rows, query="Entrance fee")
        slugs = {row["slug"] for row in result}
        self.assertEqual(slugs, {"free-show", "paid-show"})

    def test_free_admission_query_returns_only_free(self) -> None:
        rows = [
            _row(slug="free-show", entry_fee="Free"),
            _row(slug="paid-show", entry_fee="From €14"),
        ]
        result = enrich.filter_exhibitions(rows, query="Free admission")
        self.assertEqual([row["slug"] for row in result], ["free-show"])

    def test_berlin_and_free_filter(self) -> None:
        rows = [
            _row(slug="berlin-free", city="Berlin", entry_fee="Free"),
            _row(slug="berlin-paid", city="Berlin", entry_fee="€12"),
            _row(slug="tokyo-free", city="Tokyo", entry_fee="Free"),
        ]
        result = enrich.filter_exhibitions(rows, city="Berlin", admission="free")
        self.assertEqual([row["slug"] for row in result], ["berlin-free"])

    def test_paid_filter_excludes_free_and_unknown(self) -> None:
        rows = [
            _row(slug="free-show", entry_fee="Free"),
            _row(slug="paid-show", entry_fee="From €14"),
            _row(slug="unknown-show", entry_fee=""),
        ]
        result = enrich.filter_exhibitions(rows, admission="paid")
        self.assertEqual([row["slug"] for row in result], ["paid-show"])

    def test_unknown_filter_returns_unverified_admission(self) -> None:
        rows = [
            _row(slug="free-show", entry_fee="Free"),
            _row(slug="unknown-show", entry_fee=""),
        ]
        result = enrich.filter_exhibitions(rows, admission="unknown")
        self.assertEqual([row["slug"] for row in result], ["unknown-show"])

    def test_artist_search(self) -> None:
        rows = [
            _row(slug="carol", artists=["Carol Bove"]),
            _row(slug="other", artists=["Other Artist"]),
        ]
        result = enrich.filter_exhibitions(rows, query="Carol Bove")
        self.assertEqual([row["slug"] for row in result], ["carol"])

    def test_institution_search(self) -> None:
        rows = [
            _row(slug="one", venue="Neue Nationalgalerie"),
            _row(slug="two", venue="M+"),
        ]
        result = enrich.filter_exhibitions(rows, query="Neue Nationalgalerie")
        self.assertEqual([row["slug"] for row in result], ["one"])

    def test_unknown_admission_is_not_marked_free(self) -> None:
        row = _row(entry_fee="")
        self.assertEqual(row["admission"]["status"], "unknown")
        self.assertNotEqual(row["admission"]["display"].casefold(), "free")

    def test_reservation_filter(self) -> None:
        rows = [
            _row(slug="reserved", entry_fee="Paid admission · Reservation required"),
            _row(slug="open", entry_fee="Free"),
        ]
        result = enrich.filter_exhibitions(rows, admission="reservation")
        self.assertEqual([row["slug"] for row in result], ["reserved"])

    def test_visitor_lookup_by_normalised_institution(self) -> None:
        index = enrich.VisitorIndex(
            [
                {
                    "institution": "Hamburger Bahnhof – Nationalgalerie der Gegenwart",
                    "city": "Berlin",
                    "entry_fee": "Free",
                    "amenities": "Gift shop",
                    "source_url": "https://www.smb.museum/en/museums-institutions/hamburger-bahnhof/exhibitions/current/",
                    "last_updated": "2026-07-02T02:54:30.125692+00:00",
                }
            ]
        )
        row = enrich.enrich_exhibition_row(
            {
                "id": "hb-show",
                "title": "Collection",
                "name": "Hamburger Bahnhof",
                "city": "Berlin",
                "country": "Germany",
                "artists": [],
                "source_url": "https://www.smb.museum/en/museums-institutions/hamburger-bahnhof/exhibitions/current/show",
            },
            index,
        )
        self.assertEqual(row["admission"]["status"], "free")
        self.assertEqual(row["amenities"], "Gift shop")


if __name__ == "__main__":
    unittest.main()
