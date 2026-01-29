# Bridge Watch Push Notifications - Implementation Plan

## Overview

Add backend support for "Watch this bridge" feature. Users can watch a bridge for a duration (e.g., 2 hours) and receive notifications when status changes.

**Phased approach:**
- **Phase 1 (MVP):** Regular push notifications - much easier iOS work (~2 hrs)
- **Phase 2 (Later):** Live Activities - adds Lock Screen widget (~10 hrs iOS work)

Backend work is nearly identical for both phases.

## Phase Comparison

| Component | Phase 1: Push Notifications | Phase 2: Live Activities |
|-----------|---------------------------|-------------------------|
| Backend: APNs setup | Same | Same |
| Backend: Endpoints | Same | Same |
| Backend: Push logic | Same (different payload) | Same |
| iOS: Widget extension | Not needed | Required |
| iOS: 4 SwiftUI presentations | Not needed | Required |
| iOS: ActivityKit integration | Not needed | Required |
| iOS: Handle notification | ~2 hours | - |
| **iOS Total** | **~2 hours** | **~10 hours** |

## User Experience

### Phase 1: Push Notification
```
BridgeDetailView → "Notify me for 2 hours" → Done

[Later, bridge status changes]

┌─────────────────────────────────────┐
│ Bridge Up                      now  │
│ Queenston St is now closed          │
│ Opens in approximately 12 minutes   │
└─────────────────────────────────────┘
```

### Phase 2: Live Activity (Future)
```
Lock Screen shows live countdown widget that updates in real-time
```

---

## Architecture

```
iOS App → POST /watch → Backend stores token
Bridge status changes → Backend → APNs → Device notification
```

## New Files

| File | Purpose |
|------|---------|
| `apns.py` | APNs client (JWT auth, HTTP/2 push) |
| `watchers.py` | Watcher registry (in-memory + JSON backup) |
| `data/watchers.json` | Persistent storage for active watchers |

---

## Implementation Steps

### 1. Add Dependencies

```bash
# requirements.txt
aioapns==3.3        # Async APNs client (HTTP/2, token-based auth)
```

### 2. Environment Variables

```bash
# .env
APNS_KEY_PATH=/path/to/AuthKey_XXXXXXXX.p8
APNS_KEY_ID=XXXXXXXX          # 10-char Key ID from Apple
APNS_TEAM_ID=XXXXXXXXXX       # 10-char Team ID
APNS_BUNDLE_ID=com.example.bridgeup
APNS_USE_SANDBOX=false        # true for development
```

### 3. Create `watchers.py` - Watcher Registry

