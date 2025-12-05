#!/bin/bash
#
# GRAPE Phase 3 Products Service Controller
# Generates spectrograms and power data from DRF archive in real-time
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/venv"
CONFIG_FILE="$PROJECT_ROOT/config/grape-config.toml"

# Load configuration
if [[ -f "$CONFIG_FILE" ]]; then
    DATA_ROOT=$(grep -E "^test_data_root\s*=" "$CONFIG_FILE" | head -1 | sed 's/.*=\s*"\([^"]*\)".*/\1/')
    if [[ -z "$DATA_ROOT" ]]; then
        DATA_ROOT="/tmp/grape-test"
    fi
else
    DATA_ROOT="/tmp/grape-test"
fi

STATE_DIR="$DATA_ROOT/state"
LOG_DIR="$DATA_ROOT/logs"
PRODUCTS_DIR="$DATA_ROOT/products"

# Ensure directories exist
mkdir -p "$STATE_DIR" "$LOG_DIR" "$PRODUCTS_DIR"

# Get list of channels from config
get_channels() {
    if [[ -f "$CONFIG_FILE" ]]; then
        python3 -c "
import tomli
with open('$CONFIG_FILE', 'rb') as f:
    config = tomli.load(f)
channels = config.get('recorder', {}).get('channels', [])
for ch in channels:
    if ch.get('enabled', True):
        name = ch.get('description', f\"Channel {ch.get('ssrc')}\")
        freq = ch.get('frequency', 0)
        print(f\"{name}|{freq}\")
"
    fi
}

start_service() {
    echo "▶️  Starting Phase 3 Products Services..."
    
    local count=0
    local started=0
    
    while IFS='|' read -r channel_name frequency; do
        ((count++))
        
        # Create channel-specific paths
        local clean_name=$(echo "$channel_name" | tr ' ' '_')
        local archive_dir="$DATA_ROOT/raw_archive/$clean_name"
        local output_dir="$PRODUCTS_DIR/$clean_name"
        local log_file="$LOG_DIR/phase3-${clean_name}.log"
        local pid_file="$STATE_DIR/phase3-${clean_name}.pid"
        
        # Check if already running
        if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            continue
        fi
        
        # Start the service
        "$VENV_DIR/bin/python" -m grape_recorder.grape.phase3_products_service \
            --archive-dir "$archive_dir" \
            --output-dir "$output_dir" \
            --channel-name "$channel_name" \
            --frequency-hz "$frequency" \
            --poll-interval 60 \
            --log-level INFO \
            >> "$log_file" 2>&1 &
        
        local pid=$!
        echo "$pid" > "$pid_file"
        ((started++))
        
    done < <(get_channels)
    
    echo "   ✅ Started $started/$count Phase 3 products channels"
    echo "   📄 Logs: $LOG_DIR/phase3-*.log"
    echo "   📊 Output: $PRODUCTS_DIR/{CHANNEL}/"
}

stop_service() {
    echo "🛑 Stopping Phase 3 Products Services..."
    
    local stopped=0
    for pid_file in "$STATE_DIR"/phase3-*.pid; do
        if [[ -f "$pid_file" ]]; then
            local pid=$(cat "$pid_file")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null
                ((stopped++))
            fi
            rm -f "$pid_file"
        fi
    done
    
    echo "   ✅ Stopped $stopped Phase 3 services"
}

status_service() {
    echo "📊 Phase 3 Products Service Status:"
    
    local running=0
    local total=0
    
    for pid_file in "$STATE_DIR"/phase3-*.pid; do
        if [[ -f "$pid_file" ]]; then
            ((total++))
            local channel=$(basename "$pid_file" .pid | sed 's/phase3-//')
            local pid=$(cat "$pid_file")
            
            if kill -0 "$pid" 2>/dev/null; then
                echo "   ✅ $channel (PID: $pid)"
                ((running++))
            else
                echo "   ❌ $channel (not running)"
            fi
        fi
    done
    
    if [[ $total -eq 0 ]]; then
        echo "   No Phase 3 services configured"
    else
        echo "   Running: $running/$total"
    fi
}

case "$1" in
    -start|start)
        start_service
        ;;
    -stop|stop)
        stop_service
        ;;
    -restart|restart)
        stop_service
        sleep 2
        start_service
        ;;
    -status|status)
        status_service
        ;;
    *)
        echo "Usage: $0 {-start|-stop|-restart|-status}"
        echo ""
        echo "Phase 3 Products Service - real-time spectrogram and power generation"
        exit 1
        ;;
esac
