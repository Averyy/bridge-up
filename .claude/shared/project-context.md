# Bridge Up Backend - Project Context

## Project Overview

Bridge Up Backend is a Python-based bridge monitoring service that scrapes real-time bridge status data from official St. Lawrence Seaway websites, processes this information with intelligent analysis, and stores it in Firebase Firestore. The system provides automated updates, historical tracking, and predictive analytics for consumption by the iOS app.

**Core Value Proposition**: Authoritative bridge status data with intelligent predictions based on historical analysis.

## Recent Critical Updates (June 2025)
- **Fixed**: APScheduler stalling issue with request timeouts + `max_instances=3`
- **Added**: Concurrent scraping with ThreadPoolExecutor (50x speedup)
- **Implemented**: Comprehensive test suite (33 tests, <1s execution)

## Architecture Overview

```
St. Lawrence Seaway Websites → Python Scraper → Data Processing → Firebase Firestore → iOS App
        ↓                          ↓              ↓                      ↓
Scheduled Updates          Statistical       Real-time Updates    Live Status
                          Analysis          to Mobile App        Display
```

**Key Design Decisions**: 
- Aggressive scraping schedule for real-time accuracy (20-30 second intervals)
- Historical data analysis for predictive confidence intervals
- Firebase as the bridge between backend and iOS app
- Docker containerization for reliable deployment
- Dual parser system for old and new JSON API formats with smart endpoint caching
- Concurrent execution with timeout protection (10s + 3 retries)
- Test-first development workflow

## Monitored Bridge Network

### Regions & Bridges
- **SCT (St. Catharines)**: 5 bridges including Highway 20, Queenston St, Glendale Ave, Lakeshore Rd, Carlton St
- **PC (Port Colborne)**: 3 bridges including Main St, Clarence St, Mellanby Ave
- **MSS (Montreal South Shore)**: 3 bridges including Victoria Bridge variants, Sainte-Catherine
- **SBS (Salaberry/Beauharnois)**: Various bridges in the region

### Bridge Status Types
- **open**: Normal traffic flow
- **closed**: Bridge raised for vessel passage
- **closing soon**: Bridge will raise within predicted timeframe
- **opening**: Bridge lowering after vessel passage
- **construction**: Scheduled maintenance or construction
- **unknown**: Status unavailable or parsing error

## Technical Stack

- **Language**: Python 3.9+
- **Web Framework**: Flask with APScheduler for development, Waitress for production
- **Data Fetching**: requests (with timeouts), direct JSON API consumption
- **Database**: Firebase Firestore for real-time data synchronization
- **Scheduling**: APScheduler with `max_instances=3`, `coalesce=True`
- **Deployment**: Docker with GitHub Actions CI/CD
- **Testing**: 33 tests covering core logic and edge cases
- **Monitoring**: Comprehensive logging for debugging and reliability

## Core Files & Functionality

### Main Components
- **`scraper.py`** - Main bridge data scraping logic and Firebase integration
- **`stats_calculator.py`** - Historical analysis and predictive statistics calculation
- **`config.py`** - Bridge URLs, coordinates, and configuration management
- **`start_flask.py`** - Development server with APScheduler setup
- **`start_waitress.py`** - Production server configuration
- **`app.py`** - Basic Flask app (minimal, mainly for health checks)

### Core Functionality

1. **Data Fetching Engine**
   - Scheduled fetching of official bridge status JSON API
   - JSON parsing and data extraction
   - Smart endpoint caching (auto-discovers correct endpoint per region)
   - Error handling for API changes and downtime
   - Rate limiting to avoid IP blocking

2. **Data Processing Pipeline**
   - Status normalization and validation
   - Upcoming closure detection and parsing
   - Historical activity logging
   - Statistical analysis for predictions

3. **Firebase Integration**
   - Real-time document updates
   - Historical data storage
   - Structured schema for iOS app consumption
   - Cost-optimized write operations (only on actual changes)

4. **Predictive Analytics**
   - Confidence interval calculations from historical data
   - Closure duration analysis
   - "Closing soon" time predictions
   - Statistical categorization of closure patterns

## Data Sources

The backend scrapes bridge status from official sources:

1. **St. Lawrence Seaway Management Corporation**
   - Real-time bridge status pages
   - Upcoming closure schedules
   - Construction notifications

2. **Regional Bridge Authorities**
   - Port Colborne bridge systems
   - St. Catharines bridge network
   - Montreal South Shore bridges

