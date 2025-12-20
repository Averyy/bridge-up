#!/usr/bin/env python3
"""
Bridge Up Configuration Tests

Quick validation of bridge configuration to catch deployment errors.

Run with: python3 test_configuration.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from config import BRIDGE_KEYS, BRIDGE_DETAILS

class TestConfiguration(unittest.TestCase):

    def test_bridge_configuration_completeness(self):
        """Verify all bridges have required configuration"""
        for bridge_key, info in BRIDGE_KEYS.items():
            region = info['region']

            # Check region exists in BRIDGE_DETAILS
            self.assertIn(region, BRIDGE_DETAILS,
                         f"Region '{region}' from BRIDGE_KEYS not found in BRIDGE_DETAILS")

            # Check this region has bridges defined
            self.assertGreater(len(BRIDGE_DETAILS[region]), 0,
                              f"Region '{region}' has no bridges defined")
    
    def test_coordinate_validity(self):
        """Verify all coordinates are valid lat/lng values"""
        for region, bridges in BRIDGE_DETAILS.items():
            for bridge_name, details in bridges.items():
                if 'lat' in details and 'lng' in details:
                    lat = details['lat']
                    lng = details['lng']
                    
                    # Valid latitude: -90 to 90
                    self.assertGreaterEqual(lat, -90, 
                                          f"{bridge_name} has invalid latitude: {lat}")
                    self.assertLessEqual(lat, 90,
                                       f"{bridge_name} has invalid latitude: {lat}")
                    
                    # Valid longitude: -180 to 180
                    self.assertGreaterEqual(lng, -180,
                                          f"{bridge_name} has invalid longitude: {lng}")
                    self.assertLessEqual(lng, 180,
                                       f"{bridge_name} has invalid longitude: {lng}")
    
    def test_region_shortcodes_unique(self):
        """Verify all region shortcodes are unique"""
        shortcodes = set()
        for region, bridges in BRIDGE_DETAILS.items():
            for bridge_name, details in bridges.items():
                if 'region_short' in details:
                    shortcode = details['region_short']
                    self.assertNotIn(shortcode, shortcodes,
                                   f"Duplicate region shortcode: {shortcode}")
                    shortcodes.add(shortcode)
    
    def test_bridge_numbers_present(self):
        """Verify bridges have numbers where expected"""
        # Some bridges should have bridge numbers for construction matching
        expected_numbered_regions = ['SBS', 'MSS']
        
        for region in expected_numbered_regions:
            if region in BRIDGE_DETAILS:
                has_numbers = False
                for bridge_name, details in BRIDGE_DETAILS[region].items():
                    if 'bridge_number' in details:
                        has_numbers = True
                        # Verify it's a valid number format
                        bridge_num = details['bridge_number']
                        self.assertIsInstance(bridge_num, (int, str),
                                            f"Invalid bridge number type for {bridge_name}")
                
                # At least some bridges in these regions should have numbers
                self.assertTrue(has_numbers,
                              f"No bridge numbers found in region {region}")
    
    def test_no_duplicate_bridges_per_region(self):
        """Verify no duplicate bridge names within a region"""
        for region, bridges in BRIDGE_DETAILS.items():
            bridge_names = list(bridges.keys())
            unique_names = set(bridge_names)
            
            self.assertEqual(len(bridge_names), len(unique_names),
                           f"Duplicate bridge names found in region {region}")

if __name__ == '__main__':
    print("Running Bridge Up Configuration Tests...")
    print("Quick validation to catch deployment configuration errors.")
    print("=" * 70)
    
    unittest.main(verbosity=2)