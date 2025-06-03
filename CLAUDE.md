# Bridge Up Backend - Claude Guidelines

## Project Overview
This is the Python backend for Bridge Up - a bridge monitoring system that scrapes real-time bridge status data from St. Lawrence Seaway websites and provides it to the iOS app via Firebase Firestore.

**Key Context**: This backend is the **authoritative data source** for the iOS app. It scrapes, processes, and stores all bridge status information.

## Critical Rules - DO NOT VIOLATE

- **ALWAYS run tests before committing or deploying** - use `python run_tests.py`
- **NEVER create mock data or simplified components** unless explicitly told to do so
- **NEVER replace existing complex components with simplified versions** - always fix the actual problem
- **ALWAYS work with the existing codebase** - do not create new simplified alternatives
- **ALWAYS find and fix the root cause** of issues instead of creating workarounds
- **NEVER change the Firebase document structure** without coordinating with iOS app
- **ALWAYS preserve the data processing algorithms** - they're core to the predictions
- **NEVER break the scheduling system** - it's critical for real-time updates
- **Respect scraping ethics** - don't aggressively scrape or you'll get IP blocked
- When debugging issues, focus on fixing the existing implementation, not replacing it
- When something doesn't work, debug and fix it - don't start over with a simple version

## Architecture Overview
```
St. Lawrence Seaway Websites → Python Scraper → Data Processing → Firebase Firestore → iOS App
```

## Core Files
- `scraper.py` - Main bridge data scraping and Firebase integration
- `stats_calculator.py` - Historical analysis and predictive statistics  
- `config.py` - Bridge URLs, coordinates, and configuration
- `start_flask.py` - Development server with APScheduler
- `start_waitress.py` - Production server setup
- `app.py` - Basic Flask app (minimal, mainly for health checks)

## Python Development Standards

- Use Python 3.9+ with type hints for all functions
- Follow PEP 8 style guidelines with proper docstrings
- Use Loguru for logging (already configured in scraper.py)
- Always validate scraped data before processing
- Implement proper error handling for network requests
- **CRITICAL**: Always use timeouts on requests (10s default)
- **CRITICAL**: Use ThreadPoolExecutor for concurrent scraping (not asyncio)
- **CRITICAL**: Protect shared state with threading.Lock() when using concurrent execution
- Optimize for reliability and cost efficiency
- Design for Docker deployment

## Statistics Calculation
- **Location**: `stats_calculator.py` → `calculate_bridge_statistics()`
- **Trigger**: Daily at 3AM (prod) / 4AM (dev) via APScheduler
- **Process**: Python calculates ALL statistics (not Firebase Functions)
- **Key Fields**: average_closure_duration, closure_ci, closure_durations buckets
- **Testing**: Run `python run_tests.py` to verify calculations

## Firebase Integration Rules

- **CRITICAL**: Backend is the authoritative data source
- **Never change document schema** without coordinating with iOS team
- **Preserve all existing fields** that iOS app expects
- **Real-time updates only on actual status changes** to minimize costs
- **Batch statistical updates** during daily recalculation
- **Handle Firebase errors gracefully** with retry logic
- **Cost optimization**: Only write when data actually changes
- **Minimize reads and listeners** To keep costs down only do this when necessary to get up to date data

## Bridge Status Mapping (DO NOT CHANGE)

The status mapping is implemented in `interpret_bridge_status()` function in `scraper.py`:

```python
# Status normalization logic:
# - "Available" → "Open"
# - "Available (raising soon)" → "Closing soon"
# - "Unavailable" → "Closed"
# - "Unavailable (lowering)" → "Opening"
# - "Unavailable (raising)" → "Closing"
# - "Unavailable (work in progress)" → "Construction"
# - All other statuses → "Unknown"

# Final statuses written to Firebase:
# "Open", "Closed", "Closing soon", "Opening", "Construction", "Unknown"
```

## Monitored Bridges
- **SCT (St. Catharines)**: Highway 20, Glendale Ave, Queenston St, Lakeshore Rd, Carlton St
- **PC (Port Colborne)**: Clarence St, Main St, Mellanby Ave
- **MSS (Montreal South Shore)**: Victoria Bridge variants, Sainte-Catherine
- **SBS (Salaberry/Beauharnois)**: Various bridges in the region

## Scraping Ethics & Requirements

- **Respect rate limits**: Current 30-60 second intervals are already aggressive
- **Use random User-Agent headers** to avoid automated detection
- **Handle failures gracefully** - temporary site issues should not crash the system
- **Monitor for IP blocking** and implement backoff strategies
- **Log scraping activities** for debugging and monitoring
- **Never exceed current scraping frequency** without explicit approval

## Firebase Document Schema (DO NOT MODIFY)

