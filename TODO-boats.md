# Boat Tracking Implementation Plan

## Overview

Real-time vessel tracking for Bridge Up via:
- **Local AIS Dispatchers** (UDP, real-time) - St. Catharines, Port Colborne (future)
- **AISHub API** (polled every 61s) - Welland + Montreal

## Architecture

```
    AIS Dispatchers          AISHub API
    (UDP :10110)             (61s polls)
         │                        │
         └──────────┬─────────────┘
                    ▼
              boat_tracker.py
              (VesselRegistry)
                    │
                    ▼
              GET /boats
              (REST only)
```

**Key decisions**:
- REST polling only (no WebSocket for boats)
- In-memory only (no persistence)
- 5-second update interval
- 30-min "moving" filter, 60-min cleanup

---

## Configuration

### Environment Variables
```bash
# .env (NEVER commit - already in .gitignore)
AISHUB_API_KEY=<your_key_here>
AISHUB_URL=https://data.aishub.net/ws.php
AIS_UDP_PORT=10110
AIS_UDP_ENABLED=true
```

**Security**: Load key via `os.getenv('AISHUB_API_KEY')` - never hardcode, never log, never expose in API responses.

### Region Bounding Boxes

**Verified**: All 15 bridges covered with ~15km buffer to track approaching vessels.

```python
BOAT_REGIONS = {
    "welland": {
        "name": "Welland Canal",
        # Extended coverage: Lake Ontario entrance (north) to Lake Erie (south)
        # ~15km buffer beyond bridges to catch approaching vessels
        # Bridges: Lakeshore, Carlton, Queenston, Glendale, Hwy20, Main, Mellanby, Clarence
        "bounds": {"lat_min": 42.75, "lat_max": 43.35, "lon_min": -79.35, "lon_max": -79.10}
    },
    "montreal": {
        "name": "Montreal South Shore",
        # Extended coverage: St. Lawrence Seaway approaches
        # ~15km buffer beyond bridges to catch approaching vessels
        # Bridges: Victoria x2, Sainte-Catherine, CP Railway 7A/7B, St-Louis, Larocque
        "bounds": {"lat_min": 45.15, "lat_max": 45.60, "lon_min": -74.20, "lon_max": -73.35}
    }
}

def get_vessel_region(lat: float, lng: float) -> str | None:
    """Assign vessel to region based on position."""
    for region_id, config in BOAT_REGIONS.items():
        b = config["bounds"]
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lng <= b["lon_max"]:
            return region_id
    return None  # Outside all regions - vessel ignored
```

### Vessel Types (Complete AIS Type Codes)
```python
# AIS vessel type code -> (display_name, category)
VESSEL_TYPES = {
    # Category 2x: Wing in Ground
    20: ("WIG", "other"),

    # Category 3x: Special craft
    30: ("Fishing", "fishing"),
    31: ("Towing", "tug"),
    32: ("Towing (large)", "tug"),
    33: ("Dredger", "other"),
    34: ("Diving Ops", "other"),
    35: ("Military", "other"),
    36: ("Sailing", "sailing"),
    37: ("Pleasure Craft", "pleasure"),

    # Category 4x: High-Speed Craft
    40: ("High-Speed Craft", "passenger"),
    41: ("HSC - Hazard A", "passenger"),
    42: ("HSC - Hazard B", "passenger"),
    43: ("HSC - Hazard C", "passenger"),
    44: ("HSC - Hazard D", "passenger"),
    49: ("HSC - No info", "passenger"),

    # Category 5x: Special craft
    50: ("Pilot Vessel", "other"),
    51: ("SAR", "other"),
    52: ("Tug", "tug"),
    53: ("Port Tender", "other"),
    54: ("Anti-Pollution", "other"),
    55: ("Law Enforcement", "other"),
    56: ("Local Vessel", "other"),
    57: ("Local Vessel", "other"),
    58: ("Medical", "other"),
    59: ("Special Craft", "other"),

    # Category 6x: Passenger
    60: ("Passenger", "passenger"),
    61: ("Passenger - Hazard A", "passenger"),
    62: ("Passenger - Hazard B", "passenger"),
    63: ("Passenger - Hazard C", "passenger"),
    64: ("Passenger - Hazard D", "passenger"),
    69: ("Passenger - No info", "passenger"),

    # Category 7x: Cargo
    70: ("Cargo", "cargo"),
    71: ("Cargo - Hazard A", "cargo"),
    72: ("Cargo - Hazard B", "cargo"),
    73: ("Cargo - Hazard C", "cargo"),
    74: ("Cargo - Hazard D", "cargo"),
    79: ("Cargo - No info", "cargo"),

    # Category 8x: Tanker
    80: ("Tanker", "tanker"),
    81: ("Tanker - Hazard A", "tanker"),
    82: ("Tanker - Hazard B", "tanker"),
    83: ("Tanker - Hazard C", "tanker"),
    84: ("Tanker - Hazard D", "tanker"),
    89: ("Tanker - No info", "tanker"),

    # Category 9x: Other
    90: ("Other", "other"),
    91: ("Other - Hazard A", "other"),
    92: ("Other - Hazard B", "other"),
    93: ("Other - Hazard C", "other"),
    94: ("Other - Hazard D", "other"),
}

def get_vessel_type_info(type_code: int) -> tuple[str, str]:
    """Get (display_name, category) for vessel type code."""
    if type_code in VESSEL_TYPES:
        return VESSEL_TYPES[type_code]
    if 0 <= type_code < 100:
        return ("Unknown", "other")
    return ("Invalid", "other")
```

