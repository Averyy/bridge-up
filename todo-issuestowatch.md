# Issues to Watch

## V2 API (SBS Region) — Verify When Seaway Reopens (March/April)

### `bridgeLiftList` field names unverified for SBS
- **Risk**: Unknown
- **Issue**: We parse `eta` and `type` fields from lift entries, but have never seen a populated `bridgeLiftList` from SBS — both bridges always return `[]`. Field names are assumed from how other regions work.
- **Action**: During next active vessel closure for SBS, check the API response to confirm field names match

### `bridgeLiftListE` — unknown if it ever differs from `bridgeLiftList`
- **Risk**: Low
- **Issue**: We only parse `bridgeLiftList`, ignoring `bridgeLiftListE` (likely English version). Since `isEnglish: false`, this should be fine. But if lifts ever only appear in `ListE`, we'd miss them.
- **Action**: Compare both lists during an active SBS vessel event

### `eventTypeId` — unknown range of values
- **Risk**: Low
- **Issue**: We see `1` for bridge outage. Unknown if other values (2, 3, etc.) exist with different semantics. Currently all maintenance entries are treated as Construction regardless of type.
- **Action**: Monitor API responses for other eventTypeId values
