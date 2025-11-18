#!/bin/bash
#
# Start radiod health monitor
# This continuously monitors radiod status for the web UI
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
MONITOR_SCRIPT="$SCRIPT_DIR/scripts/monitor_radiod_health.py"
STATUS_FILE="/tmp/grape-test/state/radiod-status.json"
POLL_INTERVAL=10

# Check if already running
if pgrep -f "monitor_radiod_health.py" > /dev/null; then
    echo "✓ Radiod monitor already running"
    exit 0
fi

echo "Starting radiod health monitor..."
echo "  Status file: $STATUS_FILE"
echo "  Poll interval: ${POLL_INTERVAL}s"

# Create state directory
mkdir -p "$(dirname "$STATUS_FILE")"

# Start monitor in background
nohup "$VENV_PYTHON" "$MONITOR_SCRIPT" "$STATUS_FILE" "$POLL_INTERVAL" \
    > /tmp/radiod-monitor.log 2>&1 &

PID=$!
sleep 2

# Verify it started
if ps -p $PID > /dev/null 2>&1; then
    echo "✅ Radiod monitor started (PID $PID)"
    
    # Wait for first status update
    for i in {1..5}; do
        if [ -f "$STATUS_FILE" ]; then
            echo "✅ Status file created"
            cat "$STATUS_FILE" | python3 -m json.tool 2>/dev/null | head -10
            exit 0
        fi
        sleep 1
    done
    
    echo "⚠️  Monitor running but status file not created yet"
    exit 0
else
    echo "❌ Failed to start radiod monitor"
    exit 1
fi
