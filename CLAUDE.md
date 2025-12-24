# Bridge Up Backend - Claude Guidelines

## Project Overview
This is the Python backend for Bridge Up - a bridge monitoring system that scrapes real-time bridge status data from St. Lawrence Seaway websites and serves it via WebSocket and REST API.

**Key Context**: This backend is the **authoritative data source** for all clients (iOS, web). It scrapes, processes, calculates predictions, and serves all bridge status information.

## Architecture (Post-Migration December 2024)

```
St. Lawrence Seaway API -> Scraper -> JSON Files -> FastAPI -> WebSocket/REST -> iOS/Web Apps
```

**Key Components**:
- `main.py` - FastAPI app with WebSocket, scheduler, CORS
- `scraper.py` - Bridge data scraping and JSON updates
- `predictions.py` - Prediction logic (moved from iOS to backend)
- `stats_calculator.py` - Historical statistics calculation
- `shared.py` - Shared state module (avoids circular imports)
- `config.py` - Bridge configuration

**Data Storage**: JSON files in `data/` directory (no external database)
- `data/bridges.json` - Current bridge state
- `data/history/*.json` - Historical data per bridge

## Critical Rules - DO NOT VIOLATE

- **ALWAYS run tests before committing or deploying** - use `python run_tests.py`
- **NEVER create mock data or simplified components** unless explicitly told to do so
- **NEVER replace existing complex components with simplified versions** - always fix the actual problem
- **ALWAYS work with the existing codebase** - do not create new simplified alternatives
- **ALWAYS find and fix the root cause** of issues instead of creating workarounds
- **NEVER change the JSON schema** without coordinating with iOS app
- **ALWAYS preserve the data processing algorithms** - they're core to the predictions
- **NEVER break the scheduling system** - it's critical for real-time updates
- **Respect scraping ethics** - don't aggressively scrape or you'll get IP blocked
- When debugging issues, focus on fixing the existing implementation, not replacing it

## Python Development Standards

- Use Python 3.11+ with type hints for all functions
- Follow PEP 8 style guidelines with proper docstrings
- Use Loguru for logging (already configured in scraper.py)
- Always validate scraped data before processing
- Implement proper error handling for network requests
- **CRITICAL**: Always use timeouts on requests (10s default)
- **CRITICAL**: Use ThreadPoolExecutor for concurrent scraping
- **CRITICAL**: Protect shared state with threading.Lock()
- Optimize for reliability
- Design for Docker deployment

## API Endpoints

- `WS /ws` - WebSocket for real-time updates
- `GET /bridges` - HTTP fallback (same data as WebSocket)
- `GET /bridges/{id}` - Single bridge by ID
- `GET /health` - Health check with status info
- `GET /docs` - Auto-generated OpenAPI documentation

## JSON Schema (DO NOT MODIFY WITHOUT iOS COORDINATION)

```json
{
  "last_updated": "2025-12-24T15:30:00-05:00",
  "available_bridges": [
    {"id": "SCT_CarltonSt", "name": "Carlton St.", "region_short": "SCT", "region": "St Catharines"}
  ],
  "bridges": {
    "SCT_CarltonSt": {
      "static": {
        "name": "Carlton St.",
        "region": "St Catharines",
        "region_short": "SCT",
        "coordinates": {"lat": 43.19, "lng": -79.20},
        "statistics": {
          "average_closure_duration": 12,
          "closure_ci": {"lower": 8, "upper": 16},
          "average_raising_soon": 3,
          "raising_soon_ci": {"lower": 2, "upper": 5},
          "closure_durations": {"under_9m": 45, "10_15m": 30, "16_30m": 15, "31_60m": 8, "over_60m": 2},
          "total_entries": 287
        }
      },
      "live": {
        "status": "Closed",
        "last_updated": "2025-12-20T15:20:00-05:00",
        "predicted": {"lower": "2025-12-20T15:28:00-05:00", "upper": "2025-12-20T15:36:00-05:00"},
        "upcoming_closures": [...]
      }
    }
  }
}
```

## Bridge Status Mapping (DO NOT CHANGE)

```python
# Status normalization in interpret_bridge_status():
# - "Available" -> "Open"
# - "Available (raising soon)" -> "Closing soon"
# - "Unavailable" -> "Closed"
# - "Unavailable (lowering)" -> "Opening"
# - "Unavailable (raising)" -> "Closing"
# - "Unavailable (work in progress)" -> "Construction"
# - All other statuses -> "Unknown"
```

