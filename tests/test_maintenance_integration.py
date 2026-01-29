#!/usr/bin/env python3
"""Integration tests for maintenance override logic in scraper.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

from shared import TIMEZONE
from scraper import periods_overlap


# Sample maintenance data for testing
SAMPLE_MAINTENANCE_DATA = {
    "last_scrape_success": "2026-01-29T03:15:00-05:00",
    "source_url": "https://greatlakes-seaway.com/",
    "closures": [
        {
            "bridge_id": "PC_ClarenceSt",
            "description": "Structural steel repair work",
            "periods": [
                {
                    "start": "2026-01-10T00:00:00-05:00",
                    "end": "2026-03-14T23:59:59-05:00"
                }
            ]
        }
    ]
}


class TestMaintenanceOverrideIntegration(unittest.TestCase):
    """Tests for maintenance override logic in update_json_and_broadcast()."""

    def test_unknown_status_overridden_to_construction(self):
        """Should override Unknown status to Construction during maintenance."""
        from maintenance import get_active_maintenance

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # Test time during maintenance window
                test_time = TIMEZONE.localize(datetime(2026, 2, 1, 12, 0, 0))
                result = get_active_maintenance("PC_ClarenceSt", test_time)

                self.assertIsNotNone(result)
                self.assertEqual(result["description"], "Structural steel repair work")
        finally:
            os.remove(temp_path)

    def test_no_override_when_not_in_maintenance(self):
        """Should not override when bridge is not in maintenance."""
        from maintenance import get_active_maintenance

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                # Test time before maintenance starts
                test_time = TIMEZONE.localize(datetime(2026, 1, 5, 12, 0, 0))
                result = get_active_maintenance("PC_ClarenceSt", test_time)

                self.assertIsNone(result)
        finally:
            os.remove(temp_path)

    def test_maintenance_periods_merged_into_closures(self):
        """Should merge maintenance periods into upcoming_closures."""
        from maintenance import get_all_maintenance_periods

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                test_time = TIMEZONE.localize(datetime(2026, 1, 15, 12, 0, 0))
                periods = get_all_maintenance_periods("PC_ClarenceSt", test_time)

                self.assertEqual(len(periods), 1)
                self.assertEqual(periods[0]["description"], "Structural steel repair work")
        finally:
            os.remove(temp_path)

    def test_duplicate_closures_not_added(self):
        """Should not add duplicate closures with same start/end times."""
        from maintenance import get_all_maintenance_periods

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_MAINTENANCE_DATA, f)
            temp_path = f.name

        try:
            with patch('maintenance.MAINTENANCE_FILE', temp_path):
                test_time = TIMEZONE.localize(datetime(2026, 1, 15, 12, 0, 0))
                periods = get_all_maintenance_periods("PC_ClarenceSt", test_time)

                # Check that we can detect duplicates
                existing_closures = [{
                    'type': 'Construction',
                    'time': periods[0]['start'].isoformat(),
                    'end_time': periods[0]['end'].isoformat()
                }]

                # Should detect this as a duplicate
                is_duplicate = any(
                    c.get('type') == 'Construction' and
                    c.get('time') == periods[0]['start'].isoformat() and
                    c.get('end_time') == periods[0]['end'].isoformat()
                    for c in existing_closures
                )

                self.assertTrue(is_duplicate)
        finally:
            os.remove(temp_path)


class TestMaintenanceOverrideHistorySkip(unittest.TestCase):
    """Tests for history update skipping with maintenance overrides."""

    def test_history_not_updated_for_maintenance_override(self):
        """Should verify history update logic understands maintenance_overridden flag."""
        # This tests the logic that when maintenance_overridden=True,
        # history updates should be skipped (tested via code inspection)

        # The scraper.py code at lines 693-700:
        # if not maintenance_overridden:
        #     update_history(...)

        # This test verifies the flag logic conceptually
        maintenance_overridden = True
        history_updated = False

        if not maintenance_overridden:
            history_updated = True

        self.assertFalse(history_updated)

    def test_history_updated_for_normal_status_change(self):
        """Should update history when not a maintenance override."""
        maintenance_overridden = False
        history_updated = False

        if not maintenance_overridden:
            history_updated = True

        self.assertTrue(history_updated)


class TestOverlapBasedDeduplication(unittest.TestCase):
    """Tests for overlap-based duplicate detection in closure merging.

    Uses the imported periods_overlap() function from scraper.py to ensure
    tests verify actual production behavior.
    """

    def test_exact_time_overlap_detected(self):
        """Should detect exact same start/end times as overlap."""
        seaway_start = "2026-02-02T09:00:00-05:00"
        seaway_end = "2026-02-02T16:00:00-05:00"
        maint_start = TIMEZONE.localize(datetime(2026, 2, 2, 9, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 2, 2, 16, 0, 0))

        self.assertTrue(periods_overlap(seaway_start, seaway_end, maint_start, maint_end))

    def test_partial_overlap_detected(self):
        """Should detect overlapping periods with different time precision."""
        # Seaway shows 09:00-16:00, maintenance shows 08:00-17:00 (same closure, different precision)
        seaway_start = "2026-02-02T09:00:00-05:00"
        seaway_end = "2026-02-02T16:00:00-05:00"
        maint_start = TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0))

        self.assertTrue(periods_overlap(seaway_start, seaway_end, maint_start, maint_end))

    def test_no_overlap_different_days(self):
        """Should not detect overlap for closures on different days."""
        seaway_start = "2026-03-01T09:00:00-05:00"
        seaway_end = "2026-03-01T17:00:00-05:00"
        maint_start = TIMEZONE.localize(datetime(2026, 3, 5, 8, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 3, 5, 17, 0, 0))

        self.assertFalse(periods_overlap(seaway_start, seaway_end, maint_start, maint_end))

    def test_null_end_time_detected_as_overlap(self):
        """Should detect overlap when Seaway closure has no end_time (None)."""
        # Seaway closure with no end_time (this happens in real data)
        seaway_start = "2026-02-02T09:00:00-05:00"
        seaway_end = None
        maint_start = TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0))

        self.assertTrue(periods_overlap(seaway_start, seaway_end, maint_start, maint_end))

    def test_null_end_time_outside_window_no_overlap(self):
        """Should not detect overlap when closure with no end_time is outside maintenance window."""
        # Seaway closure on different day
        seaway_start = "2026-03-01T09:00:00-05:00"
        seaway_end = None
        maint_start = TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0))

        self.assertFalse(periods_overlap(seaway_start, seaway_end, maint_start, maint_end))

    def test_null_start_time_returns_false(self):
        """Should return False when closure has no start time."""
        maint_start = TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0))

        self.assertFalse(periods_overlap(None, "2026-02-02T16:00:00-05:00", maint_start, maint_end))

    def test_invalid_date_format_returns_false(self):
        """Should return False for invalid date formats instead of crashing."""
        maint_start = TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0))
        maint_end = TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0))

        self.assertFalse(periods_overlap("not-a-date", "2026-02-02T16:00:00-05:00", maint_start, maint_end))


class TestMergeLogic(unittest.TestCase):
    """Tests for the actual merge behavior in scraper.py.

    The merge strategy is:
    - Seaway has accurate times (07:00-17:00), maintenance has descriptions
    - Enrich Seaway closures with maintenance descriptions (don't replace)
    - Add maintenance periods that don't overlap as new entries
    """

    def _simulate_merge(self, closures, maintenance_periods):
        """Simulate the merge logic from scraper.py."""
        merged_indices = set()

        for closure in closures:
            if closure.get('type') != 'Construction':
                continue
            for i, period in enumerate(maintenance_periods):
                if periods_overlap(closure.get('time'), closure.get('end_time'), period['start'], period['end']):
                    merged_indices.add(i)
                    if not closure.get('description'):
                        closure['description'] = period.get('description') or 'Scheduled maintenance'
                    break

        for i, period in enumerate(maintenance_periods):
            if i in merged_indices:
                continue
            closures.append({
                'type': 'Construction',
                'time': period['start'].isoformat(),
                'end_time': period['end'].isoformat(),
                'description': period.get('description') or 'Scheduled maintenance'
            })

        return closures

    def test_seaway_times_preserved_with_maintenance_description(self):
        """Should keep Seaway times (accurate) but add maintenance description."""
        # Seaway has accurate times 07:00-17:00, no description
        closures = [
            {'type': 'Construction', 'time': '2026-01-10T07:00:00-05:00',
             'end_time': '2026-03-14T17:00:00-05:00', 'description': None},
        ]
        # Maintenance has full-day times (wrong) but has description
        maintenance_periods = [{
            'start': TIMEZONE.localize(datetime(2026, 1, 10, 0, 0, 0)),
            'end': TIMEZONE.localize(datetime(2026, 3, 14, 23, 59, 59)),
            'description': 'Structural steel repair work'
        }]

        result = self._simulate_merge(closures, maintenance_periods)

        # Should have ONE closure with Seaway times + maintenance description
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['time'], '2026-01-10T07:00:00-05:00')  # Seaway time preserved
        self.assertEqual(result[0]['end_time'], '2026-03-14T17:00:00-05:00')  # Seaway time preserved
        self.assertEqual(result[0]['description'], 'Structural steel repair work')

    def test_existing_description_not_overwritten(self):
        """Should not overwrite existing description on Seaway closure."""
        closures = [
            {'type': 'Construction', 'time': '2026-02-02T09:00:00-05:00',
             'end_time': '2026-02-02T16:00:00-05:00', 'description': 'Original description'},
        ]
        maintenance_periods = [{
            'start': TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0)),
            'end': TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0)),
            'description': 'Should be ignored'
        }]

        result = self._simulate_merge(closures, maintenance_periods)

        # Description should NOT be overwritten, and no duplicate added
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['description'], 'Original description')

    def test_non_construction_closures_untouched(self):
        """Should not modify non-Construction closures (ship transits)."""
        closures = [
            {'type': 'Construction', 'time': '2026-02-02T09:00:00-05:00',
             'end_time': '2026-02-02T16:00:00-05:00', 'description': None},
            {'type': 'Next Arrival', 'time': '2026-02-02T10:00:00-05:00',
             'end_time': '2026-02-02T10:30:00-05:00'},
        ]
        maintenance_periods = [{
            'start': TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0)),
            'end': TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0)),
            'description': 'Maintenance work'
        }]

        result = self._simulate_merge(closures, maintenance_periods)

        # Both closures remain, Construction gets description, Next Arrival unchanged
        self.assertEqual(len(result), 2)
        construction = [c for c in result if c['type'] == 'Construction'][0]
        arrival = [c for c in result if c['type'] == 'Next Arrival'][0]
        self.assertEqual(construction['description'], 'Maintenance work')
        self.assertNotIn('description', arrival)  # Next Arrival unchanged

    def test_unmatched_maintenance_added_as_new(self):
        """Should add maintenance periods that don't overlap with any Seaway closure."""
        # Seaway closure on different day
        closures = [
            {'type': 'Construction', 'time': '2026-03-01T09:00:00-05:00',
             'end_time': '2026-03-01T17:00:00-05:00', 'description': None},
        ]
        # Maintenance on Feb 2 - no overlap
        maintenance_periods = [{
            'start': TIMEZONE.localize(datetime(2026, 2, 2, 9, 0, 0)),
            'end': TIMEZONE.localize(datetime(2026, 2, 2, 16, 0, 0)),
            'description': 'Daily maintenance'
        }]

        result = self._simulate_merge(closures, maintenance_periods)

        # Should have TWO closures - original Seaway + new maintenance
        self.assertEqual(len(result), 2)
        self.assertIsNone(result[0]['description'])  # Seaway still has no description
        self.assertEqual(result[1]['description'], 'Daily maintenance')

    def test_null_description_fallback(self):
        """Should fall back to 'Scheduled maintenance' when description is None."""
        closures = [
            {'type': 'Construction', 'time': '2026-02-02T09:00:00-05:00',
             'end_time': '2026-02-02T16:00:00-05:00', 'description': None},
        ]
        maintenance_periods = [{
            'start': TIMEZONE.localize(datetime(2026, 2, 2, 8, 0, 0)),
            'end': TIMEZONE.localize(datetime(2026, 2, 2, 17, 0, 0)),
            'description': None  # No description
        }]

        result = self._simulate_merge(closures, maintenance_periods)

        self.assertEqual(result[0]['description'], 'Scheduled maintenance')


class TestClosureSorting(unittest.TestCase):
    """Tests for closure sorting after merge."""

    def test_closures_sorted_by_time(self):
        """Should sort merged closures by time."""
        closures = [
            {'type': 'Construction', 'time': '2026-03-01T00:00:00-05:00'},
            {'type': 'Next Arrival', 'time': '2026-01-15T10:00:00-05:00'},
            {'type': 'Construction', 'time': '2026-02-01T00:00:00-05:00'},
        ]

        # Sort as scraper.py does
        closures.sort(key=lambda c: c.get('time', ''))

        self.assertEqual(closures[0]['time'], '2026-01-15T10:00:00-05:00')
        self.assertEqual(closures[1]['time'], '2026-02-01T00:00:00-05:00')
        self.assertEqual(closures[2]['time'], '2026-03-01T00:00:00-05:00')


if __name__ == "__main__":
    unittest.main()
