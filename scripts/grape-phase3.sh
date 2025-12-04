#!/bin/bash
# GRAPE Phase 3: Product Generation (Batch Processing)
#
# Phase 3 generates decimated 10 Hz DRF products for PSWS upload:
#   - Reads Phase 1 raw archive (20 kHz Digital RF)
#   - Applies Phase 2 D_clock timing corrections
#   - Decimates 20 kHz → 10 Hz with high-quality filters
#   - Produces gap analysis and timing annotations
#
# Input:  raw_archive/{CHANNEL}/ + phase2/{CHANNEL}/clock_offset/
# Output: products/{CHANNEL}/decimated/ (PSWS-compatible DRF)
#
# This script is designed to run daily (e.g., via cron or systemd timer)
# to process the previous day's data for upload.
#
# Usage: grape-phase3.sh -yesterday|-today|-date YYYY-MM-DD [config-file]

# Source common settings (sets PYTHON, PROJECT_DIR, etc.)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ACTION=""
DATE=""
CONFIG=""

for arg in "$@"; do
    case $arg in
        -yesterday) ACTION="yesterday" ;;
        -today) ACTION="today" ;;
        -date) ACTION="date" ;;
        -status) ACTION="status" ;;
        20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]) DATE="$arg" ;;
        *) CONFIG="$arg" ;;
    esac
done

CONFIG="${CONFIG:-$DEFAULT_CONFIG}"

if [ -z "$ACTION" ]; then
    echo "Usage: $0 -yesterday|-today|-date YYYY-MM-DD|-status [config-file]"
    echo ""
    echo "Examples:"
    echo "  $0 -yesterday                    # Process yesterday's data"
    echo "  $0 -date 2025-12-04              # Process specific date"
    echo "  $0 -status                       # Show Phase 3 output status"
    exit 1
fi

DATA_ROOT=$(get_data_root "$CONFIG")

# Get station config from config file
if [ -f "$CONFIG" ]; then
    CALLSIGN=$(grep '^callsign' "$CONFIG" | head -1 | cut -d'"' -f2)
    GRID=$(grep '^grid_square' "$CONFIG" | head -1 | cut -d'"' -f2)
    STATION_ID=$(grep '^id' "$CONFIG" | head -1 | cut -d'"' -f2)
    INSTRUMENT_ID=$(grep '^instrument_id' "$CONFIG" | head -1 | cut -d'"' -f2)
else
    CALLSIGN="UNKNOWN"
    GRID="UNKNOWN"
    STATION_ID="UNKNOWN"
    INSTRUMENT_ID="1"
fi

case $ACTION in
yesterday)
    TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
    echo "📦 Phase 3: Processing yesterday ($TARGET_DATE)"
    echo "================================================================"
    echo "📁 Data root: $DATA_ROOT"
    echo "📋 Station: $CALLSIGN @ $GRID"
    echo ""
    
    cd "$PROJECT_DIR"
    $PYTHON scripts/run_phase3_processor.py \
        --data-root "$DATA_ROOT" \
        --all-channels \
        --date "$TARGET_DATE" \
        --callsign "$CALLSIGN" \
        --grid "$GRID" \
        --psws-station-id "$STATION_ID" \
        --psws-instrument-id "$INSTRUMENT_ID" \
        --log-level INFO
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "✅ Phase 3 decimation complete for $TARGET_DATE"
        echo "📦 Output: $DATA_ROOT/products/{CHANNEL}/decimated/"
        
        # Generate spectrograms from decimated data
        echo ""
        echo "📊 Generating spectrograms..."
        for channel in WWV_2.5_MHz WWV_5_MHz WWV_10_MHz WWV_15_MHz WWV_20_MHz WWV_25_MHz CHU_3.33_MHz CHU_7.85_MHz CHU_14.67_MHz; do
            channel_name="${channel//_/ }"
            $PYTHON -m grape_recorder.grape.spectrogram_generator \
                --data-root "$DATA_ROOT" \
                --channel "$channel_name" \
                --date "$TARGET_DATE" 2>/dev/null && \
            echo "   ✅ $channel_name" || echo "   ⭕ $channel_name (no data)"
        done
        echo "📊 Spectrograms: $DATA_ROOT/products/{CHANNEL}/spectrograms/"
    else
        echo ""
        echo "❌ Phase 3 failed (exit code: $EXIT_CODE)"
        exit $EXIT_CODE
    fi
    ;;

today)
    TARGET_DATE=$(date +%Y-%m-%d)
    echo "📦 Phase 3: Processing today ($TARGET_DATE) - NOTE: Data may be incomplete"
    echo "================================================================"
    echo "📁 Data root: $DATA_ROOT"
    echo ""
    
    cd "$PROJECT_DIR"
    $PYTHON scripts/run_phase3_processor.py \
        --data-root "$DATA_ROOT" \
        --all-channels \
        --date "$TARGET_DATE" \
        --callsign "$CALLSIGN" \
        --grid "$GRID" \
        --psws-station-id "$STATION_ID" \
        --psws-instrument-id "$INSTRUMENT_ID" \
        --log-level INFO
    ;;

date)
    if [ -z "$DATE" ]; then
        echo "❌ Please specify a date: $0 -date 2025-12-04"
        exit 1
    fi
    
    echo "📦 Phase 3: Processing $DATE"
    echo "================================================================"
    echo "📁 Data root: $DATA_ROOT"
    echo ""
    
    cd "$PROJECT_DIR"
    $PYTHON scripts/run_phase3_processor.py \
        --data-root "$DATA_ROOT" \
        --all-channels \
        --date "$DATE" \
        --callsign "$CALLSIGN" \
        --grid "$GRID" \
        --psws-station-id "$STATION_ID" \
        --psws-instrument-id "$INSTRUMENT_ID" \
        --log-level INFO
    ;;

status)
    echo "📊 Phase 3 Product Status"
    echo "================================================================"
    
    PRODUCTS_DIR="$DATA_ROOT/products"
    
    if [ ! -d "$PRODUCTS_DIR" ]; then
        echo "⭕ No products directory found at $PRODUCTS_DIR"
        exit 0
    fi
    
    echo "📁 Products directory: $PRODUCTS_DIR"
    echo ""
    
    # List channels with products
    for channel_dir in "$PRODUCTS_DIR"/*/; do
        if [ -d "$channel_dir" ]; then
            CHANNEL=$(basename "$channel_dir")
            
            # Count decimated days
            DECIMATED_DIR="$channel_dir/decimated"
            if [ -d "$DECIMATED_DIR" ]; then
                DAYS=$(ls -d "$DECIMATED_DIR"/20*/  2>/dev/null | wc -l)
                SIZE=$(du -sh "$DECIMATED_DIR" 2>/dev/null | cut -f1)
                echo "✅ $CHANNEL: $DAYS days, $SIZE"
            else
                echo "⭕ $CHANNEL: No decimated data"
            fi
        fi
    done
    
    echo ""
    
    # Show most recent processing
    LATEST=$(find "$PRODUCTS_DIR" -name "*_gaps.json" -type f 2>/dev/null | sort | tail -1)
    if [ -n "$LATEST" ]; then
        LATEST_DATE=$(basename "$LATEST" | cut -d'_' -f1)
        echo "📅 Most recent processing: $LATEST_DATE"
    fi
    
    # Show total size
    TOTAL_SIZE=$(du -sh "$PRODUCTS_DIR" 2>/dev/null | cut -f1)
    echo "💾 Total products size: $TOTAL_SIZE"
    ;;
esac
