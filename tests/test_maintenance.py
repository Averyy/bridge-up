#!/usr/bin/env python3
"""Tests for maintenance override system runtime functions."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

from maintenance import (
    load_maintenance_data,
    get_active_maintenance,
    get_all_maintenance_periods,
    expand_daily_periods,
    get_maintenance_info,
    validate_maintenance_file,
    _maintenance_cache,
    _maintenance_cache_lock
)
from shared import TIMEZONE


def clear_maintenance_cache():
    """Clear the maintenance cache to prevent test pollution."""
    with _maintenance_cache_lock:
        _maintenance_cache["mtime"] = None
        _maintenance_cache["data"] = None


# Sample maintenance data for testing
SAMPLE_MAINTENANCE_DATA = {
    "last_scrape_success": "2026-01-29T03:15:00-05:00",
    "source_url": "https://greatlakes-seaway.com/en/for-our-communities/infrastructure-maintenance/",
    "closures": [
        {
            "bridge_id": "PC_ClarenceSt",
            "description": "Structural steel repair work",
            "periods": [
                {
                    "start": "2026-01-10T00:00:00-05:00",
                    "end": "2026-03-14T23:59:59-05:00"
                },
                {
                    "type": "daily",
                    "start_date": "2026-03-17",
                    "end_date": "2026-03-19",
                    "daily_start_time": "09:00",
                    "daily_end_time": "16:00"
                }
            ]
        },
        {
            "bridge_id": "SCT_CarltonSt",
            "description": "Structural repairs",
            "periods": [
                {
                    "type": "daily",
                    "start_date": "2026-02-02",
                    "end_date": "2026-02-02",
                    "daily_start_time": "08:00",
                    "daily_end_time": "17:00"
                }
            ]
        }
    ]
}


class TestLoadMaintenanceData(unittest.TestCase):
    """Tests for load_maintenance_data() function."""

    def setUp(self):
        """Clear cache before each test."""
        clear_maintenance_cache()

    def test_load_valid_file(self):
        """Should load valid JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                data = load_maintenance_data()
                self.assertIn("closures", data)
                self.assertEqual(len(data["closures"]), 2)
        finally:
            os.remove(temp_path)

    def test_load_nonexistent_file(self):
        """Should return empty closures for nonexistent file."""
        with patch('maintenance.MAINTENANCE_FILE', '/nonexistent/path/maintenance.json'):
            data = load_maintenance_data()
            self.assertEqual(data, {"closures": []})

    def test_load_invalid_json(self):
        """Should return empty closures and clear cache for malformed JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json content")
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                data = load_maintenance_data()
                self.assertEqual(data, {"closures": []})

                # Verify cache was cleared
                with _maintenance_cache_lock:
                    self.assertIsNone(_maintenance_cache["mtime"])
                    self.assertIsNone(_maintenance_cache["data"])
        finally:
            os.remove(temp_path)

    def test_cache_invalidation_on_file_delete(self):
        """Should clear cache and return empty when file is deleted after being loaded."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # First load - should populate cache
                data = load_maintenance_data()
                self.assertEqual(len(data["closures"]), 2)

                # Verify cache is populated
                with _maintenance_cache_lock:
                    self.assertIsNotNone(_maintenance_cache["mtime"])
                    self.assertIsNotNone(_maintenance_cache["data"])

                # Delete the file
                os.remove(temp_path)

                # Second load - should detect file gone and return empty
                data = load_maintenance_data()
                self.assertEqual(data, {"closures": []})

                # Verify cache was cleared
                with _maintenance_cache_lock:
                    self.assertIsNone(_maintenance_cache["mtime"])
                    self.assertIsNone(_maintenance_cache["data"])
        except FileNotFoundError:
            pass  # File already removed in test


