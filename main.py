# main.py
"""
FastAPI application with WebSocket for real-time bridge updates.

This is the main entry point for the migrated backend:
- WebSocket endpoint for real-time push to iOS/web clients
- HTTP endpoints for fallback and health monitoring
- APScheduler for background scraping tasks
- CORS configuration for web clients
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Set
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
import copy
import json
import asyncio
import os
import threading

import shared
from shared import (
    TIMEZONE, last_known_state, last_known_state_lock, connected_clients,
    bridges_file_lock, WebSocketClient
)

# Valid WebSocket channels and their allowed region filters
CHANNEL_REGIONS = {
    "boats": {"welland", "montreal"},
    "bridges": {"sct", "pc", "mss", "k", "sbs"},
}


def parse_channel(channel: str) -> tuple:
    """
    Parse channel string into (base, region).

    Examples:
        "boats" -> ("boats", None)
        "boats:welland" -> ("boats", "welland")
        "bridges:sct" -> ("bridges", "sct")
        "invalid:foo" -> (None, None)
        123 -> (None, None)  # Non-string input
    """
    if not isinstance(channel, str):
        return None, None
    if ":" in channel:
        base, region = channel.split(":", 1)
        if base in CHANNEL_REGIONS and region in CHANNEL_REGIONS[base]:
            return base, region
        return None, None  # Invalid

    if channel in CHANNEL_REGIONS:
        return channel, None  # Valid base channel, no region filter

    return None, None  # Invalid


def validate_channels(requested: list) -> set:
    """Filter to valid channels only."""
    valid = set()
    for ch in requested:
        base, region = parse_channel(ch)
        if base:
            valid.add(ch)
    return valid


from config import BRIDGE_KEYS, BRIDGE_DETAILS
from boat_config import VESSEL_IDLE_THRESHOLD_MINUTES
from maintenance import get_maintenance_info, validate_maintenance_file
from loguru import logger

# Boat tracker (initialized in lifespan if enabled)
boat_tracker = None

# Maintenance scraper control (seasonal - winter only)
ENABLE_MAINTENANCE_SCRAPER = os.getenv("ENABLE_MAINTENANCE_SCRAPER", "true").lower() == "true"

# Boat WebSocket broadcast interval (check for changes every N seconds)
BOATS_CHECK_INTERVAL_SECONDS = 10

# Startup maintenance scraper thread (tracked for status monitoring)
_maintenance_startup_thread: Optional[threading.Thread] = None

# Lock to prevent concurrent maintenance scraper runs (startup thread + scheduled job)
_maintenance_scraper_lock = threading.Lock()


def get_real_client_ip(request: Request) -> str:
    """
    Get the real client IP, checking proxy headers first.

    When behind a reverse proxy (Caddy/Nginx), the direct client IP
    is the proxy, not the actual user. The proxy sets X-Forwarded-For
    or X-Real-IP headers with the real client IP.

    Security note: We take the RIGHTMOST IP from X-Forwarded-For because:
    - Caddy APPENDS the real client IP to any existing header
    - A malicious client could send "X-Forwarded-For: spoofed.ip"
    - Caddy would forward "X-Forwarded-For: spoofed.ip, real.client.ip"
    - Taking rightmost gives us what Caddy added (the real IP)
    """
    # X-Forwarded-For: Caddy appends the real client IP as the rightmost entry
    # Format: "client-provided, ..., caddy-added-real-ip"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the rightmost (last) IP - this is what Caddy adds
        return forwarded.split(",")[-1].strip()

    # Some proxies use X-Real-IP instead
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fallback to direct connection (local dev or no proxy)
    # Check both request.client and request.client.host - host can be None with Unix sockets
    return request.client.host if request.client and request.client.host else "127.0.0.1"


# Rate limiter (in-memory, uses real client IP behind proxy)
limiter = Limiter(key_func=get_real_client_ip)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return 429 with Retry-After header when rate limit exceeded."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": str(exc.detail)
        },
        headers={"Retry-After": "60"}
    )


# === Response Models for API Documentation ===

class EndpointsInfo(BaseModel):
    docs: str = "/docs"
    health: str = "/health"
    bridges: str = "/bridges"
    boats: str = "/boats"
    websocket: str = "wss://api.bridgeup.app/ws"


class RootResponse(BaseModel):
    """API root response with endpoint discovery."""
    name: str = "Bridge Up API"
    description: str = "Real-time bridge status for St. Lawrence Seaway"
    website: str = "https://bridgeup.app"
    endpoints: EndpointsInfo

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Bridge Up API",
                "description": "Real-time bridge status for St. Lawrence Seaway",
                "website": "https://bridgeup.app",
                "endpoints": {
                    "docs": "/docs",
                    "health": "/health",
                    "bridges": "/bridges",
                    "boats": "/boats",
                    "websocket": "wss://api.bridgeup.app/ws"
                }
            }
        }
    }


class MaintenanceInfo(BaseModel):
    """
    Maintenance override system status.

    Note: last_scrape_success and last_scrape_attempt/last_scrape_error are mutually exclusive.
    On successful scrape: only last_scrape_success is set.
    On failed scrape: last_scrape_attempt and last_scrape_error are set (no last_scrape_success).
    """
    file_exists: bool = Field(description="Whether maintenance.json exists")
    closure_count: int = Field(description="Number of bridge closures defined")
    source_url: Optional[str] = Field(default=None, description="URL of maintenance data source")
    last_scrape_success: Optional[str] = Field(default=None, description="Last successful scrape timestamp (mutually exclusive with last_scrape_attempt)")
    last_scrape_attempt: Optional[str] = Field(default=None, description="Last failed scrape attempt timestamp (mutually exclusive with last_scrape_success)")
    last_scrape_error: Optional[str] = Field(default=None, description="Last scrape error message (only present with last_scrape_attempt)")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(description="API status: ok, warning, or error", examples=["ok"])
    status_message: str = Field(description="Human-readable status explanation")
    last_updated: Optional[str] = Field(description="Last time bridge data changed")
    last_scrape: Optional[str] = Field(description="Last successful scrape timestamp")
    last_scrape_had_changes: bool = Field(description="Whether last scrape found changes")
    statistics_last_updated: Optional[str] = Field(description="Last time statistics were calculated")
    bridges_count: int = Field(description="Number of bridges in data")
    boats_count: int = Field(description="Number of vessels currently tracked")
    websocket_clients: int = Field(description="Connected WebSocket clients")
    websocket_bridges_subscribers: int = Field(description="WebSocket clients subscribed to bridges")
    websocket_boats_subscribers: int = Field(description="WebSocket clients subscribed to boats")
    maintenance: Optional[MaintenanceInfo] = Field(default=None, description="Maintenance override system status")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "status_message": "All systems operational",
                "last_updated": "2025-12-24T12:25:00-05:00",
                "last_scrape": "2025-12-24T12:30:05-05:00",
                "last_scrape_had_changes": False,
                "statistics_last_updated": "2025-12-24T03:00:00-05:00",
                "bridges_count": 15,
                "boats_count": 4,
                "websocket_clients": 3,
                "websocket_bridges_subscribers": 2,
                "websocket_boats_subscribers": 1,
                "maintenance": {
                    "file_exists": True,
                    "closure_count": 2,
                    "source_url": "https://greatlakes-seaway.com/en/for-our-communities/infrastructure-maintenance/",
                    "last_scrape_success": "2025-12-24T06:00:00-05:00"
                }
            }
        }
    }


class AvailableBridge(BaseModel):
    """Bridge identifier for the available bridges list."""
    id: str = Field(description="Unique bridge ID", examples=["SCT_CarltonSt"])
    name: str = Field(description="Bridge name", examples=["Carlton St."])
    region_short: str = Field(description="Region code", examples=["SCT"])
    region: str = Field(description="Full region name", examples=["St Catharines"])


class Coordinates(BaseModel):
    """Bridge GPS coordinates."""
    lat: float = Field(description="Latitude", examples=[43.19])
    lng: float = Field(description="Longitude", examples=[-79.20])


class ConfidenceInterval(BaseModel):
    """Confidence interval for predictions."""
    lower: float = Field(description="Lower bound (minutes)")
    upper: float = Field(description="Upper bound (minutes)")


class ClosureDurations(BaseModel):
    """Distribution of closure durations."""
    under_9m: int = Field(description="Closures under 9 minutes")
    m_10_15m: int = Field(alias="10_15m", description="Closures 10-15 minutes")
    m_16_30m: int = Field(alias="16_30m", description="Closures 16-30 minutes")
    m_31_60m: int = Field(alias="31_60m", description="Closures 31-60 minutes")
    over_60m: int = Field(description="Closures over 60 minutes")


class Statistics(BaseModel):
    """Historical statistics for a bridge."""
    average_closure_duration: Optional[float] = Field(description="Average closure in minutes")
    closure_ci: Optional[ConfidenceInterval] = Field(description="95% CI for closure duration")
    average_raising_soon: Optional[float] = Field(description="Average 'closing soon' duration")
    raising_soon_ci: Optional[ConfidenceInterval] = Field(description="95% CI for closing soon")
    closure_durations: Optional[ClosureDurations] = Field(description="Duration distribution")
    total_entries: Optional[int] = Field(description="Total historical data points")


class StaticBridgeData(BaseModel):
    """Static bridge information that rarely changes."""
    name: str = Field(description="Bridge name")
    region: str = Field(description="Region name")
    region_short: str = Field(description="Region code")
    coordinates: Coordinates
    statistics: Optional[Statistics] = None


class PredictedTime(BaseModel):
    """Predicted time range for status change."""
    lower: str = Field(description="Earliest expected time (ISO 8601)")
    upper: str = Field(description="Latest expected time (ISO 8601)")


class UpcomingClosure(BaseModel):
    """Scheduled or imminent closure."""
    type: str = Field(description="Closure type", examples=["Commercial Vessel", "Pleasure Craft", "Construction"])
    time: str = Field(description="Expected closure time (ISO 8601)")
    longer: Optional[bool] = Field(default=False, description="Longer than normal closure")
    end_time: Optional[str] = Field(default=None, description="End time for construction")
    expected_duration_minutes: Optional[int] = Field(default=None, description="Expected duration")
    description: Optional[str] = Field(default=None, description="Human-readable closure reason (for maintenance)")


class LiveBridgeData(BaseModel):
    """Real-time bridge status."""
    status: str = Field(description="Current status", examples=["Open", "Closed", "Closing soon", "Opening", "Construction"])
    last_updated: str = Field(description="When status was last updated (ISO 8601)")
    predicted: Optional[PredictedTime] = Field(default=None, description="Predicted next status change")
    upcoming_closures: list[UpcomingClosure] = Field(default=[], description="Scheduled closures")
    responsible_vessel_mmsi: Optional[int] = Field(default=None, description="MMSI of vessel likely causing closure (for Closing soon/Closed/Closing status)")


class BridgeData(BaseModel):
    """Complete bridge data with static and live info."""
    static: StaticBridgeData
    live: LiveBridgeData

    model_config = {
        "json_schema_extra": {
            "example": {
                "static": {
                    "name": "Carlton St.",
                    "region": "St Catharines",
                    "region_short": "SCT",
                    "coordinates": {"lat": 43.19, "lng": -79.20},
                    "statistics": {
                        "average_closure_duration": 12.5,
                        "closure_ci": {"lower": 8, "upper": 16},
                        "average_raising_soon": 3.2,
                        "raising_soon_ci": {"lower": 2, "upper": 5},
                        "total_entries": 287
                    }
                },
                "live": {
                    "status": "Closed",
                    "last_updated": "2025-12-24T12:30:00-05:00",
                    "predicted": {
                        "lower": "2025-12-24T12:38:00-05:00",
                        "upper": "2025-12-24T12:46:00-05:00"
                    },
                    "upcoming_closures": [{
                        "type": "Commercial Vessel",
                        "time": "2025-12-24T12:25:00-05:00",
                        "longer": False,
                        "expected_duration_minutes": 15
                    }],
                    "responsible_vessel_mmsi": 316013966
                }
            }
        }
    }


class BridgesResponse(BaseModel):
    """Response for /bridges endpoint."""
    last_updated: Optional[str] = Field(description="Last data update timestamp")
    available_bridges: list[AvailableBridge] = Field(description="List of all monitored bridges")
    bridges: dict[str, BridgeData] = Field(description="Bridge data keyed by ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "last_updated": "2025-12-24T12:30:00-05:00",
                "available_bridges": [
                    {"id": "SCT_CarltonSt", "name": "Carlton St.", "region_short": "SCT", "region": "St Catharines"},
                    {"id": "SCT_Highway", "name": "Highway 20", "region_short": "SCT", "region": "St Catharines"}
                ],
                "bridges": {
                    "SCT_CarltonSt": {
                        "static": {
                            "name": "Carlton St.",
                            "region": "St Catharines",
                            "region_short": "SCT",
                            "coordinates": {"lat": 43.19, "lng": -79.20},
                            "statistics": {"closure_ci": {"lower": 8, "upper": 16}}
                        },
                        "live": {
                            "status": "Open",
                            "last_updated": "2025-12-24T12:30:00-05:00",
                            "predicted": None,
                            "upcoming_closures": [],
                            "responsible_vessel_mmsi": None
                        }
                    }
                }
            }
        }
    }


# === Boat Tracking Response Models ===

class VesselPosition(BaseModel):
    """Vessel GPS coordinates."""
    lat: float = Field(description="Latitude")
    lon: float = Field(description="Longitude")


class VesselDimensions(BaseModel):
    """Vessel physical dimensions."""
    length: int = Field(description="Length in meters")
    width: int = Field(description="Width in meters")


class Vessel(BaseModel):
    """Vessel data from AIS."""
    mmsi: int = Field(description="Maritime Mobile Service Identity")
    name: Optional[str] = Field(description="Vessel name")
    type_name: str = Field(description="Vessel type (e.g. Cargo, Tanker - Hazard A)")
    type_category: str = Field(description="Category for icons/filtering (cargo, tanker, tug, etc.)")
    position: VesselPosition
    heading: Optional[int] = Field(description="Heading in degrees")
    course: Optional[float] = Field(description="Course over ground in degrees")
    speed_knots: Optional[float] = Field(description="Speed in knots")
    destination: Optional[str] = Field(description="Reported destination")
    dimensions: Optional[VesselDimensions] = Field(description="Vessel dimensions")
    last_seen: str = Field(description="Last update timestamp (ISO 8601)")
    source: str = Field(description="Data source (udp:sct, aishub)")
    region: str = Field(description="Region (welland, montreal)")


class UDPStationStatus(BaseModel):
    """UDP station health status."""
    active: bool = Field(description="Receiving data within last 30s")
    last_message: Optional[str] = Field(description="Last message timestamp")


class AISHubStatus(BaseModel):
    """AISHub API status."""
    ok: bool = Field(description="API working without errors")
    last_poll: Optional[str] = Field(description="Last poll timestamp")
    last_error: Optional[str] = Field(description="Last error message if any")
    failure_count: int = Field(description="Consecutive failures")


class BoatStatus(BaseModel):
    """Boat tracking system status."""
    udp: dict[str, UDPStationStatus] = Field(description="UDP station status")
    aishub: Optional[AISHubStatus] = Field(description="AISHub API status")


class BoatsResponse(BaseModel):
    """
    Response for /boats endpoint.

    Only vessels within monitored bounding boxes are included.
    Vessels outside these regions are not tracked.

    Bounding boxes (approximate ~20-25km buffer around bridges):
    - Welland Canal: 42.70°N to 43.40°N, 79.40°W to 79.05°W
    - Montreal: 45.05°N to 45.70°N, 74.35°W to 73.20°W
    """
    last_updated: str = Field(description="Response timestamp")
    vessel_count: int = Field(description="Number of moving vessels in monitored regions")
    status: BoatStatus = Field(description="System status")
    vessels: list[Vessel] = Field(description="Moving vessels")

    model_config = {
        "json_schema_extra": {
            "example": {
                "last_updated": "2025-12-25T15:30:00Z",
                "vessel_count": 3,
                "status": {
                    "udp": {"udp1": {"active": True, "last_message": "2025-12-25T15:29:55Z"}},
                    "aishub": {"ok": True, "last_poll": "2025-12-25T15:29:00Z", "last_error": None, "failure_count": 0}
                },
                "vessels": [{
                    "mmsi": 316013966,
                    "name": "ALGOMA GUARDIAN",
                    "type_name": "Cargo",
                    "type_category": "cargo",
                    "position": {"lat": 43.139, "lon": -79.192},
                    "heading": 180,
                    "course": 182.5,
                    "speed_knots": 6.2,
                    "destination": "HAMILTON",
                    "dimensions": {"length": 225, "width": 23},
                    "last_seen": "2025-12-25T15:29:55Z",
                    "source": "udp:udp1",
                    "region": "welland"
                }]
            }
        }
    }


# Scheduler instance
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


def sanitize_document_id(shortform: str, name: str) -> str:
    """
    Create a sanitized document ID from bridge shortform and name.

    Matches the logic from scraper.py for consistency.
    """
    import unicodedata
    import re
    normalized = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
    letters_only = re.sub(r'[^a-zA-Z]', '', normalized)
    truncated = letters_only[:25]
    return f"{shortform}_{truncated}"


def generate_available_bridges() -> list:
    """
    Generate available_bridges list from config.

    This replaces the hardcoded bridge list + regionFullNames in iOS.
    """
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
                "region": region
            })
    return bridges


# Generated once at module load
AVAILABLE_BRIDGES = generate_available_bridges()


def initialize_data_files():
    """
    Initialize data directory and bridges.json file.

    Creates directory structure and loads existing state into memory.
    """
    os.makedirs("data/history", exist_ok=True)

    if not os.path.exists("data/bridges.json"):
        # Create initial empty structure
        initial_data = {
            "last_updated": None,
            "available_bridges": AVAILABLE_BRIDGES,
            "bridges": {}
        }
        with open("data/bridges.json", "w") as f:
            json.dump(initial_data, f, indent=2, default=str)
        logger.info("Created initial bridges.json")
    else:
        # Load existing data into memory
        with open("data/bridges.json") as f:
            data = json.load(f)

        # Populate in-memory cache
        with shared.last_known_state_lock:
            for bridge_id, bridge_data in data.get("bridges", {}).items():
                last_known_state[bridge_id] = bridge_data

        # Load last_updated_time for memory-based /bridges endpoint
        last_updated_str = data.get("last_updated")
        if last_updated_str:
            try:
                shared.last_updated_time = datetime.fromisoformat(last_updated_str)
            except ValueError:
                shared.last_updated_time = None

        # Ensure available_bridges is present (migration from old format)
        if "available_bridges" not in data:
            data["available_bridges"] = AVAILABLE_BRIDGES
            with open("data/bridges.json", "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info("Added available_bridges to bridges.json")

        logger.info(f"Loaded {len(data.get('bridges', {}))} bridges from bridges.json")


def scrape_and_update_wrapper():
    """
    Wrapper for scrape_and_update to handle exceptions.

    Called by the scheduler - catches and logs errors.
    """
    from scraper import scrape_and_update
    try:
        scrape_and_update()
    except Exception as e:
        logger.error(f"Scheduler task failed: {str(e)[:100]}")


def daily_statistics_wrapper():
    """
    Wrapper for daily_statistics_update to handle exceptions.
    """
    from scraper import daily_statistics_update
    try:
        daily_statistics_update()
    except Exception as e:
        logger.error(f"Daily statistics failed: {str(e)[:100]}")


def maintenance_scraper_wrapper():
    """
    Wrapper for maintenance scraper to handle exceptions.

    Uses a lock to prevent concurrent runs (startup thread + 6 AM scheduled job).
    """
    # Non-blocking acquire - skip if another instance is already running
    if not _maintenance_scraper_lock.acquire(blocking=False):
        logger.debug("Maintenance scraper already running, skipping")
        return

    try:
        from maintenance_scraper import scrape_maintenance_page
        scrape_maintenance_page()
    except Exception as e:
        logger.error(f"Maintenance scraper failed: {str(e)[:100]}")
    finally:
        _maintenance_scraper_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan handler for startup and shutdown.
    """
    global boat_tracker

    # Startup
    shared.main_loop = asyncio.get_running_loop()
    initialize_data_files()

    # Schedule scraping jobs
    # Day: every 20s (6AM-10PM), Night: every 30s (10PM-6AM)
    scheduler.add_job(
        scrape_and_update_wrapper, 'cron',
        hour='6-21', minute='*', second='0,20,40',
        max_instances=3, coalesce=True, misfire_grace_time=60
    )
    scheduler.add_job(
        scrape_and_update_wrapper, 'cron',
        hour='22-23,0-5', minute='*', second='0,30',
        max_instances=3, coalesce=True, misfire_grace_time=120
    )

    # Daily statistics update at 3 AM
    scheduler.add_job(daily_statistics_wrapper, 'cron', hour=3, minute=0)

    # Schedule maintenance page scraping (seasonal - winter only)
    if ENABLE_MAINTENANCE_SCRAPER:
        scheduler.add_job(
            maintenance_scraper_wrapper,
            'cron',
            hour=6,
            minute=0,
            id='maintenance_scraper',
            max_instances=1,
            coalesce=True
        )
        # Run once on startup (non-blocking) so we don't wait until 6 AM
        global _maintenance_startup_thread
        _maintenance_startup_thread = threading.Thread(
            target=maintenance_scraper_wrapper, daemon=True, name="maintenance-startup"
        )
        _maintenance_startup_thread.start()
        logger.info("Maintenance scraper enabled (runs daily 6:00 AM + on startup)")
    else:
        logger.info("Maintenance scraper disabled (off-season)")

    # Validate maintenance.json on startup (info-level if missing, since scraper thread may not have created it yet)
    maintenance_errors = validate_maintenance_file()
    if maintenance_errors:
        for error in maintenance_errors:
            # File not found is expected on first startup before scraper completes
            if "not found" in error.lower():
                logger.info(f"maintenance.json: {error} (will be created by scraper)")
            else:
                logger.warning(f"maintenance.json: {error}")

    scheduler.start()
    logger.info("Scheduler started")

    # Run initial scrape
    scrape_and_update_wrapper()

    # Start boat tracker (UDP always listens, AISHub if API key exists)
    from boat_tracker import BoatTracker
    boat_tracker = BoatTracker()
    await boat_tracker.start()

    # Schedule boat change check (pushes to WebSocket subscribers when data changes)
    scheduler.add_job(
        check_and_broadcast_boats_sync,
        'interval',
        seconds=BOATS_CHECK_INTERVAL_SECONDS,
        id='boat_change_check',
        max_instances=1,
        coalesce=True
    )
    logger.info(f"Boat WebSocket broadcast enabled (checking every {BOATS_CHECK_INTERVAL_SECONDS}s)")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop boat tracker
    if boat_tracker:
        await boat_tracker.stop()

    # Close all WebSocket connections gracefully
    for client in connected_clients.copy():
        try:
            await client.websocket.close(code=1001, reason="Server shutting down")
        except Exception:
            pass
    connected_clients.clear()

    scheduler.shutdown(wait=False)
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Bridge Up API",
    description="Real-time bridge status for St. Lawrence Seaway",
    version="2.0.0",
    contact={"url": "https://bridgeup.app"},
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None  # We serve /openapi.json ourselves with rate limiting
)

