#scrapyer.py
import firebase_admin
from firebase_admin import credentials, initialize_app, firestore
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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
from config import BRIDGE_URLS, BRIDGE_DETAILS
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

def parse_date(date_str):
    if isinstance(date_str, datetime):
        return date_str.astimezone(TIMEZONE), False

    # Check if the date string contains only time
    time_match = re.match(r'(\d{2}:\d{2})(\*)?', date_str)
    if time_match:
        time_str, asterisk = time_match.groups()
        now = datetime.now(TIMEZONE)
        closure_time = TIMEZONE.localize(datetime.combine(now.date(), datetime.strptime(time_str, '%H:%M').time()))
        
        # Handle * for longer closures
        longer = bool(asterisk)
        return closure_time, longer
    
    # Check if the date string is valid datetime
    try:
        closure_time = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        closure_time = TIMEZONE.localize(closure_time)
        longer = False
        return closure_time, longer
    except ValueError:
        logger.warning(f"Invalid date string: {date_str}")
        return None, False
    
def parse_old_style(soup):
    current_time = datetime.now(TIMEZONE)
    bridges = []
    bridge_tables = soup.select('table#grey_box')
    
    for table in bridge_tables:
        name = table.select_one('span.lgtextblack').text.strip()
        status_span = table.select_one('span#status')
        current_status = status_span.text.strip() if status_span else "Unknown"
        
        upcoming_closures = []
        upcoming_span = table.select_one('span.lgtextblack10')
        if upcoming_span:
            arrival_text = upcoming_span.text.strip()
            if "Next Arrival:" in arrival_text:
                next_arrival = arrival_text.split("Next Arrival:")[1].strip()
                if next_arrival != "----":
                    closure_time, longer = parse_date(next_arrival)
                    if closure_time:
                        upcoming_closures.append({
                            'type': 'Next Arrival',
                            'time': closure_time,
                            'longer': longer or '*' in next_arrival
                        })

        bridges.append({
            'name': name,
            'raw_status': current_status,
            'upcoming_closures': upcoming_closures
        })

    # Parse planned closures (construction)
    bridge_planned_closures = soup.select('div.closuretext')
    for closure in bridge_planned_closures:
        closure_text = closure.text.strip()
        match = re.search(r'Bridge (\d+[A-Z]?) Closure\. Effective: (\w+ \d{1,2}, \d{4})(?: - (\w+ \d{1,2}, \d{4}))?, (\d{2}:\d{2} - \d{2}:\d{2})', closure_text)
        if match:
            bridge_number, start_date, end_date, time_range = match.groups()
            start_time, end_time = time_range.split(' - ')
            
            end_date = end_date or start_date  # If end_date is None, use start_date

            try:
                start_date = datetime.strptime(start_date, '%b %d, %Y').date()
                end_date = datetime.strptime(end_date, '%b %d, %Y').date()
                start_time = datetime.strptime(start_time, '%H:%M').time()
                end_time = datetime.strptime(end_time, '%H:%M').time()
            except ValueError:
                continue  # Skip invalid date formats

            for current_date in (start_date + timedelta(days=n) for n in range((end_date - start_date).days + 1)):
                day_start = TIMEZONE.localize(datetime.combine(current_date, start_time))
                day_end = TIMEZONE.localize(datetime.combine(current_date, end_time))

                if day_end > current_time:
                    planned_closure = {
                        'type': 'Construction',
                        'time': day_start,
                        'end_time': day_end,
                        'longer': False
                    }

                    for bridge in bridges:
                        for region, bridge_info in BRIDGE_DETAILS.items():
                            if bridge['name'] in bridge_info and bridge_info[bridge['name']].get('number') == bridge_number:
                                bridge['upcoming_closures'].append(planned_closure)
                                break
                        else:
                            continue
                        break

    return bridges

