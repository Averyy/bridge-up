# config.py

BRIDGE_URLS = {
    'https://seaway-greatlakes.com/bridgestatus/detailsnai?key=BridgeSCT': {
        'region': 'St Catharines',
        'shortform': 'SCT'
    },
    'https://seaway-greatlakes.com/bridgestatus/detailsnai?key=BridgePC': {
        'region': 'Port Colborne',
        'shortform': 'PC'
    },
    'https://seaway-greatlakes.com/bridgestatus/detailsmai?key=BridgeM': {
        'region': 'Montreal South Shore',
        'shortform': 'MSS'
    },
    'https://seaway-greatlakes.com/bridgestatus/detailsmai?key=BridgeK': {
        'region': 'Kahnawake',
        'shortform': 'K'
    },
    'https://www.seaway-greatlakes.com/bridgestatus/detailsmai2?key=BridgeSBS': {
        'region': 'Salaberry / Beauharnois / Suroît Region',
        'shortform': 'SBS'
    }
}

BRIDGE_COORDINATES = {
    'St Catharines': {
        'Lakeshore Rd': {'lat': 43.21617521494522, 'lng': -79.21223177177772},
        'Carlton St.': {'lat': 43.19185980424842, 'lng': -79.20100809118367},
        'Queenston St.': {'lat': 43.165824700918485, 'lng': -79.19492604380804},
        'Glendale Ave.': {'lat': 43.145269317159695, 'lng': -79.19232941376643},
        'Highway 20': {'lat': 43.076504078254914, 'lng': -79.21046775066173}
    },
    'Port Colborne': {
        # Add coordinates for Port Colborne bridges here
        # For example:
        # 'Bridge Name': {'lat': 42.123456, 'lng': -79.123456},
    }
    # Add other regions and their coordinates here
}