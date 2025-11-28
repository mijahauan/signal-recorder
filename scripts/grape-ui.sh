#!/bin/bash
# GRAPE Web-UI Control
# Usage: grape-ui.sh -start|-stop|-status [config-file]

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
    echo "▶️  Starting Web-UI..."
    
    # Stop existing
    pkill -f "monitoring-server" 2>/dev/null
    sleep 1
    
    mkdir -p "$DATA_ROOT/logs"
    cd "$PROJECT_DIR/web-ui"
    
    nohup node monitoring-server-v3.js "$DATA_ROOT" \
        > "$DATA_ROOT/logs/webui.log" 2>&1 &
    
    PID=$!
    sleep 2
    
    if ps -p $PID > /dev/null 2>&1; then
        echo "   ✅ Started (PID: $PID)"
        echo "   🌐 http://localhost:3000/"
        echo "   📄 Log: $DATA_ROOT/logs/webui.log"
    else
        echo "   ❌ Failed to start"
        tail -5 "$DATA_ROOT/logs/webui.log" 2>/dev/null
        exit 1
    fi
    ;;

stop)
    echo "🛑 Stopping Web-UI..."
    
    if ! pgrep -f "monitoring-server" > /dev/null; then
        echo "   ℹ️  Not running"
        exit 0
    fi
    
    pkill -f "monitoring-server" 2>/dev/null
    sleep 1
    echo "   ✅ Stopped"
    ;;

status)
    if pgrep -f "monitoring-server" > /dev/null; then
        echo "✅ Web-UI: RUNNING → http://localhost:3000/"
    else
        echo "⭕ Web-UI: STOPPED"
    fi
    ;;
esac
