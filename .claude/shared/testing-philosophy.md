# Testing Philosophy: Guardrails, Not Roadblocks

## Core Principle

We follow a "Guardrails, Not Roadblocks" approach to testing. This philosophy acknowledges that as a small startup, we need to balance quality with development velocity. Our testing strategy focuses on protecting critical functionality without impeding progress.

## MVP Testing Approach

**Priority**: Ship fast, test what matters most.

### Critical Tests Only

We focus testing efforts on **core business logic** that:
1. **Has complex edge cases** (parsing, data transformation)
2. **Would fail silently** (wrong data vs obvious crashes)
3. **Is hard to debug** (external dependencies, format changes)
4. **Directly impacts users** (bridge status accuracy)

### What We DON'T Test

- **Infrastructure/plumbing**: APScheduler, Firebase, network requests
- **Third-party libraries**: We trust well-maintained dependencies
- **Simple getters/setters**: Low complexity, obvious when broken
- **Integration flows**: Too brittle, changes frequently

### Bridge Up Specific Testing

**Core Business Logic (Test These)**:
- HTML parsing functions (`parse_old_style`, `parse_new_style`)
- Status interpretation logic (`interpret_bridge_status`) 
- Date/time parsing (`parse_date`)

**Infrastructure (Don't Test These)**:
- HTTP requests to bridge websites
- Firebase read/write operations
- APScheduler job execution
- End-to-end scraping flows

### Test Organization

- **Single file**: `test_parsers.py` (keep it simple)
- **Real data**: Use actual HTML samples from live websites
- **Edge cases**: Focus on the tricky scenarios that could break silently
- **Fast execution**: Tests should run in <5 seconds total

### Running Tests

```bash
# Optional - tests are for development confidence only
python3 test_parsers.py
```

**Important**: Tests are purely for development. They have ZERO impact on production deployment or runtime.