#!/bin/bash

# Wait for 60 seconds
echo "Waiting 60 seconds for IB-Gateway to initialize..."
sleep 60

# Execute the Python script
exec python pnl_monitor.py