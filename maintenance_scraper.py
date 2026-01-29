"""
Automated maintenance page scraper.

Fetches and parses https://greatlakes-seaway.com/en/for-our-communities/infrastructure-maintenance/
to extract bridge closure information.

Runs daily at 6:00 AM when ENABLE_MAINTENANCE_SCRAPER=true.
"""
import os
import json
import re
import time as time_module
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from loguru import logger

from shared import TIMEZONE, atomic_write_json
from config import BRIDGE_NAME_MAP, MAINTENANCE_FILE

MAINTENANCE_URL = "https://greatlakes-seaway.com/en/for-our-communities/infrastructure-maintenance/"
REQUEST_TIMEOUT = 10  # seconds (matches CLAUDE.md default)

# Regex patterns for date extraction
# Matches both "Full closure:" and "Closure Dates:" formats
FULL_CLOSURE_PATTERN = re.compile(
    r'(?:Full closure|Closure Dates):?\s*(\w+ \d+, \d{4})\s+to\s+(\w+ \d+, \d{4})',
    re.IGNORECASE
)
# Daily patterns support:
# - Any am/pm combination (am-am, am-pm, pm-pm, pm-am)
# - Optional minutes (9 am, 9:30 am, 9:30am)
# - Optional space before am/pm
DAILY_RANGE_PATTERN = re.compile(
    r'Daily closure[:\s]*\((\d+)(?::(\d+))?\s*(am|pm)\s*-\s*(\d+)(?::(\d+))?\s*(am|pm)\)\s*(\w+ \d+, \d{4})\s+to\s+(\w+ \d+, \d{4})',
    re.IGNORECASE
)
DAILY_SINGLE_PATTERN = re.compile(
    r'Daily closure[:\s]*\((\d+)(?::(\d+))?\s*(am|pm)\s*-\s*(\d+)(?::(\d+))?\s*(am|pm)\)\s*(\w+ \d+, \d{4})(?!\s+(?:to|and))',
    re.IGNORECASE
)
DAILY_AND_PATTERN = re.compile(
    r'Daily closure[:\s]*\((\d+)(?::(\d+))?\s*(am|pm)\s*-\s*(\d+)(?::(\d+))?\s*(am|pm)\)\s*(\w+ \d+, \d{4})\s+and\s+(\w+ \d+, \d{4})',
    re.IGNORECASE
)


def sanitize_text(text: str) -> str:
    """
    Sanitize scraped text by removing unwanted characters and normalizing whitespace.

    Args:
        text: Raw scraped text

    Returns:
        Cleaned text with normalized whitespace and no control characters.
        Does NOT escape HTML entities - clients render as plain text.
    """
    if not text:
        return ""
    # Remove control characters (except newline/tab which get normalized below)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    # Normalize whitespace (multiple spaces, tabs, newlines -> single space)
    text = re.sub(r'\s+', ' ', text)
    # Strip leading/trailing whitespace
    text = text.strip()
    # NOTE: We intentionally do NOT call html.escape() here because:
    # 1. iOS client renders descriptions as plain text, not HTML
    # 2. Escaping would show literal "&amp;" instead of "&" to users
    # 3. The data comes from a trusted source (Seaway website)
    return text


