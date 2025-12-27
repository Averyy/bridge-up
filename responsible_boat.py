# responsible_boat.py
"""
Responsible vessel detection for bridge closures.

Identifies which vessel is most likely responsible for a bridge closure
based on position, heading, speed, and proximity to the bridge.

Two different algorithms:
- "Closing soon": Vessel approaching OR stationary waiting at bridge
- "Closed/Closing": Vessel actively passing through (must be moving)
"""
import math
from typing import Optional

from config import BRIDGE_DETAILS, BRIDGE_KEYS
from boat_config import COG_NOT_AVAILABLE, HEADING_NOT_AVAILABLE


# Algorithm constants
MAX_DISTANCE_CLOSING_SOON = 7.0  # km (allows catching vessels approaching from further out)
MAX_DISTANCE_CLOSED = 4.0  # km (buffer for vessels actively transiting)
MIN_SCORE_CLOSING_SOON = 0.25  # Slightly lower than Closed to catch approaching vessels further out
MIN_SCORE_CLOSED = 0.3
BASE_SCORE_CAP = 3.0  # Prevents very close vessels from dominating
MOVING_SPEED_THRESHOLD = 0.5  # knots
MOVING_AWAY_SPEED_THRESHOLD = 1.5  # knots - vessels moving away faster than this cannot be responsible for "Closing soon"
HEADING_TOLERANCE = 60  # degrees
STATIONARY_WAITING_ZONE = 0.25  # km - only vessels within 250m are actually waiting at the bridge


def get_bridge_region(bridge_id: str) -> str:
    """
    Map bridge ID prefix to vessel tracking region.

    Args:
        bridge_id: Bridge identifier (e.g., "SCT_CarltonSt")

    Returns:
        Region name ("welland" or "montreal")
    """
    prefix = bridge_id.split("_")[0] if "_" in bridge_id else bridge_id
    if prefix in ("SCT", "PC"):
        return "welland"
    elif prefix in ("MSS", "K", "SBS"):
        return "montreal"
    return "unknown"


def get_bridge_coordinates(bridge_id: str) -> Optional[tuple[float, float]]:
    """
    Get bridge coordinates from config.

    Args:
        bridge_id: Bridge identifier

    Returns:
        Tuple of (lat, lng) or None if not found
    """
    prefix = bridge_id.split("_")[0] if "_" in bridge_id else ""

    # Find region from prefix
    region = None
    for key, info in BRIDGE_KEYS.items():
        if info['shortform'] == prefix:
            region = info['region']
            break

    if not region:
        return None

    # Find bridge in region
    bridges = BRIDGE_DETAILS.get(region, {})
    for name, details in bridges.items():
        # Generate the ID the same way main.py does
        import unicodedata
        import re
        normalized = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
        letters_only = re.sub(r'[^a-zA-Z]', '', normalized)
        truncated = letters_only[:25]
        generated_id = f"{prefix}_{truncated}"

        if generated_id == bridge_id:
            return (details['lat'], details['lng'])

    return None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points in kilometers using Haversine formula.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates

    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth's radius in km

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate initial bearing from point 1 to point 2.

    Args:
        lat1, lon1: Start point coordinates
        lat2, lon2: End point coordinates

    Returns:
        Bearing in degrees (0-360, where 0=North, 90=East)
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon_rad = math.radians(lon2 - lon1)

    x = math.sin(dlon_rad) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)

    bearing = math.atan2(x, y)
    bearing = math.degrees(bearing)
    bearing = (bearing + 360) % 360

    return bearing


def angle_difference(angle1: float, angle2: float) -> float:
    """
    Calculate the absolute difference between two angles (0-180).

    Handles wraparound correctly (e.g., 350° and 10° differ by 20°, not 340°).

    Args:
        angle1, angle2: Angles in degrees

    Returns:
        Absolute difference in degrees (0-180)
    """
    diff = abs(angle1 - angle2) % 360
    if diff > 180:
        diff = 360 - diff
    return diff


