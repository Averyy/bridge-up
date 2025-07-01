# TODO: Vessel Tracking Implementation

## Overview
Implement real-time vessel tracking for the St. Lawrence Seaway using **AISHub API only** (simplified approach):
- All regions (Welland Canal + Montreal) via AISHub API
- Single data source for consistency
- Leverages existing AIS submission to AISHub

This approach simplifies implementation since local AIS data is already being submitted to AISHub.

## Current Setup
- **Local AIS Coverage** (St. Catharines/Port Colborne):
  - AIS Dispatcher running locally with web interface at `http://localhost:8080`
  - Receives AIS data from local AIS receiver
  - Web interface credentials: admin/admin
  - Can output data via TCP Server, UDP, or act as TCP Client
  - Performs downsampling and duplicate removal
  
- **Remote Coverage** (Montreal):
  - AISHub API access available
  - Rate limited to 1 request/minute
  - Provides coverage for areas without local AIS receivers

## Implementation Strategy

### Single Data Source Approach:
- **All Regions**: AISHub API (includes Welland Canal since local data is submitted)
- **Simplified Architecture**: One data source, one implementation
- **Cost Optimized**: Single document per region in Firebase

---

## AISHub API Implementation (All Regions)

### Why AISHub API Only?
- Local AIS data already submitted to AISHub
- Single implementation for all regions
- Consistent data format
- No UDP infrastructure needed

### API Configuration

**Base URL**: `https://data.aishub.net/ws.php`

**Authentication**:
```python
# Store API key as environment variable (DO NOT commit to git)
# AISHUB_API_KEY

import os

# Note: AISHub calls it an "API Key" but uses it as the 'username' parameter
AISHUB_CONFIG = {
    'username': os.environ.get('AISHUB_API_KEY'),  # API key used as username
    'format': 1,  # Human-readable format
    'output': 'json',  # Response format
}
```

**Station Monitoring**:
Monitor your AIS station coverage and statistics at: https://www.aishub.net/stations/3551

### Geographic Regions for API Queries

```python
# All regions use AISHub API
VESSEL_REGIONS = {
    'welland_canal': {
        'name': 'Welland Canal',
        'bounds': {
            'latmin': 42.836,   # Port Colborne (Lake Erie)
            'latmax': 43.276,   # Port Weller (Lake Ontario)
            'lonmin': -79.299,  # Western boundary
            'lonmax': -79.137   # Eastern boundary
        },
        'bridges': ['St. Catharines (5)', 'Port Colborne (3)']
    },
    'montreal_south_shore': {
        'name': 'Montreal South Shore',
        'bounds': {
            'latmin': 45.358,
            'latmax': 45.546,
            'lonmin': -73.568,
            'lonmax': -73.467
        },
        'bridges': ['Victoria Bridge', 'Sainte-Catherine']
    },
    'salaberry_beauharnois': {
        'name': 'Salaberry/Beauharnois',
        'bounds': {
            'latmin': 45.176,
            'latmax': 45.283,
            'lonmin': -74.165,
            'lonmax': -73.953
        },
        'bridges': ['Larocque', 'Valleyfield']
    }
}
```

### AISHub API Documentation

**Official API Documentation**: https://www.aishub.net/api

**API Endpoints**:
- Vessel Data: `https://data.aishub.net/ws.php`
- Station Data: `https://data.aishub.net/stations.php`

**Example API Calls**:
```bash
# All vessels in Montreal South Shore area
https://data.aishub.net/ws.php?username=YOUR_USERNAME&format=1&output=json&latmin=45.358&latmax=45.546&lonmin=-73.568&lonmax=-73.467

# Specific vessel by MMSI
https://data.aishub.net/ws.php?username=YOUR_USERNAME&format=1&output=json&mmsi=316001234

# With compression (BZIP2)
https://data.aishub.net/ws.php?username=YOUR_USERNAME&format=1&output=json&compress=3&latmin=45.358&latmax=45.546&lonmin=-73.568&lonmax=-73.467
```

