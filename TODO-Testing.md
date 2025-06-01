# TODO: Testing Implementation Roadmap

## Overview
This document outlines additional testing opportunities for the Bridge Up Backend to build with confidence. These tests focus on business logic that could fail silently in production.

**Philosophy**: Guardrails, Not Roadblocks - test what matters most, skip the infrastructure.

---

## 📊 Statistics Calculation Answer

**YES - All statistics are calculated in THIS Python backend!**

**Location**: `stats_calculator.py` → `calculate_bridge_statistics()`
**Trigger**: Daily at 3AM (production) / 4AM (dev) via APScheduler
**Process**: 
1. Reads bridge history from Firebase
2. Calculates all statistics in Python
3. Writes back to Firebase `statistics` field

**🚨 CRITICAL: These calculations power your iOS app's intelligence!**

The exact Firebase values you mentioned are calculated here:
- `average_closure_duration`: Line 68 - `round(sum(closure_durations) / len(closure_durations))`
- `closure_ci`: Line 69 - `{'lower': floor(avg-margin), 'upper': ceil(avg+margin)}`
- `closure_durations`: Line 81 - Duration buckets based on Lines 52-61:
  - `under_9m`: duration < 9 minutes
  - `10_15m`: 9 ≤ duration ≤ 15 minutes  
  - `16_30m`: 15 < duration ≤ 30 minutes
  - `31_60m`: 30 < duration ≤ 60 minutes
  - `over_60m`: duration > 60 minutes
- `average_raising_soon`: Line 75 - `round(sum(raising_soon_durations) / len(raising_soon_durations))`
- `raising_soon_ci`: Line 76 - Same confidence interval math as closures
- `total_entries`: Line 82 - Count of kept history entries (enforces MAX_HISTORY_ENTRIES = 300)

**📈 Why Statistics Testing is ABSOLUTELY CRITICAL:**
1. **App Differentiation**: These predictions are what makes your app unique vs simple bridge status apps
2. **User Trust**: Wrong predictions = users lose confidence in your app
3. **Silent Failures**: Math errors won't crash the app, but will provide wrong data
4. **iOS UI Dependency**: Duration buckets directly drive iOS app UI display
5. **Business Logic**: Confidence intervals determine prediction reliability shown to users

---

## 🚨 Priority 1: Critical Business Logic Tests (Week 1)

### ✅ COMPLETED
- [x] Basic parser tests (`test_parsers.py`)
- [x] Status interpretation fundamentals  
- [x] Date/time parsing basics

### 🔥 HIGH PRIORITY - IMPLEMENT FIRST

#### 1. Statistics Calculation Logic Tests ⭐ HIGHEST PRIORITY ⭐
**File**: `stats_calculator.py` - Lines 7-98  
**Estimated Time**: 4-5 hours  
**Why Critical**: This is your app's core intelligence! Math errors break iOS predictions and differentiate your app from competitors.

**CRITICAL: All your Firebase statistics fields are calculated here:**
- `average_closure_duration` (Line 68)
- `closure_ci` → `{'lower': X, 'upper': Y}` (Line 69) 
- `closure_durations` → `{'under_9m': X, '10_15m': Y, ...}` (Line 81)
- `average_raising_soon` (Line 75)
- `raising_soon_ci` → `{'lower': X, 'upper': Y}` (Line 76)
- `total_entries` (Line 82, max 300)

