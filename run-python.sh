#!/bin/sh
sleep 60
python3 ./src/run_pnl_monitor.py
python3 ./src/pnl_web_service.py
