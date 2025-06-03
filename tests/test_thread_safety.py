#!/usr/bin/env python3
"""
Bridge Up Thread Safety Tests

Tests to ensure concurrent updates don't cause race conditions.

Run with: python3 test_thread_safety.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
import unittest
from scraper import last_known_state, last_known_state_lock

class TestThreadSafety(unittest.TestCase):
    def test_concurrent_state_updates(self):
        """Test that concurrent updates don't cause race conditions"""
        # Clear state
        last_known_state.clear()
        
        def update_state(thread_id):
            for i in range(100):
                with last_known_state_lock:
                    last_known_state[f"bridge_{thread_id}_{i}"] = {
                        'status': 'Open',
                        'timestamp': time.time()
                    }
                time.sleep(0.001)
        
        # Create 4 threads (matching max_workers=4)
        threads = []
        for i in range(4):
            t = threading.Thread(target=update_state, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Verify no data corruption
        self.assertEqual(len(last_known_state), 400)  # 4 threads * 100 updates
        
        # Verify all keys exist
        for i in range(4):
            for j in range(100):
                self.assertIn(f"bridge_{i}_{j}", last_known_state)

if __name__ == '__main__':
    print("Running Bridge Up Thread Safety Tests...")
    print("Testing concurrent access to shared state.")
    print("=" * 70)
    
    unittest.main(verbosity=2)