#!/bin/bash
# Setup GRAPE with standard paths and run recorder

set -e

# Configuration
GRAPE_ROOT="${GRAPE_DATA_ROOT:-$HOME/grape-data}"
CONFIG_FILE="${1:-config/grape-S000171.toml}"
DURATION="${2:-86400}"  # 24 hours default

echo "🚀 GRAPE Recorder Setup"
echo "======================="
echo ""
echo "Configuration:"
echo "  Data root: $GRAPE_ROOT"
echo "  Config: $CONFIG_FILE"
echo "  Duration: $DURATION seconds"
echo ""

# Create standard directory structure
echo "📁 Creating directory structure..."
TODAY=$(date +%Y%m%d)

mkdir -p "$GRAPE_ROOT/raw/$TODAY"
mkdir -p "$GRAPE_ROOT/analytics/quality/$TODAY"
mkdir -p "$GRAPE_ROOT/analytics/discontinuities/$TODAY"
mkdir -p "$GRAPE_ROOT/analytics/daily_summary/$TODAY"
mkdir -p "$GRAPE_ROOT/psws_upload/$TODAY"
mkdir -p "$GRAPE_ROOT/logs"

echo "✅ Directories created:"
echo "  $GRAPE_ROOT/raw/$TODAY"
echo "  $GRAPE_ROOT/analytics/quality/$TODAY"
echo "  $GRAPE_ROOT/logs"
echo ""

# Stop existing recorder
echo "🛑 Stopping any existing recorder..."
pkill -f test_v2_recorder_filtered.py 2>/dev/null || true
sleep 2
echo ""

# Start recorder with new paths
echo "▶️  Starting recorder..."
cd "$(dirname "$0")/.."

LOGFILE="$GRAPE_ROOT/logs/recorder_$(date +%Y%m%d_%H%M%S).log"

nohup python scripts/test_v2_recorder_filtered.py \
  --config "$CONFIG_FILE" \
  --duration "$DURATION" \
  --output-dir "$GRAPE_ROOT" \
  > "$LOGFILE" 2>&1 &

RECORDER_PID=$!
sleep 3

# Verify recorder started
if ps -p $RECORDER_PID > /dev/null; then
    echo "✅ Recorder started successfully (PID: $RECORDER_PID)"
else
    echo "❌ Recorder failed to start. Check log:"
    echo "   tail -f $LOGFILE"
    exit 1
fi

echo ""
echo "📝 Log file: $LOGFILE"
echo ""

# Update web-ui configuration
echo "🌐 Configuring web-ui..."
WEB_ENV="$(dirname "$0")/../web-ui/.env"
echo "GRAPE_DATA_ROOT=$GRAPE_ROOT" > "$WEB_ENV"
echo "✅ Web-UI environment updated"
echo ""

# Restart web server
echo "🔄 Restarting web server..."
cd web-ui
pkill -f monitoring-server.js 2>/dev/null || true
sleep 2

nohup node monitoring-server.js > monitoring-server.log 2>&1 &
WEB_PID=$!
sleep 3

if ps -p $WEB_PID > /dev/null; then
    echo "✅ Web server started successfully (PID: $WEB_PID)"
else
    echo "⚠️  Web server may have failed. Check:"
    echo "   tail -f web-ui/monitoring-server.log"
fi

cd ..
echo ""
echo "=" * 60
echo "🎉 GRAPE System Running!"
echo "=" * 60
echo ""
echo "📊 Dashboard: http://localhost:3000/"
echo ""
echo "📁 Data paths:"
echo "   Root: $GRAPE_ROOT"
echo "   Raw IQ: $GRAPE_ROOT/raw/$TODAY/"
echo "   Quality: $GRAPE_ROOT/analytics/quality/$TODAY/"
echo "   Logs: $GRAPE_ROOT/logs/"
echo ""
echo "🔍 Monitor:"
echo "   Recorder: tail -f $LOGFILE"
echo "   Web: tail -f web-ui/monitoring-server.log"
echo "   Status: ./web-ui/check-dashboard-status.sh"
echo ""
echo "⏰ Timeline:"
echo "   • Recorder is collecting data now"
echo "   • CSV export every 10 minutes"
echo "   • Dashboard updates after export"
echo "   • Check back in ~10 minutes for first data"
echo ""
