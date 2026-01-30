# WebSocket Client Guide

Complete guide for iOS and web developers to integrate with the Bridge Up WebSocket API.

## Quick Start

```javascript
// Connect
const ws = new WebSocket("wss://api.bridgeup.app/ws");

// Subscribe on open
ws.onopen = () => {
  ws.send(JSON.stringify({
    action: "subscribe",
    channels: ["bridges", "boats"]
  }));
};

// Handle messages
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch (msg.type) {
    case "subscribed": console.log("Subscribed to:", msg.channels); break;
    case "bridges": handleBridges(msg.data); break;
    case "boats": handleBoats(msg.data); break;
  }
};
```

---

## Connection Flow

```
1. Connect to wss://api.bridgeup.app/ws
2. Nothing received (clean slate)
3. Send subscribe message
4. Receive confirmation + current data
5. Receive push updates when data changes
```

**Key Point:** Clients must explicitly subscribe. No data is sent until you subscribe.

---

## Channels

### Base Channels (All Data)

| Channel | Description |
|---------|-------------|
| `bridges` | All 15 bridges across all regions |
| `boats` | All vessels across all regions |

### Region-Filtered Channels

Subscribe to specific regions to:
- Receive only relevant data
- Get push updates only when that region changes
- Reduce bandwidth and battery usage

**Boat Regions:**

| Channel | Region | Description |
|---------|--------|-------------|
| `boats:welland` | Welland Canal | St. Catharines + Port Colborne area |
| `boats:montreal` | Montreal | South Shore + Kahnawake area |

**Bridge Regions:**

| Channel | Region | Bridges |
|---------|--------|---------|
| `bridges:sct` | St. Catharines | Highway 20, Glendale Ave, Queenston St, Lakeshore Rd, Carlton St |
| `bridges:pc` | Port Colborne | Clarence St, Main St, Mellanby Ave |
| `bridges:mss` | Montreal South Shore | Victoria Bridge variants, Sainte-Catherine |
| `bridges:k` | Kahnawake | CP Railway Bridges 7A, 7B |
| `bridges:sbs` | Salaberry/Beauharnois | St-Louis-de-Gonzague, Larocque Bridge |

---

## Subscribe Message

### Format

```json
{"action": "subscribe", "channels": ["channel1", "channel2"]}
```

### Rules

- `channels` is an array of channel names
- Each subscribe **replaces** previous subscription
- Empty array `[]` unsubscribes from all (connection stays open)
- Invalid channels are silently ignored

### Examples

```json
// All bridges, all boats
{"action": "subscribe", "channels": ["bridges", "boats"]}

// Welland area only (St. Catharines + Port Colborne bridges, Welland boats)
{"action": "subscribe", "channels": ["bridges:sct", "bridges:pc", "boats:welland"]}

// Montreal area only
{"action": "subscribe", "channels": ["bridges:mss", "bridges:k", "bridges:sbs", "boats:montreal"]}

// All bridges, only Welland boats
{"action": "subscribe", "channels": ["bridges", "boats:welland"]}

// Only boats, no bridges
{"action": "subscribe", "channels": ["boats"]}

// Unsubscribe from everything
{"action": "subscribe", "channels": []}
```

---

## Server Messages

All messages have a `type` field.

### Subscription Confirmation

```json
{"type": "subscribed", "channels": ["bridges", "boats"]}
```

Sent immediately after each subscribe. Shows your active subscriptions.

### Bridges Update

```json
{
  "type": "bridges",
  "data": {
    "last_updated": "2026-01-30T15:30:00-05:00",
    "available_bridges": [
      {"id": "SCT_CarltonSt", "name": "Carlton St.", "region_short": "SCT", "region": "St Catharines"}
    ],
    "bridges": {
      "SCT_CarltonSt": {
        "static": {
          "name": "Carlton St.",
          "region": "St Catharines",
          "region_short": "SCT",
          "coordinates": {"lat": 43.19, "lng": -79.20},
          "statistics": {
            "average_closure_duration": 12,
            "closure_ci": {"lower": 8, "upper": 16},
            "average_raising_soon": 3,
            "raising_soon_ci": {"lower": 2, "upper": 5},
            "closure_durations": {"under_9m": 45, "10_15m": 30, "16_30m": 15, "31_60m": 8, "over_60m": 2},
            "total_entries": 287
          }
        },
        "live": {
          "status": "Open",
          "last_updated": "2026-01-30T15:20:00-05:00",
          "predicted": null,
          "upcoming_closures": [],
          "responsible_vessel_mmsi": null
        }
      }
    }
  }
}
```

