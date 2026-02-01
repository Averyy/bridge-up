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


def is_winter_season(dt: datetime) -> bool:
    """
    Check if date is in winter season (Dec 1 - Mar 15).
    Mirrors the logic in main.py.
    """
    month, day = dt.month, dt.day
    return month == 12 or month in (1, 2) or (month == 3 and day <= 15)


def calculate_health_status(last_scrape_time, last_updated_time, now=None, consecutive_failures=0):
    """
    Calculate health status based on seaway API and bridge activity.
    Mirrors the logic in main.py's health() endpoint.

    Returns:
        tuple: (status, status_message, seaway_status, seaway_message, bridge_activity, bridge_activity_message)
    """
    if now is None:
        now = datetime.now(TIMEZONE)

    inactivity_threshold = timedelta(hours=168) if is_winter_season(now) else timedelta(hours=24)

    # Seaway status (can we reach the seaway API?)
    seaway_status = "ok"
    seaway_message = "Seaway API responding normally"

    if consecutive_failures >= 3:
        seaway_status = "error"
        seaway_message = f"{consecutive_failures} consecutive failures (all regions)"
    elif last_scrape_time:
        scrape_age = now - last_scrape_time
        if scrape_age > timedelta(minutes=5):
            seaway_status = "error"
            minutes_ago = int(scrape_age.total_seconds() / 60)
            seaway_message = f"No successful fetch in {minutes_ago} minutes"

    # Bridge activity (are bridges changing?)
    bridge_activity = "ok"
    bridge_activity_message = "Data up to date"

    if last_updated_time:
        data_age = now - last_updated_time
        hours_ago = int(data_age.total_seconds() / 3600)
        threshold_hours = int(inactivity_threshold.total_seconds() / 3600)

        if data_age > inactivity_threshold:
            bridge_activity = "warning"
            bridge_activity_message = f"No changes in {hours_ago} hours (threshold: {threshold_hours}h)"
        elif hours_ago >= 1:
            bridge_activity_message = f"Last change {hours_ago} hours ago"

    # Combined status
    if seaway_status == "error":
        status = "error"
        status_message = f"Seaway error: {seaway_message}"
    elif bridge_activity == "warning":
        status = "warning"
        status_message = f"Data stale: {bridge_activity_message}"
    else:
        status = "ok"
        status_message = "All systems operational"

    return (status, status_message, seaway_status, seaway_message,
            bridge_activity, bridge_activity_message)


class TestSeasonDetection(unittest.TestCase):
    """Test winter season detection logic"""

    def test_december_is_winter(self):
        """December 1 onwards is winter"""
        dec_1 = datetime(2025, 12, 1, tzinfo=TIMEZONE)
        dec_31 = datetime(2025, 12, 31, tzinfo=TIMEZONE)
        self.assertTrue(is_winter_season(dec_1))
        self.assertTrue(is_winter_season(dec_31))

    def test_january_february_is_winter(self):
        """January and February are winter"""
        jan = datetime(2026, 1, 15, tzinfo=TIMEZONE)
        feb = datetime(2026, 2, 15, tzinfo=TIMEZONE)
        self.assertTrue(is_winter_season(jan))
        self.assertTrue(is_winter_season(feb))

    def test_early_march_is_winter(self):
        """March 1-15 is winter"""
        mar_1 = datetime(2026, 3, 1, tzinfo=TIMEZONE)
        mar_15 = datetime(2026, 3, 15, tzinfo=TIMEZONE)
        self.assertTrue(is_winter_season(mar_1))
        self.assertTrue(is_winter_season(mar_15))

    def test_late_march_is_not_winter(self):
        """March 16 onwards is not winter"""
        mar_16 = datetime(2026, 3, 16, tzinfo=TIMEZONE)
        mar_31 = datetime(2026, 3, 31, tzinfo=TIMEZONE)
        self.assertFalse(is_winter_season(mar_16))
        self.assertFalse(is_winter_season(mar_31))

    def test_summer_is_not_winter(self):
        """April through November are not winter"""
        for month in [4, 5, 6, 7, 8, 9, 10, 11]:
            dt = datetime(2026, month, 15, tzinfo=TIMEZONE)
            self.assertFalse(is_winter_season(dt), f"Month {month} should not be winter")


