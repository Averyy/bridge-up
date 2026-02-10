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

- **NEVER blame external services** (Claude, Anthropic, Google, Reddit, etc.) for issues. If something isn't working, the problem is in THIS codebase. Investigate our code first, add logging, and find the real cause. Blaming external parties wastes time.
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
| `WS /ws` | - | - | WebSocket with channel subscriptions (see below) |
| `GET /` | 30/min | 60s | API root with endpoint discovery |
| `GET /bridges` | 60/min | 10s | All bridges (HTTP fallback) |
| `GET /bridges/{id}` | 60/min | 10s | Single bridge by ID |
| `GET /boats` | 60/min | 10s | All vessels (HTTP fallback) |
| `GET /health` | 30/min | 5s | Health check with status info |
| `GET /docs` | 30/min | 60s | Custom Swagger UI with dark theme |
| `GET /openapi.json` | 30/min | 60s | OpenAPI schema |

**Rate Limiting**: Uses slowapi (in-memory). Returns 429 with `Retry-After: 60` header.
**Caching**: Cache-Control headers for browser/CDN caching. WebSocket unaffected.

### WebSocket (`/ws`)

Clients must subscribe to channels after connecting. See [ws-client-guide.md](ws-client-guide.md) for full docs.

**Channels:**
| Channel | Description |
|---------|-------------|
| `bridges` | All 15 bridges |
| `bridges:{region}` | Region-specific: `sct`, `pc`, `mss`, `k`, `sbs` |
| `boats` | All vessels |
| `boats:{region}` | Region-specific: `welland`, `montreal` |

**Push behavior:**
- **Bridges**: Pushed when status changes (few times/day per bridge)
- **Boats**: Pushed when vessel data changes (~30-60s), excludes volatile fields (`last_seen`, `source`)

**Example:**
```json
{"action": "subscribe", "channels": ["bridges", "boats:welland"]}
```

### Health Endpoint (`/health`)

Returns monitoring info with two separate health checks:

**Seaway Status** (can we reach the Seaway API?):
- `seaway_status`: "ok" or "error"
- `seaway_message`: Details (e.g., "No successful fetch in 6 minutes")

**Bridge Activity** (are bridges changing?):
- `bridge_activity`: "ok" or "warning"
- `bridge_activity_message`: Details (e.g., "Last bridge status change 2 hours ago")

**Seasonal thresholds** for bridge activity warnings:
- Summer (Mar 16 - Nov 30): 24 hours
- Winter (Dec 1 - Mar 15): 168 hours (1 week)

**Combined status** (for backwards compatibility):
- `status`: "ok", "warning", or "error"
- `status_message`: Human-readable explanation

**Other fields:**
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

## Rate Limiting & Caching

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

## Web Fetching

**CRITICAL: NEVER use WebFetch directly. ALWAYS use fetchaller first.**
Load via `ToolSearch("fetchaller")` then use `mcp__fetchaller__fetch`. It has no domain restrictions.
Add `raw: true` for raw HTML instead of markdown. If raw:true fails, use `curl` via Bash as fallback.
Only fall back to WebFetch if fetchaller fails entirely.
If a dedicated MCP exists (GitHub, Slack, etc.), use that instead.

## Reddit Searching and Browsing

Load via `ToolSearch("fetchaller")` first. Use `mcp__fetchaller__browse_reddit` to browse subreddits, `mcp__fetchaller__search_reddit` to find posts, and `mcp__fetchaller__fetch` to read full discussions.
