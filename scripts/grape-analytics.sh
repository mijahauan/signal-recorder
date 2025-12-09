#!/bin/bash
# GRAPE Phase 2 Analytics Services Control (all 9 channels)
#
# Phase 2 processes raw archive data to produce:
#   - D_clock (timing correction for UTC alignment)
#   - Station discrimination (WWV vs WWVH)
#   - Quality metrics and tone detections
#   - 10-second sliding window monitoring
#
# Input:  raw_archive/{CHANNEL}/ (20 kHz Digital RF from Phase 1)
# Output: phase2/{CHANNEL}/      (timing analysis, clock offset CSV)
#
# Usage: grape-analytics.sh -start|-stop|-status [config-file]

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
    echo "▶️  Starting Phase 2 Analytics Services..."
    
    # Stop existing first
    pkill -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null
    sleep 1
    
    if [ ! -f "$CONFIG" ]; then
        echo "   ❌ Config not found: $CONFIG"
        exit 1
    fi
    
    CALLSIGN=$(grep '^callsign' "$CONFIG" | head -1 | cut -d'"' -f2)
    GRID=$(grep '^grid_square' "$CONFIG" | head -1 | cut -d'"' -f2)
    STATION_ID=$(grep '^id' "$CONFIG" | head -1 | cut -d'"' -f2)
    INSTRUMENT_ID=$(grep '^instrument_id' "$CONFIG" | head -1 | cut -d'"' -f2)
    
    # Precise coordinates for improved timing accuracy (~16μs improvement)
    LATITUDE=$(grep '^latitude' "$CONFIG" | head -1 | awk '{print $3}')
    LONGITUDE=$(grep '^longitude' "$CONFIG" | head -1 | awk '{print $3}')
    
    # Build coordinate args if available
    COORD_ARGS=""
    if [ -n "$LATITUDE" ] && [ -n "$LONGITUDE" ]; then
        COORD_ARGS="--latitude $LATITUDE --longitude $LONGITUDE"
        echo "   📍 Using precise coordinates: ${LATITUDE}°N, ${LONGITUDE}°W"
    fi
    
    # Create directories for three-phase structure
    mkdir -p "$DATA_ROOT/logs" "$DATA_ROOT/state" "$DATA_ROOT/status"
    mkdir -p "$DATA_ROOT/phase2" "$DATA_ROOT/products"
    cd "$PROJECT_DIR"
    
    # WWV Channels (PYTHON is set by common.sh)
    # Input: raw_archive/WWV_X_MHz/ (Phase 1 DRF)
    # Output: phase2/WWV_X_MHz/    (D_clock, timing metrics)
    for freq_mhz in 2.5 5 10 15 20 25; do
        freq_hz=$(echo "$freq_mhz * 1000000" | bc | cut -d. -f1)
        channel_dir="WWV_${freq_mhz}_MHz"
        
        # Phase 2 reads from raw_archive (Phase 1 output)
        # and writes timing analysis to phase2/
        # Run at lower priority (nice 10) on cores 8-15 to not interfere with radiod/recorder
        nohup taskset -c 8-15 nice -n 10 $PYTHON -m grape_recorder.grape.phase2_analytics_service \
          --archive-dir "$DATA_ROOT/raw_archive/$channel_dir" \
          --output-dir "$DATA_ROOT/phase2/$channel_dir" \
          --channel-name "WWV ${freq_mhz} MHz" \
          --frequency-hz "$freq_hz" \
          --state-file "$DATA_ROOT/state/phase2-wwv${freq_mhz}.json" \
          --poll-interval 10.0 --backfill-gaps --max-backfill 100 \
          --log-level INFO \
          --callsign "$CALLSIGN" --grid-square "$GRID" \
          --receiver-name "GRAPE" \
          --psws-station-id "$STATION_ID" --psws-instrument-id "$INSTRUMENT_ID" \
          $COORD_ARGS \
          > "$DATA_ROOT/logs/phase2-wwv${freq_mhz}.log" 2>&1 &
        
        sleep 0.2
    done
    
    # CHU Channels
    declare -A CHU_FREQS=( ["3.33"]="3330000" ["7.85"]="7850000" ["14.67"]="14670000" )
    
    for freq_mhz in 3.33 7.85 14.67; do
        freq_hz=${CHU_FREQS[$freq_mhz]}
        channel_dir="CHU_${freq_mhz}_MHz"
        
        # Run at lower priority (nice 10) on cores 8-15 to not interfere with radiod/recorder
        nohup taskset -c 8-15 nice -n 10 $PYTHON -m grape_recorder.grape.phase2_analytics_service \
          --archive-dir "$DATA_ROOT/raw_archive/$channel_dir" \
          --output-dir "$DATA_ROOT/phase2/$channel_dir" \
          --channel-name "CHU ${freq_mhz} MHz" \
          --frequency-hz "$freq_hz" \
          --state-file "$DATA_ROOT/state/phase2-chu${freq_mhz}.json" \
          --poll-interval 10.0 --backfill-gaps --max-backfill 100 \
          --log-level INFO \
          --callsign "$CALLSIGN" --grid-square "$GRID" \
          --receiver-name "GRAPE" \
          --psws-station-id "$STATION_ID" --psws-instrument-id "$INSTRUMENT_ID" \
          $COORD_ARGS \
          > "$DATA_ROOT/logs/phase2-chu${freq_mhz}.log" 2>&1 &
        
        sleep 0.2
    done
    
    sleep 2
    COUNT=$(pgrep -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null | wc -l)
    echo "   ✅ Started $COUNT/9 Phase 2 analytics channels"
    
    # Start Multi-Broadcast Fusion Service
    # Combines all 13 broadcasts (6 WWV + 4 WWVH + 3 CHU) for UTC(NIST) convergence
    pkill -f "grape_recorder.grape.multi_broadcast_fusion" 2>/dev/null
    sleep 0.5
    nohup $PYTHON -m grape_recorder.grape.multi_broadcast_fusion \
      --data-root "$DATA_ROOT" \
      --interval 60.0 \
      --log-level INFO \
      > "$DATA_ROOT/logs/phase2-fusion.log" 2>&1 &
    echo "   🔀 Started Multi-Broadcast Fusion (13 broadcasts → UTC(NIST))"
    
    echo "   📄 Logs: $DATA_ROOT/logs/phase2-*.log"
    echo "   📊 Output: $DATA_ROOT/phase2/{CHANNEL}/clock_offset/"
    echo "   🎯 Fusion: $DATA_ROOT/phase2/fusion/fused_d_clock.csv"
    ;;

stop)
    echo "🛑 Stopping Phase 2 Analytics Services..."
    
    # Stop fusion service first
    pkill -f "grape_recorder.grape.multi_broadcast_fusion" 2>/dev/null
    
    COUNT=$(pgrep -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null | wc -l)
    if [ "$COUNT" -eq 0 ]; then
        echo "   ℹ️  Not running"
        exit 0
    fi
    
    pkill -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null
    sleep 2
    
    REMAINING=$(pgrep -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null | wc -l)
    if [ "$REMAINING" -gt 0 ]; then
        pkill -9 -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null
    fi
    
    echo "   ✅ Stopped $COUNT Phase 2 services + fusion"
    ;;

status)
    COUNT=$(pgrep -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null | wc -l)
    if [ "$COUNT" -gt 0 ]; then
        echo "✅ Phase 2 Analytics: RUNNING ($COUNT/9 channels)"
        echo "   Input:  $DATA_ROOT/raw_archive/{CHANNEL}/"
        echo "   Output: $DATA_ROOT/phase2/{CHANNEL}/clock_offset/"
    else
        echo "⭕ Phase 2 Analytics: STOPPED"
    fi
    ;;
esac
