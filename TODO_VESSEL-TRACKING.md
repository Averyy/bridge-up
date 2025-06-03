# TODO: Vessel Tracking Implementation

## Overview
Implement real-time vessel tracking for the St. Lawrence Seaway using a **hybrid approach**:
- **Phase 1**: AISHub API for Montreal region (proof of concept, remote coverage)
- **Phase 2**: UDP AIS Dispatcher for Welland Canal (leveraging local AIS infrastructure)

This hybrid approach allows immediate implementation for remote regions while utilizing existing local AIS receivers for better real-time data where available.

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

### Region-Specific Data Sources:
- **Welland Canal** (St. Catharines + Port Colborne): UDP from local AIS Dispatcher
- **Montreal** (South Shore + Salaberry/Beauharnois): AISHub API

This allows leveraging local infrastructure where available while using API for remote coverage.

---

## Phase 1: AISHub API Implementation (Montreal Region)

### Why Start with AISHub API?
- Immediate proof of concept without infrastructure setup
- Test vessel tracking features and Firebase integration
- Provides coverage for Montreal where no local AIS receiver exists
- Simpler implementation to validate the concept

### API Configuration

**Base URL**: `https://data.aishub.net/ws.php`

**Authentication**:
```python
# Store API key as environment variable (DO NOT commit to git)
# Add to .env file or set in environment:
# AISHUB_API_KEY=AH_3551_38EC19B6

import os

AISHUB_CONFIG = {
    'apikey': os.environ.get('AISHUB_API_KEY'),  # Required for authentication
    'format': 1,  # Human-readable format
    'output': 'json',  # Response format
}
```

**Station Monitoring**:
Monitor your AIS station coverage and statistics at: https://www.aishub.net/stations/3551

### Geographic Regions for API Queries

```python
# Only Montreal regions use AISHub API
AISHUB_REGIONS = {
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
https://data.aishub.net/ws.php?apikey=YOUR_API_KEY&format=1&output=json&latmin=45.358&latmax=45.546&lonmin=-73.568&lonmax=-73.467

# Specific vessel by MMSI
https://data.aishub.net/ws.php?apikey=YOUR_API_KEY&format=1&output=json&mmsi=316001234

# With compression (BZIP2)
https://data.aishub.net/ws.php?apikey=YOUR_API_KEY&format=1&output=json&compress=3&latmin=45.358&latmax=45.546&lonmin=-73.568&lonmax=-73.467
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
2. API key format: `AH_XXXX_XXXXXXXX`
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

---

## Phase 2: UDP AIS Dispatcher Implementation (Welland Canal)

### 1. Connect to Local AIS Dispatcher

**Architecture**: UDP Push from AIS Dispatcher to backend domain

**Multi-Location Setup**:
```python
# Backend UDP listeners
AIS_SOURCES = {
    9999: {"name": "Welland Canal", "location": "St. Catharines area"},
    9998: {"name": "Montreal", "location": "Montreal/South Shore"},
    # Future: Add more ports for additional locations
}
```

**AIS Dispatcher Configuration** (per location):
1. **Output Configuration**:
   - Add UDP destination: `ais.bridgeup.app:9999` (different port per location)
   - Click "Add" and "Save" in web interface
   
2. **Settings Panel**:
   - ✅ Enabled: ON
   - Downsampling: 60 seconds (recommended)
   - ✅ Duplicates removal: ON
   - ✅ Tag: ON (helps identify source)
   - ❌ Non-VDM: OFF

**Current Device Settings (for reference)**:
```
Station Location: 43.1451°N, -79.2102°W (St. Catharines area)
Inactivity Timeout: 300s
Reconnect Timeout: 60s
Downsampling Time: 10s (consider increasing to 60s)
Duplicates Removal: ON ✓
NMEA Tags: OFF (consider enabling for source identification)
Non-VDM: OFF ✓
``` 

**Backend UDP Listener**:
```python
import socket
import threading

def listen_udp_port(port: int, source_name: str):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', port))
    
    while True:
        data, addr = sock.recvfrom(4096)
        nmea_sentences = data.decode('utf-8').strip().split('\r\n')
        for sentence in nmea_sentences:
            process_nmea(sentence, source_name)

# Start listeners for each location
for port, config in AIS_SOURCES.items():
    thread = threading.Thread(
        target=listen_udp_port, 
        args=(port, config['name'])
    )
    thread.daemon = True
    thread.start()
