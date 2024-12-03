#!/bin/bash

# Start both Python scripts in background
python ./pnl_monitor.py & 
python ./db.py &

# Wait for all background processes to complete
wait