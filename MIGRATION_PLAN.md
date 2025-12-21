# Bridge Up Backend Migration Plan

## Overview

Migrate from Firebase to a self-hosted $5/month VPS with fixed costs and full control.

## Why

- **Fixed cost**: $5/mo forever, no surprise bills
- **Full control**: No vendor lock-in
- **Simpler iOS**: Remove Firebase SDK entirely
- **Same features**: Everything works exactly as before

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Vultr Toronto ($5/mo)                       │
│              1 vCPU, 1GB RAM                             │
│                                                          │
│  ┌─────────┐     ┌──────────────────────────────────┐   │
│  │  Caddy  │────▶│         FastAPI                  │   │
│  │  (SSL)  │     │                                  │   │
│  └─────────┘     │  ┌──────────┐   ┌────────────┐  │   │
│                  │  │ Scraper  │──▶│ JSON Files │  │   │
│                  │  │ (20s/30s)│   │            │  │   │
│                  │  └────┬─────┘   └────────────┘  │   │
│                  │       │                         │   │
│                  │       ▼ (on change)             │   │
│                  │  ┌──────────┐                   │   │
│                  │  │Broadcast │──▶ iOS clients    │   │
│                  │  │WebSocket │                   │   │
│                  │  └──────────┘                   │   │
│                  │                                 │   │
│                  │  Endpoints:                     │   │
│                  │   • WS  /ws       (real-time)   │   │
│                  │   • GET /bridges  (fallback)    │   │
│                  │   • GET /health   (monitoring)  │   │
│                  └──────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
Seaway API
    │
    ▼
Scraper (every 20s day / 30s night)
    │
    ▼
Change detected?
    │
   Yes ──▶ Update bridges.json
    │              │
    │              ▼
    │      Broadcast to all WebSocket clients (instant)
    │
   No ──▶ Sleep → Repeat
```

---

## Data Storage

Simple JSON files (no database needed):

```
data/
├── bridges.json           # Live status + statistics for all 13 bridges
└── history/
    ├── SCT_CarltonSt.json
    ├── SCT_QueenstonSt.json
    ├── PC_MainSt.json
    └── ... (13 files, one per bridge, max 300 entries each)
```

### bridges.json structure
```json
{
  "last_updated": "2025-12-20T15:30:00-05:00",
  "bridges": {
    "SCT_CarltonSt": {
      "name": "Carlton St.",
      "region": "St Catharines",
      "region_short": "SCT",
      "coordinates": {"lat": 43.19, "lng": -79.20},
      "live": {
        "status": "Open",
        "raw_status": "Available",
        "available": true,
        "last_updated": "2025-12-20T15:30:00-05:00",
        "upcoming_closures": []
      },
      "statistics": {
        "average_closure_duration": 12,
        "closure_ci": {"lower": 8, "upper": 16},
        "average_raising_soon": 3,
        "raising_soon_ci": {"lower": 2, "upper": 5},
        "closure_durations": {
          "under_9m": 45,
          "10_15m": 30,
          "16_30m": 15,
          "31_60m": 8,
          "over_60m": 2
        },
        "total_entries": 287
      }
    }
  }
}
```

---

## Backend Code

### File Structure
```
backend/
├── main.py              # FastAPI app + WebSocket
├── scraper.py           # Existing code, modified for JSON storage
├── stats_calculator.py  # Unchanged
├── config.py            # Unchanged
├── data/
│   ├── bridges.json
│   └── history/
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
└── requirements.txt
```

### main.py (~40 lines)
```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
import json
import asyncio

connected_clients: list[WebSocket] = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scraper in background
    asyncio.create_task(run_scraper())
    yield

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    # Send current state immediately
    with open("data/bridges.json") as f:
        await websocket.send_text(f.read())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

async def broadcast(data: dict):
    """Called by scraper when data changes"""
    message = json.dumps(data)
    for client in connected_clients.copy():
        try:
            await client.send_text(message)
        except:
            connected_clients.remove(client)

@app.get("/bridges")
def get_bridges():
    with open("data/bridges.json") as f:
        return json.load(f)

@app.get("/health")
def health():
    return {"status": "ok"}
```

### Scraper Changes

**Keep unchanged:**
- `scrape_bridge_data()`
- `parse_old_json()` / `parse_new_json()`
- `interpret_bridge_status()`
- `interpret_tracked_status()`
- `stats_calculator.py` (entire file)
- `config.py` (entire file)
- Backoff/retry logic
- Concurrent scraping

**Replace:**
- `update_firestore()` → `update_json_and_broadcast()`
- `update_bridge_history()` → `append_to_history_file()`
- Remove all Firebase imports

### docker-compose.yml
```yaml
services:
  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    depends_on:
      - app
    restart: always

  app:
    build: .
    expose:
      - "8000"
    volumes:
      - ./data:/app/data
    environment:
      - OLD_JSON_ENDPOINT=${OLD_JSON_ENDPOINT}
      - NEW_JSON_ENDPOINT=${NEW_JSON_ENDPOINT}
    restart: always

volumes:
  caddy_data:
```

### Caddyfile
```
bridgeup.yourdomain.com {
    reverse_proxy app:8000
}
```

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data/history

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### requirements.txt
```
fastapi
uvicorn[standard]
requests
pytz
python-dotenv
cachetools
loguru
apscheduler
```

---

## iOS Changes

### Remove
- Firebase SDK (entire dependency)
- All Firestore listener code

### Add (~50 lines total)

```swift
class BridgeWebSocket: ObservableObject {
    @Published var bridges: [Bridge] = []
    private var task: URLSessionWebSocketTask?
    private let url = URL(string: "wss://bridgeup.yourdomain.com/ws")!