**Test Cases Needed**:
```python
class TestStatisticsCalculation(unittest.TestCase):
    def test_average_closure_duration_calculation(self):
        # Test Line 68: round(sum(closure_durations) / len(closure_durations))
        history = [
            {'status': 'Unavailable (Closed)', 'duration': 600},  # 10 minutes  
            {'status': 'Unavailable (Closed)', 'duration': 900},  # 15 minutes
            {'status': 'Unavailable (Closed)', 'duration': 420}   # 7 minutes
        ]
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        expected = round((10 + 15 + 7) / 3)  # Should be 11 minutes
        self.assertEqual(stats['average_closure_duration'], expected)
        
    def test_average_raising_soon_calculation(self):
        # Test Line 75: round(sum(raising_soon_durations) / len(raising_soon_durations))
        history = [
            {'status': 'Available (Raising Soon)', 'duration': 780},  # 13 minutes
            {'status': 'Available (Raising Soon)', 'duration': 600},  # 10 minutes  
            {'status': 'Available (Raising Soon)', 'duration': 900}   # 15 minutes
        ]
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        expected = round((13 + 10 + 15) / 3)  # Should be 13 minutes
        self.assertEqual(stats['average_raising_soon'], expected)
        
    def test_closure_duration_bucketing_exact_boundaries(self):
        # Test Lines 52-61: Critical boundary conditions for iOS UI
        test_cases = [
            (539, 'under_9m'),     # 8.98 minutes - just under 9
            (540, 'under_9m'),     # 9.0 minutes exactly - boundary case!
            (541, '10_15m'),       # 9.02 minutes - just over 9
            (900, '10_15m'),       # 15.0 minutes exactly
            (901, '16_30m'),       # 15.02 minutes - just over 15
            (1800, '16_30m'),      # 30.0 minutes exactly
            (1801, '31_60m'),      # 30.02 minutes - just over 30
            (3600, '31_60m'),      # 60.0 minutes exactly
            (3601, 'over_60m')     # 60.02 minutes - just over 60
        ]
        
        for duration_seconds, expected_bucket in test_cases:
            history = [{'status': 'Unavailable (Closed)', 'duration': duration_seconds}]
            stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
            
            # Check that only the expected bucket has count=1, others are 0
            for bucket, count in stats['closure_durations'].items():
                if bucket == expected_bucket:
                    self.assertEqual(count, 1, f"Duration {duration_seconds}s should be in {bucket}")
                else:
                    self.assertEqual(count, 0, f"Duration {duration_seconds}s should NOT be in {bucket}")
                    
    def test_confidence_interval_mathematics(self):
        # Test Lines 86-98: 95% confidence interval calculation
        # Using known statistical dataset for verification
        data = [10, 12, 14, 16, 18]  # Mean=14, StdDev≈3.16
        result = calculate_confidence_interval(data)
        
        # Manual calculation: 1.96 * (3.16 / sqrt(5)) ≈ 2.77
        # Lower: floor(14 - 2.77) = 11, Upper: ceil(14 + 2.77) = 17
        self.assertEqual(result['lower'], 11)
        self.assertEqual(result['upper'], 17)
        
    def test_confidence_interval_edge_cases(self):
        # Single data point (new bridges) - Line 87-88
        result = calculate_confidence_interval([15])
        self.assertEqual(result, {'lower': 0, 'upper': 0})
        
        # Empty dataset
        result = calculate_confidence_interval([])
        self.assertEqual(result, {'lower': 0, 'upper': 0})
        
        # Two identical values (zero variance)
        result = calculate_confidence_interval([10, 10])
        self.assertEqual(result['lower'], result['upper'])
        
        # Very small dataset (n=2)
        result = calculate_confidence_interval([8, 12])  # Mean=10
        self.assertIsInstance(result['lower'], int)
        self.assertIsInstance(result['upper'], int)
        self.assertLessEqual(result['lower'], 10)
        self.assertGreaterEqual(result['upper'], 10)
        
    def test_history_entry_filtering_and_max_entries(self):
        # Test Lines 28-42: Critical data management logic
        history = []
        
        # Add entries that should be KEPT
        for i in range(150):
            history.append({'status': 'Unavailable (Closed)', 'duration': 600, 'id': f'keep_{i}'})
        for i in range(150):  
            history.append({'status': 'Available (Raising Soon)', 'duration': 480, 'id': f'keep_soon_{i}'})
            
        # Add entries that should be DELETED
        for i in range(50):
            history.append({'status': 'Available', 'duration': 300, 'id': f'delete_avail_{i}'})
        for i in range(50):
            history.append({'status': 'Unavailable (Construction)', 'duration': 7200, 'id': f'delete_const_{i}'})
            
        # Total: 400 entries, but only 300 'kept' entries, should enforce MAX_HISTORY_ENTRIES
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        
        # Should keep exactly 300 entries (MAX_HISTORY_ENTRIES)
        self.assertEqual(stats['total_entries'], 300)
        
        # Should have both closure and raising soon data
        self.assertGreater(stats['average_closure_duration'], 0)
        self.assertGreater(stats['average_raising_soon'], 0)
        
    def test_zero_data_scenarios(self):
        # Test Lines 67-79: Graceful handling of missing data
        
        # No closure data, only raising soon
        history = [{'status': 'Available (Raising Soon)', 'duration': 600}]
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        self.assertEqual(stats['average_closure_duration'], 0)
        self.assertEqual(stats['closure_ci'], {'lower': 0, 'upper': 0})
        self.assertGreater(stats['average_raising_soon'], 0)
        
        # No raising soon data, only closures  
        history = [{'status': 'Unavailable (Closed)', 'duration': 600}]
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        self.assertGreater(stats['average_closure_duration'], 0)
        self.assertEqual(stats['average_raising_soon'], 0)
        self.assertEqual(stats['raising_soon_ci'], {'lower': 0, 'upper': 0})
        
        # No valid data at all
        history = [{'status': 'Available', 'duration': 600}]  # Gets filtered out
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        self.assertEqual(stats['average_closure_duration'], 0)
        self.assertEqual(stats['average_raising_soon'], 0)
        self.assertEqual(stats['total_entries'], 0)
        
    def test_closure_duration_buckets_completeness(self):
        # Test Line 81: Ensure all expected buckets exist
        history = [{'status': 'Unavailable (Closed)', 'duration': 600}]
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        
        expected_buckets = ['under_9m', '10_15m', '16_30m', '31_60m', 'over_60m']
        for bucket in expected_buckets:
            self.assertIn(bucket, stats['closure_durations'])
            self.assertIsInstance(stats['closure_durations'][bucket], int)
            
    def test_duration_conversion_accuracy(self):
        # Test Lines 50, 63: Seconds to minutes conversion (duration / 60)
        history = [
            {'status': 'Unavailable (Closed)', 'duration': 1800},      # 30 minutes
            {'status': 'Available (Raising Soon)', 'duration': 900}    # 15 minutes
        ]
        stats, _, _ = calculate_bridge_statistics(history, mock_doc_ref, mock_batch)
        
        self.assertEqual(stats['average_closure_duration'], 30)    # 1800/60 = 30
        self.assertEqual(stats['average_raising_soon'], 15)        # 900/60 = 15
```

