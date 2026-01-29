"""
Runtime functions for maintenance override system.

Loads and interprets maintenance.json to override bridge statuses
and merge maintenance periods into upcoming closures.
"""
import os
import json
import copy
import threading
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
from loguru import logger

from shared import TIMEZONE
from config import BRIDGE_NAME_MAP, MAINTENANCE_FILE

# Cache for file-change detection (thread-safe)
_maintenance_cache = {
    "mtime": None,
    "data": None
}
_maintenance_cache_lock = threading.Lock()


def load_maintenance_data(_cached: bool = False) -> Dict:
    """
    Load maintenance.json with file-change detection caching.

    Thread-safe: uses lock to protect cache access.

    Args:
        _cached: Internal parameter. If False (default), returns a deep copy safe
                 for modification. If True, returns the cached reference directly.
                 WARNING: When True, callers MUST NOT modify the returned data.
                 The leading underscore indicates this is for internal optimization only.

    Returns:
        Dict with structure {"closures": [...], "last_scrape_success": "...", ...}
        Returns {"closures": []} if file doesn't exist or is invalid
    """
    with _maintenance_cache_lock:
        # Check if file exists
        if not os.path.exists(MAINTENANCE_FILE):
            # Clear cache when file doesn't exist to prevent stale data
            _maintenance_cache["mtime"] = None
            _maintenance_cache["data"] = None
            return {"closures": []}

        # Get file modification time
        try:
            mtime = os.path.getmtime(MAINTENANCE_FILE)
        except OSError as e:
            logger.error(f"Failed to get mtime for {MAINTENANCE_FILE}: {e}")
            return {"closures": []}

        # Return cached data if file hasn't changed
        if _maintenance_cache["mtime"] == mtime and _maintenance_cache["data"] is not None:
            if _cached:
                return _maintenance_cache["data"]
            return copy.deepcopy(_maintenance_cache["data"])

        # Load and parse file
        try:
            with open(MAINTENANCE_FILE, 'r') as f:
                data = json.load(f)

            # Ensure closures key exists
            if "closures" not in data:
                data["closures"] = []

            # Update cache (store original, return copy to prevent mutation)
            _maintenance_cache["mtime"] = mtime
            _maintenance_cache["data"] = data

            if _cached:
                return data
            return copy.deepcopy(data)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {MAINTENANCE_FILE}: {e}")
            _maintenance_cache["mtime"] = None
            _maintenance_cache["data"] = None
            return {"closures": []}
        except OSError as e:
            logger.error(f"Failed to load {MAINTENANCE_FILE}: {e}")
            _maintenance_cache["mtime"] = None
            _maintenance_cache["data"] = None
            return {"closures": []}


def expand_daily_periods(period: Dict, timezone, min_date: Optional[datetime] = None) -> List[Dict]:
    """
    Expand a daily closure pattern into individual day periods.

    Args:
        period: Dict with type="daily", start_date, end_date, daily_start_time, daily_end_time
        timezone: pytz timezone object
        min_date: Optional minimum date to include (skip periods ending before this)

    Returns:
        List of period dicts with start/end datetimes
    """
    try:
        start_date = datetime.fromisoformat(period["start_date"]).date()
        end_date = datetime.fromisoformat(period["end_date"]).date()
        start_time_str = period["daily_start_time"]
        end_time_str = period["daily_end_time"]

        # Validate date range
        if end_date < start_date:
            logger.warning(f"Invalid period: end_date {end_date} before start_date {start_date}")
            return []

        # Limit to 365 days to prevent runaway expansion from data errors
        max_days = 365
        days_span = (end_date - start_date).days
        if days_span > max_days:
            logger.warning(f"Period spans {days_span} days, truncating to {max_days}")
            end_date = start_date + timedelta(days=max_days)

        # Parse times
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        # Check if closure spans midnight (e.g., 21:00 to 02:00)
        spans_midnight = end_time < start_time

        # Generate one period per day
        expanded = []
        current_date = start_date
        while current_date <= end_date:
            # is_dst=False prevents AmbiguousTimeError/NonExistentTimeError during DST transitions
            start_dt = timezone.localize(datetime.combine(current_date, start_time), is_dst=False)
            end_dt = timezone.localize(datetime.combine(current_date, end_time), is_dst=False)

            # If closure spans midnight (e.g., 21:00-02:00), end is on the next calendar day.
            # Note: On the last day of the range, this intentionally extends to end_date+1.
            # For example, a closure ending March 19 at 02:00 actually ends March 20 at 02:00.
            if spans_midnight:
                end_dt = timezone.localize(datetime.combine(current_date + timedelta(days=1), end_time), is_dst=False)

            # Skip past periods if min_date is specified
            if min_date is None or end_dt > min_date:
                expanded.append({
                    "start": start_dt,
                    "end": end_dt
                })
            current_date += timedelta(days=1)

        return expanded
    except (ValueError, KeyError) as e:
        logger.warning(f"Failed to expand daily period: {e}")
        return []