class TestExpandDailyPeriods(unittest.TestCase):
    """Tests for expand_daily_periods() function."""

    def test_expand_single_day(self):
        """Should expand single day closure."""
        period = {
            "type": "daily",
            "start_date": "2026-02-02",
            "end_date": "2026-02-02",
            "daily_start_time": "08:00",
            "daily_end_time": "17:00"
        }

        expanded = expand_daily_periods(period, TIMEZONE)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["start"].hour, 8)
        self.assertEqual(expanded[0]["end"].hour, 17)

    def test_expand_multi_day(self):
        """Should expand multi-day closure range."""
        period = {
            "type": "daily",
            "start_date": "2026-03-17",
            "end_date": "2026-03-19",
            "daily_start_time": "09:00",
            "daily_end_time": "16:00"
        }

        expanded = expand_daily_periods(period, TIMEZONE)
        self.assertEqual(len(expanded), 3)  # 17th, 18th, 19th

        # Check times are consistent
        for exp in expanded:
            self.assertEqual(exp["start"].hour, 9)
            self.assertEqual(exp["end"].hour, 16)

    def test_expand_overnight_closure(self):
        """Should handle overnight closures spanning midnight (e.g., 21:00 to 02:00)."""
        period = {
            "type": "daily",
            "start_date": "2026-01-15",
            "end_date": "2026-01-15",
            "daily_start_time": "21:00",
            "daily_end_time": "02:00"
        }

        expanded = expand_daily_periods(period, TIMEZONE)
        self.assertEqual(len(expanded), 1)

        # Verify start is before end (end should be next day)
        self.assertLess(expanded[0]["start"], expanded[0]["end"])

        # Start should be 21:00 on Jan 15
        self.assertEqual(expanded[0]["start"].hour, 21)
        self.assertEqual(expanded[0]["start"].day, 15)

        # End should be 02:00 on Jan 16
        self.assertEqual(expanded[0]["end"].hour, 2)
        self.assertEqual(expanded[0]["end"].day, 16)

    def test_expand_multiday_overnight_at_range_boundary(self):
        """Should handle multi-day overnight closure where last period extends past end_date.

        Per the code comment: "On the last day of the range, this intentionally extends to end_date+1.
        For example, a closure ending March 19 at 02:00 actually ends March 20 at 02:00."
        """
        period = {
            "type": "daily",
            "start_date": "2026-01-15",
            "end_date": "2026-01-17",
            "daily_start_time": "21:00",
            "daily_end_time": "02:00"
        }

        expanded = expand_daily_periods(period, TIMEZONE)
        self.assertEqual(len(expanded), 3)  # 15th, 16th, 17th

        # First period: Jan 15 21:00 -> Jan 16 02:00
        self.assertEqual(expanded[0]["start"].day, 15)
        self.assertEqual(expanded[0]["start"].hour, 21)
        self.assertEqual(expanded[0]["end"].day, 16)
        self.assertEqual(expanded[0]["end"].hour, 2)

        # Second period: Jan 16 21:00 -> Jan 17 02:00
        self.assertEqual(expanded[1]["start"].day, 16)
        self.assertEqual(expanded[1]["end"].day, 17)

        # Third/last period: Jan 17 21:00 -> Jan 18 02:00 (extends past end_date!)
        self.assertEqual(expanded[2]["start"].day, 17)
        self.assertEqual(expanded[2]["start"].hour, 21)
        self.assertEqual(expanded[2]["end"].day, 18)  # Extends to next day
        self.assertEqual(expanded[2]["end"].hour, 2)