class TestHealthStatusLogic(unittest.TestCase):
    """Test health status calculation - could fail silently with wrong monitoring alerts"""

    def setUp(self):
        # Use a summer date for standard tests
        self.summer_now = datetime(2026, 7, 15, 12, 0, tzinfo=TIMEZONE)
        # Use a winter date for seasonal tests
        self.winter_now = datetime(2026, 1, 15, 12, 0, tzinfo=TIMEZONE)

    def test_healthy_returns_ok(self):
        """Recent scrape and data returns ok status"""
        result = calculate_health_status(self.summer_now, self.summer_now, self.summer_now)
        status, _, seaway_status, _, bridge_activity, _ = result
        self.assertEqual(status, "ok")
        self.assertEqual(seaway_status, "ok")
        self.assertEqual(bridge_activity, "ok")

    def test_stale_seaway_returns_error(self):
        """Seaway API not responding for 6 minutes returns error"""
        stale = self.summer_now - timedelta(minutes=6)
        result = calculate_health_status(stale, self.summer_now, self.summer_now)
        status, _, seaway_status, seaway_msg, _, _ = result
        self.assertEqual(status, "error")
        self.assertEqual(seaway_status, "error")
        self.assertIn("6 minutes", seaway_msg)

    def test_consecutive_failures_returns_error(self):
        """3+ consecutive scrape failures returns error"""
        result = calculate_health_status(
            self.summer_now, self.summer_now, self.summer_now, consecutive_failures=3
        )
        status, _, seaway_status, seaway_msg, _, _ = result
        self.assertEqual(status, "error")
        self.assertEqual(seaway_status, "error")
        self.assertIn("3 consecutive failures", seaway_msg)

    def test_stale_summer_returns_warning(self):
        """No bridge changes for 25 hours in summer returns warning"""
        stale = self.summer_now - timedelta(hours=25)
        result = calculate_health_status(self.summer_now, stale, self.summer_now)
        status, _, _, _, bridge_activity, activity_msg = result
        self.assertEqual(status, "warning")
        self.assertEqual(bridge_activity, "warning")
        self.assertIn("25 hours", activity_msg)
        self.assertIn("threshold: 24h", activity_msg)

    def test_recent_winter_100h_returns_ok(self):
        """No bridge changes for 100 hours in winter returns ok (within 168h threshold)"""
        stale = self.winter_now - timedelta(hours=100)
        result = calculate_health_status(self.winter_now, stale, self.winter_now)
        status, _, _, _, bridge_activity, _ = result
        self.assertEqual(status, "ok")
        self.assertEqual(bridge_activity, "ok")

    def test_stale_winter_200h_returns_warning(self):
        """No bridge changes for 200 hours in winter returns warning (beyond 168h threshold)"""
        stale = self.winter_now - timedelta(hours=200)
        result = calculate_health_status(self.winter_now, stale, self.winter_now)
        status, _, _, _, bridge_activity, activity_msg = result
        self.assertEqual(status, "warning")
        self.assertEqual(bridge_activity, "warning")
        self.assertIn("200 hours", activity_msg)
        self.assertIn("threshold: 168h", activity_msg)

    def test_error_takes_precedence(self):
        """Error takes precedence over warning when both conditions met"""
        stale_scrape = self.summer_now - timedelta(minutes=10)
        stale_data = self.summer_now - timedelta(hours=30)
        result = calculate_health_status(stale_scrape, stale_data, self.summer_now)
        status, _, seaway_status, _, bridge_activity, _ = result
        self.assertEqual(status, "error")
        self.assertEqual(seaway_status, "error")
        self.assertEqual(bridge_activity, "warning")

    def test_missing_timestamps_returns_ok(self):
        """Missing timestamps (startup case) returns ok gracefully"""
        result = calculate_health_status(None, None, self.summer_now)
        status, _, seaway_status, _, bridge_activity, _ = result
        self.assertEqual(status, "ok")
        self.assertEqual(seaway_status, "ok")
        self.assertEqual(bridge_activity, "ok")

    def test_winter_threshold_boundary(self):
        """Test exact boundary of 168h threshold in winter"""
        # Just under 168h - should be ok
        just_under = self.winter_now - timedelta(hours=167)
        result = calculate_health_status(self.winter_now, just_under, self.winter_now)
        _, _, _, _, bridge_activity, _ = result
        self.assertEqual(bridge_activity, "ok")

        # Just over 168h - should be warning
        just_over = self.winter_now - timedelta(hours=169)
        result = calculate_health_status(self.winter_now, just_over, self.winter_now)
        _, _, _, _, bridge_activity, _ = result
        self.assertEqual(bridge_activity, "warning")

    def test_summer_threshold_boundary(self):
        """Test exact boundary of 24h threshold in summer"""
        # Just under 24h - should be ok
        just_under = self.summer_now - timedelta(hours=23)
        result = calculate_health_status(self.summer_now, just_under, self.summer_now)
        _, _, _, _, bridge_activity, _ = result
        self.assertEqual(bridge_activity, "ok")

        # Just over 24h - should be warning
        just_over = self.summer_now - timedelta(hours=25)
        result = calculate_health_status(self.summer_now, just_over, self.summer_now)
        _, _, _, _, bridge_activity, _ = result
        self.assertEqual(bridge_activity, "warning")


if __name__ == '__main__':
    print("Running Bridge Up Health Status Tests...")
    print("Testing monitoring logic with seasonal thresholds.")
    print("=" * 70)

    unittest.main(verbosity=2)
