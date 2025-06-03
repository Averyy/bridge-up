# Bridge Up Backend Improvements TODO

## Overview
Simple, pragmatic improvements for production reliability. Total implementation time: ~1 hour.

## 1. Fix Docker Logs Not Updating ⚠️

### Why:
- Python buffers output in Docker containers
- Logs get "stuck" and don't show in `docker logs`
- Makes debugging production issues impossible

### Task:
- [ ] Set PYTHONUNBUFFERED=1 environment variable in Dockerfile

### Implementation:

**Add to Dockerfile:**
```dockerfile
# Add this line anywhere in your Dockerfile (typically near the top)
ENV PYTHONUNBUFFERED=1
```

**Why this approach:**
- Standard Docker + Python best practice
- Works for all Python processes in the container
- No deployment configuration changes needed
- Just rebuild and redeploy the image

## 2. Replace print() with Loguru + Cleaner Logs

### Why:
- See what's happening in production via `docker logs`
- **Loguru auto-flushes, solving the buffering issue!**
- Make logs shorter and easier to read
- Add colors for local development

### Tasks:
- [ ] Install loguru: Add `loguru` to requirements.txt
- [ ] Import logger at top of scraper.py: `from loguru import logger`
- [ ] Replace verbose prints with concise logs
- [ ] Remove repetitive "Scrape and update completed successfully" messages
- [ ] Consolidate multi-line outputs into single lines
- [ ] Test that logs show up in `docker logs`

### Implementation:
```python
# scraper.py (at top)
from loguru import logger

# Configure for cleaner output
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    enqueue=False,    # Ensures immediate output in Docker logs
    colorize=False    # Disable colors for Docker (containers don't support ANSI colors)
)

# BEFORE (verbose):
print(f"Starting scrape_and_update at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"SUCCESS: {info['region']} ({len(bridges)} bridges)")
print(f"Completed scrape_and_update in {duration:.2f} seconds")
print(f"Scrape and update completed successfully at {datetime.now(TIMEZONE).strftime('%I:%M:%S%p').lower()}")

# AFTER (concise):
logger.info("Scraping...")
logger.info(f"✓ {info['region']}: {len(bridges)}")  # St Catharines: 5
logger.info(f"Done in {duration:.1f}s - All: {success_count} ✓, {fail_count} ✗")

# Example output:
# 09:21:30 | INFO     | Scraping...
# 09:21:30 | INFO     | ✓ St Catharines: 5
# 09:21:30 | INFO     | ✓ Port Colborne: 3
# 09:21:30 | INFO     | ✓ Montreal South Shore: 3
# 09:21:30 | INFO     | ✓ Salaberry / Beauharnois / Suroît Region: 2
# 09:21:31 | INFO     | Done in 0.5s - All: 4 ✓, 0 ✗

# For errors (only log actual problems):
logger.error(f"✗ {region}: {str(e)[:50]}...")  # Truncate long errors
logger.warning(f"⚠ {region}: No data")

# Remove these entirely (too verbose):
# - "Scrape and update completed successfully"
# - "Starting scrape_and_update at [timestamp]" (timestamp already in log)
# - Individual "SUCCESS" prefix (use ✓ instead)
```

## 3. Add Smart Backoff That Never Gives Up

### Why:
- Prevent hammering sites that are down
- Avoid getting IP banned
- Keep trying forever since sites will come back
- Handle both connection errors and bad data the same way

### Tasks:
- [ ] Add thread-safe dictionary to track failures and next retry time per URL
- [ ] Implement exponential backoff (2, 4, 8, 16, 32, 64... up to 300s)
- [ ] Reset failure count on successful scrape
- [ ] Never stop trying - just increase intervals
- [ ] Fix existing thread safety issues in last_known_state

### ⚠️ CRITICAL: Thread Safety Requirements
Since you're using `ThreadPoolExecutor(max_workers=4)`, ALL shared state must be protected with locks:
- **Existing issue**: `last_known_state` dictionary is NOT thread-safe
- **New shared state**: `region_failures` and `region_status` need protection
- **Use simple threading.Lock()** - RLock not needed for this use case