```

### 2. Geographic Region for UDP Coverage

**UDP Coverage Region** (only Welland Canal uses UDP):

```python
UDP_REGIONS = {
    'welland_canal': {
        'name': 'Welland Canal',
        'description': 'Complete canal from Lake Ontario to Lake Erie',
        'bounds': {
            'min_lat': 42.836,   # Port Colborne (Lake Erie)
            'max_lat': 43.276,   # Port Weller (Lake Ontario)
            'min_lon': -79.299,  # Western boundary
            'max_lon': -79.137   # Eastern boundary
        },
        'bridges': 8  # St. Catharines (5) + Port Colborne (3)
    }
    # Montreal regions use AISHub API instead of UDP
}
```

**UDP Implementation Details**:
- Single UDP port (9999) for Welland Canal AIS data
- Real-time updates with configurable downsampling
- Direct feed from local AIS receiver

### 3. Firebase Schema
Create new collection: `boats`

Document structure (use MMSI as document ID since all boats will have it and its unique):
```json
{
  "mmsi": "316001234",              // Maritime Mobile Service Identity
  "name": "FEDERAL YUKINA",         // Vessel name
  "coordinates": GeoPoint,          // Firebase GeoPoint
    "lat": 43.123456,               // Latitude (decimal degrees)
    "lon": -79.123456,              // Longitude (decimal degrees)
  "course": 225.5,                  // Course over ground (degrees) direction of movement
  "speed": 12.5,                    // Speed over ground (knots)
  "moving": true,                   // Boolean: true if speed > 0.5 knots, false if stopped
  "category": "commercial",         // "commercial", "sail", "passenger", "pleasure", "service"
  "destination": "MONTREAL",        // Destination port
  "flag": "CA",                     // Country flag (derived from MMSI)
  "region": "welland_canal",        // Region ID for filtering
  "last_updated": timestamp         // Firebase server timestamp
}
```

### 4. AIS Message Types to Process
- **Types 1,2,3**: Position reports (lat/lon, speed, course, heading, status)
- **Type 5**: Static vessel data (name, callsign, IMO, ship type, destination)
- **Type 4**: Base station report (for fixed objects)

### 5. Data Processing Requirements
- Update vessels only when position/data changes (minimize Firebase writes)
- **DELETE vessels from Firestore after 10 minutes of no updates** (only track currently visible ships)
- Handle partial data (not all fields always available)
- Derive country flag from MMSI (first 3 digits = MID)

### 6. Implementation Notes

**NMEA Parsing**:
- Use `pyais` library for reliable AIS decoding
- Handle multi-part messages (some AIS messages span multiple sentences)
- Validate checksums

**Firebase Update Strategy - CRITICAL FOR COST SAVINGS**:
```python
# Backend accumulates vessel updates in memory
vessel_cache = {}  # MMSI -> vessel data

# Every 60 seconds, batch update ALL vessels at once
def batch_update_firebase():
    batch = db.batch()
    
    for mmsi, vessel_data in vessel_cache.items():
        vessel_ref = db.collection('boats').document(mmsi)
        batch.set(vessel_ref, vessel_data, merge=True)
    
    batch.commit()  # Single write operation
    
# Schedule batch updates
scheduler.add_job(batch_update_firebase, 'interval', seconds=60)
```

**Cost Impact**:
- Without batching: 60 vessels × 60 updates/hour = 3,600 writes/hour
- With batching: 60 vessels × 1 batch/minute = 60 writes/hour
- **60x reduction in Firebase writes!**

**Implementation Details**:
- Backend receives continuous UDP stream from AIS Dispatcher
- Updates kept in memory cache (not Firebase)
- Every 60 seconds: batch write ALL vessels to Firebase
- Only include vessels that have been updated since last batch
- **DELETE vessels from Firestore** that haven't been seen for 10+ minutes
- **Assign region ID** based on vessel coordinates for iOS filtering

**Vessel Cleanup Strategy**:
```python
def batch_update_firebase():
    batch = db.batch()
    current_time = time.time()
    
    # Update active vessels
    for mmsi, vessel_data in vessel_cache.items():
        if current_time - vessel_data['last_seen'] < 600:  # 10 minutes
            vessel_ref = db.collection('boats').document(mmsi)
            batch.set(vessel_ref, vessel_data, merge=True)
    
    # Delete stale vessels
    all_vessels = db.collection('boats').stream()
    for vessel in all_vessels:
        if vessel.id not in vessel_cache or \
           current_time - vessel_cache[vessel.id]['last_seen'] >= 600:
            batch.delete(vessel.reference)
    
    batch.commit()
