# Testing Philosophy: Guardrails, Not Roadblocks

## Core Principle

We test what could fail silently and impact users. We don't test infrastructure or obvious failures.

**Key Rule**: Always run `python run_tests.py` before deploying or committing changes.

## What We Test ✅

**Core Business Logic**:
- HTML parsing functions (both old/new formats)
- Status interpretation logic  
- Statistics calculations (predictions)
- Configuration validation

**Why These**:
1. Would fail silently (wrong data vs crashes)
2. Hard to debug when broken
3. Directly impacts iOS app users
4. Complex edge cases exist

## What We DON'T Test ❌

- Infrastructure (APScheduler, Firebase, HTTP)
- Third-party libraries
- Simple getters/setters
- End-to-end flows

## Test Stats

- **33 tests** covering core logic + edge cases
- **<1 second** execution time
- **4 test files** organized by domain

## Running Tests

```bash
# MANDATORY before deployment
python run_tests.py
```