#!/bin/bash
# GRAPE Spectrogram Generator
#
# Generate carrier spectrograms from the decimated 10 Hz binary buffer.
# Can run on-demand or periodically (e.g., every 10 minutes via cron).
#
# Usage:
#   grape-spectrogram.sh -rolling [hours]    # Generate rolling spectrograms (default: 6h)
#   grape-spectrogram.sh -daily YYYYMMDD     # Generate daily spectrogram
#   grape-spectrogram.sh -all                # Generate all rolling spectrograms (6h, 12h, 24h)
#   grape-spectrogram.sh -status             # Show spectrogram status

# Source common settings
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ACTION=""
HOURS=6
DATE=""
CHANNEL=""

for arg in "$@"; do
    case $arg in
        -rolling) ACTION="rolling" ;;
        -daily) ACTION="daily" ;;
        -all) ACTION="all" ;;
        -status) ACTION="status" ;;
        -channel) ACTION="channel" ;;
        [0-9]|[0-9][0-9]) HOURS="$arg" ;;
        20[0-9][0-9][0-1][0-9][0-3][0-9]) DATE="$arg" ;;
        "WWV"*|"CHU"*) CHANNEL="$arg" ;;
        *) 
            if [ -z "$CHANNEL" ] && [[ "$arg" =~ ^[A-Za-z] ]]; then
                CHANNEL="$arg"
            fi
            ;;
    esac
done

DATA_ROOT=$(get_data_root "$DEFAULT_CONFIG")

# Get grid square from config for solar zenith overlay
if [ -f "$DEFAULT_CONFIG" ]; then
    GRID=$(grep '^grid_square' "$DEFAULT_CONFIG" | head -1 | cut -d'"' -f2)
fi
GRID="${GRID:-}"

case $ACTION in
rolling)
    echo "📊 Generating ${HOURS}h rolling spectrograms..."
    [ -n "$GRID" ] && echo "   Grid: $GRID (for solar zenith)"
    cd "$PROJECT_DIR"
    
    if [ -n "$CHANNEL" ]; then
        $PYTHON -m grape_recorder.grape.carrier_spectrogram \
            --data-root "$DATA_ROOT" \
            --channel "$CHANNEL" \
            --hours "$HOURS" \
            --grid "$GRID"
    else
        $PYTHON -m grape_recorder.grape.carrier_spectrogram \
            --data-root "$DATA_ROOT" \
            --all-channels \
            --hours "$HOURS" \
            --grid "$GRID"
    fi
    ;;

daily)
    if [ -z "$DATE" ]; then
        DATE=$(date -d yesterday +%Y%m%d)
    fi
    
    echo "📊 Generating daily spectrograms for $DATE..."
    [ -n "$GRID" ] && echo "   Grid: $GRID (for solar zenith overlay)"
    cd "$PROJECT_DIR"
    
    if [ -n "$CHANNEL" ]; then
        $PYTHON -m grape_recorder.grape.carrier_spectrogram \
            --data-root "$DATA_ROOT" \
            --channel "$CHANNEL" \
            --date "$DATE" \
            --grid "$GRID"
    else
        for channel in "WWV 2.5 MHz" "WWV 5 MHz" "WWV 10 MHz" "WWV 15 MHz" "WWV 20 MHz" "WWV 25 MHz" "CHU 3.33 MHz" "CHU 7.85 MHz" "CHU 14.67 MHz"; do
            echo "  Processing $channel..."
            $PYTHON -m grape_recorder.grape.carrier_spectrogram \
                --data-root "$DATA_ROOT" \
                --channel "$channel" \
                --date "$DATE" \
                --grid "$GRID" 2>/dev/null && echo "    ✅ Done" || echo "    ⭕ No data"
        done
    fi
    ;;

all)
    echo "📊 Generating all rolling spectrograms (6h, 12h, 24h)..."
    [ -n "$GRID" ] && echo "   Grid: $GRID (for solar zenith)"
    cd "$PROJECT_DIR"
    
    for hours in 6 12 24; do
        echo "  Generating ${hours}h spectrograms..."
        $PYTHON -m grape_recorder.grape.carrier_spectrogram \
            --data-root "$DATA_ROOT" \
            --all-channels \
            --hours "$hours" \
            --grid "$GRID"
    done
    ;;

status)
    echo "📊 Spectrogram Status"
    echo "================================================================"
    
    PRODUCTS_DIR="$DATA_ROOT/products"
    
    if [ ! -d "$PRODUCTS_DIR" ]; then
        echo "⭕ No products directory found"
        exit 0
    fi
    
    for channel_dir in "$PRODUCTS_DIR"/*/; do
        if [ -d "$channel_dir/spectrograms" ]; then
            CHANNEL=$(basename "$channel_dir")
            COUNT=$(find "$channel_dir/spectrograms" -name "*.png" 2>/dev/null | wc -l)
            LATEST=$(find "$channel_dir/spectrograms" -name "rolling_*.png" -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
            
            if [ -n "$LATEST" ]; then
                AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST")) / 60 ))
                echo "✅ $CHANNEL: $COUNT images, latest ${AGE}m ago"
            else
                echo "⭕ $CHANNEL: $COUNT images"
            fi
        fi
    done
    ;;

*)
    echo "Usage: $0 <action> [options]"
    echo ""
    echo "Actions:"
    echo "  -rolling [hours]     Generate rolling spectrograms (default: 6h)"
    echo "  -daily [YYYYMMDD]    Generate daily spectrogram (default: yesterday)"
    echo "  -all                 Generate all rolling spectrograms (6h, 12h, 24h)"
    echo "  -status              Show spectrogram status"
    echo ""
    echo "Options:"
    echo "  -channel \"NAME\"      Process specific channel (e.g., \"WWV 10 MHz\")"
    echo ""
    echo "Examples:"
    echo "  $0 -rolling 6                    # 6-hour rolling for all channels"
    echo "  $0 -daily 20251205               # Daily for specific date"
    echo "  $0 -rolling -channel \"WWV 10 MHz\"  # Single channel"
    exit 1
    ;;
esac

echo "✅ Spectrogram generation complete"
