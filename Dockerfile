# Dockerfile
# Bridge Up Backend - FastAPI + WebSocket

FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for Docker cache optimization
COPY requirements.txt .

# Install dependencies (no build tools needed for FastAPI stack)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories for JSON storage
RUN mkdir -p /app/data/history

# Environment variables
ENV DOCKER_ENV=true
ENV PYTHONUNBUFFERED=1

# Expose uvicorn port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
