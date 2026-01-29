# 🌉 Bridge Up Backend

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

> *Know before you go.* Real-time bridge status and predictions for the St. Lawrence Seaway region.

Backend API powering the [Bridge Up iOS app](https://bridgeup.app). Never wait at a closed bridge again.

**⚠️ Hobby project:** Depends entirely on St Lawrence Seaway API. If they change the API or block access, it breaks. No warranty provided.

## ✨ Features

- 🌉 **15 bridges** across 5 regions monitored in real-time
- 🚢 **Vessel tracking:** real-time ship positions via AIS
- 🔧 **Maintenance scraper:** auto-detects scheduled closures from Seaway website
- ⚡ **Concurrent scraping:** all bridges in ~0.7 seconds
- 📊 **Predictive intelligence:** reopening estimates based on 300+ closures per bridge
- 🔄 **Real-time updates:** every 20-30 seconds via WebSocket
- 🐳 **Docker containerized:** easy deployment
- 📁 **JSON file storage:** no database dependencies
- 🔒 **Thread-safe:** concurrent execution with proper locking
- 🔁 **Smart retry:** exponential backoff for failed regions (never gives up)

## 🗺️ Coverage

### Bridges

| Region | Bridges |
|--------|---------|
| **St. Catharines** | Highway 20, Glendale Ave, Queenston St, Lakeshore Rd, Carlton St |
| **Montreal** | Ste-Catherine, Victoria Downstream, Victoria Upstream |
| **Port Colborne** | Clarence St, Main St, Mellanby Ave |
| **Beauharnois** | Larocque Bridge, St-Louis-de-Gonzague |
| **Kahnawake** | CP Railway Bridge 7A & 7B |

### Boats

| Region | Bounds |
|--------|--------|
| **Welland Canal** | 42.75°N - 43.35°N, 79.35°W - 79.10°W |
| **Montréal** | 45.15°N - 45.60°N, 74.20°W - 73.35°W |

## 🔌 API

**Base URL:** `https://api.bridgeup.app`

### Endpoints

| Endpoint | Rate Limit | Cache | Description |
|----------|------------|-------|-------------|
| `wss://api.bridgeup.app/ws` | - | - | WebSocket (real-time bridge updates) |
| `GET /` | 30/min | 60s | API root with endpoint discovery |
| `GET /bridges` | 60/min | 10s | All bridges (same data as WebSocket) |
| `GET /bridges/{id}` | 60/min | 10s | Single bridge by ID |
| `GET /boats` | 60/min | 10s | Vessel positions in bridge regions |
| `GET /health` | 30/min | 5s | Health check |
| `GET /docs` | 30/min | 60s | API documentation |

**Rate limiting**: Per IP, returns 429 with `Retry-After: 60` header when exceeded.

### REST Example

```bash
curl https://api.bridgeup.app/bridges
```

### WebSocket Example

```javascript
const ws = new WebSocket('wss://api.bridgeup.app/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.bridges);
};
```

### Response Format

```json
{
  "last_updated": "2025-12-24T12:30:00-05:00",
  "available_bridges": [
    {"id": "SCT_CarltonSt", "name": "Carlton St.", "region_short": "SCT", "region": "St Catharines"}
  ],
  "bridges": {
    "SCT_CarltonSt": {
      "static": {
        "name": "Carlton St.",
        "region": "St Catharines",
        "coordinates": {"lat": 43.19, "lng": -79.20},
        "statistics": {
          "average_closure_duration": 12,
          "closure_ci": {"lower": 8, "upper": 16},
          "average_raising_soon": 3,
          "raising_soon_ci": {"lower": 2, "upper": 5},
          "total_entries": 287
        }
      },
      "live": {
        "status": "Open",
        "last_updated": "2025-12-24T12:30:00-05:00",
        "predicted": null,
        "upcoming_closures": [],
        "responsible_vessel_mmsi": null
      }
    }
  }
}
```

### Boats Response

```bash
curl https://api.bridgeup.app/boats
```

```json
{
  "last_updated": "2025-12-25T19:22:28Z",
  "vessel_count": 20,
  "status": {
    "udp": {"udp1": {"active": true, "last_message": "2025-12-25T19:22:28Z"}},
    "aishub": {"ok": true, "last_poll": "2025-12-25T19:22:28Z", "last_error": null, "failure_count": 0}
  },
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
      "last_seen": "2025-12-25T19:22:28Z",
      "source": "aishub",
      "region": "welland"
    }
  ]
}
```

**Vessel categories:** `cargo`, `tanker`, `tug`, `passenger`, `fishing`, `sailing`, `pleasure`, `other`

**Data sources:**
- UDP listeners (local AIS receivers) - real-time, ~1s latency
- AISHub API - polled every 60 seconds

**Configuration:**
| Variable | Description |
|----------|-------------|
| `AISHUB_API_KEY` | AISHub API key (optional, disables polling if not set) |
| `ENABLE_MAINTENANCE_SCRAPER` | Enable scheduled maintenance scraper (default: `true`) |

Send AIS NMEA sentences to the server's IP on port 10110. Supports up to 2 UDP sources (auto-assigned as `udp1`, `udp2`).

### Statistics Null Handling

Statistics fields return `null` only when no historical data exists for that type:

| Field | With Data | No Data |
|-------|-----------|---------|
| `average_closure_duration` | `12` | `null` |
| `closure_ci` | `{"lower": 8, "upper": 16}` | `null` |
| `average_raising_soon` | `3` | `null` |
| `raising_soon_ci` | `{"lower": 2, "upper": 5}` | `null` |

**Note:** CI requires 2+ entries to calculate. With fewer entries, CI is `null`. More entries = narrower CI range. Predictions still work internally with sensible defaults when statistics are null.

### Status Values

| Status | Meaning |
|--------|---------|
| `Open` | Bridge is open to traffic |
| `Closed` | Bridge is raised for vessel |
| `Closing soon` | Will close shortly |
| `Opening` | Currently lowering |
| `Construction` | Maintenance/work |

## 🏗️ Architecture

```
St. Lawrence Seaway API → Python Scraper → JSON Storage → FastAPI → WebSocket/REST → iOS/Web
```

### Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app with WebSocket + scheduler |
| `scraper.py` | Bridge data scraping and JSON updates |
| `predictions.py` | Prediction calculations |
| `stats_calculator.py` | Historical statistics |
| `config.py` | Bridge configuration |
| `boat_tracker.py` | Real-time vessel tracking (AIS) |
| `boat_config.py` | Vessel regions and type mappings |
| `responsible_boat.py` | Closure attribution (which vessel caused it) |
| `maintenance.py` | Maintenance override runtime logic |
| `maintenance_scraper.py` | Scheduled closure scraper (Seaway website) |

## 🚀 Quick Start

### Prerequisites
- Docker (recommended) or Python 3.11+
- `.env` file with API endpoints

### Docker (Production)

```bash
git clone https://github.com/Averyy/bridge-up-backend
cd bridge-up-backend

# Create environment file
echo "OLD_JSON_ENDPOINT=your_endpoint_here" > .env
echo "NEW_JSON_ENDPOINT=your_endpoint_here" >> .env
echo "AISHUB_API_KEY=your_aishub_api_key" >> .env

# Run
docker compose up -d

# Check health
curl https://api.bridgeup.app/health
```

### Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

## 🔄 CI/CD

Pushing to `main` triggers GitHub Actions:
1. Builds Docker image → pushes to Docker Hub
2. SSHs into VPS → `docker compose pull && docker compose up -d`

**Required secrets:** `DOCKER_HUB_USERNAME`, `DOCKER_HUB_ACCESS_TOKEN`, `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`

## ⏰ Schedule

- **6 AM – 10 PM:** Scrapes every 20 seconds
- **10 PM – 6 AM:** Scrapes every 30 seconds
- **3 AM daily:** Statistics recalculation
- **6 AM daily:** Maintenance page scraper (when enabled)

## 🧪 Testing

**Always run tests before deploying!**

```bash
python run_tests.py
```

## 📄 License

GPL v3: Do whatever you want as long as you give attribution and your derivative work is also open source.