def get_vessel_direction(vessel: dict, prefer_cog: bool) -> Optional[float]:
    """
    Get vessel's direction of travel or pointing.

    For moving vessels: prefer COG (actual travel direction)
    For stationary vessels: use heading (bow direction)

    Args:
        vessel: Vessel data dict
        prefer_cog: True for moving vessels (use COG), False for stationary (use heading)

    Returns:
        Direction in degrees, or None if not available
    """
    if prefer_cog:
        # Moving: COG is actual travel direction
        cog = vessel.get("course")
        if cog is not None and cog != COG_NOT_AVAILABLE:
            return float(cog)
        # Fallback to heading
        heading = vessel.get("heading")
        if heading is not None and heading != HEADING_NOT_AVAILABLE:
            return float(heading)
        return None
    else:
        # Stationary: heading is bow direction (COG meaningless at 0 speed)
        heading = vessel.get("heading")
        if heading is not None and heading != HEADING_NOT_AVAILABLE:
            return float(heading)
        return None


def is_heading_toward_bridge(vessel: dict, bridge_coords: tuple[float, float],
                              is_moving: bool) -> Optional[bool]:
    """
    Check if vessel is heading toward (or pointed at) the bridge.

    Args:
        vessel: Vessel data dict with position, heading, course
        bridge_coords: (lat, lng) of bridge
        is_moving: True if vessel speed >= 0.5 knots

    Returns:
        True if heading toward bridge (within tolerance),
        False if heading away,
        None if direction unknown
    """
    # Get vessel position (handle both nested and flat formats)
    position = vessel.get("position") or {}
    v_lat = position.get("lat") if position else vessel.get("lat")
    v_lon = position.get("lon") if position else vessel.get("lon")

    if v_lat is None or v_lon is None:
        return None

    # Get vessel direction
    direction = get_vessel_direction(vessel, prefer_cog=is_moving)
    if direction is None:
        return None

    # Calculate bearing from vessel to bridge
    bridge_lat, bridge_lon = bridge_coords
    bearing = calculate_bearing(v_lat, v_lon, bridge_lat, bridge_lon)

    # Check if within tolerance
    diff = angle_difference(direction, bearing)
    return diff <= HEADING_TOLERANCE


def score_for_closed(vessel: dict, distance_km: float) -> float:
    """
    Calculate score for Closed/Closing status.

    Vessel is actively passing through - must be moving.
    No heading multiplier needed (could be entering, in span, or exiting).

    Args:
        vessel: Vessel data dict
        distance_km: Distance to bridge in km

    Returns:
        Score (higher = more likely responsible)
    """
    if distance_km > MAX_DISTANCE_CLOSED:
        return 0.0

    speed = vessel.get("speed_knots") or 0
    if speed < MOVING_SPEED_THRESHOLD:
        return 0.0  # Must be moving to be passing through

    # Capped base score (closer = higher, but capped to prevent very close from dominating)
    return min(1.0 / (distance_km + 0.1), BASE_SCORE_CAP)


