#!/bin/bash
#
# Generate carrier spectrograms from both pathways for comparison
#
# This script demonstrates the two independent data processing paths:
# 1. Wide-decimated: 16 kHz → 10 Hz (legacy, with decimation artifacts)
# 2. Native-carrier: 200 Hz → 10 Hz (new, cleaner radiod filtering)
#

set -e

# Default to today if no date provided
DATE=${1:-$(date +%Y%m%d)}
DATA_ROOT=${DATA_ROOT:-/tmp/grape-test}

echo "========================================"
echo "Carrier Spectrogram Comparison Generator"
echo "========================================"
echo "Date: $DATE"
echo "Data root: $DATA_ROOT"
echo ""

# Path 1: Wide-Decimated (16 kHz → 10 Hz)
echo "📶 Generating WIDE-DECIMATED spectrograms (16 kHz → 10 Hz)..."
echo "   Source: Analytics decimated files"
echo "   Output: $DATA_ROOT/spectrograms/$DATE/wide-decimated/"
echo ""
python3 scripts/generate_spectrograms_from_10hz_npz.py \
    --date "$DATE" \
    --data-root "$DATA_ROOT"

if [ $? -eq 0 ]; then
    echo "✅ Wide-decimated spectrograms complete"
else
    echo "❌ Wide-decimated generation failed"
    exit 1
fi

echo ""
echo "----------------------------------------"
echo ""

# Path 2: Native-Carrier (200 Hz → 10 Hz)
echo "📡 Generating NATIVE-CARRIER spectrograms (200 Hz → 10 Hz)..."
echo "   Source: Native 200 Hz carrier channels"
echo "   Output: $DATA_ROOT/spectrograms/$DATE/native-carrier/"
echo ""
python3 scripts/generate_spectrograms_from_carrier.py \
    --date "$DATE" \
    --data-root "$DATA_ROOT"

if [ $? -eq 0 ]; then
    echo "✅ Native-carrier spectrograms complete"
else
    echo "❌ Native-carrier generation failed"
    exit 1
fi

echo ""
echo "========================================"
echo "✅ COMPARISON READY"
echo "========================================"
echo ""
echo "View results:"
echo "  Wide-decimated:   $DATA_ROOT/spectrograms/$DATE/wide-decimated/"
echo "  Native-carrier:   $DATA_ROOT/spectrograms/$DATE/native-carrier/"
echo ""
echo "Web UI: http://localhost:3000/carrier.html"
echo ""

# Show file counts
WIDE_COUNT=$(find "$DATA_ROOT/spectrograms/$DATE/wide-decimated/" -name "*.png" 2>/dev/null | wc -l)
CARRIER_COUNT=$(find "$DATA_ROOT/spectrograms/$DATE/native-carrier/" -name "*.png" 2>/dev/null | wc -l)

echo "Generated spectrograms:"
echo "  Wide-decimated:   $WIDE_COUNT files"
echo "  Native-carrier:   $CARRIER_COUNT files"
echo ""

if [ "$WIDE_COUNT" -eq "$CARRIER_COUNT" ] && [ "$WIDE_COUNT" -gt 0 ]; then
    echo "✅ Both pathways produced matching file counts"
else
    echo "⚠️  File count mismatch - check for missing data"
fi