# Register rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Mount static files for custom CSS
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS middleware for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://(www\.)?bridgeup\.app|http://localhost:\d+|http://192\.168\.\d+\.\d+:\d+",
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates with channel subscriptions.

    On connect: nothing sent (client must subscribe)
    Subscribe: client sends {"action": "subscribe", "channels": ["bridges", "boats"]}

    Channels:
    - bridges: pushed when bridge status changes
    - boats: pushed when vessel data changes (~every 30-60s based on AIS data arrival)
    """
    await websocket.accept()
    client = WebSocketClient(websocket=websocket)
    connected_clients.append(client)
    logger.info(f"WebSocket client connected ({len(connected_clients)} total)")

    try:
        while True:
            raw_message = await websocket.receive_text()
            await handle_client_message(client, raw_message)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        if client in connected_clients:
            connected_clients.remove(client)
        logger.info(f"WebSocket client disconnected ({len(connected_clients)} total)")


async def handle_client_message(client: WebSocketClient, raw: str):
    """Handle incoming client messages (subscribe)."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return  # Ignore malformed messages

    action = msg.get("action")

    if action == "subscribe":
        requested_channels = msg.get("channels", [])

        # Validate and filter to known channels (supports region filters like boats:welland)
        if not isinstance(requested_channels, list):
            return
        valid_requested = validate_channels(requested_channels)

        # Update subscription (replaces previous)
        client.channels = valid_requested

        # Send confirmation
        await client.websocket.send_text(
            json.dumps({"type": "subscribed", "channels": list(client.channels)})
        )

        # Send current state for all subscribed channels
        if client.wants_bridges():
            await send_bridges_to_client(client)
        if client.wants_boats():
            await send_boats_to_client(client)

        logger.debug(
            f"Client subscribed to {list(client.channels)} "
            f"(bridges: {sum(1 for c in connected_clients if c.wants_bridges())}, "
            f"boats: {sum(1 for c in connected_clients if c.wants_boats())})"
        )


