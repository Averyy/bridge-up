# scraper.py
"""
Bridge data scraper for St. Lawrence Seaway.

Scrapes bridge status from JSON APIs, stores in JSON files, and broadcasts
updates via WebSocket. Migrated from Firebase to self-hosted storage.
"""
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import pytz
import unicodedata
import re
import copy
import random
import string
import os
import sys
import json
import tempfile
import concurrent.futures
import threading

from config import BRIDGE_KEYS, BRIDGE_DETAILS, OLD_JSON_ENDPOINT, NEW_JSON_ENDPOINT
from stats_calculator import calculate_bridge_statistics
from predictions import calculate_prediction, add_expected_duration_to_closures, parse_datetime
from loguru import logger

# Import shared state
import shared
from shared import (
    TIMEZONE,
    last_known_state, last_known_state_lock,
    region_failures, region_failures_lock,
    endpoint_cache, endpoint_cache_lock,
    bridges_file_lock
)

# Configure logger for cleaner output
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    enqueue=False,
    colorize=False  # Disable colors for Docker
)


def atomic_write_json(path: str, data: Any) -> None:
    """
    Atomically write JSON data to file (crash-safe).

    Writes to temp file first, then renames. This prevents corruption
    if the process crashes mid-write.
    """
    dir_path = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, suffix='.tmp') as f:
        json.dump(data, f, default=str, indent=2)
        temp_path = f.name
    os.replace(temp_path, path)  # Atomic on POSIX


def parse_date(date_str: str) -> Tuple[Optional[datetime], bool]:
    """
    Parse date/time strings from bridge data into timezone-aware datetime objects.

    Handles multiple formats:
    - datetime objects (returned as-is with timezone)
    - Time-only strings like "18:15" or "18:15*" (asterisk = longer closure)
    - ISO datetime strings like "2025-12-20T11:51:00" or "2025-12-20T11:51:00Z"
    - Standard datetime strings like "2025-12-20 11:51:00"

    Args:
        date_str: The date/time string to parse

    Returns:
        Tuple of (datetime or None, bool indicating longer closure)
    """
    if isinstance(date_str, datetime):
        return date_str.astimezone(TIMEZONE), False

    # Handle None or empty strings
    if not date_str or date_str == '----':
        return None, False

    # Handle placeholder dates (API returns 0001-01-01 for null dates)
    if '0001-01-01' in str(date_str):
        return None, False

    # Check for ISO datetime format (2025-12-20T11:51:00 or 2025-12-20T11:51:00Z)
    if 'T' in str(date_str):
        try:
            clean_str = str(date_str).replace('Z', '+00:00')
            closure_time = datetime.fromisoformat(clean_str)
            return closure_time.astimezone(TIMEZONE), False
        except ValueError:
            pass

    # Check if the date string contains only time (18:15 or 18:15*)
    time_match = re.match(r'(\d{2}:\d{2})(\*)?', str(date_str))
    if time_match:
        time_str, asterisk = time_match.groups()
        now = datetime.now(TIMEZONE)
        closure_time = TIMEZONE.localize(
            datetime.combine(now.date(), datetime.strptime(time_str, '%H:%M').time())
        )
        longer = bool(asterisk)
        return closure_time, longer

    # Check if the date string is valid datetime (2025-12-20 11:51:00)
    try:
        closure_time = datetime.strptime(str(date_str), '%Y-%m-%d %H:%M:%S')
        closure_time = TIMEZONE.localize(closure_time)
        return closure_time, False
    except ValueError:
        logger.warning(f"Invalid date string: {date_str}")
        return None, False


