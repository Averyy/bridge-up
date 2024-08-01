#stats_calculator.py
import math
from datetime import datetime

MAX_HISTORY_ENTRIES = 300  # New constant for max history entries

def calculate_bridge_statistics(history_data, doc_ref, batch):
    delete_ids = []
    closure_durations = []
    raising_soon_durations = []
    closure_buckets = {'under_9m': 0, '10_15m': 0, '16_30m': 0, '31_60m': 0, 'over_60m': 0}
    total_entries = 0
    batch_operation_count = 0

    # Sort history_data by start_time in descending order (newest first)
    sorted_history = sorted(history_data, key=lambda x: x.get('start_time', datetime.min), reverse=True)
    kept_entries = []

    for entry in sorted_history:
        if not isinstance(entry, dict) or 'status' not in entry:
            continue

        status = entry['status']
        duration = entry.get('duration')

        if duration is None:
            continue  # Keep ongoing entries
        elif status in ['Unavailable (Closed)', 'Available (Raising Soon)']:
            kept_entries.append(entry)
        else:
            # deletes "Available" and "Unavailable (Construction)"
            delete_ids.append(entry['id'])
            batch.delete(doc_ref.collection('history').document(entry['id']))
            batch_operation_count += 1

    # Limit to MAX_HISTORY_ENTRIES, deleting oldest if exceeded
    if len(kept_entries) > MAX_HISTORY_ENTRIES:
        for entry in kept_entries[MAX_HISTORY_ENTRIES:]:
            delete_ids.append(entry['id'])
            batch.delete(doc_ref.collection('history').document(entry['id']))
            batch_operation_count += 1
        kept_entries = kept_entries[:MAX_HISTORY_ENTRIES]

    # Process kept entries for statistics
    for entry in kept_entries:
        total_entries += 1
        status = entry['status']
        duration = entry['duration']
        if status == 'Unavailable (Closed)':
            duration_minutes = duration / 60
            closure_durations.append(duration_minutes)
            if duration_minutes < 9:
                closure_buckets['under_9m'] += 1
            elif duration_minutes <= 15:
                closure_buckets['10_15m'] += 1
            elif duration_minutes <= 30:
                closure_buckets['16_30m'] += 1
            elif duration_minutes <= 60:
                closure_buckets['31_60m'] += 1
            else:
                closure_buckets['over_60m'] += 1
        elif status == 'Available (Raising Soon)':
            raising_soon_durations.append(duration / 60)

    # Calculate statistics
    stats = {}
    if closure_durations:
        stats['average_closure_duration'] = round(sum(closure_durations) / len(closure_durations))
        stats['closure_ci'] = calculate_confidence_interval(closure_durations)
    else:
        stats['average_closure_duration'] = 0
        stats['closure_ci'] = {'lower': 0, 'upper': 0}

    if raising_soon_durations:
        stats['average_raising_soon'] = round(sum(raising_soon_durations) / len(raising_soon_durations))
        stats['raising_soon_ci'] = calculate_confidence_interval(raising_soon_durations)
    else:
        stats['average_raising_soon'] = 0
        stats['raising_soon_ci'] = {'lower': 0, 'upper': 0}

    stats['closure_durations'] = closure_buckets
    stats['total_entries'] = total_entries

    return stats, batch_operation_count, batch

def calculate_confidence_interval(data):
    if len(data) < 2:
        return {'lower': 0, 'upper': 0}
    
    avg = sum(data) / len(data)
    variance = sum((x - avg) ** 2 for x in data) / (len(data) - 1)
    std_dev = math.sqrt(variance)
    margin = 1.96 * (std_dev / math.sqrt(len(data)))  # 95% confidence interval
    
    return {
        'lower': math.floor(max(0, avg - margin)),
        'upper': math.ceil(avg + margin)
    }