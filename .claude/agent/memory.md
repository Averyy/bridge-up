# Private Memory - Sage (Backend Development Agent)

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
  - Created `test_parsers.py` for core parsing logic
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
- Dual parser system (old/new website formats)
- Status normalization for iOS app compatibility