**When sent:**
- Immediately after subscribing to any bridges channel
- When any subscribed bridge changes status

**Region filtering:** If subscribed to `bridges:sct`, only SCT bridges are included.

### Boats Update

```json
{
  "type": "boats",
  "data": {
    "last_updated": "2026-01-30T15:30:00-05:00",
    "vessel_count": 6,
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
        "last_seen": "2026-01-30T15:29:58-05:00",
        "source": "udp:udp1",
        "region": "welland"
      }
    ]
  }
}
```

**When sent:**
- Immediately after subscribing to any boats channel
- When vessel data in subscribed regions changes (~30-60s based on AIS data)

**Region filtering:** If subscribed to `boats:welland`, only welland vessels are included.

---

## Bridge Status Values

| Status | Meaning | `predicted` field |
|--------|---------|-------------------|
| `Open` | Bridge is down, traffic flowing | `null` |
| `Closing soon` | Bridge will raise soon | When it will close |
| `Closing` | Bridge is currently raising | `null` |
| `Closed` | Bridge is up, no traffic | When it will open |
| `Opening` | Bridge is currently lowering | `null` |
| `Construction` | Scheduled maintenance | End time if known |
| `Unknown` | Status cannot be determined | `null` |

---

## Vessel Categories

| `type_category` | Description |
|-----------------|-------------|
| `cargo` | Cargo/freight ships |
| `tanker` | Tanker vessels |
| `tug` | Tugboats |
| `passenger` | Passenger/cruise ships |
| `fishing` | Fishing vessels |
| `sailing` | Sailing vessels |
| `pleasure` | Pleasure craft |
| `other` | Other vessel types |

---

## Push Behavior

### Bridges

- **Trigger:** Bridge status changes (e.g., Open → Closing soon)
- **Frequency:** Few times per day per bridge
- **Region filtering:** Only pushes if subscribed region changed

### Boats

- **Trigger:** Vessel data changes (position, new vessel, vessel leaves)
- **Frequency:** Every 30-60 seconds (matches AIS data arrival)
- **Region filtering:** Only pushes if subscribed region changed
- **Minimum interval:** 10 seconds between pushes (flood prevention)

**What triggers a boat push:**
- Vessel position changed
- New vessel entered region
- Vessel left region
- Vessel metadata updated (name, destination, dimensions)
- Heading, course, or speed changed

**What does NOT trigger a push:**
- `last_seen` timestamp updates (changes constantly)
- `source` field changes (can flip between udp/aishub)

---

## iOS Implementation

### WebSocket Manager

```swift
class WebSocketManager: NSObject, URLSessionWebSocketDelegate {
    private var webSocket: URLSessionWebSocketTask?
    private var session: URLSession!

    func connect() {
        session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        let url = URL(string: "wss://api.bridgeup.app/ws")!
        webSocket = session.webSocketTask(with: url)
        webSocket?.resume()
        receiveMessage()
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        subscribe()
    }

    func subscribe() {
        var channels = ["bridges"]

        if UserSettings.showBoatLayer {
            if let region = UserSettings.currentBoatRegion {
                channels.append("boats:\(region)")  // e.g., "boats:welland"
            } else {
                channels.append("boats")
            }
        }

        let msg = ["action": "subscribe", "channels": channels]
        if let data = try? JSONSerialization.data(withJSONObject: msg),
           let str = String(data: data, encoding: .utf8) {
            webSocket?.send(.string(str)) { _ in }
        }
    }

    func receiveMessage() {
        webSocket?.receive { [weak self] result in
            switch result {
            case .success(.string(let text)):
                self?.handleMessage(text)
            default:
                break
            }
            self?.receiveMessage()
        }
    }

    func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else { return }

        DispatchQueue.main.async {
            switch type {
            case "subscribed":
                print("Subscribed to: \(json["channels"] ?? [])")
            case "bridges":
                if let payload = json["data"] as? [String: Any] {
                    NotificationCenter.default.post(
                        name: .bridgesUpdated,
                        object: nil,
                        userInfo: ["data": payload]
                    )
                }
            case "boats":
                if let payload = json["data"] as? [String: Any] {
                    NotificationCenter.default.post(
                        name: .boatsUpdated,
                        object: nil,
                        userInfo: ["data": payload]
                    )
                }
            default:
                break
            }
        }
    }
}
```

### Update Subscription on Settings Change

```swift
// When user toggles boat layer or changes region
func updateSubscription() {
    WebSocketManager.shared.subscribe()
}
```

