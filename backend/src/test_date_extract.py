"""Unit tests for date extraction patterns."""

from __future__ import annotations

import unittest

import date_extract as de
import html_exhibition_parse as hep


class DateExtractTests(unittest.TestCase):
    def test_en_day_month_range(self) -> None:
        hit = de.extract_date_range("12 March - 23 August 2026 Free")
        self.assertEqual(hit["start_date"], "2026-03-12")
        self.assertEqual(hit["end_date"], "2026-08-23")
        self.assertIn("12 March", hit["date_citation"])

    def test_en_month_day_range(self) -> None:
        hit = de.extract_date_range("June 12 – August 15, 2026")
        self.assertEqual(hit["start_date"], "2026-06-12")
        self.assertEqual(hit["end_date"], "2026-08-15")

    def test_photographers_dmy_range(self) -> None:
        hit = de.extract_date_range("24 Jun 2026 - 27 Sep 2026 Japanese Women")
        self.assertEqual(hit["start_date"], "2026-06-24")
        self.assertEqual(hit["end_date"], "2026-09-27")

    def test_moca_slash_dates(self) -> None:
        hit = de.extract_date_range("2026 05 / 23 Sat. 2026 08 / 30 Sun.")
        self.assertEqual(hit["start_date"], "2026-05-23")
        self.assertEqual(hit["end_date"], "2026-08-30")

    def test_swiss_weekday_range(self) -> None:
        hit = de.extract_date_range("Sat Jun 13—Sun Sep 6 2026")
        self.assertEqual(hit["start_date"], "2026-06-13")
        self.assertEqual(hit["end_date"], "2026-09-06")

    def test_biennale_to_range(self) -> None:
        hit = de.extract_date_range("Saturday 9 May to Sunday 22 November 2026")
        self.assertEqual(hit["start_date"], "2026-05-09")
        self.assertEqual(hit["end_date"], "2026-11-22")

    def test_mam_short_year_pt(self) -> None:
        hit = de.extract_date_range("01 July 26 - 27 set 26")
        self.assertEqual(hit["start_date"], "2026-07-01")
        self.assertEqual(hit["end_date"], "2026-09-27")

    def test_bozar_now_arrow(self) -> None:
        hit = de.extract_date_range("Now → 23 Aug.'26 From 8 €")
        self.assertEqual(hit["end_date"], "2026-08-23")


    def test_mplus_two_dates(self) -> None:
        hit = de.extract_date_range("25 Apr 2026 30 Aug 2026 Dial-A-Poem")
        self.assertEqual(hit["start_date"], "2026-04-25")
        self.assertEqual(hit["end_date"], "2026-08-30")

    def test_jumex_dot_month(self) -> None:
        hit = de.extract_date_range("10.JUN. - 30.AUG.2026 DIFFUSE")
        self.assertEqual(hit["start_date"], "2026-06-10")
        self.assertEqual(hit["end_date"], "2026-08-30")

    def test_masp_short_eu(self) -> None:
        hit = de.extract_date_range("15.5 - 13.9.2026 MORE info")
        self.assertEqual(hit["start_date"], "2026-05-15")
        self.assertEqual(hit["end_date"], "2026-09-13")

    def test_mori_jp_dots(self) -> None:
        hit = de.extract_date_range("2026.10.31 [Sat] - 2027.3.28 [Sun]")
        self.assertEqual(hit["start_date"], "2026-10-31")
        self.assertEqual(hit["end_date"], "2027-03-28")

    def test_eu_short_year_range(self) -> None:
        hit = de.extract_date_range("5.11.25 – 23.2.26")
        self.assertEqual(hit["start_date"], "2025-11-05")
        self.assertEqual(hit["end_date"], "2026-02-23")

    def test_does_not_invent(self) -> None:
        hit = de.extract_date_range("Welcome to the museum shop")
        self.assertEqual(hit["start_date"], "")
        self.assertEqual(hit["end_date"], "")

    def test_html_time_elements(self) -> None:
        html = """
        <article class="exhibition-card">
          <h3>Marc Brandenburg</h3>
          <time datetime="2026-06-01">1.6.26</time>
          <time datetime="2026-09-14">14.9.26</time>
        </article>
        """
        rows = hep.parse_from_html(html, "https://example.org/exhibitions/")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["title"], "Marc Brandenburg")
        self.assertEqual(rows[0]["start_date"], "2026-06-01")
        self.assertEqual(rows[0]["end_date"], "2026-09-14")
        self.assertTrue(rows[0]["date_citation"])

    def test_nav_titles_filtered(self) -> None:
        html = '<a href="/exhibitions/"><h2>Exhibitions</h2></a>'
        rows = hep.parse_from_html(html, "https://example.org/")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
