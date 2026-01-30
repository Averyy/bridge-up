# Bridge Up Backend - Claude Guidelines

## Project Overview
This is the Python backend for Bridge Up - a bridge monitoring system that scrapes real-time bridge status data from St. Lawrence Seaway websites and serves it via WebSocket and REST API.

**Key Context**: This backend is the **authoritative data source** for all clients (iOS, web). It scrapes, processes, calculates predictions, and serves all bridge status information.

**Agent Documentation**: When working on this project, also review:
- `.claude/agent/instructions.md` - Agent-specific responsibilities and workflow
- `.claude/agent/memory.md` - Session history and lessons learned
- `.claude/shared/project-context.md` - Detailed project architecture

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
- `boat_tracker.py` - Real-time vessel tracking (AIS)
- `boat_config.py` - Vessel regions, types, configuration
- `responsible_boat.py` - Closure attribution algorithm

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

## Python Environment

Python is managed via **uv** (see `~/Code/CLAUDE.md` for global setup).

```bash
# Create venv and install dependencies
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

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

| Endpoint | Rate Limit | Cache | Description |
|----------|------------|-------|-------------|
| `WS /ws` | - | - | WebSocket for real-time bridge updates |
| `GET /` | 30/min | 60s | API root with endpoint discovery |
| `GET /bridges` | 60/min | 10s | HTTP fallback (same data as WebSocket) |
| `GET /bridges/{id}` | 60/min | 10s | Single bridge by ID |
| `GET /boats` | 60/min | 10s | Vessel positions in bridge regions (REST only) |
| `GET /health` | 30/min | 5s | Health check with status info |
| `GET /docs` | 30/min | 60s | Custom Swagger UI with dark theme |
| `GET /openapi.json` | 30/min | 60s | OpenAPI schema |

**Rate Limiting**: Uses slowapi (in-memory). Returns 429 with `Retry-After: 60` header.
**Caching**: Cache-Control headers for browser/CDN caching. WebSocket unaffected.

### Health Endpoint (`/health`)

Returns monitoring info:
- `status`: "ok" or "error"
- `status_message`: Human-readable status description
- `last_updated`: Last time bridge data changed
- `last_scrape`: Last **successful** scrape timestamp (not attempts)
- `last_scrape_had_changes`: Whether last scrape found changes
- `statistics_last_updated`: Last time statistics were calculated (daily at 3 AM or manual)
- `bridges_count`: Number of bridges in data
- `websocket_clients`: Connected WebSocket clients

### API Documentation (`/docs`)

Custom-styled Swagger UI with Bridge Up dark theme:
- CSS in `static/swagger-custom.css`
- Injected after default Swagger CSS via `main.py` custom endpoint
- Contact URL links to https://bridgeup.app
- Response models with examples for all endpoints

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
        "upcoming_closures": [...],
        "responsible_vessel_mmsi": 316001635
      }
    }
  }
}
```

### Statistics Null Handling

Statistics fields return `null` only when no data exists for that type:

| Field | With Data | No Data |
|-------|-----------|---------|
| `average_closure_duration` | `12` | `null` |
| `closure_ci` | `{"lower": 8, "upper": 16}` | `null` |
| `average_raising_soon` | `3` | `null` |
| `raising_soon_ci` | `{"lower": 2, "upper": 5}` | `null` |

**Note**: CI requires 2+ entries to calculate. With fewer entries, CI is `null`. More entries = narrower CI range.

**Predictions still work**: Backend uses internal defaults (15-20 min) for prediction calculations when stats are `null`.

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

All 12 test files must pass (100%):
- Parser tests, Statistics tests, Prediction tests
- Status edge cases, Configuration, Thread safety
- Backoff logic, Network backoff, Logging
- Health tests, Boat tracker tests, Responsible boat tests

## Error Handling Standards

