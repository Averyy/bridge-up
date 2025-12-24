# Bridge Up Backend

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Real-time bridge status monitoring for the St. Lawrence Seaway. Scrapes bridge data, calculates predictive statistics, and serves it via WebSocket and REST API.

**Hobby project** - Depends entirely on St Lawrence Seaway API. If they change the API or block access, it breaks. No warranty provided.

## Features

- Monitors bridge status from 5 regions (15 bridges total)
- Concurrent scraping - all bridges in 0.7 seconds
- Calculates predictive statistics from historical data
- Real-time updates every 20-30 seconds via WebSocket
- FastAPI + uvicorn for high performance
- JSON file storage (no database dependencies)
- Docker containerized for easy deployment
- Thread-safe concurrent execution
- Smart exponential backoff for failed regions (never gives up)
- Clean, structured logging with Loguru

## Architecture

```
St. Lawrence Seaway Websites -> Python Scraper -> JSON Storage -> WebSocket/REST -> iOS/Web Apps
```

### Endpoints
- `wss://api.bridgeup.app/ws` - WebSocket (real-time updates)
- `GET /bridges` - HTTP fallback (same data)
- `GET /bridges/{id}` - Single bridge
- `GET /health` - Health check
- `GET /docs` - OpenAPI documentation

## Quick Start

### Prerequisites
- Docker (recommended) or Python 3.11+
- `.env` file with API endpoints

### Docker (Production)

```bash
# Clone the repository
git clone https://github.com/yourusername/bridge-up-backend
cd bridge-up-backend

# Create environment file
echo "OLD_JSON_ENDPOINT=your_endpoint_here" > .env
echo "NEW_JSON_ENDPOINT=your_endpoint_here" >> .env

# Pull and run
docker compose pull
docker compose up -d

# Check health
curl https://api.bridgeup.app/health
```

### CI/CD Auto-Deploy

Pushing to `main` triggers GitHub Actions which:
1. Builds Docker image and pushes to Docker Hub
2. SSHs into VPS and runs `docker compose pull && docker compose up -d`

Required GitHub secrets: `DOCKER_HUB_USERNAME`, `DOCKER_HUB_ACCESS_TOKEN`, `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`

### Local Development

```bash
# Clone and setup
git clone https://github.com/yourusername/bridge-up-backend
cd bridge-up-backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env with API endpoints
# Run development server
uvicorn main:app --reload
```

### Initial Setup: Statistics Required

On first deployment, **you must manually run the statistics calculation**. The iOS app requires statistics data.

```bash
# Run once after initial deployment
docker exec bridge-up python -c "from scraper import daily_statistics_update; daily_statistics_update()"
```

Statistics are automatically recalculated daily at 3 AM.

## Key Files

- `main.py` - FastAPI application with WebSocket + scheduler
- `scraper.py` - Bridge data scraping and JSON updates
- `predictions.py` - Prediction calculations (moved from iOS)
- `stats_calculator.py` - Historical statistics calculation
- `shared.py` - Shared state module (avoids circular imports)
- `config.py` - Bridge configuration

## Schedule

- Scrapes every 20 seconds from 6:00 AM to 9:59 PM
- Scrapes every 30 seconds from 10:00 PM to 5:59 AM
- Runs daily statistics update at 3 AM

## Testing

**Always run tests before deploying or committing changes!**

```bash
# Run all tests (required before deployment)
python run_tests.py

# Individual test files
python tests/test_parsers.py          # JSON parsing logic
python tests/test_statistics.py       # Prediction calculations
python tests/test_predictions.py      # Prediction logic (from iOS)
python tests/test_status_edge_cases.py # Status interpretation
python tests/test_configuration.py    # Config validation
python tests/test_thread_safety.py    # Concurrent access safety
python tests/test_backoff.py          # Exponential retry logic
python tests/test_network_backoff.py  # Network failure handling
python tests/test_logging.py          # Logger configuration
```

## Contributing

PRs welcome! But **always run tests first**:
```bash
python run_tests.py  # Must pass before submitting PR
```

## License

GPL v3: You can do whatever you want as long you give attribution and the software you use it in also has an open license.
