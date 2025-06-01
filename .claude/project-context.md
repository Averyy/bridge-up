# Bridge Up Backend - Project Context

## What This Project Does
Bridge Up is a real-time bridge status monitoring system for the St. Lawrence Seaway. This Python backend scrapes bridge status websites, processes the data, calculates predictive statistics, and stores everything in Firebase Firestore for the iOS app to consume.

## Key Technical Decisions

### Scraping Architecture
- **Dual Parser System**: Handles both old (table-based) and new (div-based) website formats
- **Concurrent Execution**: ThreadPoolExecutor scrapes all regions simultaneously (50x speedup)
- **Timeout Protection**: 10-second timeouts + 3 retries prevent infinite hangs
- **Status Normalization**: Complex website statuses → Clean iOS app states

### Data Processing
- **Statistics Calculation**: All predictive math done in Python (not Firebase Functions)
  - Average closure duration, confidence intervals, duration buckets
  - Runs daily at 3AM via APScheduler
  - 300 history entry rolling window
- **Firebase Optimization**: Only writes when status actually changes
- **In-Memory Caching**: `last_known_state` dictionary prevents redundant writes

### Infrastructure
- **APScheduler Configuration**: `max_instances=3`, `coalesce=True` prevents job backlog
- **Docker Deployment**: GitHub Actions → Docker Hub → Auto-deploy on push
- **Production Server**: Waitress WSGI server (not Flask dev server)
- **No Tests Yet**: Following "Guardrails, Not Roadblocks" philosophy

## Common Pitfalls to Avoid
1. **Never remove request timeouts** - This caused the major stalling bug
2. **Don't change Firebase schema** - iOS app depends on exact structure
3. **Maintain concurrent execution** - Sequential would be 50x slower
4. **Keep dual parser system** - Websites use different formats
5. **Don't over-engineer** - This is a startup, ship fast

## Future Improvements
- Implement tests from `TODO-Testing.md` (focus on statistics calculation)
- Add proper logging instead of print statements
- Consider connection pooling for Firebase
- Monitor for website format changes

## Performance Metrics
- **Scraping Speed**: ~0.7 seconds for all 4 regions (13 bridges total)
- **Firebase Writes**: Only on status changes (cost optimization)
- **History Management**: Auto-cleanup keeps max 300 entries per bridge
- **Scheduling**: 30-second intervals during day, 60-second at night

## Critical Files to Understand
1. `scraper.py` - Main orchestration and Firebase integration
2. `stats_calculator.py` - Predictive math (this is the secret sauce!)
3. `config.py` - Bridge URLs and coordinates
4. `start_waitress.py` - Production entry point

## Business Context
- **Users**: Boaters and bridge operators who need real-time status
- **Value Prop**: Not just status, but predictions based on historical patterns
- **Competition**: Other apps just show open/closed, we predict duration
- **iOS App**: Read-only consumer of this backend's data