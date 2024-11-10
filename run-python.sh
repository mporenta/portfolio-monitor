#!/bin/sh
sleep 30
# Change directory to the specified path
cd /home/tbot/develop/github/portfolio-monitor/src || exit

# Run main.py using Python (ensure Python is installed and configured)
python3 pnl_monitor.py
sleep 10
python3 app.py
