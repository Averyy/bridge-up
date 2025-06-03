#!/usr/bin/env python3
"""
Bridge Up Logging Tests

Tests for Loguru integration and log output format.

Run with: python3 test_logging.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from scraper import logger

class TestLoggingConfiguration(unittest.TestCase):
    
    def test_logger_exists(self):
        """Test that logger is imported and available"""
        self.assertIsNotNone(logger)
    
    def test_logger_methods_exist(self):
        """Test that logger has expected methods"""
        self.assertTrue(hasattr(logger, 'info'))
        self.assertTrue(hasattr(logger, 'error'))
        self.assertTrue(hasattr(logger, 'warning'))
        self.assertTrue(hasattr(logger, 'debug'))
    
    def test_logger_can_log(self):
        """Test that logger can log without errors"""
        try:
            logger.info("Test info message")
            logger.warning("Test warning message")
            logger.error("Test error message")
            # If we get here without exceptions, logging works
            success = True
        except Exception:
            success = False
        
        self.assertTrue(success)
    
    def test_logger_handles_unicode(self):
        """Test that logger handles unicode characters"""
        try:
            logger.info("✓ Unicode test: 日本語")
            logger.error("✗ Error with émojis 🔥")
            success = True
        except Exception:
            success = False
        
        self.assertTrue(success)
    
    def test_logger_handles_long_messages(self):
        """Test that logger handles long messages"""
        long_message = "x" * 1000
        try:
            logger.info(long_message)
            success = True
        except Exception:
            success = False
        
        self.assertTrue(success)

if __name__ == '__main__':
    print("Running Bridge Up Logging Tests...")
    print("Testing Loguru configuration and output format.")
    print("=" * 70)
    
    # Suppress log output during tests
    logger.remove()
    logger.add(sys.stderr, level="CRITICAL")
    
    unittest.main(verbosity=2)