async def send_bridges_to_client(client: WebSocketClient):
    """Send current bridge state to a single client, filtered to their regions."""
    from responsible_boat import find_responsible_vessel

    if not os.path.exists("data/bridges.json"):
        return

    with bridges_file_lock:
        with open("data/bridges.json") as f:
            data = json.load(f)

    # Inject responsible vessels
    vessels = []
    if boat_tracker:
        vessels = boat_tracker.registry.get_moving_vessels(max_idle_minutes=VESSEL_IDLE_THRESHOLD_MINUTES)

    for bridge_id, bridge_data in data.get("bridges", {}).items():
        live = bridge_data.get("live", {})
        status = live.get("status", "Unknown")
        responsible_mmsi = find_responsible_vessel(bridge_id, status, vessels)
        live["responsible_vessel_mmsi"] = responsible_mmsi

    # Filter to client's regions if specified
    client_regions = client.bridge_regions()
    if client_regions is not None:
        data["bridges"] = {
            bid: bdata for bid, bdata in data.get("bridges", {}).items()
            if bid.split("_")[0].lower() in client_regions
        }
        data["available_bridges"] = [
            b for b in data.get("available_bridges", [])
            if b["region_short"].lower() in client_regions
        ]

    message = json.dumps({"type": "bridges", "data": data}, default=str)
    await client.websocket.send_text(message)