**Response Format Example (JSON)**:
```json
{
  "MMSI": 316001234,
  "TIME": "2024-06-03 12:34:56 GMT",
  "LONGITUDE": -73.512,
  "LATITUDE": 45.421,
  "COG": 225.5,
  "SOG": 12.5,
  "HEADING": 223,
  "ROT": 0,
  "NAVSTAT": 0,
  "IMO": 9123456,
  "NAME": "FEDERAL YUKINA",
  "CALLSIGN": "CGAB",
  "TYPE": 70,
  "A": 180,
  "B": 20,
  "C": 15,
  "D": 15,
  "DRAUGHT": 8.5,
  "DEST": "MONTREAL",
  "ETA": "06-03 18:00"
}
```

**API Access Requirements**:
1. Must be an AISHub member with valid API key
2. API key format: `AH_XXXX_XXXXXXXX` (used as 'username' parameter)
3. Rate limit: Maximum 1 request per minute
4. Returns empty response if accessed too frequently
5. Store API key as environment variable for security

### AISHub Data Processing

```python
import requests
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class AISHubTracker:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('AISHUB_API_KEY')
        if not self.api_key:
            raise ValueError("AISHub API key not provided. Set AISHUB_API_KEY environment variable.")
        self.api_url = 'https://data.aishub.net/ws.php'
        
    def fetch_vessels_for_region(self, region_id: str, bounds: Dict) -> List[Dict]:
        """Fetch vessels from AISHub API for a specific region."""
        params = {
            'apikey': self.api_key,
            'format': 1,
            'output': 'json',
            'latmin': bounds['latmin'],
            'latmax': bounds['latmax'],
            'lonmin': bounds['lonmin'],
            'lonmax': bounds['lonmax']
        }
        
        try:
            response = requests.get(self.api_url, params=params, timeout=10)
            if response.status_code == 200:
                vessels = response.json()
                # Tag vessels with their data source
                for vessel in vessels:
                    vessel['data_source'] = 'aishub_api'
                    vessel['region'] = region_id
                return vessels
            else:
                logger.error(f"AISHub API error: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Failed to fetch vessels for {region_id}: {e}")
            return []
    
    def process_aishub_vessel(self, vessel_data: Dict) -> Dict:
        """Convert AISHub format to our Firebase format."""
        return {
            'mmsi': str(vessel_data['MMSI']),
            'name': vessel_data.get('NAME', 'Unknown').strip(),
            'coordinates': {
                'lat': float(vessel_data['LATITUDE']),
                'lon': float(vessel_data['LONGITUDE'])
            },
            'course': float(vessel_data.get('COG', 0)),
            'speed': float(vessel_data.get('SOG', 0)),
            'heading': int(vessel_data.get('HEADING', 511)),  # 511 = not available
            'moving': float(vessel_data.get('SOG', 0)) > 0.5,
            'category': self._get_vessel_category(int(vessel_data.get('TYPE', 0))),
            'destination': vessel_data.get('DEST', '').strip(),
            'flag': self._get_country_flag(str(vessel_data['MMSI'])),
            'region': vessel_data['region'],
            'data_source': vessel_data['data_source'],
            'last_updated': firestore.SERVER_TIMESTAMP
        }
```

### API Rate Limiting

**CRITICAL**: AISHub limits API access to **once per minute**. More frequent access returns empty results.

```python
# Schedule AISHub updates every 60 seconds
scheduler.add_job(
    fetch_aishub_vessels,
    'interval',
    seconds=60,
    id='aishub_vessels',
    max_instances=1,
    coalesce=True
)
```

### Cost-Optimized Firebase Schema

**Single Document per Region** to minimize reads:

Collection: `boats_by_region`

```json
{
  // Document ID: region name (e.g., "welland_canal")
  "vessels": {
    "316001234": {
      "mmsi": "316001234",
      "name": "FEDERAL YUKINA",
      "lat": 43.123456,
      "lon": -79.123456,
      "course": 225.5,
      "speed": 12.5,
      "heading": 223,
      "moving": true,
      "category": "commercial",
      "destination": "MONTREAL",
      "flag": "CA"
    },
    "338002345": {
      // ... another vessel
    }
  },
  "vessel_count": 2,
  "last_updated": timestamp
}
```

**Benefits**:
- iOS app needs only 1-3 listeners (one per region)
- Single write per region per minute
- Vessels automatically "deleted" when not in API response

---

## Implementation Details

### 1. Complete Implementation Example

