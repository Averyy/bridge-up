# Prometheus Metrics - Future Implementation

Overview of metrics endpoint for Bridge Up backend monitoring.

---

## Proposed Endpoint

`GET /metrics` - Prometheus-compatible metrics in text exposition format

---

## Metrics to Expose

### Scraper Health

| Metric | Type | Description |
|--------|------|-------------|
| `bridgeup_scrape_total` | Counter | Total scrape attempts |
| `bridgeup_scrape_success_total` | Counter | Successful scrapes |
| `bridgeup_scrape_failure_total` | Counter | Failed scrapes |
| `bridgeup_scrape_duration_seconds` | Histogram | Scrape cycle duration |
| `bridgeup_last_scrape_timestamp` | Gauge | Unix timestamp of last scrape |
| `bridgeup_last_update_timestamp` | Gauge | Unix timestamp of last data change |

### Per-Region Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `bridgeup_region_scrape_success` | Gauge | `region` | 1 if last scrape succeeded, 0 if failed |
| `bridgeup_region_failure_count` | Gauge | `region` | Consecutive failure count |
| `bridgeup_region_backoff_seconds` | Gauge | `region` | Current backoff wait time |

### Bridge Status

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `bridgeup_bridge_status` | Gauge | `bridge_id`, `status` | 1 for current status, 0 otherwise |
| `bridgeup_bridge_last_change_timestamp` | Gauge | `bridge_id` | When status last changed |

### WebSocket

| Metric | Type | Description |
|--------|------|-------------|
| `bridgeup_websocket_clients` | Gauge | Connected WebSocket clients |
| `bridgeup_websocket_broadcasts_total` | Counter | Total broadcasts sent |

### Boat Tracking

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `bridgeup_vessels_tracked` | Gauge | `region` | Vessels currently tracked |
| `bridgeup_udp_messages_total` | Counter | `station` | UDP messages received |
| `bridgeup_udp_station_active` | Gauge | `station` | 1 if received data in last 30s |
| `bridgeup_aishub_polls_total` | Counter | | AISHub API poll attempts |
| `bridgeup_aishub_failure_count` | Gauge | | Consecutive AISHub failures |

### Statistics

| Metric | Type | Description |
|--------|------|-------------|
| `bridgeup_statistics_last_update_timestamp` | Gauge | Last daily stats calculation |

---

## Implementation Approach

### Option A: prometheus-fastapi-instrumentator (Recommended)

Auto-instruments FastAPI with request metrics + custom metrics.

```python
# main.py
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Gauge, Histogram

# Custom metrics
SCRAPE_DURATION = Histogram('bridgeup_scrape_duration_seconds', 'Scrape cycle duration')
SCRAPE_TOTAL = Counter('bridgeup_scrape_total', 'Total scrape attempts')
WEBSOCKET_CLIENTS = Gauge('bridgeup_websocket_clients', 'Connected clients')

# Auto-instrument app
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
```

**Pros**: Auto HTTP metrics, battle-tested, minimal code
**Cons**: Additional dependency

### Option B: prometheus-client only (Lightweight)

Manual metrics without auto-instrumentation.

```python
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

**Pros**: Minimal dependency, full control
**Cons**: No auto HTTP metrics, more manual work

---

## Example Output

```
# HELP bridgeup_scrape_duration_seconds Scrape cycle duration
# TYPE bridgeup_scrape_duration_seconds histogram
bridgeup_scrape_duration_seconds_bucket{le="0.5"} 892
bridgeup_scrape_duration_seconds_bucket{le="1.0"} 1203
bridgeup_scrape_duration_seconds_sum 847.23
bridgeup_scrape_duration_seconds_count 1205

# HELP bridgeup_websocket_clients Connected WebSocket clients
# TYPE bridgeup_websocket_clients gauge
bridgeup_websocket_clients 3

# HELP bridgeup_region_scrape_success Last scrape success by region
# TYPE bridgeup_region_scrape_success gauge
bridgeup_region_scrape_success{region="SCT"} 1
bridgeup_region_scrape_success{region="PC"} 1
bridgeup_region_scrape_success{region="MSS"} 0
bridgeup_region_scrape_success{region="K"} 1
bridgeup_region_scrape_success{region="SBS"} 1

# HELP bridgeup_vessels_tracked Vessels currently tracked
# TYPE bridgeup_vessels_tracked gauge
bridgeup_vessels_tracked{region="welland"} 4
bridgeup_vessels_tracked{region="montreal"} 2
```

---

## Deployment Integration

### Docker Compose

```yaml
services:
  bridge-up:
    # ... existing config
    labels:
      - "prometheus.scrape=true"
      - "prometheus.port=8000"
      - "prometheus.path=/metrics"
```

### Prometheus Config

```yaml
scrape_configs:
  - job_name: 'bridge-up'
    static_configs:
      - targets: ['api.bridgeup.app:8000']
    metrics_path: /metrics
    scrape_interval: 30s
```

---

## Alerting Rules (Example)

```yaml
groups:
  - name: bridge-up
    rules:
      - alert: ScraperStalled
        expr: time() - bridgeup_last_scrape_timestamp > 300
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Bridge Up scraper has not run in 5+ minutes"

      - alert: RegionDown
        expr: bridgeup_region_failure_count > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Region {{ $labels.region }} failing repeatedly"

      - alert: NoWebSocketClients
        expr: bridgeup_websocket_clients == 0
        for: 30m
        labels:
          severity: info
        annotations:
          summary: "No WebSocket clients connected for 30 minutes"
```

---

## Dependencies to Add

```
# requirements.txt
prometheus-client
prometheus-fastapi-instrumentator  # if using Option A
```

---

## Implementation Priority

1. Basic `/metrics` endpoint with core gauges
2. Scraper metrics (duration, success/failure)
3. Per-region health metrics
4. Boat tracking metrics
5. Alerting rules

Estimated effort: 1-2 hours for basic implementation, +1 hour for comprehensive metrics.
