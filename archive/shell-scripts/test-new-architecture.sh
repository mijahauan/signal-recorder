#!/bin/bash
# Test New time_snap Architecture
# 2025-11-23 - Startup Buffering + Embedded time_snap

set -e

echo "=================================================="
echo "Testing New Core Recorder Architecture"
echo "=================================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
CONFIG_FILE="config/grape-config.toml"
ARCHIVE_DIR="/tmp/grape-test/archives"
TEST_CHANNEL="WWV_10_MHz"  # Test with 10 MHz

echo -e "${YELLOW}Step 1: Stop existing core recorder${NC}"
echo "Looking for existing core_recorder process..."
if pgrep -f "signal_recorder.core_recorder" > /dev/null; then
    echo "Found running core_recorder, stopping..."
    pkill -f "signal_recorder.core_recorder"
    sleep 2
    
    if pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        echo -e "${RED}Warning: Process still running, force killing...${NC}"
        pkill -9 -f "signal_recorder.core_recorder"
        sleep 1
    fi
    echo -e "${GREEN}✓ Core recorder stopped${NC}"
else
    echo "No core recorder running"
fi
echo ""

echo -e "${YELLOW}Step 2: Backup current archives (for comparison)${NC}"
BACKUP_DIR="/tmp/grape-test/archives_pre_new_arch"
if [ -d "$ARCHIVE_DIR/$TEST_CHANNEL" ]; then
    echo "Backing up $TEST_CHANNEL archives..."
    mkdir -p "$BACKUP_DIR"
    cp -r "$ARCHIVE_DIR/$TEST_CHANNEL" "$BACKUP_DIR/" 2>/dev/null || true
    
    # Get latest file info
    LATEST_FILE=$(ls -t "$ARCHIVE_DIR/$TEST_CHANNEL"/*.npz 2>/dev/null | head -1 || echo "none")
    if [ "$LATEST_FILE" != "none" ]; then
        echo "Latest old file: $(basename $LATEST_FILE)"
        echo "  Size: $(stat -c%s "$LATEST_FILE") bytes"
    fi
    echo -e "${GREEN}✓ Backup complete${NC}"
else
    echo "No existing archives to backup"
fi
echo ""

echo -e "${YELLOW}Step 3: Check configuration${NC}"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}✗ Config file not found: $CONFIG_FILE${NC}"
    exit 1
fi
echo "Config file: $CONFIG_FILE"
echo -e "${GREEN}✓ Configuration OK${NC}"
echo ""

echo -e "${YELLOW}Step 4: Start new core recorder${NC}"
echo "Starting core recorder with new architecture..."
echo "  - Startup buffering: 120 seconds"
echo "  - Tone detection: ±1ms precision"
echo "  - Embedded time_snap in NPZ files"
echo ""
echo "Log file: /tmp/grape-test/core_recorder_test.log"
echo ""

# Activate venv and start core recorder in background, capture output
source venv/bin/activate && python3 -m signal_recorder.core_recorder --config "$CONFIG_FILE" \
    > /tmp/grape-test/core_recorder_test.log 2>&1 &

RECORDER_PID=$!
echo "Core recorder started (PID: $RECORDER_PID)"
echo ""

echo -e "${YELLOW}Step 5: Monitor startup sequence${NC}"
echo "Watching for startup events (120 second buffer expected)..."
echo "Press Ctrl+C to stop monitoring (recorder will keep running)"
echo ""

# Monitor log file for key events
tail -f /tmp/grape-test/core_recorder_test.log | while read line; do
    case "$line" in
        *"CoreRecorder initialized"*)
            echo -e "${GREEN}✓ Core recorder initialized${NC}"
            ;;
        *"Starting startup buffer"*)
            echo -e "${GREEN}✓ Startup buffering started${NC}"
            echo "  Buffering 120 seconds..."
            ;;
        *"Startup buffer complete"*)
            echo -e "${GREEN}✓ Startup buffer complete${NC}"
            ;;
        *"time_snap established"*)
            echo -e "${GREEN}✓ time_snap established!${NC}"
            echo "  $line" | grep -o 'time_snap.*'
            ;;
        *"Startup complete, normal recording started"*)
            echo -e "${GREEN}✓ Startup complete - normal recording started${NC}"
            echo ""
            echo "Waiting for first file..."
            ;;
        *"Wrote "*".npz"*)
            FILE=$(echo "$line" | grep -o '[0-9TZ_]*\.npz')
            echo -e "${GREEN}✓ NPZ file written: $FILE${NC}"
            ;;
        *"ERROR"*|*"CRITICAL"*)
            echo -e "${RED}✗ Error detected:${NC}"
            echo "  $line"
            ;;
    esac
done

echo ""
echo "Test script completed (recorder still running in background)"
echo "PID: $RECORDER_PID"