async def send_boats_to_client(client: WebSocketClient):
    """Send current boat state to a single client, filtered to their regions."""
    if not boat_tracker:
        return

    boats_data = boat_tracker.get_boats_response()
    vessels = boats_data["vessels"]

    # Filter to client's regions if specified
    client_regions = client.boat_regions()
    if client_regions is not None:
        vessels = [v for v in vessels if v.get("region") in client_regions]

    payload = {
        "last_updated": boats_data["last_updated"],
        "vessel_count": len(vessels),
        "vessels": vessels
    }

    message = json.dumps({"type": "boats", "data": payload}, default=str)
    await client.websocket.send_text(message)


async def broadcast(data: dict, changed_bridge_ids: Optional[Set[str]] = None):
    """
    Broadcast bridge data to clients subscribed to bridge channels.

    Called when bridge status changes (from scraper).
    Injects responsible_vessel_mmsi for each bridge before sending.

    Args:
        data: Full bridge data
        changed_bridge_ids: Optional set of bridge IDs that changed.
            If provided, only notifies subscribers to those regions.
            If None, notifies all bridge subscribers.
    """
    from responsible_boat import find_responsible_vessel

    # Get subscribers
    subscribers = [c for c in connected_clients if c.wants_bridges()]
    if not subscribers:
        return

    # Deep copy to avoid modifying original
    broadcast_data = copy.deepcopy(data)

    # Get vessels for responsible boat calculation
    vessels = []
    if boat_tracker:
        vessels = boat_tracker.registry.get_moving_vessels(max_idle_minutes=VESSEL_IDLE_THRESHOLD_MINUTES)

    # Calculate responsible vessels for each bridge
    bridges = broadcast_data.get("bridges", {})
    for bridge_id, bridge_data in bridges.items():
        live = bridge_data.get("live", {})
        status = live.get("status", "Unknown")
        responsible_mmsi = find_responsible_vessel(bridge_id, status, vessels)
        live["responsible_vessel_mmsi"] = responsible_mmsi

    # Determine which regions changed
    changed_regions: Optional[Set[str]] = None
    if changed_bridge_ids:
        changed_regions = set()
        for bridge_id in changed_bridge_ids:
            # Extract region from bridge_id (e.g., "SCT_CarltonSt" -> "sct")
            region = bridge_id.split("_")[0].lower()
            changed_regions.add(region)

    # Send to subscribers based on their region subscriptions
    disconnected = []
    notified_count = 0

    for client in subscribers:
        try:
            client_regions = client.bridge_regions()

            # Check if this client should receive the update
            should_send = False
            if client_regions is None:
                # Subscribed to all bridges ("bridges")
                should_send = True
            elif changed_regions is None:
                # No change info provided, send to all
                should_send = True
            elif client_regions & changed_regions:
                # Client cares about at least one changed region
                should_send = True

            if should_send:
                # Filter to client's regions if they have a preference
                if client_regions is not None:
                    filtered_bridges = {
                        bid: bdata for bid, bdata in broadcast_data.get("bridges", {}).items()
                        if bid.split("_")[0].lower() in client_regions
                    }
                    filtered_available = [
                        b for b in broadcast_data.get("available_bridges", [])
                        if b["region_short"].lower() in client_regions
                    ]
                    client_data = {
                        "last_updated": broadcast_data["last_updated"],
                        "available_bridges": filtered_available,
                        "bridges": filtered_bridges
                    }
                else:
                    client_data = broadcast_data

                message = json.dumps({"type": "bridges", "data": client_data}, default=str)
                await client.websocket.send_text(message)
                notified_count += 1
        except Exception:
            disconnected.append(client)

    # Clean up disconnected clients
    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)

    if changed_regions:
        logger.debug(f"Broadcast bridges: regions {changed_regions} changed, notified {notified_count}/{len(subscribers)} subscribers")


