#!/usr/bin/env python3
"""
Bridge Up Parser Tests - Core Business Logic Only

Tests the critical parsing functions that could fail silently if API format changes.
These tests have ZERO impact on production - they're purely for development confidence.

Run with: python3 test_parsers.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime
import pytz
from scraper import parse_old_json, parse_new_json, interpret_bridge_status, parse_date

TIMEZONE = pytz.timezone('America/Toronto')


class TestParseOldJson(unittest.TestCase):
    """Tests for parse_old_json() - old API format"""

    def test_basic_bridge_parsing(self):
        """Test parsing basic bridge data with status"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Queenston St.', 'status': 'Available', 'vessel1ETA': '----'},
                {'address': 'Glendale Ave.', 'status': 'Unavailable', 'vessel1ETA': '----'}
            ],
            'bridgeClosureList': []
        }

        result = parse_old_json(json_data)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'Queenston St.')
        self.assertEqual(result[0]['raw_status'], 'Available')
        self.assertEqual(result[1]['name'], 'Glendale Ave.')
        self.assertEqual(result[1]['raw_status'], 'Unavailable')

    def test_vessel_eta_parsing(self):
        """Test parsing vessel ETA as upcoming closure"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Carlton St.', 'status': 'Available (raising soon)', 'vessel1ETA': '14:30'}
            ],
            'bridgeClosureList': []
        }

        result = parse_old_json(json_data)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'Carlton St.')
        self.assertEqual(result[0]['raw_status'], 'Available (raising soon)')
        self.assertEqual(len(result[0]['upcoming_closures']), 1)
        self.assertEqual(result[0]['upcoming_closures'][0]['type'], 'Next Arrival')

    def test_vessel_eta_with_asterisk(self):
        """Test parsing vessel ETA with asterisk (longer closure)"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Highway 20', 'status': 'Available', 'vessel1ETA': '16:45*'}
            ],
            'bridgeClosureList': []
        }

        result = parse_old_json(json_data)

        self.assertEqual(len(result[0]['upcoming_closures']), 1)
        self.assertTrue(result[0]['upcoming_closures'][0]['longer'])

    def test_empty_bridge_list(self):
        """Test parsing empty response"""
        json_data = {'bridgeModelList': [], 'bridgeClosureList': []}

        result = parse_old_json(json_data)

        self.assertEqual(len(result), 0)

    def test_missing_fields_handled_gracefully(self):
        """Test that missing fields don't cause crashes"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Test Bridge'}  # Missing status and vessel1ETA
            ],
            'bridgeClosureList': []
        }

        result = parse_old_json(json_data)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'Test Bridge')
        self.assertEqual(result[0]['raw_status'], 'Unknown')

    def test_construction_closure_parsing(self):
        """Test parsing planned closures from closureP field"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Main St.', 'status': 'Available', 'vessel1ETA': '----'}
            ],
            'bridgeClosureList': [
                {
                    'bridgeAddress': 'Main St.',
                    'closureP': 'DEC 22, 2026 - DEC 22, 2026, 09:00 - 12:00',
                    'continuousHour': 'N',
                    'reason': 'Bridge / road maintenance'
                }
            ]
        }

        result = parse_old_json(json_data)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['upcoming_closures']), 1)
        closure = result[0]['upcoming_closures'][0]
        self.assertEqual(closure['type'], 'Construction')
        self.assertEqual(closure['time'].year, 2026)
        self.assertEqual(closure['time'].month, 12)
        self.assertEqual(closure['time'].day, 22)
        self.assertEqual(closure['time'].hour, 9)
        self.assertEqual(closure['end_time'].hour, 12)

    def test_multiday_noncontinuous_closure(self):
        """Test that non-continuous multi-day closures create separate daily entries"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Carlton St.', 'status': 'Available', 'vessel1ETA': '----'}
            ],
            'bridgeClosureList': [
                {
                    'bridgeAddress': 'Carlton St.',
                    'closureP': 'DEC 22, 2026 - DEC 24, 2026, 08:00 - 17:00',
                    'continuousHour': 'N',
                    'reason': 'Bridge / road maintenance'
                }
            ]
        }

        result = parse_old_json(json_data)

        # Should create 3 separate closures (Dec 22, 23, 24)
        self.assertEqual(len(result[0]['upcoming_closures']), 3)

        closures = result[0]['upcoming_closures']
        # Each closure should be 8am-5pm on its respective day
        for i, day in enumerate([22, 23, 24]):
            self.assertEqual(closures[i]['time'].day, day)
            self.assertEqual(closures[i]['time'].hour, 8)
            self.assertEqual(closures[i]['end_time'].day, day)
            self.assertEqual(closures[i]['end_time'].hour, 17)

    def test_continuous_closure(self):
        """Test that continuous closures create single entry spanning full period"""
        json_data = {
            'bridgeModelList': [
                {'address': 'Test Bridge', 'status': 'Available', 'vessel1ETA': '----'}
            ],
            'bridgeClosureList': [
                {
                    'bridgeAddress': 'Test Bridge',
                    'closureP': 'DEC 22, 2026 - DEC 24, 2026, 08:00 - 17:00',
                    'continuousHour': 'Y',
                    'reason': 'Emergency repair'
                }
            ]
        }

        result = parse_old_json(json_data)

        # Should create 1 continuous closure
        self.assertEqual(len(result[0]['upcoming_closures']), 1)

        closure = result[0]['upcoming_closures'][0]
        # Single entry from Dec 22 8am to Dec 24 5pm
        self.assertEqual(closure['time'].day, 22)
        self.assertEqual(closure['time'].hour, 8)
        self.assertEqual(closure['end_time'].day, 24)
        self.assertEqual(closure['end_time'].hour, 17)


class TestParseNewJson(unittest.TestCase):
    """Tests for parse_new_json() - new API format"""

    def test_basic_bridge_parsing(self):
        """Test parsing basic bridge data with status3"""
        json_data = {
            'bridgeStatusList': [
                {'address': 'Larocque Bridge', 'status3': 'Available', 'bridgeLiftList': [], 'bridgeMaintenanceList': []},
                {'address': 'St-Louis Bridge', 'status3': 'Unavailable', 'bridgeLiftList': [], 'bridgeMaintenanceList': []}
            ]
        }

        result = parse_new_json(json_data)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'Larocque Bridge')
        self.assertEqual(result[0]['raw_status'], 'Available')
        self.assertEqual(result[1]['raw_status'], 'Unavailable')

    def test_fallback_to_status_field(self):
        """Test falling back to status field when status3 is missing"""
        json_data = {
            'bridgeStatusList': [
                {'address': 'Test Bridge', 'status': 'Available (raising soon)', 'bridgeLiftList': [], 'bridgeMaintenanceList': []}
            ]
        }

        result = parse_new_json(json_data)

        self.assertEqual(result[0]['raw_status'], 'Available (raising soon)')

    def test_empty_bridge_list(self):
        """Test parsing empty response"""
        json_data = {'bridgeStatusList': []}

        result = parse_new_json(json_data)

        self.assertEqual(len(result), 0)

    def test_bridge_lift_list_parsing(self):
        """Test parsing vessel arrivals from bridgeLiftList"""
        json_data = {
            'bridgeStatusList': [
                {
                    'address': 'Test Bridge',
                    'status3': 'Available',
                    'bridgeLiftList': [
                        {'id': 123, 'type': 'a', 'eta': '2026-12-20T14:30:00'}
                    ],
                    'bridgeMaintenanceList': []
                }
            ]
        }

        result = parse_new_json(json_data)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['upcoming_closures']), 1)
        closure = result[0]['upcoming_closures'][0]
        self.assertEqual(closure['type'], 'Next Arrival')
        self.assertEqual(closure['time'].hour, 14)
        self.assertEqual(closure['time'].minute, 30)


class TestInterpretBridgeStatus(unittest.TestCase):
    """Tests for status interpretation logic"""

    def test_available_maps_to_open(self):
        """Test that 'Available' status maps to 'Open'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'Available', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Open')
        self.assertTrue(result['available'])

    def test_unavailable_maps_to_closed(self):
        """Test that 'Unavailable' status maps to 'Closed'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'Unavailable', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Closed')
        self.assertFalse(result['available'])

    def test_raising_soon_maps_to_closing_soon(self):
        """Test that 'Available (raising soon)' maps to 'Closing soon'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'Available (raising soon)', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Closing soon')
        self.assertTrue(result['available'])

    def test_lowering_maps_to_opening(self):
        """Test that 'Unavailable (lowering)' maps to 'Opening'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'Unavailable (lowering)', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Opening')
        self.assertFalse(result['available'])

    def test_work_in_progress_maps_to_construction(self):
        """Test that 'Unavailable (work in progress)' maps to 'Construction'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'Unavailable (work in progress)', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Construction')
        self.assertFalse(result['available'])

    def test_unknown_status_maps_to_unknown(self):
        """Test that garbage data maps to 'Unknown'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'xyzabc123garbage', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Unknown')

    def test_data_unavailable_maps_to_unknown(self):
        """Test that 'Data unavailable' maps to 'Unknown'"""
        bridge = {'name': 'Test Bridge', 'raw_status': 'Data unavailable', 'upcoming_closures': []}

        result = interpret_bridge_status(bridge)

        self.assertEqual(result['status'], 'Unknown')


class TestParseDate(unittest.TestCase):
    """Tests for parse_date() function"""

    def test_time_only_format(self):
        """Test parsing time-only string like '18:15'"""
        result, longer = parse_date('18:15')

        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 18)
        self.assertEqual(result.minute, 15)
        self.assertFalse(longer)

    def test_time_with_asterisk(self):
        """Test parsing time with asterisk like '18:15*'"""
        result, longer = parse_date('18:15*')

        self.assertIsNotNone(result)
        self.assertEqual(result.hour, 18)
        self.assertEqual(result.minute, 15)
        self.assertTrue(longer)

    def test_iso_datetime_format(self):
        """Test parsing ISO datetime like '2025-12-20T11:51:00'"""
        result, longer = parse_date('2025-12-20T11:51:00')

        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 12)
        self.assertEqual(result.day, 20)
        self.assertFalse(longer)

    def test_iso_datetime_with_z_suffix(self):
        """Test parsing ISO datetime with Z suffix like '2025-12-20T11:51:00Z'"""
        result, longer = parse_date('2025-12-20T11:51:00Z')

        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2025)
        self.assertFalse(longer)

    def test_empty_string(self):
        """Test that empty string returns None"""
        result, longer = parse_date('')

        self.assertIsNone(result)
        self.assertFalse(longer)

    def test_dash_placeholder(self):
        """Test that '----' placeholder returns None"""
        result, longer = parse_date('----')

        self.assertIsNone(result)
        self.assertFalse(longer)

    def test_invalid_date_string(self):
        """Test that invalid date string returns None"""
        result, longer = parse_date('not a date')

        self.assertIsNone(result)
        self.assertFalse(longer)

    def test_placeholder_date(self):
        """Test that placeholder date '0001-01-01T00:00:00' returns None"""
        result, longer = parse_date('0001-01-01T00:00:00')

        self.assertIsNone(result)
        self.assertFalse(longer)


if __name__ == '__main__':
    print("Running Bridge Up JSON Parser Tests...")
    print("These tests have ZERO impact on production - purely for development confidence.")
    print("=" * 70)

    unittest.main(verbosity=2)