```python
"""
In-memory watcher registry with JSON file persistence.
Follows patterns from shared.py and boat_tracker.py.
"""
import threading
import os
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from scraper import atomic_write_json
from loguru import logger

WATCHERS_FILE = "data/watchers.json"

@dataclass
class Watcher:
    bridge_id: str
    device_id: str
    push_token: str
    created_at: str  # ISO format
    expires_at: str  # ISO format

# In-memory registry: {bridge_id: {device_id: Watcher}}
_watchers: dict[str, dict[str, Watcher]] = {}
_watchers_lock = threading.Lock()

def load_watchers() -> None:
    """Load watchers from JSON file on startup."""
    global _watchers
    if not os.path.exists(WATCHERS_FILE):
        return

    with _watchers_lock:
        with open(WATCHERS_FILE) as f:
            data = json.load(f)

        now = datetime.now(timezone.utc)
        for bridge_id, device_watchers in data.items():
            _watchers[bridge_id] = {}
            for device_id, w in device_watchers.items():
                # Skip expired watchers
                expires = datetime.fromisoformat(w["expires_at"])
                if expires > now:
                    _watchers[bridge_id][device_id] = Watcher(**w)

        logger.info(f"Loaded {sum(len(d) for d in _watchers.values())} active watchers")

def _save_watchers() -> None:
    """Persist watchers to JSON (call while holding lock)."""
    data = {
        bridge_id: {
            device_id: asdict(w)
            for device_id, w in device_watchers.items()
        }
        for bridge_id, device_watchers in _watchers.items()
        if device_watchers  # Skip empty bridges
    }
    atomic_write_json(WATCHERS_FILE, data)

def register_watcher(
    bridge_id: str,
    device_id: str,
    push_token: str,
    duration_hours: float
) -> datetime:
    """Register a new watcher. Returns expiration time."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=duration_hours)

    watcher = Watcher(
        bridge_id=bridge_id,
        device_id=device_id,
        push_token=push_token,
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat()
    )

    with _watchers_lock:
        if bridge_id not in _watchers:
            _watchers[bridge_id] = {}
        _watchers[bridge_id][device_id] = watcher
        _save_watchers()

    logger.info(f"Registered watcher: {bridge_id} for device {device_id[:8]}... expires {expires_at}")
    return expires_at

def unregister_watcher(bridge_id: str, device_id: str) -> bool:
    """Remove a watcher. Returns True if found and removed."""
    with _watchers_lock:
        if bridge_id in _watchers and device_id in _watchers[bridge_id]:
            del _watchers[bridge_id][device_id]
            _save_watchers()
            logger.info(f"Unregistered watcher: {bridge_id} for device {device_id[:8]}...")
            return True
    return False

def get_watchers_for_bridge(bridge_id: str) -> list[Watcher]:
    """Get all active (non-expired) watchers for a bridge."""
    now = datetime.now(timezone.utc)
    result = []
    expired = []

    with _watchers_lock:
        for device_id, w in _watchers.get(bridge_id, {}).items():
            expires = datetime.fromisoformat(w.expires_at)
            if expires > now:
                result.append(w)
            else:
                expired.append(device_id)

        # Lazy cleanup of expired watchers
        if expired:
            for device_id in expired:
                del _watchers[bridge_id][device_id]
            _save_watchers()

    return result

def remove_invalid_token(push_token: str) -> None:
    """Remove a watcher by push token (called when APNs returns invalid token)."""
    with _watchers_lock:
        for bridge_id, device_watchers in _watchers.items():
            for device_id, w in list(device_watchers.items()):
                if w.push_token == push_token:
                    del device_watchers[device_id]
                    logger.warning(f"Removed invalid token for {bridge_id}")
        _save_watchers()

def get_total_watcher_count() -> int:
    """Get total number of active watchers (for health endpoint)."""
    with _watchers_lock:
        return sum(len(d) for d in _watchers.values())
```

### 4. Create `apns.py` - APNs Client