### Implementation:
```python
# scraper.py
from loguru import logger
from datetime import datetime, timedelta
import threading

# Add at module level - WITH THREAD SAFETY
region_failures = {}  # url -> (failure_count, next_retry_time)
region_failures_lock = threading.Lock()

# FIX EXISTING THREAD SAFETY ISSUE
last_known_state_lock = threading.Lock()  # Add this for existing global dict

def process_single_region(url_info_pair):
    """Process a single region with smart backoff that never gives up"""
    url, info = url_info_pair
    region = info['region']
    
    # Check if we're still in backoff period - THREAD SAFE
    with region_failures_lock:
        if url in region_failures:
            failure_count, next_retry = region_failures[url]
            if datetime.now() < next_retry:
                wait_seconds = (next_retry - datetime.now()).total_seconds()
                logger.info(f"⏳ {region}: Still waiting {wait_seconds:.0f}s (attempt #{failure_count})")
                return f"WAITING: {region}"
    
    try:
        bridges = scrape_bridge_data(url)
        if bridges:
            update_firestore(bridges, info['region'], info['shortform'])
            
            # Success - reset failure count - THREAD SAFE
            with region_failures_lock:
                if url in region_failures:
                    failure_count = region_failures[url][0]
                    logger.info(f"✓ {region}: {len(bridges)} (recovered after {failure_count} failures)")
                    del region_failures[url]  # Clear failures
                else:
                    logger.info(f"✓ {region}: {len(bridges)}")
            
            return f"SUCCESS: {region}"
        else:
            # Empty response counts as failure
            handle_region_failure(url, region, "No data")
            return f"FAILED: {region}"
            
    except Exception as e:
        handle_region_failure(url, region, str(e)[:30] + "...")
        return f"ERROR: {region}"

def handle_region_failure(url, region, error_msg):
    """Update failure tracking with next retry time - THREAD SAFE"""
    with region_failures_lock:
        failure_count = region_failures.get(url, (0, None))[0] + 1
        
        # Calculate next retry time (exponential backoff, max 5 minutes)
        wait_seconds = min(2 ** failure_count, 300)
        next_retry = datetime.now() + timedelta(seconds=wait_seconds)
        
        region_failures[url] = (failure_count, next_retry)
    
    if failure_count == 1:
        logger.error(f"✗ {region}: {error_msg}")
    else:
        logger.error(f"✗ {region}: {error_msg} (attempt #{failure_count}, retry in {wait_seconds}s)")
```

## Example of How It Works

### Extended Outage (Never Gives Up):
```
09:22:00 | INFO     | Scraping...
09:22:00 | ERROR    | ✗ Port Colborne: Connection timeout...
09:22:00 | INFO     | Done in 1.2s - All: 3 ✓, 1 ✗

[Next scrape - 2s backoff]
09:22:30 | INFO     | ⏳ Port Colborne: Still waiting 1s (attempt #1)

[Next scrape - 4s backoff]
09:23:00 | ERROR    | ✗ Port Colborne: Connection timeout... (attempt #2, retry in 4s)

[Continues with exponential backoff: 8s, 16s, 32s, 64s, 128s, then caps at 300s]

[Much later - still trying every 5 minutes]
10:45:00 | INFO     | ⏳ Port Colborne: Still waiting 180s (attempt #45)

[When it finally recovers]
10:48:00 | INFO     | ✓ Port Colborne: 3 (recovered after 45 failures)

[Back to normal - failure count reset!]
10:48:30 | INFO     | ✓ Port Colborne: 3
```


## 4. Fix Existing Thread Safety Issue in last_known_state ⚠️ CRITICAL (10 minutes)

### Why:
- `last_known_state` dictionary is accessed by multiple threads without locks
- Can cause race conditions, lost updates, or crashes
- Already affects production code - not just new features

### Implementation:
```python
# In scraper.py, at the top with other globals:
import threading

# After the existing globals
last_known_state_lock = threading.Lock()

# In update_firestore() function, wrap ALL access to last_known_state:

# BEFORE (line ~394):
if not force_update and bridge_ref.id in last_known_state:
    if last_known_state[bridge_ref.id] == doc_data:
        skipped_count += 1
        continue

# AFTER (thread-safe):
with last_known_state_lock:
    if not force_update and bridge_ref.id in last_known_state:
        if last_known_state[bridge_ref.id] == doc_data:
            skipped_count += 1
            continue

# BEFORE (line ~410):
last_known_state[bridge_ref.id] = doc_data

# AFTER (thread-safe):
with last_known_state_lock:
    last_known_state[bridge_ref.id] = doc_data

# Similarly for last_known_open_times - though TTLCache is mostly thread-safe,
# the pattern of checking then setting should still be protected
```

