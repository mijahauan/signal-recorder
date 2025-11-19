#!/bin/bash
# Auto-generate spectrograms every 15 minutes
# For test mode with /tmp/grape-test

DATA_ROOT="${1:-/tmp/grape-test}"
INTERVAL="${2:-900}"  # 15 minutes default

echo "=========================================="
echo "GRAPE Auto-Spectrogram Generator"
echo "=========================================="
echo "Data root: $DATA_ROOT"
echo "Interval: $INTERVAL seconds ($(($INTERVAL/60)) minutes)"
echo "Started at: $(date)"
echo ""

cd "$(dirname "$0")/.." || exit 1

while true; do
    DATE=$(date -u +%Y%m%d)
    echo "[$(date -u +%H:%M:%S)] Generating spectrograms for $DATE..."
    
    # Generate ALL channel spectrograms from decimated 10Hz NPZ files
    # This includes both wide (16kHz→10Hz) and carrier (200Hz→10Hz) channels
    # Both use identical IIR decimation via analytics_service.py
    python3 scripts/generate_spectrograms_from_10hz_npz.py \
        --data-root "$DATA_ROOT" \
        --date "$DATE" \
        --include-carrier \
        2>&1 | grep -E "(Processing|Generated|Error)" || true
    
    echo "[$(date -u +%H:%M:%S)] Done. Next run in $(($INTERVAL/60)) minutes."
    echo ""
    
    sleep "$INTERVAL"
done
