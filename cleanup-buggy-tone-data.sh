#!/bin/bash
# Cleanup script for data affected by tone detector timing bug
# Bug period: Nov 17 22:23 UTC - Nov 18 01:45 UTC (analytics restart)
# Issue: 30-second timing offset in tone detection causing invalid discrimination data

set -e

DATA_ROOT="/tmp/grape-test"

echo "=================================================="
echo "Cleaning Buggy Tone Detector Data"
echo "=================================================="
echo ""
echo "Bug: 30-second timing offset (fixed in tone_detector.py line 351)"
echo "Affected period: Nov 17 22:23 UTC - Nov 18 01:45 UTC"
echo ""

# Confirm before proceeding
read -p "Continue with cleanup? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cleanup cancelled"
    exit 0
fi

echo ""
echo "Step 1: Removing discrimination CSV files (bad timing data)..."
find "$DATA_ROOT/analytics/"*/discrimination/ -name "*20251117*.csv" -delete -print
find "$DATA_ROOT/analytics/"*/discrimination/ -name "*20251118*.csv" -delete -print
echo "  ✓ Discrimination CSVs deleted"
echo ""

echo "Step 2: Removing decimated NPZ files (contain bad time_snap metadata)..."
# Remove files from Nov 17 after 22:00 UTC and all of Nov 18
for channel_dir in "$DATA_ROOT/analytics/"*/decimated/; do
    if [ -d "$channel_dir" ]; then
        # Nov 17 from 22:00 onwards
        find "$channel_dir" -name "20251117T22*.npz" -delete 2>/dev/null || true
        find "$channel_dir" -name "20251117T23*.npz" -delete 2>/dev/null || true
        # All of Nov 18
        find "$channel_dir" -name "20251118*.npz" -delete 2>/dev/null || true
    fi
done
echo "  ✓ Decimated NPZ files deleted"
echo ""

echo "Step 3: Clearing time_snap from state files (force re-detection)..."
for state_file in "$DATA_ROOT/state/analytics-"*.json; do
    if [ -f "$state_file" ]; then
        # Backup first
        cp "$state_file" "${state_file}.backup-$(date +%Y%m%d-%H%M%S)"
        
        # Clear time_snap using jq
        jq 'del(.time_snap) | del(.time_snap_history)' "$state_file" > "${state_file}.tmp"
        mv "${state_file}.tmp" "$state_file"
        
        echo "  ✓ Cleared: $(basename $state_file)"
    fi
done
echo ""

echo "Step 4: Summary of remaining archives (raw 16 kHz data is preserved)..."
echo "  Archives will be reprocessed with fixed tone detector"
echo ""
find "$DATA_ROOT/archives/WWV_5_MHz/" -name "20251117T22*.npz" -o -name "20251117T23*.npz" -o -name "20251118T0*.npz" | wc -l | xargs echo "  Raw NPZ files to reprocess:"
echo ""

echo "=================================================="
echo "✓ Cleanup Complete"
echo "=================================================="
echo ""
echo "Next steps:"
echo "  1. Analytics services will automatically reprocess raw archives"
echo "  2. New time_snap will be established on next WWV/CHU tone"
echo "  3. Discrimination data will be regenerated with correct timing"
echo ""
echo "Monitor progress:"
echo "  tail -f $DATA_ROOT/logs/analytics-wwv5.log | grep -E '(Detected|time_snap)'"
echo ""
