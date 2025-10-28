#!/bin/bash
# Helper script to manually start the watchdog
# Use this if you started the daemon manually without the watchdog

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if daemon is running
if ! pgrep -f "signal_recorder.cli daemon" > /dev/null; then
    echo "⚠️  No daemon process found. Start the daemon first."
    exit 1
fi

# Check if watchdog is already running
if pgrep -f "test-watchdog.py" > /dev/null; then
    echo "✓ Watchdog is already running"
    exit 0
fi

# Start watchdog
echo "Starting watchdog..."
nohup "${SCRIPT_DIR}/venv/bin/python" "${SCRIPT_DIR}/test-watchdog.py" > /dev/null 2>&1 &

sleep 2

# Verify it started
if pgrep -f "test-watchdog.py" > /dev/null; then
    WATCHDOG_PID=$(pgrep -f "test-watchdog.py")
    echo "✓ Watchdog started successfully (PID: ${WATCHDOG_PID})"
else
    echo "❌ Failed to start watchdog"
    exit 1
fi
