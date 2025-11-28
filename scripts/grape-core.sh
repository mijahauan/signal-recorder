#!/bin/bash
# GRAPE Core Recorder Control
# Usage: grape-core.sh -start|-stop|-status [config-file]

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
    echo "▶️  Starting Core Recorder..."
    
    if pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        echo "   ℹ️  Already running (PID: $(pgrep -f 'signal_recorder.core_recorder'))"
        exit 0
    fi
    
    if [ ! -f "$CONFIG" ]; then
        echo "   ❌ Config not found: $CONFIG"
        exit 1
    fi
    
    mkdir -p "$DATA_ROOT/logs"
    cd "$PROJECT_DIR"
    
    nohup python3 -m signal_recorder.core_recorder --config "$CONFIG" \
        > "$DATA_ROOT/logs/core-recorder.log" 2>&1 &
    
    PID=$!
    sleep 3
    
    if ps -p $PID > /dev/null 2>&1; then
        echo "   ✅ Started (PID: $PID)"
        echo "   📄 Log: $DATA_ROOT/logs/core-recorder.log"
    else
        echo "   ❌ Failed to start"
        tail -5 "$DATA_ROOT/logs/core-recorder.log" 2>/dev/null
        exit 1
    fi
    ;;

stop)
    echo "🛑 Stopping Core Recorder..."
    
    if ! pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        echo "   ℹ️  Not running"
        exit 0
    fi
    
    pkill -f "signal_recorder.core_recorder" 2>/dev/null
    sleep 2
    
    if pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        pkill -9 -f "signal_recorder.core_recorder" 2>/dev/null
    fi
    
    echo "   ✅ Stopped"
    ;;

status)
    if pgrep -f "signal_recorder.core_recorder" > /dev/null; then
        echo "✅ Core Recorder: RUNNING (PID: $(pgrep -f 'signal_recorder.core_recorder'))"
    else
        echo "⭕ Core Recorder: STOPPED"
    fi
    ;;
esac
