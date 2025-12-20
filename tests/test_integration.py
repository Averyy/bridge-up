#!/usr/bin/env python3
"""
Bridge Up Integration Test

Manual test to verify all components work together.
This simulates failures and verifies recovery.

Run with: python3 tests/test_integration.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
from unittest.mock import patch
from scraper import process_single_region, region_failures, logger
from config import BRIDGE_KEYS

def test_concurrent_with_failures():
    """Test concurrent scraping with simulated failures"""
    print("\n=== Testing Concurrent Scraping with Failures ===")

    # Create a mock that fails first 2 times, then succeeds
    call_counts = {}
    original_scrape = __import__('scraper', fromlist=['scrape_bridge_data']).scrape_bridge_data

    def mock_scrape(bridge_key, timeout=10, retries=3):
        if bridge_key not in call_counts:
            call_counts[bridge_key] = 0
        call_counts[bridge_key] += 1

        # Fail first 2 attempts for one specific region
        if bridge_key == 'BridgePC' and call_counts[bridge_key] <= 2:
            raise Exception("Simulated network failure")

        return original_scrape(bridge_key, timeout, retries)

    # Patch and run
    with patch('scraper.scrape_bridge_data', side_effect=mock_scrape):
        # Clear any existing failures
        region_failures.clear()

        # Run scraping 3 times with 5 second gaps
        for i in range(3):
            print(f"\n--- Run {i+1} ---")
            threads = []

            for bridge_key, info in BRIDGE_KEYS.items():
                t = threading.Thread(target=process_single_region, args=((bridge_key, info),))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # Show failure status
            if region_failures:
                print("\nFailure tracking:")
                for bridge_key, (count, next_retry) in region_failures.items():
                    wait = (next_retry - __import__('datetime').datetime.now()).total_seconds()
                    print(f"  {bridge_key}: {count} failures, retry in {wait:.0f}s")

            time.sleep(5)

    print("\n✅ Integration test complete!")

def test_logging_output():
    """Test that logging produces expected output"""
    print("\n=== Testing Log Output Format ===")
    
    logger.info("✓ St Catharines: 5")
    logger.warning("⚠ Port Colborne: No data")
    logger.error("✗ Montreal: Connection timeout...")
    logger.info("⏳ Salaberry: Still waiting 30s (attempt #3)")
    logger.info("Done in 1.2s - All: 3 ✓, 1 ✗")
    
    print("\n✅ Log format test complete!")

def main():
    print("🌉 Bridge Up Integration Tests")
    print("Testing all components work together")
    print("=" * 70)
    
    # Test logging first
    test_logging_output()
    
    # Test concurrent scraping with failures
    test_concurrent_with_failures()
    
    print("\n" + "=" * 70)
    print("All integration tests completed!")
    print("Check the output above to verify:")
    print("1. Log messages are clean and concise")
    print("2. Failures trigger exponential backoff")
    print("3. Recovery messages appear when sites come back")
    print("4. Concurrent execution works without issues")

if __name__ == '__main__':
    main()