### Thread Safety Best Practices Applied:

1. **Use `threading.Lock()` not `RLock`** - No recursive locking needed here
2. **Keep critical sections small** - Only lock during dictionary access
3. **Use context managers** - `with lock:` ensures proper release
4. **Snapshot pattern for reads** - Copy data under lock, process outside
5. **No nested locks** - Avoids deadlock risks

## Testing Plan

### 1. Test Logging
- [ ] Run locally and check console output is cleaner
- [ ] Run in Docker and check `docker logs` updates in real-time
- [ ] Verify errors are logged properly

### 2. Test Backoff
- [ ] Temporarily break one URL in config.py
- [ ] Watch logs to see exponential backoff (2s, 4s, 8s...)
- [ ] Verify it caps at 5 minutes
- [ ] Let it run for 30+ minutes to ensure it never gives up
- [ ] Fix URL and confirm recovery message + failure count reset

### 3. Add Critical Unit Tests (REQUIRED before production)

#### A. Test Status Bug Fix (5 minutes)
Add to `tests/test_status_edge_cases.py`:
```python
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
```

#### B. Test Thread Safety (10 minutes)
Create new file `tests/test_thread_safety.py`:
```python
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
```

### 4. Manual Thread Safety Verification
- [ ] Start the app
- [ ] Run 4 concurrent curl requests: `for i in {1..4}; do curl http://localhost:5000/health & done`
- [ ] Verify no crashes or errors in logs
- [ ] Check that all requests complete successfully

## Success Criteria

- ✅ Docker logs update in real-time (no buffering)
- ✅ Logs are 50% shorter and easier to scan
- ✅ Can identify issues at a glance (✓ ✗ ⚠ ⏳)
- ✅ Failed regions don't block working ones
- ✅ Backoff never gives up, just waits longer
- ✅ Failure counts reset on successful scrape
- ✅ **NO RACE CONDITIONS** - All shared state properly locked
- ✅ Thread-safe implementation verified with concurrent testing
- ✅ **All tests pass**: `python run_tests.py` shows green (including new tests)
- ✅ **Status bug test passes**: Garbage data returns "Unknown" not "Closed"
- ✅ Total implementation time < 1.5 hours (including tests)

## 5. Fix Status Mismatch Bug - Garbage Data Shows as "Closed"

### Bug Summary
When the website returns unrecognized/garbage data, the backend defaults to "Closed" instead of "Unknown", causing false closure predictions in the iOS app.

### Root Cause
**Location**: `scraper.py`, line 234

When we can't determine the bridge status from the website data, we default to "Closed" instead of "Unknown".

### The Simple Fix
Change line 234 from:
```python
status = "Closed"  # ❌ Wrong default
```
To:
```python
status = "Unknown"  # ✅ Correct default for unrecognized data
```

### Why This Happens
Normal website statuses always contain "Available" or "Unavailable":
- "Available" → Open
- "Unavailable" → Closed
- "Data unavailable" → Unknown (special case)

But when the website returns garbage (server errors, maintenance pages, etc.) that contains neither word, we currently default to "Closed" when we should default to "Unknown".

### Impact
- Users see false "Bridge Closed" with opening predictions
- Should show "?" icon with "Unknown" status instead

### Testing
After making the fix, test with garbage data:
- Empty string → Should show "Unknown"
- "Server Error" → Should show "Unknown"  
- "Maintenance Mode" → Should show "Unknown"
- Any unrecognized text → Should show "Unknown"

---

## ✅ IMPLEMENTATION COMPLETE - June 3, 2025

All improvements have been successfully implemented and tested:

1. **Docker Logging** - Added `PYTHONUNBUFFERED=1` to Dockerfile
2. **Loguru Integration** - Clean, concise logs with immediate output
3. **Smart Backoff** - Exponential retry (2s → 300s cap) that never gives up
4. **Thread Safety** - Added locks to prevent race conditions
5. **Status Bug Fixed** - Garbage data now correctly returns "Unknown"

**Test Coverage Added:**
- `test_thread_safety.py` - Verifies concurrent access safety
- `test_backoff.py` - Tests exponential backoff calculations
- `test_network_backoff.py` - Tests network failure handling
- `test_logging.py` - Verifies logger configuration
- Updated `test_status_edge_cases.py` with garbage data test

All tests pass. Production ready. 🚀