def fetch_maintenance_page(max_retries: int = 5) -> Optional[str]:
    """
    Fetch HTML from maintenance page with incremental backoff retry.

    Uses blocking time.sleep() for backoff delays (up to 62s total). This is
    acceptable because the scraper runs daily at 6 AM on its own scheduled job,
    not in the main scraping hot path.

    Args:
        max_retries: Maximum number of retry attempts (default 5)

    Returns:
        HTML string if successful, None on failure after all retries
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    # Incremental backoff delays: 2s, 4s, 8s, 16s, 32s
    backoff_delays = [2, 4, 8, 16, 32]

    for attempt in range(max_retries):
        try:
            # verify=False: greatlakes-seaway.com has SSL chain issues (missing Sectigo intermediate)
            response = requests.get(MAINTENANCE_URL, timeout=REQUEST_TIMEOUT, verify=False, headers=headers)
            response.raise_for_status()
            if attempt > 0:
                logger.info(f"Maintenance page fetch succeeded on attempt {attempt + 1}")
            return response.text
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                logger.warning(f"Fetch attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s...")
                time_module.sleep(delay)
            else:
                logger.error(f"Failed to fetch maintenance page after {max_retries} attempts: {e}")
                return None
    return None  # pragma: no cover - unreachable but satisfies type checker


def parse_date(date_str: str) -> datetime:
    """
    Parse date string like "January 10, 2026" to datetime.

    Args:
        date_str: Date string in format "Month Day, Year"

    Returns:
        Timezone-aware datetime object
    """
    dt = dateutil_parser.parse(date_str)
    # Ensure it's localized to EST
    if dt.tzinfo is None:
        dt = TIMEZONE.localize(dt, is_dst=False)
    return dt


def convert_12h_to_24h(hour_str: str, ampm: str) -> int:
    """
    Convert 12-hour time to 24-hour format.

    Args:
        hour_str: Hour as string (e.g., "9", "12")
        ampm: "am" or "pm"

    Returns:
        Hour in 24-hour format (0-23)
    """
    hour = int(hour_str)
    if hour < 1 or hour > 12:
        raise ValueError(f"Invalid 12-hour format hour: {hour} (must be 1-12)")
    ampm_lower = ampm.lower()
    if ampm_lower not in ('am', 'pm'):
        raise ValueError(f"Invalid am/pm value: {ampm} (must be 'am' or 'pm')")

    if ampm_lower == 'am':
        # 12 am = midnight (00:00)
        if hour == 12:
            return 0
        return hour
    else:  # pm
        # 12 pm = noon (12:00)
        if hour == 12:
            return 12
        return hour + 12


def fix_date_typo(date_str: str, now: datetime) -> str:
    """
    Fix obvious year typos in dates (e.g., 2025 when it should be 2026).

    If a date is more than 180 days in the past, assume the year is wrong
    and increment it. This handles website typos like "March 5, 2025" when
    they meant "March 5, 2026".

    Args:
        date_str: Date string like "March 5, 2025"
        now: Current datetime (timezone-aware)

    Returns:
        Corrected date string
    """
    try:
        parsed = dateutil_parser.parse(date_str)
        # Make parsed datetime timezone-aware for comparison
        if parsed.tzinfo is None:
            parsed = TIMEZONE.localize(parsed, is_dst=False)

        # If date is more than 180 days in the past, likely a typo
        days_diff = (now - parsed).days
        if days_diff > 180:
            # Increment year
            corrected = parsed.replace(year=parsed.year + 1)
            corrected_str = corrected.strftime("%B %d, %Y")
            logger.warning(f"Date typo detected: '{date_str}' → '{corrected_str}' (was {days_diff} days in past)")
            return corrected_str
        return date_str
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not check date typo for '{date_str}': {e}")
        return date_str


def extract_closures_from_html(html: str) -> List[Dict]:
    """
    Parse HTML and extract bridge closure information.

    Only includes periods that haven't ended yet (future/current closures).

    Args:
        html: HTML string from maintenance page

    Returns:
        List of closure dicts with bridge_id, description, periods (only future/current)
    """
    soup = BeautifulSoup(html, 'html.parser')
    closures = []
    parse_failures = 0
    now = datetime.now(TIMEZONE)

    # Find all bridge headers (h1 with class ea-header)
    bridge_headers = soup.find_all('h1', class_='ea-header')

    for header in bridge_headers:
        # Extract bridge name from header text and sanitize
        bridge_name = sanitize_text(header.get_text(strip=True))

        # Skip pedestrian bridges
        if "Pedestrian" in bridge_name or "Trail" in bridge_name:
            logger.debug(f"Skipping pedestrian bridge: {bridge_name}")
            continue

        # Map to bridge ID using partial matching
        # (website uses "Clarence Street Bridge", we use "Clarence St.")
        bridge_id = None
        for name_pattern, bid in BRIDGE_NAME_MAP.items():
            # Use partial matching - if pattern is in the bridge name
            if name_pattern.lower() in bridge_name.lower():
                bridge_id = bid
                break

        if not bridge_id:
            logger.warning(f"Unknown bridge name: {bridge_name} - skipping")
            continue

        # Find the associated body content
        body_div = header.find_parent('div', class_='ea-card')
        if not body_div:
            continue

        body_content = body_div.find('div', class_='ea-body')
        if not body_content:
            continue

        # Extract work description (prefer "Project Type", fallback to "Work Summary")
        description = "Scheduled maintenance"
        for p in body_content.find_all('p'):
            text = p.get_text(strip=True)
            if 'Project Type:' in text:
                description = sanitize_text(text.replace('Project Type:', ''))
                # Clean up common prefix
                if description.startswith('Bridge closure for '):
                    description = description.replace('Bridge closure for ', '')
                break

        # If no Project Type, try Work Summary
        if description == "Scheduled maintenance":
            for p in body_content.find_all('p'):
                text = p.get_text(strip=True)
                if 'Work Summary:' in text:
                    description = sanitize_text(text.replace('Work Summary:', ''))
                    # Truncate if too long (keep first sentence)
                    if '.' in description:
                        description = description.split('.')[0] + '.'
                    break

        # Capitalize first character for consistency
        if description and len(description) > 0:
            description = description[0].upper() + description[1:]

        # Extract all closure information
        periods = []
        full_text = body_content.get_text()

        # Parse full closures
        for match in FULL_CLOSURE_PATTERN.finditer(full_text):
            start_str, end_str = match.groups()
            try:
                # Fix obvious year typos before parsing
                start_str = fix_date_typo(start_str, now)
                end_str = fix_date_typo(end_str, now)

                start_dt = parse_date(start_str).replace(hour=0, minute=0, second=0)
                end_dt = parse_date(end_str).replace(hour=23, minute=59, second=59)

                # Only include if not yet ended
                if end_dt > now:
                    periods.append({
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat()
                    })
                    logger.debug(f"{bridge_name}: Full closure {start_str} to {end_str}")
                else:
                    logger.debug(f"{bridge_name}: Skipping past closure {start_str} to {end_str}")
            except (ValueError, TypeError) as e:
                parse_failures += 1
                logger.warning(f"Failed to parse full closure dates: {e}")

        # Parse daily closures (range)
        for match in DAILY_RANGE_PATTERN.finditer(full_text):
            groups = match.groups()
            start_hour, start_min, start_ampm, end_hour, end_min, end_ampm, start_date_str, end_date_str = groups
            try:
                # Fix obvious year typos before parsing
                start_date_str = fix_date_typo(start_date_str, now)
                end_date_str = fix_date_typo(end_date_str, now)

                # Parse dates as naive datetime objects (no timezone)
                start_date = dateutil_parser.parse(start_date_str).date()
                end_date = dateutil_parser.parse(end_date_str).date()

                # Convert to 24-hour format
                start_hour_24 = convert_12h_to_24h(start_hour, start_ampm)
                end_hour_24 = convert_12h_to_24h(end_hour, end_ampm)
                start_minute = int(start_min) if start_min else 0
                end_minute = int(end_min) if end_min else 0
                if not (0 <= start_minute <= 59) or not (0 <= end_minute <= 59):
                    raise ValueError(f"Invalid minute value: start={start_minute}, end={end_minute}")

                # Check if the last day of closure has passed
                end_time = datetime.strptime(f"{end_hour_24:02d}:{end_minute:02d}", "%H:%M").time()
                end_datetime = TIMEZONE.localize(datetime.combine(end_date, end_time), is_dst=False)

                # Only include if not yet ended
                if end_datetime > now:
                    periods.append({
                        "type": "daily",
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "daily_start_time": f"{start_hour_24:02d}:{start_minute:02d}",
                        "daily_end_time": f"{end_hour_24:02d}:{end_minute:02d}"
                    })
                    logger.debug(f"{bridge_name}: Daily {start_hour}{start_ampm}-{end_hour}{end_ampm} from {start_date_str} to {end_date_str}")
                else:
                    logger.debug(f"{bridge_name}: Skipping past daily closure {start_date_str} to {end_date_str}")
            except (ValueError, TypeError) as e:
                parse_failures += 1
                logger.warning(f"Failed to parse daily range: {e}")

        # Parse daily closures (with "and") - creates TWO separate single-day periods
        for match in DAILY_AND_PATTERN.finditer(full_text):
            groups = match.groups()
            start_hour, start_min, start_ampm, end_hour, end_min, end_ampm, date1_str, date2_str = groups
            try:
                # Fix obvious year typos before parsing
                date1_str = fix_date_typo(date1_str, now)
                date2_str = fix_date_typo(date2_str, now)

                # Parse dates as naive datetime objects (no timezone)
                date1 = dateutil_parser.parse(date1_str).date()
                date2 = dateutil_parser.parse(date2_str).date()

                # Convert to 24-hour format
                start_hour_24 = convert_12h_to_24h(start_hour, start_ampm)
                end_hour_24 = convert_12h_to_24h(end_hour, end_ampm)
                start_minute = int(start_min) if start_min else 0
                end_minute = int(end_min) if end_min else 0
                if not (0 <= start_minute <= 59) or not (0 <= end_minute <= 59):
                    raise ValueError(f"Invalid minute value: start={start_minute}, end={end_minute}")

                end_time = datetime.strptime(f"{end_hour_24:02d}:{end_minute:02d}", "%H:%M").time()

                # "and" means two discrete days, NOT a range - create separate periods
                for single_date in [date1, date2]:
                    end_datetime = TIMEZONE.localize(datetime.combine(single_date, end_time), is_dst=False)

                    # Only include if not yet ended
                    if end_datetime > now:
                        periods.append({
                            "type": "daily",
                            "start_date": single_date.isoformat(),
                            "end_date": single_date.isoformat(),
                            "daily_start_time": f"{start_hour_24:02d}:{start_minute:02d}",
                            "daily_end_time": f"{end_hour_24:02d}:{end_minute:02d}"
                        })
                        logger.debug(f"{bridge_name}: Daily {start_hour}{start_ampm}-{end_hour}{end_ampm} on {single_date}")
                    else:
                        logger.debug(f"{bridge_name}: Skipping past daily closure {single_date}")
            except (ValueError, TypeError) as e:
                parse_failures += 1
                logger.warning(f"Failed to parse daily 'and' pattern: {e}")

        # Parse daily closures (single day)
        for match in DAILY_SINGLE_PATTERN.finditer(full_text):
            groups = match.groups()
            start_hour, start_min, start_ampm, end_hour, end_min, end_ampm, date_str = groups
            try:
                # Fix obvious year typos before parsing
                date_str = fix_date_typo(date_str, now)

                # Parse date as naive datetime object (no timezone)
                single_date = dateutil_parser.parse(date_str).date()

                # Convert to 24-hour format
                start_hour_24 = convert_12h_to_24h(start_hour, start_ampm)
                end_hour_24 = convert_12h_to_24h(end_hour, end_ampm)
                start_minute = int(start_min) if start_min else 0
                end_minute = int(end_min) if end_min else 0
                if not (0 <= start_minute <= 59) or not (0 <= end_minute <= 59):
                    raise ValueError(f"Invalid minute value: start={start_minute}, end={end_minute}")

                # Check if this day has passed
                end_time = datetime.strptime(f"{end_hour_24:02d}:{end_minute:02d}", "%H:%M").time()
                end_datetime = TIMEZONE.localize(datetime.combine(single_date, end_time), is_dst=False)

                # Only include if not yet ended
                if end_datetime > now:
                    periods.append({
                        "type": "daily",
                        "start_date": single_date.isoformat(),
                        "end_date": single_date.isoformat(),
                        "daily_start_time": f"{start_hour_24:02d}:{start_minute:02d}",
                        "daily_end_time": f"{end_hour_24:02d}:{end_minute:02d}"
                    })
                    logger.debug(f"{bridge_name}: Daily {start_hour}{start_ampm}-{end_hour}{end_ampm} on {date_str}")
                else:
                    logger.debug(f"{bridge_name}: Skipping past daily closure {date_str}")
            except (ValueError, TypeError) as e:
                parse_failures += 1
                logger.warning(f"Failed to parse daily single: {e}")

        if periods:
            # Deduplicate periods (multiple regex patterns can match overlapping content)
            seen = set()
            unique_periods = []
            for period in periods:
                if period.get("type") == "daily":
                    key = (period["start_date"], period["end_date"], period["daily_start_time"], period["daily_end_time"])
                else:
                    key = (period["start"], period["end"])
                if key not in seen:
                    seen.add(key)
                    unique_periods.append(period)
            periods = unique_periods

            closures.append({
                "bridge_id": bridge_id,
                "description": description,
                "periods": periods
            })
            logger.info(f"{bridge_id}: {len(periods)} period(s) - {description}")

    # Warn if all parses failed - possible HTML structure change
    if parse_failures > 0 and len(closures) == 0:
        logger.warning(f"All {parse_failures} closure parses failed - possible HTML structure change")

    return closures


def write_maintenance_json(closures: List[Dict], error: Optional[str] = None):
    """
    Write maintenance.json with scraped data or empty on failure.

    Args:
        closures: List of closure dicts
        error: Error message if scraping failed
    """
    now = datetime.now(TIMEZONE)

    data = {
        "source_url": MAINTENANCE_URL,
        "closures": closures
    }

    if error:
        data["last_scrape_attempt"] = now.isoformat()
        data["last_scrape_error"] = error
    else:
        data["last_scrape_success"] = now.isoformat()

    # Atomic write using shared utility
    try:
        dir_path = os.path.dirname(MAINTENANCE_FILE)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        atomic_write_json(MAINTENANCE_FILE, data)
        logger.info(f"Wrote {len(closures)} closure(s) to {MAINTENANCE_FILE}")
    except OSError as e:
        logger.error(f"Failed to write maintenance.json: {e}")


def scrape_maintenance_page():
    """
    Main scraper function - fetches, parses, and writes maintenance data.

    Called by scheduler daily at 6:00 AM (if ENABLE_MAINTENANCE_SCRAPER=true).
    """
    logger.info("Starting maintenance page scrape...")

    # Fetch HTML
    html = fetch_maintenance_page()
    if not html:
        write_maintenance_json([], error="Failed to fetch page")
        return

    # Parse closures
    try:
        closures = extract_closures_from_html(html)
        write_maintenance_json(closures)
        logger.info(f"Maintenance scrape completed: {len(closures)} bridge(s) with closures")
    except Exception as e:
        logger.error(f"Failed to parse maintenance page: {e}")
        write_maintenance_json([], error=f"Parse error: {str(e)}")


if __name__ == "__main__":
    # For manual testing
    scrape_maintenance_page()
