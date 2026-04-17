# Bridge Up API Reference

## Endpoints

| Endpoint | Rate Limit | Cache | Description |
|----------|------------|-------|-------------|
| `WS /ws` | - | - | WebSocket with channel subscriptions (see below) |
| `GET /` | 30/min | 60s | API root with endpoint discovery |
| `GET /bridges` | 60/min | 10s | All bridges (HTTP fallback) |
| `GET /bridges/{id}` | 60/min | 10s | Single bridge by ID |
| `GET /boats` | 60/min | 10s | All vessels (HTTP fallback) |
| `GET /health` | 30/min | 5s | Health check with status info |
| `GET /docs` | 30/min | 60s | Custom Swagger UI with dark theme |
| `GET /openapi.json` | 30/min | 60s | OpenAPI schema |

## Rate Limiting

- **Library**: slowapi (in-memory storage)
- **Limits**: 60/min for data endpoints, 30/min for static endpoints
- **Response**: 429 status with `Retry-After: 60` header
- **IP Detection**: Takes rightmost X-Forwarded-For (Caddy appends real IP)

## Response Caching

All responses include `Cache-Control: public, max-age=X` headers for browser/CDN caching.

| Type | Cache Duration |
|------|---------------|
| Data endpoints (`/bridges`, `/boats`) | 10s (data updates every ~20s anyway) |
| Static endpoints (`/`, `/docs`, `/openapi.json`) | 60s |
| Health (`/health`) | 5s |
| WebSocket | Unaffected (real-time push) |

## WebSocket Protocol (`/ws`)

Clients must subscribe to channels after connecting. See [ws-client-guide.md](../ws-client-guide.md) for full docs.

### Channels

| Channel | Description |
|---------|-------------|
| `bridges` | All 15 bridges |
| `bridges:{region}` | Region-specific: `sct`, `pc`, `mss`, `k`, `sbs` |
| `boats` | All vessels |
| `boats:{region}` | Region-specific: `welland`, `montreal` |

### Push Behavior

- **Bridges**: Pushed when status changes (few times/day per bridge)
- **Boats**: Pushed when vessel data changes (~30-60s), excludes volatile fields (`last_seen`, `source`)

### Subscribe Example

```json
{"action": "subscribe", "channels": ["bridges", "boats:welland"]}
```

## Health Endpoint (`/health`)

Returns monitoring info with two separate health checks:

### Seaway Status

Can we reach the Seaway API?

- `seaway_status`: "ok" or "error"
- `seaway_message`: Details (e.g., "No successful fetch in 6 minutes")

### Bridge Activity

Are bridges changing?

- `bridge_activity`: "ok" or "warning"
- `bridge_activity_message`: Details (e.g., "Last bridge status change 2 hours ago")

### Seasonal Thresholds

Bridge activity warning thresholds:

- Summer (Mar 16 - Nov 30): 24 hours
- Winter (Dec 1 - Mar 15): 168 hours (1 week)

### Combined Status

For backwards compatibility:

- `status`: "ok", "warning", or "error"
- `status_message`: Human-readable explanation

### Other Fields

- `last_updated`: Last time bridge data changed
- `last_scrape`: Last **successful** scrape timestamp (not attempts)
- `last_scrape_had_changes`: Whether last scrape found changes
- `statistics_last_updated`: Last time statistics were calculated (daily at 3 AM or manual)
- `bridges_count`: Number of bridges in data
- `websocket_clients`: Connected WebSocket clients

## API Documentation (`/docs`)

Custom-styled Swagger UI with Bridge Up dark theme:

- CSS in `static/swagger-custom.css`
- Injected after default Swagger CSS via `main.py` custom endpoint
- Contact URL links to https://bridgeup.app
- Response models with examples for all endpoints

## JSON Schema

**DO NOT MODIFY WITHOUT iOS COORDINATION**

```json
{
  "last_updated": "2025-12-24T15:30:00-05:00",
  "available_bridges": [
    {"id": "SCT_CarltonSt", "name": "Carlton St.", "region_short": "SCT", "region": "St Catharines"}
  ],
  "bridges": {
    "SCT_CarltonSt": {
      "static": {
        "name": "Carlton St.",
        "region": "St Catharines",
        "region_short": "SCT",
        "coordinates": {"lat": 43.19, "lng": -79.20},
        "statistics": {
          "average_closure_duration": 12,
          "closure_ci": {"lower": 8, "upper": 16},
          "average_raising_soon": 3,
          "raising_soon_ci": {"lower": 2, "upper": 5},
          "closure_durations": {"under_9m": 45, "10_15m": 30, "16_30m": 15, "31_60m": 8, "over_60m": 2},
          "total_entries": 287
        }
      },
      "live": {
        "status": "Closed",
        "last_updated": "2025-12-20T15:20:00-05:00",
        "predicted": {"lower": "2025-12-20T15:28:00-05:00", "upper": "2025-12-20T15:36:00-05:00"},
        "upcoming_closures": ["..."],
        "responsible_vessel_mmsi": 316001635
      }
    }
  }
}
```

### Statistics Null Handling

Statistics fields return `null` only when no data exists for that type:

| Field | With Data | No Data |
|-------|-----------|---------|
| `average_closure_duration` | `12` | `null` |
| `closure_ci` | `{"lower": 8, "upper": 16}` | `null` |
| `average_raising_soon` | `3` | `null` |
| `raising_soon_ci` | `{"lower": 2, "upper": 5}` | `null` |

**Note**: CI requires 2+ entries to calculate. With fewer entries, CI is `null`. More entries = narrower CI range.

**Predictions still work**: Backend uses internal defaults (15-20 min) for prediction calculations when stats are `null`.
