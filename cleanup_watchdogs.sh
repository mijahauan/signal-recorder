#!/bin/bash
# Cleanup all orphaned watchdog processes

echo "=== Cleaning up orphaned watchdog processes ==="

# Find and kill all test-watchdog.py processes
WATCHDOG_PIDS=$(pgrep -f "test-watchdog.py")

if [ -z "$WATCHDOG_PIDS" ]; then
    echo "No watchdog processes found"
else
    echo "Found watchdog processes: $WATCHDOG_PIDS"
    
    for pid in $WATCHDOG_PIDS; do
        echo "Killing watchdog PID $pid..."
        kill $pid 2>/dev/null || kill -9 $pid 2>/dev/null
    done
    
    # Wait a moment
    sleep 1
    
    # Verify they're gone
    REMAINING=$(pgrep -f "test-watchdog.py")
    if [ -z "$REMAINING" ]; then
        echo "✓ All watchdog processes cleaned up"
    else
        echo "⚠️  Some watchdog processes still running: $REMAINING"
        echo "   Try: kill -9 $REMAINING"
    fi
fi

# Also clean up any orphaned pgrep/ps from watchdog
echo ""
echo "Checking for orphaned watchdog subprocesses..."
ORPHANED=$(ps aux | grep -E "pgrep.*signal_recorder|ps.*signal_recorder" | grep -v grep | awk '{print $2}')

if [ -n "$ORPHANED" ]; then
    echo "Found orphaned subprocesses: $ORPHANED"
    for pid in $ORPHANED; do
        kill $pid 2>/dev/null
    done
else
    echo "No orphaned subprocesses found"
fi

echo ""
echo "=== Cleanup complete ==="
echo "Current watchdog count: $(pgrep -f test-watchdog.py | wc -l)"