def parse_new_style(soup):
    bridges = []
    bridge_items = soup.select('div.bridge-item')
    
    for item in bridge_items:
        name = item.select_one('h3').text.strip()
        status_elements = item.select('h1.status-title')
        status = ' '.join([elem.text.strip() for elem in status_elements])
        
        upcoming_closures = []
        lift_container = item.select_one('div.bridge-lift-container')
        if lift_container:
            lift_items = lift_container.select('p.item-data')
            for lift_item in lift_items:
                if "No anticipated bridge lifts" in lift_item.text:
                    continue
                lift_parts = lift_item.text.split(': ')
                if len(lift_parts) == 2:
                    lift_type, lift_time = lift_parts
                    if lift_time != "----":
                        closure_time, parsed_longer = parse_date(lift_time.strip())
                        if closure_time:
                            upcoming_closures.append({
                                'type': lift_type.strip(),
                                'time': closure_time,
                                'longer': parsed_longer or '*' in lift_time
                            })

        bridges.append({
            'name': name,
            'raw_status': status,
            'upcoming_closures': upcoming_closures
        })
    
    return bridges

def scrape_bridge_data(url, timeout=10, retries=3):
    """Scrape bridge data with timeout and retry logic."""
    soup = None
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'lxml')
            break
        except (requests.RequestException, requests.Timeout) as e:
            if attempt == retries - 1:
                logger.error(f"✗ {url}: {str(e)[:50]}...")
                return []
            logger.warning(f"Retry {attempt + 1}/{retries} for {url}")
            continue
    
    if soup is None:
        logger.error(f"✗ All attempts failed for {url}")
        return []
    
    if soup.select_one('div.new-bridgestatus-container'):
        return parse_new_style(soup)
    else:
        return parse_old_style(soup)
    
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
        
        # Commit the batch for this bridge
        if operation_count > 0:
            # print(f"Committing batch with {operation_count} delete operations and 1 update operation")
            updated_batch.commit()
        # else:
            # print("No changes to commit for this bridge")
    
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
def process_single_region(url_info_pair):
    """Process a single region with smart backoff that never gives up"""
    url, info = url_info_pair
    region = info['region']
    
    # Check if we're still in backoff period - THREAD SAFE
    with region_failures_lock:
        if url in region_failures:
            failure_count, next_retry = region_failures[url]
            if datetime.now() < next_retry:
                wait_seconds = (next_retry - datetime.now()).total_seconds()
                logger.info(f"⏳ {region}: Still waiting {wait_seconds:.0f}s (attempt #{failure_count})")
                return (False, 0)
    
    try:
        bridges = scrape_bridge_data(url)
        if bridges:
            update_firestore(bridges, info['region'], info['shortform'])
            
            # Success - reset failure count - THREAD SAFE
            with region_failures_lock:
                if url in region_failures:
                    failure_count = region_failures[url][0]
                    logger.info(f"✓ {region}: {len(bridges)} (recovered after {failure_count} failures)")
                    del region_failures[url]  # Clear failures
                else:
                    logger.info(f"✓ {region}: {len(bridges)}")
            
            return (True, len(bridges))
        else:
            # Empty response counts as failure
            handle_region_failure(url, region, "No data")
            return (False, 0)
            
    except Exception as e:
        handle_region_failure(url, region, str(e)[:30] + "...")
        return (False, 0)

def handle_region_failure(url, region, error_msg):
    """Update failure tracking with next retry time - THREAD SAFE"""
    with region_failures_lock:
        failure_count = region_failures.get(url, (0, None))[0] + 1
        
        # Calculate next retry time (exponential backoff, max 5 minutes)
        wait_seconds = min(2 ** failure_count, 300)
        next_retry = datetime.now() + timedelta(seconds=wait_seconds)
        
        region_failures[url] = (failure_count, next_retry)
    
    if failure_count == 1:
        logger.error(f"✗ {region}: {error_msg}")
    else:
        logger.error(f"✗ {region}: {error_msg} (attempt #{failure_count}, retry in {wait_seconds}s)")

def scrape_and_update():
    """Main scraping function with concurrent execution and error handling."""
    start_time = datetime.now(TIMEZONE)
    logger.info("Scraping...")
    
    success_count = 0
    fail_count = 0
    
    # Use ThreadPoolExecutor for concurrent scraping (I/O bound operations)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="BridgeScraper") as executor:
        # Submit all scraping tasks concurrently
        future_to_region = {
            executor.submit(process_single_region, (url, info)): info['region'] 
            for url, info in BRIDGE_URLS.items()
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