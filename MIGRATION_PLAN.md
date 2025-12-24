# Bridge Up Backend Migration Plan

## Overview

Migrate from Firebase to a self-hosted $5/month VPS with fixed costs and full control.

## Why

- **Fixed cost**: $5/mo forever, no surprise bills
- **Full control**: No vendor lock-in
- **Simpler iOS**: Remove Firebase SDK entirely
- **Same features**: Everything works exactly as before

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Vultr Toronto ($5/mo)                       │
│              1 vCPU, 1GB RAM                             │
│                                                          │
│  ┌─────────┐     ┌──────────────────────────────────┐   │
│  │  Caddy  │────▶│         FastAPI                  │   │
│  │  (SSL)  │     │                                  │   │
│  └─────────┘     │  ┌──────────┐   ┌────────────┐  │   │
│                  │  │ Scraper  │──▶│ JSON Files │  │   │
│                  │  │ (20s/30s)│   │            │  │   │
│                  │  └────┬─────┘   └────────────┘  │   │
│                  │       │                         │   │
│                  │       ▼ (on change)             │   │
│                  │  ┌──────────┐                   │   │
│                  │  │Broadcast │──▶ iOS clients    │   │
│                  │  │WebSocket │                   │   │
│                  │  └──────────┘                   │   │
│                  │                                 │   │
│                  │  Endpoints:                     │   │
│                  │   • WS  /ws       (real-time)   │   │
│                  │   • GET /bridges  (fallback)    │   │
│                  │   • GET /health   (monitoring)  │   │
│                  └──────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
Seaway API
    │
    ▼
Scraper (every 20s day / 30s night)
    │
    ▼
Change detected?
    │
   Yes ──▶ Update bridges.json
    │              │
    │              ▼
    │      Broadcast to all WebSocket clients (instant)
    │
   No ──▶ Sleep → Repeat
```

---

## Data Storage

Simple JSON files (no database needed):

```
data/
├── bridges.json           # Live status + statistics for all 15 bridges
└── history/
    ├── SCT_CarltonSt.json
    ├── SCT_QueenstonSt.json
    ├── PC_MainSt.json
    └── ... (15 files, one per bridge, max 300 entries each)
```

### bridges.json structure (confirmed with iOS)
```json
{
  "last_updated": "2025-12-20T15:30:00-05:00",

  "available_bridges": [
    // Generated from config.py - 15 bridges with {id, name, region_short, region}
    {"id": "SCT_CarltonSt", "name": "Carlton St.", "region_short": "SCT", "region": "St Catharines"},
    // ... (14 more)
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
          "closure_durations": {
            "under_9m": 45,
            "10_15m": 30,
            "16_30m": 15,
            "31_60m": 8,
            "over_60m": 2
          },
          "total_entries": 287
        }
      },
      "live": {
        "status": "Closed",
        "last_updated": "2025-12-20T15:20:00-05:00",

        "predicted": {
          "lower": "2025-12-20T15:28:00-05:00",
          "upper": "2025-12-20T15:36:00-05:00"
        },

        "upcoming_closures": [
          {
            "type": "Commercial Vessel",
            "time": "2025-12-20T15:20:00-05:00",
            "longer": false,
            "expected_duration_minutes": 15,
            "end_time": null
          }
        ]
      }
    },

    "SCT_QueenstonSt": {
      "static": {
        "name": "Queenston St.",
        "region": "St Catharines",
        "region_short": "SCT",
        "coordinates": {"lat": 43.17, "lng": -79.19},
        "statistics": { "...": "..." }
      },
      "live": {
        "status": "Closing soon",
        "last_updated": "2025-12-20T15:25:00-05:00",

        "predicted": {
          "lower": "2025-12-20T15:27:00-05:00",
          "upper": "2025-12-20T15:30:00-05:00"
        },

        "upcoming_closures": []
      }
    }
  }
}
```

**Schema notes:**
- `available_bridges`: Array with `id`, `name`, `region_short`, `region` (replaces hardcoded list + regionFullNames in iOS)
- `static`/`live` structure: Matches iOS `staticData`/`liveData` model (no iOS refactoring needed)
- `coordinates`: Uses `lat`/`lng` keys (iOS adds computed `.latitude`/`.longitude` properties)
- `status`: Capitalized values: `"Open"`, `"Closed"`, `"Closing soon"`, `"Opening"`, `"Construction"`, `"Unknown"`
- `predicted`: Single field for predicted status change (meaning depends on status):
  | Status | `predicted` means |
  |--------|-------------------|
  | Closed | When it will open |
  | Closing soon | When it will close |
  | Construction | When it will open |
  | Open/Opening/Closing | Not present (use `upcoming_closures[0].time`) |
- `predicted: null` means "longer than usual" or unknown (iOS shows appropriate text)
- `expected_duration_minutes`: Backend calculates from type + longer flag (removes hardcoded values from iOS)
- `upcoming_closures`: Array (can be empty `[]`)
- All timestamps: ISO 8601 with timezone (e.g., `2025-12-20T15:30:00-05:00`)
- `/bridges` HTTP endpoint returns identical structure to WebSocket messages
- Dropped internal fields: `raw_status`, `available` (not needed by iOS)

### Prediction Logic (moved from iOS to backend)

**Duration constants** (from seaway site, not guesses):
| Vessel Type | longer=false | longer=true |
|-------------|--------------|-------------|
| Commercial Vessel | 15 min | 30 min |
| Pleasure Craft | 10 min | 20 min |

**`predicted` calculation** (single field, meaning depends on status):
```
IF status == "Closed" or "Construction":
  → calculate when bridge will OPEN

  IF construction with end_time:
    → return {lower: end_time, upper: end_time}

  IF status == "Construction" without end_time:
    → return null  (unknown opening)

  elapsed_minutes = (now - last_updated) / 60

  IF active boat closure (started):
    expected = expected_duration_minutes
    lower = (expected + closure_ci.lower) / 2 - elapsed_minutes
    upper = (expected + closure_ci.upper) / 2 - elapsed_minutes
  ELSE:
    lower = closure_ci.lower - elapsed_minutes
    upper = closure_ci.upper - elapsed_minutes

  IF lower <= 0 AND upper <= 0:
    → return null  ("longer than usual")

  → return {lower: now + lower_minutes, upper: now + upper_minutes}


