# Plan: WebSocket Channel Subscriptions

## Problem

Currently boats are served via HTTP polling (`GET /boats` every 30s), while bridges use WebSocket for instant updates. This creates:
- Slower boat position updates (30s vs instant)
- More battery drain on iOS (polling vs push)
- Higher server load (repeated HTTP requests)

## Solution

Implement a channel-based subscription system for WebSocket. Clients explicitly subscribe to the channels they want. Both channels use **push-on-change** - data is only sent when something actually changes.

```
Current:
- WebSocket /ws → bridges only (always sent)
- HTTP /boats → polled every 30s

New:
- WebSocket /ws → subscribe to channels: bridges, boats, or both
- Both channels push on change (no polling, no periodic push)
- HTTP /bridges, /boats → kept as backups (unchanged)
```

---

## Design Decisions

### 1. Array-Based Channel Subscriptions

Clients subscribe to an array of channels. Each channel is independent:

```json
// Client → Server
{"action": "subscribe", "channels": ["bridges"]}              // bridges only
{"action": "subscribe", "channels": ["boats"]}                // boats only
{"action": "subscribe", "channels": ["bridges", "boats"]}     // both
{"action": "subscribe", "channels": []}                       // unsubscribe all
```

**Why this approach:**
- Extensible - add new channels without combinatorial explosion
- Flexible - any combination allowed (including boats-only)
- Common pattern - similar to Pusher, Ably, other pub/sub systems
- Single message to set/change subscription
- New subscription replaces previous (no need for separate unsubscribe)

### 2. Connection Behavior

| Event | What Happens |
|-------|--------------|
| Client connects | Nothing sent (clean slate) |
| Client subscribes | Server confirms, then immediately sends current state for all subscribed channels |
| Subscription changes | New subscription replaces old, sends current state for all subscribed channels |
| Channel update occurs | Server pushes to clients subscribed to that channel |

### 3. Message Format: Typed Wrapper

All messages have a `type` field:

```json
// Data messages
{"type": "bridges", "data": {"last_updated": "...", "bridges": {...}}}
{"type": "boats", "data": {"last_updated": "...", "vessels": [...]}}

// Subscription confirmation
{"type": "subscribed", "channels": ["bridges", "boats"]}
```

### 4. Update Frequencies - Push on Change

Both channels use true push-on-change:

| Channel | Push Trigger | Expected Frequency |
|---------|--------------|-------------------|
| `bridges` | Bridge status changes | Few times per day per bridge |
| `boats` | Vessel data changes (position, new vessel, vessel leaves) | Every 30-60s (matches AIS data arrival) |

**Why push-on-change for boats:**
- AIS data sources update every 30-60 seconds (UDP: 30-45s, AISHub: 60s)
- Periodic 10s push would send identical data 3-6 times before it actually changes
- Push-on-change = no redundant data, less battery drain, true WebSocket pattern
- Minimum 5s interval between pushes prevents edge-case flooding

**What counts as a boat "change":**
- Vessel position updated
- New vessel entered region
- Vessel left region (out of bounds or stale)
- Vessel metadata updated (name, destination, dimensions)

### 5. HTTP Endpoints: Unchanged

All HTTP endpoints remain as backups:
- `GET /bridges` - bridge data fallback
- `GET /bridges/{id}` - single bridge lookup
- `GET /boats` - boat data fallback

---

## Message Protocol

### Client → Server

| Message | Description |
|---------|-------------|
| `{"action": "subscribe", "channels": ["bridges"]}` | Subscribe to bridges only |
| `{"action": "subscribe", "channels": ["boats"]}` | Subscribe to boats only |
| `{"action": "subscribe", "channels": ["bridges", "boats"]}` | Subscribe to both |
| `{"action": "subscribe", "channels": []}` | Unsubscribe from all (connection stays open) |
| Any other message | Ignored (pings, etc.) |

### Server → Client

| Type | When Sent | Payload |
|------|-----------|---------|
| `subscribed` | After subscribe action | `{"type": "subscribed", "channels": ["bridges", "boats"]}` |
| `bridges` | Immediately on subscribe + when status changes | Full bridge state |
| `boats` | Immediately on subscribe + when vessel data changes | Vessel positions |