---

## AIS Message Handling

### Message Types
| Type | Purpose | Action |
|------|---------|--------|
| 1, 2, 3, 18, 19 | Vessel position | PROCESS (dynamic data) |
| 5, 24 | Vessel static data | PROCESS (name, dimensions, type) |
| 4, 20, 22 | Base station/channel mgmt | **SKIP** (~55% of traffic) |

### pyais Usage (CORRECT API)
```python
from pyais import decode

# Single message
raw = b"!AIVDM,1,1,,B,15NG6V0P01G?cFhE`R2IU?wn28R>,0*05"
decoded = decode(raw)
data = decoded.asdict()  # Returns dict with 'mmsi', 'lat', 'lon', etc.

# Access fields
mmsi = data['mmsi']
lat = data.get('lat')  # May be None for type 5 messages
lon = data.get('lon')
speed = data.get('speed')  # In knots * 10
heading = data.get('heading')
ship_type = data.get('ship_type')  # Only in type 5/24
ship_name = data.get('shipname')   # Only in type 5/24

# Note: Position messages (1,2,3,18,19) have lat/lon/speed/heading
# Static messages (5,24) have shipname/ship_type/dimensions
# Must merge by MMSI to get complete vessel info
```

### UDP Listener (Async with DatagramProtocol)
```python
import asyncio
from pyais import decode
from loguru import logger

class UDPProtocol(asyncio.DatagramProtocol):
    """Async UDP receiver using asyncio.DatagramProtocol."""

    def __init__(self, station_id: str, registry: "VesselRegistry"):
        self.station_id = station_id
        self.registry = registry
        self.vessel_buffer: dict[int, dict] = {}
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info(f"UDP:{self.station_id} listening")

    def datagram_received(self, data: bytes, addr: tuple):
        """Called for each UDP packet received."""
        try:
            decoded = decode(data)
            msg = decoded.asdict()
        except Exception as e:
            logger.debug(f"UDP:{self.station_id} decode error: {e}")
            return

        # Skip base station messages
        if msg.get('msg_type') in (4, 20, 22):
            return

        mmsi = msg.get('mmsi')
        if not mmsi:
            return

        # Validate MMSI (ships are 200M-799M range)
        if not (200_000_000 <= mmsi <= 799_999_999):
            return

        # Buffer update (last-write-wins per MMSI)
        self.vessel_buffer[mmsi] = {
            "lat": msg.get('lat'),
            "lng": msg.get('lon'),
            "speed_knots": (msg.get('speed') or 0) / 10,  # AIS speed is knots * 10
            "heading": msg.get('heading'),
            "course": msg.get('course'),
            "name": sanitize_vessel_name(msg.get('shipname')),
            "type": msg.get('ship_type'),
            "destination": msg.get('destination'),
            "dimensions": {
                "length": msg.get('to_bow', 0) + msg.get('to_stern', 0),
                "width": msg.get('to_port', 0) + msg.get('to_starboard', 0)
            } if msg.get('to_bow') else None
        }

    def error_received(self, exc):
        logger.error(f"UDP:{self.station_id} error: {exc}")


