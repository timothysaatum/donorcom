#!/bin/bash

# Run Alembic migrations
alembic upgrade head

# Start FastAPI app
python run.py