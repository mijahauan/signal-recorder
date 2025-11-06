#!/bin/bash
# Comprehensive daemon and watchdog shutdown script

echo "=== Stopping Signal Recorder Daemon ==="

# Find daemon PID
DAEMON_PID=$(pgrep -f "signal_recorder.cli daemon")

if [ -z "$DAEMON_PID" ]; then
    echo "No daemon process found"
else
    echo "Found daemon PID: $DAEMON_PID"
    
    # Try graceful shutdown first
    echo "Sending SIGTERM..."
    kill $DAEMON_PID 2>/dev/null
    
    # Wait up to 10 seconds for graceful shutdown
    for i in {1..10}; do
        if ! kill -0 $DAEMON_PID 2>/dev/null; then
            echo "✓ Daemon stopped gracefully"
            break
        fi
        echo "  Waiting for daemon to stop... ($i/10)"
        sleep 1
    done
    
    # Force kill if still running
    if kill -0 $DAEMON_PID 2>/dev/null; then
        echo "⚠️  Daemon didn't stop, forcing kill..."
        kill -9 $DAEMON_PID 2>/dev/null
        sleep 1
        
        if ! kill -0 $DAEMON_PID 2>/dev/null; then
            echo "✓ Daemon force-killed"
        else
            echo "❌ Failed to kill daemon!"
        fi
    fi
fi

echo ""
echo "=== Stopping Watchdog Processes ==="

# Kill all watchdogs
WATCHDOG_PIDS=$(pgrep -f "test-watchdog.py")

if [ -z "$WATCHDOG_PIDS" ]; then
    echo "✓ No watchdog processes found"
else
    echo "Found watchdog PIDs: $WATCHDOG_PIDS"
    
    for pid in $WATCHDOG_PIDS; do
        echo "Killing watchdog PID $pid..."
        kill $pid 2>/dev/null || kill -9 $pid 2>/dev/null
    done
    
    sleep 1
    
    # Verify
    REMAINING=$(pgrep -f "test-watchdog.py")
    if [ -z "$REMAINING" ]; then
        echo "✓ All watchdog processes stopped"
    else
        echo "⚠️  Some watchdogs still running: $REMAINING"
        echo "   Force killing..."
        for pid in $REMAINING; do
            kill -9 $pid 2>/dev/null
        done
    fi
fi

# Clean up PID file
if [ -f "data/watchdog.pid" ]; then
    rm -f data/watchdog.pid
    echo "✓ Removed watchdog PID file"
fi

echo ""
echo "=== Final Status ==="
echo "Daemon processes: $(pgrep -f 'signal_recorder.cli daemon' | wc -l)"
echo "Watchdog processes: $(pgrep -f 'test-watchdog.py' | wc -l)"
echo ""

if [ $(pgrep -f 'signal_recorder.cli daemon' | wc -l) -eq 0 ] && \
   [ $(pgrep -f 'test-watchdog.py' | wc -l) -eq 0 ]; then
    echo "✅ All processes stopped cleanly"
else
    echo "⚠️  Some processes may still be running"
fi
