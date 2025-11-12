#!/bin/bash
# Stop GRAPE Signal Recorder - Dual Service Architecture
# Stops: Core Recorder + Analytics Service (all channels) + Web-UI

echo "🛑 Stopping GRAPE Signal Recorder (Dual-Service Architecture)"
echo "================================================================"
echo ""

# Get configuration to determine data root
CONFIG="${1:-config/grape-config.toml}"
DATA_ROOT="/tmp/grape-test"

if [ -f "$CONFIG" ]; then
    MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
    if [ "$MODE" = "production" ]; then
        DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
    else
        DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
    fi
fi

echo "📋 Configuration:"
echo "   Config file: $CONFIG"
echo "   Data root: $DATA_ROOT"
echo ""

# Function to stop processes and show count
stop_service() {
    local name=$1
    local pattern=$2
    
    echo "🛑 Stopping $name..."
    local count=$(ps aux | grep -E "$pattern" | grep -v grep | wc -l)
    
    if [ "$count" -eq 0 ]; then
        echo "   ℹ️  No $name processes running"
        return
    fi
    
    echo "   Found $count process(es)"
    pkill -f "$pattern" 2>/dev/null || true
    sleep 2
    
    # Check if any survived
    local remaining=$(ps aux | grep -E "$pattern" | grep -v grep | wc -l)
    if [ "$remaining" -gt 0 ]; then
        echo "   ⚠️  $remaining process(es) still running, forcing..."
        pkill -9 -f "$pattern" 2>/dev/null || true
        sleep 1
        remaining=$(ps aux | grep -E "$pattern" | grep -v grep | wc -l)
    fi
    
    if [ "$remaining" -eq 0 ]; then
        echo "   ✅ $name stopped"
    else
        echo "   ❌ Failed to stop $remaining $name process(es)"
    fi
}

# Stop all services
stop_service "Core Recorder" "signal_recorder.core_recorder"
stop_service "Analytics Services" "signal_recorder.analytics_service"
stop_service "Web-UI Monitoring Server" "monitoring-server.js"

echo ""
echo "📊 Final Status:"
CORE_COUNT=$(ps aux | grep core_recorder | grep -v grep | wc -l)
ANALYTICS_COUNT=$(ps aux | grep analytics_service | grep -v grep | wc -l)
WEBUI_COUNT=$(ps aux | grep monitoring-server.js | grep -v grep | wc -l)

echo "   Core Recorder: $CORE_COUNT running"
echo "   Analytics Services: $ANALYTICS_COUNT running"
echo "   Web-UI: $WEBUI_COUNT running"

if [ "$CORE_COUNT" -eq 0 ] && [ "$ANALYTICS_COUNT" -eq 0 ] && [ "$WEBUI_COUNT" -eq 0 ]; then
    echo ""
    echo "✅ All services stopped successfully"
    exit 0
else
    echo ""
    echo "⚠️  Some services may still be running"
    echo ""
    echo "🔍 Check remaining processes:"
    echo "   ps aux | grep -E '(core_recorder|analytics_service|monitoring-server)' | grep -v grep"
    exit 1
fi
