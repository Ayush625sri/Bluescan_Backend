
# Start the FastAPI server
echo "Starting the FastAPI server..."
uvicorn main:app --host 0.0.0.0 --port 5000 --reload