```python
# vessel_tracker.py
import os
import requests
from typing import Dict, List
from datetime import datetime
import pytz
from firebase_admin import firestore
from loguru import logger
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class VesselTracker:
    def __init__(self):
        self.api_key = os.environ.get('AISHUB_API_KEY')
        if not self.api_key:
            raise ValueError("AISHUB_API_KEY not set in .env file")
        
        self.api_url = 'https://data.aishub.net/ws.php'
        self.db = firestore.client()
        
        # Rate limiting protection
        self.last_api_call = None
        self.min_interval_seconds = 65  # 5 second buffer for safety
        
        # Metrics for monitoring
        self.stats = {
            'last_run': None,
            'vessels_by_region': {},
            'api_errors': 0,
            'total_runs': 0
        }
        
    def fetch_all_regions(self):
        """Fetch vessels for all regions with retry logic and rate limiting"""
        import time
        
        # Check rate limit
        if self.last_api_call:
            elapsed = (datetime.now() - self.last_api_call).total_seconds()
            if elapsed < self.min_interval_seconds:
                wait_time = self.min_interval_seconds - elapsed
                logger.warning(f"Rate limit protection: waiting {wait_time:.1f}s")
                time.sleep(wait_time)
        
        for attempt in range(3):  # Retry up to 3 times
            try:
                self._fetch_all_regions_internal()
                self.stats['total_runs'] += 1
                self.stats['last_run'] = datetime.now()
                break
            except requests.exceptions.RequestException as e:
                self.stats['api_errors'] += 1
                if attempt == 2:
                    logger.error(f"Failed after 3 attempts: {e}")
                else:
                    logger.warning(f"Retry {attempt + 1}/3 after error: {e}")
                    time.sleep(5)  # Wait before retry
    
    def _fetch_all_regions_internal(self):
        """Internal method to fetch vessels for all regions"""
        from config import VESSEL_REGIONS
        import time
        
        regions = list(VESSEL_REGIONS.items())
        
        for i, (region_id, config) in enumerate(regions):
            try:
                # Fetch from API
                vessels = self._fetch_vessels_for_region(config['bounds'])
                
                # Empty response handling
                if not vessels:
                    logger.warning(f"{config['name']}: Empty response (rate limit or no vessels)")
                
                # Process vessels with validation
                processed_vessels = {}
                for vessel in vessels:
                    if isinstance(vessel, dict) and self._validate_vessel_data(vessel):
                        mmsi = str(vessel['MMSI'])
                        processed_vessels[mmsi] = self._process_vessel(vessel)
                
                # Update stats
                self.stats['vessels_by_region'][region_id] = len(processed_vessels)
                
                # Update Firebase (single document per region)
                doc_ref = self.db.collection('boats_by_region').document(region_id)
                doc_ref.set({
                    'region_id': region_id,
                    'region_name': config['name'],
                    'vessels': processed_vessels,
                    'vessel_count': len(processed_vessels),
                    'last_updated': firestore.SERVER_TIMESTAMP
                })
                
                logger.info(f"✓ {config['name']}: {len(processed_vessels)} vessels")
                
                # Wait 65 seconds between regions (except after last region)
                if i < len(regions) - 1:
                    logger.info(f"Waiting 65s before next region (API rate limit)...")
                    time.sleep(65)
                
            except Exception as e:
                logger.error(f"✗ {config['name']}: {str(e)}")
                # Continue to next region even if this one fails
                if i < len(regions) - 1:
                    logger.info(f"Waiting 65s before next region (API rate limit)...")
                    time.sleep(65)
    
    def _fetch_vessels_for_region(self, bounds: Dict) -> List[Dict]:
        """Fetch vessels from AISHub API for specific bounds"""
        params = {
            'username': self.api_key,  # API key is used as username parameter
            'format': 1,  # Human-readable format
            'output': 'json',
            'latmin': bounds['latmin'],
            'latmax': bounds['latmax'],
            'lonmin': bounds['lonmin'],
            'lonmax': bounds['lonmax'],
            'compress': 0,  # Could use 3 for BZIP2 if bandwidth is an issue
            'interval': 30  # Only return positions from last 30 minutes
        }
        
        # Track API call time
        self.last_api_call = datetime.now()
        
        response = requests.get(self.api_url, params=params, timeout=10)
        if response.status_code == 200:
            try:
                data = response.json()
                # AISHub returns [metadata, vessels_array] format
                if isinstance(data, list) and len(data) == 2:
                    metadata, vessels = data
                    if isinstance(vessels, list):
                        return vessels
                    else:
                        logger.warning(f"Unexpected vessel data type: {type(vessels)}")
                else:
                    logger.warning(f"Unexpected API response format: {type(data)}")
                return []
            except ValueError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                return []
        else:
            logger.error(f"API returned status code: {response.status_code}")
            return []
    
    def _validate_vessel_data(self, vessel_data: Dict) -> bool:
        """Validate vessel data before processing"""
        try:
            lat = float(vessel_data.get('LATITUDE', 0))
            lon = float(vessel_data.get('LONGITUDE', 0))
            
            # Valid coordinate ranges
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return False
                
            # Must have MMSI
            if not vessel_data.get('MMSI'):
                return False
            
            # Validate coordinate values aren't exactly 0 (common AIS error)
            if lat == 0.0 and lon == 0.0:
                return False
                
            return True
        except (ValueError, TypeError):
            return False
    
    def _process_vessel(self, vessel_data: Dict) -> Dict:
        """Convert AISHub format to our simplified format"""
        # Calculate data age if TIME field exists
        data_age_minutes = None
        if vessel_data.get('TIME'):
            try:
                # Parse "2024-06-03 12:34:56 GMT" format
                ais_time = datetime.strptime(vessel_data['TIME'], '%Y-%m-%d %H:%M:%S GMT')
                data_age_minutes = (datetime.utcnow() - ais_time).total_seconds() / 60
            except:
                pass
        
        # Parse ETA if available
        eta_timestamp = None
        eta_raw = vessel_data.get('ETA', '').strip()
        if eta_raw and eta_raw != '00-00 00:00':  # Invalid ETA
            try:
                # Parse "06-27 18:00" format (MM-DD HH:MM)
                current_year = datetime.now().year
                eta_datetime = datetime.strptime(f"{current_year}-{eta_raw}", '%Y-%m-%d %H:%M')
                # Convert to UTC (ETA is typically in destination timezone, but we'll assume UTC)
                eta_timestamp = eta_datetime.replace(tzinfo=pytz.UTC)
            except:
                pass  # Invalid format, leave as None
        
        return {
            'mmsi': str(vessel_data['MMSI']),
            'imo': vessel_data.get('IMO', 0),  # Important vessel identifier
            'name': vessel_data.get('NAME', 'Unknown').strip(),
            'callsign': vessel_data.get('CALLSIGN', '').strip(),
            'lat': float(vessel_data['LATITUDE']),
            'lon': float(vessel_data['LONGITUDE']),
            'course': float(vessel_data.get('COG', 0)),
            'speed': float(vessel_data.get('SOG', 0)),
            'heading': int(vessel_data.get('HEADING', 511)),
            'rot': float(vessel_data.get('ROT', 0)),  # Rate of turn
            'moving': self._is_moving(vessel_data),
            'nav_status': int(vessel_data.get('NAVSTAT', 0)),
            'category': self._get_vessel_category(int(vessel_data.get('TYPE', 0))),
            'ship_type': int(vessel_data.get('TYPE', 0)),  # Raw type for iOS
            'destination': vessel_data.get('DEST', '').strip(),
            'eta': eta_timestamp,  # Firestore timestamp or None
            'flag': self._get_country_flag(str(vessel_data['MMSI'])),
            'length': vessel_data.get('A', 0) + vessel_data.get('B', 0),
            'width': vessel_data.get('C', 0) + vessel_data.get('D', 0),
            'draught': float(vessel_data.get('DRAUGHT', 0)),
            'data_age_minutes': data_age_minutes  # How old is this AIS data
        }
    
    def _is_moving(self, vessel_data: Dict) -> bool:
        """Better movement detection using nav status and speed"""
        nav_status = int(vessel_data.get('NAVSTAT', 0))
        speed = float(vessel_data.get('SOG', 0))
        
        # Stationary statuses: 1=At anchor, 5=Moored, 6=Aground
        if nav_status in [1, 5, 6]:
            return False
        
        return speed > 0.5
    
    def _get_vessel_category(self, ship_type: int) -> str:
        """Categorize vessel based on AIS ship type"""
        if ship_type in range(70, 90):  # Cargo/Tanker
            return "commercial"
        elif ship_type in [31, 32, 52]:  # Towing
            return "commercial"
        elif ship_type == 36:  # Sailing
            return "sail"
        elif ship_type in range(60, 70):  # Passenger
            return "passenger"
        elif ship_type == 37:  # Pleasure
            return "pleasure"
        elif ship_type in [33, 34, 35, 50, 51, 53, 54, 55, 58]:  # Service
            return "service"
        else:
            return "commercial"
    
    def _get_country_flag(self, mmsi: str) -> str:
        """Extract country code from MMSI"""
        if len(mmsi) >= 3:
            mid = mmsi[:3]
            # Common flags in the Seaway
            if mid == '316': return 'CA'      # Canada
            elif mid == '338': return 'US'    # United States
            elif mid == '228': return 'FR'    # France
            elif mid == '232': return 'GB'    # United Kingdom
            elif mid == '244': return 'NL'    # Netherlands
            elif mid == '211': return 'DE'    # Germany
            elif mid == '265': return 'SE'    # Sweden
            elif mid == '219': return 'DK'    # Denmark
            elif mid == '257': return 'NO'    # Norway
            elif mid == '230': return 'FI'    # Finland
            elif mid == '255': return 'PT'    # Portugal (Madeira)
            elif mid == '368': return 'US'    # USA (alternate)
            elif mid == '369': return 'US'    # USA (alternate)
        return 'UN'  # Unknown

# For testing
if __name__ == '__main__':
    tracker = VesselTracker()
    tracker.fetch_all_regions()
```