- **Network failures**: Retry with exponential backoff (never give up)
- **Website changes**: Log parsing failures for manual review
- **JSON write errors**: Use atomic writes (temp file + rename)
- **Unknown status**: Fall back to "Unknown", don't crash
- **Missing data**: Use previous known state when appropriate
- **SSL issues**: Using `verify=False` for seaway-greatlakes.com (missing Sectigo intermediate cert in chain)

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
- **Added**: Custom Swagger UI theme (branded dark mode)
- **Added**: Response models with examples in API docs
- **Changed**: CI always calculated when data exists (no minimum threshold)
- **Added**: `last_scrape_had_changes` to health endpoint

### June 2025: Performance & Reliability
- **Fixed**: APScheduler stalling issue with request timeouts
- **Added**: Concurrent scraping with ThreadPoolExecutor (50x speedup)
- **Added**: Thread safety for shared state
- **Added**: Exponential backoff for failed regions

### December 2025: Boat Tracking
- **Added**: Real-time vessel tracking via AIS
- **Added**: `boat_tracker.py` - UDP listener + AISHub API poller
- **Added**: `boat_config.py` - Region bounding boxes, vessel types
- **Added**: `GET /boats` endpoint (REST only, no WebSocket)
- **Data sources**: Local UDP dispatchers (real-time) + AISHub API (60s polling)
- **In-memory only**: No persistence, vessels cleaned up after 15 min
- **Regions**: Welland Canal + Montreal South Shore

### December 2025: Responsible Vessel Attribution
- **Added**: `responsible_boat.py` - Identifies which vessel caused a closure
- **Added**: `responsible_vessel_mmsi` field to bridge live data (REST + WebSocket)
- **Algorithm**: Score-based with distance, heading, and speed factors
- **Two modes**: "Closing soon" (approaching/waiting) vs "Closed/Closing" (actively transiting)
- **Added**: 42 unit tests for responsible boat logic

## Boat Tracking System

### Architecture
```
AIS Dispatchers (UDP) ─┐
                       ├─> VesselRegistry ─> GET /boats
AISHub API (HTTP) ────┘
```

### Data Sources
| Source | Latency | Data |
|--------|---------|------|
| UDP (local AIS receivers) | 30-45 seconds (randomized) | Position, speed, heading |
| AISHub API | 60 seconds | Position + static data (name, type, dimensions) |

**AISHub Polling Strategy**: Uses a combined bounding box covering both Welland and Montreal regions in a single request. This gives 60s freshness for both regions (vs 120s if alternating). Extra vessels in Lake Ontario/St. Lawrence are filtered out by region bounds. AISHub has a hard limit of 1 request per 60 seconds.

### Configuration
- `AISHUB_API_KEY` - API key for AISHub (optional, disables if not set)
- UDP listens on port 10110 (hardcoded)

### Vessel Schema
```json
{
  "mmsi": 316001635,
  "name": "RT HON PAUL J MARTIN",
  "type_name": "Cargo",
  "type_category": "cargo",
  "position": {"lat": 42.92, "lon": -79.24},
  "heading": 10,
  "course": 8.9,
  "speed_knots": 7.2,
  "destination": "MONTREAL",
  "dimensions": {"length": 225, "width": 24},
  "last_seen": "2025-12-25T19:22:28Z",
  "source": "udp:udp1",
  "region": "welland"
}
```

### Vessel Categories
`cargo`, `tanker`, `tug`, `passenger`, `fishing`, `sailing`, `pleasure`, `other`

### Filtering
- Only vessels in monitored regions (welland/montreal bounding boxes) - instantly removed when they leave
- Only vessels that moved in last 120 minutes (filters out anchored/docked vessels while allowing time for vessels waiting, maneuvering, or temporarily stopped)
- Only ship MMSIs (200M-799M range)
- Stale vessels removed after 15 minutes (no data received)

## Responsible Vessel Attribution (responsible_boat.py)

