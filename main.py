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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from datetime import datetime
import json
import asyncio
import os

import shared
from shared import (
    TIMEZONE, last_known_state, connected_clients,
    bridges_file_lock
)
from config import BRIDGE_KEYS, BRIDGE_DETAILS
from loguru import logger

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

    yield

    # Shutdown
    logger.info("Shutting down...")

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
    lifespan=lifespan
)

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


@app.get("/bridges")
def get_bridges():
    """
    Get current state of all bridges.

    Returns identical structure to WebSocket messages.
    Useful as HTTP fallback if WebSocket fails.
    """
    if os.path.exists("data/bridges.json"):
        with open("data/bridges.json") as f:
            return json.load(f)
    return {"last_updated": None, "available_bridges": AVAILABLE_BRIDGES, "bridges": {}}


@app.get("/bridges/{bridge_id}")
def get_bridge(bridge_id: str):
    """
    Get a single bridge by ID.

    Useful for deep links and focused queries.
    """
    if os.path.exists("data/bridges.json"):
        with open("data/bridges.json") as f:
            data = json.load(f)
        bridge = data.get("bridges", {}).get(bridge_id)
        if bridge:
            return bridge
    raise HTTPException(status_code=404, detail="Bridge not found")


@app.get("/health")
def health():
    """
    Health check endpoint for monitoring.

    Returns:
        - status: "ok" if healthy
        - last_updated: timestamp of last data update
        - last_scrape: timestamp of last scrape attempt
        - bridges_count: number of bridges in data
        - websocket_clients: number of connected clients
    """
    last_updated = None
    bridges_count = 0

    if os.path.exists("data/bridges.json"):
        with open("data/bridges.json") as f:
            data = json.load(f)
        last_updated = data.get("last_updated")
        bridges_count = len(data.get("bridges", {}))

    return {
        "status": "ok",
        "last_updated": last_updated,
        "last_scrape": shared.last_scrape_time.isoformat() if shared.last_scrape_time else None,
        "bridges_count": bridges_count,
        "websocket_clients": len(connected_clients)
    }


# Export broadcast_sync for use by scraper
__all__ = ['app', 'broadcast_sync', 'AVAILABLE_BRIDGES']
