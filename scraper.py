#scraper.py
import firebase_admin
from firebase_admin import credentials, initialize_app, firestore
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
import concurrent.futures
import threading
from config import BRIDGE_KEYS, BRIDGE_DETAILS, OLD_JSON_ENDPOINT, NEW_JSON_ENDPOINT
from cachetools import TTLCache
from stats_calculator import calculate_bridge_statistics
from loguru import logger

# Configure logger for cleaner output
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    enqueue=False,    # Ensures immediate output in Docker logs
    colorize=False    # Disable colors for Docker (containers don't support ANSI colors)
)


# Get Firebase creds
if os.environ.get('DOCKER_ENV'):
    cred_path = '/app/data/firebase-auth.json'
else:
    cred_path = os.path.join(os.path.dirname(__file__), 'firebase-auth.json')

# Initialize Firebase
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Timezone for New York / Toronto
TIMEZONE = pytz.timezone('America/Toronto')

# Store last known state
last_known_state = {}
last_known_state_lock = threading.Lock()

# Smart backoff tracking - WITH THREAD SAFETY
region_failures = {}  # url -> (failure_count, next_retry_time)
region_failures_lock = threading.Lock()

# Caching TTL
last_known_open_times = TTLCache(maxsize=1000, ttl=10800)  # 3 hours TTL for bridges

