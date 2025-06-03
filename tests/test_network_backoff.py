#!/usr/bin/env python3
"""
Bridge Up Network Failure Backoff Tests

Tests that network failures trigger the backoff mechanism.

Run with: python3 test_network_backoff.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, Mock
from datetime import datetime
from scraper import process_single_region, region_failures, region_failures_lock

class TestNetworkBackoff(unittest.TestCase):
    
    def setUp(self):
        """Clear failure tracking before each test"""
        with region_failures_lock:
            region_failures.clear()
    
    @patch('scraper.scrape_bridge_data')
    @patch('scraper.update_firestore')
    def test_network_failure_triggers_backoff(self, mock_update, mock_scrape):
        """Test that network failures trigger exponential backoff"""
        test_url = "https://test-bridge.com"
        test_info = {'region': 'Test Region', 'shortform': 'TEST'}
        
        # Simulate network failure (empty list returned)
        mock_scrape.return_value = []
        
        # First attempt - should fail and set backoff
        result = process_single_region((test_url, test_info))
        self.assertEqual(result, (False, 0))
        
        # Check backoff was set
        with region_failures_lock:
            self.assertIn(test_url, region_failures)
            failure_count, next_retry = region_failures[test_url]
            self.assertEqual(failure_count, 1)
            wait_time = (next_retry - datetime.now()).total_seconds()
            self.assertAlmostEqual(wait_time, 2, delta=1)  # ~2 seconds
        
        # Second attempt immediately - should be in backoff
        result = process_single_region((test_url, test_info))
        self.assertEqual(result, (False, 0))
        
        # Verify scrape wasn't called during backoff
        self.assertEqual(mock_scrape.call_count, 1)  # Only called once
    
    @patch('scraper.scrape_bridge_data')
    @patch('scraper.update_firestore')
    def test_recovery_after_network_failure(self, mock_update, mock_scrape):
        """Test that successful scrape clears backoff"""
        test_url = "https://test-bridge.com"
        test_info = {'region': 'Test Region', 'shortform': 'TEST'}
        
        # First fail
        mock_scrape.return_value = []
        process_single_region((test_url, test_info))
        
        # Verify failure tracked
        with region_failures_lock:
            self.assertIn(test_url, region_failures)
        
        # Clear backoff manually to simulate time passing
        with region_failures_lock:
            failure_count, _ = region_failures[test_url]
            region_failures[test_url] = (failure_count, datetime.now())  # Set retry time to now
        
        # Now succeed
        mock_scrape.return_value = [{'name': 'Bridge1'}, {'name': 'Bridge2'}]
        result = process_single_region((test_url, test_info))
        self.assertEqual(result, (True, 2))
        
        # Verify failure cleared
        with region_failures_lock:
            self.assertNotIn(test_url, region_failures)
    
    @patch('scraper.scrape_bridge_data')
    def test_exception_triggers_backoff(self, mock_scrape):
        """Test that exceptions also trigger backoff"""
        test_url = "https://test-bridge.com"
        test_info = {'region': 'Test Region', 'shortform': 'TEST'}
        
        # Simulate exception
        mock_scrape.side_effect = Exception("Network error")
        
        # Should handle exception and set backoff
        result = process_single_region((test_url, test_info))
        self.assertEqual(result, (False, 0))
        
        # Check backoff was set
        with region_failures_lock:
            self.assertIn(test_url, region_failures)
            failure_count, _ = region_failures[test_url]
            self.assertEqual(failure_count, 1)

if __name__ == '__main__':
    print("Running Bridge Up Network Backoff Tests...")
    print("Testing network failure handling with exponential backoff.")
    print("=" * 70)
    
    unittest.main(verbosity=2)