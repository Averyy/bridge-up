#!/usr/bin/env python3
"""
Bridge Up Test Runner - Run all tests

Following "guardrails not roadblocks" philosophy.
Tests what matters for confidence, not comprehensiveness.

Run with: python3 run_tests.py
"""
import subprocess
import sys
import time

def run_test_file(filename, description):
    """Run a single test file and report results"""
    print(f"\n{'='*70}")
    print(f"Running {description}...")
    print(f"{'='*70}")
    
    start_time = time.time()
    result = subprocess.run([sys.executable, filename], capture_output=True, text=True)
    elapsed = time.time() - start_time
    
    if result.returncode == 0:
        # Extract OK line from output
        for line in result.stdout.split('\n'):
            if line.strip().startswith('OK') or 'Ran' in line:
                print(f"✅ {line.strip()} ({elapsed:.2f}s)")
        return True
    else:
        print(f"❌ FAILED - see details below:")
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        return False

def main():
    print("🌉 Bridge Up Backend Test Suite")
    print("Testing critical business logic only - guardrails not roadblocks")
    
    tests = [
        ("tests/test_parsers.py", "Parser Tests (JSON parsing logic)"),
        ("tests/test_statistics.py", "Statistics Tests (prediction calculations)"),
        ("tests/test_status_edge_cases.py", "Status Edge Cases (realistic scenarios)"),
        ("tests/test_configuration.py", "Configuration Tests (deployment safety)"),
        ("tests/test_thread_safety.py", "Thread Safety Tests (concurrent access)"),
        ("tests/test_backoff.py", "Backoff Tests (exponential retry logic)"),
        ("tests/test_network_backoff.py", "Network Backoff Tests (failure handling)"),
        ("tests/test_logging.py", "Logging Tests (output format)")
    ]
    
    passed = 0
    failed = 0
    total_start = time.time()
    
    for test_file, description in tests:
        if run_test_file(test_file, description):
            passed += 1
        else:
            failed += 1
    
    total_time = time.time() - total_start
    
    print(f"\n{'='*70}")
    print(f"Test Summary: {passed} passed, {failed} failed in {total_time:.2f}s")
    print(f"{'='*70}")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n✅ All tests passed! Safe to deploy.")

if __name__ == '__main__':
    main()