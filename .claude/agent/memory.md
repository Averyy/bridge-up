# Private Memory - Sage (Backend Development Agent)

## CRITICAL USER PREFERENCE - NEVER VIOLATE
**NEVER add "Generated with Claude Code" or "Co-Authored-By: Claude" to commit messages.**
The user pays for this service. Do not take credit. Commit messages should contain ONLY the user's requested content.

## Session: June 1, 2025 - Major Backend Fixes & Performance Improvements

### Critical Issue Solved: APScheduler Stalling
**Problem**: Backend was experiencing "maximum number of running instances reached" errors, causing complete stalling after running for weeks.

**Root Cause**: 
- `requests.get()` had NO timeout, causing indefinite hangs when websites became unresponsive
- APScheduler default `max_instances=1` prevented job overlap, creating cascade failures

**Solution Implemented**:
1. Added 10-second timeout + 3 retries to all HTTP requests
2. Set APScheduler `max_instances=3`, `coalesce=True` 
3. Implemented concurrent scraping with ThreadPoolExecutor
4. Result: 50x performance improvement (40s → 0.7s)

### Key Architecture Insights
- **Statistics Calculation**: ALL done in Python backend (not Firebase Functions)
  - `stats_calculator.py` → `calculate_bridge_statistics()`
  - Runs daily at 3AM (production) / 4AM (dev)
  - Calculates: averages, confidence intervals, duration buckets
  - MAX_HISTORY_ENTRIES = 300 enforced here
  
- **Testing Philosophy**: "Guardrails, Not Roadblocks"
  - No existing tests in project (startup velocity focus)
  - Created `tests/test_parsers.py` for core parsing logic
  - Created comprehensive `TODO-Testing.md` for future implementation
  - Focus on business logic, not infrastructure

### Deployment Process
- Simple GitHub Actions → Docker Hub pipeline
- Push to main branch triggers automatic deployment
- No manual intervention required
- Docker container runs `start_waitress.py` in production

### Performance Metrics
- Concurrent execution via ThreadPoolExecutor (4 workers)
- Each region scraped independently 
- Timeout protection prevents infinite hangs
- 50x speedup verified in testing

### Critical Code Patterns
- Firebase writes only on actual status changes (cost optimization)
- In-memory caching with `last_known_state` dictionary
- Dual parser system (old/new JSON API formats with smart caching)
- Status normalization for iOS app compatibility

## Session: December 2025 - Comprehensive Test Suite Implementation

### Test Suite Created
**Purpose**: Protect against regressions when updating/changing code

**Implemented Tests**:
1. `tests/test_parsers.py` - Core JSON parsing (20+ tests)
2. `tests/test_statistics.py` - Prediction calculations (9 tests)  
3. `tests/test_status_edge_cases.py` - Status interpretation (7 tests)
4. `tests/test_configuration.py` - Config validation (5 tests)
5. `run_tests.py` - One-command test runner

**Key Testing Principle**: Test BOTH core functionality AND edge cases
- Core: Happy path that must always work
- Edge: Realistic scenarios we've seen

**CRITICAL WORKFLOW CHANGE**:
```bash
# ALWAYS run before committing/deploying:
python run_tests.py
```

Tests take <1 second - no excuse to skip them!

## Session: June 2, 2025 - Thread Safety Analysis & Production Improvements

### Critical Discovery: Thread Safety Vulnerability
**Problem**: Identified existing race condition bug in production code
- `ThreadPoolExecutor(max_workers=4)` with NO thread protection on shared state
- `last_known_state` dictionary accessed by multiple threads simultaneously
- **Risk**: Data corruption, KeyError crashes, lost bridge status updates

**Impact Assessment**: 
- Current bug could cause random production crashes
- Race conditions are intermittent and hard to debug
- Problem exists NOW, not just in proposed features

### Thread Safety Research & Best Practices
**Key Learning**: Python's GIL does NOT eliminate race conditions
- Dictionary operations can be interrupted mid-execution
- Check-then-update patterns are particularly vulnerable
- Simple `threading.Lock()` with context managers is the correct solution

**Best Practice Pattern**:
```python
# Thread-safe shared state access
with state_lock:
    if key in shared_dict:
        shared_dict[key] = new_value
```

**Performance Impact**: Lock overhead ~0.0002ms vs network requests ~1000ms (negligible)

### Production Reliability Improvements Planned
**TODO Items Validated**: 
1. Fix Docker log buffering (2 min) - Critical for debugging
2. Replace print() with Loguru (30 min) - Better visibility  
3. Add health check endpoint (10 min) - Monitor region status
4. Implement smart backoff (20 min) - Prevent IP banning
5. Fix thread safety bugs (10 min) - Prevent crashes

**Total Implementation**: ~1.2 hours for significant reliability improvements

### Architecture Insights
- Health endpoints should read from in-memory state (no Firestore ops)
- Exponential backoff should "never give up" since sites will recover
- Thread safety fixes have ZERO impact on Firestore operations
- All improvements are infrastructure-layer, not business logic changes

### Key Principle Confirmed
**"Guardrails, Not Roadblocks"** philosophy applies to thread safety:
- Add protection without changing core functionality
- Simple solutions over complex thread-safe data structures
- Test improvements don't break existing behavior

## Session: December 20, 2025 - JSON API Migration

### Major Change: HTML Scraping → JSON API
**Problem**: HTML scraping was fragile and broke when website changed format.

**Solution**: Migrated to direct JSON API consumption:
- Discovered two undocumented JSON endpoints (old and new formats)
- Implemented smart endpoint caching (auto-discovers which format each region uses)
- Removed BeautifulSoup/lxml dependencies
- Added python-dotenv for secure endpoint configuration

### Key Implementation Details
- **Endpoints stored in .env** (gitignored, never committed)
- **Smart caching**: First scrape discovers working endpoint, subsequent scrapes use cached choice
- **Dual parser system**: `parse_old_json()` for SCT/PC/MSS, `parse_new_json()` for SBS
- **Closure parsing**: Construction from `closureP` field, vessel arrivals from `bridgeLiftList`

### Schedule Change
- Daytime: 30s → 20s intervals
- Nighttime: 60s → 30s intervals

### Bug Fixed
- `daily_statistics_update()` wasn't committing stats when no history entries needed deletion

### Tests Added
- `test_construction_closure_parsing` - Verifies closureP regex parsing
- `test_bridge_lift_list_parsing` - Verifies vessel arrival parsing

### Files Modified
- `scraper.py` - Major refactor (JSON parsing, removed HTML)
- `config.py` - BRIDGE_URLS → BRIDGE_KEYS, loads endpoints from .env
- `requirements.txt` - Removed beautifulsoup4/lxml, added python-dotenv
- `start_flask.py`, `start_waitress.py` - Updated intervals
- Tests and documentation updated
