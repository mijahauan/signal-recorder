#!/bin/bash
# GRAPE Daily Upload Packager
#
# Package decimated 10 Hz binary data into PSWS-compatible DRF for upload.
# Designed to run once daily at ~00:15 UTC to process the previous day's data.
#
# Input:  phase2/{CHANNEL}/decimated/{YYYYMMDD}.bin + _meta.json
# Output: upload/{YYYYMMDD}/{CALLSIGN}_{GRID}/{RECEIVER}@{ID}/OBS.../ch0/
#
# Usage:
#   grape-daily-upload.sh -yesterday         # Package yesterday's data
#   grape-daily-upload.sh -date YYYY-MM-DD   # Package specific date
#   grape-daily-upload.sh -status            # Show upload status

# Source common settings
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
        -upload) ACTION="upload" ;;
        20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]) DATE="$arg" ;;
        *) CONFIG="$arg" ;;
    esac
done

CONFIG="${CONFIG:-$DEFAULT_CONFIG}"
DATA_ROOT=$(get_data_root "$CONFIG")

# Get station config from config file
if [ -f "$CONFIG" ]; then
    CALLSIGN=$(grep '^callsign' "$CONFIG" | head -1 | cut -d'"' -f2)
    GRID=$(grep '^grid_square' "$CONFIG" | head -1 | cut -d'"' -f2)
    STATION_ID=$(grep '^id' "$CONFIG" | head -1 | cut -d'"' -f2)
else
    CALLSIGN="${CALLSIGN:-UNKNOWN}"
    GRID="${GRID:-UNKNOWN}"
    STATION_ID="${STATION_ID:-UNKNOWN}"
fi

case $ACTION in
yesterday)
    TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
    echo "📦 Packaging yesterday ($TARGET_DATE) for upload"
    echo "================================================================"
    echo "📁 Data root: $DATA_ROOT"
    echo "📋 Station: $CALLSIGN @ $GRID"
    echo ""
    
    cd "$PROJECT_DIR"
    $PYTHON -m grape_recorder.grape.daily_drf_packager \
        --data-root "$DATA_ROOT" \
        --yesterday \
        --callsign "$CALLSIGN" \
        --grid "$GRID" \
        --log-level INFO
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "✅ Package complete"
        echo "📦 Output: $DATA_ROOT/upload/$(date -d 'yesterday' +%Y%m%d)/"
        
        # Show package size
        UPLOAD_DIR="$DATA_ROOT/upload/$(date -d 'yesterday' +%Y%m%d)"
        if [ -d "$UPLOAD_DIR" ]; then
            SIZE=$(du -sh "$UPLOAD_DIR" | cut -f1)
            echo "💾 Package size: $SIZE"
        fi
    else
        echo "❌ Packaging failed (exit code: $EXIT_CODE)"
        exit $EXIT_CODE
    fi
    ;;

date)
    if [ -z "$DATE" ]; then
        echo "❌ Please specify a date: $0 -date 2025-12-04"
        exit 1
    fi
    
    echo "📦 Packaging $DATE for upload"
    echo "================================================================"
    echo "📁 Data root: $DATA_ROOT"
    echo ""
    
    cd "$PROJECT_DIR"
    $PYTHON -m grape_recorder.grape.daily_drf_packager \
        --data-root "$DATA_ROOT" \
        --date "$DATE" \
        --callsign "$CALLSIGN" \
        --grid "$GRID" \
        --log-level INFO
    ;;

status)
    echo "📦 Upload Package Status"
    echo "================================================================"
    
    UPLOAD_DIR="$DATA_ROOT/upload"
    
    if [ ! -d "$UPLOAD_DIR" ]; then
        echo "⭕ No upload directory found at $UPLOAD_DIR"
        exit 0
    fi
    
    echo "📁 Upload directory: $UPLOAD_DIR"
    echo ""
    
    # List packaged dates
    for date_dir in "$UPLOAD_DIR"/*/; do
        if [ -d "$date_dir" ]; then
            DATE=$(basename "$date_dir")
            SIZE=$(du -sh "$date_dir" 2>/dev/null | cut -f1)
            
            # Check for gap summary
            GAP_FILE=$(find "$date_dir" -name "gap_summary.json" 2>/dev/null | head -1)
            if [ -n "$GAP_FILE" ]; then
                COMPLETENESS=$(grep -o '"completeness_pct":[^,}]*' "$GAP_FILE" 2>/dev/null | head -1 | cut -d':' -f2)
                echo "✅ $DATE: $SIZE, ${COMPLETENESS:-?}% complete"
            else
                echo "✅ $DATE: $SIZE"
            fi
        fi
    done
    
    echo ""
    
    # Show total size
    TOTAL_SIZE=$(du -sh "$UPLOAD_DIR" 2>/dev/null | cut -f1)
    echo "💾 Total upload size: $TOTAL_SIZE"
    ;;

upload)
    echo "📤 Upload to GRAPE repository"
    echo "================================================================"
    echo ""
    echo "⚠️  Actual upload not yet implemented"
    echo ""
    echo "To manually upload:"
    echo "  rsync -av $DATA_ROOT/upload/ user@grape-server:/incoming/"
    echo ""
    ;;

*)
    echo "Usage: $0 <action> [options]"
    echo ""
    echo "Actions:"
    echo "  -yesterday           Package yesterday's data for upload"
    echo "  -date YYYY-MM-DD     Package specific date"
    echo "  -status              Show upload package status"
    echo "  -upload              Upload packages to GRAPE repository"
    echo ""
    echo "Environment:"
    echo "  CALLSIGN             Station callsign (or set in config)"
    echo "  GRID                 Grid square (or set in config)"
    echo ""
    echo "Examples:"
    echo "  $0 -yesterday                    # Package yesterday"
    echo "  $0 -date 2025-12-05              # Package specific date"
    echo "  $0 -status                       # Show what's ready for upload"
    exit 1
    ;;
esac
