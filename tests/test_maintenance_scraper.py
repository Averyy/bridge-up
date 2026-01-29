#!/usr/bin/env python3
"""Tests for maintenance page scraper."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch
from datetime import datetime

from maintenance_scraper import (
    parse_date,
    convert_12h_to_24h,
    extract_closures_from_html,
    fix_date_typo,
    FULL_CLOSURE_PATTERN,
    DAILY_RANGE_PATTERN,
    DAILY_SINGLE_PATTERN,
    DAILY_AND_PATTERN
)
from shared import TIMEZONE


# Sample HTML fragments for testing
SAMPLE_HTML = """
<div class="sp-ea-one sp-easy-accordion">
  <div class="ea-card">
    <h1 class="ea-header">
      <a>Clarence Street Bridge</a>
    </h1>
    <div class="ea-body">
      <p><strong>Location:</strong> Port Colborne, Ontario</p>
      <p><strong>Closure Dates</strong></p>
      <p>Full closure: January 10, 2026 to March 14, 2026</p>
      <p>Daily closure: (9 am - 4 pm) March 17, 2026 to March 19, 2026</p>
      <p><strong>Project Type:</strong> Bridge closure for structural steel repair work</p>
    </div>
  </div>
</div>
"""

SAMPLE_DAILY_SINGLE = """
<div class="ea-card">
  <h1 class="ea-header"><a>Glendale Avenue Bridge</a></h1>
  <div class="ea-body">
    <p><strong>Location:</strong> St. Catharines, Ontario</p>
    <p>Daily closure (8 am - 5 pm) February 2, 2026</p>
  </div>
