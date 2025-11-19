#!/bin/bash
# Direct start of GRAPE core recorder (no tmux)
# For testing: Run this in your own tmux/screen session
# For production: Use systemd service instead

set -e

CONFIG="${1:-config/grape-config.toml}"

if [ ! -f "$CONFIG" ]; then
    echo "❌ Config file not found: $CONFIG"
    echo "Usage: $0 [config-file]"
    exit 1
fi

echo "🚀 Starting GRAPE Core Recorder"
echo "================================"
echo ""

# Get mode and data_root from config
MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
if [ "$MODE" = "production" ]; then
    DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
    echo "Mode: PRODUCTION"
else
    DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
    echo "Mode: TEST"
fi

echo "Data root: $DATA_ROOT"
echo ""

# Ensure directories exist
mkdir -p "$DATA_ROOT"/{archives,logs,state}

# Set up Python virtual environment
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run: python3 -m venv venv && source venv/bin/activate && pip install -e ."
    exit 1
fi

source venv/bin/activate

# Start core recorder
echo "Starting core recorder..."
echo "Press Ctrl+C to stop"
echo ""

python3 -m signal_recorder.grape_recorder \
    --config "$CONFIG" \
    --data-root "$DATA_ROOT"
