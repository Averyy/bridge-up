# 🔼🌉🔽 Bridge Up Scraper

[![Docker Image](https://img.shields.io/docker/v/averyyyy/bridge-up?style=flat-square&logo=docker)](https://hub.docker.com/r/averyyyy/bridge-up)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Description
Bridge Up Scraper is a Python-based service that monitors and analyzes bridge statuses along the Great Lakes St. Lawrence Seaway. It scrapes real-time data from official websites, processes this information, and stores it in Firebase Firestore. Containerized with Docker, it provides comprehensive insights into bridge operations with automated updates. 

This is a hobby project so expect breaking changes. Don't aggressively scrape their website or they will probably block your IP. Also because it completely relies on the St Lawrence Seaway website, if they change their HTML layout or block public access then it will stop working completely 💀 No warranty or guarantees of any kind provided, use at your own risk.

## Features
- 👀 Scrapes bridge status information from multiple regions
- 📊 Stores and manages historical activity logs
- 🗓️ Organizes and displays current and upcoming bridge events
- 📈 Calculates statistics from historical data
- 🔥 Utilizes Firebase Firestore for efficient data storage
- 🧹 Automatically cleans up old and irrelevant historical data
- 🐳 Containerized with Docker for easy deployment

## Prerequisites
- Firebase
- Docker
- Python 3.9+
- pip

## Setup

### Local Development Setup

1. Clone the repository

2. Add your Firebase credentials `firebase-auth.json` file in the project root:

2. Create a virtual environment:

```sh
python -m venv venv
source venv/bin/activate  # On Windows, use venv\Scripts\activate
```

3. Install dependencies:

```sh
pip install -r requirements.txt
```

4. Run the application:

```sh
python start_flask.py
```

### 🐳 Docker Production Setup

You can either build the Docker image yourself below, or download it from Docker Hub by clicking [here](https://hub.docker.com/repository/docker/averyyyy/bridge-up). The image is updated via a Github Workflow every time a commit it made.

1. Build the Docker image:

```sh
docker build -t bridge-up-backend .
```

2. Run the Docker container (make sure to provide the path to your Firebase credentials file called `firebase-auth.json`):

```sh
docker run -p 5000:5000 /path/on/host/firebase-auth.json:/app/data/firebase-auth.json bridge-up-backend
```

## Configuration

Bridge URLs and coordinates are configured in `config.py`. A couple of the bridges i'm not 100% sure about their location (since I don't live in the area), and I've only got the bridge numbers for St Catharines and Port Colburne. Modify this file or submit a pull request if you know what they should be.

## Scheduler

The application uses APScheduler to run tasks and can be managed inside the `start_flask.py` and `start_waitress.py` files. This interval is pretty aggressive, so you should probably make it a longer interval or risk your IP getting banned.

- 🌞 Scrapes and updates bridge data every 30 seconds from 6:00 AM to 9:59 PM
- 🌙 Scrapes and updates bridge data every 60 seconds from 10:00 PM to 5:59 AM
- 🧮 Runs daily statistics update at 4 AM

## Files

- `scraper.py`: Main script for scraping and processing bridge data
- `stats_calculator.py`: Calculates bridge statistics
- `start_flask.py`: Starts the Flask development server
- `start_waitress.py`: Starts the Waitress production server
- `config.py`: Configuration for bridge URLs and coordinates

## Contributing

Contributions are welcome. Please submit a pull request or create an issue for any features or bug fixes.

## License

GPL v3: You can do whatever you want as long you give attribution and the software you use it in also has a open license. 