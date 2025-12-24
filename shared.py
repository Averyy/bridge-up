# shared.py
"""
Shared state module - prevents circular imports between main.py and scraper.py.

This module contains:
- Timezone configuration
- Thread-safe state management for bridge data
- WebSocket client tracking
- Event loop reference for sync->async broadcasting
"""
from datetime import datetime
from typing import Dict, Any, Optional, List
import threading
import asyncio
import pytz

# Timezone for Toronto/Eastern time
TIMEZONE = pytz.timezone('America/Toronto')

# Last scrape timestamp (for health monitoring)
last_scrape_time: Optional[datetime] = None
last_scrape_had_changes: bool = False

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
