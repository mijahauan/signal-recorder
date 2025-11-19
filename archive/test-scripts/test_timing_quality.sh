#!/bin/bash
# Test and verify Timing Quality Framework implementation

set -e

DATA_ROOT="${1:-/tmp/grape-test}"
TEST_CHANNEL="WWV_5_MHz"

echo "================================================================"
echo "Testing Timing Quality Framework"
echo "================================================================"
echo ""
echo "Data root: $DATA_ROOT"
echo "Test channel: $TEST_CHANNEL"
echo ""

# ============================================================================
# Test 1: Check NTP Sync
# ============================================================================
echo "Test 1: System NTP Synchronization"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if timedatectl status 2>/dev/null | grep -q "System clock synchronized: yes"; then
    echo "✅ NTP synchronized"
    
    # Try to get offset details
    if command -v chronyc &> /dev/null; then
        echo ""
        chronyc tracking | grep "System time"
    elif command -v ntpq &> /dev/null; then
        echo ""
        ntpq -c rv | grep -o "offset=[^,]*"
    fi
else
    echo "⚠️  NTP NOT synchronized"
fi
echo ""

# ============================================================================
# Test 2: Analytics Service Status
# ============================================================================
echo "Test 2: Analytics Service Running"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

STATUS_FILE="$DATA_ROOT/analytics/$TEST_CHANNEL/status/analytics-service-status.json"

if [ -f "$STATUS_FILE" ]; then
    echo "✅ Status file exists: $STATUS_FILE"
    
    # Check last update time
    LAST_UPDATE=$(stat -c %y "$STATUS_FILE" 2>/dev/null || stat -f "%Sm" "$STATUS_FILE" 2>/dev/null)
    echo "   Last update: $LAST_UPDATE"
    
    # Extract key metrics
    echo ""
    echo "Status summary:"
    python3 << EOF
import json
try:
    with open('$STATUS_FILE') as f:
        status = json.load(f)
    print(f"   Running: {status.get('running', 'unknown')}")
    print(f"   Files processed: {status.get('files_processed', 0)}")
    print(f"   Time_snap: {'Yes' if status.get('time_snap_established') else 'No'}")
    if status.get('time_snap_established'):
        ts = status.get('time_snap', {})
        print(f"   Time_snap source: {ts.get('station', 'unknown')}")
        print(f"   Confidence: {ts.get('confidence', 0):.2f}")
except Exception as e:
    print(f"   Error reading status: {e}")
EOF
else
    echo "❌ Status file not found"
    echo "   Expected: $STATUS_FILE"
    echo "   Analytics service may not be running"
fi
echo ""

# ============================================================================
# Test 3: Check Recent Log Messages
# ============================================================================
echo "Test 3: Timing Quality Log Messages (last 50 lines)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

LOG_FILE="$DATA_ROOT/logs/analytics-$TEST_CHANNEL.log"

if [ -f "$LOG_FILE" ]; then
    echo "Checking log: $LOG_FILE"
    echo ""
    
    # Look for timing-related messages
    tail -50 "$LOG_FILE" | grep -i "timing\|ntp\|gps\|time_snap" || echo "   No timing messages in last 50 lines"
else
    echo "❌ Log file not found: $LOG_FILE"
fi
echo ""

# ============================================================================
# Test 4: Digital RF Metadata
# ============================================================================
echo "Test 4: Digital RF Metadata (Timing Quality)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

DRF_DIR="$DATA_ROOT/analytics/$TEST_CHANNEL/digital_rf"

if [ -d "$DRF_DIR" ]; then
    echo "✅ Digital RF directory exists"
    echo ""
    
    # Count HDF5 files
    RF_FILES=$(find "$DRF_DIR" -name "rf@*.h5" 2>/dev/null | wc -l)
    echo "   RF files: $RF_FILES"
    
    if [ $RF_FILES -gt 0 ]; then
        echo ""
        echo "Reading metadata from latest file..."
        python3 << EOF
import sys
import os
import json