def broadcast_sync(data: dict, changed_bridge_ids: Optional[Set[str]] = None):
    """
    Synchronous wrapper for broadcast, called from scraper threads.

    Schedules the async broadcast on the main event loop.

    Args:
        data: Full bridge data
        changed_bridge_ids: Optional set of bridge IDs that changed
    """
    if shared.main_loop and shared.main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(data, changed_bridge_ids), shared.main_loop)


# Fields excluded from boat change detection (they update constantly but aren't meaningful changes)
# - last_seen: updates on every AIS message even if position unchanged
# - source: can flip between udp/aishub for same vessel
VOLATILE_VESSEL_FIELDS = {'last_seen', 'source'}


def get_vessels_for_comparison(vessels: list) -> str:
    """
    Build a comparison string from vessel data, excluding volatile fields.

    This ensures we only broadcast when meaningful data changes (position,
    heading, speed, metadata) rather than on every AIS timestamp update.
    """
    stable_vessels = [
        {k: v for k, v in vessel.items() if k not in VOLATILE_VESSEL_FIELDS}
        for vessel in vessels
    ]
    return json.dumps(stable_vessels, sort_keys=True, default=str)


async def broadcast_boats_if_changed():
    """
    Broadcast boat positions to subscribers if data has changed.

    Called periodically by scheduler (every 10s).
    Tracks changes per-region so clients only receive updates when
    their subscribed regions have changes.

    Change detection excludes volatile fields (last_seen, source) to avoid
    broadcasting on every AIS message when nothing meaningful changed.
    """
    import time

    if not boat_tracker:
        return

    # Check if anyone is subscribed to any boats channel
    subscribers = [c for c in connected_clients if c.wants_boats()]
    if not subscribers:
        return

    # Check minimum interval (flood prevention)
    now = time.time()
    if now - shared.last_boats_broadcast_time < shared.BOATS_MIN_BROADCAST_INTERVAL:
        return

    # Get all vessels and group by region
    boats_data = boat_tracker.get_boats_response()
    vessels = boats_data["vessels"]

    by_region: Dict[str, list] = {}
    for v in vessels:
        region = v.get("region")
        if region:
            by_region.setdefault(region, []).append(v)

    # Track which regions changed
    changed_regions: Set[str] = set()

    for region, region_vessels in by_region.items():
        comparison = get_vessels_for_comparison(region_vessels)

        if comparison != shared.last_boats_by_region.get(region):
            changed_regions.add(region)
            shared.last_boats_by_region[region] = comparison

    # Also detect removed regions (had vessels before, now empty)
    for region in list(shared.last_boats_by_region.keys()):
        if region not in by_region:
            changed_regions.add(region)
            del shared.last_boats_by_region[region]

    if not changed_regions:
        return  # Nothing changed

    # Send to subscribers based on their region subscriptions
    disconnected = []
    notified_count = 0

    for client in subscribers:
        try:
            client_regions = client.boat_regions()

            if client_regions is None:
                # Subscribed to all boats ("boats") - send full payload if any region changed
                payload = {
                    "last_updated": boats_data["last_updated"],
                    "vessel_count": len(vessels),
                    "vessels": vessels
                }
                message = json.dumps({"type": "boats", "data": payload}, default=str)
                await client.websocket.send_text(message)
                notified_count += 1
            else:
                # Subscribed to specific regions - check if any of their regions changed
                relevant_changes = client_regions & changed_regions
                if relevant_changes:
                    # Send only the vessels they care about
                    client_vessels = [v for v in vessels if v.get("region") in client_regions]
                    payload = {
                        "last_updated": boats_data["last_updated"],
                        "vessel_count": len(client_vessels),
                        "vessels": client_vessels
                    }
                    message = json.dumps({"type": "boats", "data": payload}, default=str)
                    await client.websocket.send_text(message)
                    notified_count += 1
        except Exception:
            disconnected.append(client)

    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)

    shared.last_boats_broadcast_time = now

    logger.debug(f"Broadcast boats: regions {changed_regions} changed, notified {notified_count}/{len(subscribers)} subscribers")


