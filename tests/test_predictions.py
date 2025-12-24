# tests/test_predictions.py
"""
Tests for prediction logic (moved from iOS to backend).

Tests the calculate_prediction() function that predicts when bridges will
open/close based on status, elapsed time, and historical statistics.
"""
import unittest
from datetime import datetime, timedelta
import pytz
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predictions import (
    calculate_prediction,
    get_expected_duration,
    add_expected_duration_to_closures,
    parse_datetime
)

TIMEZONE = pytz.timezone('America/Toronto')


class TestPredictions(unittest.TestCase):
    """Test prediction calculation logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.current_time = datetime(2025, 12, 24, 12, 0, 0, tzinfo=TIMEZONE)
        self.default_stats = {
            'closure_ci': {'lower': 8, 'upper': 16},
            'raising_soon_ci': {'lower': 3, 'upper': 8}
        }

    # === CLOSED STATUS TESTS ===

    def test_closed_pure_stats_fresh(self):
        """Closed bridge with no closure info uses pure stats."""
        last_updated = self.current_time  # Just closed
        result = calculate_prediction(
            status='Closed',
            last_updated=last_updated,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )

        # Should return prediction based on CI (8-16 min from now)
        self.assertIsNotNone(result)
        lower = parse_datetime(result['lower'])
        upper = parse_datetime(result['upper'])

        # Lower should be 8 min from now, upper 16 min
        self.assertAlmostEqual((lower - self.current_time).total_seconds(), 8 * 60, delta=60)
        self.assertAlmostEqual((upper - self.current_time).total_seconds(), 16 * 60, delta=60)

    def test_closed_5min_elapsed_pure_stats(self):
        """Closed bridge with 5 min elapsed shows reduced prediction."""
        last_updated = self.current_time - timedelta(minutes=5)
        result = calculate_prediction(
            status='Closed',
            last_updated=last_updated,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )

        self.assertIsNotNone(result)
        lower = parse_datetime(result['lower'])
        upper = parse_datetime(result['upper'])

        # Lower: 8-5=3 min, Upper: 16-5=11 min from now
        self.assertAlmostEqual((lower - self.current_time).total_seconds(), 3 * 60, delta=60)
        self.assertAlmostEqual((upper - self.current_time).total_seconds(), 11 * 60, delta=60)

    def test_closed_longer_than_usual(self):
        """Closed bridge past upper CI returns None (longer than usual)."""
        last_updated = self.current_time - timedelta(minutes=20)  # Past 16 min upper
        result = calculate_prediction(
            status='Closed',
            last_updated=last_updated,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )

        # Should return None when both lower and upper are <= 0
        self.assertIsNone(result)

    def test_closed_with_active_boat_blended(self):
        """Closed with active boat closure uses blended prediction."""
        last_updated = self.current_time - timedelta(minutes=5)
        closures = [{
            'type': 'Commercial Vessel',
            'time': (self.current_time - timedelta(minutes=5)).isoformat(),  # Started
            'longer': False,
            'expected_duration_minutes': 15
        }]

        result = calculate_prediction(
            status='Closed',
            last_updated=last_updated,
            statistics=self.default_stats,
            upcoming_closures=closures,
            current_time=self.current_time
        )

        self.assertIsNotNone(result)
        # Blended: (15 + 8) / 2 - 5 = 6.5 min lower
        # Blended: (15 + 16) / 2 - 5 = 10.5 min upper
        lower = parse_datetime(result['lower'])
        self.assertAlmostEqual((lower - self.current_time).total_seconds(), 6.5 * 60, delta=60)

    def test_closed_boat_not_started_uses_pure_stats(self):
        """Future boat closure doesn't affect prediction (pure stats)."""
        last_updated = self.current_time
        closures = [{
            'type': 'Commercial Vessel',
            'time': (self.current_time + timedelta(minutes=10)).isoformat(),  # Future
            'longer': False
        }]

        result = calculate_prediction(
            status='Closed',
            last_updated=last_updated,
            statistics=self.default_stats,
            upcoming_closures=closures,
            current_time=self.current_time
        )

        # Should use pure stats, not blended
        self.assertIsNotNone(result)
        lower = parse_datetime(result['lower'])
        self.assertAlmostEqual((lower - self.current_time).total_seconds(), 8 * 60, delta=60)

    # === CONSTRUCTION STATUS TESTS ===

    def test_construction_with_end_time(self):
        """Construction with known end_time returns exact time."""
        end_time = self.current_time + timedelta(hours=2)
        closures = [{
            'type': 'Construction',
            'time': (self.current_time - timedelta(hours=1)).isoformat(),  # Started
            'end_time': end_time.isoformat()
        }]

        result = calculate_prediction(
            status='Construction',
            last_updated=self.current_time - timedelta(hours=1),
            statistics=self.default_stats,
            upcoming_closures=closures,
            current_time=self.current_time
        )

        self.assertIsNotNone(result)
        lower = parse_datetime(result['lower'])
        upper = parse_datetime(result['upper'])
        # Both should be the exact end time
        self.assertEqual(lower, end_time)
        self.assertEqual(upper, end_time)

    def test_construction_without_end_time(self):
        """Construction without end_time returns None (unknown)."""
        closures = [{
            'type': 'Construction',
            'time': (self.current_time - timedelta(hours=1)).isoformat()
            # No end_time
        }]

        result = calculate_prediction(
            status='Construction',
            last_updated=self.current_time - timedelta(hours=1),
            statistics=self.default_stats,
            upcoming_closures=closures,
            current_time=self.current_time
        )

        self.assertIsNone(result)

    # === CLOSING SOON STATUS TESTS ===

    def test_closing_soon_pure_stats(self):
        """Closing soon with no closure info uses pure stats."""
        last_updated = self.current_time
        result = calculate_prediction(
            status='Closing soon',
            last_updated=last_updated,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )

        self.assertIsNotNone(result)
        lower = parse_datetime(result['lower'])
        upper = parse_datetime(result['upper'])

        # Should use raising_soon_ci (3-8 min)
        self.assertAlmostEqual((lower - self.current_time).total_seconds(), 3 * 60, delta=60)
        self.assertAlmostEqual((upper - self.current_time).total_seconds(), 8 * 60, delta=60)

    def test_closing_soon_with_upcoming_closure_within_hour(self):
        """Closing soon with known closure time < 1 hour returns None (iOS uses closure.time)."""
        closures = [{
            'type': 'Commercial Vessel',
            'time': (self.current_time + timedelta(minutes=10)).isoformat()
        }]

        result = calculate_prediction(
            status='Closing soon',
            last_updated=self.current_time,
            statistics=self.default_stats,
            upcoming_closures=closures,
            current_time=self.current_time
        )

        # Returns None so iOS uses the closure time directly
        self.assertIsNone(result)

    def test_closing_soon_closure_time_passed(self):
        """Closing soon with passed closure time returns None (boat is late)."""
        closures = [{
            'type': 'Commercial Vessel',
            'time': (self.current_time - timedelta(minutes=5)).isoformat()  # Passed
        }]

        result = calculate_prediction(
            status='Closing soon',
            last_updated=self.current_time - timedelta(minutes=10),
            statistics=self.default_stats,
            upcoming_closures=closures,
            current_time=self.current_time
        )

        # Returns None (iOS shows "was expected at X")
        self.assertIsNone(result)

    # === OTHER STATUS TESTS ===

    def test_open_status_no_prediction(self):
        """Open bridge returns None (no prediction needed)."""
        result = calculate_prediction(
            status='Open',
            last_updated=self.current_time,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )
        self.assertIsNone(result)

    def test_opening_status_no_prediction(self):
        """Opening bridge returns None."""
        result = calculate_prediction(
            status='Opening',
            last_updated=self.current_time,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )
        self.assertIsNone(result)

    def test_unknown_status_no_prediction(self):
        """Unknown status returns None."""
        result = calculate_prediction(
            status='Unknown',
            last_updated=self.current_time,
            statistics=self.default_stats,
            upcoming_closures=[],
            current_time=self.current_time
        )
        self.assertIsNone(result)