### Example Flow

```
1. Client connects
   (nothing sent - waiting for subscription)

2. Client: {"action": "subscribe", "channels": ["bridges"]}
   Server: {"type": "subscribed", "channels": ["bridges"]}
   Server: {"type": "bridges", "data": {...}}

3. Bridge status changes (e.g., Open → Closing soon)
   Server: {"type": "bridges", "data": {...}}

4. Client: {"action": "subscribe", "channels": ["bridges", "boats"]}
   Server: {"type": "subscribed", "channels": ["bridges", "boats"]}
   Server: {"type": "bridges", "data": {...}}
   Server: {"type": "boats", "data": {...}}

5. New AIS data arrives (vessel moved, ~30-60s later)
   Server: {"type": "boats", "data": {...}}

6. No boat changes for a while
   (nothing sent - no redundant data)

7. Client: {"action": "subscribe", "channels": []}
   Server: {"type": "subscribed", "channels": []}
   (no more updates until next subscribe)
```

### Payload Structures

**Bridges:**
```json
{
  "type": "bridges",
  "data": {
    "last_updated": "2026-01-22T15:30:00-05:00",
    "available_bridges": [...],
    "bridges": {
      "PC_ClarenceSt": {
        "static": {...},
        "live": {
          "status": "Open",
          "last_updated": "...",
          "responsible_vessel_mmsi": 316001635
        }
      }
    }
  }
}
```

**Boats:**
```json
{
  "type": "boats",
  "data": {
    "last_updated": "2026-01-22T15:30:00-05:00",
    "vessel_count": 12,
    "vessels": [
      {
        "mmsi": 316001635,
        "name": "RT HON PAUL J MARTIN",
        "type_name": "Cargo",
        "type_category": "cargo",
        "position": {"lat": 42.92, "lon": -79.24},
        "heading": 10,
        "course": 8.9,
        "speed_knots": 7.2,
        "destination": "MONTREAL",
        "dimensions": {"length": 225, "width": 24},
        "last_seen": "2026-01-22T15:29:58-05:00",
        "source": "udp:udp1",
        "region": "welland"
      }
    ]
  }
}
```

---

## Implementation

### Step 1: Add WebSocketClient Class

**File: `shared.py`** - Add after existing imports

```python
from dataclasses import dataclass, field
from typing import Set, TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket


@dataclass
class WebSocketClient:
    """
    Tracks per-client WebSocket state and channel subscriptions.

    Attributes:
        websocket: The WebSocket connection
        channels: Set of channels the client is subscribed to
    """
    websocket: 'WebSocket'
    channels: Set[str] = field(default_factory=set)

    def wants_bridges(self) -> bool:
        """Check if client is subscribed to bridge updates."""
        return "bridges" in self.channels

    def wants_boats(self) -> bool:
        """Check if client is subscribed to boat updates."""
        return "boats" in self.channels
```

**Update `connected_clients` type hint:**
```python
# WebSocket clients (managed by main.py, used by scraper for broadcasting)
connected_clients: List['WebSocketClient'] = []
```

**Add boat broadcast state tracking:**
```python
# Last broadcast state for boats channel (for change detection)
# Structure: serialized JSON string of last broadcast payload
last_boats_broadcast: Optional[str] = None
last_boats_broadcast_time: float = 0.0
BOATS_MIN_BROADCAST_INTERVAL = 5.0  # Minimum seconds between broadcasts (flood prevention)
```

### Step 2: Update WebSocket Endpoint

**File: `main.py`** - Replace `websocket_endpoint()` function

