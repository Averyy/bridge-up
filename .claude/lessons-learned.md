# Lessons Learned / Known Issues

## DO NOT FLAG - Intentional Design Decisions

### SSL Verification Disabled for greatlakes-seaway.com
**Files**: `scraper.py`, `maintenance_scraper.py`
**Pattern**: `verify=False` in requests calls

This is **intentional and required**. The greatlakes-seaway.com server has a broken SSL certificate chain (missing Sectigo intermediate certificate). We cannot fix their server.

**DO NOT SUGGEST**:
- Enabling SSL verification
- Adding certificate bundles
- Suppressing urllib3 warnings (we accept the warnings as a reminder)

This is documented in CLAUDE.md under "Error Handling Standards".
