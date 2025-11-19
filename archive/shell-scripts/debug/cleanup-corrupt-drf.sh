#!/bin/bash
# Cleanup script for corrupt Digital RF data
# Run this after applying the bug fix to regenerate clean DRF from NPZ archives

set -e

echo "======================================================================="
echo "Digital RF Corruption Cleanup Script"
echo "======================================================================="
echo ""
echo "This script will:"
echo "  1. Stop all analytics services"
echo "  2. Backup corrupt DRF data"
echo "  3. Delete corrupt DRF directories"
echo "  4. Optionally reset analytics state"
echo "  5. Restart analytics services"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

DATA_ROOT="/tmp/grape-test"
BACKUP_DIR="/tmp/grape-test/analytics.corrupt.$(date +%Y%m%d_%H%M%S)"

echo ""
echo "=== Step 1: Stopping Analytics Services ==="
echo "Looking for running analytics processes..."
PIDS=$(ps aux | grep "[p]ython.*analytics_service" | awk '{print $2}')
if [ -z "$PIDS" ]; then
    echo "No analytics services running."
else
    echo "Found processes: $PIDS"
    echo "$PIDS" | xargs kill
    echo "Waiting for processes to stop..."
    sleep 3
    
    # Check if still running
    REMAINING=$(ps aux | grep "[p]ython.*analytics_service" | wc -l)
    if [ $REMAINING -gt 0 ]; then
        echo "Some processes still running, force killing..."
        pkill -9 -f "analytics_service"
        sleep 1
    fi
    echo "✅ All analytics services stopped"
fi

echo ""
echo "=== Step 2: Backing up corrupt DRF data ==="
echo "Backup location: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

for channel_dir in "$DATA_ROOT"/analytics/*/; do
    channel=$(basename "$channel_dir")
    if [ -d "$channel_dir/digital_rf" ]; then
        echo "  Backing up $channel..."
        cp -r "$channel_dir/digital_rf" "$BACKUP_DIR/$channel/"
    fi
done
echo "✅ Backup complete: $(du -sh $BACKUP_DIR | awk '{print $1}')"

echo ""
echo "=== Step 3: Deleting corrupt DRF data ==="
echo "Removing Digital RF directories for Nov 12-16..."
for date in 20251112 20251113 20251114 20251115 20251116; do
    echo "  Removing $date..."
    find "$DATA_ROOT/analytics" -path "*/digital_rf/$date" -type d -exec rm -rf {} + 2>/dev/null || true
done

# Also remove any OBS directories that might have bad data
echo "  Checking for corrupt OBS directories (year 2081)..."
find "$DATA_ROOT/analytics" -type d -name "OBS*" 2>/dev/null | while read obs_dir; do
    # Check if directory has any HDF5 files
    if [ "$(find "$obs_dir" -name "*.h5" | head -1)" ]; then
        echo "    Found: $obs_dir"
    fi
done

echo "✅ Corrupt DRF data deleted"

echo ""
echo "=== Step 4: Analytics State ==="
echo "Current state files:"
ls -lh "$DATA_ROOT/state/analytics-*.json" 2>/dev/null || echo "  (none found)"
echo ""
read -p "Reset analytics state to reprocess all archives? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Resetting state files..."
    rm -f "$DATA_ROOT/state/analytics-*.json"
    echo "✅ State reset - will reprocess all NPZ archives"
else
    echo "Keeping existing state - will resume from last processed file"
fi

echo ""
echo "=== Step 5: Ready to restart ==="
echo ""
echo "Cleanup complete! Next steps:"
echo ""
echo "1. Restart analytics services:"
echo "   cd /home/mjh/git/signal-recorder"
echo "   ./start-analytics-services.sh"
echo ""
echo "2. Monitor logs for issues:"
echo "   tail -f $DATA_ROOT/logs/analytics-*.log"
echo ""
echo "3. Check for backwards-time warnings (should be rare/none):"
echo "   grep 'out of order' $DATA_ROOT/logs/analytics-*.log"
echo ""
echo "4. Wait for DRF regeneration (may take hours for full history)"
echo ""
echo "5. Regenerate spectrograms:"
echo "   for date in 20251112 20251113 20251114 20251115 20251116; do"
echo "       python3 scripts/generate_spectrograms_drf.py --date \$date"
echo "   done"
echo ""
echo "======================================================================="
echo "Backup preserved at: $BACKUP_DIR"
echo "======================================================================="