</div>
"""

SAMPLE_PEDESTRIAN_BRIDGE = """
<h1 class="ea-header"><a>Welland Canals Trail Pedestrian Bridge</a></h1>
<div class="ea-body"><p>Full closure: January 12, 2026 to February 6, 2026</p></div>
"""


class TestDateParsing(unittest.TestCase):
    """Tests for date parsing."""

    def test_parse_date_full_format(self):
        """Should parse 'Month Day, Year' format."""
        result = parse_date("January 10, 2026")
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 10)
        self.assertIsNotNone(result.tzinfo)

    def test_parse_date_different_months(self):
        """Should handle different month names."""
        result = parse_date("March 14, 2026")
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 14)


class TestTimeConversion(unittest.TestCase):
    """Tests for 12-hour to 24-hour time conversion."""

    def test_convert_am_hours(self):
        """Should convert AM hours correctly."""
        self.assertEqual(convert_12h_to_24h("9", "am"), 9)
        self.assertEqual(convert_12h_to_24h("1", "am"), 1)
        self.assertEqual(convert_12h_to_24h("11", "am"), 11)

    def test_convert_pm_hours(self):
        """Should convert PM hours correctly."""
        self.assertEqual(convert_12h_to_24h("1", "pm"), 13)
        self.assertEqual(convert_12h_to_24h("4", "pm"), 16)
        self.assertEqual(convert_12h_to_24h("11", "pm"), 23)

    def test_convert_noon_and_midnight(self):
        """Should handle noon and midnight edge cases."""
        self.assertEqual(convert_12h_to_24h("12", "am"), 0)   # midnight
        self.assertEqual(convert_12h_to_24h("12", "pm"), 12)  # noon

    def test_invalid_hour_raises_error(self):
        """Should raise ValueError for invalid hour values."""
        with self.assertRaises(ValueError):
            convert_12h_to_24h("0", "am")
        with self.assertRaises(ValueError):
            convert_12h_to_24h("13", "pm")
        with self.assertRaises(ValueError):
            convert_12h_to_24h("24", "am")

    def test_invalid_ampm_raises_error(self):
        """Should raise ValueError for invalid am/pm values."""
        with self.assertRaises(ValueError):
            convert_12h_to_24h("9", "noon")
        with self.assertRaises(ValueError):
            convert_12h_to_24h("9", "AM ")  # trailing space


class TestFixDateTypo(unittest.TestCase):
    """Tests for fix_date_typo() function."""

    def test_fix_past_year_typo(self):
        """Should fix dates more than 180 days in the past."""
        # Simulate current time as Jan 29, 2026
        now = TIMEZONE.localize(datetime(2026, 1, 29, 12, 0, 0))

        # March 5, 2025 is about 330 days in the past - should be fixed
        result = fix_date_typo("March 5, 2025", now)
        self.assertEqual(result, "March 05, 2026")

    def test_no_fix_for_future_dates(self):
        """Should not change dates in the future."""
        now = TIMEZONE.localize(datetime(2026, 1, 29, 12, 0, 0))

        # March 5, 2026 is in the future - should not change
        result = fix_date_typo("March 5, 2026", now)
        self.assertEqual(result, "March 5, 2026")

    def test_no_fix_for_recent_past(self):
        """Should not change dates only slightly in the past."""
        now = TIMEZONE.localize(datetime(2026, 1, 29, 12, 0, 0))

        # Jan 10, 2026 is only 19 days ago - should not change
        result = fix_date_typo("January 10, 2026", now)
        self.assertEqual(result, "January 10, 2026")


class TestRegexPatterns(unittest.TestCase):
    """Tests for regex date extraction patterns."""

    def test_full_closure_pattern(self):
        """Should match full closure date ranges."""
        text = "Full closure: January 10, 2026 to March 14, 2026"
        match = FULL_CLOSURE_PATTERN.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "January 10, 2026")
        self.assertEqual(match.group(2), "March 14, 2026")

    def test_closure_dates_pattern(self):
        """Should match 'Closure Dates:' format (alternate to 'Full closure:')."""
        text = "Closure Dates: January 10, 2026 to January 30, 2026"
        match = FULL_CLOSURE_PATTERN.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "January 10, 2026")
        self.assertEqual(match.group(2), "January 30, 2026")

    def test_daily_range_pattern(self):
        """Should match daily closure ranges."""
        text = "Daily closure: (9 am - 4 pm) March 17, 2026 to March 19, 2026"
        match = DAILY_RANGE_PATTERN.search(text)
        self.assertIsNotNone(match)
        groups = match.groups()
        self.assertEqual(groups[0], "9")  # start hour
        self.assertIsNone(groups[1])  # start minute (optional)
        self.assertEqual(groups[2].lower(), "am")  # start am/pm

    def test_daily_range_with_minutes(self):
        """Should match daily closures with minutes."""
        text = "Daily closure: (9:30 am - 4:45 pm) March 17, 2026 to March 19, 2026"
        match = DAILY_RANGE_PATTERN.search(text)
        self.assertIsNotNone(match)
        groups = match.groups()
        self.assertEqual(groups[0], "9")
        self.assertEqual(groups[1], "30")

    def test_daily_single_pattern(self):
        """Should match single day closures."""
        text = "Daily closure (8 am - 5 pm) February 2, 2026"
        match = DAILY_SINGLE_PATTERN.search(text)
        self.assertIsNotNone(match)
        groups = match.groups()
        self.assertEqual(groups[0], "8")
        self.assertEqual(groups[3], "5")

    def test_daily_and_pattern(self):
        """Should match daily closures with 'and'."""
        text = "Daily closure (9 am - 4 pm) February 24, 2026 and February 25, 2026"
        match = DAILY_AND_PATTERN.search(text)
        self.assertIsNotNone(match)
        groups = match.groups()
        self.assertEqual(groups[6], "February 24, 2026")
        self.assertEqual(groups[7], "February 25, 2026")


class TestHTMLExtraction(unittest.TestCase):
    """Tests for HTML parsing and data extraction."""

    @patch('maintenance_scraper.datetime')
    def test_extract_full_closure(self, mock_datetime_module):
        """Should extract full closure period."""
        # Mock only datetime.now() while keeping other datetime functions
        mock_datetime_module.now.return_value = TIMEZONE.localize(datetime(2026, 1, 5, 0, 0, 0))
        mock_datetime_module.combine = datetime.combine
        mock_datetime_module.strptime = datetime.strptime

        closures = extract_closures_from_html(SAMPLE_HTML)
        self.assertEqual(len(closures), 1)

        closure = closures[0]
        self.assertEqual(closure['bridge_id'], "PC_ClarenceSt")

        # Should have 2 periods (full + daily)
        self.assertEqual(len(closure['periods']), 2)

        # Check full closure
        full = closure['periods'][0]
        self.assertIn('start', full)
        self.assertIn('end', full)
        self.assertIn('2026-01-10', full['start'])
        self.assertIn('2026-03-14', full['end'])

    @patch('maintenance_scraper.datetime')
    def test_extract_daily_single(self, mock_datetime_module):
        """Should extract single day closure."""
        mock_datetime_module.now.return_value = TIMEZONE.localize(datetime(2026, 1, 5, 0, 0, 0))
        mock_datetime_module.combine = datetime.combine
        mock_datetime_module.strptime = datetime.strptime

        closures = extract_closures_from_html(SAMPLE_DAILY_SINGLE)
        self.assertEqual(len(closures), 1)

        period = closures[0]['periods'][0]
        self.assertEqual(period['type'], 'daily')
        self.assertEqual(period['start_date'], '2026-02-02')
        self.assertEqual(period['end_date'], '2026-02-02')
        self.assertEqual(period['daily_start_time'], '08:00')
        self.assertEqual(period['daily_end_time'], '17:00')

    @patch('maintenance_scraper.datetime')
    def test_skip_pedestrian_bridges(self, mock_datetime_module):
        """Should ignore pedestrian bridges."""
        mock_datetime_module.now.return_value = TIMEZONE.localize(datetime(2026, 1, 5, 0, 0, 0))
        mock_datetime_module.combine = datetime.combine
        mock_datetime_module.strptime = datetime.strptime

        closures = extract_closures_from_html(SAMPLE_PEDESTRIAN_BRIDGE)
        self.assertEqual(len(closures), 0)

    @patch('maintenance_scraper.datetime')
    def test_extract_work_description(self, mock_datetime_module):
        """Should extract work description from Project Type."""
        mock_datetime_module.now.return_value = TIMEZONE.localize(datetime(2026, 1, 5, 0, 0, 0))
        mock_datetime_module.combine = datetime.combine
        mock_datetime_module.strptime = datetime.strptime

        closures = extract_closures_from_html(SAMPLE_HTML)
        self.assertEqual(len(closures), 1)
        # Should strip "Bridge closure for " prefix
        self.assertEqual(closures[0]['description'], "Structural steel repair work")

    @patch('maintenance_scraper.datetime')
    def test_filters_past_closures(self, mock_datetime_module):
        """Should not include closures that have ended."""
        # Mock datetime to be after all closures
        mock_datetime_module.now.return_value = TIMEZONE.localize(datetime(2026, 5, 1, 0, 0, 0))
        mock_datetime_module.combine = datetime.combine
        mock_datetime_module.strptime = datetime.strptime

        closures = extract_closures_from_html(SAMPLE_HTML)
        # Should have no closures with periods because all are in the past
        self.assertTrue(len(closures) == 0 or all(len(c['periods']) == 0 for c in closures))


if __name__ == "__main__":
    unittest.main()