def score_for_closing_soon(vessel: dict, bridge_coords: tuple[float, float],
                           distance_km: float) -> float:
    """
    Calculate score for Closing Soon status.

    Vessel could be approaching OR stationary waiting at bridge.
    Uses heading/COG to determine likelihood.

    Args:
        vessel: Vessel data dict
        bridge_coords: (lat, lng) of bridge
        distance_km: Distance to bridge in km

    Returns:
        Score (higher = more likely responsible)
    """
    if distance_km > MAX_DISTANCE_CLOSING_SOON:
        return 0.0

    # Capped base score
    base_score = min(1.0 / (distance_km + 0.1), BASE_SCORE_CAP)

    speed = vessel.get("speed_knots") or 0
    is_moving = speed >= MOVING_SPEED_THRESHOLD

    # Determine if heading toward bridge
    heading_toward = is_heading_toward_bridge(vessel, bridge_coords, is_moving)

    if is_moving:
        if heading_toward is True:
            multiplier = 2.0  # Approaching - very likely
        elif heading_toward is None:
            multiplier = 1.0  # Unknown direction
        else:
            # Moving away from bridge - cannot be responsible for upcoming closure
            if speed >= MOVING_AWAY_SPEED_THRESHOLD:
                return 0.0  # Clearly moving away at speed - impossible to cause upcoming closure
            else:
                multiplier = 0.1  # Slow movement away, might be maneuvering
    else:
        # Stationary - only high multiplier if close (actually waiting at bridge)
        # Distant stationary vessels are likely docked, not waiting
        if distance_km <= STATIONARY_WAITING_ZONE:
            if heading_toward is True:
                multiplier = 2.5  # Close and pointed at bridge - waiting to transit
            elif heading_toward is None:
                multiplier = 0.1  # Close but unknown direction - can't confirm waiting
            else:
                multiplier = 0.05  # Close but pointed away - probably docked
        else:
            # Far from bridge - likely docked somewhere, not waiting
            if heading_toward is True:
                multiplier = 0.3  # Happens to point toward bridge, but far away
            elif heading_toward is None:
                multiplier = 0.05  # Unknown and far - very unlikely
            else:
                multiplier = 0.02  # Pointed away and far - almost certainly not responsible

    return base_score * multiplier


def find_responsible_vessel(bridge_id: str, bridge_status: str,
                            vessels: list[dict]) -> Optional[int]:
    """
    Find the vessel most likely responsible for a bridge closure.

    Uses different algorithms for different statuses:
    - "Closing soon": Consider approaching vessels AND stationary vessels pointed at bridge
    - "Closed"/"Closing": Prioritize moving vessels (actively transiting)

    Args:
        bridge_id: Bridge identifier (e.g., "SCT_CarltonSt")
        bridge_status: Current bridge status string
        vessels: List of vessel dicts from boat tracker

    Returns:
        MMSI of responsible vessel, or None if no likely candidate
    """
    # Only calculate for closure-related statuses
    if bridge_status not in ("Closing soon", "Closed", "Closing"):
        return None

    # Get bridge info
    bridge_coords = get_bridge_coordinates(bridge_id)
    if bridge_coords is None:
        return None

    bridge_region = get_bridge_region(bridge_id)

    # Pre-filter vessels by region (optimization)
    regional_vessels = [v for v in vessels if v.get("region") == bridge_region]

    if not regional_vessels:
        return None

    # Determine which algorithm to use
    is_closing_soon = bridge_status == "Closing soon"
    min_threshold = MIN_SCORE_CLOSING_SOON if is_closing_soon else MIN_SCORE_CLOSED

    best_mmsi = None
    best_score = 0.0

    for vessel in regional_vessels:
        # Get vessel position (handle both nested and flat formats)
        position = vessel.get("position") or {}
        v_lat = position.get("lat") if position else vessel.get("lat")
        v_lon = position.get("lon") if position else vessel.get("lon")

        if v_lat is None or v_lon is None:
            continue

        # Calculate distance
        distance_km = haversine(bridge_coords[0], bridge_coords[1], v_lat, v_lon)

        # Calculate score based on status
        if is_closing_soon:
            score = score_for_closing_soon(vessel, bridge_coords, distance_km)
        else:
            score = score_for_closed(vessel, distance_km)

        if score > best_score:
            best_score = score
            best_mmsi = vessel.get("mmsi")

    # Apply minimum threshold
    if best_score < min_threshold:
        return None

    return best_mmsi


def calculate_responsible_vessels(bridges: dict, vessels: list[dict]) -> dict[str, Optional[int]]:
    """
    Calculate responsible vessels for all bridges.

    Convenience function that processes all bridges at once.

    Args:
        bridges: Dict of bridge_id -> bridge data (with 'live' -> 'status')
        vessels: List of vessel dicts from boat tracker

    Returns:
        Dict of bridge_id -> responsible_vessel_mmsi (or None)
    """
    result = {}

    for bridge_id, bridge_data in bridges.items():
        live = bridge_data.get("live", {})
        status = live.get("status", "Unknown")

        result[bridge_id] = find_responsible_vessel(bridge_id, status, vessels)

    return result