    func connect() {
        task = URLSession.shared.webSocketTask(with: url)
        task?.resume()
        listen()
    }

    private func listen() {
        task?.receive { [weak self] result in
            switch result {
            case .success(.string(let text)):
                if let data = text.data(using: .utf8),
                   let response = try? JSONDecoder().decode(BridgeResponse.self, from: data) {
                    DispatchQueue.main.async {
                        self?.bridges = response.bridges
                    }
                }
                self?.listen()
            case .failure:
                // Reconnect after 3 seconds
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                    self?.connect()
                }
            default:
                self?.listen()
            }
        }
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
    }
}
```

### Fallback polling (optional)
```swift
func fetchBridges() async throws -> [Bridge] {
    let url = URL(string: "https://bridgeup.yourdomain.com/bridges")!
    let (data, _) = try await URLSession.shared.data(from: url)
    return try JSONDecoder().decode(BridgeResponse.self, from: data).bridges
}
```

---

## Deployment

### Vultr Setup

1. Go to Vultr → Deploy → Cloud Compute
2. Select:
   - **Location**: Toronto
   - **OS**: Ubuntu 24.04 LTS x64
   - **Plan**: $5/mo (1 vCPU, 1GB RAM, 25GB SSD)
   - **Public IPv4**: Enabled
   - **Public IPv6**: Enabled (free)
   - **Automatic Backups**: Skip (data is reproducible)
   - **Hostname**: `bridgeup`

3. Point your domain to the VPS IP (A record)

### Initial Setup (one-time)

SSH in and run:
```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Create shared network for multiple projects
docker network create web
```

Clone repo and deploy:
```bash
git clone https://github.com/yourusername/bridge-up-backend
cd bridge-up-backend
echo "OLD_JSON_ENDPOINT=xxx" > .env
echo "NEW_JSON_ENDPOINT=xxx" >> .env
docker compose up -d
```

### GitHub Actions Auto-Deploy

**1. Generate SSH key on VPS:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_deploy  # Copy this private key
```

**2. Add GitHub secrets** (repo → Settings → Secrets → Actions):
- `VPS_HOST` = your server IP
- `VPS_SSH_KEY` = the private key from step 1

**3. Add workflow file:**
```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to VPS
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: root
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /root/bridge-up-backend
            git pull
            docker compose up -d --build
```

Now every push to main auto-deploys.

---

## Hosting Multiple Projects

The same $5 VPS can host multiple projects. Caddy routes by domain.

### Add a new Docker project
```bash
# Clone new project
cd /root
git clone https://github.com/you/other-project
cd other-project

# Add to shared network in docker-compose.yml:
# networks:
#   - web
# networks:
#   web:
#     external: true

docker compose up -d
```

### Add a static website
```bash
mkdir -p /var/www/mysite
# Put your HTML/CSS/JS files there
```

### Update Caddyfile
```
# Bridge Up API
bridgeup.yourdomain.com {
    reverse_proxy bridge-app:8000
}

# Another Docker app
otherapp.yourdomain.com {
    reverse_proxy other-app:3000
}

# Static website
www.yourdomain.com {
    root * /var/www/mysite
    file_server
}

# React/Vue SPA
app.yourdomain.com {
    root * /var/www/spa/dist
    file_server
    try_files {path} /index.html
}
```

### Reload Caddy
```bash
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Auto SSL for all domains. ~3-5 small apps fit on 1GB RAM.

---

## Costs

| Item | Cost |
|------|------|
| Vultr Toronto VPS | $5/mo |
| Domain (optional) | ~$10/yr |
| SSL (Let's Encrypt via Caddy) | Free |
| **Total** | **$5/mo fixed** |

---

## Migration Checklist

### Backend
- [ ] Create FastAPI app with WebSocket
- [ ] Modify scraper to use JSON storage
- [ ] Modify scraper to call broadcast() on changes
- [ ] Update history management for JSON files
- [ ] Update daily stats to read/write JSON
- [ ] Test locally
- [ ] Setup Vultr VPS
- [ ] Configure Caddy + SSL
- [ ] Deploy with Docker Compose
- [ ] Run initial statistics calculation
- [ ] Verify scraping works

### iOS
- [ ] Remove Firebase SDK dependency
- [ ] Add WebSocket client code
- [ ] Add polling fallback
- [ ] Update data models if needed
- [ ] Test WebSocket connection
- [ ] Test reconnection logic
- [ ] Submit app update

---

## Timeline

| Task | Time |
|------|------|
| Setup Vultr + Docker + Caddy | 1 hr |
| Modify scraper (Firebase → JSON) | 2-3 hrs |
| FastAPI + WebSocket | 1 hr |
| iOS WebSocket client | 2-3 hrs |
| Testing both ends | 2-3 hrs |
| **Total** | **~1-1.5 days** |

---

## Rollback Plan

Keep Firebase running during migration. If issues arise:
- iOS can switch back to Firebase SDK
- No data loss (Firebase still has everything)
- Revert iOS app via App Store

---

## What You Keep

- All 13 bridges monitored
- Real-time status updates (actually faster via WebSocket)
- Statistics and predictions
- History tracking (300 entries per bridge)
- Smart backoff on failures
- Concurrent scraping
- Daily stats recalculation

## What You Lose

- Nothing

## What You Gain

- **Fixed $5/mo cost** (no Firebase anxiety)
- **Faster updates** (WebSocket vs Firestore ~1-2s)
- **Simpler iOS code** (no Firebase SDK)
- **Full control** (your server, your data)
- **Room to grow** (same server can host other projects)
- **Toronto datacenter** (low latency for Canadian users)