# Smart endpoint caching - auto-discovers which endpoint works for each region
endpoint_cache: Dict[str, str] = {}  # {'BridgeSCT': 'old', 'BridgeSBS': 'new'}
endpoint_cache_lock = threading.Lock()

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
            # Handle Z suffix and +00:00 timezone
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
        closure_time = TIMEZONE.localize(datetime.combine(now.date(), datetime.strptime(time_str, '%H:%M').time()))

        # Handle * for longer closures
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

    This format is used by SCT, PC, and MSS regions. Contains:
    - bridgeModelList: Live bridge status with vessel ETAs
    - bridgeClosureList: Planned construction closures

    Args:
        json_data: Raw JSON response from API

    Returns:
        List of bridge dicts with {name, raw_status, upcoming_closures}
    """
    bridges = []
    bridge_models = json_data.get('bridgeModelList', [])
    bridge_closures = json_data.get('bridgeClosureList', [])

    # Parse live bridge status
    for bridge_model in bridge_models:
        name = bridge_model.get('address', '').strip()
        status = bridge_model.get('status', 'Unknown').strip()

        # Extract vessel ETA if available (upcoming closure)
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
        reason = closure.get('reason', 'Construction')
        is_continuous = closure.get('continuousHour', 'Y') == 'Y'

        if not closure_period:
            continue

        try:
            # Parse closureP format: "DEC 22, 2025 - DEC 23, 2025, 08:00 - 17:00"
            # or single day: "DEC 22, 2025 - DEC 22, 2025, 09:00 - 12:00"
            import re
            match = re.match(
                r'([A-Z]{3} \d{1,2}, \d{4}) - ([A-Z]{3} \d{1,2}, \d{4}), (\d{2}:\d{2}) - (\d{2}:\d{2})',
                closure_period
            )
            if not match:
                logger.warning(f"Failed to match closure pattern: {closure_period}")
                continue

            start_date_str, end_date_str, start_time_str, end_time_str = match.groups()

            # Parse dates: "DEC 22, 2025"
            start_date = datetime.strptime(start_date_str, '%b %d, %Y')
            end_date = datetime.strptime(end_date_str, '%b %d, %Y')

            # Parse times
            start_hour, start_min = map(int, start_time_str.split(':'))
            end_hour, end_min = map(int, end_time_str.split(':'))

            if is_continuous:
                # Continuous closure: single entry from start datetime to end datetime
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
                # Non-continuous: daily time window repeated for each day in range
                # e.g., "DEC 22 - DEC 23, 08:00 - 17:00" means 8am-5pm on Dec 22 AND 8am-5pm on Dec 23
                current_date = start_date
                while current_date <= end_date:
                    day_start = TIMEZONE.localize(current_date.replace(hour=start_hour, minute=start_min))
                    day_end = TIMEZONE.localize(current_date.replace(hour=end_hour, minute=end_min))

                    # Only add future or ongoing closures
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
            logger.warning(f"Failed to parse closure closureP: {closure_period} - {e}")
            continue

    return bridges


def parse_new_json(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse JSON response from new API format.

    This format is used by SBS region. Contains:
    - bridgeStatusList: Bridge status with lift list and maintenance list

    Args:
        json_data: Raw JSON response from API

    Returns:
        List of bridge dicts with {name, raw_status, upcoming_closures}
    """
    bridges = []
    bridge_statuses = json_data.get('bridgeStatusList', [])
    current_time = datetime.now(TIMEZONE)

    for bridge_status in bridge_statuses:
        name = bridge_status.get('address', '').strip()

        # New format has status3 as the combined status
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

                # Only add future closures
                if closure_time and closure_time > current_time:
                    lift_type = lift.get('type', 'a')
                    upcoming_closures.append({
                        'type': 'Next Arrival' if lift_type == 'a' else 'Commercial Vessel',
                        'time': closure_time,
                        'longer': False  # New format doesn't have asterisk notation
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

                # Only add future closures
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

    Tries cached endpoint first, falls back to other endpoint if needed.
    Auto-discovers and remembers which endpoint works for each region.

    Args:
        bridge_key: The bridge region key (e.g., 'BridgeSCT')
        timeout: Request timeout in seconds
        retries: Number of retry attempts per endpoint

    Returns:
        List of bridge dicts with {name, raw_status, upcoming_closures}
    """
    # Get cached endpoint preference
    with endpoint_cache_lock:
        cached = endpoint_cache.get(bridge_key, 'old')

    # Define endpoint order based on cache
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
            # Update cache on success
            with endpoint_cache_lock:
                if endpoint_cache.get(bridge_key) != endpoint_type:
                    logger.info(f"{bridge_key}: Discovered {endpoint_type} endpoint works")
                    endpoint_cache[bridge_key] = endpoint_type
            return parser(data)

        # Check if old endpoint returned new format
        if data and endpoint_type == 'old' and data.get('bridgeStatusList'):
            with endpoint_cache_lock:
                endpoint_cache[bridge_key] = 'new'
            logger.info(f"{bridge_key}: Old endpoint returned new format, caching")
            return parse_new_json(data)

    logger.error(f"✗ {bridge_key}: No data from either endpoint")
    return []


def interpret_bridge_status(bridge_data):
    name = bridge_data['name']
    raw_status = bridge_data['raw_status'].lower()
    upcoming_closures = bridge_data.get('upcoming_closures', [])

    # Data unavailable is message returned for new style bridges if service is down
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
        # Handle specific unavailable statuses
        if "lowering" in raw_status:
            status = "Opening"
        elif "raising" in raw_status:
            status = "Closing"
        elif "work in progress" in raw_status:
            status = "Construction"
        else:
            status = "Closed"
    else:
        # No "available" or "unavailable" in status - this is garbage data
        status = "Unknown"

    return {
        "name": name,
        "available": available,
        "status": status,
        "raw_status": raw_status,
        "upcoming_closures": upcoming_closures
    }

def interpret_tracked_status(raw_status):
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

def sanitize_document_id(shortcut, doc_id):
    # Normalize unicode characters to their closest ASCII representation
    normalized_doc_id = unicodedata.normalize('NFKD', doc_id).encode('ASCII', 'ignore').decode('ASCII')
    # Remove all non-letter characters
    letters_only_doc_id = re.sub(r'[^a-zA-Z]', '', normalized_doc_id)
    # Truncate to the first 10 characters
    truncated_doc_id = letters_only_doc_id[:25]
    # Combine shortcut and truncated ID
    sanitized_doc_id = f"{shortcut}_{truncated_doc_id}"
    return sanitized_doc_id

def generate_history_doc_id(current_time):
    # Generated as Jul15-1325-abcd (month date - event start time - 4 random letters)
    formatted_time = current_time.strftime('%b%d-%H%M')
    unique_id = ''.join(random.choices(string.ascii_lowercase, k=4))
    return f"{formatted_time}-{unique_id}"

def update_bridge_history(doc_ref, new_status, current_time, batch):
    history_query = doc_ref.collection('history').order_by('start_time', direction=firestore.Query.DESCENDING).limit(1)
    history_docs = history_query.get()
    
    doc_id = generate_history_doc_id(current_time)

    if not history_docs:
        new_history = {
            'start_time': current_time,
            'end_time': None,
            'status': new_status,
            'duration': None
        }
        batch.set(doc_ref.collection('history').document(doc_id), new_history)
    else:
        last_history = history_docs[0]
        last_history_data = last_history.to_dict()

        if last_history_data['status'] != new_status:
            end_time = current_time
            duration = round((end_time - last_history_data['start_time']).total_seconds())

            batch.update(last_history.reference, {
                'end_time': end_time,
                'duration': duration
            })

            new_history = {
                'start_time': current_time,
                'end_time': None,
                'status': new_status,
                'duration': None
            }
            batch.set(doc_ref.collection('history').document(doc_id), new_history)

def daily_statistics_update():
    bridges = db.collection('bridges').get()
    batch = db.batch()
    
    for bridge in bridges:
        doc_ref = bridge.reference
        
        # Get all history entries
        history = doc_ref.collection('history').order_by('start_time', direction=firestore.Query.DESCENDING).get()
        
        # print(f"\nProcessing bridge: {doc_ref.id}")
        # print(f"Total history entries: {len(history)}")
        
        # Calculate statistics and optimize history in one pass
        history_data = [{'id': entry.id, **entry.to_dict()} for entry in history]
        stats, operation_count, updated_batch = calculate_bridge_statistics(history_data, doc_ref, batch)
        
        # Update statistics in the main bridge document
        updated_batch.update(doc_ref, {'statistics': stats})

        # Always commit - statistics update needs to be saved
        updated_batch.commit()
    
    # print("Daily statistics update completed")

def update_firestore(bridges, region, shortform):
    global last_known_state
    batch = db.batch()
    update_needed = False

    for bridge in bridges:
        doc_id = sanitize_document_id(shortform, bridge['name'])
        doc_ref = db.collection('bridges').document(doc_id)

        current_time = datetime.now(TIMEZONE)
        interpreted_status = interpret_bridge_status(bridge)

        new_data = {
            'name': bridge['name'],
            'region': region,
            'region_short': shortform,
            'coordinates': firestore.GeoPoint(
                BRIDGE_DETAILS.get(region, {}).get(bridge['name'], {}).get('lat', 0),
                BRIDGE_DETAILS.get(region, {}).get(bridge['name'], {}).get('lng', 0)
            ),
            'live': {
                'available': interpreted_status['available'],
                'raw_status': bridge['raw_status'],
                'status': interpreted_status['status'],
                'upcoming_closures': [
                    {
                        'type': closure['type'],
                        'time': closure['time'],
                        'longer': closure['longer'],
                        'end_time': closure.get('end_time')
                    }
                    for closure in bridge['upcoming_closures']
                ]
            }
        }

        # Check if we need to fetch existing data - THREAD SAFE
        with last_known_state_lock:
            doc_id_not_cached = doc_id not in last_known_state
        
        if doc_id_not_cached:
            try:
                existing_doc = doc_ref.get()
            except Exception as e:
                logger.error(f"✗ Failed to read {doc_id}: {str(e)[:50]}...")
                existing_doc = None
            
            if existing_doc and existing_doc.exists:
                existing_data = existing_doc.to_dict()
                if 'statistics' in existing_data:
                    new_data['statistics'] = existing_data['statistics']
                if 'live' in existing_data and 'last_updated' in existing_data['live']:
                    new_data['live']['last_updated'] = existing_data['live']['last_updated']
                else:
                    new_data['live']['last_updated'] = current_time
            else:
                new_data['live']['last_updated'] = current_time
            update_needed = True
            batch.set(doc_ref, new_data)
            
            # Update cache - THREAD SAFE
            with last_known_state_lock:
                last_known_state[doc_id] = copy.deepcopy(new_data)
        else:
            # Get old data - THREAD SAFE
            with last_known_state_lock:
                old_data = copy.deepcopy(last_known_state[doc_id])
            
            old_live = {k: v for k, v in old_data['live'].items() if k != 'last_updated'}
            new_live = {k: v for k, v in new_data['live'].items() if k != 'last_updated'}

            if new_live != old_live:
                update_needed = True
                new_data['live']['last_updated'] = current_time
                batch.set(doc_ref, {'live': new_data['live']}, merge=True)
                
                if new_data['live']['raw_status'] != old_data['live']['raw_status']:
                    update_bridge_history(doc_ref, interpret_tracked_status(new_data['live']['raw_status']), current_time, batch)
                    if new_data['live']['available']:
                        last_known_open_times[doc_id] = current_time
                
                # Update cache - THREAD SAFE
                with last_known_state_lock:
                    last_known_state[doc_id]['live'] = copy.deepcopy(new_data['live'])
            else:
                new_data['live']['last_updated'] = old_data['live']['last_updated']

    if update_needed:
        try:
            batch.commit()
        except Exception as e:
            logger.error(f"✗ Firebase batch failed for {region}: {str(e)[:50]}...")
            raise

# Can trigger externally as well:
def process_single_region(bridge_key_info_pair: Tuple[str, Dict[str, str]]) -> Tuple[bool, int]:
    """
    Process a single region with smart backoff that never gives up.

    Args:
        bridge_key_info_pair: Tuple of (bridge_key, info_dict) where info_dict
                             contains 'region' and 'shortform' keys

    Returns:
        Tuple of (success: bool, bridge_count: int)
    """
    bridge_key, info = bridge_key_info_pair
    region = info['region']

    # Check if we're still in backoff period - THREAD SAFE
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
            update_firestore(bridges, info['region'], info['shortform'])

            # Success - reset failure count - THREAD SAFE
            with region_failures_lock:
                if bridge_key in region_failures:
                    failure_count = region_failures[bridge_key][0]
                    logger.info(f"✓ {region}: {len(bridges)} (recovered after {failure_count} failures)")
                    del region_failures[bridge_key]  # Clear failures
                else:
                    logger.info(f"✓ {region}: {len(bridges)}")

            return (True, len(bridges))
        else:
            # Empty response counts as failure
            handle_region_failure(bridge_key, region, "No data")
            return (False, 0)

    except Exception as e:
        handle_region_failure(bridge_key, region, str(e)[:30] + "...")
        return (False, 0)


def handle_region_failure(bridge_key: str, region: str, error_msg: str) -> None:
    """
    Update failure tracking with next retry time - THREAD SAFE.

    Args:
        bridge_key: The bridge region key (e.g., 'BridgeSCT')
        region: Human-readable region name
        error_msg: Error message to log
    """
    with region_failures_lock:
        failure_count = region_failures.get(bridge_key, (0, None))[0] + 1

        # Calculate next retry time (exponential backoff, max 5 minutes)
        wait_seconds = min(2 ** failure_count, 300)
        next_retry = datetime.now() + timedelta(seconds=wait_seconds)

        region_failures[bridge_key] = (failure_count, next_retry)

    if failure_count == 1:
        logger.error(f"✗ {region}: {error_msg}")
    else:
        logger.error(f"✗ {region}: {error_msg} (attempt #{failure_count}, retry in {wait_seconds}s)")


def scrape_and_update() -> None:
    """Main scraping function with concurrent execution and error handling."""
    start_time = datetime.now(TIMEZONE)
    logger.info("Scraping...")

    success_count = 0
    fail_count = 0

    # Use ThreadPoolExecutor for concurrent scraping (I/O bound operations)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="BridgeScraper") as executor:
        # Submit all scraping tasks concurrently
        future_to_region = {
            executor.submit(process_single_region, (bridge_key, info)): info['region']
            for bridge_key, info in BRIDGE_KEYS.items()
        }

        # Collect results with timeout
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
    logger.info(f"Done in {duration:.1f}s - All: {success_count} ✓, {fail_count} ✗")

if __name__ == '__main__':
    scrape_and_update()