```

**Error Handling**:
- Connection failures to AIS Dispatcher
- Malformed NMEA sentences
- Firebase quota limits
- Invalid position data (lat=91, lon=181)

### 7. Expected Vessel Traffic in Welland Canal

**Typical vessels**:
- Lakers (bulk carriers) - 600-740 feet
- Salties (ocean vessels) - up to 740 feet  
- Tugboats and service vessels
- Recreational boats (summer months)

**Traffic volume**:
- ~3,000 vessel transits per year
- ~10-20 vessels in canal at any time
- Peak season: April-December
- 24/7 operations

### 8. Testing Approach
1. Verify AIS Dispatcher connection and data flow
2. Monitor actual vessel count in Welland Canal bounds
3. Test NMEA parsing with sample sentences
4. Confirm geographic filtering works correctly
5. Validate Firebase writes and updates
6. Check vessel cleanup after timeout
7. Verify vessel appears on iOS app map

### 9. Multi-Location Considerations

**Source Identification**:
- Use different UDP ports per location
- Store source metadata with vessel data
- Consider adding 'source' field to Firebase documents

**Coverage Areas** (future phases):
- Phase 1: Welland Canal (Port Colborne to St. Catharines)
- Phase 2: Montreal/South Shore bridges
- Phase 3: Additional Seaway locations

**Network Requirements**:
- Backend domain: e.g., `ais.bridgeup.app`
- Open UDP ports: 9998-9999 (more as needed)
- Firewall: Allow inbound UDP on these ports
- Bandwidth: ~10KB/min per location (with 60s downsampling)
- Monitor for packet loss

**Security Considerations**:
- AIS data is public (not sensitive)
- Validate packet format before parsing
- Rate limit per source IP
- Log source IPs for monitoring
- Consider IP allowlist if locations are static

### 10. Integration with Existing System
- Run as separate process/thread alongside bridge scraper
- Use same Firebase initialization as `scraper.py`
- Follow existing logging patterns
- Add to scheduler if periodic cleanup needed

### 9. Vessel Tracking Feature Requirements

**Backend Implementation**:
- Add `region` field to each vessel document based on coordinates
- Region determines which vessels are visible to users
- Vessels only stored if they fall within defined region boundaries

**Region Assignment Logic**:
- Check vessel lat/lon against each region's bounds
- Assign appropriate region ID: `welland_canal`, `montreal_south_shore`, or `salaberry_beauharnois`
- Vessels outside all regions are not stored in Firebase

**Client Filtering Strategy**:
- Clients query vessels by region field
- Only regions with enabled bridges should have listeners
- Reduces unnecessary data transfer and costs

### 10. Country Flag Mapping (MID to ISO)
MMSI starts with 3-digit Maritime Identification Digits (MID):
- 316: Canada (CA)
- 338: United States (US)
- 228: France (FR)
- etc. (full list: https://www.itu.int/en/ITU-R/terrestrial/fmd/Pages/mid.aspx)

### 11. Vessel Type Classification

**Text Labels for iOS App** (based on AIS ship type codes):
```python
def get_vessel_category(ship_type: int) -> str:
    """Returns vessel category label for iOS app to handle display."""
    
    # Commercial vessels (majority of canal traffic)
    if ship_type in range(70, 90):  # Cargo (70-79) and Tanker (80-89)
        return "commercial"
    
    # Towing/tug operations
    elif ship_type in [31, 32, 52]:
        return "commercial"  # Tugs are commercial operations
    
    # Sailing vessels
    elif ship_type == 36:
        return "sail"
    
    # Passenger vessels (commercial passenger operations)
    elif ship_type in range(60, 70):
        return "passenger"
    
    # Pleasure/recreational craft
    elif ship_type == 37:
        return "pleasure"
    
    # Fishing (commercial)
    elif ship_type == 30:
        return "commercial"
    
    # Service/government vessels
    elif ship_type in [33, 34, 35, 50, 51, 53, 54, 55, 58]:
        return "service"
    
    # Unknown/other
    else:
        return "commercial"
```

**Movement Status** (from navigation status and speed):
```python
def is_moving(nav_status: int, speed: float) -> bool:
    """Determines if vessel is moving based on AIS data."""
    
    # Definitely not moving if anchored, moored, or aground
    if nav_status in [1, 5, 6]:  # At anchor, moored, aground
        return False
    
    # Moving if speed is above threshold (0.5 knots)
    return speed > 0.5