ELSE IF status == "Closing soon":
  → calculate when bridge will CLOSE

  IF upcoming_closure with time within 1 hour:
    → return null  (iOS uses closure.time directly)

  IF upcoming_closure with time already passed:
    → return null  (iOS shows "was expected at X")

  elapsed_minutes = (now - last_updated) / 60
  lower = raising_soon_ci.lower - elapsed_minutes
  upper = raising_soon_ci.upper - elapsed_minutes

  IF lower <= 0 AND upper <= 0:
    → return null  ("longer than usual")

  → return {lower: now + lower_minutes, upper: now + upper_minutes}


ELSE:
  → return null  (Open, Opening, Closing, Unknown - no prediction)
```

---

## Backend Code

### File Structure
```
backend/
├── main.py              # FastAPI app + WebSocket + scheduler
├── shared.py            # NEW: Shared state (avoids circular imports)
├── scraper.py           # Modified for JSON storage + broadcast
├── predictions.py       # NEW: Prediction logic (moved from iOS)
├── stats_calculator.py  # Refactored (no Firestore params)
├── config.py            # Unchanged
├── data/
│   ├── bridges.json
│   └── history/
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
└── requirements.txt
```

### shared.py (NEW - avoids circular imports)
```python
"""Shared state module - prevents circular imports between main.py and scraper.py."""
from datetime import datetime
from typing import Dict, Any, Optional, List
import threading
import asyncio

# Timezone
import pytz
TIMEZONE = pytz.timezone('America/Toronto')

# Last scrape time (for health monitoring)
last_scrape_time: Optional[datetime] = None

# In-memory cache of current bridge state
last_known_state: Dict[str, Any] = {}
last_known_state_lock = threading.Lock()

# WebSocket clients (managed by main.py)
connected_clients: List = []  # List[WebSocket] - can't type hint due to import

# Event loop reference (set by main.py at startup)
main_loop: Optional[asyncio.AbstractEventLoop] = None
```

### main.py
```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from datetime import datetime
import json
import asyncio
import os

from shared import (
    TIMEZONE, last_known_state, connected_clients, main_loop,
    last_scrape_time
)
import shared  # For updating module-level variables
from scraper import scrape_and_update, daily_statistics_update, sanitize_document_id
from config import BRIDGE_KEYS, BRIDGE_DETAILS

scheduler = AsyncIOScheduler(timezone=TIMEZONE)

def generate_available_bridges() -> list:
    """Generate available_bridges list from config (removes hardcoded list + regionFullNames from iOS)."""
    bridges = []
    for bridge_key, info in BRIDGE_KEYS.items():
        region = info['region']
        shortform = info['shortform']
        for name in BRIDGE_DETAILS.get(region, {}):
            bridge_id = sanitize_document_id(shortform, name)
            bridges.append({
                "id": bridge_id,
                "name": name,
                "region_short": shortform,
                "region": region  # Full name for SettingsView grouping
            })
    return bridges

# Generated once at module load
AVAILABLE_BRIDGES = generate_available_bridges()

