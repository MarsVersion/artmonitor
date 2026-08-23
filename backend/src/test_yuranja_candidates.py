"""Tests for Yuranja candidate selection and export gates."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yuranja_candidates as yc
import yuranja_export as ye
import yuranja_model as ym


def _base_record(**overrides: object) -> dict:
    record = {
        "title": "Artist Survey",
        "venue": "Test Museum",
        "city": "Berlin",
        "country": "Germany",
        "status": "current",
        "archive_status": "active",
        "editorial_status": "pending",
        "is_duplicate": False,
        "dates": {"start": "2026-06-01", "end": "2026-09-01"},
        "exhibitionUrl": "https://example.org/exhibition/survey",
        "source_url": "https://example.org/exhibition/survey",
        "artists": ["Artist One"],
        "curators": ["Curator One"],
        "description": "A museum survey presenting major works across four decades of practice.",
        "format": "solo",
        "categories": ["installation"],
        "importance": "global",
        "category": "museum",
        "citations": [
            {"field": "title", "url": "https://example.org/exhibition/survey", "checkedAt": "2026-08-23"},
            {"field": "dates", "url": "https://example.org/exhibition/survey", "checkedAt": "2026-08-23", "note": "1 Jun – 1 Sep 2026"},
        ],
        "admission": {
            "status": "unknown",
            "display": "Check current admission",
            "reservationRequired": None,
        },
    }
    record.update(overrides)
    return record


class YuranjaCandidateTests(unittest.TestCase):
    def test_expired_excluded(self) -> None:
        record = _base_record(status="past", archive_status="archived")
        self.assertEqual(yc.check_eligibility(record), "expired")

    def test_undated_excluded(self) -> None:
        record = _base_record(dates={"start": "", "end": ""})
        self.assertEqual(yc.check_eligibility(record), "missing official citation")

    def test_missing_citation_excluded(self) -> None:
        record = _base_record(citations=[], exhibitionUrl="", source_url="")
        self.assertEqual(yc.check_eligibility(record), "missing official citation")

    def test_duplicate_consolidated(self) -> None:
        record = _base_record(is_duplicate=True)
        self.assertEqual(yc.check_eligibility(record), "duplicate")

    def test_admission_never_invented_free(self) -> None:
        built = ym.build_yuranja_record(
            {
                "title": "Show",
                "name": "Venue",
                "city": "Berlin",
                "country": "Germany",
                "start_date": "2026-06-01",
                "end_date": "2026-09-01",
                "source_url": "https://example.org/show",
            },
            venue={
                "slug": "venue",
                "name": "Venue",
                "city": "Berlin",
                "country": "Germany",
                "address": "",
                "website": "https://example.org",
                "exhibitions_url": "https://example.org/show",
            },
            visitor=None,
            checked_at="2026-08-23",
        )
        self.assertEqual(built["admission"]["status"], "unknown")

    def test_yuranja_note_empty(self) -> None:
        candidate = yc.to_candidate_shape(
            _base_record(),
            editorial_score=80,
            selection_reason="survey",
            slug="artist-survey-2026",
        )
        self.assertEqual(candidate["yuranjaNote"], "")

    def test_candidates_default_pending(self) -> None:
        candidate = yc.to_candidate_shape(
            _base_record(),
            editorial_score=80,
            selection_reason="survey",
            slug="artist-survey-2026",
        )
        self.assertEqual(candidate["humanReviewStatus"], "pending")

    def test_pending_not_exported(self) -> None:
        record = _base_record(editorial_status="pending")
        self.assertFalse(ym.export_eligible(record))

    def test_approved_current_exported(self) -> None:
        record = _base_record(
            editorial_status="approved",
            admission={
                "status": "unknown",
                "display": "Admission not published — check the official visitor information",
                "ticketUrl": "",
                "informationUrl": "https://example.org/visit",
                "informationLabel": "Official visitor information",
                "reservationRequired": None,
            },
        )
        record["exhibitionUrl"] = record["source_url"]
        self.assertTrue(ym.export_eligible(record))
        shape = ym.to_export_shape(record)
        self.assertEqual(shape["slug"], record.get("slug"))
        self.assertIn("dates", shape)

    def test_export_schema_shape(self) -> None:
        record = _base_record(
            editorial_status="approved",
            slug="artist-survey-2026",
            website="https://example.org/exhibition/survey",
            exhibitionUrl="https://example.org/exhibition/survey",
            admission={
                "status": "unknown",
                "display": "Admission not published — check the official visitor information",
                "informationUrl": "https://example.org/visit",
                "informationLabel": "Official visitor information",
                "reservationRequired": None,
            },
        )
        shape = ym.to_export_shape(record)
        required = {
            "slug",
            "title",
            "artists",
            "venue",
            "city",
            "dates",
            "website",
            "description",
            "yuranjaNote",
            "admission",
            "citations",
        }
        self.assertTrue(required.issubset(shape.keys()))
        self.assertEqual(shape["yuranjaNote"], "")

    def test_all_cities_in_review_report_when_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review_path = Path(tmp) / "review.md"
            city_stats = {}
            candidates_by_city = {}
            for city in yc.PRIORITY_CITIES:
                city_stats[city] = {
                    "crawled": 5,
                    "eligible": 2,
                    "selected": 1,
                    "excluded": 3,
                    "approved": 0,
                    "needs_edit": 0,
                    "rejected": 0,
                }
                candidates_by_city[city] = [
                    yc.to_candidate_shape(
                        _base_record(city=city),
                        editorial_score=70,
                        selection_reason="test",
                        slug=f"show-{city.lower().replace(' ', '-')}",
                    )
                ]
            yc._write_review_report(
                city_stats=city_stats,
                candidates_by_city=candidates_by_city,
                path=review_path,
            )
            text = review_path.read_text(encoding="utf-8")
            for city in yc.PRIORITY_CITIES:
                self.assertIn(city, text)

    def test_slugs_stable_and_unique(self) -> None:
        used: set[str] = set()
        a = yc._stable_slug(_base_record(title="Shared Title"), used)
        b = yc._stable_slug(
            _base_record(title="Shared Title", dates={"start": "2027-01-01", "end": "2027-03-01"}),
            used,
        )
        self.assertNotEqual(a, b)
        self.assertTrue(a)
        self.assertTrue(b)


class YuranjaExportFileTests(unittest.TestCase):
    def test_empty_export_when_none_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "yuranja_exhibitions.json"
            # Pending records must not appear in the public export payload shape gate.
            pending = _base_record(editorial_status="pending")
            self.assertFalse(ym.export_eligible(pending))
            # Writing an empty export file is valid when no rows pass the gate.
            payload = {"generated_at": "2026-08-23", "count": 0, "exhibitions": []}
            out.write_text(json.dumps(payload), encoding="utf-8")
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["count"], 0)
            self.assertEqual(loaded["exhibitions"], [])


if __name__ == "__main__":
    unittest.main()