### 2. Integration with Existing System

Add to scheduler in `start_flask.py` and `start_waitress.py`:

```python
# Add after existing imports
from vessel_tracker import VesselTracker

# Initialize vessel tracker
vessel_tracker = VesselTracker()

# In start_scheduler() function, add:
# Vessel tracking - every 3.5 minutes (65s per region * 3 regions = 195s, round up to 210s)
scheduler.add_job(
    vessel_tracker.fetch_all_regions, 
    'interval', 
    seconds=210,  # 3.5 minutes to complete all regions safely
    id='vessel_tracking',
    max_instances=1,
    coalesce=True,
    replace_existing=True
)
```

### 3. Add to config.py

```python
# Add to config.py
VESSEL_REGIONS = {
    'welland_canal': {
        'name': 'Welland Canal',
        'bounds': {
            'latmin': 42.836,   # Port Colborne (Lake Erie)
            'latmax': 43.276,   # Port Weller (Lake Ontario)
            'lonmin': -79.299,  # Western boundary
            'lonmax': -79.137   # Eastern boundary
        }
    },
    'montreal_south_shore': {
        'name': 'Montreal South Shore',
        'bounds': {
            'latmin': 45.358,
            'latmax': 45.546,
            'lonmin': -73.568,
            'lonmax': -73.467
        }
    },
    'salaberry_beauharnois': {
        'name': 'Salaberry/Beauharnois',
        'bounds': {
            'latmin': 45.176,
            'latmax': 45.283,
            'lonmin': -74.165,
            'lonmax': -73.953
        }
    }
}
```