def fetch_json_endpoint(url: str, timeout: int = 10, retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    Fetch JSON data from endpoint with retry logic.

    Args:
        url: The full URL to fetch
        timeout: Request timeout in seconds
        retries: Number of retry attempts

    Returns:
        Parsed JSON data as dict, or None on failure
    """
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, requests.Timeout, ValueError) as e:
            if attempt == retries - 1:
                logger.warning(f"Fetch failed {url[:50]}...: {str(e)[:50]}...")
                return None
            continue
    return None


def parse_old_json(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse JSON response from old API format.

    This format is used by SCT, PC, MSS, and K regions.
    """
    bridges = []
    bridge_models = json_data.get('bridgeModelList', [])
    bridge_closures = json_data.get('bridgeClosureList', [])

    # Parse live bridge status
    for bridge_model in bridge_models:
        name = bridge_model.get('address', '').strip()
        status = bridge_model.get('status', 'Unknown').strip()

        # Extract vessel ETA if available
        upcoming_closures = []
        vessel_eta = bridge_model.get('vessel1ETA', '').strip()
        if vessel_eta and vessel_eta != '----':
            closure_time, longer = parse_date(vessel_eta)
            if closure_time:
                upcoming_closures.append({
                    'type': 'Next Arrival',
                    'time': closure_time,
                    'longer': longer
                })

        bridges.append({
            'name': name,
            'raw_status': status,
            'upcoming_closures': upcoming_closures
        })

    # Parse planned closures (construction)
    current_time = datetime.now(TIMEZONE)
    for closure in bridge_closures:
        bridge_name = closure.get('bridgeAddress', '').strip()
        closure_period = closure.get('closureP', '')
        is_continuous = closure.get('continuousHour', 'Y') == 'Y'

        if not closure_period:
            continue

        try:
            match = re.match(
                r'([A-Z]{3} \d{1,2}, \d{4}) - ([A-Z]{3} \d{1,2}, \d{4}), (\d{2}:\d{2}) - (\d{2}:\d{2})',
                closure_period
            )
            if not match:
                logger.warning(f"Failed to match closure pattern: {closure_period}")
                continue

            start_date_str, end_date_str, start_time_str, end_time_str = match.groups()
            start_date = datetime.strptime(start_date_str, '%b %d, %Y')
            end_date = datetime.strptime(end_date_str, '%b %d, %Y')
            start_hour, start_min = map(int, start_time_str.split(':'))
            end_hour, end_min = map(int, end_time_str.split(':'))

            if is_continuous:
                start_time = TIMEZONE.localize(start_date.replace(hour=start_hour, minute=start_min))
                end_time = TIMEZONE.localize(end_date.replace(hour=end_hour, minute=end_min))

                if end_time > current_time:
                    planned_closure = {
                        'type': 'Construction',
                        'time': start_time,
                        'end_time': end_time,
                        'longer': False
                    }
                    for bridge in bridges:
                        if bridge['name'] == bridge_name:
                            bridge['upcoming_closures'].append(planned_closure)
                            break
            else:
                current_date = start_date
                while current_date <= end_date:
                    day_start = TIMEZONE.localize(current_date.replace(hour=start_hour, minute=start_min))
                    day_end = TIMEZONE.localize(current_date.replace(hour=end_hour, minute=end_min))

                    if day_end > current_time:
                        planned_closure = {
                            'type': 'Construction',
                            'time': day_start,
                            'end_time': day_end,
                            'longer': False
                        }
                        for bridge in bridges:
                            if bridge['name'] == bridge_name:
                                bridge['upcoming_closures'].append(planned_closure)
                                break
                    current_date += timedelta(days=1)

        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse closure: {closure_period} - {e}")
            continue

    return bridges


def parse_new_json(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse JSON response from new API format.

    This format is used by SBS region.
    """
    bridges = []
    bridge_statuses = json_data.get('bridgeStatusList', [])
    current_time = datetime.now(TIMEZONE)

    for bridge_status in bridge_statuses:
        name = bridge_status.get('address', '').strip()
        status = bridge_status.get('status3', '').strip()
        if not status:
            status = bridge_status.get('status', 'Unknown').strip()

        upcoming_closures = []

        # Parse bridge lifts (vessel arrivals)
        bridge_lifts = bridge_status.get('bridgeLiftList', [])
        for lift in bridge_lifts:
            eta_str = lift.get('eta', '').strip()
            if eta_str:
                closure_time, _ = parse_date(eta_str)
                if closure_time and closure_time > current_time:
                    lift_type = lift.get('type', 'a')
                    upcoming_closures.append({
                        'type': 'Next Arrival' if lift_type == 'a' else 'Commercial Vessel',
                        'time': closure_time,
                        'longer': False
                    })

        # Parse maintenance closures
        maintenance_list = bridge_status.get('bridgeMaintenanceList', [])
        for maintenance in maintenance_list:
            close_date_str = maintenance.get('closeDateFr', '')
            close_date_to = maintenance.get('closeDateTo', '')

            if not close_date_str:
                continue

            try:
                start_time, _ = parse_date(close_date_str)
                end_time = None
                if close_date_to:
                    end_time, _ = parse_date(close_date_to)

                if start_time and (not end_time or end_time > current_time):
                    upcoming_closures.append({
                        'type': 'Construction',
                        'time': start_time,
                        'end_time': end_time,
                        'longer': False
                    })
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse maintenance date: {close_date_str}")
                continue

        bridges.append({
            'name': name,
            'raw_status': status,
            'upcoming_closures': upcoming_closures
        })

    return bridges


def scrape_bridge_data(bridge_key: str, timeout: int = 10, retries: int = 3) -> List[Dict[str, Any]]:
    """
    Fetch bridge data from JSON API with smart endpoint caching.
    """
    with endpoint_cache_lock:
        cached = endpoint_cache.get(bridge_key, 'old')

    if cached == 'new':
        endpoints = [
            ('new', NEW_JSON_ENDPOINT, parse_new_json, 'bridgeStatusList'),
            ('old', OLD_JSON_ENDPOINT, parse_old_json, 'bridgeModelList')
        ]
    else:
        endpoints = [
            ('old', OLD_JSON_ENDPOINT, parse_old_json, 'bridgeModelList'),
            ('new', NEW_JSON_ENDPOINT, parse_new_json, 'bridgeStatusList')
        ]

    for endpoint_type, base_url, parser, data_key in endpoints:
        url = base_url + bridge_key
        data = fetch_json_endpoint(url, timeout, retries)

        if data and data.get(data_key):
            with endpoint_cache_lock:
                if endpoint_cache.get(bridge_key) != endpoint_type:
                    logger.info(f"{bridge_key}: Discovered {endpoint_type} endpoint works")
                    endpoint_cache[bridge_key] = endpoint_type
            return parser(data)

        if data and endpoint_type == 'old' and data.get('bridgeStatusList'):
            with endpoint_cache_lock:
                endpoint_cache[bridge_key] = 'new'
            logger.info(f"{bridge_key}: Old endpoint returned new format, caching")
            return parse_new_json(data)

    logger.error(f"✗ {bridge_key}: No data from either endpoint")
    return []


def interpret_bridge_status(bridge_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interpret raw bridge status into normalized status values.
    """
    name = bridge_data['name']
    raw_status = bridge_data['raw_status'].lower()
    upcoming_closures = bridge_data.get('upcoming_closures', [])

    if "data unavailable" in raw_status:
        return {
            "name": name,
            "available": False,
            "status": "Unknown",
            "raw_status": bridge_data['raw_status'],
            "upcoming_closures": upcoming_closures
        }

    available = "available" in raw_status and "unavailable" not in raw_status
    status = "Unknown"

    if available:
        if "raising soon" in raw_status:
            status = "Closing soon"
        else:
            status = "Open"
    elif "unavailable" in raw_status:
        if "lowering" in raw_status:
            status = "Opening"
        elif "raising" in raw_status:
            status = "Closing"
        elif "work in progress" in raw_status:
            status = "Construction"
        else:
            status = "Closed"
    else:
        status = "Unknown"

    return {
        "name": name,
        "available": available,
        "status": status,
        "raw_status": raw_status,
        "upcoming_closures": upcoming_closures
    }


def interpret_tracked_status(raw_status: str) -> str:
    """
    Convert raw status to tracked status for history.
    """
    raw_status = raw_status.lower()
    if "data unavailable" in raw_status:
        return "Unknown"
    if "available" in raw_status and "unavailable" not in raw_status:
        if "raising soon" in raw_status:
            return "Available (Raising Soon)"
        else:
            return "Available"
    elif "work in progress" in raw_status:
        return "Unavailable (Construction)"
    else:
        return "Unavailable (Closed)"


def sanitize_document_id(shortcut: str, doc_id: str) -> str:
    """
    Create a sanitized document ID from bridge shortform and name.
    """
    normalized_doc_id = unicodedata.normalize('NFKD', doc_id).encode('ASCII', 'ignore').decode('ASCII')
    letters_only_doc_id = re.sub(r'[^a-zA-Z]', '', normalized_doc_id)
    truncated_doc_id = letters_only_doc_id[:25]
    return f"{shortcut}_{truncated_doc_id}"


def generate_history_doc_id(current_time: datetime) -> str:
    """
    Generate unique history entry ID.
    """
    formatted_time = current_time.strftime('%b%d-%H%M')
    unique_id = ''.join(random.choices(string.ascii_lowercase, k=4))
    return f"{formatted_time}-{unique_id}"


def append_to_history_file(bridge_id: str, entry: Dict[str, Any]) -> None:
    """
    Append entry to bridge history file (max 300 entries).

    Replaces Firestore subcollection with JSON file.
    """
    path = f"data/history/{bridge_id}.json"

    # Read existing or start fresh
    if os.path.exists(path):
        try:
            with open(path) as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []
    else:
        history = []

    # Prepend new entry (newest first)
    history.insert(0, entry)

    # Trim to max 300 entries
    history = history[:300]

    # Atomic write
    atomic_write_json(path, history)


def update_history(bridge_id: str, new_status: str, current_time: datetime, old_status: Optional[str] = None) -> None:
    """
    Update bridge history when status changes.

    Replaces update_bridge_history() for Firestore.
    """
    path = f"data/history/{bridge_id}.json"

    # Read existing history
    if os.path.exists(path):
        try:
            with open(path) as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []
    else:
        history = []

    doc_id = generate_history_doc_id(current_time)

    if not history:
        # No history - create first entry
        new_entry = {
            'id': doc_id,
            'start_time': current_time.isoformat(),
            'end_time': None,
            'status': new_status,
            'duration': None
        }
        history.insert(0, new_entry)
    else:
        last_entry = history[0]
        if last_entry.get('status') != new_status:
            # Status changed - close old entry, create new one
            end_time = current_time
            start_time = parse_datetime(last_entry.get('start_time'))
            if start_time:
                duration = round((end_time - start_time).total_seconds())
            else:
                duration = None

            # Update last entry
            last_entry['end_time'] = end_time.isoformat()
            last_entry['duration'] = duration

            # Create new entry
            new_entry = {
                'id': doc_id,
                'start_time': current_time.isoformat(),
                'end_time': None,
                'status': new_status,
                'duration': None
            }
            history.insert(0, new_entry)

    # Trim to max 300 entries
    history = history[:300]

    # Atomic write
    atomic_write_json(path, history)


def update_json_and_broadcast(bridges: List[Dict[str, Any]], region: str, shortform: str) -> None:
    """
    Update bridges.json and broadcast to WebSocket clients.

    Replaces update_firestore() for Firebase.
    """
    # Import broadcast function (avoid circular import at module level)
    try:
        from main import broadcast_sync, AVAILABLE_BRIDGES
    except ImportError:
        # Running standalone (e.g., for testing)
        broadcast_sync = lambda x: None
        AVAILABLE_BRIDGES = []

    current_time = datetime.now(TIMEZONE)
    updates_made = False

    for bridge in bridges:
        doc_id = sanitize_document_id(shortform, bridge['name'])
        interpreted = interpret_bridge_status(bridge)

        # Serialize upcoming_closures with expected_duration_minutes
        closures = add_expected_duration_to_closures([
            {
                'type': c['type'],
                'time': c['time'].isoformat() if isinstance(c['time'], datetime) else c['time'],
                'longer': c['longer'],
                'end_time': c.get('end_time').isoformat() if isinstance(c.get('end_time'), datetime) else c.get('end_time')
            }
            for c in bridge['upcoming_closures']
        ])

        # Get coordinates from config
        coords = BRIDGE_DETAILS.get(region, {}).get(bridge['name'], {})

        # Get existing statistics (if any)
        with last_known_state_lock:
            existing = last_known_state.get(doc_id, {})
        existing_stats = existing.get('static', {}).get('statistics', {})
        existing_last_updated = existing.get('live', {}).get('last_updated')

        # Build new data structure (matching migration plan schema)
        new_data = {
            'static': {
                'name': bridge['name'],
                'region': region,
                'region_short': shortform,
                'coordinates': {
                    'lat': coords.get('lat', 0),
                    'lng': coords.get('lng', 0)
                },
                'statistics': existing_stats if existing_stats else {
                    'average_closure_duration': 0,
                    'closure_ci': {'lower': 15, 'upper': 20},
                    'average_raising_soon': 0,
                    'raising_soon_ci': {'lower': 15, 'upper': 20},
                    'closure_durations': {
                        'under_9m': 0, '10_15m': 0, '16_30m': 0, '31_60m': 0, 'over_60m': 0
                    },
                    'total_entries': 0
                }
            },
            'live': {
                'status': interpreted['status'],
                'last_updated': current_time.isoformat(),
                'upcoming_closures': closures
            }
        }

        # Check if status actually changed
        with last_known_state_lock:
            doc_id_not_cached = doc_id not in last_known_state

        if doc_id_not_cached:
            # First time seeing this bridge
            updates_made = True

            # Calculate prediction
            prediction = calculate_prediction(
                status=new_data['live']['status'],
                last_updated=current_time,
                statistics=new_data['static']['statistics'],
                upcoming_closures=closures,
                current_time=current_time
            )
            new_data['live']['predicted'] = prediction

            with last_known_state_lock:
                last_known_state[doc_id] = copy.deepcopy(new_data)
        else:
            with last_known_state_lock:
                old_data = copy.deepcopy(last_known_state[doc_id])

            # Compare live data (excluding timestamps)
            old_live_compare = {k: v for k, v in old_data.get('live', {}).items()
                               if k not in ('last_updated', 'predicted')}
            new_live_compare = {k: v for k, v in new_data['live'].items()
                               if k not in ('last_updated', 'predicted')}

            if new_live_compare != old_live_compare:
                updates_made = True

                # Status changed - update history
                old_raw = bridge['raw_status']
                update_history(
                    doc_id,
                    interpret_tracked_status(old_raw),
                    current_time
                )

                # Calculate prediction
                prediction = calculate_prediction(
                    status=new_data['live']['status'],
                    last_updated=current_time,
                    statistics=new_data['static']['statistics'],
                    upcoming_closures=closures,
                    current_time=current_time
                )
                new_data['live']['predicted'] = prediction

                with last_known_state_lock:
                    last_known_state[doc_id] = copy.deepcopy(new_data)
            else:
                # No change - keep old timestamp and prediction
                new_data['live']['last_updated'] = old_data['live'].get('last_updated', current_time.isoformat())
                new_data['live']['predicted'] = old_data['live'].get('predicted')

                with last_known_state_lock:
                    last_known_state[doc_id] = copy.deepcopy(new_data)

    # Write to JSON file and broadcast if changes made
    if updates_made:
        with bridges_file_lock:
            # Read current file
            if os.path.exists("data/bridges.json"):
                with open("data/bridges.json") as f:
                    data = json.load(f)
            else:
                data = {"last_updated": None, "available_bridges": AVAILABLE_BRIDGES, "bridges": {}}

            # Update with new data
            with last_known_state_lock:
                for bridge_id, bridge_data in last_known_state.items():
                    data["bridges"][bridge_id] = bridge_data

            data["last_updated"] = current_time.isoformat()

            # Atomic write
            atomic_write_json("data/bridges.json", data)

        # Broadcast to WebSocket clients
        broadcast_sync(data)


def daily_statistics_update() -> None:
    """
    Recalculate statistics for all bridges from history files.

    Runs daily at 3 AM to update predictions.
    Works both when called from running app (updates in-memory state)
    and when called from CLI (updates file directly).
    """
    logger.info("Starting daily statistics update...")

    # Load bridges.json to get bridge IDs and current data
    with bridges_file_lock:
        if os.path.exists("data/bridges.json"):
            with open("data/bridges.json") as f:
                data = json.load(f)
        else:
            data = {"last_updated": None, "available_bridges": [], "bridges": {}}

    bridge_ids = list(data.get("bridges", {}).keys())
    if not bridge_ids:
        logger.warning("No bridges found in bridges.json")
        return

    updated_count = 0
    for bridge_id in bridge_ids:
        history_path = f"data/history/{bridge_id}.json"

        # Read history file
        if os.path.exists(history_path):
            try:
                with open(history_path) as f:
                    history = json.load(f)
            except (json.JSONDecodeError, IOError):
                history = []
        else:
            history = []

        if not history:
            continue

        # Convert to format expected by stats_calculator
        history_data = []
        for entry in history:
            history_data.append({
                'id': entry.get('id', ''),
                'status': entry.get('status', ''),
                'duration': entry.get('duration'),
                'start_time': parse_datetime(entry.get('start_time')) or datetime.min
            })

        # Calculate statistics
        stats, entries_to_delete = calculate_bridge_statistics(history_data)

        # Remove old entries from history file
        if entries_to_delete:
            history = [e for e in history if e.get('id') not in entries_to_delete]
            atomic_write_json(history_path, history)

        # Update statistics directly in the data dict (works for both CLI and app)
        if bridge_id in data["bridges"]:
            data["bridges"][bridge_id]["static"]["statistics"] = stats
            updated_count += 1

            # Also update in-memory state if app is running
            with last_known_state_lock:
                if bridge_id in last_known_state:
                    last_known_state[bridge_id]['static']['statistics'] = stats

    # Write updated data to bridges.json
    with bridges_file_lock:
        data["last_updated"] = datetime.now(TIMEZONE).isoformat()
        atomic_write_json("data/bridges.json", data)

    logger.info(f"Daily statistics update complete: {updated_count} bridges updated")


def process_single_region(bridge_key_info_pair: Tuple[str, Dict[str, str]]) -> Tuple[bool, int]:
    """
    Process a single region with smart backoff that never gives up.
    """
    bridge_key, info = bridge_key_info_pair
    region = info['region']

    # Check if we're still in backoff period
    with region_failures_lock:
        if bridge_key in region_failures:
            failure_count, next_retry = region_failures[bridge_key]
            if datetime.now() < next_retry:
                wait_seconds = (next_retry - datetime.now()).total_seconds()
                logger.info(f"⏳ {region}: Still waiting {wait_seconds:.0f}s (attempt #{failure_count})")
                return (False, 0)

    try:
        bridges = scrape_bridge_data(bridge_key)
        if bridges:
            update_json_and_broadcast(bridges, info['region'], info['shortform'])

            # Success - reset failure count
            with region_failures_lock:
                if bridge_key in region_failures:
                    failure_count = region_failures[bridge_key][0]
                    logger.info(f"✓ {region}: {len(bridges)} (recovered after {failure_count} failures)")
                    del region_failures[bridge_key]
                else:
                    logger.info(f"✓ {region}: {len(bridges)}")

            return (True, len(bridges))
        else:
            handle_region_failure(bridge_key, region, "No data")
            return (False, 0)

    except Exception as e:
        handle_region_failure(bridge_key, region, str(e)[:30] + "...")
        return (False, 0)


def handle_region_failure(bridge_key: str, region: str, error_msg: str) -> None:
    """
    Update failure tracking with next retry time.
    """
    with region_failures_lock:
        failure_count = region_failures.get(bridge_key, (0, None))[0] + 1
        wait_seconds = min(2 ** failure_count, 300)
        next_retry = datetime.now() + timedelta(seconds=wait_seconds)
        region_failures[bridge_key] = (failure_count, next_retry)

    if failure_count == 1:
        logger.error(f"✗ {region}: {error_msg}")
    else:
        logger.error(f"✗ {region}: {error_msg} (attempt #{failure_count}, retry in {wait_seconds}s)")


def scrape_and_update() -> None:
    """
    Main scraping function with concurrent execution and error handling.
    """
    start_time = datetime.now(TIMEZONE)
    logger.info("Scraping...")

    success_count = 0
    fail_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="BridgeScraper") as executor:
        future_to_region = {
            executor.submit(process_single_region, (bridge_key, info)): info['region']
            for bridge_key, info in BRIDGE_KEYS.items()
        }

        for future in concurrent.futures.as_completed(future_to_region, timeout=25):
            region = future_to_region[future]
            try:
                success, bridge_count = future.result()
                if success:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"✗ {region}: Unexpected error")
                fail_count += 1

    end_time = datetime.now(TIMEZONE)
    duration = (end_time - start_time).total_seconds()

    # Update last scrape time and change flag
    shared.last_scrape_time = end_time
    shared.last_scrape_had_changes = updates_made

    logger.info(f"Done in {duration:.1f}s - All: {success_count} ✓, {fail_count} ✗")


if __name__ == '__main__':
    # For standalone testing
    os.makedirs("data/history", exist_ok=True)
    if not os.path.exists("data/bridges.json"):
        with open("data/bridges.json", "w") as f:
            json.dump({"last_updated": None, "available_bridges": [], "bridges": {}}, f)
    scrape_and_update()
