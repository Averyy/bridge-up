# TODO: Lock Down Bridge Up UDP Port

## Issue

Bridge Up listens on UDP port 10110 for AIS NMEA sentences. Currently exposed to the internet via `docker-compose.yml`, meaning anyone could inject fake vessel data.

## Current Setup

- `docker-compose.yml` exposes port: `"10110:10110/udp"`
- ship-sparr sends NMEA sentences to this port
- On VPS: ship-sparr uses Docker network (`bridge-up:10110`)
- Local dev: sends directly to VPS IP (`184.107.178.158:10110`)
- AISHub uses HTTP polling (unaffected by this change)

## The Fix

Remove the UDP port exposure from `docker-compose.yml`:

```yaml
# Before
ports:
  - "8000:8000"
  - "10110:10110/udp"  # DELETE THIS LINE

# After
ports:
  - "8000:8000"
```

That's it. Internal container communication still works via Docker DNS (`bridge-up:10110`).

## Prerequisites

- ship-sparr must be deployed on the same VPS (on the `web` Docker network)
- Local dev won't be able to send UDP directly to VPS anymore

## Why Not Firewall?

ufw rules can get out of sync with Docker (Docker bypasses ufw by default). Would require extra config (`DOCKER_IPTABLES=false` or manual iptables rules). More moving parts to debug. Not worth it when Docker network isolation is simpler.

## Risk Assessment (Current State)

Low but not zero. An attacker would need to:
1. Know the VPS IP
2. Know port 10110
3. Send valid NMEA sentences that parse correctly
4. Send MMSIs in the 200M-799M ship range
5. Send positions within monitored regions (Welland/Montreal)

Still good hygiene to lock it down once ship-sparr is local.

## When to Do This

Once ship-sparr (marinetraffic dispatcher) is deployed on the VPS alongside Bridge Up.