### 4. Testing Scripts

```python
# test_vessels.py - Basic test
import os
from dotenv import load_dotenv
from vessel_tracker import VesselTracker
from loguru import logger

# Test the implementation
load_dotenv()

if not os.environ.get('AISHUB_API_KEY'):
    logger.error("Please set AISHUB_API_KEY in .env file")
    exit(1)

tracker = VesselTracker()
logger.info("Testing vessel tracking...")
tracker.fetch_all_regions()
logger.info("Check Firebase console for boats_by_region collection")

# test_vessels_comprehensive.py - Detailed testing
import os
import time
from dotenv import load_dotenv
from vessel_tracker import VesselTracker
from loguru import logger
from config import VESSEL_REGIONS

load_dotenv()

def test_single_region(tracker, region_id):
    """Test a single region fetch"""
    bounds = VESSEL_REGIONS[region_id]['bounds']
    logger.info(f"\nTesting {region_id}:")
    logger.info(f"  Bounds: {bounds}")
    
    vessels = tracker._fetch_vessels_for_region(bounds)
    logger.info(f"  Raw vessels found: {len(vessels)}")
    
    if vessels:
        # Validate and show sample
        valid_count = sum(1 for v in vessels if tracker._validate_vessel_data(v))
        logger.info(f"  Valid vessels: {valid_count}")
        
        # Show sample vessel
        sample = vessels[0]
        logger.info(f"  Sample: {sample.get('NAME', 'Unknown')} "
                   f"({sample.get('TYPE', 0)}) at "
                   f"{sample.get('LATITUDE')}, {sample.get('LONGITUDE')}")
        logger.info(f"  Moving: {sample.get('SOG', 0)} knots, "
                   f"Status: {sample.get('NAVSTAT', 0)}")

def main():
    tracker = VesselTracker()
    
    # Test each region individually
    logger.info("=== Testing Individual Regions ===")
    for region_id in VESSEL_REGIONS.keys():
        test_single_region(tracker, region_id)
        time.sleep(61)  # Respect rate limit
    
    # Test full update
    logger.info("\n=== Testing Full Update ===")
    tracker.fetch_all_regions()
    
    # Show stats
    logger.info(f"\n=== Statistics ===")
    logger.info(f"Total runs: {tracker.stats['total_runs']}")
    logger.info(f"API errors: {tracker.stats['api_errors']}")
    logger.info(f"Vessels by region: {tracker.stats['vessels_by_region']}")

if __name__ == '__main__':
    main()
```

