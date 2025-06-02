# Bridge Up Backend Improvements TODO

## Overview
Simple, pragmatic improvements for production reliability. Total implementation time: ~1 hour.

### ⚠️ CRITICAL DISCOVERY: Thread Safety Issues
Your code uses `ThreadPoolExecutor(max_workers=4)` but has **NO thread safety** on shared state:
- **Existing bug**: `last_known_state` dictionary can corrupt/crash under concurrent access
- **New features**: Must add proper locking to avoid same issues
- **Solution**: Use `threading.Lock()` for all shared state access

## 0. Fix Docker Logs Not Updating ⚠️ URGENT (2 minutes)

### Why:
- Python buffers output in Docker containers
- Logs get "stuck" and don't show in `docker logs`
- Makes debugging production issues impossible

### Tasks:
- [ ] Add `-u` flag to Python in Dockerfile OR
- [ ] Set PYTHONUNBUFFERED=1 environment variable OR
- [ ] Force flush after each print

### Implementation (Choose ONE):

**Option 1 - Dockerfile (Recommended):**
```dockerfile
# In your Dockerfile, change:
CMD ["python", "start_waitress.py"]
# To:
CMD ["python", "-u", "start_waitress.py"]
```

**Option 2 - Environment Variable:**
```dockerfile
# Add to Dockerfile:
ENV PYTHONUNBUFFERED=1
```

**Option 3 - Force Flush (if not using Docker):**
```python
# After each print statement add:
print("Something happened")
sys.stdout.flush()  # Forces output immediately
```

## 1. Replace print() with Loguru + Cleaner Logs ✅ High Priority (30 minutes)

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
    level="INFO"
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

### Clean Log Format:
```python
# Production (JSON for parsing):
if os.getenv('JSON_LOGS', '').lower() == 'true':
    logger.add(sys.stderr, serialize=True, level="INFO")
else:
    # Development (colored and clean):
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
```

## 2. Add Health Check with Region Status ✅ High Priority (10 minutes)

### Why:
- Monitor if your backend is alive
- See which specific regions are working/failing
- Required for uptime monitoring services

### Tasks:
- [ ] Add global variables to track last scrape time and region status
- [ ] Update region status after each scrape attempt
- [ ] Add /health endpoint to app.py
- [ ] Return detailed status for each region

### Implementation:
```python
# app.py
from flask import Flask, jsonify
from datetime import datetime
import threading

app = Flask(__name__)

# Add these globals - WITH THREAD SAFETY
last_scrape_time = None
last_scrape_time_lock = threading.Lock()

region_status = {}  # region -> {'status': 'ok'/'failing', 'last_success': timestamp, 'failure_count': n}
region_status_lock = threading.Lock()

@app.route('/')
def home():
    return "Bridge Up Backend is running!", 200

@app.route('/health')
def health_check():
    # Create snapshot of current state to minimize lock time
    with region_status_lock:
        status_snapshot = dict(region_status)
    
    with last_scrape_time_lock:
        scrape_time_snapshot = last_scrape_time
    
    if not status_snapshot:
        return jsonify({
            "status": "starting",
            "message": "No data yet - backend is starting up"
        })
    
    # Process snapshot outside of locks
    healthy_regions = sum(1 for r in status_snapshot.values() if r['status'] == 'ok')
    total_regions = len(status_snapshot)
    
    # Simple status determination
    if healthy_regions == total_regions:
        overall_status = "healthy"
    elif healthy_regions == 0:
        overall_status = "down"
    else:
        overall_status = "degraded"
    
    return jsonify({
        "status": overall_status,
        "healthy_regions": f"{healthy_regions}/{total_regions}",
        "last_scrape": scrape_time_snapshot.isoformat() if scrape_time_snapshot else None,
        "regions": {
            name: {
                "status": info['status'],
                "last_success": info['last_success'].isoformat() if info['last_success'] else None,
                "failure_count": info['failure_count']
            }
            for name, info in status_snapshot.items()
        }
    })

# In scraper.py, add this function:
def update_region_status(region, success, failure_count=0):
    """Update health check status for a region - THREAD SAFE"""
    from app import region_status, region_status_lock  # Import from app.py
    
    with region_status_lock:
        if region not in region_status:
            region_status[region] = {
                'status': 'unknown',
                'last_success': None,
                'failure_count': 0
            }
        
        if success:
            region_status[region] = {
                'status': 'ok',
                'last_success': datetime.now(TIMEZONE),
                'failure_count': 0  # Reset on success!
            }
        else:
            region_status[region]['status'] = 'failing'
            region_status[region]['failure_count'] = failure_count
```

## 3. Add Smart Backoff That Never Gives Up ✅ High Priority (20 minutes)

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
                update_region_status(region, False, failure_count)  # Update health check
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
            
            update_region_status(region, True)  # Update health check - resets failure count!
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
    
    update_region_status(region, False, failure_count)  # Update health check
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

### Health Check During Outage:
```json
{
  "status": "degraded",
  "healthy_regions": "3/4",
  "last_scrape": "2025-06-02T10:45:00.123456",
  "regions": {
    "Port Colborne": {
      "status": "failing",
      "last_success": "2025-06-02T09:22:00.123456",
      "failure_count": 45
    },
    // ... other regions with status "ok"
  }
}
```

### After Recovery:
```json
{
  "status": "healthy",
  "healthy_regions": "4/4",
  "last_scrape": "2025-06-02T10:48:00.123456",
  "regions": {
    "Port Colborne": {
      "status": "ok",
      "last_success": "2025-06-02T10:48:00.123456",
      "failure_count": 0  // Reset!
    },
    // ... other regions
  }
}
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

### 2. Test Health Check
- [ ] Hit http://localhost:5000/health
- [ ] Check it shows region-specific status
- [ ] Verify failure counts increment and reset properly

### 3. Test Backoff
- [ ] Temporarily break one URL in config.py
- [ ] Watch logs to see exponential backoff (2s, 4s, 8s...)
- [ ] Verify it caps at 5 minutes
- [ ] Let it run for 30+ minutes to ensure it never gives up
- [ ] Fix URL and confirm recovery message + failure count reset

## Success Criteria

- [ ] Docker logs update in real-time (no buffering)
- [ ] Logs are 50% shorter and easier to scan
- [ ] Can identify issues at a glance (✓ ✗ ⚠ ⏳)
- [ ] Health check shows per-region status
- [ ] Failed regions don't block working ones
- [ ] Backoff never gives up, just waits longer
- [ ] Failure counts reset on successful scrape
- [ ] **NO RACE CONDITIONS** - All shared state properly locked
- [ ] Thread-safe implementation verified with concurrent testing
- [ ] Total implementation time < 1 hour (including thread safety fixes)

## Future Improvements (When You Need Them)

- Structured JSON logging (when you add log aggregation)
- Detailed metrics (when you have performance issues)  
- Request tracing (when you have complex debugging needs)
- Multiple health check endpoints (when you have microservices)

But for now, **ship it!** 🚀

## 5. Fix Status Mismatch Bug - Garbage Data Shows as "Closed" ⚠️ CRITICAL (5 minutes)

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