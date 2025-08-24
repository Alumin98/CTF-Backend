# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1

# Install system deps (curl for healthcheck, build-essential for any wheels)
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential curl     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies first (leverages Docker layer cache)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy application code
COPY app /app/app

# Expose uvicorn port
EXPOSE 8000

# Default command (can be overridden by docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