```python
# Valid channel names
VALID_CHANNELS = {"bridges", "boats"}


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
    from shared import WebSocketClient

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


async def handle_client_message(client: 'WebSocketClient', raw: str):
    """Handle incoming client messages (subscribe)."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return  # Ignore malformed messages

    action = msg.get("action")

    if action == "subscribe":
        requested_channels = msg.get("channels", [])

        # Validate and filter to known channels
        if not isinstance(requested_channels, list):
            return
        valid_requested = set(requested_channels) & VALID_CHANNELS

        # Update subscription (replaces previous)
        client.channels = valid_requested

        # Send confirmation
        await client.websocket.send_text(
            json.dumps({"type": "subscribed", "channels": list(client.channels)})
        )

        # Send current state for all subscribed channels
        # (simpler than tracking new vs existing - subscribe is infrequent)
        if client.wants_bridges():
            await send_bridges_to_client(client)
        if client.wants_boats():
            await send_boats_to_client(client)

        logger.debug(
            f"Client subscribed to {list(client.channels)} "
            f"(bridges: {sum(1 for c in connected_clients if c.wants_bridges())}, "
            f"boats: {sum(1 for c in connected_clients if c.wants_boats())})"
        )


async def send_bridges_to_client(client: 'WebSocketClient'):
    """Send current bridge state to a single client."""
    from responsible_boat import find_responsible_vessel

    if not os.path.exists("data/bridges.json"):
        return

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

    message = json.dumps({"type": "bridges", "data": data}, default=str)
    await client.websocket.send_text(message)


async def send_boats_to_client(client: 'WebSocketClient'):
    """Send current boat state to a single client."""
    if not boat_tracker:
        return

    boats_data = boat_tracker.get_boats_response()

    payload = {
        "last_updated": boats_data["last_updated"],
        "vessel_count": boats_data["vessel_count"],
        "vessels": boats_data["vessels"]
    }

    message = json.dumps({"type": "boats", "data": payload}, default=str)
    await client.websocket.send_text(message)
```

### Step 3: Update broadcast() for Channel Filtering

**File: `main.py`** - Modify existing `broadcast()` function

```python
async def broadcast(data: dict):
    """
    Broadcast bridge data to clients subscribed to 'bridges' channel.
    Called when bridge status changes (from scraper).
    """
    from responsible_boat import find_responsible_vessel

    # Get subscribers
    subscribers = [c for c in connected_clients if c.wants_bridges()]
    if not subscribers:
        return

    # Deep copy to avoid modifying original
    broadcast_data = copy.deepcopy(data)

    # Inject responsible vessels
    vessels = []
    if boat_tracker:
        vessels = boat_tracker.registry.get_moving_vessels(max_idle_minutes=VESSEL_IDLE_THRESHOLD_MINUTES)

    for bridge_id, bridge_data in broadcast_data.get("bridges", {}).items():
        live = bridge_data.get("live", {})
        status = live.get("status", "Unknown")
        responsible_mmsi = find_responsible_vessel(bridge_id, status, vessels)
        live["responsible_vessel_mmsi"] = responsible_mmsi

    message = json.dumps({"type": "bridges", "data": broadcast_data}, default=str)
    disconnected = []

    for client in subscribers:
        try:
            await client.websocket.send_text(message)
        except Exception:
            disconnected.append(client)

    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)
```

### Step 4: Add Push-on-Change Boat Broadcasting

**File: `main.py`** - Add new functions for change-based boat broadcasting