#### 2. Status Interpretation Edge Cases  
**File**: `scraper.py` - Lines 182-227  
**Estimated Time**: 2-3 hours  
**Why Critical**: Website changes break this silently

**Test Cases Needed**:
```python
class TestStatusInterpretationAdvanced(unittest.TestCase):
    def test_case_sensitivity_variations(self):
        # 'AVAILABLE (RAISING SOON)' vs 'available (raising soon)'
        # Mixed case scenarios from website changes
        
    def test_unexpected_status_formats(self):
        # 'Unavailable - maintenance work'
        # 'Unavailable (lowering)' 
        # 'Temporarily unavailable'
        # 'Service interruption'
        
    def test_status_normalization_edge_cases(self):
        # Complex closing scenarios
        # Multiple status indicators in one string
        # Unicode characters in status text
```

---

## 🔧 Priority 2: Data Validation Tests (Week 2)

#### 3. Configuration Validation Tests
**File**: `config.py` - All bridge configuration  
**Estimated Time**: 1-2 hours  
**Why Valuable**: Catches deployment configuration errors

**Test Cases Needed**:
```python
class TestConfiguration(unittest.TestCase):
    def test_bridge_configuration_completeness(self):
        # Every bridge in BRIDGE_DETAILS has lat/lng
        # Coordinate ranges are valid (-90 to 90, -180 to 180)
        # Every region in BRIDGE_URLS exists in BRIDGE_DETAILS
        
    def test_region_consistency(self):
        # Region names match between BRIDGE_URLS and BRIDGE_DETAILS
        # Shortform codes are unique
        # No duplicate bridge names within regions
        
    def test_url_format_validation(self):
        # All URLs are properly formatted
        # Required query parameters present
        # No broken or malformed URLs
```

#### 4. Document ID Sanitization Tests
**File**: `scraper.py` - Lines 355-362  
**Estimated Time**: 1-2 hours  
**Why Valuable**: Prevents Firebase write failures

**Test Cases Needed**:
```python
class TestDocumentSanitization(unittest.TestCase):
    def test_unicode_handling(self):
        # French bridge names: 'Sainte-Cathérine Bridge'
        # Accented characters in region names
        # Special Unicode characters
        
    def test_special_character_removal(self):
        # 'Main St. (Highway #20)' → 'PC_MainStHighway'
        # Parentheses, periods, hash symbols
        # Forward slashes, ampersands
        
    def test_length_limits(self):
        # Very long bridge names (>30 chars)
        # Firebase document ID constraints
        # Consistent truncation behavior
```

---

## ⚠️ Priority 3: Edge Cases & Data Integrity (Week 3)

#### 5. Date/Time Parsing Advanced Tests
**File**: `scraper.py` - Lines 41-65  
**Estimated Time**: 2-3 hours  
**Why Valuable**: Prevents time zone and scheduling bugs

**Test Cases Needed**:
```python
class TestDateParsingAdvanced(unittest.TestCase):
    def test_midnight_rollover_scenarios(self):
        # Parsing "02:30" when current time is 23:45
        # Date boundary edge cases
        # Daylight saving time transitions
        
    def test_malformed_time_inputs(self):
        # Invalid formats from website changes
        # Empty strings, 'N/A', 'TBD'
        # Should not crash parser
        
    def test_timezone_edge_cases(self):
        # America/Toronto timezone handling
        # Daylight saving time transitions
        # Year boundary crossings
```