```python
"""
APNs client for push notifications.
Uses aioapns for async HTTP/2 with token-based auth.

Supports both:
- Phase 1: Regular push notifications (alert banner)
- Phase 2: Live Activity updates (content-state)
"""
import os
import asyncio
from datetime import datetime, timezone
from aioapns import APNs, NotificationRequest, PushType
from aioapns.common import APNS_RESPONSE_CODE
from loguru import logger
from watchers import get_watchers_for_bridge, remove_invalid_token

# Configuration from environment
APNS_KEY_PATH = os.getenv("APNS_KEY_PATH")
APNS_KEY_ID = os.getenv("APNS_KEY_ID")
APNS_TEAM_ID = os.getenv("APNS_TEAM_ID")
APNS_BUNDLE_ID = os.getenv("APNS_BUNDLE_ID")
APNS_USE_SANDBOX = os.getenv("APNS_USE_SANDBOX", "false").lower() == "true"

# Global client (initialized in main.py lifespan)
_apns_client: APNs | None = None

def is_configured() -> bool:
    """Check if APNs is configured."""
    return all([APNS_KEY_PATH, APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID])

async def init_apns() -> None:
    """Initialize APNs client. Call during FastAPI startup."""
    global _apns_client

    if not is_configured():
        logger.warning("APNs not configured - push notifications disabled")
        return

    if not os.path.exists(APNS_KEY_PATH):
        logger.error(f"APNs key file not found: {APNS_KEY_PATH}")
        return

    _apns_client = APNs(
        key=APNS_KEY_PATH,
        key_id=APNS_KEY_ID,
        team_id=APNS_TEAM_ID,
        topic=APNS_BUNDLE_ID,  # Phase 1: regular push topic
        use_sandbox=APNS_USE_SANDBOX,
    )
    logger.info(f"APNs client initialized (sandbox={APNS_USE_SANDBOX})")

async def close_apns() -> None:
    """Close APNs client. Call during FastAPI shutdown."""
    global _apns_client
    if _apns_client:
        await _apns_client.close()
        _apns_client = None
        logger.info("APNs client closed")


def _format_prediction_text(predicted: dict | None) -> str:
    """Format prediction as human-readable text."""
    if not predicted:
        return ""

    lower = predicted.get("lower")
    if not lower:
        return ""

    try:
        lower_dt = datetime.fromisoformat(lower.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        minutes = int((lower_dt - now).total_seconds() / 60)
        if minutes > 0:
            return f" (~{minutes} min)"
    except:
        pass
    return ""


async def push_bridge_update(bridge_id: str, bridge_data: dict, old_status: str | None = None) -> None:
    """
    Send push notification to all watchers of a bridge.
    Called when bridge status changes.
    """
    if not _apns_client:
        return

    watchers = get_watchers_for_bridge(bridge_id)
    if not watchers:
        return

    live = bridge_data.get("live", {})
    static = bridge_data.get("static", {})

    bridge_name = static.get("name", bridge_id)
    new_status = live.get("status", "Unknown")
    predicted = live.get("predicted")

    # Build notification text based on status
    if new_status == "Closed":
        body = f"Now closed{_format_prediction_text(predicted)}"
    elif new_status == "Open":
        body = "Now open"
    elif new_status == "Closing soon":
        body = f"Closing soon{_format_prediction_text(predicted)}"
    elif new_status == "Opening":
        body = "Currently opening"
    elif new_status == "Closing":
        body = "Currently closing"
    else:
        body = f"Status: {new_status}"

    # Phase 1: Regular push notification payload
    payload = {
        "aps": {
            "alert": {
                "title": bridge_name,
                "body": body,
            },
            "sound": "default",
            "badge": 1,
        },
        # Custom data for app to handle tap
        "bridge_id": bridge_id,
        "status": new_status,
    }

    # Send to all watchers concurrently
    tasks = []
    for watcher in watchers:
        request = NotificationRequest(
            device_token=watcher.push_token,
            message=payload,
            push_type=PushType.ALERT,  # Phase 1: regular alert
        )
        tasks.append(_send_notification(request, watcher.push_token))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Sent {len(tasks)} push notifications for {bridge_id}: {new_status}")


async def _send_notification(request: NotificationRequest, token: str) -> None:
    """Send a single notification with error handling."""
    try:
        response = await _apns_client.send_notification(request)

        if not response.is_successful:
            if response.status == APNS_RESPONSE_CODE.BAD_DEVICE_TOKEN:
                logger.warning(f"Invalid device token, removing: {token[:16]}...")
                remove_invalid_token(token)
            elif response.status == APNS_RESPONSE_CODE.UNREGISTERED:
                logger.warning(f"Unregistered device, removing: {token[:16]}...")
                remove_invalid_token(token)
            else:
                logger.error(f"APNs error: {response.status} - {response.description}")
    except Exception as e:
        logger.error(f"APNs send failed: {e}")


async def push_to_all_changed_bridges(bridges_data: dict, changed_bridge_ids: set[str]) -> None:
    """
    Push updates to all watchers of changed bridges.
    Called from broadcast flow.
    """
    if not _apns_client or not changed_bridge_ids:
        return

    bridges = bridges_data.get("bridges", {})
    tasks = []

    for bridge_id in changed_bridge_ids:
        if bridge_id in bridges:
            tasks.append(push_bridge_update(bridge_id, bridges[bridge_id]))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

### 5. Add API Endpoints to `main.py`

```python
# New imports
from watchers import register_watcher, unregister_watcher, load_watchers, get_total_watcher_count
import apns