```python
async def broadcast_boats_if_changed():
    """
    Broadcast boat positions to subscribers if data has changed.

    Called after registry updates (UDP flush or AISHub poll).
    Only broadcasts if:
    1. There are boat subscribers
    2. Data has actually changed since last broadcast
    3. Minimum interval (5s) has passed (flood prevention)
    """
    import time

    if not boat_tracker:
        return

    # Check if anyone is subscribed
    subscribers = [c for c in connected_clients if c.wants_boats()]
    if not subscribers:
        return

    # Check minimum interval (flood prevention)
    now = time.time()
    if now - shared.last_boats_broadcast_time < shared.BOATS_MIN_BROADCAST_INTERVAL:
        return

    # Get current boat data
    boats_data = boat_tracker.get_boats_response()

    payload = {
        "last_updated": boats_data["last_updated"],
        "vessel_count": boats_data["vessel_count"],
        "vessels": boats_data["vessels"]
    }

    # Serialize for comparison (consistent ordering for reliable comparison)
    current_state = json.dumps(payload, sort_keys=True, default=str)

    # Check if anything changed
    if current_state == shared.last_boats_broadcast:
        return  # No changes, don't broadcast

    # Data changed - broadcast to all subscribers
    message = json.dumps({"type": "boats", "data": payload}, default=str)
    disconnected = []

    for client in subscribers:
        try:
            await client.websocket.send_text(message)
        except Exception:
            disconnected.append(client)

    for client in disconnected:
        if client in connected_clients:
            connected_clients.remove(client)

    # Update last broadcast state
    shared.last_boats_broadcast = current_state
    shared.last_boats_broadcast_time = now

    logger.debug(f"Broadcast boats to {len(subscribers)} subscribers ({payload['vessel_count']} vessels)")


def broadcast_boats_if_changed_sync():
    """Synchronous wrapper for boat broadcast, called from registry update hooks."""
    if shared.main_loop and shared.main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_boats_if_changed(), shared.main_loop)
```

### Step 5: Hook into Registry Updates

**File: `boat_tracker.py`** - Add callback after registry updates

In `VesselRegistry.update_vessel()`, after updating vessel data:
```python
# Notify WebSocket subscribers of change
try:
    from main import broadcast_boats_if_changed_sync
    broadcast_boats_if_changed_sync()
except ImportError:
    pass  # Running standalone
```

In `UDPListener._flush_buffer()`, after flushing to registry:
```python
# Notify WebSocket subscribers after batch update
try:
    from main import broadcast_boats_if_changed_sync
    broadcast_boats_if_changed_sync()
except ImportError:
    pass  # Running standalone
```

In `AISHubPoller._process_response()`, after processing vessels:
```python
# Notify WebSocket subscribers after AISHub update
try:
    from main import broadcast_boats_if_changed_sync
    broadcast_boats_if_changed_sync()
except ImportError:
    pass  # Running standalone
```

**Alternative approach** - Use a periodic check instead of hooks (simpler, less invasive):

**File: `main.py`** - Add a lightweight periodic checker

```python
BOATS_CHECK_INTERVAL_SECONDS = 5  # Check for changes every 5s


async def check_and_broadcast_boats():
    """
    Periodically check if boat data changed and broadcast if so.
    This is simpler than hooking into registry updates directly.
    """
    await broadcast_boats_if_changed()


def check_and_broadcast_boats_sync():
    """Synchronous wrapper for scheduler."""
    if shared.main_loop and shared.main_loop.is_running():
        asyncio.run_coroutine_threadsafe(check_and_broadcast_boats(), shared.main_loop)
```

**In `lifespan()` startup section, add scheduler job:**

```python
scheduler.add_job(
    check_and_broadcast_boats_sync,
    'interval',
    seconds=BOATS_CHECK_INTERVAL_SECONDS,
    id='boat_change_check',
    max_instances=1,
    coalesce=True
)
```

**Note:** The periodic check approach is recommended because:
- Simpler implementation (no hooks into boat_tracker.py)
- 5s check interval + change detection = broadcasts only when data changes
- Less coupling between modules
- Still achieves push-on-change behavior

### Step 6: Update Health Endpoint

**File: `main.py`** - Add subscriber counts to health response

