#!/bin/bash
# GRAPE Analytics Services Control (all 9 channels)
# Usage: grape-analytics.sh -start|-stop|-status [config-file]

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
    echo "▶️  Starting Analytics Services..."
    
    # Stop existing first
    pkill -f "grape_recorder.grape.analytics_service" 2>/dev/null
    sleep 1
    
    if [ ! -f "$CONFIG" ]; then
        echo "   ❌ Config not found: $CONFIG"
        exit 1
    fi
    
    CALLSIGN=$(grep '^callsign' "$CONFIG" | head -1 | cut -d'"' -f2)
    GRID=$(grep '^grid_square' "$CONFIG" | head -1 | cut -d'"' -f2)
    STATION_ID=$(grep '^id' "$CONFIG" | head -1 | cut -d'"' -f2)
    INSTRUMENT_ID=$(grep '^instrument_id' "$CONFIG" | head -1 | cut -d'"' -f2)
    
    mkdir -p "$DATA_ROOT/logs" "$DATA_ROOT/state"
    cd "$PROJECT_DIR"
    
    # WWV Channels
    for freq_mhz in 2.5 5 10 15 20 25; do
        freq_hz=$(echo "$freq_mhz * 1000000" | bc | cut -d. -f1)
        channel_dir="WWV_${freq_mhz}_MHz"
        
        nohup python3 -m grape_recorder.grape.analytics_service \
          --archive-dir "$DATA_ROOT/archives/$channel_dir" \
          --output-dir "$DATA_ROOT/analytics/$channel_dir" \
          --channel-name "WWV ${freq_mhz} MHz" \
          --frequency-hz "$freq_hz" \
          --state-file "$DATA_ROOT/state/analytics-wwv${freq_mhz}.json" \
          --poll-interval 10.0 --backfill-gaps --max-backfill 100 \
          --log-level INFO \
          --callsign "$CALLSIGN" --grid-square "$GRID" \
          --receiver-name "GRAPE" \
          --psws-station-id "$STATION_ID" --psws-instrument-id "$INSTRUMENT_ID" \
          > "$DATA_ROOT/logs/analytics-wwv${freq_mhz}.log" 2>&1 &
        
        sleep 0.2
    done
    
    # CHU Channels
    declare -A CHU_FREQS=( ["3.33"]="3330000" ["7.85"]="7850000" ["14.67"]="14670000" )
    
    for freq_mhz in 3.33 7.85 14.67; do
        freq_hz=${CHU_FREQS[$freq_mhz]}
        channel_dir="CHU_${freq_mhz}_MHz"
        
        nohup python3 -m grape_recorder.grape.analytics_service \
          --archive-dir "$DATA_ROOT/archives/$channel_dir" \
          --output-dir "$DATA_ROOT/analytics/$channel_dir" \
          --channel-name "CHU ${freq_mhz} MHz" \
          --frequency-hz "$freq_hz" \
          --state-file "$DATA_ROOT/state/analytics-chu${freq_mhz}.json" \
          --poll-interval 10.0 --backfill-gaps --max-backfill 100 \
          --log-level INFO \
          --callsign "$CALLSIGN" --grid-square "$GRID" \
          --receiver-name "GRAPE" \
          --psws-station-id "$STATION_ID" --psws-instrument-id "$INSTRUMENT_ID" \
          > "$DATA_ROOT/logs/analytics-chu${freq_mhz}.log" 2>&1 &
        
        sleep 0.2
    done
    
    sleep 2
    COUNT=$(pgrep -f "grape_recorder.grape.analytics_service" 2>/dev/null | wc -l)
    echo "   ✅ Started $COUNT/9 channels"
    echo "   📄 Logs: $DATA_ROOT/logs/analytics-*.log"
    ;;

stop)
    echo "🛑 Stopping Analytics Services..."
    
    COUNT=$(pgrep -f "grape_recorder.grape.analytics_service" 2>/dev/null | wc -l)
    if [ "$COUNT" -eq 0 ]; then
        echo "   ℹ️  Not running"
        exit 0
    fi
    
    pkill -f "grape_recorder.grape.analytics_service" 2>/dev/null
    sleep 2
    
    REMAINING=$(pgrep -f "grape_recorder.grape.analytics_service" 2>/dev/null | wc -l)
    if [ "$REMAINING" -gt 0 ]; then
        pkill -9 -f "grape_recorder.grape.analytics_service" 2>/dev/null
    fi
    
    echo "   ✅ Stopped $COUNT services"
    ;;

status)
    COUNT=$(pgrep -f "grape_recorder.grape.analytics_service" 2>/dev/null | wc -l)
    if [ "$COUNT" -gt 0 ]; then
        echo "✅ Analytics: RUNNING ($COUNT/9 channels)"
    else
        echo "⭕ Analytics: STOPPED"
    fi
    ;;
esac
