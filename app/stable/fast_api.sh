#!/bin/bash

# Wait for 60 seconds
echo "app.py Waiting 60 seconds for IB-Gateway to initialize..."
sleep 10

# Execute the Python script
exec python app.py
