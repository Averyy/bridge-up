# boat_tracker.py
"""
Real-time vessel tracking for Bridge Up.

Receives AIS data from:
- Local UDP dispatchers (real-time, ~1s latency)
- AISHub API (polled every 60s, respects rate limit)

All data is in-memory only, no persistence.
"""
import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from pyais import decode
from loguru import logger

from boat_config import (
    BOAT_REGIONS,
    get_vessel_region,
    get_vessel_type_info,
    sanitize_vessel_name,
)


class VesselRegistry:
    """
    Thread-safe in-memory vessel storage with deduplication.

    Handles merging data from multiple sources (UDP, AISHub) with
    priority given to real-time UDP data.
    """

    MAX_UDP_STATIONS = 2
    MAX_VESSELS = 1000  # Safety cap - more than enough for our regions

    def __init__(self):
        self.vessels: dict[int, dict] = {}  # MMSI -> vessel data
        self._lock = asyncio.Lock()
        self.udp_station_last_message: dict[str, datetime] = {}  # station_id -> last msg time
        self._ip_to_station: dict[str, str] = {}  # IP -> station_id (dynamic assignment)

    def get_station_id(self, ip: str) -> Optional[str]:
        """
        Get or assign station ID for an IP address.

        Dynamically assigns 'udp1', 'udp2' to first 2 unique IPs.
        Returns None if max stations reached and IP is new.
        """
        if ip in self._ip_to_station:
            return self._ip_to_station[ip]

        if len(self._ip_to_station) >= self.MAX_UDP_STATIONS:
            return None  # Ignore additional sources

        station_id = f"udp{len(self._ip_to_station) + 1}"
        self._ip_to_station[ip] = station_id
        logger.info(f"UDP station {station_id} registered from {ip}")
        return station_id

    async def update_vessel(self, mmsi: int, data: dict, source: str) -> None:
        """
        Update or insert vessel data with deduplication logic.

        Args:
            mmsi: Maritime Mobile Service Identity (unique vessel ID)
            data: Vessel data dict with lat, lng, speed, etc.
            source: Data source ("udp:sct", "aishub", etc.)
        """
        async with self._lock:
            now = datetime.now(timezone.utc)

            # Track per-station UDP timestamps
            if source.startswith("udp:"):
                station_id = source.split(":")[1]
                self.udp_station_last_message[station_id] = now

            # Must have position data
            lat = data.get("lat")
            lon = data.get("lon")
            if lat is None or lon is None:
                # Static-only update (type 5/24) - merge with existing if present
                existing = self.vessels.get(mmsi)
                if existing:
                    self._merge_static_data(existing, data)
                return

            # Filter vessels outside our regions
            region = get_vessel_region(lat, lon)
            if region is None:
                # Outside Welland/Montreal - remove if previously tracked
                if mmsi in self.vessels:
                    del self.vessels[mmsi]
                return

            existing = self.vessels.get(mmsi)

            if existing is None:
                # New vessel - create entry (if under limit)
                if len(self.vessels) >= self.MAX_VESSELS:
                    return  # Safety cap reached
                vessel = self._create_vessel_entry(mmsi, data, source, region, now)
                self.vessels[mmsi] = vessel
                return

            # Existing vessel - apply deduplication logic
            last_seen = datetime.fromisoformat(existing["last_seen"].replace("Z", "+00:00"))
            age_seconds = (now - last_seen).total_seconds()

            # UDP always wins (real-time)
            if source.startswith("udp:"):
                self._merge_vessel_data(existing, data, source, region, now)
                return

            # AISHub only updates if existing data is stale (>60s)
            if source == "aishub" and age_seconds > 60:
                self._merge_vessel_data(existing, data, source, region, now)

    def _create_vessel_entry(self, mmsi: int, data: dict, source: str,
                             region: str, now: datetime) -> dict:
        """Create a new vessel entry."""
        type_code = data.get("type")
        type_name, type_category = get_vessel_type_info(type_code)

        return {
            "mmsi": mmsi,
            "name": data.get("name"),
            "type_name": type_name,
            "type_category": type_category,
            "lat": data["lat"],
            "lon": data["lon"],
            "speed_knots": data.get("speed_knots"),
            "heading": data.get("heading"),
            "course": data.get("course"),
            "destination": data.get("destination"),
            "dimensions": data.get("dimensions"),
            "last_seen": now.isoformat(),
            "last_moved": now.isoformat(),
            "source": source,
            "region": region,
        }

    def _merge_vessel_data(self, existing: dict, new_data: dict, source: str,
                           region: str, now: datetime) -> None:
        """Merge new position data into existing vessel."""
        # Check if position changed significantly (>10m)
        if self._position_changed(existing, new_data):
            existing["last_moved"] = now.isoformat()

        # Update position and dynamic fields
        existing["lat"] = new_data["lat"]
        existing["lon"] = new_data["lon"]

        if new_data.get("speed_knots") is not None:
            existing["speed_knots"] = new_data["speed_knots"]
        if new_data.get("heading") is not None:
            existing["heading"] = new_data["heading"]
        if new_data.get("course") is not None:
            existing["course"] = new_data["course"]

        # Merge static data if present
        self._merge_static_data(existing, new_data)

        existing["last_seen"] = now.isoformat()
        existing["source"] = source
        existing["region"] = region

    def _merge_static_data(self, existing: dict, new_data: dict) -> None:
        """Merge static vessel data (name, type, dimensions)."""
        if new_data.get("name"):
            existing["name"] = new_data["name"]
        if new_data.get("type") is not None:
            type_name, type_category = get_vessel_type_info(new_data["type"])
            existing["type_name"] = type_name
            existing["type_category"] = type_category
        if new_data.get("destination"):
            existing["destination"] = new_data["destination"]
        if new_data.get("dimensions"):
            existing["dimensions"] = new_data["dimensions"]

    def _position_changed(self, old: dict, new: dict, threshold_m: float = 10) -> bool:
        """Check if position changed by more than threshold meters."""
        if old.get("lat") is None or new.get("lat") is None:
            return True

        # Approximate distance (good enough for 10m threshold)
        lat_diff = abs(old["lat"] - new["lat"]) * 111320  # meters per degree
        lon_diff = abs(old["lon"] - new["lon"]) * 78710   # meters at ~45 degrees lat
        distance = (lat_diff ** 2 + lon_diff ** 2) ** 0.5
        return distance > threshold_m

    def get_moving_vessels(self, max_idle_minutes: int = 30) -> list[dict]:
        """
        Get vessels that moved within the specified time window.

        Filters out anchored/docked vessels. Logic: if a vessel hasn't moved
        in 30+ min, it's likely anchored - not actively transiting. Vessels
        waiting for a bridge won't wait 30 min (closures are ~10-20 min).

        This is a sync method - no await needed.

        Args:
            max_idle_minutes: Maximum minutes since last movement

        Returns:
            List of vessel dicts
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_idle_minutes)

        moving = []
        for vessel in self.vessels.values():
            last_moved_str = vessel.get("last_moved", vessel["last_seen"])
            last_moved = datetime.fromisoformat(last_moved_str.replace("Z", "+00:00"))
            if last_moved >= cutoff:
                moving.append(vessel)
        return moving

    def get_udp_status(self) -> dict:
        """Get UDP station status for health/API response."""
        now = datetime.now(timezone.utc)
        stations = {}
        for station_id, last_msg in self.udp_station_last_message.items():
            age = (now - last_msg).total_seconds()
            stations[station_id] = {
                "active": age < 30,  # 30s threshold
                "last_message": last_msg.isoformat(),
            }
        return stations

    async def cleanup_stale_vessels(self, max_age_minutes: int = 60) -> int:
        """
        Remove vessels not seen within max_age_minutes.

        Args:
            max_age_minutes: Maximum minutes since last seen

        Returns:
            Number of vessels removed
        """
        async with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
            stale = []
            for mmsi, vessel in self.vessels.items():
                last_seen = datetime.fromisoformat(vessel["last_seen"].replace("Z", "+00:00"))
                if last_seen < cutoff:
                    stale.append(mmsi)

            for mmsi in stale:
                del self.vessels[mmsi]

            return len(stale)


class UDPProtocol(asyncio.DatagramProtocol):
    """
    Async UDP receiver for AIS NMEA messages.

    Handles:
    - Single-part messages (immediate decode)
    - Multi-part messages (buffer until complete)
    - Base station filtering (skip type 4, 20, 22)
    """

    # Message types to skip (base stations, channel management)
    SKIP_TYPES = {4, 20, 22}

    # Message types with position data
    POSITION_TYPES = {1, 2, 3, 18, 19}

    # Message types with static data (name, type, dimensions)
    STATIC_TYPES = {5, 24}

    # Safety limits
    MAX_BUFFER_SIZE = 500  # Max vessels in buffer before flush
    MAX_MULTIPART_BUFFER = 100  # Max incomplete multipart messages

    def __init__(self, registry: VesselRegistry):
        self.registry = registry
        self.station_id = "udp"  # Updated dynamically on first message
        self.transport = None
        self.vessel_buffer: dict[int, dict] = {}  # MMSI -> latest data
        self.multipart_buffer: dict[tuple, list] = {}  # (msg_id, channel) -> parts
        self.multipart_timestamps: dict[tuple, float] = {}  # (msg_id, channel) -> time.time()
        self.message_count = 0

    def connection_made(self, transport):
        self.transport = transport
        logger.info("UDP listener ready")

    def datagram_received(self, data: bytes, addr: tuple):
        """Process incoming AIS NMEA sentence."""
        # Get or assign station ID for this source IP
        station_id = self.registry.get_station_id(addr[0])
        if station_id is None:
            return  # Max stations reached, ignore this source

        self.station_id = station_id
        self.message_count += 1

        try:
            # Parse NMEA sentence structure
            sentence = data.decode('ascii', errors='ignore').strip()
            if not sentence.startswith('!'):
                return

            parts = sentence.split(',')
            if len(parts) < 7:
                return

            fragment_count = int(parts[1])
            fragment_num = int(parts[2])
            msg_id = parts[3]  # Empty for single-part
            channel = parts[4]

            if fragment_count == 1:
                # Single-part message - decode immediately
                self._process_message(data)
            else:
                # Multi-part message - buffer until complete
                key = (msg_id, channel)
                if key not in self.multipart_buffer:
                    # Check buffer limit before adding new entry
                    if len(self.multipart_buffer) >= self.MAX_MULTIPART_BUFFER:
                        return  # Drop message if buffer full
                    self.multipart_buffer[key] = [None] * fragment_count
                    self.multipart_timestamps[key] = time.time()

                self.multipart_buffer[key][fragment_num - 1] = data

                # Check if complete
                if all(p is not None for p in self.multipart_buffer[key]):
                    self._process_message(*self.multipart_buffer[key])
                    del self.multipart_buffer[key]
                    del self.multipart_timestamps[key]

            # Periodically clean stale multipart buffers (every ~100 messages)
            if self.message_count % 100 == 0:
                self._cleanup_stale_multipart()

        except Exception as e:
            logger.debug(f"UDP:{self.station_id} parse error: {e}")

    def _process_message(self, *raw_parts: bytes):
        """Decode AIS message and buffer vessel data."""
        try:
            decoded = decode(*raw_parts)
            msg = decoded.asdict()
        except Exception as e:
            logger.debug(f"UDP:{self.station_id} decode error: {e}")
            return

        msg_type = msg.get("msg_type")
        if msg_type in self.SKIP_TYPES:
            return

        mmsi = msg.get("mmsi")
        if not mmsi:
            return

        # Validate MMSI (ships are 200M-799M range)
        if not (200_000_000 <= mmsi <= 799_999_999):
            return

        # Build vessel data
        vessel_data = {}

        if msg_type in self.POSITION_TYPES:
            lat = msg.get("lat")
            lon = msg.get("lon")

            # Skip invalid positions (91, 181 are "not available" markers)
            if lat is not None and lon is not None:
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    vessel_data["lat"] = lat
                    vessel_data["lon"] = lon

            speed = msg.get("speed")
            if speed is not None and speed < 102.3:  # 102.3 = not available
                vessel_data["speed_knots"] = speed

            heading = msg.get("heading")
            if heading is not None and heading < 360:  # 511 = not available
                vessel_data["heading"] = heading

            course = msg.get("course")
            if course is not None and course < 360:  # 360 = not available
                vessel_data["course"] = course

        if msg_type in self.STATIC_TYPES:
            name = sanitize_vessel_name(msg.get("shipname"))
            if name:
                vessel_data["name"] = name

            ship_type = msg.get("ship_type")
            if ship_type is not None:
                vessel_data["type"] = ship_type

            dest = sanitize_vessel_name(msg.get("destination"))
            if dest:
                vessel_data["destination"] = dest

            # Dimensions from A/B/C/D offsets
            to_bow = msg.get("to_bow", 0) or 0
            to_stern = msg.get("to_stern", 0) or 0
            to_port = msg.get("to_port", 0) or 0
            to_starboard = msg.get("to_starboard", 0) or 0
            length = to_bow + to_stern
            width = to_port + to_starboard
            if length > 0 or width > 0:
                vessel_data["dimensions"] = {"length": length, "width": width}

        # Buffer update (last-write-wins per MMSI within flush period)
        if vessel_data:
            if mmsi in self.vessel_buffer:
                # Merge with existing buffer entry
                self.vessel_buffer[mmsi].update(vessel_data)
            elif len(self.vessel_buffer) < self.MAX_BUFFER_SIZE:
                # Only add if under limit (prevents memory exhaustion from spam)
                self.vessel_buffer[mmsi] = vessel_data

    def _cleanup_stale_multipart(self, max_age_seconds: float = 10.0):
        """Remove incomplete multipart messages older than max_age_seconds."""
        now = time.time()
        stale_keys = [
            key for key, ts in self.multipart_timestamps.items()
            if now - ts > max_age_seconds
        ]
        for key in stale_keys:
            del self.multipart_buffer[key]
            del self.multipart_timestamps[key]

    def error_received(self, exc):
        logger.warning(f"UDP:{self.station_id} error: {exc}")


class UDPListener:
    """
    Manages UDP socket lifecycle and periodic buffer flush.
    """

    def __init__(self, registry: VesselRegistry, port: int):
        self.registry = registry
        self.port = port
        self.protocol: Optional[UDPProtocol] = None
        self.transport = None
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start UDP listener and flush task."""
        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(self.registry),
            local_addr=('0.0.0.0', self.port)
        )
        # Start periodic flush (runs even if no messages arrive)
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(f"UDP listener started on port {self.port}")

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

        if self.protocol:
            logger.info(f"UDP listener stopped ({self.protocol.message_count} messages processed)")

    async def _periodic_flush(self):
        """Flush buffer every 5 seconds."""
        while True:
            await asyncio.sleep(5.0)
            await self._flush_buffer()

    async def _flush_buffer(self):
        """Send buffered vessels to registry."""
        if not self.protocol or not self.protocol.vessel_buffer:
            return

        # Swap buffer atomically
        buffer = self.protocol.vessel_buffer
        self.protocol.vessel_buffer = {}

        station_id = self.protocol.station_id
        source = f"udp:{station_id}"

        for mmsi, data in buffer.items():
            await self.registry.update_vessel(mmsi, data, source)