def initialize_data_files():
    os.makedirs("data/history", exist_ok=True)
    if not os.path.exists("data/bridges.json"):
        with open("data/bridges.json", "w") as f:
            json.dump({"last_updated": None, "available_bridges": AVAILABLE_BRIDGES, "bridges": {}}, f)
    else:
        with open("data/bridges.json") as f:
            data = json.load(f)
            for bridge_id, bridge_data in data.get("bridges", {}).items():
                last_known_state[bridge_id] = bridge_data
            # Ensure available_bridges is present (migration from old format)
            if "available_bridges" not in data:
                data["available_bridges"] = AVAILABLE_BRIDGES
                with open("data/bridges.json", "w") as f:
                    json.dump(data, f)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set shared state
    shared.main_loop = asyncio.get_running_loop()
    initialize_data_files()

    # Day: every 20s (6AM-10PM), Night: every 30s (10PM-6AM)
    scheduler.add_job(scrape_and_update, 'cron', hour='6-21', minute='*', second='0,20,40',
                      max_instances=3, coalesce=True)
    scheduler.add_job(scrape_and_update, 'cron', hour='22-23,0-5', minute='*', second='0,30',
                      max_instances=3, coalesce=True)
    scheduler.add_job(daily_statistics_update, 'cron', hour=3, minute=0)
    scheduler.start()
    scrape_and_update()  # Run immediately
    yield
    # Graceful shutdown: close all WebSocket connections
    for client in connected_clients.copy():
        try:
            await client.close(code=1001, reason="Server shutting down")
        except Exception:
            pass
    connected_clients.clear()
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    with open("data/bridges.json") as f:
        await websocket.send_text(f.read())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

async def broadcast(data: dict):
    message = json.dumps(data)
    for client in connected_clients.copy():
        try:
            await client.send_text(message)
        except:
            connected_clients.remove(client)

def broadcast_sync(data: dict):
    """Called from scraper threads."""
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(data), main_loop)

@app.get("/bridges")
def get_bridges():
    with open("data/bridges.json") as f:
        return json.load(f)

@app.get("/health")
def health():
    with open("data/bridges.json") as f:
        data = json.load(f)
    return {
        "status": "ok",
        "last_updated": data.get("last_updated"),
        "last_scrape": last_scrape_time.isoformat() if last_scrape_time else None,
        "bridges_count": len(data.get("bridges", {})),
        "websocket_clients": len(connected_clients)
    }

@app.get("/bridges/{bridge_id}")
def get_bridge(bridge_id: str):
    """Get a single bridge by ID (useful for deep links)."""
    with open("data/bridges.json") as f:
        data = json.load(f)
    bridge = data.get("bridges", {}).get(bridge_id)
    if not bridge:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Bridge not found")
    return bridge
```

### CORS (Required for Web Clients)

Add CORS middleware after creating the app. iOS doesn't use CORS (native apps), this is only for web:

```python
# Add after: app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://(www\.)?bridgeup\.app|http://localhost:\d+|http://192\.168\.\d+\.\d+:\d+",
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

**Allowed origins:**
- `https://bridgeup.app` and `https://www.bridgeup.app` (production)
- `http://localhost:*` (any port, for local dev)
- `http://192.168.*.*:*` (local network testing)

### WebSocket Behavior
- **On connect**: Server sends full state immediately (all bridges)
- **On change**: Server broadcasts full state to all clients (no deltas)
- **Reconnect**: Client receives full state again (no special handling needed)
- **Protocol-level ping/pong**: Handled automatically by uvicorn (keeps TCP connection alive)
- **Application-level ping**: iOS should still send ping every 30s to detect dead connections faster (see iOS Implementation Notes)
- **No auth required**: Public read-only data

### Scraper Changes

**Keep unchanged:**
- `scrape_bridge_data()`
- `parse_old_json()` / `parse_new_json()`
- `interpret_bridge_status()`
- `interpret_tracked_status()`
- `config.py` (entire file)
- Backoff/retry logic
- Concurrent scraping with ThreadPoolExecutor

**Refactor:**
- `stats_calculator.py` - Remove Firestore `doc_ref` and `batch` params, return stats dict only
- `daily_statistics_update()` - Rewrite to read/write JSON files instead of Firestore

**Replace:**
- `update_firestore()` → `update_json_and_broadcast()`
- `update_bridge_history()` → `append_to_history_file()`
- Remove all Firebase imports
- Remove `cachetools.TTLCache` for `last_known_open_times` (not needed without Firestore)

**Update `scrape_and_update()` to track last scrape time:**
```python
from main import last_scrape_time  # Import global

def scrape_and_update():
    global last_scrape_time
    # ... existing scraping logic ...
    last_scrape_time = datetime.now(TIMEZONE)  # Update at end of each cycle
```

