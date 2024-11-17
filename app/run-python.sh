#!/bin/bash

# Navigate to the directory containing the Python files
cd /home/tbot/develop/github/portfolio-monitor/src

# Start the Flask app
python3 app.py

# Run the PnL monitor script
python3 pnl_monitor.py

