# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# JSON API Endpoints (loaded from .env)
OLD_JSON_ENDPOINT = os.getenv('OLD_JSON_ENDPOINT')
NEW_JSON_ENDPOINT = os.getenv('NEW_JSON_ENDPOINT')

if not OLD_JSON_ENDPOINT or not NEW_JSON_ENDPOINT:
    raise ValueError("JSON endpoints not configured in .env file. See .env.example for required variables.")

# Bridge keys and metadata (safe to commit - no URLs!)
BRIDGE_KEYS = {
    'BridgeSCT': {
        'region': 'St Catharines',
        'shortform': 'SCT'
    },
    'BridgePC': {
        'region': 'Port Colborne',
        'shortform': 'PC'
    },
    'BridgeM': {
        'region': 'Montreal South Shore',
        'shortform': 'MSS'
    },
    'BridgeK': {
        'region': 'Kahnawake',
        'shortform': 'K'
    },
    'BridgeSBS': {
        'region': 'Salaberry / Beauharnois / Suroît Region',
        'shortform': 'SBS'
    }
}

BRIDGE_DETAILS = {
    'St Catharines': {
        'Lakeshore Rd': {'lat': 43.21617521494522, 'lng': -79.21223177177772, 'number': '1'},
        'Carlton St.': {'lat': 43.19185980424842, 'lng': -79.20100809118367, 'number': '3A'},
        'Queenston St.': {'lat': 43.165824700918485, 'lng': -79.19492604380804, 'number': '4'},
        'Glendale Ave.': {'lat': 43.145269317159695, 'lng': -79.19232941376643, 'number': '5'},
        'Highway 20': {'lat': 43.076504078254914, 'lng': -79.21046775066173, 'number': '11'}
    },
    'Port Colborne': {
        'Main St.': {'lat': 42.90150138320793, 'lng': -79.24542847877964, 'number': '19'},
        'Mellanby Ave.': {'lat': 42.89646530877105, 'lng': -79.24659751954275, 'number': '19A'},
        'Clarence St.': {'lat': 42.88637569993079, 'lng': -79.2486307492592, 'number': '21'}
    },
    'Montreal South Shore': {
        'Victoria Bridge Downstream': {'lat': 45.495530624042686, 'lng': -73.5178096557915},
        'Victoria Bridge Upstream (Cycling Path)': {'lat': 45.49234276250341, 'lng': -73.5168207947014},
        'Sainte-Catherine/RécréoParc Bridge': {'lat': 45.4080536309029, 'lng': -73.56725875784645}
    },
    'Kahnawake': {
        'CP Railway Bridge 7A': {'lat': 45.411294284530854, 'lng': -73.66214553001862},
        'CP Railway Bridge 7B': {'lat': 45.4112624483958, 'lng': -73.66203405574073}
    },
    'Salaberry / Beauharnois / Suroît Region': {
        'St-Louis-de-Gonzague Bridge': {'lat': 45.232607447464225, 'lng': -74.00297750906498},
        'Larocque Bridge (Salaberry-de-Valleyfield)': {'lat': 45.22588000852819, 'lng': -74.11479220520631}
    }
}
