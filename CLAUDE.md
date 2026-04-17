# Bridge Up Backend - Claude Guidelines

See @docs/api-reference.md for API endpoints, WebSocket protocol, JSON schema, and rate limiting.

## Project Overview

This is the Python backend for Bridge Up - a bridge monitoring system that scrapes real-time bridge status data from St. Lawrence Seaway websites and serves it via WebSocket and REST API.

**Key Context**: This backend is the **authoritative data source** for all clients (iOS, web). It scrapes, processes, calculates predictions, and serves all bridge status information.

**Agent Documentation**: When working on this project, also review:
- `.claude/agent/instructions.md` - Agent-specific responsibilities and workflow
- `.claude/agent/memory.md` - Session history and lessons learned
- `.claude/shared/project-context.md` - Detailed project architecture

## Critical Rules - DO NOT VIOLATE

- **ALWAYS run tests before committing or deploying** - use `python run_tests.py`
- **NEVER change the JSON schema** without coordinating with iOS app
- **ALWAYS preserve the data processing algorithms** - they're core to the predictions
- **NEVER break the scheduling system** - it's critical for real-time updates
- **Respect scraping ethics** - don't aggressively scrape or you'll get IP blocked

## Status Mapping (DO NOT CHANGE)

```python
# Status normalization in interpret_bridge_status():
# - "Available" -> "Open"
# - "Available (raising soon)" -> "Closing soon"
# - "Unavailable" -> "Closed"
# - "Unavailable (lowering)" -> "Opening"
# - "Unavailable (raising)" -> "Closing"
# - "Unavailable (work in progress)" -> "Construction"
# - All other statuses -> "Unknown"
```

## Development

```bash
# Run tests (REQUIRED before commit/deploy)
python run_tests.py

# Dev server
uvicorn main:app --reload

# Test scraper standalone
python scraper.py
```

**Deployment** (on VPS at api.bridgeup.app):

```bash
docker compose pull && docker compose up -d
curl https://api.bridgeup.app/health
```

## Non-obvious Gotchas

- **SSL**: Using `verify=False` for seaway-greatlakes.com because their server is missing the Sectigo intermediate cert in the chain. This is intentional, not a shortcut.
- **Scheduling intervals**: Daytime (6AM-10PM) every 20s, nighttime (10PM-6AM) every 30s, daily statistics recalculation at 3 AM.
- **Scraping ethics**: The current 20-30s intervals are already aggressive for the Seaway site. Never increase scraping frequency without explicit approval.