**Add (predictions - moved from iOS):**
```python
# predictions.py - New file for prediction logic
# Matches iOS BridgeInfoGenerator.swift logic exactly

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import pytz

TIMEZONE = pytz.timezone('America/Toronto')

# Duration constants from seaway site (hardcoded in iOS, now in backend)
EXPECTED_DURATIONS = {
    'commercial vessel': {False: 15, True: 30},
    'pleasure craft': {False: 10, True: 20},
    'next arrival': {False: 15, True: 30},  # Treat as commercial
}

# Types that use blended prediction (boat closures)
BOAT_TYPES = {'commercial vessel', 'pleasure craft', 'next arrival'}


def get_expected_duration(closure_type: str, longer: bool) -> Optional[int]:
    """Get expected closure duration in minutes based on vessel type."""
    type_lower = closure_type.lower()
    if type_lower in EXPECTED_DURATIONS:
        return EXPECTED_DURATIONS[type_lower][longer]
    return None


def parse_datetime(dt: Any) -> Optional[datetime]:
    """Parse datetime from various formats."""
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            return None
    return None


def calculate_prediction(
    status: str,
    last_updated: datetime,
    statistics: Dict[str, Any],
    upcoming_closures: List[Dict[str, Any]],
    current_time: datetime
) -> Optional[Dict[str, str]]:
    """
    Calculate predicted next status change.
    Matches iOS BridgeInfoGenerator.swift logic exactly.

    - For Closed/Construction: predicts when bridge will OPEN
    - For Closing soon: predicts when bridge will CLOSE

    Returns:
        {"lower": ISO timestamp, "upper": ISO timestamp} or None if unknown
    """
    status_lower = status.lower()

    # === CLOSED / CONSTRUCTION: predict when it will OPEN ===
    if status_lower in ('closed', 'construction'):
        elapsed_minutes = (current_time - last_updated).total_seconds() / 60
        closure_ci = statistics.get('closure_ci', {'lower': 8, 'upper': 16})

        # Case A: Construction with known end_time
        for closure in upcoming_closures:
            if closure.get('type', '').lower() == 'construction':
                end_time = parse_datetime(closure.get('end_time'))
                closure_start = parse_datetime(closure.get('time'))

                if (end_time and end_time > current_time and
                    closure_start and closure_start <= current_time):
                    return {
                        "lower": end_time.isoformat(),
                        "upper": end_time.isoformat()
                    }

        # Case B: Construction without end_time → unknown
        if status_lower == 'construction':
            return None

        # Case C: Boat closure that has STARTED
        if upcoming_closures:
            first = upcoming_closures[0]
            closure_time = parse_datetime(first.get('time'))
            closure_type = first.get('type', '').lower()

            if (closure_time and closure_time <= current_time and
                closure_type in BOAT_TYPES):

                expected = first.get('expected_duration_minutes') or get_expected_duration(
                    closure_type, first.get('longer', False)
                )

                if expected:
                    lower = (expected + closure_ci['lower']) / 2 - elapsed_minutes
                    upper = (expected + closure_ci['upper']) / 2 - elapsed_minutes

                    if lower <= 0 and upper <= 0:
                        return None

                    return {
                        "lower": (current_time + timedelta(minutes=max(lower, 0))).isoformat(),
                        "upper": (current_time + timedelta(minutes=max(upper, 0))).isoformat()
                    }

        # Case D: Pure statistics
        lower = closure_ci['lower'] - elapsed_minutes
        upper = closure_ci['upper'] - elapsed_minutes

        if lower <= 0 and upper <= 0:
            return None

        return {
            "lower": (current_time + timedelta(minutes=max(lower, 0))).isoformat(),
            "upper": (current_time + timedelta(minutes=max(upper, 0))).isoformat()
        }

    # === CLOSING SOON: predict when it will CLOSE ===
    elif status_lower == 'closing soon':
        # If there's a specific closure time, iOS uses it directly
        if upcoming_closures:
            first = upcoming_closures[0]
            closure_time = parse_datetime(first.get('time'))

            if closure_time:
                # Closure time passed → iOS shows "was expected at"
                if closure_time <= current_time:
                    return None

                # Closure within 1 hour → iOS uses closure.time
                if (closure_time - current_time).total_seconds() < 3600:
                    return None

        # Pure statistics
        elapsed_minutes = (current_time - last_updated).total_seconds() / 60
        raising_soon_ci = statistics.get('raising_soon_ci', {'lower': 3, 'upper': 8})

        lower = raising_soon_ci['lower'] - elapsed_minutes
        upper = raising_soon_ci['upper'] - elapsed_minutes

        if lower <= 0 and upper <= 0:
            return None

        return {
            "lower": (current_time + timedelta(minutes=max(lower, 0))).isoformat(),
            "upper": (current_time + timedelta(minutes=max(upper, 0))).isoformat()
        }

    # === OTHER STATUSES: no prediction ===
    return None


def add_expected_duration_to_closures(upcoming_closures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add expected_duration_minutes to each closure based on type + longer."""
    for closure in upcoming_closures:
        if 'expected_duration_minutes' not in closure:
            duration = get_expected_duration(
                closure.get('type', ''),
                closure.get('longer', False)
            )
            if duration:
                closure['expected_duration_minutes'] = duration
    return upcoming_closures
```

**Prediction Test Cases** (`test_predictions.py`):