#### 6. Construction Closure Parsing Tests
**File**: `scraper.py` - Lines 97-136  
**Estimated Time**: 2-3 hours  
**Why Valuable**: Safety-critical information parsing

**Test Cases Needed**:
```python
class TestConstructionClosures(unittest.TestCase):
    def test_date_range_parsing(self):
        # 'Jan 15, 2024 - Jan 17, 2024, 09:00 - 15:00'
        # Single day: 'Jan 15, 2024, 09:00 - 15:00'
        # Different date formats
        
    def test_bridge_number_matching(self):
        # 'Bridge 4 Closure' → match to BRIDGE_DETAILS
        # 'Bridge 3A Closure' → handle alphanumeric
        # Multiple bridges in one closure notice
        
    def test_invalid_construction_data(self):
        # Malformed date strings
        # Missing time ranges
        # Should not crash regex parser
```

---

## 📊 Priority 4: Data Structure & Integration (Week 4)

#### 7. Firestore Data Structure Validation
**File**: `scraper.py` - Lines 347-410  
**Estimated Time**: 2 hours  
**Why Valuable**: Ensures iOS app compatibility

**Test Cases Needed**:
```python
class TestFirestoreDataStructure(unittest.TestCase):
    def test_complete_document_structure(self):
        # Required fields: name, region, region_short, coordinates, live
        # Live fields: available, raw_status, status, upcoming_closures
        # Statistics fields: All the values you listed above
        
    def test_coordinate_formatting(self):
        # firestore.GeoPoint format
        # Latitude/longitude ranges
        # Precision handling
        
    def test_upcoming_closures_array(self):
        # Closure object structure
        # Type, time, longer, end_time fields
        # Array format consistency
```

#### 8. History Document ID Generation
**File**: `scraper.py` - Lines 331-339  
**Estimated Time**: 1 hour  
**Why Valuable**: Prevents data loss from ID collisions

**Test Cases Needed**:
```python
class TestHistoryDocumentIDs(unittest.TestCase):
    def test_id_uniqueness(self):
        # Generate 100+ IDs at same timestamp
        # Ensure all are unique
        # Random component working properly
        
    def test_id_format_consistency(self):
        # 'Jul15-1325-abcd' format
        # Date formatting consistency
        # Random string length/format
```

---

## 🛠️ Implementation Strategy

### Phase 1: Critical Protection (Week 1)
**Focus**: Statistics calculation and status interpretation  
**Impact**: Protects core app intelligence  
**Files**: `test_statistics.py`, extend `test_parsers.py`

### Phase 2: Data Validation (Week 2)  
**Focus**: Configuration and sanitization  
**Impact**: Prevents deployment errors  
**Files**: `test_configuration.py`, `test_data_validation.py`

### Phase 3: Edge Cases (Week 3)
**Focus**: Advanced parsing and error handling  
**Impact**: Handles unusual scenarios gracefully  
**Files**: `test_edge_cases.py`

### Phase 4: Integration (Week 4)
**Focus**: Data structure and ID generation  
**Impact**: Maintains iOS app compatibility  
**Files**: `test_integration.py`

---

## 📝 Test Organization

### File Structure
```
test_parsers.py          # ✅ COMPLETED - Basic parsing
test_statistics.py       # 🔥 Priority 1 - Stats calculation
test_status_logic.py     # 🔥 Priority 1 - Status interpretation  
test_configuration.py    # 🔧 Priority 2 - Config validation
test_data_validation.py  # 🔧 Priority 2 - Sanitization
test_edge_cases.py       # ⚠️ Priority 3 - Advanced parsing
test_integration.py      # 📊 Priority 4 - Data structures
```

### Running Tests
```bash
# Run all tests
python3 test_parsers.py && python3 test_statistics.py && python3 test_status_logic.py

# Run specific priority level
python3 test_statistics.py  # Priority 1
python3 test_configuration.py  # Priority 2
```

---

## 🎯 Expected Benefits

- **Catch Silent Failures**: Status interpretation bugs from website changes
- **Protect Statistics**: Math errors that would break iOS predictions  
- **Validate Configuration**: Deployment errors caught early
- **Handle Edge Cases**: Unusual scenarios don't crash the system
- **Maintain Compatibility**: iOS app continues working through changes

---

## 📈 Success Metrics

- **Coverage of Critical Logic**: Statistics calculation, status interpretation
- **Edge Case Protection**: Boundary conditions, malformed inputs
- **Configuration Safety**: All deployment scenarios validated
- **Fast Execution**: All tests run in <10 seconds total
- **Zero Production Impact**: Tests don't affect deployment or runtime

---

**Remember**: These tests are purely for development confidence. They have ZERO impact on production deployment or runtime performance.