Identifies which vessel is most likely responsible for a bridge closure based on position, heading, speed, and proximity.

### Algorithm Overview

Two different algorithms based on bridge status:

| Status | Algorithm | Distance | Threshold | Notes |
|--------|-----------|----------|-----------|-------|
| Closing soon | `score_for_closing_soon()` | 7 km | 0.3 | Approaching OR waiting at bridge |
| Closed/Closing | `score_for_closed()` | 3 km | 0.3 | Actively passing through (must be moving) |

### Score Calculation

**Base score** (capped at 3.0 to prevent very close vessels from dominating):
```python
base_score = min(1.0 / (distance_km + 0.1), 3.0)
```

**Multipliers for "Closing soon"**:
| Vessel State | Distance | Heading | Multiplier |
|--------------|----------|---------|------------|
| Moving (≥0.1 kt) | Any | Toward bridge | 2.0 + speed bonus |
| Moving | Any | Unknown | 1.0 |
| Moving (≥1.5 kt) | Any | Away | **0.0** (impossible) |
| Moving (0.1-1.5 kt) | Any | Away | 0.1 (might be maneuvering) |
| Stationary | ≤250m | Toward bridge | 2.5 |
| Stationary | ≤250m | Unknown | 0.1 |
| Stationary | ≤250m | Away | 0.05 |
| Stationary | >250m | Toward bridge | 0.2 |
| Stationary | >250m | Unknown | 0.05 |
| Stationary | >250m | Away | 0.02 |

**Speed bonuses for moving vessels heading toward bridge**:
| Speed | Bonus | Total Multiplier |
|-------|-------|------------------|
| 0.1-1 kt | +0.0 | 2.0 |
| >1 kt | +0.2 | 2.2 |
| >4 kt | +0.2 more | 2.4 |

**Key insights**:
- Vessels moving away at ≥1.5 knots get **zero score** - logically impossible to cause an upcoming closure
- Stationary vessels only get high multipliers if within 250m (actually waiting at bridge)

**"Closed/Closing"**: No multipliers, but vessel must be moving (speed ≥ 0.5 knots)

### Key Constants
```python
MAX_DISTANCE_CLOSING_SOON = 7.0  # km (catches approaching vessels further out)
MAX_DISTANCE_CLOSED = 4.0        # km
MIN_SCORE_CLOSING_SOON = 0.25    # Lower to catch approaching vessels further out
MIN_SCORE_CLOSED = 0.3
BASE_SCORE_CAP = 3.0
MOVING_SPEED_THRESHOLD = 0.5     # knots
MOVING_AWAY_SPEED_THRESHOLD = 1.5  # knots - vessels moving away faster get zero score
HEADING_TOLERANCE = 60           # degrees
STATIONARY_WAITING_ZONE = 0.25   # km - only vessels within 250m are actually waiting
```

### Direction Logic
- **Moving vessels**: Use COG (Course Over Ground) - actual travel direction
- **Stationary vessels**: Use heading (bow direction) - determines if waiting vs docked

### API Integration
- `responsible_vessel_mmsi` field added to `live` section of bridge data
- Calculated on-demand for `/bridges` and `/bridges/{id}` endpoints
- Injected into WebSocket broadcasts and initial connection
- Returns `null` for non-closure statuses or when no confident match

## Rate Limiting & Caching (January 2026)

### Rate Limiting
- **Library**: slowapi (in-memory storage)
- **Limits**: 60/min for data endpoints, 30/min for static endpoints
- **Response**: 429 status with `Retry-After: 60` header
- **IP Detection**: Takes rightmost X-Forwarded-For (Caddy appends real IP)

### Response Caching
- **Headers**: `Cache-Control: public, max-age=X`
- **Data endpoints**: 10s cache (data updates every ~20s anyway)
- **Static endpoints**: 60s cache
- **Health**: 5s cache
- **WebSocket**: Unaffected (real-time push)
