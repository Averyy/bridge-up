#!/usr/bin/env python3
"""
Bridge Up Status Edge Case Tests - Realistic Guardrails

Tests realistic edge cases that we've seen or might reasonably encounter.
Following "guardrails not roadblocks" - testing what matters, not every possibility.

Run with: python3 test_status_edge_cases.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from scraper import interpret_bridge_status

class TestStatusEdgeCases(unittest.TestCase):
    
    def test_case_sensitivity_common_variations(self):
        """Test case variations we've actually seen"""
        test_cases = [
            ('AVAILABLE', True, 'Open'),
            ('available', True, 'Open'),
            ('Available', True, 'Open'),
            ('UNAVAILABLE', False, 'Closed'),
            ('Unavailable', False, 'Closed'),
            ('Available (Raising Soon)', True, 'Closing soon'),
            ('AVAILABLE (RAISING SOON)', True, 'Closing soon')
        ]
        
        for raw_status, expected_available, expected_status in test_cases:
            bridge_data = {
                'name': 'Test Bridge',
                'raw_status': raw_status,
                'upcoming_closures': []
            }
            result = interpret_bridge_status(bridge_data)
            self.assertEqual(result['available'], expected_available,
                           f"Available check failed for: {raw_status}")
            self.assertEqual(result['status'], expected_status, 
                           f"Status check failed for: {raw_status}")
    
    def test_data_unavailable_handling(self):
        """Test the specific 'data unavailable' case"""
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': 'Data unavailable',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertFalse(result['available'])
        self.assertEqual(result['status'], 'Unknown')
    
    def test_status_with_timing_details(self):
        """Test statuses with embedded timing info"""
        test_cases = [
            ('Unavailable (raised since 17:38)', False, 'Closed'),
            ('Unavailable (raised at 14:30)', False, 'Closed'),
            ('Available (last raised 08:00)', True, 'Open'),
            ('Unavailable (lowering)', False, 'Opening')
        ]
        
        for raw_status, expected_available, expected_status in test_cases:
            bridge_data = {
                'name': 'Test Bridge',
                'raw_status': raw_status,
                'upcoming_closures': []
            }
            result = interpret_bridge_status(bridge_data)
            self.assertEqual(result['available'], expected_available)
            self.assertEqual(result['status'], expected_status)
    
    def test_construction_status(self):
        """Test construction-related statuses"""
        # Current implementation only checks for "work in progress"
        test_cases = [
            ('Unavailable (work in progress)', False, 'Construction'),
            ('unavailable (Work In Progress)', False, 'Construction'),
            ('UNAVAILABLE (WORK IN PROGRESS)', False, 'Construction'),
            # These will be "Closed" in current implementation
            ('Unavailable (Construction)', False, 'Closed'),
            ('unavailable (construction)', False, 'Closed')
        ]
        
        for raw_status, expected_available, expected_status in test_cases:
            bridge_data = {
                'name': 'Test Bridge',
                'raw_status': raw_status,
                'upcoming_closures': []
            }
            result = interpret_bridge_status(bridge_data)
            self.assertEqual(result['available'], expected_available)
            self.assertEqual(result['status'], expected_status)
    
    def test_empty_status_defaults_to_closed(self):
        """Test that empty/missing status is handled safely"""
        # Current implementation treats empty as closed/unknown
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': '',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        # Empty status is treated as unavailable
        self.assertFalse(result['available'])
    
    def test_whitespace_in_status(self):
        """Test status with extra whitespace"""
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': '  Available  ',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertTrue(result['available'])
        self.assertEqual(result['status'], 'Open')
    
    def test_mixed_available_unavailable(self):
        """Test the priority of unavailable over available"""
        # "unavailable" takes precedence in the current logic
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': 'Previously available, now unavailable',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertFalse(result['available'])
    
    def test_garbage_data_returns_unknown_not_closed(self):
        """Test that unrecognized data returns Unknown, not Closed"""
        garbage_inputs = [
            "Server Error 500",
            "Maintenance Mode", 
            "<!DOCTYPE html>",
            "Random garbage text",
            ""
        ]
        
        for garbage in garbage_inputs:
            bridge_data = {
                'name': 'Test Bridge',
                'raw_status': garbage,
                'upcoming_closures': []
            }
            result = interpret_bridge_status(bridge_data)
            self.assertEqual(result['status'], 'Unknown', 
                            f"Garbage '{garbage}' should map to Unknown, not {result['status']}")

if __name__ == '__main__':
    print("Running Bridge Up Status Edge Case Tests...")
    print("Testing realistic edge cases as guardrails, not roadblocks.")
    print("=" * 70)
    
    unittest.main(verbosity=2)