def check_and_broadcast_boats_sync():
    """Synchronous wrapper for boat broadcast, called from scheduler."""
    if shared.main_loop and shared.main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_boats_if_changed(), shared.main_loop)


@app.get("/bridges", response_model=BridgesResponse)
@limiter.limit("60/minute")
def get_bridges(request: Request, response: Response):
    """
    Get current state of all bridges.

    Returns identical structure to WebSocket messages.
    Served from memory cache for faster responses (same source as WebSocket).

    Includes `responsible_vessel_mmsi` for bridges with closure status,
    identifying the vessel most likely causing the closure.

    Rate limit: 60 requests/minute per IP.
    Cache: Responses cached for 10 seconds (data updates every ~20s).
    """
    from responsible_boat import find_responsible_vessel

    response.headers["Cache-Control"] = "public, max-age=10"

    with last_known_state_lock:
        bridges = copy.deepcopy(last_known_state)

    # Get vessels for responsible boat calculation
    vessels = []
    if boat_tracker:
        vessels = boat_tracker.registry.get_moving_vessels(max_idle_minutes=VESSEL_IDLE_THRESHOLD_MINUTES)

    # Calculate responsible vessels for each bridge
    for bridge_id, bridge_data in bridges.items():
        live = bridge_data.get("live", {})
        status = live.get("status", "Unknown")

        responsible_mmsi = find_responsible_vessel(bridge_id, status, vessels)
        live["responsible_vessel_mmsi"] = responsible_mmsi

    return {
        "last_updated": shared.last_updated_time.isoformat() if shared.last_updated_time else None,
        "available_bridges": AVAILABLE_BRIDGES,
        "bridges": bridges
    }


