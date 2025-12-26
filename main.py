# main.py
"""
FastAPI application with WebSocket for real-time bridge updates.

This is the main entry point for the migrated backend:
- WebSocket endpoint for real-time push to iOS/web clients
- HTTP endpoints for fallback and health monitoring
- APScheduler for background scraping tasks
- CORS configuration for web clients
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, Field
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import copy
import json
import asyncio
import os

import shared
from shared import (
    TIMEZONE, last_known_state, last_known_state_lock, connected_clients,
    bridges_file_lock
)
from config import BRIDGE_KEYS, BRIDGE_DETAILS
from loguru import logger

# Boat tracker (initialized in lifespan if enabled)
boat_tracker = None


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


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(description="API status: ok, warning, or error", examples=["ok"])
    status_message: str = Field(description="Human-readable status explanation")
    last_updated: Optional[str] = Field(description="Last time bridge data changed")
    last_scrape: Optional[str] = Field(description="Last scrape attempt timestamp")
    last_scrape_had_changes: bool = Field(description="Whether last scrape found changes")
    statistics_last_updated: Optional[str] = Field(description="Last time statistics were calculated")
    bridges_count: int = Field(description="Number of bridges in data")
    boats_count: int = Field(description="Number of vessels currently tracked")
    websocket_clients: int = Field(description="Connected WebSocket clients")

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
                "websocket_clients": 3
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


class LiveBridgeData(BaseModel):
    """Real-time bridge status."""
    status: str = Field(description="Current status", examples=["Open", "Closed", "Closing soon", "Opening", "Construction"])
    last_updated: str = Field(description="When status was last updated (ISO 8601)")
    predicted: Optional[PredictedTime] = Field(default=None, description="Predicted next status change")
    upcoming_closures: list[UpcomingClosure] = Field(default=[], description="Scheduled closures")


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
                    }]
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
                            "upcoming_closures": []
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
    """Response for /boats endpoint."""
    last_updated: str = Field(description="Response timestamp")
    vessel_count: int = Field(description="Number of moving vessels")
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

    scheduler.start()
    logger.info("Scheduler started")

    # Run initial scrape
    scrape_and_update_wrapper()

    # Start boat tracker (UDP always listens, AISHub if API key exists)
    from boat_tracker import BoatTracker
    boat_tracker = BoatTracker()
    await boat_tracker.start()

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Stop boat tracker
    if boat_tracker:
        await boat_tracker.stop()

    # Close all WebSocket connections gracefully
    for client in connected_clients.copy():
        try:
            await client.close(code=1001, reason="Server shutting down")
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
    redoc_url=None
)

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
    WebSocket endpoint for real-time bridge updates.

    - On connect: sends full state immediately
    - On change: server broadcasts full state to all clients
    - Protocol-level ping/pong handled by uvicorn
    """
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"WebSocket client connected ({len(connected_clients)} total)")

    try:
        # Send current state immediately on connect
        if os.path.exists("data/bridges.json"):
            with open("data/bridges.json") as f:
                await websocket.send_text(f.read())

        # Keep connection alive, handle incoming messages
        while True:
            # Client can send pings, we just acknowledge by staying alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected ({len(connected_clients)} total)")


async def broadcast(data: dict):
    """
    Broadcast data to all connected WebSocket clients.

    Called when bridge status changes.
    """
    message = json.dumps(data, default=str)
    disconnected = []

    for client in connected_clients.copy():
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)

    # Clean up disconnected clients
    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)


def broadcast_sync(data: dict):
    """
    Synchronous wrapper for broadcast, called from scraper threads.

    Schedules the async broadcast on the main event loop.
    """
    if shared.main_loop and shared.main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(data), shared.main_loop)


@app.get("/bridges", response_model=BridgesResponse)
def get_bridges():
    """
    Get current state of all bridges.

    Returns identical structure to WebSocket messages.
    Served from memory cache for faster responses (same source as WebSocket).
    """
    with last_known_state_lock:
        bridges = copy.deepcopy(last_known_state)

    return {
        "last_updated": shared.last_updated_time.isoformat() if shared.last_updated_time else None,
        "available_bridges": AVAILABLE_BRIDGES,
        "bridges": bridges
    }


@app.get("/bridges/{bridge_id}", response_model=BridgeData)
def get_bridge(bridge_id: str):
    """
    Get a single bridge by ID.

    Useful for deep links and focused queries.
    Served from memory cache for faster responses.
    """
    with last_known_state_lock:
        bridge = last_known_state.get(bridge_id)
        if bridge:
            return copy.deepcopy(bridge)
    raise HTTPException(status_code=404, detail="Bridge not found")


@app.get("/", response_model=RootResponse)
def root():
    """
    API root - returns available endpoints.
    """
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
async def custom_swagger_ui():
    """Serve custom-styled Swagger UI with dark theme."""
    from fastapi.responses import HTMLResponse

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

    return HTMLResponse(content=modified_html)


@app.get("/boats", response_model=BoatsResponse)
def get_boats():
    """
    Get current vessel positions in monitored regions.

    Returns vessels that have moved within the last 30 minutes.
    Data sources: local AIS UDP receivers and AISHub API.

    Regions:
    - welland: Welland Canal (St. Catharines to Port Colborne)
    - montreal: Montreal South Shore (St. Lawrence Seaway)
    """
    from datetime import datetime, timezone

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
def health():
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
    """
    now = datetime.now(TIMEZONE)
    status = "ok"
    status_message = "All systems operational"

    # Get bridge count from memory
    with last_known_state_lock:
        bridges_count = len(last_known_state)

    # Check scraper health (runs every 20-30s, so 5 min = definitely stuck)
    if shared.last_scrape_time:
        scrape_age = now - shared.last_scrape_time
        if scrape_age > timedelta(minutes=5):
            status = "error"
            minutes_ago = int(scrape_age.total_seconds() / 60)
            status_message = f"Scraper has not run in {minutes_ago} minutes, may be stuck or crashed"

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
        "last_scrape": shared.last_scrape_time.isoformat() if shared.last_scrape_time else None,
        "last_scrape_had_changes": shared.last_scrape_had_changes,
        "statistics_last_updated": shared.statistics_last_updated.isoformat() if shared.statistics_last_updated else None,
        "bridges_count": bridges_count,
        "boats_count": boats_count,
        "websocket_clients": len(connected_clients)
    }


# Export broadcast_sync for use by scraper
__all__ = ['app', 'broadcast_sync', 'AVAILABLE_BRIDGES']
