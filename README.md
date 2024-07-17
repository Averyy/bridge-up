# Bridge Up Backend

[![Docker Image](https://img.shields.io/docker/v/averyyyy/bridge-up?style=flat-square&logo=docker)](https://hub.docker.com/r/averyyyy/bridge-up)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Description
Bridge Up Backend is a Python-based service that scrapes bridge status information from the Great Lakes St. Lawrence Seaway website and provides statistical analysis. It uses Flask, BeautifulSoup, and APScheduler, and is containerized using Docker for ease of deployment.

## Features
- Scrapes bridge status information from multiple regions
- Calculates and stores statistical data about bridge operations
- Provides daily updates of bridge statistics
- Uses Firebase for data storage
- Containerized with Docker

## Prerequisites
- Docker
- Python 3.9+
- pip

## Setup

### Local Development Setup

1. Clone the repository

2. Create a `.env` file in the project root with the following content:

```sh
FIREBASE_CREDENTIALS={"type": "service_account","project_id": "your-project-id", ...}
```

Replace the placeholder with your actual Firebase credentials.

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

### Docker/Production Setup

You can either build the Docker image yourself below, or download it from Docker Hub by clicking [here](https://hub.docker.com/repository/docker/averyyyy/bridge-up). The image is updated via a Github Workflow every time a commit it made.

1. Build the Docker image:

```sh
docker build -t bridge-up-backend .
```

2. Run the Docker container (make sure to provide the FIREBASE_CREDENTIALS env variable):

```sh
docker run -p 5000:5000 -e FIREBASE_CREDENTIALS bridge-up-backend
```

## Configuration

Bridge URLs and coordinates are configured in `config.py`. Modify this file to add or change bridge information.

## Scheduler

The application uses APScheduler to run tasks and can be managed inside the `start_flask.py` and `start_waitress.py` files:
- Scrapes and updates bridge data every 30 seconds from 6:00 AM to 9:59 PM
- Scrapes and updates bridge data every 60 seconds from 10:00 PM to 5:59 AM
- Runs daily statistics update at 4 AM

## Files

- `scraper.py`: Main script for scraping and processing bridge data
- `stats_calculator.py`: Calculates bridge statistics
- `start_flask.py`: Starts the Flask development server
- `start_waitress.py`: Starts the Waitress production server
- `config.py`: Configuration for bridge URLs and coordinates

## Contributing

Contributions are welcome. Please submit a pull request or create an issue for any features or bug fixes.