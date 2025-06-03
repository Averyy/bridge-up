# Health Check API - TODO

## Overview
Add a `/health` endpoint to monitor backend status and individual region health. Separated from main improvements to avoid introducing bugs into production scraping.

## Why Add This
- Monitor if your backend is alive
- See which specific regions are working/failing
- Required for uptime monitoring services (UptimeRobot, Pingdom, etc.)
- Helps diagnose issues without checking logs

## Implementation Plan

### 1. Basic Health Check (Start Here)
Simple endpoint that just confirms the backend is running:

```python
# app.py
@app.route('/health')
def health_check():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    })
```

### 2. Add Region Status Tracking (Phase 2)
Track success/failure of each region WITHOUT affecting scraping:

```python
# app.py
from datetime import datetime
import threading

# Global state for health tracking
region_status = {}  # region -> {'status': 'ok'/'failing', 'last_success': timestamp, 'failure_count': n}
region_status_lock = threading.Lock()
last_scrape_time = None
last_scrape_time_lock = threading.Lock()

@app.route('/health')
def health_check():
    # Create snapshot to minimize lock time
    with region_status_lock:
        status_snapshot = dict(region_status)
    
    with last_scrape_time_lock:
        scrape_time_snapshot = last_scrape_time
    
    if not status_snapshot:
        return jsonify({
            "status": "starting",
            "message": "No data yet - backend is starting up"
        })
    
    # Calculate health outside of locks
    healthy_regions = sum(1 for r in status_snapshot.values() if r['status'] == 'ok')
    total_regions = len(status_snapshot)
    
    if healthy_regions == total_regions:
        overall_status = "healthy"
    elif healthy_regions == 0:
        overall_status = "down"
    else:
        overall_status = "degraded"
    
    return jsonify({
        "status": overall_status,
        "healthy_regions": f"{healthy_regions}/{total_regions}",
        "last_scrape": scrape_time_snapshot.isoformat() if scrape_time_snapshot else None,
        "regions": status_snapshot
    })
```

### 3. Integration with Scraper (Phase 3)
Add lightweight status updates to scraper.py:

```python
# scraper.py
def update_region_status(region, success, failure_count=0):
    """Update health check status for a region"""
    from app import region_status, region_status_lock
    
    with region_status_lock:
        if region not in region_status:
            region_status[region] = {
                'status': 'unknown',
                'last_success': None,
                'failure_count': 0
            }
        
        if success:
            region_status[region] = {
                'status': 'ok',
                'last_success': datetime.now(TIMEZONE),
                'failure_count': 0
            }
        else:
            region_status[region]['status'] = 'failing'
            region_status[region]['failure_count'] = failure_count

# Integration points from TODO_IMPROVEMENTS.md:
# 1. In process_single_region() when checking backoff:
#    update_region_status(region, False, failure_count)
#
# 2. After successful scrape:
#    update_region_status(region, True)
#
# 3. In handle_region_failure():
#    update_region_status(region, False, failure_count)
```

## Thread Safety Considerations

Since scraper uses `ThreadPoolExecutor(max_workers=4)`, ALL shared state must be protected:
- Use `threading.Lock()` for all access to `region_status`
- Keep critical sections small
- Use snapshot pattern for reads

## Testing Strategy

1. **Start with basic endpoint**
   - Deploy just the simple /health
   - Verify no impact on scraping

2. **Test region tracking separately**
   - Add status tracking in dev environment
   - Monitor for any performance impact
   - Check thread safety with concurrent requests

3. **Gradual rollout**
   - Phase 1: Basic health endpoint
   - Phase 2: Add region tracking (monitor for 24h)
   - Phase 3: Full integration

## Example Responses

### Healthy System:
```json
{
  "status": "healthy",
  "healthy_regions": "4/4",
  "last_scrape": "2025-06-03T10:30:15.123456",
  "regions": {
    "St. Catharines": {
      "status": "ok",
      "last_success": "2025-06-03T10:30:15.123456",
      "failure_count": 0
    },
    // ... other regions
  }
}
```

### Degraded System:
```json
{
  "status": "degraded",
  "healthy_regions": "3/4",
  "last_scrape": "2025-06-03T10:30:15.123456",
  "regions": {
    "Port Colborne": {
      "status": "failing",
      "last_success": "2025-06-03T09:45:00.123456",
      "failure_count": 5
    },
    // ... other regions
  }
}
```

## Monitoring Integration

Once deployed, can be used with:
- UptimeRobot: Check for `status: healthy`
- Grafana: Parse JSON for metrics
- Custom alerts: Notify when regions fail

## Success Criteria

- [ ] No impact on scraping performance
- [ ] Thread-safe implementation
- [ ] Clear status for each region
- [ ] Easy to integrate with monitoring tools
- [ ] Helps diagnose issues faster

## Notes

- Keep this SEPARATE from main scraping logic initially
- Test thoroughly before full integration
- Consider read-only implementation first (no writes from scraper)
- Can always fall back to basic version if issues arise