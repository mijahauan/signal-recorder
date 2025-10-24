#!/bin/bash
# Test script for dynamic channel creation

set -e

echo "=========================================="
echo "Testing Dynamic Channel Creation"
echo "=========================================="
echo ""

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "docs/venv" ]; then
    source docs/venv/bin/activate
fi

echo "Step 1: List current channels"
echo "----------------------------------------"
control -v 239.251.200.193 | grep "SSRC" | head -25
echo ""

echo "Step 2: Create new channel at 14.5 MHz (SSRC 14500000)"
echo "----------------------------------------"
signal-recorder create-channels --config config/test-new-channel.toml
echo ""

echo "Step 3: Verify new channel exists"
echo "----------------------------------------"
echo "Looking for SSRC 14500000..."
if control -v 239.251.200.193 | grep -q "14500000"; then
    echo "✓ SUCCESS: Channel 14500000 found!"
    control -v 239.251.200.193 | grep "14500000"
else
    echo "✗ FAILED: Channel 14500000 not found"
    echo ""
    echo "Current channels:"
    control -v 239.251.200.193 | grep "SSRC" | head -25
fi
echo ""

echo "=========================================="
echo "Test Complete"
echo "=========================================="

