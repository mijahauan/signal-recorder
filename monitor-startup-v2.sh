#!/bin/bash
# Monitor core recorder startup - Wait for NEW files only

echo "=== Core Recorder Startup Monitor ==="
echo ""

# Get timestamp of latest existing file
BASELINE_FILE=$(ls -t /tmp/grape-test/archives/WWV_10_MHz/*.npz 2>/dev/null | head -1)
if [ -n "$BASELINE_FILE" ]; then
    BASELINE_TIME=$(stat -c%Y "$BASELINE_FILE")
    echo "Baseline (latest old file): $(basename $BASELINE_FILE)"
    echo "Waiting for files NEWER than $(date -d @$BASELINE_TIME '+%H:%M:%S')..."
else
    BASELINE_TIME=0
    echo "No existing files, waiting for first file..."
fi

echo ""
echo "Core recorder startup timeline:"
echo "  0-120s:   Buffering samples for time_snap detection"
echo "  ~120s:    Analyzing buffer, detecting WWV tone edge"
echo "  ~120-180s: Processing buffered samples, writing files"
echo ""

START_TIME=$(date +%s)

while true; do
    ELAPSED=$(($(date +%s) - START_TIME))
    
    # Check if process is still running
    if ! pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        echo "❌ Core recorder stopped!"
        exit 1
    fi
    
    # Look for files newer than baseline
    LATEST_FILE=$(ls -t /tmp/grape-test/archives/WWV_10_MHz/*.npz 2>/dev/null | head -1)
    if [ -n "$LATEST_FILE" ]; then
        LATEST_TIME=$(stat -c%Y "$LATEST_FILE")
        
        if [ $LATEST_TIME -gt $BASELINE_TIME ]; then
            echo ""
            echo "✅ NEW FILE DETECTED!"
            echo "File: $(basename $LATEST_FILE)"
            echo "Created: $(date -d @$LATEST_TIME '+%H:%M:%S')"
            echo "Size: $(stat -c%s "$LATEST_FILE") bytes"
            echo ""
            echo "Analyzing file structure..."
            python3 << EOF
import numpy as np
npz = np.load('$LATEST_FILE')

print(f"  Samples: {len(npz['iq']):,}")
print(f"  Duration: {len(npz['iq'])/npz['sample_rate']:.1f} seconds")
print(f"  RTP timestamp: {npz['rtp_timestamp']}")

# Check for time_snap fields (new architecture)
if 'time_snap_rtp' in npz:
    print()
    print("  ✅ NEW ARCHITECTURE DETECTED!")
    print(f"  time_snap_rtp: {npz['time_snap_rtp']}")
    print(f"  time_snap_utc: {npz['time_snap_utc']}")
    print(f"  time_snap_source: {npz['time_snap_source']}")
    print(f"  time_snap_station: {npz['time_snap_station']}")
    print(f"  time_snap_confidence: {npz['time_snap_confidence']:.2f}")
    print()
    print("  ✅ time_snap embedded in NPZ file!")
    print("  ✅ Self-contained archive format!")
else:
    print()
    print("  ⚠️  OLD FORMAT (no embedded time_snap)")
EOF
            echo ""
            exit 0
        fi
    fi
    
    # Status update
    if [ $ELAPSED -lt 120 ]; then
        STATUS="Buffering"
        REMAINING=$((120 - ELAPSED))
        printf "\r[%3ds] $STATUS... (%ds until time_snap detection)" $ELAPSED $REMAINING
    elif [ $ELAPSED -lt 180 ]; then
        STATUS="Processing"
        printf "\r[%3ds] $STATUS buffer, writing files..." $ELAPSED
    else
        STATUS="Waiting"
        printf "\r[%3ds] $STATUS for file..." $ELAPSED
    fi
    
    sleep 2
done