class UDPListener:
    """Manages UDP socket lifecycle and periodic buffer flush."""

    def __init__(self, station_id: str, registry: "VesselRegistry", port: int = 10110):
        self.station_id = station_id
        self.registry = registry
        self.port = port
        self.protocol: UDPProtocol | None = None
        self.transport = None
        self._flush_task: asyncio.Task | None = None

    async def start(self):
        """Start UDP listener and flush task."""
        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(self.station_id, self.registry),
            local_addr=('0.0.0.0', self.port)
        )
        # Start periodic flush (runs even if no messages arrive)
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(f"UDP:{self.station_id} started on port {self.port}")

    async def stop(self):
        """Stop UDP listener."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        if self.transport:
            self.transport.close()
        logger.info(f"UDP:{self.station_id} stopped")

    async def _periodic_flush(self):
        """Flush buffer every 5 seconds (runs independently of message receipt)."""
        while True:
            await asyncio.sleep(5.0)
            await self._flush_buffer()

    async def _flush_buffer(self):
        """Send buffered vessels to registry."""
        if not self.protocol or not self.protocol.vessel_buffer:
            return

        buffer = self.protocol.vessel_buffer
        self.protocol.vessel_buffer = {}  # Reset for next period

        for mmsi, data in buffer.items():
            # Skip if no position data
            if data.get('lat') is None or data.get('lng') is None:
                continue
            await self.registry.update_vessel(mmsi, data, f"udp:{self.station_id}")


def sanitize_vessel_name(name: str | None) -> str | None:
    """Clean vessel name for JSON/display."""
    if not name:
        return None
    # Remove non-printable and control characters
    name = ''.join(c for c in name if c.isprintable() and c not in '\t\n\r\v\f')
    name = ' '.join(name.split()).strip()  # Normalize whitespace
    return name if name else None
```

---

## Vessel Registry (Async, Thread-Safe)

```python
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

class VesselRegistry:
    def __init__(self):
        self.vessels: dict[int, dict] = {}
        self._lock = asyncio.Lock()
        self.udp_station_last_message: dict[str, datetime] = {}  # Per-station tracking

    async def update_vessel(self, mmsi: int, data: dict, source: str):
        async with self._lock:
            now = datetime.now(timezone.utc)

            # Track per-station UDP timestamps (identified by source IP via station_id)
            if source.startswith("udp:"):
                station_id = source.split(":")[1]  # "udp:sct" -> "sct"
                self.udp_station_last_message[station_id] = now

            # Filter out vessels outside defined regions
            lat, lng = data.get("lat"), data.get("lng")
            if lat is None or lng is None:
                return

            region = get_vessel_region(lat, lng)
            if region is None:
                return  # Outside Welland/Montreal - ignore

            existing = self.vessels.get(mmsi)

            if existing is None:
                # New vessel
                data["last_seen"] = now.isoformat()
                data["last_moved"] = now.isoformat()
                data["source"] = source
                data["region"] = region
                data["mmsi"] = mmsi
                self.vessels[mmsi] = data
                return

            # Deduplication logic
            existing_age = (now - datetime.fromisoformat(existing["last_seen"])).total_seconds()

            # UDP always wins (real-time, ~1s latency)
            if source.startswith("udp:"):
                self._merge_vessel_data(existing, data, source, now, region)
                return

            # AISHub only updates if existing data is stale (>60s)
            # Short threshold because vessel may leave UDP range quickly
            if source == "aishub" and existing_age > 60:
                self._merge_vessel_data(existing, data, source, now, region)

    def _merge_vessel_data(self, existing: dict, new_data: dict, source: str,
                           now: datetime, region: str):
        """Merge new data into existing vessel record."""
        # Check if position changed significantly (>10m)
        if self._has_position_changed(existing, new_data):
            existing["last_moved"] = now.isoformat()

        # Update fields (preserve non-null values)
        for key in ["lat", "lng", "speed_knots", "heading", "course", "destination"]:
            if new_data.get(key) is not None:
                existing[key] = new_data[key]

        # Merge static data (name, type, dimensions) - only update if new is non-null
        if new_data.get("name"):
            existing["name"] = new_data["name"]
        if new_data.get("type"):
            existing["type"] = new_data["type"]
        if new_data.get("dimensions"):
            existing["dimensions"] = new_data["dimensions"]

        existing["last_seen"] = now.isoformat()
        existing["source"] = source
        existing["region"] = region

    def _has_position_changed(self, old: dict, new: dict, threshold_m: float = 10) -> bool:
        """Check if position changed by more than threshold meters."""
        if old.get("lat") is None or new.get("lat") is None:
            return True

        # Approximate distance (good enough for 10m threshold)
        lat_diff = abs(old["lat"] - new["lat"]) * 111320  # meters per degree
        lng_diff = abs(old["lng"] - new["lng"]) * 78710   # meters at ~45 degrees lat
        return (lat_diff ** 2 + lng_diff ** 2) ** 0.5 > threshold_m

    def get_udp_status(self) -> dict:
        """Get UDP station status for health/API response."""
        now = datetime.now(timezone.utc)
        stations = {}
        for station_id, last_msg in self.udp_station_last_message.items():
            age = (now - last_msg).total_seconds() if last_msg else None
            stations[station_id] = {
                "active": age is not None and age < 30,  # 30s threshold
                "last_message": last_msg.isoformat() if last_msg else None
            }
        return stations

    def get_moving_vessels(self, max_idle_minutes: int = 30) -> list[dict]:
        """Get vessels that moved within max_idle_minutes. SYNC method."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_idle_minutes)

        moving = []
        for mmsi, vessel in self.vessels.items():
            last_moved = datetime.fromisoformat(vessel["last_moved"])
            if last_moved >= cutoff:
                moving.append(vessel)
        return moving

    async def cleanup_stale_vessels(self, max_age_minutes: int = 60):
        """Remove vessels not seen in max_age_minutes. Run every 5 min."""
        async with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
            stale = [
                mmsi for mmsi, v in self.vessels.items()
                if datetime.fromisoformat(v["last_seen"]) < cutoff
            ]
            for mmsi in stale:
                del self.vessels[mmsi]
            if stale:
                logger.info(f"Cleaned up {len(stale)} stale vessels")
