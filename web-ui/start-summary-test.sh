#!/bin/bash
# Quick test script for Summary screen

set -e

echo "🧪 Starting GRAPE Summary Screen Test"
echo "======================================"
echo ""

# Check if config exists
CONFIG="../config/grape-config.toml"
if [ ! -f "$CONFIG" ]; then
    echo "❌ Config not found: $CONFIG"
    exit 1
fi

# Get data root from config
DATA_ROOT=$(grep -E '^test_data_root|^production_data_root' "$CONFIG" | head -1 | cut -d'"' -f2)
if [ -z "$DATA_ROOT" ]; then
    DATA_ROOT="/tmp/grape-test"
    echo "⚠️  Using default data root: $DATA_ROOT"
else
    echo "📁 Data root: $DATA_ROOT"
fi

# Check if data exists
if [ ! -d "$DATA_ROOT/archives" ]; then
    echo "⚠️  Warning: No archives directory found at $DATA_ROOT/archives"
    echo "   Summary will display but may show empty data"
fi

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install Node.js first."
    exit 1
fi

echo ""
echo "Starting monitoring server..."
echo ""

export GRAPE_CONFIG="$CONFIG"
node monitoring-server-v3.js

# Note: Server will run until Ctrl+C