## Firebase Document Schema

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
            "under_9m": int,
            "10_15m": int,
            "16_30m": int,
            "31_60m": int,
            "over_60m": int
        },
        "total_entries": int
    },
    "live": {
        "status": str,              # Bridge status
        "last_updated": timestamp,
        "upcoming_closures": [
            {
                "type": str,        # "Commercial Vessel", "Construction"
                "time": timestamp,
                "longer": bool,
                "end_time": timestamp  # Optional
            }
        ]
    }
}
```

## Scheduling System

### Scraping Intervals
- **Daytime (6:00 AM - 9:59 PM)**: 20-second intervals for high traffic periods
- **Nighttime (10:00 PM - 5:59 AM)**: 30-second intervals for reduced activity
- **Daily Statistics**: 4:00 AM recalculation of confidence intervals

### Error Handling
- Automatic retry with exponential backoff
- Graceful degradation during website outages
- IP blocking detection and mitigation
- Comprehensive error logging

## Data Processing Workflow

### 1. Data Fetching
- Fetch bridge status from JSON API
- Parse JSON for status information
- Extract upcoming closure schedules
- Validate data format and completeness

### 2. Status Analysis
- Normalize status strings to standard values
- Detect status changes from previous scrape
- Parse upcoming vessel and construction closures
- Handle special cases (construction, unknown status)

### 3. Historical Tracking
- Log all status changes with timestamps
- Calculate closure durations
- Track "closing soon" lead times
- Maintain rolling history for statistics

### 4. Statistical Analysis
- Calculate confidence intervals for closure durations
- Analyze "closing soon" timing patterns
- Categorize closures by duration
- Generate predictive statistics for iOS app

### 5. Firebase Updates
- Update live status data in real-time
- Batch update statistical information
- Trigger iOS app updates via Firestore listeners
- Optimize write operations for cost efficiency

## Configuration Management

### Bridge Configuration (config.py)
```python
# Bridge keys and metadata (endpoints loaded from .env)
BRIDGE_KEYS = {
    'BridgeSCT': {'region': 'St Catharines', 'shortform': 'SCT'},
    'BridgePC': {'region': 'Port Colborne', 'shortform': 'PC'},
    'BridgeM': {'region': 'Montreal South Shore', 'shortform': 'MSS'},
    'BridgeSBS': {'region': 'Salaberry / Beauharnois / Suroît Region', 'shortform': 'SBS'}
}

BRIDGE_DETAILS = {
    'St Catharines': {
        'Queenston St.': {
            'lat': 43.165824700918485,
            'lng': -79.19492604380804,
            'number': '4'
        },
        # ... other bridges
    }
}
```

### Environment Variables
- Firebase credentials path
- Scraping intervals
- Error thresholds
- Logging levels

## Deployment Architecture

### Development
- Flask development server
- Local Firebase emulator (optional)
- Manual scraping triggers
- Debug logging enabled

### Production
- Docker container with Waitress WSGI server
- Firebase production database
- Automated scheduling with APScheduler
- Structured logging for monitoring
- Health checks and auto-restart capabilities

## Performance & Cost Optimization

- **Minimize Firebase writes**: Only update when status actually changes
- **Efficient queries**: Use targeted document updates
- **Smart caching**: Avoid redundant scraping when status unchanged
- **Resource management**: Proper connection pooling and cleanup
- **Memory usage**: Handle large historical datasets efficiently
- **Cost monitoring**: Track Firebase operations for optimization

## Development Workflow

```bash
# 1. Make changes
# 2. Run tests (MANDATORY)
python run_tests.py
# 3. Deploy only if tests pass
```

## Common Pitfalls to Avoid
1. **Never skip tests** - Always run `python run_tests.py` before deploying
2. **Never remove request timeouts** - This caused the major stalling bug
3. **Don't change Firebase schema** - iOS app depends on exact structure
4. **Maintain concurrent execution** - Sequential would be 50x slower
5. **Keep dual parser system** - Different regions use different JSON formats
6. **Don't over-engineer** - This is a startup, ship fast

## Performance Metrics
- **Scraping Speed**: ~0.7 seconds for all 5 regions (15 bridges total)
- **Test Execution**: <1 second for full test suite
- **Firebase Writes**: Only on status changes (cost optimization)
- **History Management**: Auto-cleanup keeps max 300 entries per bridge
- **Uptime**: No stalling since timeout fix implementation

## Success Metrics

- 99%+ scraping success rate during normal operations
- Sub-30-second latency for status changes
- Accurate predictions within confidence intervals
- Zero data loss during website outages
- Cost-effective Firebase operations

## Business Context
- **Users**: Boaters and bridge operators who need real-time status
- **Value Prop**: Not just status, but predictions based on historical patterns
- **Competition**: Other apps just show open/closed, we predict duration
- **iOS App**: Read-only consumer of this backend's data

## Relationship to iOS App

The backend serves as the **authoritative data source** for the iOS app:
- iOS app is **read-only** - never writes to Firebase
- Backend manages all document schema and structure
- Real-time updates flow from backend to iOS via Firebase listeners
- Statistical predictions calculated here are consumed by iOS for user predictions
- Any schema changes must be coordinated between backend and iOS teams