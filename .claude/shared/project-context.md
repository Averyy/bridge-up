# Bridge Up Backend - Project Context

## Project Overview

Bridge Up Backend is a Python-based bridge monitoring service that scrapes real-time bridge status data from official St. Lawrence Seaway websites, processes this information with intelligent analysis, and serves it via WebSocket and REST API. The system provides automated updates, historical tracking, and predictive analytics for consumption by iOS and web apps.

**Core Value Proposition**: Authoritative bridge status data with intelligent predictions based on historical analysis.

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

**Data Storage**: JSON files in `data/` directory
- `data/bridges.json` - Current bridge state with predictions
- `data/history/*.json` - Historical data per bridge (max 300 entries each)

## API Endpoints

- `WS /ws` - WebSocket for real-time updates (push on change)
- `GET /` - API root with endpoint discovery
- `GET /bridges` - HTTP fallback (same data as WebSocket)
- `GET /bridges/{id}` - Single bridge by ID
- `GET /health` - Health check with status info
- `GET /docs` - Custom Swagger UI with Bridge Up dark theme

### API Documentation
- Custom dark theme in `static/swagger-custom.css`
- Matches bridgeup.app branding (primary blue `#0A84FF`)
- Response models with examples for all endpoints
- Contact URL links to https://bridgeup.app

## Monitored Bridge Network

### Regions & Bridges
- **SCT (St. Catharines)**: 5 bridges including Highway 20, Queenston St, Glendale Ave, Lakeshore Rd, Carlton St
- **PC (Port Colborne)**: 3 bridges including Main St, Clarence St, Mellanby Ave
- **MSS (Montreal South Shore)**: 3 bridges including Victoria Bridge variants, Sainte-Catherine
- **K (Kahnawake)**: 2 bridges (CP Railway Bridges 7A, 7B)
- **SBS (Salaberry/Beauharnois)**: 2 bridges including St-Louis-de-Gonzague, Larocque Bridge

### Bridge Status Types
- **Open**: Normal traffic flow
- **Closed**: Bridge raised for vessel passage
- **Closing soon**: Bridge will raise within predicted timeframe
- **Opening**: Bridge lowering after vessel passage
- **Construction**: Scheduled maintenance or construction
- **Unknown**: Status unavailable or parsing error

## Technical Stack

- **Language**: Python 3.11+
- **Web Framework**: FastAPI with uvicorn
- **Data Storage**: JSON files with atomic writes
- **Scheduling**: APScheduler with `max_instances=3`, `coalesce=True`
- **Deployment**: Docker with Caddy reverse proxy
- **Testing**: 9 test files covering core logic and edge cases
- **Monitoring**: Loguru for structured logging, `/health` endpoint

## Core Functionality

### 1. Data Fetching Engine
- Scheduled fetching from official bridge status JSON API
- Smart endpoint caching (auto-discovers correct endpoint per region)
- Concurrent scraping with ThreadPoolExecutor (4 workers)
- Error handling with exponential backoff (never gives up)

### 2. Data Processing Pipeline
- Status normalization and validation
- Upcoming closure detection and parsing
- Historical activity logging
- Prediction calculation (moved from iOS)

### 3. Real-Time Updates
- WebSocket broadcast on status changes
- HTTP fallback for clients that can't use WebSocket
- Full state sent on connect (no delta sync)

### 4. Predictive Analytics
- Confidence interval calculations from historical data
- Blended predictions (vessel duration + statistics)
- Duration bucket analysis
- Prediction meanings:
  - Closed: When bridge will OPEN
  - Closing soon: When bridge will CLOSE
  - Construction: When bridge will OPEN (if end_time known)

## JSON Schema

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
        "upcoming_closures": [
          {
            "type": "Commercial Vessel",
            "time": "2025-12-20T15:20:00-05:00",
            "longer": false,
            "expected_duration_minutes": 15
          }
        ]
      }
    }
  }
}
```

## Scheduling System

### Scraping Intervals
- **Daytime (6:00 AM - 9:59 PM)**: 20-second intervals
- **Nighttime (10:00 PM - 5:59 AM)**: 30-second intervals
- **Daily Statistics**: 3:00 AM recalculation

### Error Handling
- Automatic retry with exponential backoff (never gives up)
- Graceful degradation during website outages
- Smart endpoint caching recovers from temporary failures

## Development Workflow

```bash
# 1. Make changes
# 2. Run tests (MANDATORY)
python run_tests.py
# 3. Run development server
uvicorn main:app --reload
```

## Deployment

```bash
# On VPS (api.bridgeup.app)
docker compose pull
docker compose up -d
curl https://api.bridgeup.app/health
docker exec bridge-up python -c "from scraper import daily_statistics_update; daily_statistics_update()"
```

## Performance Metrics
- **Scraping Speed**: ~0.7 seconds for all 5 regions (15 bridges total)
- **Test Execution**: <1 second for full test suite
- **Updates**: Only on status changes (efficient)
- **History Management**: Auto-cleanup keeps max 300 entries per bridge

## Common Pitfalls to Avoid
1. **Never skip tests** - Always run `python run_tests.py` before deploying
2. **Never remove request timeouts** - This caused a major stalling bug
3. **Don't change JSON schema** - Clients depend on exact structure
4. **Maintain concurrent execution** - Sequential would be 50x slower
5. **Keep dual parser system** - Different regions use different JSON formats
6. **Use atomic writes** - Prevents JSON corruption on crash
7. **Update API docs when changing endpoints** - Keep `/docs`, CLAUDE.md, README.md in sync
8. **Test Swagger UI visually** - CSS changes can break layout unexpectedly

## Statistics Null Handling
Statistics fields return `null` when insufficient data exists:
- `average_closure_duration`, `average_raising_soon`: null when 0 entries
- `closure_ci`, `raising_soon_ci`: null when <2 entries (need 2+ for CI math)
- Predictions still work internally with defaults: `{'lower': 15, 'upper': 20}`
- iOS should handle null gracefully (show "N/A" or hide the field)

## Business Context
- **Users**: Travelers who need real-time bridge status
- **Value Prop**: Not just status, but predictions based on historical patterns
- **Competition**: Other apps just show open/closed, we predict duration
- **Clients**: iOS app, potential web app, potential Android app

## Relationship to Clients

The backend serves as the **authoritative data source** for all clients:
- Clients are **read-only** - never write to backend
- Backend manages all data schema and structure
- Real-time updates flow via WebSocket
- Predictions calculated server-side (simpler client code)
- Any schema changes must be coordinated with client teams
