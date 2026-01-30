# Pending Optimizations

Low-priority improvements that aren't blocking but could help at scale.

---

## 1. Pre-serialize Boat Broadcasts

**Status:** Not started
**Priority:** Low
**Trigger:** If 200+ concurrent WebSocket clients or noticeable lag during boat broadcasts

### Problem

Currently, `broadcast_boats_if_changed()` calls `json.dumps()` separately for each subscriber:

```python
for client in subscribers:
    payload = {...}
    message = json.dumps(payload)  # Called 100 times for 100 clients
    await client.websocket.send_text(message)
```

With 100 clients, that's 100 JSON serializations (~200ms) every 30-60 seconds.

### Solution

Pre-serialize the 3 possible payloads once, then send the cached string:

```python
# Serialize once per region
serialized = {
    "all": json.dumps({...all vessels...}),
    "welland": json.dumps({...welland only...}),
    "montreal": json.dumps({...montreal only...}),
}

# Send pre-serialized string
for client in subscribers:
    regions = client.boat_regions()
    if regions is None:
        message = serialized["all"]
    elif regions == {"welland"}:
        message = serialized["welland"]
    elif regions == {"montreal"}:
        message = serialized["montreal"]
    else:
        # Multi-region edge case - build on demand
        message = json.dumps(...)
    await client.websocket.send_text(message)
```

### Impact

- 100 clients: 3 serializations instead of 100 (97% reduction)
- ~15 lines of code change
- Negligible memory overhead

### Why Deferred

At current scale (<50 users), the inefficiency is unnoticeable. Server spends ~200ms every 30-60 seconds on serialization, which is fine.

---
