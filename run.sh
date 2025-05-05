#!/bin/bash

# Wait for the database to be ready
echo "Waiting for database to be ready..."
sleep 5

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the FastAPI server
echo "Starting the FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload