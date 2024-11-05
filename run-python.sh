#!/bin/sh

# Function to log messages with timestamp
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# Function to run a command and log its status
run_with_logging() {
    log "Starting: $1"
    if $1; then
        log "Successfully completed: $1"
    else
        log "ERROR: Failed to execute: $1"
        return 1
    fi
}

# Main script execution
log "Script started"
log "Waiting for 60 seconds..."
sleep 60

# Run Python scripts with logging
run_with_logging "python3 ./src/pnl_monitor.py"


log "Script completed"
