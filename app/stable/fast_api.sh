#!/bin/bash



python3 -m venv venv && . venv/bin/activate && venv/bin/pip install -r requirements.txt 
#!/bin/bash

# Script to start FastAPI with uvicorn in Docker

# Set default values
APP_MODULE=${APP_MODULE:-"app:app"} # Replace 'main:app' with your FastAPI app's module name
HOST=0.0.0.0
PNL_HTTPS_PORT=${PORT:-5001}
WORKERS=1

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running. Please start Docker and try again."
    exit 1
fi

# Build the Docker image
echo "Building Docker image..."
docker build -t fastapi-app .

# Run the Docker container
echo "Starting FastAPI app..."
docker run -d --name fastapi-container -p $PORT:$PORT fastapi-app \
    uvicorn $APP_MODULE --host $HOST --port $PORT --workers $WORKERS

# Print success message
echo "FastAPI server is running at http://localhost:$PORT"
