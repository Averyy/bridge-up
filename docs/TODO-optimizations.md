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

Note: at current vessel counts (~20 vessels per payload), `json.dumps` is ~0.1–0.5ms each, so the real saving for 100 clients is closer to 10–50ms, not 200ms. Still worth doing at scale.

### Why Deferred

At current scale (<50 users), the inefficiency is unnoticeable.

### Do The Same For Bridge Broadcasts

The same per-client re-serialization pattern exists in `broadcast()` (`main.py:1115`), with 6 region variants (`sct`, `pc`, `mss`, `k`, `sbs`, plus all-bridges). If/when you tackle the boat version, do bridges in the same PR — same fix shape.

---

## 2. Parallelize WebSocket Sends

**Status:** Not started
**Priority:** Low
**Trigger:** Same as #1 — scale pain, or a single slow client blocking broadcasts

### Problem

Both `broadcast()` (bridges) and `broadcast_boats_if_changed()` send to clients serially:

```python
for client in subscribers:
    await client.websocket.send_text(message)
```

Each `await` blocks the loop until that client's TCP write completes. One slow/high-latency client stalls every other client behind it.

### Solution

Fan out with `asyncio.gather`:

```python
results = await asyncio.gather(
    *(client.websocket.send_text(message) for client in subscribers),
    return_exceptions=True,
)
# Remove clients whose send raised
for client, result in zip(subscribers, results):
    if isinstance(result, Exception):
        disconnected.append(client)
```

### Impact

- At 100 clients on mixed-latency connections, broadcast wall time drops from ~sum(RTTs) to ~max(RTT).
- Bigger win than #1 in practice, since the GIL doesn't block async I/O waits but does block serialization.
- Independent of #1 — can be done first, or combined.

### Why Deferred

At current scale, clients are local-ish and fast. Broadcasts complete well inside the 20s scrape cycle.

---

## 3. Remove Redundant Disk Read in `send_bridges_to_client`

**Status:** Not started
**Priority:** Low
**Trigger:** Startup/deploy bursts where many clients reconnect at once

### Problem

`send_bridges_to_client()` (`main.py:974-979`) reads `data/bridges.json` from disk every time a client subscribes:

```python
with bridges_file_lock:
    with open("data/bridges.json") as f:
        data = json.load(f)
```

This data is already in memory as `last_known_state` — the `/bridges` HTTP endpoint (`main.py:1290-1291`) uses it directly. After a deploy, N reconnecting clients each trigger a full JSON parse of the on-disk file.

### Solution

Use the in-memory snapshot like the HTTP endpoint does:

```python
with last_known_state_lock:
    bridges = copy.deepcopy(last_known_state)
data = {
    "last_updated": shared.last_updated_time.isoformat() if shared.last_updated_time else None,
    "available_bridges": AVAILABLE_BRIDGES,
    "bridges": bridges,
}
```

### Impact

- Eliminates 1 disk read + JSON parse per subscription event.
- Only meaningful during reconnect storms (post-deploy, network blip). Negligible under steady state.
- ~5 lines changed.

### Why Deferred

Subscription rate is low enough today that the extra I/O is invisible.

---

## 4. Avoid Full Deepcopy for Responsible-Vessel Injection

**Status:** Not started
**Priority:** Low
**Trigger:** Bridge payload size or broadcast frequency grows materially

### Problem

Both `broadcast()` (`main.py:1052`) and `GET /bridges` (`main.py:1291`) do a full `copy.deepcopy()` of the entire bridge state just so they can write `responsible_vessel_mmsi` into each bridge's `live` dict without mutating shared state.

The scraper also does redundant deepcopies per bridge per scrape cycle (`scraper.py:741, 744, 775, 782`) — ~45 deepcopies every 20–30s at 15 bridges.

### Solution

Build a fresh response dict instead of deep-copying and mutating. Only the `live` sub-dict needs a shallow copy since that's where the new field is written:

```python
bridges_out = {}
for bid, bdata in last_known_state.items():
    live = {**bdata["live"], "responsible_vessel_mmsi": find_responsible_vessel(...)}
    bridges_out[bid] = {"static": bdata["static"], "live": live}
```

`static` is treated read-only downstream, so sharing the reference is safe. Avoids copying stats/coordinates/closure_durations on every broadcast.

### Impact

- Today: ~2KB × 15 bridges per broadcast/request, fully recursive copy. Probably <5ms, but happens on every broadcast cycle.
- Scales worse than it looks — stats payloads will grow as history accumulates (closure_durations, CIs, etc.).
- Also cleans up scraper-side deepcopy churn if applied there.

### Why Deferred

Not currently a latency or CPU problem. Worth doing if the static payload grows (e.g., more stats fields) or if profiling shows GC pressure.

---
