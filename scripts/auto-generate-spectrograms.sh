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
    python3 scripts/generate_spectrograms_from_10hz.py \
        --data-root "$DATA_ROOT" \
        --date "$DATE" \
        2>&1 | grep -E "(Processing|Generated|Error)" || true
    
    echo "[$(date -u +%H:%M:%S)] Done. Next run in $(($INTERVAL/60)) minutes."
    echo ""
    
    sleep "$INTERVAL"
done