class AISHubError(Exception):
    """AISHub API error."""
    pass


class AISHubPoller:
    """
    Polls AISHub API with exponential backoff.

    Alternates between regions (Welland/Montreal) every poll.
    Respects 60-second rate limit.
    """

    def __init__(self, registry: VesselRegistry):
        self.registry = registry
        self.current_region = "welland"
        self.last_poll: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.failure_count = 0
        self.next_retry: Optional[datetime] = None
        self.vessels_fetched = 0

    def _calculate_backoff(self) -> int:
        """Exponential backoff: 60s minimum, doubling, capped at 300s."""
        if self.failure_count <= 1:
            return 60
        return min(60 * (2 ** (self.failure_count - 1)), 300)

    async def poll(self) -> None:
        """Poll AISHub for current region."""
        now = datetime.now(timezone.utc)

        # Check if we're in backoff period
        if self.next_retry and now < self.next_retry:
            return

        try:
            vessels = await self._fetch_region(self.current_region)

            for vessel in vessels:
                mmsi = vessel.get("mmsi")
                if mmsi:
                    await self.registry.update_vessel(mmsi, vessel, "aishub")

            self.vessels_fetched += len(vessels)

            # Success - reset backoff
            if self.failure_count > 0:
                logger.info(f"AISHub: Recovered after {self.failure_count} failures")
            self.failure_count = 0
            self.next_retry = None
            self.last_error = None
            logger.debug(f"AISHub: {len(vessels)} vessels from {self.current_region}")

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
            raise AISHubError("AISHUB_API_KEY not configured")

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
            response = await client.get(base_url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

        # AISHub returns: [{"ERROR":false, ...}, [vessels]]
        if not isinstance(data, list):
            raise AISHubError(f"Unexpected response type: {type(data)}")

        if len(data) == 0:
            return []

        header = data[0]
        if header.get("ERROR"):
            raise AISHubError(f"API error: {header.get('ERROR_MESSAGE', 'Unknown')}")

        if len(data) < 2:
            return []  # No vessels in area

        vessels_raw = data[1]
        if not isinstance(vessels_raw, list):
            return []

        # Convert AISHub format to our format
        result = []
        for v in vessels_raw:
            mmsi = v.get("MMSI")
            if not mmsi:
                continue

            # Validate MMSI (ships are 200M-799M range)
            if not (200_000_000 <= mmsi <= 799_999_999):
                continue

            lat = v.get("LATITUDE")
            lon = v.get("LONGITUDE")
            if lat is None or lon is None:
                continue

            vessel = {
                "mmsi": mmsi,
                "name": sanitize_vessel_name(v.get("NAME")),
                "lat": lat,
                "lon": lon,
                "speed_knots": v.get("SOG"),
                "heading": v.get("HEADING") if v.get("HEADING", 511) < 360 else None,
                "course": v.get("COG") if v.get("COG", 360) < 360 else None,
                "type": v.get("TYPE"),
                "destination": sanitize_vessel_name(v.get("DEST")),
            }

            # Dimensions from A/B/C/D
            a, b, c, d = v.get("A", 0), v.get("B", 0), v.get("C", 0), v.get("D", 0)
            if a or b or c or d:
                vessel["dimensions"] = {"length": (a or 0) + (b or 0), "width": (c or 0) + (d or 0)}

            result.append(vessel)

        return result


class BoatTracker:
    """
    Orchestrates vessel tracking from all sources.

    Manages:
    - UDP listeners for local AIS dispatchers
    - AISHub API polling
    - Periodic vessel cleanup
    """

    def __init__(self):
        self.registry = VesselRegistry()
        self.udp_listener: Optional[UDPListener] = None
        self.aishub_poller: Optional[AISHubPoller] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start all boat tracking components."""
        self._running = True

        # Always start UDP listener (uses data if it arrives)
        udp_port = int(os.getenv('AIS_UDP_PORT', '10110'))
        self.udp_listener = UDPListener(self.registry, udp_port)
        await self.udp_listener.start()

        # Start AISHub poller if API key configured
        if os.getenv('AISHUB_API_KEY'):
            self.aishub_poller = AISHubPoller(self.registry)
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("AISHub poller started")
        else:
            logger.info("AISHub disabled (no API key)")

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("Boat tracker started")

    async def stop(self):
        """Stop all boat tracking components."""
        self._running = False

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self.udp_listener:
            await self.udp_listener.stop()

        logger.info("Boat tracker stopped")

    async def _poll_loop(self):
        """Poll AISHub every 60 seconds (rate limit)."""
        # Initial delay to let UDP data come in first
        await asyncio.sleep(5)

        while self._running:
            if self.aishub_poller:
                await self.aishub_poller.poll()
            await asyncio.sleep(60)

    async def _cleanup_loop(self):
        """Clean up stale vessels every 5 minutes."""
        while self._running:
            await asyncio.sleep(300)
            removed = await self.registry.cleanup_stale_vessels(max_age_minutes=15)
            if removed:
                logger.info(f"Cleaned up {removed} stale vessels")

    def get_boats_response(self) -> dict:
        """
        Build response for GET /boats endpoint.

        Returns:
            Dict with vessel data and status info
        """
        now = datetime.now(timezone.utc)
        moving = self.registry.get_moving_vessels(max_idle_minutes=30)
        udp_status = self.registry.get_udp_status()

        # Build status object
        status = {
            "udp": udp_status,
            "aishub": None,
        }

        if self.aishub_poller:
            status["aishub"] = {
                "ok": self.aishub_poller.failure_count == 0,
                "last_poll": self.aishub_poller.last_poll.isoformat() if self.aishub_poller.last_poll else None,
                "last_error": self.aishub_poller.last_error,
                "failure_count": self.aishub_poller.failure_count,
            }

        # Format vessels for response
        vessels = []
        for v in moving:
            vessels.append({
                "mmsi": v["mmsi"],
                "name": v.get("name"),
                "type_name": v.get("type_name", "Unknown"),
                "type_category": v.get("type_category", "other"),
                "position": {"lat": v["lat"], "lon": v["lon"]},
                "heading": v.get("heading"),
                "course": v.get("course"),
                "speed_knots": v.get("speed_knots"),
                "destination": v.get("destination"),
                "dimensions": v.get("dimensions"),
                "last_seen": v["last_seen"],
                "source": v["source"],
                "region": v["region"],
            })

        return {
            "last_updated": now.isoformat(),
            "vessel_count": len(vessels),
            "status": status,
            "vessels": vessels,
        }
