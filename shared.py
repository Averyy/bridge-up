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
from datetime import datetime
from typing import Dict, Any, Optional, List
import threading
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

# WebSocket clients (managed by main.py, used by scraper for broadcasting)
# Type is List[WebSocket] but we can't import WebSocket here due to circular imports
connected_clients: List = []

# Event loop reference (set by main.py at startup, used for sync->async broadcast)
main_loop: Optional[asyncio.AbstractEventLoop] = None

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
