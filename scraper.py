#scrapyer.py
import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import unicodedata
import re
import math
import copy
import random
import string
from config import BRIDGE_URLS, BRIDGE_COORDINATES
from cachetools import TTLCache
from stats_calculator import calculate_bridge_statistics

# Initialize Firebase
cred = credentials.Certificate('bridge-up-firebase-auth.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# Timezone for New York / Toronto
TIMEZONE = pytz.timezone('America/Toronto')

# Store last known state
last_known_state = {}

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
        print(f"Invalid date string: {date_str}")
        return None, False

def parse_old_style(soup):
    bridges = []
    bridge_tables = soup.select('table#grey_box')
    
    for table in bridge_tables:
        name = table.select_one('span.lgtextblack').text.strip()
        status_span = table.select_one('span#status')
        current_status = status_span.text.strip() if status_span else "Unknown"
        
        available = "available" in current_status.lower()
        
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
            'available': available,
            'raw_status': current_status,
            'upcoming_closures': upcoming_closures
        })
    
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

def scrape_bridge_data(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'lxml')
    
    if soup.select_one('div.new-bridgestatus-container'):
        return parse_new_style(soup)
    else:
        return parse_old_style(soup)
    
def interpret_bridge_status(bridge_data, db, region_short):
    name = bridge_data['name']
    raw_status = bridge_data['raw_status'].lower()
    upcoming_closures = bridge_data.get('upcoming_closures', [])
    current_time = datetime.now(TIMEZONE)

    available = "available" in raw_status and "unavailable" not in raw_status
    display_status = "UNKNOWN"
    display_info = raw_status
    display_predicted_change = None

    if available:
        display_status = "OPEN"
        if upcoming_closures:
            next_closure = upcoming_closures[0]
            closure_time = next_closure['time']
            if closure_time <= current_time + timedelta(minutes=15):
                display_info = f"Closing soon at {closure_time.strftime('%-I:%M%p').lower()} for {next_closure['type']}"
            else:
                display_info = f"Next closure at {closure_time.strftime('%-I:%M%p').lower()} for {next_closure['type']}"
            if next_closure.get('longer', False):
                display_info += " (may take longer)"
            display_predicted_change = closure_time
        elif "raising soon" in raw_status:
            display_info = "Closing soon"
        else:
            doc_id = sanitize_document_id(region_short, bridge_data['name'])
            if doc_id in last_known_open_times:
                open_since = last_known_open_times[doc_id]
                display_info = f"Open since {open_since.strftime('%-I:%M%p').lower()}"
            else:
                history_query = db.collection('bridges').document(doc_id).collection('history').order_by('start_time', direction=firestore.Query.DESCENDING).limit(1)
                history_docs = history_query.get()
                if history_docs:
                    last_history = history_docs[0].to_dict()
                    open_since = last_history['start_time'].astimezone(TIMEZONE)
                    last_known_open_times[doc_id] = open_since
                    display_info = f"Open since {open_since.strftime('%-I:%M%p').lower()}"
                else:
                    display_info = "Open"
    else:
        if "lowering" in raw_status:
            display_status = "OPENING"
            display_info = "Opening right now..."
        elif "raising" in raw_status:
            display_status = "CLOSING"
            display_info = "Closing right now..."
        elif "work in progress" in raw_status:
            display_status = "CLOSED"
            display_info = "Closed for construction"
        else:
            display_status = "CLOSED"
            display_info = "Currently closed."

    return {
        "name": name,
        "available": available,
        "display_status": display_status,
        "display_info": display_info,
        "display_predicted_change": display_predicted_change
    }

def interpret_tracked_status(raw_status):
    raw_status = raw_status.lower()
    if "available" in raw_status and "unavailable" not in raw_status:
        if "raising soon" in raw_status:
            return "Available (Raising Soon)"
        else:
            return "Available"
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
        
        # Delete old history entries
        thirty_one_days_ago = datetime.now(TIMEZONE) - timedelta(days=31)
        old_history = doc_ref.collection('history').where('start_time', '<=', thirty_one_days_ago).get() # Using positional arguments as the 'filter' keyword argument caused issues
        for old_entry in old_history:
            batch.delete(old_entry.reference)
        
        # Get recent history for statistics calculation
        recent_history = doc_ref.collection('history').where('start_time', '>', thirty_one_days_ago).get() # Using positional arguments as the 'filter' keyword argument caused issues
        history_data = [entry.to_dict() for entry in recent_history]
        
        # Calculate statistics
        stats = calculate_bridge_statistics(history_data)
        
        # Update statistics in the main bridge document
        batch.update(doc_ref, {'statistics': stats})
    
    # Commit all changes
    batch.commit()

def update_firestore(bridges, region, shortform):
    global last_known_state
    batch = db.batch()
    update_needed = False

    for bridge in bridges:
        doc_id = sanitize_document_id(shortform, bridge['name'])
        doc_ref = db.collection('bridges').document(doc_id)

        current_time = datetime.now(TIMEZONE)
        interpreted_status = interpret_bridge_status(bridge, db, shortform)

        new_data = {
            'name': bridge['name'],
            'region': region,
            'region_short': shortform,
            'coordinates': firestore.GeoPoint(
                BRIDGE_COORDINATES.get(region, {}).get(bridge['name'], {}).get('lat', 0),
                BRIDGE_COORDINATES.get(region, {}).get(bridge['name'], {}).get('lng', 0)
            ),
            'live': {
                'available': interpreted_status['available'],
                'raw_status': bridge['raw_status'],
                'display_status': interpreted_status['display_status'],
                'display_info': interpreted_status['display_info'],
                'display_predicted_change': interpreted_status['display_predicted_change'],
                'upcoming_closures': [
                    {
                        'type': closure['type'],
                        'time': closure['time'],
                        'longer': closure['longer']
                    }
                    for closure in bridge['upcoming_closures']
                ]
            }
        }

        if doc_id not in last_known_state:
            update_needed = True
            new_data['live']['last_updated'] = current_time
            batch.set(doc_ref, new_data)
            last_known_state[doc_id] = copy.deepcopy(new_data)
        else:
            # Compare everything except 'live.last_updated'
            old_data = copy.deepcopy(last_known_state[doc_id])
            old_data['live'].pop('last_updated', None)
            new_data_compare = copy.deepcopy(new_data)
            new_data_compare['live'].pop('last_updated', None)

            if new_data_compare != old_data:
                update_needed = True
                new_data['live']['last_updated'] = current_time
                batch.set(doc_ref, new_data, merge=True)
                
                if new_data['live']['raw_status'] != last_known_state[doc_id]['live']['raw_status']:
                    update_bridge_history(doc_ref, interpret_tracked_status(new_data['live']['raw_status']), current_time, batch)
                    if new_data['live']['available']:
                        last_known_open_times[doc_id] = current_time
                
                last_known_state[doc_id] = copy.deepcopy(new_data)

    if update_needed:
        batch.commit()

# Can trigger externally as well:
def scrape_and_update():
    for url, info in BRIDGE_URLS.items():
        bridges = scrape_bridge_data(url)
        update_firestore(bridges, info['region'], info['shortform'])

if __name__ == '__main__':
    scrape_and_update()