```python
"websocket_clients": len(connected_clients),
"websocket_bridges_subscribers": sum(1 for c in connected_clients if c.wants_bridges()),
"websocket_boats_subscribers": sum(1 for c in connected_clients if c.wants_boats()),
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `shared.py` | Add `WebSocketClient` dataclass, update `connected_clients` type, add `last_boats_broadcast` state |
| `main.py` | Update `websocket_endpoint()`, `broadcast()`, add `broadcast_boats_if_changed()`, add scheduler job, update health endpoint |

---

## iOS App Changes Required

### 1. Handle New Message Format

```swift
func handleMessage(_ text: String) {
    guard let data = text.data(using: .utf8),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let type = json["type"] as? String else {
        return
    }

    switch type {
    case "bridges":
        if let payload = json["data"] {
            handleBridgeUpdate(payload)
        }
    case "boats":
        if let payload = json["data"] {
            handleBoatUpdate(payload)
        }
    case "subscribed":
        if let channels = json["channels"] as? [String] {
            handleSubscriptionConfirmed(channels)
        }
    default:
        break
    }
}
```

### 2. Subscribe on Connect

```swift
func websocketDidConnect() {
    var channels = ["bridges"]  // Always want bridges

    if UserSettings.showBoatLayer {
        channels.append("boats")
    }

    sendMessage(["action": "subscribe", "channels": channels])
}
```

### 3. Update Subscription When Settings Change

```swift
func boatLayerToggled(enabled: Bool) {
    var channels = ["bridges"]
    if enabled {
        channels.append("boats")
    }
    sendMessage(["action": "subscribe", "channels": channels])
}
```

### 4. Remove HTTP Polling for Boats

Once WebSocket is working, remove the 30s HTTP polling for boats. The WebSocket will push updates whenever vessel data changes (approximately every 30-60s based on AIS data arrival).

---

## Testing Plan

### Unit Tests (`tests/test_websocket_channels.py`)

1. **WebSocketClient class**
   - Default state: no channels subscribed
   - `wants_bridges()` / `wants_boats()` return correct values
   - Channels can be updated

2. **Subscription handling**
   - Subscribe to single channel works
   - Subscribe to multiple channels works
   - Subscribe replaces previous subscription
   - Invalid channels are ignored
   - Empty channels array unsubscribes all

3. **Broadcast filtering**
   - `broadcast()` only sends to bridges subscribers
   - `broadcast_boats_if_changed()` only sends to boats subscribers
   - Unsubscribed clients don't receive messages

4. **Change detection**
   - No broadcast when data unchanged
   - Broadcast when vessel position changes
   - Broadcast when vessel added/removed
   - Minimum interval respected (flood prevention)

### Integration Test

```
1. Connect → nothing received
2. Subscribe ["bridges"] → confirmation + bridges data
3. Bridge changes → bridges update received
4. Subscribe ["bridges", "boats"] → confirmation + bridges + boats data (always sends all subscribed)
5. Wait for AIS data to arrive (~30-60s) → boats update received
6. No vessel changes → no redundant boats messages
7. Subscribe ["boats"] → confirmation + boats only
8. Bridge changes → NOT received (not subscribed)
9. Subscribe [] → confirmation, no more updates
```

### Manual Test

```bash
websocat wss://api.bridgeup.app/ws

# Nothing received on connect

# Subscribe to bridges
{"action": "subscribe", "channels": ["bridges"]}
# Should receive: {"type": "subscribed", ...} then {"type": "bridges", ...}

# Add boats
{"action": "subscribe", "channels": ["bridges", "boats"]}
# Should receive confirmation, bridges, boats
# Then boats updates only when vessel data actually changes (~30-60s)
```

---

## Verification Steps

1. Run existing tests: `python run_tests.py`
2. Run new tests: `pytest tests/test_websocket_channels.py -v`
3. Manual test with websocat
4. Deploy to staging, test with iOS TestFlight
5. Monitor health endpoint for subscriber counts
6. Verify boats updates only arrive when data changes (not periodically)
7. Provide WebSocket API documentation to website and iOS developers (see below)

---

## Developer Documentation

Provide this to website and iOS developers for client updates.

---

### WebSocket API v2 - Channel Subscriptions

#### Breaking Change Summary

The WebSocket endpoint (`wss://api.bridgeup.app/ws`) now uses a subscription model. **Clients must explicitly subscribe to receive data.**

| Before | After |
|--------|-------|
| Connect → immediately receive bridges data | Connect → nothing (must subscribe first) |
| Bridges only | Bridges and/or boats |
| Raw JSON payload | Typed messages with `{"type": "...", "data": {...}}` |

---

#### Connection Flow

```
1. Connect to wss://api.bridgeup.app/ws
2. Send subscribe message
3. Receive confirmation + current data
4. Receive push updates when data changes
```

---

#### Message Format

**Client → Server**

