#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting Gunicorn..."
exec gunicorn -k uvicorn.workers.UvicornWorker app.main:app \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --timeout 120 \
    --log-level debug