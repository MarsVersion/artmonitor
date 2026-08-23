"""Tests for official admission / visitor-information URL handling."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import admission_links as al
import yuranja_model as ym


class AdmissionLinksTests(unittest.TestCase):
    def test_unknown_never_becomes_free(self) -> None:
        out = al.complete_unknown_admission(
            {"status": "unknown"},
            exhibition_url="https://www.mori.art.museum/en/exhibitions/ronmueck/",
            website="https://www.mori.art.museum/",
        )
        self.assertEqual(out["status"], "unknown")
        self.assertNotIn("free", out["display"].casefold())

    def test_unknown_export_has_information_url(self) -> None:
        out = al.complete_unknown_admission(
            {"status": "unknown"},
            exhibition_url="https://www.mori.art.museum/en/exhibitions/ronmueck/",
            website="https://www.mori.art.museum/",
        )
        self.assertTrue(out["informationUrl"])
        self.assertTrue(al.has_usable_admission_link(out))

    def test_ticket_url_only_for_ticket_pages(self) -> None:
        out = al.ensure_admission_links(
            {"status": "paid", "display": "From €14", "ticketUrl": "https://museum.example/"},
            exhibition_url="https://museum.example/exhibitions/show",
            website="https://museum.example/",
        )
        self.assertEqual(out["ticketUrl"], "")
        self.assertTrue(out["informationUrl"])

        out2 = al.ensure_admission_links(
            {
                "status": "paid",
                "display": "From €14",
                "ticketUrl": "https://museum.example/en/tickets",
            },
            exhibition_url="https://museum.example/exhibitions/show",
            website="https://museum.example/",
        )
        self.assertEqual(out2["ticketUrl"], "https://museum.example/en/tickets")

    def test_reservation_required_null_when_unknown(self) -> None:
        out = al.complete_unknown_admission(
            {"status": "unknown", "reservationRequired": False},
            exhibition_url="https://museum.example/exhibitions/a",
            website="https://museum.example/",
        )
        self.assertIsNone(out["reservationRequired"])

    def test_third_party_urls_rejected(self) -> None:
        self.assertTrue(al.is_third_party_url("https://www.tripadvisor.com/Attraction"))
        self.assertTrue(al.is_third_party_url("https://www.google.com/maps"))
        out = al.resolve_admission_links(
            ticket_url="https://www.tripadvisor.com/foo",
            exhibition_url="https://www.tripadvisor.com/bar",
            website="https://www.google.com/",
        )
        self.assertEqual(out["ticketUrl"], "")
        self.assertEqual(out["informationUrl"], "")

    def test_unreachable_urls_not_exported(self) -> None:
        with patch("admission_links.url_reachable", return_value=False):
            out = al.resolve_admission_links(
                exhibition_url="https://museum.example/exhibitions/a",
                website="https://museum.example/",
                validate_reachability=True,
            )
        self.assertEqual(out["informationUrl"], "")

    def test_missing_both_urls_fail_export_validation(self) -> None:
        record = {
            "editorial_status": "approved",
            "archive_status": "active",
            "is_duplicate": False,
            "status": "current",
            "dates": {"start": "2026-01-01", "end": "2026-12-31"},
            "citations": [{"type": "exhibition", "url": "https://museum.example/show"}],
            "exhibitionUrl": "https://museum.example/show",
            "admission": {"status": "unknown", "ticketUrl": "", "informationUrl": ""},
        }
        self.assertFalse(ym.export_eligible(record))

    def test_verified_admission_unchanged_status(self) -> None:
        out = al.ensure_admission_links(
            {
                "status": "free",
                "display": "Free admission",
                "fromPrice": "",
                "reservationRequired": False,
                "ticketUrl": "https://museum.example/visit",
                "checkedAt": "2026-08-01",
            },
            exhibition_url="https://museum.example/exhibitions/a",
            website="https://museum.example/",
        )
        self.assertEqual(out["status"], "free")
        self.assertEqual(out["display"], "Free admission")
        self.assertEqual(out["reservationRequired"], False)

    def test_model_unknown_includes_lookup_citation(self) -> None:
        record = ym.build_yuranja_record(
            {
                "title": "Show",
                "name": "Museum",
                "city": "Paris",
                "country": "France",
                "start_date": "2026-06-01",
                "end_date": "2026-09-01",
                "source_url": "https://museum.example/exhibitions/show",
                "exhibition_url": "https://museum.example/exhibitions/show",
            },
            venue={
                "slug": "museum",
                "name": "Museum",
                "city": "Paris",
                "country": "France",
                "address": "",
                "website": "https://museum.example/",
                "exhibitions_url": "https://museum.example/exhibitions/",
            },
            visitor=None,
            checked_at="2026-08-23",
        )
        self.assertEqual(record["admission"]["status"], "unknown")
        self.assertTrue(record["admission"]["informationUrl"])
        self.assertIsNone(record["admission"]["reservationRequired"])
        types = {c.get("type") or c.get("field") for c in record["citations"]}
        self.assertIn("admission_lookup", types)

    def test_information_label_for_exhibition_page(self) -> None:
        label = al.classify_information_url(
            "https://www.centrepompidou.fr/en/program/calendar/event/abc"
        )
        self.assertEqual(label, "Official exhibition page")


if __name__ == "__main__":
    unittest.main()