@app.get("/bridges/{bridge_id}", response_model=BridgeData)
@limiter.limit("60/minute")
def get_bridge(bridge_id: str, request: Request, response: Response):
    """
    Get a single bridge by ID.

    Useful for deep links and focused queries.
    Served from memory cache for faster responses.

    Includes `responsible_vessel_mmsi` for bridges with closure status.

    Rate limit: 60 requests/minute per IP.
    Cache: Responses cached for 10 seconds.
    """
    from responsible_boat import find_responsible_vessel

    response.headers["Cache-Control"] = "public, max-age=10"

    with last_known_state_lock:
        bridge = last_known_state.get(bridge_id)
        if bridge:
            bridge = copy.deepcopy(bridge)

            # Calculate responsible vessel
            vessels = []
            if boat_tracker:
                vessels = boat_tracker.registry.get_moving_vessels(max_idle_minutes=VESSEL_IDLE_THRESHOLD_MINUTES)

            live = bridge.get("live", {})
            status = live.get("status", "Unknown")
            responsible_mmsi = find_responsible_vessel(bridge_id, status, vessels)
            live["responsible_vessel_mmsi"] = responsible_mmsi

            return bridge
    raise HTTPException(status_code=404, detail="Bridge not found")


@app.get("/", response_model=RootResponse)
@limiter.limit("30/minute")
def root(request: Request, response: Response):
    """
    API root - returns available endpoints.

    Rate limit: 30 requests/minute per IP.
    Cache: 60 seconds (static content).
    """
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "name": "Bridge Up API",
        "description": "Real-time bridge status for St. Lawrence Seaway",
        "website": "https://bridgeup.app",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "bridges": "/bridges",
            "boats": "/boats",
            "websocket": "wss://api.bridgeup.app/ws"
        }
    }