```json
{"action": "subscribe", "channels": ["bridges"]}
{"action": "subscribe", "channels": ["boats"]}
{"action": "subscribe", "channels": ["bridges", "boats"]}
{"action": "subscribe", "channels": []}
```

- `channels` is an array of channel names
- Valid channels: `"bridges"`, `"boats"`
- Each subscribe **replaces** the previous subscription
- Empty array unsubscribes from all (connection stays open)

**Server → Client**

All messages have a `type` field:

```json
{"type": "subscribed", "channels": ["bridges", "boats"]}
{"type": "bridges", "data": {...}}
{"type": "boats", "data": {...}}
```

---

#### Payload Structures

**`type: "bridges"`**

```json
{
  "type": "bridges",
  "data": {
    "last_updated": "2026-01-22T15:30:00-05:00",
    "available_bridges": [
      {"id": "PC_ClarenceSt", "name": "Clarence St.", "region_short": "PC", "region": "Port Colborne"}
    ],
    "bridges": {
      "PC_ClarenceSt": {
        "static": {
          "name": "Clarence St.",
          "region": "Port Colborne",
          "region_short": "PC",
          "coordinates": {"lat": 42.88, "lng": -79.25},
          "statistics": {...}
        },
        "live": {
          "status": "Open",
          "last_updated": "2026-01-22T15:20:00-05:00",
          "predicted": null,
          "upcoming_closures": [],
          "responsible_vessel_mmsi": null
        }
      }
    }
  }
}
```

**`type: "boats"`**

```json
{
  "type": "boats",
  "data": {
    "last_updated": "2026-01-22T15:30:00-05:00",
    "vessel_count": 12,
    "vessels": [
      {
        "mmsi": 316001635,
        "name": "RT HON PAUL J MARTIN",
        "type_name": "Cargo",
        "type_category": "cargo",
        "position": {"lat": 42.92, "lon": -79.24},
        "heading": 10,
        "course": 8.9,
        "speed_knots": 7.2,
        "destination": "MONTREAL",
        "dimensions": {"length": 225, "width": 24},
        "last_seen": "2026-01-22T15:29:58-05:00",
        "source": "udp:udp1",
        "region": "welland"
      }
    ]
  }
}
```

---

#### Update Frequency

| Channel | When Pushed |
|---------|-------------|
| `bridges` | When any bridge status changes (few times per day per bridge) |
| `boats` | When vessel data changes (~every 30-60 seconds based on AIS data) |

Both channels use **push-on-change** - no polling needed, no redundant data sent.

---

#### Example Session

```
→ Client connects
  (nothing received)

→ Client sends: {"action": "subscribe", "channels": ["bridges"]}
← Server sends: {"type": "subscribed", "channels": ["bridges"]}
← Server sends: {"type": "bridges", "data": {...}}

  (bridge status changes later)
← Server sends: {"type": "bridges", "data": {...}}

→ Client sends: {"action": "subscribe", "channels": ["bridges", "boats"]}
← Server sends: {"type": "subscribed", "channels": ["bridges", "boats"]}
← Server sends: {"type": "bridges", "data": {...}}
← Server sends: {"type": "boats", "data": {...}}

  (vessel position updates ~30-60s later)
← Server sends: {"type": "boats", "data": {...}}
```

---

#### Migration Checklist

- [ ] Update WebSocket message handler to parse `type` field first
- [ ] Send subscribe message immediately after connection opens
- [ ] Handle `"subscribed"` confirmation message
- [ ] Handle `"bridges"` and `"boats"` message types
- [ ] Remove HTTP polling for boats if using WebSocket boats channel

---

#### HTTP Endpoints (Unchanged)

These remain available as fallbacks:

| Endpoint | Description |
|----------|-------------|
| `GET /bridges` | All bridge data |
| `GET /bridges/{id}` | Single bridge |
| `GET /boats` | All vessel positions |

---

#### Testing

```bash
# Using websocat
websocat wss://api.bridgeup.app/ws

# Then type:
{"action": "subscribe", "channels": ["bridges", "boats"]}
```
