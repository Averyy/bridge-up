# 🌉 Bridge Up Backend

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

> *Know before you go.* Real-time bridge status and predictions for the St. Lawrence Seaway region.

Backend API powering the [Bridge Up iOS app](https://bridgeup.app) — never wait at a closed bridge again.

**⚠️ Hobby project** — Depends entirely on St Lawrence Seaway API. If they change the API or block access, it breaks. No warranty provided.

## ✨ Features

- 🌉 **15 bridges** across 5 regions monitored in real-time
- ⚡ **Concurrent scraping** — all bridges in ~0.7 seconds
- 📊 **Predictive intelligence** — reopening estimates based on 300+ closures per bridge
- 🔄 **Real-time updates** — every 20-30 seconds via WebSocket
- 🐳 **Docker containerized** — easy deployment
- 📁 **JSON file storage** — no database dependencies
- 🔒 **Thread-safe** — concurrent execution with proper locking
- 🔁 **Smart retry** — exponential backoff for failed regions (never gives up)

## 🗺️ Coverage

| Region | Bridges |
|--------|---------|
| **St. Catharines** | Highway 20, Glendale Ave, Queenston St, Lakeshore Rd, Carlton St |
| **Montreal** | Ste-Catherine, Victoria Downstream, Victoria Upstream |
| **Port Colborne** | Clarence St, Main St, Mellanby Ave |
| **Beauharnois** | Larocque Bridge, St-Louis-de-Gonzague |
| **Kahnawake** | CP Railway Bridge 7A & 7B |

## 🔌 API

**Base URL:** `https://api.bridgeup.app`

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `wss://api.bridgeup.app/ws` | WebSocket — real-time updates |
| `GET /bridges` | All bridges (same data as WebSocket) |
| `GET /bridges/{id}` | Single bridge by ID |
| `GET /health` | Health check |
| `GET /docs` | OpenAPI documentation |

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
          "closure_ci": {"lower": 8, "upper": 16},
          "raising_soon_ci": {"lower": 2, "upper": 5}
        }
      },
      "live": {
        "status": "Open",
        "last_updated": "2025-12-24T12:30:00-05:00",
        "predicted": null,
        "upcoming_closures": []
      }
    }
  }
}
```

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

# Run
docker compose up -d

# Check health
curl https://api.bridgeup.app/health
```

### Initial Setup

On first deployment, run statistics calculation (required for predictions):

```bash
docker exec bridge-up python -c "from scraper import daily_statistics_update; daily_statistics_update()"
```

Statistics recalculate automatically daily at 3 AM.

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

## 🧪 Testing

**Always run tests before deploying!**

```bash
python run_tests.py
```

## 📄 License

GPL v3 — Do whatever you want as long as you give attribution and your derivative work is also open source.
