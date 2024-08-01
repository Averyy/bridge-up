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
	# K is just CP railway bridges, not worth logging for consumers
    # 'Kahnawake': {
	# 	# Not sure which is which or if i got the right bridges here, might have them backwards or incorrect completely
    #     'CP Railway Bridge 7A': {'lat': 45.4112624483958, 'lng': -73.66203405574073},
    #     'CP Railway Bridge 7B': {'lat': 45.411294284530854, 'lng': -73.66214553001862}
    # },
    'Salaberry / Beauharnois / Suroît Region': {
        'St-Louis-de-Gonzague Bridge': {'lat': 45.232607447464225, 'lng': -74.00297750906498},
        'Larocque Bridge (Salaberry-de-Valleyfield)': {'lat': 45.22588000852819, 'lng': -74.11479220520631}
    }
}