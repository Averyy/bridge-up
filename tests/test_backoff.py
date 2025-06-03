#!/usr/bin/env python3
"""
Bridge Up Backoff and Recovery Tests

Tests for smart backoff functionality that never gives up.

Run with: python3 test_backoff.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from scraper import handle_region_failure, region_failures, region_failures_lock

class TestBackoffBehavior(unittest.TestCase):
    
    def setUp(self):
        """Clear failure tracking before each test"""
        with region_failures_lock:
            region_failures.clear()
    
    def test_exponential_backoff_calculation(self):
        """Test that backoff follows exponential pattern"""
        test_url = "https://test.com"
        test_region = "Test Region"
        
        # Simulate multiple failures
        expected_waits = [2, 4, 8, 16, 32, 64, 128, 256, 300, 300]  # Caps at 300
        
        for i, expected_wait in enumerate(expected_waits):
            handle_region_failure(test_url, test_region, "Test error")
            
            with region_failures_lock:
                failure_count, next_retry = region_failures[test_url]
                
                # Check failure count
                self.assertEqual(failure_count, i + 1)
                
                # Check wait time (approximately, within 1 second)
                actual_wait = (next_retry - datetime.now()).total_seconds()
                self.assertAlmostEqual(actual_wait, expected_wait, delta=1.0)
    
    def test_backoff_caps_at_5_minutes(self):
        """Test that backoff caps at 300 seconds (5 minutes)"""
        test_url = "https://test.com"
        test_region = "Test Region"
        
        # Simulate many failures (10+)
        for _ in range(15):
            handle_region_failure(test_url, test_region, "Test error")
        
        with region_failures_lock:
            failure_count, next_retry = region_failures[test_url]
            wait_seconds = (next_retry - datetime.now()).total_seconds()
            
            # Should cap at 300 seconds
            self.assertLessEqual(wait_seconds, 301)  # Allow 1 second tolerance
            self.assertGreaterEqual(wait_seconds, 299)
    
    def test_multiple_regions_independent_backoff(self):
        """Test that different regions have independent backoff timers"""
        url1 = "https://test1.com"
        url2 = "https://test2.com"
        
        # Fail first region twice
        handle_region_failure(url1, "Region 1", "Error")
        handle_region_failure(url1, "Region 1", "Error")
        
        # Fail second region once
        handle_region_failure(url2, "Region 2", "Error")
        
        with region_failures_lock:
            # Check independent failure counts
            self.assertEqual(region_failures[url1][0], 2)
            self.assertEqual(region_failures[url2][0], 1)
            
            # Check different wait times
            wait1 = (region_failures[url1][1] - datetime.now()).total_seconds()
            wait2 = (region_failures[url2][1] - datetime.now()).total_seconds()
            
            self.assertAlmostEqual(wait1, 4, delta=1)  # 2^2
            self.assertAlmostEqual(wait2, 2, delta=1)  # 2^1
    
    def test_concurrent_failure_updates(self):
        """Test thread-safe failure tracking"""
        import threading
        
        test_url = "https://concurrent-test.com"
        
        def simulate_failures():
            for _ in range(10):
                handle_region_failure(test_url, "Concurrent Region", "Error")
        
        # Run concurrent failure updates
        threads = []
        for _ in range(4):
            t = threading.Thread(target=simulate_failures)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should have exactly 40 failures (4 threads * 10 each)
        with region_failures_lock:
            self.assertEqual(region_failures[test_url][0], 40)

if __name__ == '__main__':
    print("Running Bridge Up Backoff Tests...")
    print("Testing exponential backoff and recovery behavior.")
    print("=" * 70)
    
    unittest.main(verbosity=2)