class TestGetActiveMaintenance(unittest.TestCase):
    """Tests for get_active_maintenance() function."""

    def setUp(self):
        """Clear cache before each test."""
        clear_maintenance_cache()

    def test_active_full_closure(self):
        """Should detect active full closure."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # Test time during full closure period (Jan 10 - Mar 14)
                test_time = TIMEZONE.localize(datetime(2026, 2, 1, 12, 0, 0))
                result = get_active_maintenance("PC_ClarenceSt", test_time)

                self.assertIsNotNone(result)
                self.assertEqual(result["description"], "Structural steel repair work")
                self.assertTrue(result["start"] <= test_time <= result["end"])
        finally:
            os.remove(temp_path)

    def test_inactive_outside_window(self):
        """Should return None outside maintenance window."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # Test time outside all closures (Jan 1)
                test_time = TIMEZONE.localize(datetime(2026, 1, 1, 12, 0, 0))
                result = get_active_maintenance("PC_ClarenceSt", test_time)

                self.assertIsNone(result)
        finally:
            os.remove(temp_path)

    def test_unknown_bridge(self):
        """Should return None for unknown bridge."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                test_time = TIMEZONE.localize(datetime(2026, 2, 1, 12, 0, 0))
                result = get_active_maintenance("UNKNOWN_BRIDGE", test_time)

                self.assertIsNone(result)
        finally:
            os.remove(temp_path)

    def test_active_daily_closure(self):
        """Should detect active daily closure when time is within daily window."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # SCT_CarltonSt has daily closure 08:00-17:00 on Feb 2, 2026
                # Test at 10:00 AM - should be active
                test_time = TIMEZONE.localize(datetime(2026, 2, 2, 10, 0, 0))
                result = get_active_maintenance("SCT_CarltonSt", test_time)

                self.assertIsNotNone(result)
                self.assertEqual(result["description"], "Structural repairs")
                self.assertEqual(result["start"].hour, 8)
                self.assertEqual(result["end"].hour, 17)
        finally:
            os.remove(temp_path)

    def test_inactive_daily_closure_before_window(self):
        """Should return None when time is before daily closure window."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # SCT_CarltonSt has daily closure 08:00-17:00 on Feb 2, 2026
                # Test at 7:00 AM - should NOT be active
                test_time = TIMEZONE.localize(datetime(2026, 2, 2, 7, 0, 0))
                result = get_active_maintenance("SCT_CarltonSt", test_time)

                self.assertIsNone(result)
        finally:
            os.remove(temp_path)

    def test_inactive_daily_closure_after_window(self):
        """Should return None when time is after daily closure window."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # SCT_CarltonSt has daily closure 08:00-17:00 on Feb 2, 2026
                # Test at 6:00 PM - should NOT be active
                test_time = TIMEZONE.localize(datetime(2026, 2, 2, 18, 0, 0))
                result = get_active_maintenance("SCT_CarltonSt", test_time)

                self.assertIsNone(result)
        finally:
            os.remove(temp_path)


class TestGetMaintenanceInfo(unittest.TestCase):
    """Tests for get_maintenance_info() function."""

    def setUp(self):
        """Clear cache before each test."""
        clear_maintenance_cache()

    def test_info_with_valid_file(self):
        """Should return maintenance system status."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                info = get_maintenance_info()

                self.assertTrue(info["file_exists"])
                self.assertEqual(info["closure_count"], 2)
                self.assertIn("source_url", info)
                self.assertIn("last_scrape_success", info)
        finally:
            os.remove(temp_path)

    def test_info_with_nonexistent_file(self):
        """Should handle nonexistent file gracefully."""
        with patch('maintenance.MAINTENANCE_FILE', '/nonexistent/path/maintenance.json'):
            info = get_maintenance_info()

            self.assertFalse(info["file_exists"])
            self.assertEqual(info["closure_count"], 0)


class TestValidateMaintenanceFile(unittest.TestCase):
    """Tests for validate_maintenance_file() function."""

    def setUp(self):
        """Clear cache before each test."""
        clear_maintenance_cache()

    def test_validate_valid_file(self):
        """Should validate correct file structure."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                errors = validate_maintenance_file()
                self.assertEqual(len(errors), 0)
        finally:
            os.remove(temp_path)

    def test_validate_missing_file(self):
        """Should report missing file."""
        with patch('maintenance.MAINTENANCE_FILE', '/nonexistent/path/maintenance.json'):
            errors = validate_maintenance_file()
            self.assertGreater(len(errors), 0)
            self.assertIn("not found", errors[0].lower())


if __name__ == "__main__":
    unittest.main()