```python
{
    "name": str,                    # "Queenston St"
    "coordinates": GeoPoint,        # Latitude/longitude
    "region": str,                  # "St. Catharines"  
    "region_short": str,            # "SCT"
    "statistics": {
        "average_closure_duration": int,
        "closure_ci": {"lower": int, "upper": int},
        "average_raising_soon": int,
        "raising_soon_ci": {"lower": int, "upper": int},
        "closure_durations": {
            "under_9m": int, "10_15m": int, "16_30m": int,
            "31_60m": int, "over_60m": int
        },
        "total_entries": int
    },
    "live": {
        "status": str,              # Bridge status from STATUS_MAPPING
        "last_updated": timestamp,
        "upcoming_closures": [...]  # Array of closure objects
    }
}
```

## Scheduling System Rules

- Maintain existing APScheduler setup in `start_flask.py` and `start_waitress.py`
- Preserve day/night interval differences (30s vs 60s)
- Keep 4 AM daily statistics recalculation
- Handle timezone correctly for schedule reliability
- Implement proper shutdown of schedulers
- Log all scheduled task execution

## Statistical Analysis Rules

- Preserve confidence interval calculations in `stats_calculator.py`
- Maintain rolling 300-entry history for each bridge
- Keep closure duration categorization (under_9m, 10_15m, etc.)
- Preserve "closing soon" timing analysis
- Calculate averages correctly for iOS app predictions
- Handle edge cases (no historical data, all same duration)

## Development Workflow

**⚠️ CRITICAL: Always run tests before committing or deploying!**

```bash
# 1. Make your changes
# 2. Run tests (REQUIRED)
python run_tests.py

# 3. If tests pass, run development server
python start_flask.py

# Other commands:
python start_waitress.py  # Production server
python scraper.py         # Test scraper manually
```

**Never deploy without running tests first!**

## Testing Requirements

**⚠️ Tests are MANDATORY before deployment!**

```bash
# Always run before committing/deploying
python run_tests.py
```

Implemented tests cover:
- ✅ Core parsing logic (old/new HTML formats)
- ✅ Statistics calculations (predictions)
- ✅ Status interpretation (edge cases)
- ✅ Configuration validation

See `TESTING.md` for details. 

## Error Handling Standards

- **Network failures**: Retry with exponential backoff
- **Website changes**: Log parsing failures for manual review
- **Firebase errors**: Queue updates for retry, don't lose data
- **Resource limits**: Handle rate limiting gracefully
- **Unknown status**: Fall back to "unknown" status, don't crash
- **Missing data**: Use previous known state when appropriate

## Configuration Management

- Bridge URLs and coordinates defined in `config.py`
- Never hardcode scraping targets - use configuration
- Maintain regional groupings (SCT, PC, MSS, SBS)
- Preserve CSS selectors for each bridge website
- Environment-based configuration for Firebase credentials
- Configurable intervals in scheduler setup

## Performance & Cost Optimization

- **Minimize Firebase writes**: Only update when status actually changes
- **Efficient queries**: Use targeted document updates
- **Smart caching**: Avoid redundant scraping when status unchanged
- **Resource management**: Proper connection pooling and cleanup
- **Memory usage**: Handle large historical datasets efficiently
- **Cost monitoring**: Track Firebase operations for optimization

## Cross-Platform Awareness

While focusing on backend work, be aware that:
- iOS app is **read-only** - never writes to Firebase
- iOS app expects specific document schema and field names
- Real-time listeners on iOS depend on consistent document updates
- Statistical data is used for predictive UI in iOS app
- Any schema changes require coordination with iOS team

## Code Quality Checklist

- [ ] **TESTS PASS** - `python run_tests.py` shows all green
- [ ] Type hints added to all functions
- [ ] Docstrings for all classes and public methods
- [ ] Error handling for all network requests
- [ ] Logging instead of print statements
- [ ] No hardcoded values or credentials
- [ ] Tests written/updated for changes
- [ ] Firebase document structure validated
- [ ] Statistical calculations verified
- [ ] Scraping ethics respected (rate limits, etc.)
- [ ] Docker deployment considerations

## Recent Critical Fixes (June 2025)

### 1. APScheduler Stalling Issue
**Solved**: "maximum number of running instances reached"
- Added request timeouts (10s) + retry logic (3 attempts)
- Configured APScheduler with `max_instances=3`, `coalesce=True`
- Implemented concurrent scraping → 50x performance improvement

### 2. Production Reliability Improvements
**Implemented**: Thread safety, smart backoff, and status bug fix
- Added thread locks for `last_known_state` dictionary (prevents race conditions)
- Implemented exponential backoff for failed regions (2s → 300s cap, never gives up)
- Fixed status bug: garbage data now returns "Unknown" instead of "Closed"
- Replaced print() with Loguru for structured logging
- **Always maintain these fixes when modifying scraping code**