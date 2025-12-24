# predictions.py
"""
Prediction logic for bridge status changes.

This module contains the prediction calculations that were previously in iOS's
BridgeInfoGenerator.swift. Moving this logic to the backend allows:
- Smarter predictions without iOS app updates
- Consistent predictions across all platforms
- Simpler iOS code (just format what backend provides)

Prediction meanings by status:
- Closed: predicts when bridge will OPEN
- Closing soon: predicts when bridge will CLOSE
- Construction: predicts when bridge will OPEN (if end_time known)
- Open/Opening/Unknown: no prediction (returns None)
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import pytz

TIMEZONE = pytz.timezone('America/Toronto')

# Duration constants from seaway site (hardcoded in iOS, now centralized here)
# Format: {vessel_type_lowercase: {longer_flag: duration_minutes}}
EXPECTED_DURATIONS = {
    'commercial vessel': {False: 15, True: 30},
    'pleasure craft': {False: 10, True: 20},
    'next arrival': {False: 15, True: 30},  # Treat as commercial
}

# Types that use blended prediction (boat closures - blend expected with historical)
BOAT_TYPES = {'commercial vessel', 'pleasure craft', 'next arrival'}


def get_expected_duration(closure_type: str, longer: bool) -> Optional[int]:
    """
    Get expected closure duration in minutes based on vessel type.

    Args:
        closure_type: The type of closure (e.g., 'Commercial Vessel')
        longer: Whether this is a longer-than-normal closure (asterisk notation)

    Returns:
        Expected duration in minutes, or None if unknown type
    """
    type_lower = closure_type.lower()
    if type_lower in EXPECTED_DURATIONS:
        return EXPECTED_DURATIONS[type_lower][longer]
    return None


def parse_datetime(dt: Any) -> Optional[datetime]:
    """
    Parse datetime from various formats (datetime object, ISO string).

    Args:
        dt: Datetime object or ISO format string

    Returns:
        Timezone-aware datetime, or None if parsing fails
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return TIMEZONE.localize(dt)
        return dt.astimezone(TIMEZONE)

    if isinstance(dt, str):
        try:
            # Handle Z suffix and various timezone formats
            clean_str = dt.replace('Z', '+00:00')
            parsed = datetime.fromisoformat(clean_str)
            return parsed.astimezone(TIMEZONE)
        except ValueError:
            return None

    return None


def calculate_prediction(
    status: str,
    last_updated: datetime,
    statistics: Dict[str, Any],
    upcoming_closures: List[Dict[str, Any]],
    current_time: Optional[datetime] = None
) -> Optional[Dict[str, str]]:
    """
    Calculate predicted next status change.

    Matches iOS BridgeInfoGenerator.swift logic exactly.

    Args:
        status: Current bridge status (e.g., 'Closed', 'Closing soon')
        last_updated: When the current status started
        statistics: Bridge statistics with closure_ci and raising_soon_ci
        upcoming_closures: List of upcoming closure objects
        current_time: Current time (defaults to now, injectable for testing)

    Returns:
        {"lower": ISO timestamp, "upper": ISO timestamp} or None if unknown

    Prediction meanings:
        - For Closed/Construction: predicts when bridge will OPEN
        - For Closing soon: predicts when bridge will CLOSE
    """
    if current_time is None:
        current_time = datetime.now(TIMEZONE)

    status_lower = status.lower()

    # === CLOSED / CONSTRUCTION: predict when it will OPEN ===
    if status_lower in ('closed', 'construction'):
        elapsed_minutes = (current_time - last_updated).total_seconds() / 60
        closure_ci = statistics.get('closure_ci', {'lower': 15, 'upper': 20})

        # Case A: Construction with known end_time
        for closure in upcoming_closures:
            if closure.get('type', '').lower() == 'construction':
                end_time = parse_datetime(closure.get('end_time'))
                closure_start = parse_datetime(closure.get('time'))

                if (end_time and end_time > current_time and
                    closure_start and closure_start <= current_time):
                    return {
                        "lower": end_time.isoformat(),
                        "upper": end_time.isoformat()
                    }

        # Case B: Construction without end_time -> unknown
        if status_lower == 'construction':
            return None

        # Case C: Boat closure that has STARTED (time in the past)
        if upcoming_closures:
            first = upcoming_closures[0]
            closure_time = parse_datetime(first.get('time'))
            closure_type = first.get('type', '').lower()

            if (closure_time and closure_time <= current_time and
                closure_type in BOAT_TYPES):

                expected = first.get('expected_duration_minutes') or get_expected_duration(
                    closure_type, first.get('longer', False)
                )

                if expected:
                    # Blend expected duration with historical confidence interval
                    lower = (expected + closure_ci['lower']) / 2 - elapsed_minutes
                    upper = (expected + closure_ci['upper']) / 2 - elapsed_minutes

                    if lower <= 0 and upper <= 0:
                        return None  # Longer than usual

                    return {
                        "lower": (current_time + timedelta(minutes=max(lower, 0))).isoformat(),
                        "upper": (current_time + timedelta(minutes=max(upper, 0))).isoformat()
                    }

        # Case D: Pure statistics (no active boat closure)
        lower = closure_ci['lower'] - elapsed_minutes
        upper = closure_ci['upper'] - elapsed_minutes

        if lower <= 0 and upper <= 0:
            return None  # Longer than usual

        return {
            "lower": (current_time + timedelta(minutes=max(lower, 0))).isoformat(),
            "upper": (current_time + timedelta(minutes=max(upper, 0))).isoformat()
        }

    # === CLOSING SOON: predict when it will CLOSE ===
    elif status_lower == 'closing soon':
        # If there's a specific closure time, iOS uses it directly
        if upcoming_closures:
            first = upcoming_closures[0]
            closure_time = parse_datetime(first.get('time'))

            if closure_time:
                # Closure time passed -> iOS shows "was expected at"
                if closure_time <= current_time:
                    return None

                # Closure within 1 hour -> iOS uses closure.time directly
                if (closure_time - current_time).total_seconds() < 3600:
                    return None

        # Pure statistics (no upcoming closure or closure > 1 hour away)
        elapsed_minutes = (current_time - last_updated).total_seconds() / 60
        raising_soon_ci = statistics.get('raising_soon_ci', {'lower': 15, 'upper': 20})

        lower = raising_soon_ci['lower'] - elapsed_minutes
        upper = raising_soon_ci['upper'] - elapsed_minutes

        if lower <= 0 and upper <= 0:
            return None  # Longer than usual

        return {
            "lower": (current_time + timedelta(minutes=max(lower, 0))).isoformat(),
            "upper": (current_time + timedelta(minutes=max(upper, 0))).isoformat()
        }

    # === OTHER STATUSES: no prediction ===
    return None


def add_expected_duration_to_closures(upcoming_closures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Add expected_duration_minutes to each closure based on type + longer flag.

    This removes hardcoded duration values from iOS - backend now provides them.

    Args:
        upcoming_closures: List of closure dicts with 'type' and 'longer' fields

    Returns:
        Same list with 'expected_duration_minutes' added where calculable
    """
    for closure in upcoming_closures:
        if 'expected_duration_minutes' not in closure:
            duration = get_expected_duration(
                closure.get('type', ''),
                closure.get('longer', False)
            )
            if duration:
                closure['expected_duration_minutes'] = duration
    return upcoming_closures