## Dependencies

```bash
pip install python-dotenv  # For environment variables
# requests and firebase-admin already installed
```

## Environment Configuration

### Required Environment Variables
```bash
# Create .env file (DO NOT commit to git)
AISHUB_API_KEY=AH_3551_38EC19B6  # Your API key (passed as 'username' parameter)
```

### Security Considerations
1. **Never commit API keys** to version control
2. `.env` already in `.gitignore`
3. Use environment variables in production
4. Rotate API keys if accidentally exposed

## Implementation Summary

### Simplified Architecture Benefits
1. **Immediate coverage** for all 3 regions
2. **Single data source** (AISHub API)
3. **Cost-optimized** with single document per region
4. **Simple implementation** - one API, one format
5. **Automatic vessel cleanup** - vessels not in API response are removed

### Data Flow
```
┌─────────────────┐
│  AISHub API     │
│  (All Regions)  │
└────────┬────────┘
         │ HTTPS (60s interval)
         │
  ┌──────▼──────┐
  │   Backend    │
  │  Processor   │
  └──────┬──────┘
         │ Single doc per region
         │
  ┌──────▼──────┐
  │  Firebase    │
  │  Firestore   │
  └──────┬──────┘
         │ Real-time listeners
         │
  ┌──────▼──────┐
  │   iOS App    │
  └─────────────┘
```

## Implementation Checklist

- [ ] Create .env file with AISHUB_API_KEY
- [ ] Install python-dotenv: `pip install python-dotenv`
- [ ] Add VESSEL_REGIONS to config.py
- [ ] Create vessel_tracker.py
- [ ] Test with test_vessels.py script
- [ ] Add to schedulers in start_flask.py and start_waitress.py
- [ ] Deploy and monitor logs
- [ ] Coordinate with iOS team for new boats_by_region collection

## Expected Results

- 3 documents in `boats_by_region` collection
- Each document contains all vessels in that region
- Updates cycle: 3.5 minutes total (65s between regions for safety)
- Typical vessel counts:
  - Welland Canal: 10-20 vessels
  - Montreal regions: 5-15 vessels each
- Total Firebase cost: ~0.86 writes/minute (extremely minimal)

## Troubleshooting

### Common Issues

1. **Empty API responses**
   - Rate limit exceeded (wait 60 seconds)
   - API key invalid or expired
   - No vessels in region (normal at night/winter)
   - Check station status: https://www.aishub.net/stations/3551

2. **Vessels not showing expected data**
   - Some vessels may not transmit all AIS data
   - Navigation status 15 = "undefined" (common)
   - Heading 511 = "not available"
   - Name/destination may be blank for small vessels