class TestExpectedDurations(unittest.TestCase):
    """Test expected duration lookup."""

    def test_commercial_vessel_normal(self):
        """Commercial vessel normal duration is 15 min."""
        self.assertEqual(get_expected_duration('Commercial Vessel', False), 15)

    def test_commercial_vessel_longer(self):
        """Commercial vessel longer duration is 30 min."""
        self.assertEqual(get_expected_duration('Commercial Vessel', True), 30)

    def test_pleasure_craft_normal(self):
        """Pleasure craft normal duration is 10 min."""
        self.assertEqual(get_expected_duration('Pleasure Craft', False), 10)

    def test_pleasure_craft_longer(self):
        """Pleasure craft longer duration is 20 min."""
        self.assertEqual(get_expected_duration('Pleasure Craft', True), 20)

    def test_next_arrival(self):
        """Next arrival treated as commercial (15 min)."""
        self.assertEqual(get_expected_duration('Next Arrival', False), 15)

    def test_unknown_type(self):
        """Unknown vessel type returns None."""
        self.assertIsNone(get_expected_duration('Unknown Type', False))

    def test_case_insensitive(self):
        """Lookup is case insensitive."""
        self.assertEqual(get_expected_duration('commercial vessel', False), 15)
        self.assertEqual(get_expected_duration('COMMERCIAL VESSEL', False), 15)


class TestAddExpectedDurations(unittest.TestCase):
    """Test adding expected durations to closures."""

    def test_adds_duration_to_commercial(self):
        """Adds expected_duration_minutes to commercial vessel closure."""
        closures = [{'type': 'Commercial Vessel', 'longer': False}]
        result = add_expected_duration_to_closures(closures)
        self.assertEqual(result[0]['expected_duration_minutes'], 15)

    def test_preserves_existing_duration(self):
        """Does not overwrite existing expected_duration_minutes."""
        closures = [{'type': 'Commercial Vessel', 'longer': False, 'expected_duration_minutes': 20}]
        result = add_expected_duration_to_closures(closures)
        self.assertEqual(result[0]['expected_duration_minutes'], 20)

    def test_handles_unknown_type(self):
        """Unknown type does not add duration."""
        closures = [{'type': 'Unknown', 'longer': False}]
        result = add_expected_duration_to_closures(closures)
        self.assertNotIn('expected_duration_minutes', result[0])


class TestParseDatetime(unittest.TestCase):
    """Test datetime parsing helper."""

    def test_parse_datetime_object(self):
        """Parses datetime object."""
        dt = datetime(2025, 12, 24, 12, 0, 0, tzinfo=TIMEZONE)
        result = parse_datetime(dt)
        self.assertEqual(result, dt)

    def test_parse_iso_string(self):
        """Parses ISO format string."""
        result = parse_datetime('2025-12-24T12:00:00-05:00')
        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 12)

    def test_parse_iso_with_z(self):
        """Parses ISO format with Z suffix."""
        result = parse_datetime('2025-12-24T17:00:00Z')
        self.assertIsNotNone(result)
        # Z is UTC, should convert to Eastern (12:00 EST)
        self.assertEqual(result.hour, 12)

    def test_parse_invalid(self):
        """Invalid string returns None."""
        result = parse_datetime('not a date')
        self.assertIsNone(result)

    def test_parse_none(self):
        """None returns None."""
        result = parse_datetime(None)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