def get_maintenance_for_bridge(
    bridge_id: str,
    now: datetime,
    _preloaded_data: Optional[Dict] = None
) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Get maintenance info for a bridge in a single pass (optimized).

    Returns both active maintenance and all future periods, avoiding duplicate
    expansion of daily periods.

    Args:
        bridge_id: Bridge ID (e.g., "PC_ClarenceSt")
        now: Current datetime (timezone-aware)
        _preloaded_data: Optional pre-loaded maintenance data to avoid repeated
                         file reads in batch operations. Internal use only.

    Returns:
        Tuple of (active_maintenance, all_future_periods) where:
        - active_maintenance: Dict with {"start", "end", "description"} if currently in window, else None
        - all_future_periods: List of {"start", "end", "description"}, sorted by start time
    """
    # Use pre-loaded data if provided, otherwise load with caching
    if _preloaded_data is not None:
        data = _preloaded_data
    else:
        data = load_maintenance_data(_cached=True)
    active = None
    all_periods = []

    for closure in data.get("closures", []):
        if closure.get("bridge_id") != bridge_id:
            continue

        description = closure.get("description", "Scheduled maintenance")

        for period in closure.get("periods", []):
            if period.get("type") == "daily":
                # Expand daily pattern ONCE for both checks, skip past dates for performance
                expanded = expand_daily_periods(period, TIMEZONE, min_date=now)
                for exp_period in expanded:
                    # Check if currently active (for override)
                    if active is None and exp_period["start"] <= now <= exp_period["end"]:
                        active = {
                            "start": exp_period["start"],
                            "end": exp_period["end"],
                            "description": description
                        }
                    # Collect future/current periods (for upcoming_closures)
                    if exp_period["end"] > now:
                        all_periods.append({
                            "start": exp_period["start"],
                            "end": exp_period["end"],
                            "description": description
                        })
            else:
                # Standard full closure
                try:
                    start = datetime.fromisoformat(period["start"])
                    end = datetime.fromisoformat(period["end"])

                    # Check if currently active
                    if active is None and start <= now <= end:
                        active = {
                            "start": start,
                            "end": end,
                            "description": description
                        }
                    # Collect future/current periods
                    if end > now:
                        all_periods.append({
                            "start": start,
                            "end": end,
                            "description": description
                        })
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse period dates: {e}")

    # Sort by start time
    all_periods.sort(key=lambda p: p["start"])
    return active, all_periods


def get_active_maintenance(bridge_id: str, now: datetime) -> Optional[Dict]:
    """
    Check if bridge is currently in a maintenance window.

    Args:
        bridge_id: Bridge ID (e.g., "PC_ClarenceSt")
        now: Current datetime (timezone-aware)

    Returns:
        Dict with {"start": dt, "end": dt, "description": str} if active, else None
    """
    active, _ = get_maintenance_for_bridge(bridge_id, now)
    return active


def get_all_maintenance_periods(bridge_id: str, now: datetime) -> List[Dict]:
    """
    Get ALL future/current maintenance periods for a bridge.

    Args:
        bridge_id: Bridge ID (e.g., "PC_ClarenceSt")
        now: Current datetime (timezone-aware)

    Returns:
        List of {"start": dt, "end": dt, "description": str}, sorted by start time
        Only includes periods where end > now
    """
    _, all_periods = get_maintenance_for_bridge(bridge_id, now)
    return all_periods




def get_maintenance_info() -> Dict:
    """
    Get maintenance system status for health endpoint.

    Returns:
        Dict with last_scrape_success, closure_count, source_url, file_exists
    """
    if not os.path.exists(MAINTENANCE_FILE):
        return {
            "file_exists": False,
            "closure_count": 0
        }

    # Use _cached=True since we only read the data (avoids deepcopy overhead)
    data = load_maintenance_data(_cached=True)
    closures = data.get("closures", [])

    info = {
        "file_exists": True,
        "closure_count": len(closures),
        "source_url": data.get("source_url")
    }

    # Include last scrape timestamp if available
    if "last_scrape_success" in data:
        info["last_scrape_success"] = data["last_scrape_success"]
    elif "last_scrape_attempt" in data:
        info["last_scrape_attempt"] = data["last_scrape_attempt"]
        if "last_scrape_error" in data:
            # Use generic error categories instead of exposing raw messages
            raw_error = str(data["last_scrape_error"]).lower()
            if "timeout" in raw_error or "timed out" in raw_error:
                info["last_scrape_error"] = "Connection timeout"
            elif "connection" in raw_error or "network" in raw_error:
                info["last_scrape_error"] = "Connection error"
            elif "parse" in raw_error or "html" in raw_error:
                info["last_scrape_error"] = "Parse error"
            elif "fetch" in raw_error:
                info["last_scrape_error"] = "Fetch failed"
            else:
                info["last_scrape_error"] = "Scrape failed"

    return info


def validate_maintenance_file() -> List[str]:
    """
    Validate maintenance.json structure and return errors/warnings.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check file exists
    if not os.path.exists(MAINTENANCE_FILE):
        return [f"File not found: {MAINTENANCE_FILE}"]

    # Load data
    data = load_maintenance_data()

    # Check structure
    if "closures" not in data:
        errors.append("Missing 'closures' key")
        return errors

    if not isinstance(data["closures"], list):
        errors.append("'closures' must be a list")
        return errors

    # Validate each closure using known bridge IDs from config
    known_bridge_ids = set(BRIDGE_NAME_MAP.values())

    for i, closure in enumerate(data["closures"]):
        if not isinstance(closure, dict):
            errors.append(f"Closure {i}: not a dict")
            continue

        # Check required fields
        if "bridge_id" not in closure:
            errors.append(f"Closure {i}: missing 'bridge_id'")
            continue

        bridge_id = closure["bridge_id"]

        # Validate bridge ID
        if bridge_id not in known_bridge_ids:
            errors.append(f"Closure {i}: unknown bridge_id '{bridge_id}'")

        # Check periods
        if "periods" not in closure:
            errors.append(f"Closure {i} ({bridge_id}): missing 'periods'")
            continue

        if not isinstance(closure["periods"], list):
            errors.append(f"Closure {i} ({bridge_id}): 'periods' must be a list")
            continue

        # Validate periods
        for j, period in enumerate(closure["periods"]):
            if not isinstance(period, dict):
                errors.append(f"Closure {i} ({bridge_id}), period {j}: not a dict")
                continue

            if period.get("type") == "daily":
                # Validate daily period
                required = ["start_date", "end_date", "daily_start_time", "daily_end_time"]
                for field in required:
                    if field not in period:
                        errors.append(f"Closure {i} ({bridge_id}), period {j}: missing '{field}'")
            else:
                # Validate full closure
                required = ["start", "end"]
                for field in required:
                    if field not in period:
                        errors.append(f"Closure {i} ({bridge_id}), period {j}: missing '{field}'")

                # Validate date formats
                for field in required:
                    if field in period:
                        try:
                            datetime.fromisoformat(period[field])
                        except Exception:
                            errors.append(f"Closure {i} ({bridge_id}), period {j}: invalid date format for '{field}'")

    return errors
