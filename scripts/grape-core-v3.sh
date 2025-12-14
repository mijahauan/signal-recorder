#!/bin/bash
# GRAPE Phase 1: Core Recorder V3 - Per-Channel Processes
#
# This version spawns a SEPARATE PROCESS for each channel to distribute
# CPU load across all cores (avoids Python GIL bottleneck).
#
# Each channel runs in its own Python process:
#   - RTP reception and processing
#   - Binary archive writing (with optional zstd compression)
#   - Full CPU core utilization
#
# Output: raw_buffer/{CHANNEL}/ (per-channel binary IQ files)
#
# Usage: grape-core-v3.sh -start|-stop|-status [config-file]

# Source common settings (sets PYTHON, PROJECT_DIR, etc.)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ACTION=""
CONFIG=""

for arg in "$@"; do
    case $arg in
        -start) ACTION="start" ;;
        -stop) ACTION="stop" ;;
        -status) ACTION="status" ;;
        -restart) ACTION="restart" ;;
        *) CONFIG="$arg" ;;
    esac
done

CONFIG="${CONFIG:-$DEFAULT_CONFIG}"

if [ -z "$ACTION" ]; then
    echo "Usage: $0 -start|-stop|-status|-restart [config-file]"
    exit 1
fi

DATA_ROOT=$(get_data_root "$CONFIG")

# Extract channels from config
get_channels() {
    $PYTHON -c "
import toml
import sys
with open('$CONFIG') as f:
    config = toml.load(f)
for ch in config.get('recorder', {}).get('channels', []):
    freq = ch.get('frequency_hz', 0)
    desc = ch.get('description', f'{freq/1e6:.3f} MHz')
    print(f'{freq}|{desc}')
"
}

start_channels() {
    echo "▶️  Starting Phase 1 Core Recorder V3 (per-channel processes)..."
    
    if pgrep -f "grape_recorder.grape.channel_recorder" > /dev/null; then
        echo "   ℹ️  Already running"
        pgrep -af "grape_recorder.grape.channel_recorder" | head -5
        exit 0
    fi
    
    if [ ! -f "$CONFIG" ]; then
        echo "   ❌ Config not found: $CONFIG"
        exit 1
    fi
    
    # Create directory structure
    mkdir -p "$DATA_ROOT/logs" "$DATA_ROOT/raw_buffer" "$DATA_ROOT/status"
    cd "$PROJECT_DIR"
    
    # Start one process per channel with CPU affinity
    # Use cores 8-15 for GRAPE, leaving 0-7 for radiod and system
    STARTED=0
    CORE=8
    NUM_CORES=$(nproc)
    MAX_CORE=$((NUM_CORES - 1))
    
    while IFS='|' read -r freq desc; do
        if [ -z "$freq" ]; then continue; fi
        
        # Sanitize channel name for log file
        log_name=$(echo "$desc" | tr ' ' '_' | tr '.' '_')
        log_file="$DATA_ROOT/logs/phase1-${log_name}.log"
        
        echo "   Starting: $desc @ $(echo "scale=3; $freq/1000000" | bc) MHz (core $CORE)"
        
        # Use taskset to pin to specific core (8-15 range)
        nohup taskset -c $CORE $PYTHON -m grape_recorder.grape.channel_recorder \
            --config "$CONFIG" \
            --channel "$desc" \
            --frequency "$freq" \
            --log-level INFO \
            > "$log_file" 2>&1 &
        
        STARTED=$((STARTED + 1))
        
        # Cycle through cores 8-15 (or 8 to MAX_CORE if fewer cores)
        CORE=$((CORE + 1))
        if [ $CORE -gt $MAX_CORE ] || [ $CORE -gt 15 ]; then
            CORE=8
        fi
    done < <(get_channels)
    
    sleep 3
    
    RUNNING=$(pgrep -c -f "grape_recorder.grape.channel_recorder" 2>/dev/null || echo 0)
    
    if [ "$RUNNING" -gt 0 ]; then
        echo "   ✅ Started $RUNNING/$STARTED channel processes"
        echo "   📄 Logs: $DATA_ROOT/logs/phase1-*.log"
        echo "   📦 Output: $DATA_ROOT/raw_buffer/{CHANNEL}/"
    else
        echo "   ❌ Failed to start any channels"
        ls -la "$DATA_ROOT/logs/phase1-"*.log 2>/dev/null | head -3
        exit 1
    fi
}

stop_channels() {
    echo "🛑 Stopping Phase 1 Core Recorder V3..."
    
    if ! pgrep -f "grape_recorder.grape.channel_recorder" > /dev/null; then
        echo "   ℹ️  Not running"
        return 0
    fi
    
    # Graceful shutdown
    pkill -TERM -f "grape_recorder.grape.channel_recorder" 2>/dev/null
    sleep 2
    
    # Force kill if needed
    if pgrep -f "grape_recorder.grape.channel_recorder" > /dev/null; then
        pkill -9 -f "grape_recorder.grape.channel_recorder" 2>/dev/null
        sleep 1
    fi
    
    echo "   ✅ Stopped"
}

show_status() {
    PIDS=$(pgrep -f "grape_recorder.grape.channel_recorder" 2>/dev/null)
    
    if [ -n "$PIDS" ]; then
        COUNT=$(echo "$PIDS" | wc -l)
        echo "✅ Phase 1 Core Recorder V3: RUNNING ($COUNT channel processes)"
        echo "   Output: $DATA_ROOT/raw_buffer/{CHANNEL}/"
        echo ""
        echo "   Per-channel processes:"
        ps -o pid,psr,%cpu,%mem,etime,args -p $(echo $PIDS | tr '\n' ',') 2>/dev/null | head -15
    else
        echo "⭕ Phase 1 Core Recorder V3: STOPPED"
    fi
}

case $ACTION in
    start)
        start_channels
        ;;
    stop)
        stop_channels
        ;;
    restart)
        stop_channels
        sleep 1
        start_channels
        ;;
    status)
        show_status
        ;;
esac
