#!/usr/bin/env python3
"""
Bridge Up Parser Tests - Core Business Logic Only

Tests the critical parsing functions that could fail silently if websites change.
These tests have ZERO impact on production - they're purely for development confidence.

Run with: python3 test_parsers.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
from scraper import parse_old_style, parse_new_style, interpret_bridge_status, parse_date

TIMEZONE = pytz.timezone('America/Toronto')

class TestCoreParsing(unittest.TestCase):
    
    def test_old_style_parsing_normal_status(self):
        """Test old-style parser with typical bridge status"""
        html = '''
        <table id="grey_box">
            <tr>
                <td>
                    <span class="lgtextblack">Main St.</span>
                    <span id="status">Available</span>
                    <span class="lgtextblack10">Next Arrival: ----</span>
                </td>
            </tr>
        </table>
        '''
        soup = BeautifulSoup(html, 'lxml')
        bridges = parse_old_style(soup)
        
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]['name'], 'Main St.')
        self.assertEqual(bridges[0]['raw_status'], 'Available')
        self.assertEqual(len(bridges[0]['upcoming_closures']), 0)
    
    def test_old_style_parsing_with_closure_time(self):
        """Test old-style parser with upcoming closure"""
        html = '''
        <table id="grey_box">
            <tr>
                <td>
                    <span class="lgtextblack">Victoria Bridge Downstream</span>
                    <span id="status">Available (raising soon)</span>
                    <span class="lgtextblack10">Next Arrival: 18:15</span>
                </td>
            </tr>
        </table>
        '''
        soup = BeautifulSoup(html, 'lxml')
        bridges = parse_old_style(soup)
        
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]['name'], 'Victoria Bridge Downstream')
        self.assertEqual(bridges[0]['raw_status'], 'Available (raising soon)')
        self.assertEqual(len(bridges[0]['upcoming_closures']), 1)
        self.assertEqual(bridges[0]['upcoming_closures'][0]['type'], 'Next Arrival')
    
    def test_new_style_parsing_sbs_format(self):
        """Test new-style parser with SBS region format"""
        html = '''
        <div class="new-bridgestatus-container">
            <div class="bridge-item">
                <h3>St-Louis-de-Gonzague Bridge</h3>
                <h1 class="status-title">Available</h1>
                <h1 class="status-title">(raising soon)</h1>
                <div class="bridge-lift-container">
                    <p class="item-data">Commercial Vessel: 17:45*</p>
                    <p class="item-data">Commercial Vessel: 18:22*</p>
                </div>
            </div>
        </div>
        '''
        soup = BeautifulSoup(html, 'lxml')
        bridges = parse_new_style(soup)
        
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]['name'], 'St-Louis-de-Gonzague Bridge')
        self.assertEqual(bridges[0]['raw_status'], 'Available (raising soon)')
        self.assertEqual(len(bridges[0]['upcoming_closures']), 2)
        
        # Check first closure
        closure = bridges[0]['upcoming_closures'][0]
        self.assertEqual(closure['type'], 'Commercial Vessel')
        self.assertTrue(closure['longer'])  # Should detect asterisk
    
    def test_new_style_parsing_no_closures(self):
        """Test new-style parser with no upcoming closures"""
        html = '''
        <div class="new-bridgestatus-container">
            <div class="bridge-item">
                <h3>Larocque Bridge (Salaberry-de-Valleyfield)</h3>
                <h1 class="status-title">Available</h1>
                <div class="bridge-lift-container">
                    <p class="item-data">No anticipated bridge lifts</p>
                </div>
            </div>
        </div>
        '''
        soup = BeautifulSoup(html, 'lxml')
        bridges = parse_new_style(soup)
        
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]['name'], 'Larocque Bridge (Salaberry-de-Valleyfield)')
        self.assertEqual(bridges[0]['raw_status'], 'Available')
        self.assertEqual(len(bridges[0]['upcoming_closures']), 0)
    
    def test_status_interpretation_available(self):
        """Test status interpretation for available bridges"""
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': 'Available',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertTrue(result['available'])
        self.assertEqual(result['status'], 'Open')
    
    def test_status_interpretation_raising_soon(self):
        """Test status interpretation for raising soon"""
        bridge_data = {
            'name': 'Test Bridge', 
            'raw_status': 'Available (raising soon)',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertTrue(result['available'])
        self.assertEqual(result['status'], 'Closing soon')
    
    def test_status_interpretation_unavailable(self):
        """Test status interpretation for unavailable bridges"""
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': 'Unavailable (raised since 17:38)',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertFalse(result['available'])
        self.assertEqual(result['status'], 'Closed')
    
    def test_status_interpretation_data_unavailable(self):
        """Test status interpretation when data is unavailable"""
        bridge_data = {
            'name': 'Test Bridge',
            'raw_status': 'Data unavailable',
            'upcoming_closures': []
        }
        result = interpret_bridge_status(bridge_data)
        
        self.assertFalse(result['available'])
        self.assertEqual(result['status'], 'Unknown')
    
    def test_parse_date_time_only(self):
        """Test parsing time-only formats"""
        result, longer = parse_date('17:45')
        self.assertIsNotNone(result)
        self.assertFalse(longer)
        self.assertEqual(result.hour, 17)
        self.assertEqual(result.minute, 45)
    
    def test_parse_date_with_asterisk(self):
        """Test parsing time with asterisk (longer closure)"""
        result, longer = parse_date('18:22*')
        self.assertIsNotNone(result)
        self.assertTrue(longer)
        self.assertEqual(result.hour, 18)
        self.assertEqual(result.minute, 22)
    
    def test_parse_date_invalid_format(self):
        """Test parsing invalid date format"""
        result, longer = parse_date('invalid-time')
        self.assertIsNone(result)
        self.assertFalse(longer)
    
    def test_parse_date_dash_format(self):
        """Test parsing dash format (no closure)"""
        result, longer = parse_date('----')
        self.assertIsNone(result)
        self.assertFalse(longer)

if __name__ == '__main__':
    print("Running Bridge Up Parser Tests...")
    print("These tests have ZERO impact on production - purely for development confidence.")
    print("=" * 70)
    
    unittest.main(verbosity=2)