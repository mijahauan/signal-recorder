#!/bin/bash
# GRAPE All Services Control: Core + Analytics + Web-UI
# Usage: grape-all.sh -start|-stop|-status [config-file]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ACTION=""
CONFIG=""

for arg in "$@"; do
    case $arg in
        -start) ACTION="start" ;;
        -stop) ACTION="stop" ;;
        -status) ACTION="status" ;;
        *) CONFIG="$arg" ;;
    esac
done

CONFIG="${CONFIG:-$PROJECT_DIR/config/grape-config.toml}"

if [ -z "$ACTION" ]; then
    echo "Usage: $0 -start|-stop|-status [config-file]"
    exit 1
fi

get_data_root() {
    if [ -f "$CONFIG" ]; then
        MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
        if [ "$MODE" = "production" ]; then
            grep '^production_data_root' "$CONFIG" | cut -d'"' -f2
        else
            grep '^test_data_root' "$CONFIG" | cut -d'"' -f2
        fi
    else
        echo "/tmp/grape-test"
    fi
}

DATA_ROOT=$(get_data_root)

case $ACTION in
start)
    echo "🚀 Starting All GRAPE Services"
    echo "================================================================"
    echo "📋 Config: $CONFIG"
    echo "📁 Data: $DATA_ROOT"
    echo ""
    
    "$SCRIPT_DIR/grape-core.sh" -start "$CONFIG"
    echo ""
    "$SCRIPT_DIR/grape-analytics.sh" -start "$CONFIG"
    echo ""
    "$SCRIPT_DIR/grape-ui.sh" -start "$CONFIG"
    
    echo ""
    echo "================================================================"
    echo "✅ All services started"
    echo "📊 Dashboard: http://localhost:3000/"
    ;;

stop)
    echo "🛑 Stopping All GRAPE Services"
    echo "================================================================"
    
    "$SCRIPT_DIR/grape-ui.sh" -stop
    "$SCRIPT_DIR/grape-analytics.sh" -stop
    "$SCRIPT_DIR/grape-core.sh" -stop
    
    echo ""
    echo "✅ All services stopped"
    ;;

status)
    echo "📊 GRAPE Service Status"
    echo "================================================================"
    
    CORE_COUNT=$(pgrep -f "grape_recorder.grape.core_recorder" 2>/dev/null | wc -l)
    if [ "$CORE_COUNT" -gt 0 ]; then
        echo "✅ Core Recorder:     RUNNING (PIDs: $(pgrep -f 'grape_recorder.grape.core_recorder' | tr '\n' ' '))"
    else
        echo "⭕ Core Recorder:     STOPPED"
    fi
    
    ANALYTICS_COUNT=$(pgrep -f "grape_recorder.grape.analytics_service" 2>/dev/null | wc -l)
    if [ "$ANALYTICS_COUNT" -gt 0 ]; then
        echo "✅ Analytics:         RUNNING ($ANALYTICS_COUNT/9 channels)"
    else
        echo "⭕ Analytics:         STOPPED"
    fi
    
    WEBUI_COUNT=$(pgrep -f "monitoring-server" 2>/dev/null | wc -l)
    if [ "$WEBUI_COUNT" -gt 0 ]; then
        echo "✅ Web-UI:            RUNNING → http://localhost:3000/"
    else
        echo "⭕ Web-UI:            STOPPED"
    fi
    
    echo ""
    echo "📁 Data root: $DATA_ROOT"
    echo "📝 Logs: $DATA_ROOT/logs/"
    ;;
esac
