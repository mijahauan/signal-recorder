#!/bin/bash
# Restart Web-UI Monitoring Server ONLY (keeps core recorder and analytics running)
# Use this when: updating web-ui code, fixing web-ui issues

set -e

CONFIG="${1:-config/grape-config.toml}"

if [ ! -f "$CONFIG" ]; then
    echo "❌ Config file not found: $CONFIG"
    echo "Usage: $0 [config-file]"
    exit 1
fi

echo "🔄 Restarting Web-UI Monitoring Server ONLY"
echo "================================================"
echo ""

# Get data root
MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
if [ "$MODE" = "production" ]; then
    DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
else
    DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
fi

echo "📋 Config: $CONFIG"
echo "📁 Data root: $DATA_ROOT"
echo ""

# Stop existing web-ui
echo "🛑 Stopping existing web-ui..."
pkill -f monitoring-server 2>/dev/null || true
sleep 1

REMAINING=$(ps aux | grep monitoring-server | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "   ⚠️  Force killing remaining processes..."
    pkill -9 -f monitoring-server 2>/dev/null || true
    sleep 1
fi

echo "   ✅ Web-UI stopped"
echo ""

# Start web-ui v3
echo "▶️  Starting Web-UI Monitoring Server (v3)..."
cd web-ui

nohup node monitoring-server-v3.js "$DATA_ROOT" > "$DATA_ROOT/logs/webui.log" 2>&1 &
WEB_PID=$!
sleep 2

if ps -p $WEB_PID > /dev/null 2>&1; then
    echo "   ✅ Web-UI v3 started (PID: $WEB_PID)"
else
    echo "   ❌ Web-UI failed to start"
    echo "   Check log: tail -f $DATA_ROOT/logs/webui.log"
    exit 1
fi

cd ..
echo ""
echo "✅ Web-UI Restarted"
echo ""
echo "📊 Dashboard: http://localhost:3000/"
echo "📝 Log: tail -f $DATA_ROOT/logs/webui.log"
echo ""
