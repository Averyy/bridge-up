# 🔼🌉🔽 Bridge Up Backend

[![Docker Image](https://img.shields.io/docker/v/averyyyy/bridge-up?style=flat-square&logo=docker)](https://hub.docker.com/r/averyyyy/bridge-up)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Real-time bridge status monitoring for the St. Lawrence Seaway. Scrapes bridge data, calculates predictive statistics, and serves it via Firestore.

⚠️ **Hobby project** - Depends entirely on St Lawrence Seaway API. If they change the API or block access, it breaks. No warranty provided.

## Features
- 👀 Monitors bridge status from 5 regions (15 bridges total)
- 🚀 Concurrent scraping - all bridges in 0.7 seconds
- 📊 Calculates predictive statistics from historical data
- 🔄 Real-time updates every 30-60 seconds
- 🔥 Firebase Firestore for data storage
- 🧹 Automatic cleanup of old data (300 entry history)
- 🐳 Docker containerized with GitHub Actions CI/CD
- 🔒 Thread-safe concurrent execution
- 📈 Smart exponential backoff for failed regions (never gives up)
- 📝 Clean, structured logging with Loguru

## Quick Start

### Prerequisites
- Docker (recommended) or Python 3.9+
- Firebase project with Firestore
- `firebase-auth.json` credentials file

### 🐳 Docker (Production)

```bash
# Pull from Docker Hub
docker pull averyyyy/bridge-up:latest

# Run with your Firebase credentials and environment variables
docker run -p 5000:5000 \
  -v /path/to/firebase-auth.json:/app/data/firebase-auth.json \
  -e OLD_JSON_ENDPOINT="your-endpoint-here" \
  -e NEW_JSON_ENDPOINT="your-endpoint-here" \
  averyyyy/bridge-up:latest
```

### 🔧 Local Development

```bash
# Clone and setup
git clone https://github.com/averyyyy/bridge-up-backend
cd bridge-up-backend
pip install -r requirements.txt

# Create .env with API endpoints (contact maintainer for values)
# Add firebase-auth.json to project root
# Run development server
python start_flask.py
```

### ⚠️ Initial Setup: Statistics Required

On first deployment or if statistics are missing, **you must manually run the statistics calculation**. The iOS app requires statistics data and will crash without it.

```bash
# Run once after initial deployment
python -c "from scraper import daily_statistics_update; daily_statistics_update()"

# Or in Docker
docker exec <container_name> python -c "from scraper import daily_statistics_update; daily_statistics_update()"
```

Statistics are automatically recalculated daily at 4 AM, but won't exist until then on a fresh deployment.


## Architecture

```
St. Lawrence Seaway Websites → Python Scraper → Firebase → iOS App
```

### Key Files
- `scraper.py` - Main scraping logic with concurrent execution
- `stats_calculator.py` - Calculates bridge statistics and predictions
- `config.py` - Bridge URLs and coordinates configuration
- `start_flask.py` - Development server
- `start_waitress.py` - Production server

### Schedule
- 🌞 Scrapes and updates bridge data every 20 seconds from 6:00 AM to 9:59 PM
- 🌙 Scrapes and updates bridge data every 30 seconds from 10:00 PM to 5:59 AM
- 🧮 Runs daily statistics update at 4 AM

## Testing

**⚠️ IMPORTANT: Always run tests before deploying or committing changes!**

```bash
# Run all tests (required before deployment)
python run_tests.py

# Individual test files
python tests/test_parsers.py          # JSON parsing logic
python tests/test_statistics.py       # Prediction calculations
python tests/test_status_edge_cases.py # Status interpretation
python tests/test_configuration.py    # Config validation
python tests/test_thread_safety.py    # Concurrent access safety
python tests/test_backoff.py          # Exponential retry logic
python tests/test_network_backoff.py  # Network failure handling
python tests/test_logging.py          # Logger configuration
```

The test suite protects core functionality and edge cases.

## Contributing

PRs welcome! But **always run tests first**:
```bash
python run_tests.py  # Must pass before submitting PR
```

Especially looking for:
- Missing bridge coordinates/numbers in `config.py`
- New bridge regions
- Additional test coverage

## License

GPL v3: You can do whatever you want as long you give attribution and the software you use it in also has a open license. 