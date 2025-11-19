#!/bin/bash
# Clean test data for fresh start

echo "🧹 Cleaning GRAPE test data..."
echo ""

# Check if recorder is running
if pgrep -f "signal-recorder daemon" > /dev/null; then
    echo "⚠️  Recorder is still running!"
    echo "Please stop it first (Ctrl+C)"
    exit 1
fi

# Show current size
CURRENT_SIZE=$(du -sh /tmp/grape-test 2>/dev/null | cut -f1)
echo "Current test data size: ${CURRENT_SIZE:-0}"
echo ""

read -p "Delete ALL test data? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled"
    exit 0
fi

echo "Deleting /tmp/grape-test..."
rm -rf /tmp/grape-test

echo "Recreating directory structure..."
mkdir -p /tmp/grape-test/{data,analytics,logs,status,upload}

echo ""
echo "✅ Test data cleaned!"
echo "Ready for fresh start with:"
echo "  signal-recorder daemon --config config/grape-config.toml"
