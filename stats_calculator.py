#stats_calculator.py
import math

import math

def calculate_bridge_statistics(history_data):
    closure_durations = []
    raising_soon_durations = []
    closure_buckets = {'under_9m': 0, '10_15m': 0, '16_30m': 0, '31_60m': 0, 'over_60m': 0}

    for entry in history_data:
        if entry['status'] == 'Unavailable (Closed)' and entry.get('duration'):
            duration_minutes = entry['duration'] / 60
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
        elif entry['status'] == 'Available (Raising Soon)' and entry.get('duration'):
            raising_soon_durations.append(entry['duration'] / 60)

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
    #stats['closure_durations'] = {k: v for k, v in closure_buckets.items()} #show all even 0s

    return stats

def calculate_confidence_interval(data):
    if len(data) < 2:
        return {'lower': 0, 'upper': 0}
    avg = sum(data) / len(data)
    variance = sum((x - avg) ** 2 for x in data) / (len(data) - 1)
    std_dev = math.sqrt(variance)
    margin = 1.96 * (std_dev / math.sqrt(len(data)))  # 95% confidence interval
    return {
        'lower': max(0, math.floor(avg - margin)),  # Round down, minimum 0
        'upper': math.ceil(avg + margin)  # Round up
    }

def calculate_confidence_interval(data):
    if len(data) < 2:
        return {'lower': 0, 'upper': 0}
    
    avg = sum(data) / len(data)
    variance = sum((x - avg) ** 2 for x in data) / (len(data) - 1)
    std_dev = math.sqrt(variance)
    margin = 1.96 * (std_dev / math.sqrt(len(data)))  # 95% confidence interval
    
    return {
        'lower': math.floor(max(0, avg - margin)),  # Round down
        'upper': math.ceil(avg + margin)  # Round up
    }