# Add to lifespan manager (startup)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    load_watchers()  # Load watchers from JSON
    await apns.init_apns()  # Initialize APNs client

    yield

    # ... existing shutdown code ...
    await apns.close_apns()

# Pydantic models
class WatchRequest(BaseModel):
    bridge_id: str = Field(description="Bridge ID to watch (e.g., 'SCT_QueenstonSt')")
    push_token: str = Field(description="APNs device token from iOS")
    device_id: str = Field(description="Unique device identifier")
    duration_hours: float = Field(default=2.0, ge=0.5, le=8.0, description="Watch duration (0.5-8 hours)")

class WatchResponse(BaseModel):
    bridge_id: str
    expires_at: str

# Endpoints
@app.post("/watch", response_model=WatchResponse, tags=["Notifications"])
@limiter.limit("30/minute")
async def watch_bridge(request: Request, body: WatchRequest):
    """
    Register to receive push notifications when a bridge status changes.

    The push_token is the standard APNs device token from iOS.
    Notifications are sent when the bridge status changes (e.g., Open → Closed).
    Registration expires after duration_hours.
    """
    # Validate bridge exists
    with open("data/bridges.json") as f:
        data = json.load(f)

    if body.bridge_id not in data.get("bridges", {}):
        raise HTTPException(status_code=404, detail=f"Bridge not found: {body.bridge_id}")

    expires_at = register_watcher(
        bridge_id=body.bridge_id,
        device_id=body.device_id,
        push_token=body.push_token,
        duration_hours=body.duration_hours
    )

    return WatchResponse(
        bridge_id=body.bridge_id,
        expires_at=expires_at.isoformat()
    )

@app.delete("/watch/{bridge_id}", tags=["Notifications"])
@limiter.limit("30/minute")
async def stop_watching(
    request: Request,
    bridge_id: str,
    x_device_id: str = Header(alias="X-Device-ID")
):
    """
    Stop receiving push notifications for a bridge.

    Call this when the user no longer wants notifications.
    """
    if not unregister_watcher(bridge_id, x_device_id):
        raise HTTPException(status_code=404, detail="Watcher not found")

    return {"status": "unregistered"}

# Update health endpoint to include watcher count
# Add to HealthResponse: push_watchers: int
# Add to health(): "push_watchers": get_total_watcher_count()
```

### 6. Hook into Broadcast Flow

Modify `scraper.py` to track changed bridges and trigger push:

```python
# In update_json_and_broadcast(), track which bridges changed
changed_bridge_ids: set[str] = set()

# When change detected (around line 654):
if new_live_compare != old_live_compare:
    updates_made = True
    changed_bridge_ids.add(doc_id)  # Track this bridge
    # ... rest of existing code ...

# After broadcast_sync(data), add push notification call:
if updates_made and changed_bridge_ids:
    # Schedule async push (non-blocking)
    if shared.main_loop and shared.main_loop.is_running():
        import apns
        asyncio.run_coroutine_threadsafe(
            apns.push_to_all_changed_bridges(data, changed_bridge_ids),
            shared.main_loop
        )