| Test | Scenario | Expected Result |
|------|----------|-----------------|
| `test_closed_commercial_vessel_5min_elapsed` | Commercial vessel, closed 5 min ago | Blended prediction: ~6.5-11.5 min remaining |
| `test_closed_commercial_vessel_20min_elapsed` | Same bridge, closed 20 min ago | `None` (longer than usual) |
| `test_closed_no_closure_pure_stats` | Closed, no active closure | Pure stats prediction |
| `test_construction_with_end_time` | Construction with known end | Returns exact end_time |
| `test_construction_without_end_time` | Construction, no end_time | `None` (unknown) |
| `test_closing_soon_with_known_closure` | Boat expected in 8 min | `None` (iOS uses closure.time) |
| `test_closing_soon_no_closure_pure_stats` | Closing soon, no closure info | Pure stats prediction |
| `test_boat_not_started_uses_pure_stats` | Boat in future (not started) | Pure stats, not blended |
| `test_open_status_no_prediction` | Open bridge | `None` (no prediction needed) |

**Implementation Notes:**

1. **Atomic JSON writes**: Prevent corruption by writing to temp file, then rename:
   ```python
   import tempfile
   import os

   def atomic_write_json(path: str, data: Any) -> None:
       """Atomically write JSON data to file (crash-safe)."""
       dir_path = os.path.dirname(path) or "."
       with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, suffix='.tmp') as f:
           json.dump(data, f, default=str)  # default=str handles datetime
           temp_path = f.name
       os.replace(temp_path, path)  # Atomic on POSIX
   ```

2. **History files use same atomic pattern**: Each bridge has its own history file, so no locking needed between bridges. Use `atomic_write_json()` for history too:
   ```python
   def append_to_history_file(bridge_id: str, entry: dict) -> None:
       """Append entry to bridge history file (max 300 entries)."""
       path = f"data/history/{bridge_id}.json"

       # Read existing or start fresh
       if os.path.exists(path):
           with open(path) as f:
               history = json.load(f)
       else:
           history = []

       # Prepend new entry (newest first)
       history.insert(0, entry)

       # Trim to max 300 entries
       history = history[:300]

       # Atomic write
       atomic_write_json(path, history)
   ```

3. **File locking for bridges.json**: Multiple scraper threads update `bridges.json`. Use a lock:
   ```python
   bridges_file_lock = threading.Lock()

   def update_json_and_broadcast(bridge_id: str, bridge_data: dict) -> None:
       with bridges_file_lock:
           with open("data/bridges.json") as f:
               data = json.load(f)
           data["bridges"][bridge_id] = bridge_data
           data["last_updated"] = datetime.now(TIMEZONE).isoformat()
           atomic_write("data/bridges.json", data)
       broadcast_sync(data)  # Outside lock
   ```

4. **History file format**: Each bridge has `data/history/{bridge_id}.json`:
   ```json
   [
     {"id": "Dec21-1430-abcd", "start_time": "2025-12-21T14:30:00-05:00",
      "end_time": "2025-12-21T14:42:00-05:00", "status": "Unavailable (Closed)", "duration": 720},
     {"id": "Dec21-1442-efgh", "start_time": "2025-12-21T14:42:00-05:00",
      "end_time": null, "status": "Available", "duration": null}
   ]
   ```
   Sorted newest first. Max 300 entries (pruned during daily stats).

5. **DateTime serialization**: Use `.isoformat()` for all timestamps. Replace `firestore.GeoPoint` with `{"lat": x, "lng": y}`.

6. **Statistics refactor**: Modify `calculate_bridge_statistics()` to accept history list and return stats dict only (remove `doc_ref`, `batch` params). Rewrite `daily_statistics_update()` to read/write JSON files.

7. **Prediction integration**: In `update_json_and_broadcast()`, before writing to JSON:
   ```python
   from predictions import calculate_prediction, add_expected_duration_to_closures

   current_time = datetime.now(TIMEZONE)

   # Add expected_duration_minutes to closures
   bridge_data['live']['upcoming_closures'] = add_expected_duration_to_closures(
       bridge_data['live']['upcoming_closures']
   )

   # Calculate prediction (single field, meaning depends on status)
   bridge_data['live']['predicted'] = calculate_prediction(
       status=bridge_data['live']['status'],
       last_updated=parse_iso(bridge_data['live']['last_updated']),
       statistics=bridge_data['static']['statistics'],  # From static section
       upcoming_closures=bridge_data['live']['upcoming_closures'],
       current_time=current_time
   )
   ```

### docker-compose.yml
```yaml
services:
  caddy:
    image: caddy:2-alpine
    container_name: caddy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    networks:
      - web
    depends_on:
      - app
    restart: always

  app:
    build: .
    container_name: bridgeup-app
    expose:
      - "8000"
    volumes:
      - ./data:/app/data
    environment:
      - OLD_JSON_ENDPOINT=${OLD_JSON_ENDPOINT}
      - NEW_JSON_ENDPOINT=${NEW_JSON_ENDPOINT}
    networks:
      - web
    restart: always

networks:
  web:
    external: true

volumes:
  caddy_data:
```

### Caddyfile
```
api.bridgeup.app {
    reverse_proxy bridgeup-app:8000
}
```

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data/history

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### requirements.txt
```
fastapi
uvicorn[standard]
requests
pytz
python-dotenv
loguru
apscheduler
```

