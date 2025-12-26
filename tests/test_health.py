#!/usr/bin/env python3
"""
Bridge Up Health Endpoint Tests

Tests the health status calculation logic that powers monitoring.
This is business logic that could fail silently (wrong status returned).

Run with: python3 test_health.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime, timedelta
import pytz

TIMEZONE = pytz.timezone('America/Toronto')


def calculate_health_status(last_scrape_time, last_updated_time, now=None):
    """
    Calculate health status based on scraper and data freshness.
    Mirrors the logic in main.py's health() endpoint.
    """
    if now is None:
        now = datetime.now(TIMEZONE)

    status = "ok"
    status_message = "All systems operational"

    # Check scraper health (runs every 20-30s, so 5 min = definitely stuck)
    if last_scrape_time:
        scrape_age = now - last_scrape_time
        if scrape_age > timedelta(minutes=5):
            status = "error"
            minutes_ago = int(scrape_age.total_seconds() / 60)
            status_message = f"Scraper has not run in {minutes_ago} minutes, may be stuck or crashed"

    # Check data freshness (24h without any bridge change is unusual)
    if last_updated_time and status == "ok":
        data_age = now - last_updated_time
        if data_age > timedelta(hours=24):
            status = "warning"
            hours_ago = int(data_age.total_seconds() / 3600)
            status_message = f"No bridge status changes in {hours_ago} hours, unusual inactivity"

    return status, status_message


class TestHealthStatusLogic(unittest.TestCase):
    """Test health status calculation - could fail silently with wrong monitoring alerts"""

    def setUp(self):
        self.now = datetime.now(TIMEZONE)

    def test_healthy_returns_ok(self):
        """Recent scrape and data returns ok status"""
        status, msg = calculate_health_status(self.now, self.now, self.now)
        self.assertEqual(status, "ok")

    def test_stale_scraper_returns_error(self):
        """Scraper not running for 6 minutes returns error"""
        stale = self.now - timedelta(minutes=6)
        status, msg = calculate_health_status(stale, self.now, self.now)
        self.assertEqual(status, "error")
        self.assertIn("6 minutes", msg)

    def test_stale_data_returns_warning(self):
        """No data changes for 25 hours returns warning"""
        stale = self.now - timedelta(hours=25)
        status, msg = calculate_health_status(self.now, stale, self.now)
        self.assertEqual(status, "warning")
        self.assertIn("25 hours", msg)

    def test_error_takes_precedence(self):
        """Error takes precedence over warning when both conditions met"""
        stale_scrape = self.now - timedelta(minutes=10)
        stale_data = self.now - timedelta(hours=30)
        status, msg = calculate_health_status(stale_scrape, stale_data, self.now)
        self.assertEqual(status, "error")

    def test_missing_timestamps_returns_ok(self):
        """Missing timestamps (startup case) returns ok gracefully"""
        status, _ = calculate_health_status(None, None, self.now)
        self.assertEqual(status, "ok")


if __name__ == '__main__':
    print("Running Bridge Up Health Status Tests...")
    print("Testing monitoring logic that could fail silently.")
    print("=" * 70)

    unittest.main(verbosity=2)
