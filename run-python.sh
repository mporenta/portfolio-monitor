#!/bin/bash

# Navigate to the directory containing the Python files
cd /home/tbot/develop/github/portfolio-monitor/src

# Run the PnL monitor script
python3 pnl_monitor.py

# Start the Flask app
flask --app app run
