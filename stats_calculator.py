# stats_calculator.py
"""
Statistics calculation for bridge closure predictions.

Calculates averages, confidence intervals, and duration buckets from
historical closure data. Migrated from Firebase to JSON file storage.
"""
import math
from datetime import datetime
from typing import Dict, Any, List, Tuple

MAX_HISTORY_ENTRIES = 300  # Max history entries to keep per bridge


def calculate_bridge_statistics(history_data: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Calculate bridge statistics from history data.

    Processes history entries to calculate:
    - Average closure duration with confidence interval
    - Average "raising soon" duration with confidence interval
    - Duration buckets (under_9m, 10_15m, etc.)

    Args:
        history_data: List of history entry dicts with 'id', 'status', 'duration', 'start_time'

    Returns:
        Tuple of:
        - stats: Dict with calculated statistics
        - entries_to_delete: List of entry IDs that should be deleted
    """
    entries_to_delete = []
    closure_durations = []
    raising_soon_durations = []
    closure_buckets = {'under_9m': 0, '10_15m': 0, '16_30m': 0, '31_60m': 0, 'over_60m': 0}
    total_entries = 0

    # Sort history_data by start_time in descending order (newest first)
    sorted_history = sorted(
        history_data,
        key=lambda x: x.get('start_time', datetime.min),
        reverse=True
    )
    kept_entries = []

    for entry in sorted_history:
        if not isinstance(entry, dict) or 'status' not in entry:
            continue

        status = entry['status']
        duration = entry.get('duration')

        if duration is None:
            continue  # Keep ongoing entries (no duration yet)
        elif status in ['Unavailable (Closed)', 'Available (Raising Soon)']:
            kept_entries.append(entry)
        else:
            # Delete "Available" and "Unavailable (Construction)" entries
            if entry.get('id'):
                entries_to_delete.append(entry['id'])

    # Limit to MAX_HISTORY_ENTRIES, deleting oldest if exceeded
    if len(kept_entries) > MAX_HISTORY_ENTRIES:
        for entry in kept_entries[MAX_HISTORY_ENTRIES:]:
            if entry.get('id'):
                entries_to_delete.append(entry['id'])
        kept_entries = kept_entries[:MAX_HISTORY_ENTRIES]

    # Process kept entries for statistics
    for entry in kept_entries:
        total_entries += 1
        status = entry['status']
        duration = entry['duration']

        if status == 'Unavailable (Closed)':
            duration_minutes = duration / 60
            closure_durations.append(duration_minutes)

            # Bucket the duration
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
        stats['average_closure_duration'] = None
        stats['closure_ci'] = None

    if raising_soon_durations:
        stats['average_raising_soon'] = round(sum(raising_soon_durations) / len(raising_soon_durations))
        stats['raising_soon_ci'] = calculate_confidence_interval(raising_soon_durations)
    else:
        stats['average_raising_soon'] = None
        stats['raising_soon_ci'] = None

    stats['closure_durations'] = closure_buckets
    stats['total_entries'] = total_entries

    return stats, entries_to_delete


def calculate_confidence_interval(data: List[float]) -> Dict[str, int]:
    """
    Calculate 95% confidence interval for the given data.

    Uses t-distribution approximation (1.96 multiplier for 95% CI).

    Args:
        data: List of numeric values

    Returns:
        Dict with 'lower' and 'upper' bounds (floored/ceiled integers)
    """
    if len(data) < 2:
        return {'lower': 0, 'upper': 0}

    avg = sum(data) / len(data)
    variance = sum((x - avg) ** 2 for x in data) / (len(data) - 1)  # Bessel's correction
    std_dev = math.sqrt(variance)
    margin = 1.96 * (std_dev / math.sqrt(len(data)))  # 95% confidence interval

    return {
        'lower': math.floor(max(0, avg - margin)),
        'upper': math.ceil(avg + margin)
    }