@app.get("/docs", include_in_schema=False)
@limiter.limit("30/minute")
async def custom_swagger_ui(request: Request) -> HTMLResponse:
    """Serve custom-styled Swagger UI with dark theme."""
    # Get default Swagger UI HTML
    html = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Bridge Up API"
    )

    # Inject custom CSS after the default Swagger CSS
    custom_css_link = '<link rel="stylesheet" href="/static/swagger-custom.css">'
    modified_html = html.body.decode().replace(
        '</head>',
        f'{custom_css_link}</head>'
    )

    return HTMLResponse(content=modified_html, headers={"Cache-Control": "public, max-age=60"})


@app.get("/openapi.json", include_in_schema=False)
@limiter.limit("30/minute")
async def get_openapi_schema(request: Request) -> JSONResponse:
    """Return OpenAPI schema with rate limiting."""
    return JSONResponse(
        content=app.openapi(),
        headers={"Cache-Control": "public, max-age=60"}
    )


@app.get("/boats", response_model=BoatsResponse)
@limiter.limit("60/minute")
def get_boats(request: Request, response: Response):
    """
    Get current vessel positions in monitored regions.

    Returns vessels that have moved within the last 30 minutes.
    Data sources: local AIS UDP receivers and AISHub API.

    **Monitored Regions (vessels outside these bounds are not tracked):**

    | Region | Lat Range | Lon Range | Buffer |
    |--------|-----------|-----------|--------|
    | welland | 42.70°N - 43.40°N | 79.40°W - 79.05°W | ~20km |
    | montreal | 45.05°N - 45.70°N | 74.35°W - 73.20°W | ~25km |

    The bounding boxes cover all bridges plus buffer for approaching vessels.

    Rate limit: 60 requests/minute per IP.
    Cache: Responses cached for 10 seconds.
    """
    response.headers["Cache-Control"] = "public, max-age=10"

    if boat_tracker:
        return boat_tracker.get_boats_response()

    # Not running - return empty status
    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "vessel_count": 0,
        "status": {
            "udp": {},
            "aishub": None
        },
        "vessels": []
    }


@app.get("/health", response_model=HealthResponse)
@limiter.limit("30/minute")
def health(request: Request, response: Response):
    """
    Health check endpoint for monitoring.

    Status levels:
        - "ok": All systems operational
        - "warning": Unusual inactivity (no bridge changes in 24+ hours)
        - "error": Scraper stalled (no scrape in 5+ minutes)

    Returns:
        - status: ok, warning, or error
        - status_message: Human-readable explanation
        - last_updated: timestamp of last data update
        - last_scrape: timestamp of last scrape attempt
        - statistics_last_updated: timestamp of last statistics calculation
        - bridges_count: number of bridges in data
        - websocket_clients: number of connected clients

    Rate limit: 30 requests/minute per IP.
    Cache: Responses cached for 5 seconds.
    """
    response.headers["Cache-Control"] = "public, max-age=5"

    now = datetime.now(TIMEZONE)
    status = "ok"
    status_message = "All systems operational"

    # Get bridge count from memory
    with last_known_state_lock:
        bridges_count = len(last_known_state)

    # Read scrape state atomically to avoid race conditions
    with shared.scrape_state_lock:
        consecutive_failures = shared.consecutive_scrape_failures
        last_scrape = shared.last_scrape_time

    # Check for consecutive scrape failures (all regions failing)
    if consecutive_failures >= 3:
        status = "error"
        status_message = f"Scraper failing: {consecutive_failures} consecutive failures (all regions)"

    # Check scraper health (runs every 20-30s, so 5 min = definitely stuck)
    if last_scrape and status == "ok":
        scrape_age = now - last_scrape
        if scrape_age > timedelta(minutes=5):
            status = "error"
            minutes_ago = int(scrape_age.total_seconds() / 60)
            status_message = f"Scraper has not succeeded in {minutes_ago} minutes"

    # Check data freshness (24h without any bridge change is unusual)
    if shared.last_updated_time and status == "ok":
        data_age = now - shared.last_updated_time
        if data_age > timedelta(hours=24):
            status = "warning"
            hours_ago = int(data_age.total_seconds() / 3600)
            status_message = f"No bridge status changes in {hours_ago} hours, unusual inactivity"

    boats_count = boat_tracker.get_vessel_count() if boat_tracker else 0

    return {
        "status": status,
        "status_message": status_message,
        "last_updated": shared.last_updated_time.isoformat() if shared.last_updated_time else None,
        "last_scrape": last_scrape.isoformat() if last_scrape else None,
        "last_scrape_had_changes": shared.last_scrape_had_changes,
        "statistics_last_updated": shared.statistics_last_updated.isoformat() if shared.statistics_last_updated else None,
        "bridges_count": bridges_count,
        "boats_count": boats_count,
        "websocket_clients": len(connected_clients),
        # Copy list to avoid race with main event loop (health runs in threadpool)
        "websocket_bridges_subscribers": sum(1 for c in list(connected_clients) if c.wants_bridges()),
        "websocket_boats_subscribers": sum(1 for c in list(connected_clients) if c.wants_boats()),
        "maintenance": get_maintenance_info()
    }


# Export broadcast_sync for use by scraper
__all__ = ['app', 'broadcast_sync', 'AVAILABLE_BRIDGES']
