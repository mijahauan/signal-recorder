#!/bin/bash
# GRAPE Core Recorder Control
# Usage: grape-core.sh -start|-stop|-status [config-file]

# Source common settings (sets PYTHON, PROJECT_DIR, etc.)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

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

CONFIG="${CONFIG:-$DEFAULT_CONFIG}"

if [ -z "$ACTION" ]; then
    echo "Usage: $0 -start|-stop|-status [config-file]"
    exit 1
fi

DATA_ROOT=$(get_data_root "$CONFIG")

case $ACTION in
start)
    echo "▶️  Starting Core Recorder..."
    
    if pgrep -f "grape_recorder.grape.core_recorder" > /dev/null; then
        echo "   ℹ️  Already running (PID: $(pgrep -f 'grape_recorder.grape.core_recorder'))"
        exit 0
    fi
    
    if [ ! -f "$CONFIG" ]; then
        echo "   ❌ Config not found: $CONFIG"
        exit 1
    fi
    
    mkdir -p "$DATA_ROOT/logs"
    cd "$PROJECT_DIR"
    
    nohup $PYTHON -m grape_recorder.grape.core_recorder --config "$CONFIG" \
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
    
    if ! pgrep -f "grape_recorder.grape.core_recorder" > /dev/null; then
        echo "   ℹ️  Not running"
        exit 0
    fi
    
    pkill -f "grape_recorder.grape.core_recorder" 2>/dev/null
    sleep 2
    
    if pgrep -f "grape_recorder.grape.core_recorder" > /dev/null; then
        pkill -9 -f "grape_recorder.grape.core_recorder" 2>/dev/null
    fi
    
    echo "   ✅ Stopped"
    ;;

status)
    if pgrep -f "grape_recorder.grape.core_recorder" > /dev/null; then
        echo "✅ Core Recorder: RUNNING (PID: $(pgrep -f 'grape_recorder.grape.core_recorder'))"
    else
        echo "⭕ Core Recorder: STOPPED"
    fi
    ;;
esac
