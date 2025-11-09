#!/bin/bash
# quick-verify.sh - Immediate GRAPE data sanity check
# Run this NOW to verify recording is working correctly

set -e

echo "========================================"
echo "GRAPE Data Verification"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check 1: Stats file exists and recent
echo "━━━ Check 1: Recorder Status ━━━"
if [ -f /tmp/signal-recorder-stats.json ]; then
    age=$(($(date +%s) - $(stat -c %Y /tmp/signal-recorder-stats.json 2>/dev/null || echo 0)))
    if [ $age -lt 120 ]; then
        echo -e "${GREEN}✓${NC} Stats file found (age: ${age}s - recent)"
    else
        echo -e "${YELLOW}⚠${NC} Stats file found but stale (age: ${age}s)"
        echo "  Recorder may not be running or may be stuck"
    fi
    
    echo ""
    echo "Current channel stats:"
    python3 << 'EOF'
import json
import sys

try:
    with open('/tmp/signal-recorder-stats.json') as f:
        stats = json.load(f)
    
    print(f"{'Channel':<15} {'Completeness':<12} {'Packet Loss':<12} {'Status':<10}")
    print("─" * 60)
    
    for channel, data in sorted(stats.items()):
        if isinstance(data, dict):
            completeness = data.get('completeness_percent', 0)
            packet_loss = data.get('packet_loss_percent', 0)
            
            # Determine status
            if completeness >= 99 and packet_loss < 1:
                status = "🟢 Healthy"
            elif completeness >= 95:
                status = "🟡 Warning"
            else:
                status = "🔴 Error"
            
            print(f"{channel:<15} {completeness:>10.1f}% {packet_loss:>10.2f}% {status:<10}")
except Exception as e:
    print(f"Error reading stats: {e}", file=sys.stderr)
EOF
else
    echo -e "${RED}✗${NC} No stats file found at /tmp/signal-recorder-stats.json"
    echo "  Recorder is not running!"
fi

echo ""
echo "━━━ Check 2: Digital RF Files ━━━"

DATE=$(date -u +%Y%m%d)
DATA_ROOT="/tmp/grape-test/data"

if [ -d "${DATA_ROOT}/${DATE}" ]; then
    echo -e "${GREEN}✓${NC} Today's data directory exists: ${DATA_ROOT}/${DATE}"
    
    # Count HDF5 files created
    h5_count=$(find "${DATA_ROOT}/${DATE}" -name "*.h5" 2>/dev/null | wc -l)
    echo "  HDF5 files created today: ${h5_count}"
    
    if [ $h5_count -gt 0 ]; then
        echo "  Recent files:"
        find "${DATA_ROOT}/${DATE}" -name "*.h5" -type f -printf "    %TY-%Tm-%Td %TH:%TM  %p\n" 2>/dev/null | sort -r | head -5
    fi
else
    echo -e "${RED}✗${NC} No data directory for today: ${DATA_ROOT}/${DATE}"
fi

echo ""
echo "━━━ Check 3: WWV Tone Detection ━━━"

WWV_LOG="/tmp/grape-test/analytics/timing/wwv_timing.csv"
if [ -f "$WWV_LOG" ]; then
    echo -e "${GREEN}✓${NC} WWV timing log exists"
    
    # Count today's detections
    detections_today=$(grep "^${DATE}" "$WWV_LOG" 2>/dev/null | wc -l)
    echo "  Tone detections today: ${detections_today}"
    
    if [ $detections_today -gt 0 ]; then
        echo "  Recent detections:"
        grep "^${DATE}" "$WWV_LOG" 2>/dev/null | tail -5 | while IFS=, read date time channel freq timing snr duration envelope; do
            echo "    ${time} ${channel} (timing: ${timing}ms, SNR: ${snr}dB)"
        done
    else
        echo -e "${YELLOW}  ⚠ No tone detections today (may be low signal or early in day)${NC}"
    fi
else
    echo -e "${YELLOW}⚠${NC} No WWV timing log found"
    echo "  Tone detection may not be enabled or no tones detected yet"
fi

echo ""
echo "━━━ Check 4: NPZ File Status (16 kHz Full Bandwidth) ━━━"

python3 << 'EOF'
import sys
from pathlib import Path
from datetime import datetime
import time