```


## Architecture Decision: UDP Push Approach

**Why UDP Push is Optimal**:

1. **Native AIS Dispatcher Support**: Built-in UDP output, no custom code needed
2. **Multiple Locations**: Each location pushes to different port on backend domain
3. **Automatic Handling**: AIS Dispatcher manages:
   - Downsampling (60s = 10x data reduction)
   - Duplicate removal
   - CRC validation
   - Connection persistence

4. **Cost Optimization**:
   - Raw AIS: ~300 updates/vessel/hour
   - AIS Dispatcher downsampling: ~60 updates/vessel/hour (5x reduction)
   - Backend batch updates: 1 write/vessel/minute (60x reduction)
   - **Combined: 300x fewer Firebase writes!**

5. **Simple Deployment**:
   - Just configure domain:port in AIS Dispatcher web UI
   - No VPN, no port forwarding at remote sites
   - Works over cellular/home networks

## Sample AIS Data
```
!AIVDM,1,1,,B,133w;`PP00PCqghMcje0h4pP06mf,0*65
!AIVDM,2,1,3,B,533w;`02>05h961O80pTpN1T@Tr2222222220O2@73360Ht50000000000,0*5C
!AIVDM,2,2,3,B,00000000000,2*27
```

Download full sample (85K messages): https://www.aishub.net/downloads/raw-ais-sample.zip

## Dependencies

### Phase 1 (AISHub API)
```bash
pip install python-dotenv requests
```

### Phase 2 (UDP AIS Dispatcher)
```bash
pip install pyais
```

### Both Phases
```bash
# Already installed in project
pip install firebase-admin
```

## References
- AIS Dispatcher docs: https://www.aishub.net/ais-dispatcher
- NMEA AIS format: https://gpsd.gitlab.io/gpsd/AIVDM.html
- pyais library: https://github.com/M0r13n/pyais
- Ship type codes: https://api.vtexplorer.com/docs/ref-aistypes.html
- Navigation status codes: https://api.vtexplorer.com/docs/ref-navstat.html

## Environment Configuration

### Required Environment Variables
```bash
# Create .env file (DO NOT commit to git)
AISHUB_API_KEY=AH_3551_38EC19B6  # Your AISHub API key

# Or export in shell
export AISHUB_API_KEY=AH_3551_38EC19B6
```

### Security Considerations
1. **Never commit API keys** to version control
2. Add `.env` to `.gitignore` if using dotenv
3. Use environment variables or secret management in production
4. Rotate API keys if accidentally exposed

### Loading Environment Variables

**Option 1: Using python-dotenv (Recommended)**
```bash
# Install python-dotenv
pip install python-dotenv
```

```python
# In your Python code
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Access the API key
api_key = os.environ.get('AISHUB_API_KEY')
```

**Option 2: Manual export**
```bash
# Export in terminal before running script
export AISHUB_API_KEY=AH_3551_38EC19B6
python vessel_tracker.py
```

### Testing API Access
```python
# Test script to verify AISHub API access
import os
import requests
from dotenv import load_dotenv

# Load .env file
load_dotenv()

api_key = os.environ.get('AISHUB_API_KEY')
if not api_key:
    print("Error: AISHUB_API_KEY not set")
    print("Make sure .env file exists or environment variable is exported")
    exit(1)

# Test API call for Montreal area
url = 'https://data.aishub.net/ws.php'
params = {
    'apikey': api_key,
    'format': 1,
    'output': 'json',
    'latmin': 45.4,
    'latmax': 45.5,
    'lonmin': -73.6,
    'lonmax': -73.5
}

response = requests.get(url, params=params)
print(f"Status: {response.status_code}")
print(f"Vessels found: {len(response.json()) if response.status_code == 200 else 0}")
```

## Implementation Summary

### Hybrid Approach Benefits
1. **Immediate Montreal coverage** via AISHub API (Phase 1)
2. **Superior Welland Canal data** via local AIS (Phase 2)
3. **Unified Firebase schema** works with both data sources
4. **Cost-optimized** with 60-second batch updates
5. **Flexible architecture** allows adding more regions/sources

### Data Flow Architecture
```
┌─────────────────┐     ┌─────────────────┐
│  AISHub API     │     │ Local AIS       │
│  (Montreal)     │     │ (Welland Canal) │
└────────┬────────┘     └────────┬────────┘
         │                       │
         │ HTTPS                 │ UDP
         │                       │
         └───────────┬───────────┘
                     │
              ┌──────▼──────┐
              │   Backend    │
              │  Processor   │
              └──────┬──────┘
                     │
                     │ Batch Updates
                     │ (60 seconds)
                     │
              ┌──────▼──────┐
              │  Firebase    │
              │  Firestore   │
              └──────┬──────┘
                     │
                     │ Real-time
                     │
              ┌──────▼──────┐
              │   iOS App    │
              │    Users     │
              └─────────────┘
```

## Prerequisites Checklist

### Phase 1 (AISHub API - Montreal)
- [x] Create .env file with AISHUB_API_KEY
- [ ] Install python-dotenv: `pip install python-dotenv`
- [ ] Test API access with sample script
- [ ] Verify Montreal region coverage
- [ ] Implement AISHubTracker class
- [ ] Set up 60-second scheduled updates

### Phase 2 (UDP AIS Dispatcher - Welland Canal)
- [ ] Set up domain: `ais.bridgeup.app` → CNAME → `ddns.averyy.ca` (Cloudflare proxy OFF)
- [ ] Open inbound UDP ports on server for bridge up 192.168.2.126:9998-9999
- [ ] Configure AIS Dispatcher to send to `ais.bridgeup.app:9999`
- [ ] Test UDP connectivity: `nc -u -l 9999` on server, send test packet