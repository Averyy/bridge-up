# boat_config.py
"""
Configuration for boat tracking system.

Contains:
- AIS data validation constants
- Region bounding boxes (Welland Canal, Montreal)
- AIS vessel type mappings
- Vessel name sanitization
"""
from typing import Optional


# AIS data validation constants
# These are standard AIS protocol values, shared across UDP and AISHub processing
MMSI_MIN = 200_000_000  # Ships start at 200M
MMSI_MAX = 799_999_999  # Ships end at 799M (800M+ are SAR, AIS repeaters, etc.)
SPEED_NOT_AVAILABLE = 102.3  # AIS special value for speed not available
HEADING_NOT_AVAILABLE = 511  # AIS special value for heading not available
COG_NOT_AVAILABLE = 360  # AIS special value for course over ground not available
DIRECTION_MAX_VALID = 360  # Heading and COG valid range is 0-359.9 (exclusive upper bound)

# Region bounding boxes to track approaching vessels
BOAT_REGIONS = {
    "welland": {
        "name": "Welland Canal",
        # ~20km buffer: Lake Ontario entrance (north) to Lake Erie (south)
        # All 8 bridges: Lakeshore, Carlton, Queenston, Glendale, Hwy20, Main, Mellanby, Clarence
        "bounds": {"lat_min": 42.70, "lat_max": 43.40, "lon_min": -79.40, "lon_max": -79.05}
    },
    "montreal": {
        "name": "Montreal South Shore",
        # ~25km buffer: St. Lawrence Seaway approaches
        # All 7 bridges: Victoria x2, Sainte-Catherine, CP Railway 7A/7B, St-Louis, Larocque
        "bounds": {"lat_min": 45.05, "lat_max": 45.70, "lon_min": -74.35, "lon_max": -73.20}
    }
}

# Combined bounding box for AISHub polling (covers both regions in one request)
# AISHub has 1 req/60s limit, so polling one big box gives 2x fresher data for both regions
# Extra vessels (Lake Ontario, St. Lawrence) are filtered out by get_vessel_region()
# NOTE: Update this if BOAT_REGIONS changes! Must encompass all regions.
AISHUB_COMBINED_BOUNDS = {
    "lat_min": 42.70,   # South of Welland (min of all lat_min)
    "lat_max": 45.70,   # North of Montreal (max of all lat_max)
    "lon_min": -79.40,  # West of Welland (min of all lon_min)
    "lon_max": -73.20   # East of Montreal (max of all lon_max)
}

# AIS vessel type code -> (display_name, category)
# Categories: cargo, tanker, passenger, tug, fishing, sailing, pleasure, other
VESSEL_TYPES = {
    # Category 2x: Wing in Ground
    20: ("WIG", "other"),

    # Category 3x: Special craft
    30: ("Fishing", "fishing"),
    31: ("Towing", "tug"),
    32: ("Towing (large)", "tug"),
    33: ("Dredger", "other"),
    34: ("Diving Ops", "other"),
    35: ("Military", "other"),
    36: ("Sailing", "sailing"),
    37: ("Pleasure Craft", "pleasure"),

    # Category 4x: High-Speed Craft
    40: ("High-Speed Craft", "passenger"),
    41: ("HSC - Hazard A", "passenger"),
    42: ("HSC - Hazard B", "passenger"),
    43: ("HSC - Hazard C", "passenger"),
    44: ("HSC - Hazard D", "passenger"),
    49: ("HSC - No info", "passenger"),

    # Category 5x: Special craft
    50: ("Pilot Vessel", "other"),
    51: ("SAR", "other"),
    52: ("Tug", "tug"),
    53: ("Port Tender", "other"),
    54: ("Anti-Pollution", "other"),
    55: ("Law Enforcement", "other"),
    56: ("Local Vessel", "other"),
    57: ("Local Vessel", "other"),
    58: ("Medical", "other"),
    59: ("Special Craft", "other"),

    # Category 6x: Passenger
    60: ("Passenger", "passenger"),
    61: ("Passenger - Hazard A", "passenger"),
    62: ("Passenger - Hazard B", "passenger"),
    63: ("Passenger - Hazard C", "passenger"),
    64: ("Passenger - Hazard D", "passenger"),
    69: ("Passenger - No info", "passenger"),

    # Category 7x: Cargo
    70: ("Cargo", "cargo"),
    71: ("Cargo - Hazard A", "cargo"),
    72: ("Cargo - Hazard B", "cargo"),
    73: ("Cargo - Hazard C", "cargo"),
    74: ("Cargo - Hazard D", "cargo"),
    79: ("Cargo - No info", "cargo"),

    # Category 8x: Tanker
    80: ("Tanker", "tanker"),
    81: ("Tanker - Hazard A", "tanker"),
    82: ("Tanker - Hazard B", "tanker"),
    83: ("Tanker - Hazard C", "tanker"),
    84: ("Tanker - Hazard D", "tanker"),
    89: ("Tanker - No info", "tanker"),

    # Category 9x: Other
    90: ("Other", "other"),
    91: ("Other - Hazard A", "other"),
    92: ("Other - Hazard B", "other"),
    93: ("Other - Hazard C", "other"),
    94: ("Other - Hazard D", "other"),
}

def get_vessel_region(lat: float, lon: float) -> Optional[str]:
    """
    Determine which region a vessel is in based on coordinates.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        Region ID ("welland" or "montreal") or None if outside all regions
    """
    for region_id, config in BOAT_REGIONS.items():
        b = config["bounds"]
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return region_id
    return None


def get_vessel_type_info(type_code: Optional[int]) -> tuple[str, str]:
    """
    Get display name and category for AIS vessel type code.

    Args:
        type_code: AIS type code (0-99) or None

    Returns:
        Tuple of (display_name, category)
    """
    if type_code is None:
        return ("Unknown", "other")
    if type_code in VESSEL_TYPES:
        return VESSEL_TYPES[type_code]
    if 0 <= type_code < 100:
        return ("Unknown", "other")
    return ("Invalid", "other")


def sanitize_vessel_name(name: Optional[str]) -> Optional[str]:
    """
    Clean vessel name for JSON/display.

    Removes control characters and normalizes whitespace.

    Args:
        name: Raw vessel name from AIS

    Returns:
        Cleaned name or None if empty/invalid
    """
    if not name:
        return None
    # Remove non-printable and control characters
    name = ''.join(c for c in name if c.isprintable() and c not in '\t\n\r\v\f')
    # Normalize whitespace and strip
    name = ' '.join(name.split()).strip()
    # Remove common placeholder values
    if name in ('', '@', '@@@@@@@@@@@@@@@@@@@@', 'UNKNOWN'):
        return None
    return name