data_root = Path('/tmp/grape-test/data')
date_str = datetime.utcnow().strftime('%Y%m%d')
date_dir = data_root / date_str

if not date_dir.exists():
    print(f"✗ No data directory for {date_str}")
    sys.exit(0)

print(f"Checking recent NPZ files for each channel...\n")
print(f"{'Channel':<15} {'Files':<8} {'Most Recent':<20} {'Age (s)':<10} {'Status':<10}")
print("─" * 75)

for channel_dir in sorted(date_dir.glob('AC0G_EM38ww/172/*/')):
    channel = channel_dir.name
    try:
        # Find most recent NPZ file
        npz_files = list(channel_dir.glob('*.npz'))
        
        if not npz_files:
            print(f"{channel:<15} {'0':<8} {'N/A':<20} {'N/A':<10} {'🔴 No data':<10}")
            continue
        
        most_recent = max(npz_files, key=lambda p: p.stat().st_mtime)
        age = time.time() - most_recent.stat().st_mtime
        timestamp = most_recent.name.split('_')[0]
        
        # Determine status based on age
        if age < 120:  # Less than 2 minutes old
            status = "🟢 Active"
        elif age < 600:  # Less than 10 minutes old
            status = "🟡 Recent"
        else:
            status = "🔴 Stale"
        
        print(f"{channel:<15} {len(npz_files):<8} {timestamp:<20} {age:<10.0f} {status:<10}")
        
    except Exception as e:
        print(f"{channel:<15} {'Error':<8} {'':<20} {'':<10} {'🔴 Error':<10}")

EOF

echo ""
echo "━━━ Check 5: Digital RF Files (10 Hz Decimated - Upload Format) ━━━"

python3 << 'EOF'
import sys
from pathlib import Path
from datetime import datetime

data_root = Path('/tmp/grape-test/data')
date_str = datetime.utcnow().strftime('%Y%m%d')

# Look for ch0 directories (Digital RF structure)
ch0_dirs = list(data_root.glob(f'{date_str}/*/*/*/ch0'))
h5_files = list(data_root.glob(f'{date_str}/**/*.h5'))

if ch0_dirs:
    print(f"✓ Found {len(ch0_dirs)} Digital RF channels")
    for d in ch0_dirs:
        channel_name = d.parent.name
        files = list(d.glob('*/rf@*.h5'))
        print(f"  {channel_name}: {len(files)} .h5 files")
elif h5_files:
    print(f"✓ Found {len(h5_files)} .h5 files (unexpected location)")
else:
    print("✗ No Digital RF files created yet")
    print("  (Hourly writes trigger at :01 past each hour)")

EOF

echo ""
echo "━━━ Check 6: Disk Space ━━━"

if [ -d "/tmp/grape-test" ]; then
    usage=$(du -sh /tmp/grape-test 2>/dev/null | cut -f1)
    echo -e "${GREEN}✓${NC} Test data directory size: ${usage}"
    
    # Check if we're running low on /tmp space
    tmp_avail=$(df -h /tmp | tail -1 | awk '{print $4}')
    echo "  Available space on /tmp: ${tmp_avail}"
fi

if [ -d "/var/lib/signal-recorder" ]; then
    prod_usage=$(du -sh /var/lib/signal-recorder 2>/dev/null | cut -f1)
    echo "  Production data directory size: ${prod_usage}"
fi

echo ""
echo "━━━ Summary ━━━"

# Determine overall health
if [ -f /tmp/signal-recorder-stats.json ]; then
    age=$(($(date +%s) - $(stat -c %Y /tmp/signal-recorder-stats.json)))
    if [ $age -lt 120 ]; then
        echo -e "${GREEN}✓${NC} Recorder is running and recently updated"
    else
        echo -e "${YELLOW}⚠${NC} Recorder may be stuck or not running"
    fi
else
    echo -e "${RED}✗${NC} Recorder is not running"
fi

h5_count=$(find "${DATA_ROOT}/${DATE}" -name "*.h5" 2>/dev/null | wc -l)
if [ $h5_count -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Digital RF files are being created"
else
    echo -e "${RED}✗${NC} No Digital RF files created today"
fi

echo ""
echo "========================================"
echo "Run './quick-verify.sh' again anytime to re-check"
echo "For continuous monitoring, see: REALTIME_DATA_VERIFICATION.md"
echo "========================================"