```

---

## AISHub Poller (with Exponential Backoff)

```python
import httpx
import os
from datetime import datetime, timezone, timedelta

class AISHubError(Exception):
    """AISHub API error."""
    pass

class AISHubPoller:
    def __init__(self, registry: VesselRegistry):
        self.registry = registry
        self.current_region = "welland"
        self.last_poll: datetime | None = None
        self.last_error: str | None = None
        self.failure_count = 0
        self.next_retry: datetime | None = None

    def _calculate_backoff(self) -> int:
        """Exponential backoff: 61s minimum (due to rate limit), then doubling, capped at 300s."""
        if self.failure_count <= 1:
            return 61
        return min(61 * (2 ** (self.failure_count - 1)), 300)

    async def poll(self):
        """Poll AISHub with exponential backoff on failure."""
        now = datetime.now(timezone.utc)

        # Check if we're in backoff period
        if self.next_retry and now < self.next_retry:
            return

        try:
            vessels = await self._fetch_region(self.current_region)

            for vessel in vessels:
                await self.registry.update_vessel(vessel["mmsi"], vessel, "aishub")

            # Success - reset backoff
            if self.failure_count > 0:
                logger.info(f"AISHub: Recovered after {self.failure_count} failures")
            self.failure_count = 0
            self.next_retry = None
            self.last_error = None
            logger.debug(f"AISHub: Fetched {len(vessels)} vessels for {self.current_region}")

        except Exception as e:
            self.failure_count += 1
            backoff_secs = self._calculate_backoff()
            self.next_retry = now + timedelta(seconds=backoff_secs)
            self.last_error = str(e)[:100]

            if self.failure_count == 1:
                logger.warning(f"AISHub: {e}")
            else:
                logger.warning(f"AISHub: {e} (attempt #{self.failure_count}, retry in {backoff_secs}s)")

        finally:
            self.last_poll = now
            # Alternate region regardless of success/failure
            self.current_region = "montreal" if self.current_region == "welland" else "welland"

    async def _fetch_region(self, region: str) -> list[dict]:
        """Fetch vessels from AISHub for a region."""
        api_key = os.getenv('AISHUB_API_KEY')
        if not api_key:
            raise ValueError("AISHUB_API_KEY not configured")

        base_url = os.getenv('AISHUB_URL', 'https://data.aishub.net/ws.php')
        bounds = BOAT_REGIONS[region]["bounds"]

        params = {
            "username": api_key,
            "format": "1",  # JSON
            "output": "json",
            "compress": "0",
            "latmin": bounds["lat_min"],
            "latmax": bounds["lat_max"],
            "lonmin": bounds["lon_min"],
            "lonmax": bounds["lon_max"],
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

        # AISHub returns: [{"ERROR":false, ...}, [vessels]]
        if not isinstance(data, list) or len(data) < 2:
            # Empty response = no vessels in area (not an error)
            if isinstance(data, list) and len(data) == 1:
                header = data[0]
                if header.get("ERROR"):
                    raise AISHubError(f"API error: {header.get('ERROR_MESSAGE', 'Unknown')}")
                return []  # No vessels
            raise AISHubError(f"Unexpected response format: {type(data)}")

        header, vessels = data[0], data[1]

        if header.get("ERROR"):
            raise AISHubError(f"API error: {header.get('ERROR_MESSAGE', 'Unknown')}")

        # Convert AISHub format to our format
        result = []
        for v in vessels:
            result.append({
                "mmsi": v.get("MMSI"),
                "name": sanitize_vessel_name(v.get("NAME")),
                "lat": v.get("LATITUDE"),
                "lng": v.get("LONGITUDE"),
                "speed_knots": v.get("SOG"),
                "heading": v.get("HEADING"),
                "course": v.get("COG"),
                "type": v.get("TYPE"),
                "destination": v.get("DEST"),
                "dimensions": {
                    "length": v.get("A", 0) + v.get("B", 0),
                    "width": v.get("C", 0) + v.get("D", 0)
                } if v.get("A") else None
            })
        return result
```

**Backoff schedule**: 61s -> 122s -> 244s -> 300s (cap) - respects 60s rate limit

---

## API Response

### GET /boats

```json
{
  "last_updated": "2025-12-25T15:30:00-05:00",
  "vessel_count": 8,
  "status": {
    "udp": {
      "sct": {"active": true, "last_message": "2025-12-25T15:29:45-05:00"},
      "pc": {"active": false, "last_message": null}
    },
    "aishub": {
      "ok": true,
      "last_poll": "2025-12-25T15:29:00-05:00",
      "last_error": null,
      "failure_count": 0
    },
    "data_quality": "good"
  },
  "vessels": [
    {
      "mmsi": 316031772,
      "name": "FEDERAL WILLIAM PAUL",
      "type": 70,
      "type_name": "Cargo",
      "type_category": "cargo",
      "position": {"lat": 42.98225, "lng": -79.21930},
      "heading": 14,
      "course": 15,
      "speed_knots": 6.6,
      "destination": "DULUTH",
      "dimensions": {"length": 225, "width": 23},
      "last_seen": "2025-12-25T15:29:45-05:00",
      "source": "udp:sct",
      "region": "welland"
    }
  ]
}
```

### Data Quality States

```python
def get_data_quality(udp_status: dict, aishub_ok: bool, vessel_count: int) -> str:
    """Determine data quality for client display."""
    any_udp_active = any(s["active"] for s in udp_status.values())

    if any_udp_active and aishub_ok:
        return "good"  # Both sources working
    elif any_udp_active or aishub_ok:
        return "degraded"  # One source working
    else:
        return "offline"  # No sources working
```

**Notes**:
- `status.data_quality`: "good" | "degraded" | "offline"
- `status.udp`: Per-station status (identified by IP -> station_id mapping)
- `dimensions`: null if unknown (not all vessels report this)
- `region`: always "welland" or "montreal" (vessels outside regions are filtered out)

### Client State Logic

| data_quality | vessel_count | Show |
|--------------|--------------|------|
| "good" / "degraded" | 0 | "No boats in area" |
| "good" / "degraded" | >0 | Boats on map |
| "offline" | any | "Unable to load boats" (error state) |

---

## Startup Integration

```python
# main.py additions

from boat_tracker import BoatTracker

# Global boat tracker (like connected_clients)
boat_tracker: BoatTracker | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global boat_tracker

    # Existing startup...
    shared.main_loop = asyncio.get_running_loop()
    initialize_data_files()

    # Start boat tracker
    if os.getenv('AIS_UDP_ENABLED', 'false').lower() == 'true':
        boat_tracker = BoatTracker()
        await boat_tracker.start()

    # Existing scheduler setup...
    scheduler.start()

    yield

    # Shutdown
    if boat_tracker:
        await boat_tracker.stop()
    scheduler.shutdown(wait=False)


class BoatTracker:
    """Orchestrates UDP listeners and AISHub poller."""

    def __init__(self):
        self.registry = VesselRegistry()
        self.udp_listeners: list[UDPListener] = []
        self.aishub_poller = AISHubPoller(self.registry)
        self._poll_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

    async def start(self):
        """Start all boat tracking components."""
        # Start UDP listener for St. Catharines
        udp_port = int(os.getenv('AIS_UDP_PORT', '10110'))
        sct_listener = UDPListener("sct", self.registry, udp_port)
        await sct_listener.start()
        self.udp_listeners.append(sct_listener)

        # Start AISHub poller (every 61s, alternating regions)
        self._poll_task = asyncio.create_task(self._poll_loop())

        # Start cleanup task (every 5 min)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("Boat tracker started")

    async def stop(self):
        """Stop all boat tracking components."""
        for listener in self.udp_listeners:
            await listener.stop()

        if self._poll_task:
            self._poll_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()

        logger.info("Boat tracker stopped")

    async def _poll_loop(self):
        """Poll AISHub every 61 seconds."""
        while True:
            await self.aishub_poller.poll()
            await asyncio.sleep(61)

    async def _cleanup_loop(self):
        """Clean up stale vessels every 5 minutes."""
        while True:
            await asyncio.sleep(300)
            await self.registry.cleanup_stale_vessels(max_age_minutes=60)
```

---

## Health Endpoint Integration

```python
# main.py - Update health endpoint (make it async)

@app.get("/health", response_model=HealthResponse)
async def health():  # Changed to async
    """Health check endpoint for monitoring."""
    # ... existing bridge health logic ...

    # Add boat tracker status
    boat_status = None
    if boat_tracker:
        moving = boat_tracker.registry.get_moving_vessels()  # Sync method
        boat_status = {
            "vessel_count": len(boat_tracker.registry.vessels),
            "moving_count": len(moving),
            "udp_stations": boat_tracker.registry.get_udp_status(),
            "aishub": {
                "ok": boat_tracker.aishub_poller.failure_count == 0,
                "last_poll": boat_tracker.aishub_poller.last_poll.isoformat()
                            if boat_tracker.aishub_poller.last_poll else None,
                "failure_count": boat_tracker.aishub_poller.failure_count,
                "last_error": boat_tracker.aishub_poller.last_error
            },
            "data_quality": get_data_quality(
                boat_tracker.registry.get_udp_status(),
                boat_tracker.aishub_poller.failure_count == 0,
                len(moving)
            )
        }

    return {
        # ... existing fields ...
        "boats": boat_status
    }
```

---

## Dependencies

```txt
# requirements.txt additions
pyais>=2.6.0          # AIS/NMEA decoder
httpx>=0.24.0         # Async HTTP client for AISHub
```

Note: Using `>=` not `==` for flexibility. Latest pyais is 2.14.0.

---

## Docker

```yaml
# docker-compose.yml
ports:
  - "8000:8000"
  - "10110:10110/udp"  # /udp suffix required!
environment:
  - AIS_UDP_PORT=10110
  - AIS_UDP_ENABLED=true
  - AISHUB_API_KEY=${AISHUB_API_KEY}
  - AISHUB_URL=https://data.aishub.net/ws.php
```

---

## Testing

### Manual Testing
```bash
# Send test UDP packet
echo '!AIVDM,1,1,,B,13u@pJ`P00PJqfPMF9R<2?v60<0q,0*71' | nc -u localhost 10110

# Check endpoint
curl http://localhost:8000/boats | jq
```

### Unit Tests (to create)
| Test File | Coverage |
|-----------|----------|
| `test_boat_registry.py` | VesselRegistry CRUD, deduplication, cleanup |
| `test_boat_aishub.py` | AISHub response parsing, backoff logic |
| `test_boat_regions.py` | Bounding box filtering, edge cases |
| `test_boat_udp.py` | NMEA decoding, buffer flush, sanitization |

### Test Scenarios
```python
# test_boat_registry.py
def test_udp_beats_aishub():
    """UDP source always wins over AISHub."""

def test_aishub_updates_stale_udp():
    """AISHub updates vessel when UDP data is >60s old."""

def test_aishub_ignored_when_udp_fresh():
    """AISHub ignored when UDP data is <60s old."""

def test_vessel_outside_region_filtered():
    """Vessels outside bounding boxes are not stored."""

def test_cleanup_removes_stale():
    """Vessels not seen in 60 min are removed."""

def test_moving_filter():
    """Only vessels that moved in last 30 min returned."""
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `boat_config.py` | Regions, types, station configs |
| `boat_tracker.py` | VesselRegistry, UDPListener, AISHubPoller, BoatTracker |
| `main.py` (modify) | Add `/boats` endpoint, start tracker in lifespan |
| `tests/test_boat_*.py` | Test files |

---

## Implementation Checklist

### Phase 1 (MVP)
- [ ] `boat_config.py` with regions and types
- [ ] VesselRegistry with dedup/cleanup
- [ ] AISHub poller with backoff
- [ ] UDP listener with DatagramProtocol
- [ ] GET /boats endpoint
- [ ] Moving filter (30 min)
- [ ] Lifespan integration

### Phase 2
- [ ] Add to /health endpoint
- [ ] Port Colborne station
- [ ] Unit tests

---

## UDP Station Identification

Stations are identified by their source IP address. Configure a mapping:

```python
# boat_config.py
UDP_STATIONS = {
    # IP address -> station_id
    # These are the AIS dispatcher IPs that will send UDP to our server
    "192.168.1.100": "sct",  # St. Catharines dispatcher
    "192.168.1.101": "pc",   # Port Colborne dispatcher (future)
}

def get_station_id(addr: tuple) -> str:
    """Get station ID from UDP source address."""
    ip = addr[0]
    return UDP_STATIONS.get(ip, f"unknown_{ip}")
```

Then in UDPProtocol:
```python
def datagram_received(self, data: bytes, addr: tuple):
    station_id = get_station_id(addr)
    # ... rest of processing with station_id
```

---

## Codebase Patterns Reference

### Concurrency (from scraper.py)
- Boat tracker is **fully async** - uses `asyncio.Lock()` (NOT threading.Lock)
- Bridge scraper uses threads (ThreadPoolExecutor) - that's why it uses threading.Lock

### Backoff (from scraper.py:handle_region_failure)
```python
# Bridge scraper pattern (2^n, cap 300s, starts at 2s)
wait_seconds = min(2 ** failure_count, 300)

# AISHub pattern (61s minimum due to rate limit)
wait_seconds = min(61 * (2 ** (failure_count - 1)), 300)
```

### Logging (from scraper.py)
```python
logger.debug()    # High-frequency, normal operations
logger.info()     # State changes, startup/shutdown, recovery
logger.warning()  # Expected errors, retrying
logger.error()    # Unexpected errors (should be rare)
```