```

---

## APNs Payload Formats

### Phase 1: Regular Push Notification (MVP)
```json
{
  "aps": {
    "alert": {
      "title": "Queenston St",
      "body": "Now closed (~12 min)"
    },
    "sound": "default",
    "badge": 1
  },
  "bridge_id": "SCT_QueenstonSt",
  "status": "Closed"
}
```

**Headers:**
| Header | Value |
|--------|-------|
| `apns-push-type` | `alert` |
| `apns-topic` | `{bundle_id}` |
| `apns-priority` | `10` |

### Phase 2: Live Activity (Future)
```json
{
  "aps": {
    "timestamp": 1705936800,
    "event": "update",
    "content-state": {
      "bridgeId": "SCT_QueenstonSt",
      "bridgeName": "Queenston St",
      "status": "Closed",
      "predictedLower": "2025-01-22T15:30:00-05:00",
      "predictedUpper": "2025-01-22T15:45:00-05:00"
    }
  }
}
```

**Headers:**
| Header | Value |
|--------|-------|
| `apns-push-type` | `liveactivity` |
| `apns-topic` | `{bundle_id}.push-type.liveactivity` |
| `apns-priority` | `10` |

---

## Testing

### 1. Unit Tests (no APNs)

```bash
python -c "
from watchers import register_watcher, get_watchers_for_bridge, unregister_watcher

# Register
expires = register_watcher('SCT_Test', 'device123', 'token456', 0.1)
print(f'Registered, expires: {expires}')

# Get watchers
watchers = get_watchers_for_bridge('SCT_Test')
print(f'Found {len(watchers)} watchers')

# Unregister
unregister_watcher('SCT_Test', 'device123')
print('Unregistered')
"
```

### 2. Test with curl (requires iOS device token)

```bash
# Get push token from iOS app, then:
curl -X POST https://api.bridgeup.app/watch \
  -H "Content-Type: application/json" \
  -d '{
    "bridge_id": "SCT_QueenstonSt",
    "push_token": "your_device_token_here",
    "device_id": "test-device-123",
    "duration_hours": 1.0
  }'
```

### 3. Integration Test

1. iOS app registers for push notifications, gets device token
2. User taps "Notify me" → calls `POST /watch` with token
3. Bridge status changes → backend sends push
4. iOS receives notification banner
5. User taps notification → opens app to bridge detail

---

## Deployment Checklist

- [ ] Add `aioapns` to requirements.txt
- [ ] Create .p8 key in Apple Developer portal
- [ ] Add environment variables to VPS
- [ ] iOS app: Request notification permissions
- [ ] iOS app: Send device token to backend
- [ ] Deploy and test with sandbox first
- [ ] Switch to production APNs (`APNS_USE_SANDBOX=false`)
- [ ] Monitor APNs errors in logs

---

## File Changes Summary

| File | Change |
|------|--------|
| `requirements.txt` | Add `aioapns` |
| `watchers.py` | New file - watcher registry |
| `apns.py` | New file - APNs client |
| `main.py` | Add endpoints, init APNs in lifespan, health endpoint |
| `scraper.py` | Track changed bridges, trigger push |
| `.env.example` | Add APNs config vars |

---

## Estimated Effort

| Task | Backend | iOS (Phase 1) |
|------|---------|---------------|
| APNs setup (.p8 key) | 30 min | - |
| watchers.py | 1-2 hrs | - |
| apns.py | 2-3 hrs | - |
| main.py endpoints | 1 hr | - |
| scraper.py integration | 1 hr | - |
| Request permissions | - | 30 min |
| Send token to backend | - | 30 min |
| Handle notification tap | - | 30 min |
| UI for "Notify me" | - | 30 min |
| Testing | 2 hrs | 1 hr |
| **Total** | **8-10 hrs** | **~3 hrs** |

---

## Phase 2: Live Activities (Future)

When ready to add Live Activities:

1. **iOS work (~10 hrs):**
   - Create Widget Extension target
   - Define `ActivityAttributes` and `ContentState` structs
   - Build 4 SwiftUI presentations (compact, minimal, expanded, Lock Screen)
   - Integrate ActivityKit to start/update/end activities
   - Handle `pushTokenUpdates` sequence

2. **Backend changes (~1 hr):**
   - Add `push_type` field to watcher (to distinguish notification vs live activity)
   - Add second payload format for live activities
   - Use `apns-topic: {bundle}.push-type.liveactivity`
   - Use `PushType.LIVEACTIVITY` instead of `PushType.ALERT`

The watcher registry and APNs client infrastructure built in Phase 1 will be reused.
