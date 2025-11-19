#!/bin/bash
# Start GRAPE Signal Recorder System
# Both recorder and web-UI read from same config file

set -e

# Configuration
CONFIG="${1:-config/grape-config.toml}"
DURATION="${2:-86400}"  # 24 hours default

if [ ! -f "$CONFIG" ]; then
    echo "❌ Config file not found: $CONFIG"
    exit 1
fi

echo "🚀 Starting GRAPE Signal Recorder System"
echo "========================================"
echo ""

# Get mode and data_root from config
MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
if [ "$MODE" = "production" ]; then
    DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
    MODE_ICON="🚀"
    MODE_TEXT="PRODUCTION"
else
    DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
    MODE_ICON="🧪"
    MODE_TEXT="TEST"
fi

if [ -z "$DATA_ROOT" ]; then
    DATA_ROOT="/tmp/grape-test"
    echo "⚠️  Could not read data_root from config, using default: $DATA_ROOT"
fi

echo "📋 Configuration:"
echo "   Config file: $CONFIG"
echo "   Mode: $MODE_ICON $MODE_TEXT"
echo "   Data root: $DATA_ROOT"
echo "   Duration: $DURATION seconds ($(($DURATION / 3600)) hours)"
echo ""

# Stop any existing instances
echo "🛑 Stopping existing instances..."
pkill -f test_v2_recorder_filtered.py 2>/dev/null || true
pkill -f monitoring-server.js 2>/dev/null || true
sleep 2

mkdir -p "$DATA_ROOT/logs"
echo ""

# Start recorder (reads data_root from config)
echo "▶️  Starting recorder..."
RECORDER_LOG="$DATA_ROOT/logs/recorder_$(date +%Y%m%d_%H%M%S).log"

nohup python scripts/test_v2_recorder_filtered.py \
  --config "$CONFIG" \
  --duration "$DURATION" \
  > "$RECORDER_LOG" 2>&1 &

RECORDER_PID=$!
sleep 3

# Verify recorder started
if ps -p $RECORDER_PID > /dev/null 2>&1; then
    echo "   ✅ Recorder started (PID: $RECORDER_PID)"
else
    echo "   ❌ Recorder failed to start"
    echo "   Check log: tail -f $RECORDER_LOG"
    exit 1
fi

# Start web-UI (reads same config file)
echo ""
echo "▶️  Starting web-UI..."
cd web-ui

export GRAPE_CONFIG="../$CONFIG"

nohup node monitoring-server.js > monitoring-server.log 2>&1 &
WEB_PID=$!
sleep 3

if ps -p $WEB_PID > /dev/null 2>&1; then
    echo "   ✅ Web-UI started (PID: $WEB_PID)"
else
    echo "   ⚠️  Web-UI may have failed"
    echo "   Check log: tail -f web-ui/monitoring-server.log"
fi

cd ..

echo ""
echo "========================================="
echo "✅ GRAPE System Running"
echo "========================================="
echo ""
echo "📊 Dashboard: http://localhost:3000/"
echo ""
echo "📁 Paths (from config):"
echo "   Data root: $DATA_ROOT"
echo "   Raw IQ: $DATA_ROOT/data/$(date +%Y%m%d)/"
echo "   Quality: $DATA_ROOT/analytics/quality/$(date +%Y%m%d)/"
echo ""
echo "📝 Logs:"
echo "   Recorder: tail -f $RECORDER_LOG"
echo "   Web-UI: tail -f web-ui/monitoring-server.log"
echo ""
echo "⏱️  Timeline:"
echo "   • Recorder collecting data now"
echo "   • CSV export every minute (live updates!)"
echo "   • Dashboard refreshes every 60 seconds"
echo "   • WWV detection every minute at :00"
echo ""
echo "🔍 Monitor status:"
echo "   ./web-ui/check-dashboard-status.sh"
echo ""
echo "🛑 Stop all:"
echo "   pkill -f test_v2_recorder_filtered.py"
echo "   pkill -f monitoring-server.js"
echo ""