---

## iOS Changes

### Remove
- Firebase SDK (entire dependency)
- All Firestore listener code
- **~200 lines of prediction logic** in `BridgeInfoGenerator.swift` (now backend's job)
- Hardcoded bridge list in `BridgeViewModel.swift`

### Add (~80 lines total)

**WebSocket client with exponential backoff:**
```swift
class BridgeWebSocket: ObservableObject {
    @Published var bridges: [Bridge] = []
    @Published var availableBridges: [AvailableBridge] = []  // From backend
    private var task: URLSessionWebSocketTask?
    private let url = URL(string: "wss://api.bridgeup.app/ws")!
    private var reconnectDelay: TimeInterval = 1.0
    private let maxReconnectDelay: TimeInterval = 60.0

    func connect() {
        task = URLSession.shared.webSocketTask(with: url)
        task?.resume()
        reconnectDelay = 1.0  // Reset on successful connection
        listen()
    }

    private func listen() {
        task?.receive { [weak self] result in
            switch result {
            case .success(.string(let text)):
                if let data = text.data(using: .utf8),
                   let response = try? JSONDecoder().decode(BridgeResponse.self, from: data) {
                    DispatchQueue.main.async {
                        self?.bridges = response.bridges
                        self?.availableBridges = response.availableBridges
                    }
                }
                self?.listen()
            case .failure:
                self?.scheduleReconnect()
            default:
                self?.listen()
            }
        }
    }

    private func scheduleReconnect() {
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, maxReconnectDelay)  // Exponential backoff, cap at 60s
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.connect()
        }
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
    }
}
```

**Simplified info text generation (predictions now from backend):**
```swift
// BEFORE: ~223 lines of prediction logic with magic numbers
// AFTER: ~40 lines of simple formatting

static func generateInfoText(for bridge: Bridge, currentDate: Date) -> String {
    let live = bridge.liveData

    switch live.status.lowercased() {
    case "open":
        if let nextClosure = live.upcomingClosures?.first,
           nextClosure.time < currentDate.addingTimeInterval(3600) {
            let minutes = Int(currentDate.distance(to: nextClosure.time) / 60)
            return "Open, closing for \(nextClosure.type) in \(minutes)m"
        }
        return "Opened \(formatTime(live.lastUpdated))"

    case "closed":
        if let predicted = live.predicted {
            let lower = max(0, Int(currentDate.distance(to: predicted.lower) / 60))
            let upper = max(0, Int(currentDate.distance(to: predicted.upper) / 60))
            if lower == upper {
                return "Closed, opens in ~\(lower)m"
            }
            return "Closed, opens in \(lower)-\(upper)m"
        }
        return "Closed (longer than usual)"

    case "closing soon":
        // Check for upcoming closure first
        if let closure = live.upcomingClosures?.first {
            if closure.time < currentDate {
                // Boat is late - expected time passed but bridge still open
                return "Closing soon for \(closure.type) (was expected at \(formatTime(closure.time)))"
            }
            let minutes = Int(currentDate.distance(to: closure.time) / 60)
            if minutes < 60 {
                return "Closing for \(closure.type) in \(minutes)m"
            }
        }
        // Fall back to predicted (statistics-based)
        if let predicted = live.predicted {
            let lower = max(0, Int(currentDate.distance(to: predicted.lower) / 60))
            let upper = max(0, Int(currentDate.distance(to: predicted.upper) / 60))
            return "Closing in \(lower)-\(upper)m"
        }
        return "Closing soon"

    case "construction":
        if let predicted = live.predicted {
            let hours = Int(currentDate.distance(to: predicted.lower) / 3600)
            if hours > 24 {
                return "Closed for construction, opens in \(hours / 24)d"
            }
            return "Closed for construction, opens in \(hours)h"
        }
        return "Closed for construction (unknown opening)"

    case "opening":
        return "Opening now"

    default:
        return "Unknown status"
    }
}
```

### iOS Schema Reference

**New/changed types for iOS models:**

| Type | Fields | Notes |
|------|--------|-------|
| `PredictedTime` | `lower: Date`, `upper: Date` | NEW - prediction window |
| `AvailableBridge` | `id`, `name`, `region_short`, `region` | NEW - replaces hardcoded list |
| `BridgeData` | `static: StaticBridgeData`, `live: LiveBridgeData` | Wrapper with JSON keys `"static"`/`"live"` |
| `LiveBridgeData` | Add `predicted: PredictedTime?` | NEW field |
| `UpcomingClosure` | Add `expected_duration_minutes: Int?` | NEW field |
| `BridgeResponse` | `last_updated`, `available_bridges`, `bridges` | Top-level response |

**Key JSON mappings:**
- `region_short` (snake_case in JSON → `regionShort` in Swift)
- `last_updated`, `upcoming_closures`, `end_time`, `expected_duration_minutes` (all snake_case)

### iOS Implementation Notes

1. **Ping heartbeat**: Send ping every 30s to detect dead connections faster than TCP timeout
2. **Background/foreground**: Disconnect on background, reconnect on foreground via NotificationCenter
3. **Exponential backoff**: On disconnect, wait 1s → 2s → 4s → ... → 60s (cap) before reconnecting
4. **Remove hardcoded bridge list**: Use `availableBridges` from backend response
5. **Fallback polling**: `GET /bridges` returns same structure as WebSocket messages

---

## Multi-Platform Support

The REST + WebSocket architecture enables any platform without SDKs:

### Android (Kotlin + OkHttp)
```kotlin
class BridgeWebSocket {
    private val client = OkHttpClient()
    private var webSocket: WebSocket? = null

    fun connect() {
        val request = Request.Builder()
            .url("wss://api.bridgeup.app/ws")
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                val response = Json.decodeFromString<BridgeResponse>(text)
                // Update UI on main thread
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                // Reconnect with backoff
            }
        })
    }
}
```

### Web (JavaScript)
```javascript
class BridgeWebSocket {
    constructor() {
        this.connect();
    }

    connect() {
        this.ws = new WebSocket('wss://api.bridgeup.app/ws');

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.updateUI(data);
        };

        this.ws.onclose = () => {
            setTimeout(() => this.connect(), 3000);
        };
    }
}

// Or just fetch for simple use cases
async function getBridges() {
    const response = await fetch('https://api.bridgeup.app/bridges');
    return response.json();
}
```

### React/Next.js
```tsx
import { useEffect, useState } from 'react';

function useBridges() {
    const [bridges, setBridges] = useState([]);

    useEffect(() => {
        const ws = new WebSocket('wss://api.bridgeup.app/ws');
        ws.onmessage = (e) => setBridges(JSON.parse(e.data).bridges);
        ws.onclose = () => setTimeout(() => ws.close(), 3000);
        return () => ws.close();
    }, []);

    return bridges;
}
```

### Flutter (Dart)
```dart
import 'package:web_socket_channel/web_socket_channel.dart';

class BridgeService {
    final channel = WebSocketChannel.connect(
        Uri.parse('wss://api.bridgeup.app/ws'),
    );

    Stream<BridgeResponse> get bridges => channel.stream
        .map((data) => BridgeResponse.fromJson(jsonDecode(data)));
}
```

### Why This Is Better

| Aspect | Firebase | REST + WebSocket |
|--------|----------|------------------|
| iOS | Firebase SDK (2MB+) | URLSession (built-in) |
| Android | Firebase SDK (5MB+) | OkHttp (standard) |
| Web | Firebase JS (500KB+) | Native WebSocket |
| Vendor lock-in | Yes | No |
| Learning curve | Firebase-specific | Standard HTTP/WS |
| Cost control | Pay-per-read | Fixed $5/mo |
| Latency | ~1-2s | ~50-100ms |

### API Documentation (Free with FastAPI)

FastAPI auto-generates OpenAPI docs at `/docs`:

```python
app = FastAPI(
    title="Bridge Up API",
    description="Real-time bridge status for St. Lawrence Seaway",
    version="2.0.0",
)
```

Access at: `https://api.bridgeup.app/docs`

---

## Deployment

### Vultr Setup

1. Go to Vultr → Deploy → Cloud Compute
2. Select:
   - **Location**: Toronto
   - **OS**: Ubuntu 24.04 LTS x64
   - **Plan**: $5/mo (1 vCPU, 1GB RAM, 25GB SSD)
   - **Public IPv4**: Enabled
   - **Public IPv6**: Enabled (free)
   - **Automatic Backups**: Skip (data is reproducible)
   - **Hostname**: `bridgeup`

3. Add DNS A record: `api.bridgeup.app` → VPS IP

### Initial Setup (one-time)

SSH in and run:
```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Create shared network for multiple projects
docker network create web
```

Clone repo and deploy:
```bash
git clone https://github.com/yourusername/bridge-up-backend
cd bridge-up-backend
echo "OLD_JSON_ENDPOINT=xxx" > .env
echo "NEW_JSON_ENDPOINT=xxx" >> .env
docker compose up -d
```

### GitHub Actions Auto-Deploy

**1. Generate SSH key on VPS:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_deploy  # Copy this private key
```

**2. Add GitHub secrets** (repo → Settings → Secrets → Actions):
- `VPS_HOST` = your server IP
- `VPS_SSH_KEY` = the private key from step 1

**3. Add workflow file:**
```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to VPS
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: root
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /root/bridge-up-backend
            git pull
            docker compose up -d --build
```

Now every push to main auto-deploys.

---

## Costs

| Item | Cost |
|------|------|
| Vultr Toronto VPS | $5/mo |
| Domain (optional) | ~$10/yr |
| SSL (Let's Encrypt via Caddy) | Free |
| **Total** | **$5/mo fixed** |

---

## Migration Checklist

### Backend
- [x] Create `shared.py` (shared state, avoids circular imports)
- [x] Create `main.py` with FastAPI, WebSocket, scheduler, CORS
- [x] Create `predictions.py` with `calculate_prediction()` (logic moved from iOS)
- [x] Refactor `scraper.py`: replace `update_firestore()` → `update_json_and_broadcast()`
- [x] Refactor `scraper.py`: replace `update_bridge_history()` → `update_history()` + `append_to_history_file()`
- [x] Refactor `scraper.py`: import from `shared.py` instead of defining state locally
- [x] Add `predicted` field to bridge data before broadcast
- [x] Add `expected_duration_minutes` to closure objects
- [x] Refactor `stats_calculator.py`: remove Firestore params, return stats dict only
- [x] Update `Dockerfile` (uvicorn instead of waitress, port 8000)
- [x] Update `requirements.txt` (add fastapi, uvicorn; remove firebase-admin, waitress)
- [x] Update tests, add prediction tests (20+ new tests)
- [x] All tests pass (9 test files, 100% pass rate)

### Deploy
- [x] Setup Vultr VPS + Docker + `docker network create web`
- [x] Point DNS (`api.bridgeup.app` → VPS IP)
- [x] Create `docker-compose.yml` and `Caddyfile`
- [ ] Deploy with `docker compose up -d`
- [ ] Verify SSL works (Caddy auto-provisions)
- [ ] Verify scraping + WebSocket broadcasts
- [ ] Verify predictions in JSON output
- [ ] Run initial statistics calculation

### iOS (handled by iOS team after backend is ready)
- [ ] Remove Firebase SDK
- [ ] Remove hardcoded bridge list (use `availableBridges` from backend)
- [ ] Remove ~200 lines of prediction logic from `BridgeInfoGenerator.swift`
- [ ] Add WebSocket client with ping timer
- [ ] Add new model types: `PredictedTime`, `AvailableBridge`, `BridgeResponse`
- [ ] Update `LiveBridgeData`: add `predicted: PredictedTime?`
- [ ] Update `UpcomingClosure`: add `expectedDurationMinutes: Int?`
- [ ] Simplify info text generation (format backend predictions, handle "boat was late")
- [ ] Test connection + reconnection
- [ ] Submit app update

---

## Timeline

| Task | Effort |
|------|--------|
| Backend refactor (scraper, predictions, main.py) | 5-6 hrs |
| VPS setup + deploy | 1 hr |
| iOS refactor (remove Firebase, predictions, hardcoded list) | 4-5 hrs |
| Integration testing (both sides) | 2 hrs |
| **Total** | **~1.5 days** |

---

## Rollback Plan

**No parallel operation** - Hard cutover from Firebase to self-hosted.

**Pre-launch (current state):**
- Old Firebase scraper continues running during development
- New backend developed and tested locally/staging
- iOS app updated to use WebSocket (still in dev)

**Launch day:**
1. Deploy new backend to VPS
2. Verify scraping + WebSocket working
3. Submit iOS app update (already pointing to new backend)
4. Stop old Firebase scraper (optional - no cost if no writes)

**If issues arise post-launch:**
- Fix forward (no Firebase fallback)
- Backend issues: SSH into VPS, fix, redeploy
- iOS issues: Submit hotfix update
- Firebase data remains read-only as historical reference (no active use)

---

## Open Questions

| Question | Status |
|----------|--------|
| Final domain? | ✅ `api.bridgeup.app` (WS: `wss://api.bridgeup.app/ws`) |
| Rate limiting on `/bridges`? | ✅ None initially. Can add via Caddy if needed. |
| Transition period? | ✅ No parallel operation - hard cutover (see Rollback Plan) |
| Status field casing? | ✅ Confirmed - iOS handles capitalized values via `.lowercased()` |
| Schema compatibility? | ✅ Confirmed - iOS decodes by key name, order doesn't matter |

---

## What You Keep

- All 15 bridges monitored
- Real-time status updates (actually faster via WebSocket)
- Statistics and predictions
- History tracking (300 entries per bridge)
- Smart backoff on failures
- Concurrent scraping
- Daily stats recalculation

## What You Lose

- Nothing

## What You Gain

- **Fixed $5/mo cost** (no Firebase anxiety)
- **Faster updates** (WebSocket vs Firestore ~1-2s)
- **Much simpler iOS code**:
  - No Firebase SDK
  - No hardcoded bridge list (dynamic from backend)
  - No prediction logic (~200 lines removed)
  - iOS just formats what backend provides
- **Smarter predictions** (backend can improve without iOS update)
- **Multi-platform ready**:
  - Android: Standard OkHttp WebSocket
  - Web: Native WebSocket API + CORS enabled
  - Flutter/React Native: No SDKs needed
  - Free OpenAPI docs at `/docs`
- **Full control** (your server, your data)
- **Room to grow** (same server can host other projects)
- **Toronto datacenter** (low latency for Canadian users)
