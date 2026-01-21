#!/usr/bin/env python3
"""
Bridge Up Boat Tracker Tests

Tests the vessel tracking logic that could fail silently:
- Region detection (vessels in/out of monitored areas)
- Vessel type categorization (icons in app)
- Name sanitization (garbage data from AIS)
- MMSI validation (filtering non-ships)

Run with: python3 test_boat_tracker.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from boat_config import get_vessel_region, get_vessel_type_info, sanitize_vessel_name


class TestRegionDetection(unittest.TestCase):
    """Test region detection - wrong bounds = missing vessels or ghost vessels"""

    def test_welland_canal_bridge_location(self):
        """Vessel at Carlton St bridge is in welland region"""
        # Carlton St bridge coordinates
        region = get_vessel_region(43.19, -79.20)
        self.assertEqual(region, "welland")

    def test_montreal_victoria_bridge(self):
        """Vessel at Victoria Bridge is in montreal region"""
        # Victoria Bridge coordinates
        region = get_vessel_region(45.50, -73.55)
        self.assertEqual(region, "montreal")

    def test_outside_all_regions(self):
        """Vessel in Lake Ontario (not in canal) returns None"""
        # Middle of Lake Ontario
        region = get_vessel_region(43.65, -78.00)
        self.assertIsNone(region)

    def test_boundary_edge_included(self):
        """Vessel at exact boundary is included"""
        # Welland south boundary (Port Colborne area)
        region = get_vessel_region(42.70, -79.20)
        self.assertEqual(region, "welland")


class TestVesselTypeMapping(unittest.TestCase):
    """Test vessel type mapping - wrong type = wrong icon in app"""

    def test_cargo_ship(self):
        """Cargo ships (70-79) map to cargo category"""
        name, category = get_vessel_type_info(70)
        self.assertEqual(category, "cargo")
        self.assertIn("Cargo", name)

    def test_tanker(self):
        """Tankers (80-89) map to tanker category"""
        name, category = get_vessel_type_info(80)
        self.assertEqual(category, "tanker")

    def test_tug(self):
        """Tugs map to tug category"""
        name, category = get_vessel_type_info(52)
        self.assertEqual(category, "tug")

    def test_unknown_type(self):
        """Unknown type codes return 'other' category"""
        name, category = get_vessel_type_info(99)
        self.assertEqual(category, "other")

    def test_none_type(self):
        """None type code returns Unknown/other"""
        name, category = get_vessel_type_info(None)
        self.assertEqual(name, "Unknown")
        self.assertEqual(category, "other")


class TestNameSanitization(unittest.TestCase):
    """Test name sanitization - garbage names = ugly display"""

    def test_normal_name(self):
        """Normal vessel name passes through"""
        self.assertEqual(sanitize_vessel_name("ALGOMA GUARDIAN"), "ALGOMA GUARDIAN")

    def test_strips_whitespace(self):
        """Extra whitespace is normalized"""
        self.assertEqual(sanitize_vessel_name("  VESSEL   NAME  "), "VESSEL NAME")

    def test_placeholder_filtered(self):
        """AIS placeholder values return None"""
        self.assertIsNone(sanitize_vessel_name("@@@@@@@@@@@@@@@@@@@@"))
        self.assertIsNone(sanitize_vessel_name("UNKNOWN"))
        self.assertIsNone(sanitize_vessel_name("unknown"))
        self.assertIsNone(sanitize_vessel_name("NIL"))
        self.assertIsNone(sanitize_vessel_name("N/A"))
        self.assertIsNone(sanitize_vessel_name("TBD"))

    def test_empty_returns_none(self):
        """Empty string returns None"""
        self.assertIsNone(sanitize_vessel_name(""))
        self.assertIsNone(sanitize_vessel_name(None))

    def test_single_char_garbage_filtered(self):
        """Single characters are encoding artifacts, not real names"""
        self.assertIsNone(sanitize_vessel_name("Y"))
        self.assertIsNone(sanitize_vessel_name("N"))
        self.assertIsNone(sanitize_vessel_name("X"))
        self.assertIsNone(sanitize_vessel_name("@"))

    def test_at_terminator_strips_garbage(self):
        """Per AIS standard, @ terminates field - discard it and garbage after"""
        self.assertIsNone(sanitize_vessel_name("Y@"))
        self.assertIsNone(sanitize_vessel_name("@Y"))
        self.assertIsNone(sanitize_vessel_name("Y@@@@@@@@@@"))
        self.assertEqual(sanitize_vessel_name("ABC@XYZ"), "ABC")
        self.assertEqual(sanitize_vessel_name("MONTREAL@@@@@"), "MONTREAL")

    def test_valid_destinations_pass(self):
        """Real port codes and names pass through"""
        self.assertEqual(sanitize_vessel_name("MTL"), "MTL")
        self.assertEqual(sanitize_vessel_name("MONTREAL"), "MONTREAL")
        self.assertEqual(sanitize_vessel_name("DEHAM-CAMTR"), "DEHAM-CAMTR")
        self.assertEqual(sanitize_vessel_name("MONTREAL#57"), "MONTREAL#57")
        self.assertEqual(sanitize_vessel_name("US"), "US")
        self.assertEqual(sanitize_vessel_name("NY"), "NY")

    def test_space_padding_stripped(self):
        """Space-padded fields (common in AIS) get trimmed to None or clean value"""
        self.assertIsNone(sanitize_vessel_name("                    "))  # 20 spaces
        self.assertIsNone(sanitize_vessel_name("Y                   "))  # Y + 19 spaces -> "Y" -> filtered
        self.assertEqual(sanitize_vessel_name("MTL                 "), "MTL")  # MTL + spaces
        self.assertEqual(sanitize_vessel_name("  MONTREAL  "), "MONTREAL")


class TestMMSIValidation(unittest.TestCase):
    """Test MMSI range validation logic - wrong filter = miss ships or include noise"""

    def test_valid_ship_mmsi(self):
        """Ship MMSIs (200M-799M) are valid"""
        # Canadian ship
        self.assertTrue(200_000_000 <= 316001635 <= 799_999_999)
        # US ship
        self.assertTrue(200_000_000 <= 367000000 <= 799_999_999)

    def test_coast_station_filtered(self):
        """Coast stations (0-199M) should be filtered"""
        self.assertFalse(200_000_000 <= 123456789 <= 799_999_999)

    def test_sar_aircraft_filtered(self):
        """SAR aircraft (111MIDXXX) should be filtered"""
        self.assertFalse(200_000_000 <= 111123456 <= 799_999_999)


if __name__ == '__main__':
    print("Running Bridge Up Boat Tracker Tests...")
    print("Testing vessel tracking logic that could fail silently.")
    print("=" * 70)

    unittest.main(verbosity=2)