---

## Web Implementation

### Connection Manager

```javascript
class BridgeUpWebSocket {
  constructor() {
    this.ws = null;
    this.reconnectDelay = 1000;
  }

  connect() {
    this.ws = new WebSocket("wss://api.bridgeup.app/ws");

    this.ws.onopen = () => {
      console.log("Connected to Bridge Up");
      this.reconnectDelay = 1000;
      this.subscribe();
    };

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      this.handleMessage(msg);
    };

    this.ws.onclose = () => {
      console.log("Disconnected, reconnecting...");
      setTimeout(() => this.connect(), this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
    };
  }

  subscribe(channels = null) {
    if (!channels) {
      channels = ["bridges"];
      if (this.showBoats) {
        channels.push(this.boatRegion ? `boats:${this.boatRegion}` : "boats");
      }
    }

    this.ws.send(JSON.stringify({
      action: "subscribe",
      channels: channels
    }));
  }

  handleMessage(msg) {
    switch (msg.type) {
      case "subscribed":
        console.log("Subscribed to:", msg.channels);
        break;
      case "bridges":
        this.onBridgesUpdate?.(msg.data);
        break;
      case "boats":
        this.onBoatsUpdate?.(msg.data);
        break;
    }
  }
}

// Usage
const ws = new BridgeUpWebSocket();
ws.onBridgesUpdate = (data) => updateBridgeUI(data);
ws.onBoatsUpdate = (data) => updateBoatMarkers(data);
ws.connect();
```

---

## Example Sessions

### User Viewing All Data

```
→ Connect
← (nothing)

→ {"action": "subscribe", "channels": ["bridges", "boats"]}
← {"type": "subscribed", "channels": ["bridges", "boats"]}
← {"type": "bridges", "data": {... 15 bridges ...}}
← {"type": "boats", "data": {... all vessels ...}}

(bridge changes)
← {"type": "bridges", "data": {... 15 bridges ...}}

(boat moves ~30s later)
← {"type": "boats", "data": {... all vessels ...}}
```

### User Viewing Welland Only

```
→ Connect
← (nothing)

→ {"action": "subscribe", "channels": ["bridges:sct", "bridges:pc", "boats:welland"]}
← {"type": "subscribed", "channels": ["bridges:sct", "bridges:pc", "boats:welland"]}
← {"type": "bridges", "data": {... 8 SCT+PC bridges only ...}}
← {"type": "boats", "data": {... welland vessels only ...}}

(Montreal bridge changes)
← (nothing - not subscribed to that region)

(Welland boat moves)
← {"type": "boats", "data": {... welland vessels only ...}}

(SCT bridge changes)
← {"type": "bridges", "data": {... 8 SCT+PC bridges only ...}}
```

### User Toggles Boat Layer Off

```
(currently subscribed to bridges + boats)

→ {"action": "subscribe", "channels": ["bridges"]}
← {"type": "subscribed", "channels": ["bridges"]}
← {"type": "bridges", "data": {...}}

(boat moves)
← (nothing - not subscribed)
```

---

## HTTP Fallback Endpoints

If WebSocket is unavailable, these HTTP endpoints provide the same data:

| Endpoint | Description | Rate Limit |
|----------|-------------|------------|
| `GET /bridges` | All bridge data | 60/min |
| `GET /bridges/{id}` | Single bridge | 60/min |
| `GET /boats` | All vessel data | 60/min |

---

## Testing

### Using websocat

```bash
# Install
brew install websocat  # macOS
# or
cargo install websocat

# Connect and test
websocat wss://api.bridgeup.app/ws

# Then type:
{"action": "subscribe", "channels": ["bridges", "boats"]}
```

### Verify Region Filtering

```bash
# Subscribe to SCT only
{"action": "subscribe", "channels": ["bridges:sct"]}

# Should receive only 5 bridges (SCT region)
```

---

## Migration Checklist

- [ ] Update WebSocket handler to parse `type` field first
- [ ] Send subscribe message immediately after connection opens
- [ ] Handle `"subscribed"` confirmation message
- [ ] Handle `"bridges"` message type (data is in `msg.data`)
- [ ] Handle `"boats"` message type (data is in `msg.data`)
- [ ] Implement region filtering based on user's current view
- [ ] Update subscription when user changes region/toggles boat layer
- [ ] Remove HTTP polling for boats (WebSocket pushes on change)
- [ ] Test with websocat before deploying

---

## Questions?

Contact the backend team or open an issue at https://github.com/bridgeup/backend
