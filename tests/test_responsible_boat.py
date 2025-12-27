#!/usr/bin/env python3
"""
Responsible Boat Algorithm Tests

Tests the logic for identifying which vessel is likely responsible for a bridge closure.
Covers:
- Scoring algorithms for Closing soon vs Closed status
- Heading/COG calculations
- Region filtering
- Edge cases (no vessels, stationary boats, etc.)

Run with: python3 test_responsible_boat.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import math
from responsible_boat import (
    haversine,
    calculate_bearing,
    angle_difference,
    get_vessel_direction,
    is_heading_toward_bridge,
    score_for_closed,
    score_for_closing_soon,
    find_responsible_vessel,
    get_bridge_region,
    get_bridge_coordinates,
)


class TestHaversine(unittest.TestCase):
    """Test distance calculations."""

    def test_same_point(self):
        """Distance to same point is 0."""
        dist = haversine(43.19, -79.20, 43.19, -79.20)
        self.assertAlmostEqual(dist, 0.0, places=5)

    def test_known_distance(self):
        """Test a known distance (Carlton to Highway 20 bridges)."""
        # Carlton St: 43.19185, -79.20100
        # Highway 20: 43.07650, -79.21046
        dist = haversine(43.19185, -79.20100, 43.07650, -79.21046)
        # Should be roughly 12-13 km
        self.assertGreater(dist, 12.0)
        self.assertLess(dist, 14.0)

    def test_short_distance(self):
        """Short distances (~500m) are accurate."""
        # Move ~500m north (roughly 0.0045 degrees latitude)
        dist = haversine(43.19, -79.20, 43.1945, -79.20)
        self.assertGreater(dist, 0.4)
        self.assertLess(dist, 0.6)


class TestBearing(unittest.TestCase):
    """Test bearing calculations."""

    def test_north(self):
        """Point directly north = bearing 0."""
        bearing = calculate_bearing(43.0, -79.0, 44.0, -79.0)
        self.assertAlmostEqual(bearing, 0.0, delta=1.0)

    def test_east(self):
        """Point directly east = bearing ~90."""
        bearing = calculate_bearing(43.0, -79.0, 43.0, -78.0)
        self.assertGreater(bearing, 85)
        self.assertLess(bearing, 95)

    def test_south(self):
        """Point directly south = bearing 180."""
        bearing = calculate_bearing(44.0, -79.0, 43.0, -79.0)
        self.assertAlmostEqual(bearing, 180.0, delta=1.0)

    def test_west(self):
        """Point directly west = bearing ~270."""
        bearing = calculate_bearing(43.0, -78.0, 43.0, -79.0)
        self.assertGreater(bearing, 265)
        self.assertLess(bearing, 275)


class TestAngleDifference(unittest.TestCase):
    """Test angle difference calculations."""

    def test_same_angle(self):
        """Same angle = 0 difference."""
        self.assertEqual(angle_difference(90, 90), 0)

    def test_opposite(self):
        """Opposite angles = 180 difference."""
        self.assertEqual(angle_difference(0, 180), 180)
        self.assertEqual(angle_difference(90, 270), 180)

    def test_wraparound(self):
        """Handles wraparound correctly (350 vs 10 = 20)."""
        self.assertEqual(angle_difference(350, 10), 20)
        self.assertEqual(angle_difference(10, 350), 20)

    def test_small_difference(self):
        """Small differences work."""
        self.assertEqual(angle_difference(45, 50), 5)


class TestVesselDirection(unittest.TestCase):
    """Test vessel direction extraction."""

    def test_moving_prefers_cog(self):
        """Moving vessel uses COG over heading."""
        vessel = {"course": 90.0, "heading": 180}
        direction = get_vessel_direction(vessel, prefer_cog=True)
        self.assertEqual(direction, 90.0)

    def test_moving_fallback_to_heading(self):
        """Moving vessel falls back to heading if no COG."""
        vessel = {"heading": 180}
        direction = get_vessel_direction(vessel, prefer_cog=True)
        self.assertEqual(direction, 180.0)

    def test_stationary_uses_heading(self):
        """Stationary vessel uses heading only."""
        vessel = {"course": 90.0, "heading": 180}
        direction = get_vessel_direction(vessel, prefer_cog=False)
        self.assertEqual(direction, 180.0)

    def test_no_direction(self):
        """Returns None if no direction data."""
        vessel = {}
        direction = get_vessel_direction(vessel, prefer_cog=True)
        self.assertIsNone(direction)


class TestIsHeadingTowardBridge(unittest.TestCase):
    """Test heading-toward-bridge determination."""

    def test_heading_toward(self):
        """Vessel heading toward bridge returns True."""
        # Vessel south of bridge, heading north
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "course": 0,  # North
            "speed_knots": 5.0
        }
        bridge_coords = (43.19, -79.20)  # North of vessel
        result = is_heading_toward_bridge(vessel, bridge_coords, is_moving=True)
        self.assertTrue(result)

    def test_heading_away(self):
        """Vessel heading away from bridge returns False."""
        # Vessel south of bridge, heading south (away)
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "course": 180,  # South
            "speed_knots": 5.0
        }
        bridge_coords = (43.19, -79.20)  # North of vessel
        result = is_heading_toward_bridge(vessel, bridge_coords, is_moving=True)
        self.assertFalse(result)

    def test_stationary_pointed_at(self):
        """Stationary vessel pointed at bridge returns True."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "heading": 0,  # Pointing north
            "speed_knots": 0.0
        }
        bridge_coords = (43.19, -79.20)  # North of vessel
        result = is_heading_toward_bridge(vessel, bridge_coords, is_moving=False)
        self.assertTrue(result)

    def test_no_direction_data(self):
        """Returns None if no direction available."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "speed_knots": 0.0
        }
        bridge_coords = (43.19, -79.20)
        result = is_heading_toward_bridge(vessel, bridge_coords, is_moving=False)
        self.assertIsNone(result)


class TestScoreForClosed(unittest.TestCase):
    """Test scoring for Closed/Closing status."""

    def test_moving_vessel_scores(self):
        """Moving vessel gets positive score."""
        vessel = {"speed_knots": 5.0}
        score = score_for_closed(vessel, distance_km=0.5)
        self.assertGreater(score, 0)

    def test_stationary_vessel_zero(self):
        """Stationary vessel gets zero score."""
        vessel = {"speed_knots": 0.2}  # Below 0.5 threshold
        score = score_for_closed(vessel, distance_km=0.5)
        self.assertEqual(score, 0.0)

    def test_too_far_zero(self):
        """Vessel beyond 4km gets zero score."""
        vessel = {"speed_knots": 5.0}
        score = score_for_closed(vessel, distance_km=5.0)
        self.assertEqual(score, 0.0)

    def test_closer_is_better(self):
        """Closer vessels score higher."""
        vessel = {"speed_knots": 5.0}
        score_close = score_for_closed(vessel, distance_km=0.5)
        score_far = score_for_closed(vessel, distance_km=2.0)
        self.assertGreater(score_close, score_far)

    def test_score_is_capped(self):
        """Very close vessels have capped score."""
        vessel = {"speed_knots": 5.0}
        score_100m = score_for_closed(vessel, distance_km=0.1)
        score_50m = score_for_closed(vessel, distance_km=0.05)
        # Both should be at or near cap (3.0)
        self.assertLessEqual(score_100m, 3.0)
        self.assertLessEqual(score_50m, 3.0)


class TestScoreForClosingSoon(unittest.TestCase):
    """Test scoring for Closing Soon status."""

    def test_approaching_high_score(self):
        """Vessel approaching bridge gets high score."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "course": 0,  # North (toward bridge)
            "speed_knots": 5.0
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=1.0)
        # Should have 2.0x multiplier
        self.assertGreater(score, 1.5)

    def test_moving_away_fast_zero_score(self):
        """Vessel moving away at 1.5+ knots gets zero score - cannot cause upcoming closure."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "course": 180,  # South (away from bridge)
            "speed_knots": 5.0  # Well above 1.5 knot threshold
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=1.0)
        # Should be exactly 0.0 - impossible to be responsible
        self.assertEqual(score, 0.0)

    def test_moving_away_slow_low_score(self):
        """Vessel moving away slowly (< 1.5 knots) gets low score - might be maneuvering."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "course": 180,  # South (away from bridge)
            "speed_knots": 1.0  # Below 1.5 knot threshold
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=1.0)
        # Should have 0.1x multiplier (low but not zero)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 0.2)

    def test_moving_away_threshold_exactly(self):
        """Vessel at exactly 1.5 knots moving away gets zero score."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "course": 180,  # South (away from bridge)
            "speed_knots": 1.5  # Exactly at threshold
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=1.0)
        # At threshold = zero score
        self.assertEqual(score, 0.0)

    def test_stationary_pointed_at_high_score(self):
        """Stationary vessel pointed at bridge within waiting zone gets high score."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "heading": 0,  # Pointing north
            "speed_knots": 0.0
        }
        bridge_coords = (43.19, -79.20)
        # Must be within STATIONARY_WAITING_ZONE (0.25 km) to get 2.5x multiplier
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=0.15)
        # Should have 2.5x multiplier: base = 1/(0.15+0.1) = 4.0, score = 4.0 * 2.5 = 10.0
        self.assertGreater(score, 5.0)

    def test_stationary_unknown_heading_low_score(self):
        """Stationary vessel with unknown heading gets low score."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "speed_knots": 0.0
            # No heading
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=0.5)
        # Should have 0.1x multiplier
        self.assertLess(score, 0.3)

    def test_stationary_pointed_away_very_low(self):
        """Stationary vessel pointed away gets very low score."""
        vessel = {
            "position": {"lat": 43.18, "lon": -79.20},
            "heading": 180,  # Pointing south (away)
            "speed_knots": 0.0
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=0.5)
        # Should have 0.05x multiplier
        self.assertLess(score, 0.15)

    def test_too_far_zero(self):
        """Vessel beyond 7km gets zero score."""
        vessel = {
            "position": {"lat": 43.0, "lon": -79.20},
            "course": 0,
            "speed_knots": 5.0
        }
        bridge_coords = (43.19, -79.20)
        score = score_for_closing_soon(vessel, bridge_coords, distance_km=8.0)
        self.assertEqual(score, 0.0)


class TestBridgeRegion(unittest.TestCase):
    """Test bridge-to-region mapping."""

    def test_welland_bridges(self):
        """SCT and PC bridges map to welland."""
        self.assertEqual(get_bridge_region("SCT_CarltonSt"), "welland")
        self.assertEqual(get_bridge_region("PC_MainSt"), "welland")

    def test_montreal_bridges(self):
        """MSS, K, SBS bridges map to montreal."""
        self.assertEqual(get_bridge_region("MSS_VictoriaBridgeDownstream"), "montreal")
        self.assertEqual(get_bridge_region("K_CPRailwayBridgeA"), "montreal")
        self.assertEqual(get_bridge_region("SBS_StLouisdeGonzagueBridge"), "montreal")


class TestFindResponsibleVessel(unittest.TestCase):
    """Integration tests for find_responsible_vessel."""

    def setUp(self):
        """Set up test fixtures."""
        # Carlton St bridge coordinates
        self.bridge_id = "SCT_CarltonSt"
        self.bridge_coords = (43.19185980424842, -79.20100809118367)

    def test_no_vessels_returns_none(self):
        """Empty vessel list returns None."""
        result = find_responsible_vessel(self.bridge_id, "Closed", [])
        self.assertIsNone(result)

    def test_open_status_returns_none(self):
        """Open bridge status returns None."""
        vessels = [{
            "mmsi": 316001635,
            "position": {"lat": 43.19, "lon": -79.20},
            "speed_knots": 5.0,
            "region": "welland"
        }]
        result = find_responsible_vessel(self.bridge_id, "Open", vessels)
        self.assertIsNone(result)

    def test_construction_returns_none(self):
        """Construction status returns None."""
        vessels = [{
            "mmsi": 316001635,
            "position": {"lat": 43.19, "lon": -79.20},
            "speed_knots": 5.0,
            "region": "welland"
        }]
        result = find_responsible_vessel(self.bridge_id, "Construction", vessels)
        self.assertIsNone(result)

    def test_wrong_region_filtered(self):
        """Vessels in wrong region are filtered out."""
        vessels = [{
            "mmsi": 316001635,
            "position": {"lat": 45.5, "lon": -73.5},
            "speed_knots": 5.0,
            "region": "montreal"  # Wrong region for Welland bridge
        }]
        result = find_responsible_vessel(self.bridge_id, "Closed", vessels)
        self.assertIsNone(result)

    def test_selects_closest_moving_for_closed(self):
        """For Closed status, selects closest moving vessel."""
        vessels = [
            {
                "mmsi": 111,
                "position": {"lat": 43.190, "lon": -79.201},  # Closer
                "speed_knots": 5.0,
                "region": "welland"
            },
            {
                "mmsi": 222,
                "position": {"lat": 43.185, "lon": -79.201},  # Farther
                "speed_knots": 5.0,
                "region": "welland"
            }
        ]
        result = find_responsible_vessel(self.bridge_id, "Closed", vessels)
        self.assertEqual(result, 111)

    def test_approaching_beats_closer_away(self):
        """For Closing soon, approaching vessel beats closer but moving away."""
        vessels = [
            {
                "mmsi": 111,
                "position": {"lat": 43.188, "lon": -79.201},  # 400m south
                "course": 180,  # Moving south (away)
                "speed_knots": 5.0,
                "region": "welland"
            },
            {
                "mmsi": 222,
                "position": {"lat": 43.170, "lon": -79.201},  # ~2.4km south
                "course": 0,  # Moving north (toward)
                "speed_knots": 5.0,
                "region": "welland"
            }
        ]
        result = find_responsible_vessel(self.bridge_id, "Closing soon", vessels)
        # Vessel 222 should win despite being farther (approaching)
        self.assertEqual(result, 222)

    def test_stationary_waiting_detected(self):
        """Stationary vessel pointed at bridge is detected for Closing soon."""
        vessels = [
            {
                "mmsi": 111,
                "position": {"lat": 43.1915, "lon": -79.201},  # 40m away
                "heading": 0,  # Pointed north
                "speed_knots": 0.1,  # Stationary
                "region": "welland"
            }
        ]
        result = find_responsible_vessel(self.bridge_id, "Closing soon", vessels)
        self.assertEqual(result, 111)

    def test_threshold_rejects_weak_candidates(self):
        """Vessels below score threshold are rejected."""
        vessels = [
            {
                "mmsi": 111,
                "position": {"lat": 43.0, "lon": -79.20},  # ~21km away (outside 5km)
                "heading": 180,  # Pointed away
                "speed_knots": 0.0,  # Stationary
                "region": "welland"
            }
        ]
        result = find_responsible_vessel(self.bridge_id, "Closing soon", vessels)
        self.assertIsNone(result)


class TestRealWorldScenarios(unittest.TestCase):
    """Test real-world scenarios that could occur."""

    def test_just_passed_through(self):
        """Vessel that just passed through (moving away) is detected for Closed."""
        # For Closed status, we just need closest moving vessel
        bridge_id = "SCT_CarltonSt"
        vessels = [
            {
                "mmsi": 111,
                "position": {"lat": 43.1925, "lon": -79.201},  # Just north of bridge
                "course": 0,  # Moving north (away from bridge, just passed)
                "speed_knots": 5.0,
                "region": "welland"
            }
        ]
        result = find_responsible_vessel(bridge_id, "Closed", vessels)
        # Should still be selected (closest moving for Closed)
        self.assertEqual(result, 111)

    def test_docked_boat_rejected(self):
        """Docked boat at marina near bridge is rejected."""
        bridge_id = "PC_MainSt"  # Port Colborne - has marinas
        # Bridge is at 42.90150, -79.24543
        # Vessel is slightly north, pointing north (away from bridge)
        vessels = [
            {
                "mmsi": 111,
                "position": {"lat": 42.903, "lon": -79.245},  # ~150m north of bridge
                "heading": 0,  # Pointing north (away from bridge to the south)
                "speed_knots": 0.0,
                "region": "welland"
            }
        ]
        result = find_responsible_vessel(bridge_id, "Closing soon", vessels)
        # Should be rejected due to low score (pointing away from bridge)
        self.assertIsNone(result)


if __name__ == '__main__':
    print("Running Responsible Boat Algorithm Tests...")
    print("=" * 70)

    unittest.main(verbosity=2)
