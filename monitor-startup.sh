#!/bin/bash
# Monitor core recorder startup

echo "=== Core Recorder Startup Monitor ==="
echo ""
echo "Waiting for 120-second startup buffer + time_snap establishment..."
echo "Expected timeline:"
echo "  0-120s:   Buffering samples"
echo "  ~120s:    time_snap detection"
echo "  ~120-180s: Processing buffer, writing first file"
echo ""

START_TIME=$(date +%s)
LAST_FILE_COUNT=0

while true; do
    ELAPSED=$(($(date +%s) - START_TIME))
    
    # Check if process is still running
    if ! pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        echo "❌ Core recorder stopped!"
        exit 1
    fi
    
    # Count NPZ files
    FILE_COUNT=$(ls /tmp/grape-test/archives/WWV_10_MHz/*.npz 2>/dev/null | wc -l)
    
    # Check for new files
    if [ $FILE_COUNT -gt $LAST_FILE_COUNT ]; then
        echo ""
        echo "✅ NEW FILE DETECTED!"
        LATEST_FILE=$(ls -t /tmp/grape-test/archives/WWV_10_MHz/*.npz | head -1)
        echo "File: $(basename $LATEST_FILE)"
        echo "Size: $(stat -c%s "$LATEST_FILE") bytes"
        echo ""
        echo "Analyzing file..."
        python3 -c "
import numpy as np
npz = np.load('$LATEST_FILE')
print(f'  Samples: {len(npz[\"iq\"]):,}')
print(f'  Duration: {len(npz[\"iq\"])/npz[\"sample_rate\"]:.1f} seconds')

# Check for time_snap fields (new architecture)
if 'time_snap_rtp' in npz:
    print(f'  ✅ time_snap embedded!')
    print(f'    Source: {npz[\"time_snap_source\"]}')
    print(f'    Station: {npz[\"time_snap_station\"]}')
    print(f'    Confidence: {npz[\"time_snap_confidence\"]:.2f}')
else:
    print(f'  ⚠️  No time_snap (old format)')
"
        echo ""
        echo "SUCCESS! New architecture working!"
        exit 0
    fi
    
    LAST_FILE_COUNT=$FILE_COUNT
    
    # Status update every 10 seconds
    if [ $((ELAPSED % 10)) -eq 0 ]; then
        printf "\r[%3ds] Waiting for first file... (need ~%ds more)" $ELAPSED $((120 - ELAPSED))
    fi
    
    sleep 1
done