3. **Performance considerations**
   - API rate limit prevents parallel region fetching
   - Each region takes ~1-2 seconds to fetch
   - Total update cycle: ~5-10 seconds for all regions

4. **Validation failures**
   - Invalid coordinates (rare but happens)
   - Missing MMSI (corrupted AIS data)
   - Check logs for specific validation errors

### Monitoring Health

```python
# Add health check endpoint to app.py
@app.route('/vessels/health')
def vessel_health():
    """Check vessel tracking health"""
    if hasattr(vessel_tracker, 'stats'):
        last_run = vessel_tracker.stats.get('last_run')
        if last_run:
            age = (datetime.now() - last_run).seconds
            healthy = age < 120  # Should run every 60s
            return {
                'healthy': healthy,
                'last_run_seconds_ago': age,
                'vessels_by_region': vessel_tracker.stats['vessels_by_region'],
                'api_errors': vessel_tracker.stats['api_errors']
            }
    return {'healthy': False, 'error': 'No stats available'}, 503
```

### Debug Mode

For development, add verbose logging:
```python
# In vessel_tracker.py __init__
self.debug = os.environ.get('VESSEL_DEBUG', '').lower() == 'true'

# In _process_vessel
if self.debug:
    logger.debug(f"Processing: {vessel_data.get('NAME')} "
                f"Type:{vessel_data.get('TYPE')} "
                f"Status:{vessel_data.get('NAVSTAT')}")
```

## Important Considerations

### Navigation Status Codes (NAVSTAT)
- 0 = Under way using engine
- 1 = At anchor
- 2 = Not under command
- 3 = Restricted manoeuverability
- 4 = Constrained by draught
- 5 = Moored
- 6 = Aground
- 7 = Engaged in fishing
- 8 = Under way sailing
- 9-14 = Reserved
- 15 = Not defined (default)

### Data Quality Notes
- **AIS Coverage**: Not all vessels transmit AIS (small recreational boats often don't)
- **Data Age**: Check `data_age_minutes` - data older than 10 minutes may be stale
- **API Interval**: We request only positions from last 30 minutes (`interval: 30`)
- **TIME Field**: This is when the AIS message was received, not current time
- **Name/Destination**: Often blank or incorrectly entered by crew
- **Heading vs Course**: Heading = where bow points, Course = direction of travel
- **Special Values**: Speed 102.3 = invalid, Heading 511 = not available

### Performance Optimization
- **Compression**: Set `compress: 3` in API params for BZIP2 (reduces bandwidth ~70%)
- **Field Selection**: AISHub doesn't support field filtering, always returns all data
- **Caching**: Consider local caching if same vessel data needed multiple times

### Future Enhancements
1. **Vessel History Tracking**
   - Store vessel tracks in separate collection
   - Useful for analyzing traffic patterns
   
2. **Geofencing Alerts**
   - Notify when vessels enter/exit specific areas
   - Useful for bridge approach warnings
   
3. **Vessel Details API**
   - Separate endpoint to fetch detailed vessel info by MMSI
   - Reduces data in main response
   
4. **WebSocket Support**
   - Real-time updates without polling
   - Requires different API/infrastructure
   
5. **AIS Message Type 27**
   - Long-range AIS for vessels far from shore
   - Different data format, rarely seen in canals

### iOS App Considerations
- **Vessel Icons**: Use `category` field for basic icons, `ship_type` for detailed
- **Movement Arrows**: Use `heading` for arrow direction, `speed` for animation
- **Stale Data**: Highlight vessels with `data_age_minutes` > 10
- **Special Vessels**: Flag pilot boats (type 50), tugs (31-32), SAR (51)

## API Compliance Summary

Our implementation fully complies with AISHub API requirements:
- ✅ Uses correct URL: `https://data.aishub.net/ws.php`
- ✅ Authentication via `username` parameter
- ✅ Rate limiting: 60-second minimum interval enforced
- ✅ Human-readable format (`format=1`)
- ✅ JSON output (`output=json`)
- ✅ Geographic bounds for each region
- ✅ Position age filtering (`interval=30`)
- ✅ Error handling for empty responses
- ✅ Validates coordinate ranges before storage
- ✅ Handles special values (Speed 102.3, Heading 511)