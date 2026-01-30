# shared.py
"""
Shared state module - prevents circular imports between main.py and scraper.py.

This module contains:
- Timezone configuration
- Thread-safe state management for bridge data
- WebSocket client tracking
- Event loop reference for sync->async broadcasting
- Utility functions (atomic_write_json)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List, Set, TYPE_CHECKING
import threading

if TYPE_CHECKING:
    from starlette.websockets import WebSocket
import asyncio
import tempfile
import json
import os
import pytz

# Timezone for Toronto/Eastern time
TIMEZONE = pytz.timezone('America/Toronto')

# Last scrape timestamp (for health monitoring) - only updated on successful scrapes
last_scrape_time: Optional[datetime] = None
last_scrape_had_changes: bool = False
consecutive_scrape_failures: int = 0  # Resets to 0 on any successful scrape
scrape_state_lock = threading.Lock()  # Protects last_scrape_time and consecutive_scrape_failures

# Last time bridge data actually changed (for /bridges endpoint and health check)
last_updated_time: Optional[datetime] = None

# Last statistics calculation timestamp
statistics_last_updated: Optional[datetime] = None

# In-memory cache of current bridge state
# Structure: {bridge_id: {static: {...}, live: {...}}}
last_known_state: Dict[str, Any] = {}
last_known_state_lock = threading.Lock()

# Smart backoff tracking for failed regions
# Structure: {bridge_key: (failure_count, next_retry_datetime)}
region_failures: Dict[str, tuple] = {}
region_failures_lock = threading.Lock()

# Smart endpoint caching - auto-discovers which JSON format works per region
# Structure: {bridge_key: 'old' | 'new'}
endpoint_cache: Dict[str, str] = {}
endpoint_cache_lock = threading.Lock()

@dataclass
class WebSocketClient:
    """
    Tracks per-client WebSocket state and channel subscriptions.

    Attributes:
        websocket: The WebSocket connection
        channels: Set of channels the client is subscribed to

    Channels can be:
        - "bridges" / "boats" - all data
        - "bridges:sct" / "boats:welland" - region-specific
    """
    websocket: 'WebSocket'
    channels: Set[str] = field(default_factory=set)

    def wants_bridges(self) -> bool:
        """Check if client is subscribed to any bridge channel."""
        return any(c == "bridges" or c.startswith("bridges:") for c in self.channels)

    def wants_boats(self) -> bool:
        """Check if client is subscribed to any boat channel."""
        return any(c == "boats" or c.startswith("boats:") for c in self.channels)

    def boat_regions(self) -> Optional[Set[str]]:
        """
        Get boat regions client wants, or None for all.

        Returns:
            None if subscribed to "boats" (all regions)
            Set of region names if subscribed to specific regions
            None if not subscribed to any boats
        """
        if "boats" in self.channels:
            return None  # Wants all
        regions = set()
        for c in self.channels:
            if c.startswith("boats:"):
                regions.add(c.split(":", 1)[1])
        return regions if regions else None

    def bridge_regions(self) -> Optional[Set[str]]:
        """
        Get bridge regions client wants, or None for all.

        Returns:
            None if subscribed to "bridges" (all regions)
            Set of region codes if subscribed to specific regions
            None if not subscribed to any bridges
        """
        if "bridges" in self.channels:
            return None  # Wants all
        regions = set()
        for c in self.channels:
            if c.startswith("bridges:"):
                regions.add(c.split(":", 1)[1])
        return regions if regions else None

    def wants_boat_region(self, region: str) -> bool:
        """Check if client wants updates for a specific boat region."""
        if "boats" in self.channels:
            return True  # Subscribed to all
        return f"boats:{region}" in self.channels

    def wants_bridge_region(self, region: str) -> bool:
        """Check if client wants updates for a specific bridge region."""
        if "bridges" in self.channels:
            return True  # Subscribed to all
        return f"bridges:{region.lower()}" in self.channels


# WebSocket clients (managed by main.py, used by scraper for broadcasting)
connected_clients: List[WebSocketClient] = []

# Event loop reference (set by main.py at startup, used for sync->async broadcast)
main_loop: Optional[asyncio.AbstractEventLoop] = None

# Per-region boat state for change detection (excludes volatile fields)
# Structure: {region: serialized JSON string of vessels in that region}
last_boats_by_region: Dict[str, str] = {}
last_boats_broadcast_time: float = 0.0
BOATS_MIN_BROADCAST_INTERVAL: float = 10.0  # Minimum seconds between broadcasts (flood prevention)

# File lock for atomic writes to bridges.json
bridges_file_lock = threading.Lock()

# File lock for history file operations (prevents race with max_instances > 1)
history_file_lock = threading.Lock()


def atomic_write_json(path: str, data: Any) -> None:
    """
    Atomically write JSON data to file (crash-safe).

    Writes to temp file first, then renames. This prevents corruption
    if the process crashes mid-write.
    """
    dir_path = os.path.dirname(path) or "."
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, suffix='.tmp') as f:
            json.dump(data, f, default=str, indent=2)
            temp_path = f.name
        os.replace(temp_path, path)  # Atomic on POSIX
    except Exception:
        # Clean up temp file on failure
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
