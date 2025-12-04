#!/bin/bash
# GRAPE Phase 1: Core Recorder Control
#
# Phase 1 captures raw IQ data from radiod RTP stream:
#   - 20 kHz sample rate, complex float32
#   - Digital RF format with gzip compression
#   - System time tagging (NO UTC corrections)
#   - 10-second sliding window monitoring
#
# Output: raw_archive/{CHANNEL}/ (immutable source of truth)
#
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
    echo "▶️  Starting Phase 1 Core Recorder..."
    
    if pgrep -f "grape_recorder.grape.core_recorder" > /dev/null; then
        echo "   ℹ️  Already running (PID: $(pgrep -f 'grape_recorder.grape.core_recorder'))"
        exit 0
    fi
    
    if [ ! -f "$CONFIG" ]; then
        echo "   ❌ Config not found: $CONFIG"
        exit 1
    fi
    
    # Create three-phase directory structure
    mkdir -p "$DATA_ROOT/logs" "$DATA_ROOT/raw_archive" "$DATA_ROOT/status"
    cd "$PROJECT_DIR"
    
    nohup $PYTHON -m grape_recorder.grape.core_recorder --config "$CONFIG" \
        > "$DATA_ROOT/logs/phase1-core.log" 2>&1 &
    
    PID=$!
    sleep 3
    
    if ps -p $PID > /dev/null 2>&1; then
        echo "   ✅ Started (PID: $PID)"
        echo "   📄 Log: $DATA_ROOT/logs/phase1-core.log"
        echo "   📦 Output: $DATA_ROOT/raw_archive/{CHANNEL}/"
    else
        echo "   ❌ Failed to start"
        tail -5 "$DATA_ROOT/logs/phase1-core.log" 2>/dev/null
        exit 1
    fi
    ;;

stop)
    echo "🛑 Stopping Phase 1 Core Recorder..."
    
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
        echo "✅ Phase 1 Core Recorder: RUNNING (PID: $(pgrep -f 'grape_recorder.grape.core_recorder'))"
        echo "   Output: $DATA_ROOT/raw_archive/{CHANNEL}/"
        
        # Show channel count if raw_archive exists
        if [ -d "$DATA_ROOT/raw_archive" ]; then
            CHANNELS=$(ls -d "$DATA_ROOT/raw_archive"/*/  2>/dev/null | wc -l)
            echo "   Active channels: $CHANNELS"
        fi
    else
        echo "⭕ Phase 1 Core Recorder: STOPPED"
    fi
    ;;
esac
