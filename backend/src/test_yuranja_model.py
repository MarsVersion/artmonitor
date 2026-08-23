"""Tests for Yuranja model: citations, dedupe, lifecycle, export gates."""

from __future__ import annotations

import unittest

import yuranja_model as ym


class YuranjaModelTests(unittest.TestCase):
    def test_dedupe_key_normalises_institution_and_title(self) -> None:
        a = ym.dedupe_key("Hamburger Bahnhof – Nationalgalerie", "Collection Show", "2026-01-01")
        b = ym.dedupe_key("hamburger bahnhof nationalgalerie", "collection  show", "2026-01-01")
        self.assertEqual(a, b)

    def test_unknown_admission_never_marked_free(self) -> None:
        record = ym.build_yuranja_record(
            {
                "id": "x",
                "title": "Untitled",
                "name": "Venue",
                "city": "Berlin",
                "country": "Germany",
                "artists": "[]",
                "curators": "[]",
                "source_url": "https://example.org/show",
            },
            venue={
                "slug": "venue",
                "name": "Venue",
                "city": "Berlin",
                "country": "Germany",
                "address": "Street 1",
                "website": "https://example.org",
                "exhibitions_url": "https://example.org/show",
            },
            visitor=None,
            checked_at="2026-08-23T12:00:00+00:00",
        )
        self.assertEqual(record["admission"]["status"], "unknown")
        self.assertEqual(record["editorial_status"], "pending")
        self.assertNotEqual(record["admission"]["display"].casefold(), "free")

    def test_past_shows_are_archived(self) -> None:
        record = ym.build_yuranja_record(
            {
                "id": "past",
                "title": "Old Show",
                "name": "Venue",
                "city": "Berlin",
                "country": "Germany",
                "start_date": "2020-01-01",
                "end_date": "2020-02-01",
                "artists": "[]",
                "source_url": "https://example.org/old",
            },
            venue={
                "slug": "venue",
                "name": "Venue",
                "city": "Berlin",
                "country": "Germany",
                "address": "",
                "website": "https://example.org",
                "exhibitions_url": "https://example.org/old",
            },
            checked_at="2026-08-23",
        )
        self.assertEqual(record["status"], "past")
        self.assertEqual(record["archive_status"], "archived")

    def test_citations_include_source_fields(self) -> None:
        record = ym.build_yuranja_record(
            {
                "id": "cite",
                "title": "Cited Show",
                "name": "Venue",
                "city": "Tokyo",
                "country": "Japan",
                "start_date": "2026-06-01",
                "end_date": "2026-09-01",
                "artists": '["Artist"]',
                "source_url": "https://example.org/cited",
            },
            venue={
                "slug": "venue",
                "name": "Venue",
                "city": "Tokyo",
                "country": "Japan",
                "address": "1 Chome",
                "website": "https://example.org",
                "exhibitions_url": "https://example.org/cited",
            },
            visitor={"entry_fee": "Free", "last_updated": "2026-08-01"},
            checked_at="2026-08-23",
        )
        fields = {c["field"] for c in record["citations"]}
        self.assertIn("title", fields)
        self.assertIn("dates", fields)
        self.assertIn("admission", fields)
        self.assertEqual(record["admission"]["status"], "free")


if __name__ == "__main__":
    unittest.main()