try:
    import digital_rf as drf
    import numpy as np
    
    drf_dir = '$DRF_DIR'
    
    # Find subdirectories (PSWS structure)
    for root, dirs, files in os.walk(drf_dir):
        if any(f.startswith('rf@') and f.endswith('.h5') for f in files):
            reader = drf.DigitalRFReader(root)
            channels = reader.get_channels()
            
            if channels:
                ch = channels[0]
                print(f"   Channel: {ch}")
                
                # Get data bounds
                bounds = reader.get_bounds(ch)
                if bounds[0] is not None:
                    print(f"   Data range: {bounds[0]} to {bounds[1]}")
                    
                    # Try to read metadata
                    try:
                        # Read a small slice of metadata
                        start = bounds[0]
                        end = min(start + 100, bounds[1])
                        
                        metadata_reader = reader.get_digital_metadata(ch)
                        if metadata_reader:
                            metadata = metadata_reader.read(start, end)
                            
                            if metadata:
                                # Get first metadata entry
                                first_key = list(metadata.keys())[0]
                                first_meta = metadata[first_key]
                                
                                print("")
                                print("   Latest metadata fields:")
                                timing_fields = [
                                    'timing_quality',
                                    'time_snap_age_seconds',
                                    'ntp_offset_ms',
                                    'reprocessing_recommended',
                                    'timing_notes'
                                ]
                                
                                for field in timing_fields:
                                    if field in first_meta:
                                        value = first_meta[field]
                                        if isinstance(value, (bytes, np.bytes_)):
                                            value = value.decode('utf-8')
                                        print(f"     {field}: {value}")
                            else:
                                print("   No metadata entries found")
                        else:
                            print("   No metadata reader available")
                    except Exception as e:
                        print(f"   Could not read metadata: {e}")
                else:
                    print("   No data bounds available")
            break
    else:
        print("   No Digital RF data files found")
        
except ImportError:
    print("   ⚠️  digital_rf module not available")
    print("   Cannot verify metadata - install with: pip3 install digital_rf")
except Exception as e:
    print(f"   Error reading Digital RF: {e}")
    import traceback
    traceback.print_exc()
EOF
    else
        echo "   No RF files written yet"
    fi
else
    echo "❌ Digital RF directory not found: $DRF_DIR"
fi
echo ""

# ============================================================================
# Test 5: Timing Quality Distribution (if data exists)
# ============================================================================
echo "Test 5: Timing Quality Distribution"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Analyzing Digital RF metadata..."
python3 << EOF
import sys
import os
from collections import Counter

try:
    import digital_rf as drf
    
    drf_dir = '$DRF_DIR'
    quality_counts = Counter()
    
    # Find and read all metadata
    for root, dirs, files in os.walk(drf_dir):
        if any(f.startswith('rf@') and f.endswith('.h5') for f in files):
            try:
                reader = drf.DigitalRFReader(root)
                channels = reader.get_channels()
                
                if channels:
                    ch = channels[0]
                    bounds = reader.get_bounds(ch)
                    
                    if bounds[0] is not None:
                        metadata_reader = reader.get_digital_metadata(ch)
                        if metadata_reader:
                            metadata = metadata_reader.read(bounds[0], bounds[1])
                            
                            for meta_dict in metadata.values():
                                quality = meta_dict.get('timing_quality', 'unknown')
                                if isinstance(quality, bytes):
                                    quality = quality.decode('utf-8')
                                quality_counts[quality] += 1
            except Exception as e:
                continue
    
    if quality_counts:
        total = sum(quality_counts.values())
        print(f"   Total segments analyzed: {total}")
        print("")
        print("   Distribution:")
        for quality, count in quality_counts.most_common():
            pct = (count / total) * 100
            print(f"     {quality:15s}: {count:5d} ({pct:5.1f}%)")
    else:
        print("   No metadata found yet (may need more data)")
        
except ImportError:
    print("   ⚠️  digital_rf module not available")
except Exception as e:
    print(f"   Error: {e}")
EOF
echo ""

# ============================================================================
# Summary
# ============================================================================
echo "================================================================"
echo "Test Summary"
echo "================================================================"
echo ""
echo "✅ Tests complete"
echo ""
echo "Expected behavior:"
echo "  • Cold start (0-5 min): NTP_SYNCED or WALL_CLOCK"
echo "  • After WWV tone: GPS_LOCKED"
echo "  • After 24 hours: ~95% GPS_LOCKED, 4% NTP_SYNCED, 1% other"
echo ""
echo "Next steps:"
echo "  1. Monitor logs for timing quality messages"
echo "  2. Wait for WWV tone detection (~1-5 minutes)"
echo "  3. Verify time_snap establishment in status file"
echo "  4. Check metadata shows GPS_LOCKED quality"
echo ""
