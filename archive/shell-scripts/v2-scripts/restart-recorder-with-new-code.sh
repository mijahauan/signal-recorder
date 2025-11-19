#!/bin/bash
# Restart recorder to pick up new code changes
# This will also test offline gap detection!

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================"
echo "Restart Recorder (Test New Code)"
echo "========================================"
echo ""

# Record current time for offline gap calculation
STOP_TIME=$(date '+%Y-%m-%d %H:%M:%S %Z')
echo "Stop time: $STOP_TIME"
echo ""

# Find and stop old recorder
OLD_PID=$(pgrep -f "signal-recorder daemon" || echo "")

if [ -n "$OLD_PID" ]; then
    echo -e "${YELLOW}Stopping old recorder (PID: $OLD_PID)...${NC}"
    kill $OLD_PID
    
    # Wait for clean shutdown
    sleep 2
    
    if pgrep -f "signal-recorder daemon" > /dev/null; then
        echo -e "${RED}Process still running, force killing...${NC}"
        kill -9 $OLD_PID 2>/dev/null || true
    fi
    
    echo -e "${GREEN}✓ Old recorder stopped${NC}"
else
    echo "No recorder running"
fi

echo ""
echo -e "${YELLOW}Waiting 10 seconds to create offline gap...${NC}"
sleep 10

echo ""
START_TIME=$(date '+%Y-%m-%d %H:%M:%S %Z')
echo "Start time: $START_TIME"
echo ""

# Start new recorder with updated code
echo -e "${YELLOW}Starting recorder with new code...${NC}"
cd /home/mjh/git/signal-recorder

# Start in background (detached from terminal)
nohup signal-recorder daemon --config config/grape-config.toml > /tmp/grape-test/recorder.log 2>&1 &
NEW_PID=$!

sleep 3

if ps -p $NEW_PID > /dev/null; then
    echo -e "${GREEN}✓ New recorder started (PID: $NEW_PID)${NC}"
else
    echo -e "${RED}✗ Failed to start recorder${NC}"
    echo "Check logs: tail -50 /tmp/grape-test/recorder.log"
    exit 1
fi

echo ""
echo "========================================"
echo "Verification"
echo "========================================"
echo ""

# Wait a bit for initialization
sleep 5

echo "Checking for offline gap detection..."
if [ -f "/tmp/grape-test/data/session_boundaries.jsonl" ]; then
    echo -e "${GREEN}✓ Session boundaries log exists${NC}"
    echo "Latest entry:"
    tail -1 /tmp/grape-test/data/session_boundaries.jsonl | python3 -m json.tool 2>/dev/null || tail -1 /tmp/grape-test/data/session_boundaries.jsonl
else
    echo -e "${YELLOW}⚠ No session boundaries log yet (check in a moment)${NC}"
fi

echo ""
echo "Checking recent log activity..."
tail -20 /tmp/grape-test/recorder.log | grep -E "(offline|OFFLINE|gap|GAP|Started)" || echo "(no offline gap messages yet)"

echo ""
echo "========================================"
echo "Next Steps"
echo "========================================"
echo ""
echo "1. Monitor logs:"
echo "   tail -f /tmp/grape-test/recorder.log"
echo ""
echo "2. Check session boundaries:"
echo "   cat /tmp/grape-test/data/session_boundaries.jsonl"
echo ""
echo "3. Wait 1-2 minutes for quality CSV files:"
echo "   ls -lhrt /tmp/grape-test/analytics/quality/*/WWV*20251109.csv | tail -3"
echo ""
echo "4. Verify new gap categorization columns:"
echo "   head -1 /tmp/grape-test/analytics/quality/*/WWV*20251109.csv | head -1"
echo ""
echo "Expected to see: network_gap_ms, source_failure_ms, recorder_offline_ms"
echo ""
