# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory to /app
WORKDIR /app

# Copy just the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install build dependencies and Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get remove -y build-essential && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the rest of the application
COPY . .

# Create directory for persistent data if needed
RUN mkdir -p /app/data
ENV DOCKER_ENV=true
ENV PYTHONUNBUFFERED=1

# Expose port 5000
EXPOSE 5000

# Command to run the application using Waitress
CMD ["python", "start_waitress.py"]