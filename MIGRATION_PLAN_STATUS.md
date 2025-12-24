# Migration Status Tracker

Last Updated: 2025-12-24

## Overview

Migrating from Firebase Firestore to self-hosted VPS with FastAPI + WebSocket + JSON storage.

**VPS Status**: Ready (Vultr Toronto, Caddy running, api.bridgeup.app DNS pointed)

---

## Backend Tasks

| Task | Status | Notes |
|------|--------|-------|
| Create `shared.py` | Done | Shared state module (avoids circular imports) |
| Create `predictions.py` | Done | Prediction logic moved from iOS |
| Create `main.py` | Done | FastAPI app + WebSocket + scheduler + CORS |
| Refactor `scraper.py` | Done | Replace Firestore with JSON + broadcast |
| Refactor `stats_calculator.py` | Done | Remove Firestore params, returns tuple |
| Update `requirements.txt` | Done | Add fastapi/uvicorn, remove firebase/waitress |
| Update `Dockerfile` | Done | uvicorn, port 8000 |
| Create `docker-compose.yml` | Done | App config for VPS deployment |
| Create `Caddyfile` | Done | Reverse proxy config |
| Create `tests/test_predictions.py` | Done | 20+ prediction tests |
| Run test suite | Done | All 9 test files pass (including new predictions) |

---

## Deploy Tasks

| Task | Status | Notes |
|------|--------|-------|
| VPS with Docker + network | Done | `docker network create web` |
| DNS A record | Done | api.bridgeup.app -> VPS IP |
| Deploy with docker-compose | Ready | Run `docker compose up -d` on VPS |
| Verify SSL (Caddy auto-provisions) | Pending | |
| Verify scraping + WebSocket | Pending | |
| Verify predictions in JSON | Pending | |
| Initial statistics calculation | Pending | Required for iOS app |

---

## iOS Tasks (for iOS team after backend ready)

| Task | Status | Notes |
|------|--------|-------|
| Remove Firebase SDK | Pending | |
| Remove hardcoded bridge list | Pending | Use `availableBridges` from backend |
| Remove prediction logic (~200 lines) | Pending | Now backend's job |
| Add WebSocket client | Pending | With ping timer and exponential backoff |
| Add new model types | Pending | `PredictedTime`, `AvailableBridge`, `BridgeResponse` |
| Update `LiveBridgeData` | Pending | Add `predicted: PredictedTime?` |
| Simplify info text generation | Pending | Format backend predictions |
| Test + submit app update | Pending | |

---

## Files Created/Modified

### New Files
- `shared.py` - Shared state module
- `predictions.py` - Prediction logic (from iOS)
- `main.py` - FastAPI application
- `docker-compose.yml` - Docker orchestration
- `Caddyfile` - Caddy reverse proxy config
- `tests/test_predictions.py` - Prediction tests

### Modified Files
- `scraper.py` - Replaced Firebase with JSON + WebSocket broadcast
- `stats_calculator.py` - Removed Firestore params
- `requirements.txt` - FastAPI stack
- `Dockerfile` - uvicorn entry point
- `run_tests.py` - Added prediction tests
- `tests/test_statistics.py` - Updated for new API
- `tests/test_network_backoff.py` - Updated mock targets

---

## Deployment Instructions

### On VPS (api.bridgeup.app)

1. Clone or pull the latest code:
```bash
git clone https://github.com/yourusername/bridge-up-backend
cd bridge-up-backend
```

2. Create environment file:
```bash
echo "OLD_JSON_ENDPOINT=your_endpoint_here" > .env
echo "NEW_JSON_ENDPOINT=your_endpoint_here" >> .env
```

3. Add Caddy configuration:
```bash
# Add contents of Caddyfile to /etc/caddy/Caddyfile or your Caddy config
sudo systemctl reload caddy
```

4. Deploy the application:
```bash
docker compose up -d --build
```

5. Verify health:
```bash
curl https://api.bridgeup.app/health
```

6. Run initial statistics (required for iOS):
```bash
docker exec bridgeup-app python -c "from scraper import daily_statistics_update; daily_statistics_update()"
```

---

## Progress Log

### 2025-12-24

- Started migration
- VPS confirmed ready with Caddy
- Created shared.py, predictions.py, main.py
- Refactored scraper.py (removed Firebase, added JSON + broadcast)
- Refactored stats_calculator.py (removed Firebase params)
- Updated requirements.txt, Dockerfile
- Created docker-compose.yml and Caddyfile
- Created test_predictions.py with 20+ tests
- Updated existing tests for new API
- **All 9 test files pass (100%)**
- Backend migration COMPLETE - ready for deployment

### 2025-12-24 (Review Pass)

**Issues Fixed During Review:**
1. **Dockerfile casing** - Renamed `dockerfile` to `Dockerfile` (Linux is case-sensitive)
2. **Docker healthcheck** - Changed from `curl` to Python urllib (slim image has no curl)
3. **Healthcheck start_period** - Increased from 10s to 30s (initial scrape runs at startup)
4. **Updated .dockerignore** - Excluded tests, docs, old files, .claude for smaller image

**Documentation Updated:**
- README.md - New architecture
- CLAUDE.md - New architecture
- .claude/agent/instructions.md - New architecture
- .claude/agent/memory.md - Added migration session
- .claude/shared/project-context.md - New architecture

**Verification:**
- All 9 test files pass (100%)
- All Python imports work correctly
- 5 regions, 15 bridges configured

**Python Version Decision:**
- Staying with Python 3.11-slim (stable, all deps compatible)
- No features in 3.12/3.13 needed for this project

