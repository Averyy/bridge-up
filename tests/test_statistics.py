#!/usr/bin/env python3
"""
Bridge Up Statistics Tests - Core Prediction Logic

Tests the critical statistics calculations that power iOS app predictions.
These tests ensure math accuracy for the app's unique value proposition.

Run with: python3 test_statistics.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from math import floor, ceil
from stats_calculator import calculate_bridge_statistics, calculate_confidence_interval

class TestStatisticsCalculation(unittest.TestCase):

    def test_average_closure_duration_calculation(self):
        """Test average closure duration math"""
        history = [
            {'status': 'Unavailable (Closed)', 'duration': 600, 'id': '1'},  # 10 minutes
            {'status': 'Unavailable (Closed)', 'duration': 900, 'id': '2'},  # 15 minutes
            {'status': 'Unavailable (Closed)', 'duration': 420, 'id': '3'}   # 7 minutes
        ]
        stats, _ = calculate_bridge_statistics(history)

        # (10 + 15 + 7) / 3 = 10.67, rounded = 11
        self.assertEqual(stats['average_closure_duration'], 11)

    def test_average_raising_soon_calculation(self):
        """Test average raising soon duration math"""
        history = [
            {'status': 'Available (Raising Soon)', 'duration': 780, 'id': '1'},  # 13 minutes
            {'status': 'Available (Raising Soon)', 'duration': 600, 'id': '2'},  # 10 minutes
            {'status': 'Available (Raising Soon)', 'duration': 900, 'id': '3'}   # 15 minutes
        ]
        stats, _ = calculate_bridge_statistics(history)

        # (13 + 10 + 15) / 3 = 12.67, rounded = 13
        self.assertEqual(stats['average_raising_soon'], 13)

    def test_closure_duration_bucketing_boundaries(self):
        """Test critical bucket boundaries for iOS UI"""
        # Test exact boundary conditions based on actual implementation
        test_cases = [
            (539, 'under_9m'),     # 8.98 minutes (< 9)
            (540, '10_15m'),       # 9.0 minutes exactly (>= 9, <= 15)
            (541, '10_15m'),       # 9.02 minutes
            (900, '10_15m'),       # 15.0 minutes exactly (<= 15)
            (901, '16_30m'),       # 15.02 minutes (> 15, <= 30)
            (1800, '16_30m'),      # 30.0 minutes exactly (<= 30)
            (1801, '31_60m'),      # 30.02 minutes (> 30, <= 60)
            (3600, '31_60m'),      # 60.0 minutes exactly (<= 60)
            (3601, 'over_60m')     # 60.02 minutes (> 60)
        ]

        for duration_seconds, expected_bucket in test_cases:
            history = [{'status': 'Unavailable (Closed)', 'duration': duration_seconds, 'id': 'test'}]
            stats, _ = calculate_bridge_statistics(history)

            # Verify only the expected bucket has count=1
            for bucket, count in stats['closure_durations'].items():
                if bucket == expected_bucket:
                    self.assertEqual(count, 1, f"Duration {duration_seconds}s should be in {bucket}")
                else:
                    self.assertEqual(count, 0)

    def test_confidence_interval_calculation(self):
        """Test 95% confidence interval math"""
        # Known dataset for verification
        data = [10, 12, 14, 16, 18]  # Mean=14, StdDev≈3.16
        result = calculate_confidence_interval(data)

        # CI calculation: 1.96 * (3.16 / sqrt(5)) ≈ 2.77
        # Lower: floor(14 - 2.77) = 11, Upper: ceil(14 + 2.77) = 17
        self.assertEqual(result['lower'], 11)
        self.assertEqual(result['upper'], 17)

    def test_confidence_interval_edge_cases(self):
        """Test CI calculation edge cases"""
        # Single data point
        result = calculate_confidence_interval([15])
        self.assertEqual(result, {'lower': 0, 'upper': 0})

        # Empty dataset
        result = calculate_confidence_interval([])
        self.assertEqual(result, {'lower': 0, 'upper': 0})

        # Two identical values (zero variance)
        result = calculate_confidence_interval([10, 10])
        self.assertEqual(result['lower'], 10)
        self.assertEqual(result['upper'], 10)

    def test_zero_data_scenarios(self):
        """Test graceful handling of missing data types"""
        # No closure data, only raising soon
        history = [{'status': 'Available (Raising Soon)', 'duration': 600, 'id': '1'}]
        stats, _ = calculate_bridge_statistics(history)

        self.assertEqual(stats['average_closure_duration'], 0)
        self.assertEqual(stats['closure_ci'], {'lower': 0, 'upper': 0})
        self.assertGreater(stats['average_raising_soon'], 0)

        # No raising soon data, only closures
        history = [{'status': 'Unavailable (Closed)', 'duration': 600, 'id': '1'}]
        stats, _ = calculate_bridge_statistics(history)

        self.assertGreater(stats['average_closure_duration'], 0)
        self.assertEqual(stats['average_raising_soon'], 0)
        self.assertEqual(stats['raising_soon_ci'], {'lower': 0, 'upper': 0})

    def test_history_filtering_construction_removal(self):
        """Test that construction entries are filtered out"""
        history = [
            {'status': 'Unavailable (Closed)', 'duration': 600, 'id': 'test1'},
            {'status': 'Unavailable (Construction)', 'duration': 7200, 'id': 'test2'},  # Should be filtered
            {'status': 'Available', 'duration': 300, 'id': 'test3'},  # Should be filtered
            {'status': 'Available (Raising Soon)', 'duration': 480, 'id': 'test4'}
        ]
        stats, entries_to_delete = calculate_bridge_statistics(history)

        # Should only count the closed and raising soon entries
        self.assertEqual(stats['total_entries'], 2)
        self.assertGreater(stats['average_closure_duration'], 0)
        self.assertGreater(stats['average_raising_soon'], 0)

        # Should mark construction and available entries for deletion
        self.assertIn('test2', entries_to_delete)
        self.assertIn('test3', entries_to_delete)

    def test_closure_duration_buckets_all_present(self):
        """Test all expected buckets exist in output"""
        history = [{'status': 'Unavailable (Closed)', 'duration': 600, 'id': '1'}]
        stats, _ = calculate_bridge_statistics(history)

        expected_buckets = ['under_9m', '10_15m', '16_30m', '31_60m', 'over_60m']
        for bucket in expected_buckets:
            self.assertIn(bucket, stats['closure_durations'])
            self.assertIsInstance(stats['closure_durations'][bucket], int)

    def test_multiple_closures_different_buckets(self):
        """Test multiple closures across different buckets"""
        history = [
            {'status': 'Unavailable (Closed)', 'duration': 300, 'id': '1'},   # 5m -> under_9m
            {'status': 'Unavailable (Closed)', 'duration': 720, 'id': '2'},   # 12m -> 10_15m
            {'status': 'Unavailable (Closed)', 'duration': 1200, 'id': '3'},  # 20m -> 16_30m
            {'status': 'Unavailable (Closed)', 'duration': 2400, 'id': '4'},  # 40m -> 31_60m
            {'status': 'Unavailable (Closed)', 'duration': 4200, 'id': '5'}   # 70m -> over_60m
        ]
        stats, _ = calculate_bridge_statistics(history)

        # Each bucket should have exactly 1 entry
        self.assertEqual(stats['closure_durations']['under_9m'], 1)
        self.assertEqual(stats['closure_durations']['10_15m'], 1)
        self.assertEqual(stats['closure_durations']['16_30m'], 1)
        self.assertEqual(stats['closure_durations']['31_60m'], 1)
        self.assertEqual(stats['closure_durations']['over_60m'], 1)

        # Average should be (5+12+20+40+70)/5 = 29.4, rounded = 29
        self.assertEqual(stats['average_closure_duration'], 29)

if __name__ == '__main__':
    print("Running Bridge Up Statistics Tests...")
    print("Testing the core prediction logic that powers iOS app intelligence.")
    print("=" * 70)

    unittest.main(verbosity=2)