## Monitored Bridges
- **SCT (St. Catharines)**: Highway 20, Glendale Ave, Queenston St, Lakeshore Rd, Carlton St
- **PC (Port Colborne)**: Clarence St, Main St, Mellanby Ave
- **MSS (Montreal South Shore)**: Victoria Bridge variants, Sainte-Catherine
- **K (Kahnawake)**: CP Railway Bridges 7A, 7B
- **SBS (Salaberry/Beauharnois)**: St-Louis-de-Gonzague, Larocque Bridge

## Scraping Ethics & Requirements

- **Respect rate limits**: Current 20-30 second intervals are already aggressive
- **Use User-Agent headers** to identify requests
- **Handle failures gracefully** - temporary site issues should not crash the system
- **Monitor for IP blocking** and implement backoff strategies
- **Log scraping activities** for debugging and monitoring
- **Never exceed current scraping frequency** without explicit approval

## Scheduling System

- **Daytime (6AM-10PM)**: Every 20 seconds
- **Nighttime (10PM-6AM)**: Every 30 seconds
- **Daily Statistics**: 3 AM recalculation
- Uses APScheduler AsyncIOScheduler with `max_instances=3`, `coalesce=True`

## Prediction Logic (predictions.py)

Predictions are calculated server-side and included in the JSON response:
- **Closed**: Predicts when bridge will OPEN (blended with vessel duration if active)
- **Closing soon**: Predicts when bridge will CLOSE
- **Construction**: Uses known end_time if available
- **Open/Opening/Unknown**: No prediction needed

## Development Workflow

**CRITICAL: Always run tests before committing or deploying!**

```bash
# 1. Make your changes
# 2. Run tests (REQUIRED)
python run_tests.py

# 3. If tests pass, run development server
uvicorn main:app --reload

# Other commands:
python scraper.py         # Test scraper standalone
```

## Testing Requirements

**Tests are MANDATORY before deployment!**

```bash
python run_tests.py
```

All 9 test files must pass (100%):
- Parser tests, Statistics tests, Prediction tests
- Status edge cases, Configuration, Thread safety
- Backoff logic, Network backoff, Logging

## Error Handling Standards

- **Network failures**: Retry with exponential backoff (never give up)
- **Website changes**: Log parsing failures for manual review
- **JSON write errors**: Use atomic writes (temp file + rename)
- **Unknown status**: Fall back to "Unknown", don't crash
- **Missing data**: Use previous known state when appropriate

## Performance Optimization

- **Atomic JSON writes**: Use temp file + `os.replace()` pattern
- **Only update on changes**: Compare live data before writing
- **Thread-safe access**: Use locks for shared state
- **Concurrent scraping**: ThreadPoolExecutor with 4 workers
- **Smart caching**: Auto-discover which JSON endpoint works per region

## Deployment

```bash
# On VPS (api.bridgeup.app)
docker compose pull
docker compose up -d

# Verify health
curl https://api.bridgeup.app/health

# Run initial statistics (required for iOS)
docker exec bridge-up python -c "from scraper import daily_statistics_update; daily_statistics_update()"
```

## Code Quality Checklist

- [ ] **TESTS PASS** - `python run_tests.py` shows all green
- [ ] Type hints on all functions
- [ ] Docstrings for classes and public methods
- [ ] Error handling for network requests
- [ ] Logging instead of print statements
- [ ] No hardcoded values or credentials
- [ ] JSON schema compatibility verified
- [ ] Predictions working correctly
- [ ] Thread safety maintained

## Recent Critical Updates

### December 2024: Firebase to VPS Migration
- **Removed**: Firebase Firestore dependency
- **Added**: FastAPI + WebSocket for real-time updates
- **Added**: JSON file storage (atomic writes)
- **Added**: predictions.py (logic moved from iOS)
- **Added**: shared.py (shared state module)
- **Updated**: scraper.py to broadcast via WebSocket
- **Updated**: stats_calculator.py (simplified API)

### June 2025: Performance & Reliability
- **Fixed**: APScheduler stalling issue with request timeouts
- **Added**: Concurrent scraping with ThreadPoolExecutor (50x speedup)
- **Added**: Thread safety for shared state
- **Added**: Exponential backoff for failed regions
