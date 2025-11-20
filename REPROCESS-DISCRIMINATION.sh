#!/bin/bash
#
# Quick wrapper to reprocess discrimination data with coherent integration
# This regenerates discrimination CSV files from existing NPZ archives
#

set -e

DATA_ROOT="${DATA_ROOT:-/tmp/grape-test}"

echo "========================================="
echo "Reprocess Discrimination Data"
echo "with Coherent Integration"
echo "========================================="
echo

# Get today's date
TODAY=$(date -u +%Y%m%d)

echo "Available options:"
echo "  1) Reprocess today only ($TODAY)"
echo "  2) Reprocess specific date"
echo "  3) Reprocess date range"
echo "  4) Reprocess all available data"
echo

read -p "Choose option [1-4]: " CHOICE

case $CHOICE in
    1)
        read -p "Enter channel (default: WWV 10 MHz): " CHANNEL
        CHANNEL=${CHANNEL:-"WWV 10 MHz"}
        DATE=$TODAY
        echo
        echo "Reprocessing date: $DATE for $CHANNEL"
        python3 scripts/reprocess_discrimination.py \
            --data-root "$DATA_ROOT" \
            --channel "$CHANNEL" \
            --date "$DATE"
        ;;
    2)
        read -p "Enter date (YYYYMMDD): " DATE
        read -p "Enter channel (default: WWV 10 MHz): " CHANNEL
        CHANNEL=${CHANNEL:-"WWV 10 MHz"}
        echo
        echo "Reprocessing date: $DATE for $CHANNEL"
        python3 scripts/reprocess_discrimination.py \
            --data-root "$DATA_ROOT" \
            --channel "$CHANNEL" \
            --date "$DATE"
        ;;
    3)
        read -p "Enter start date (YYYYMMDD): " START_DATE
        read -p "Enter end date (YYYYMMDD): " END_DATE
        read -p "Enter channel (default: WWV 10 MHz): " CHANNEL
        CHANNEL=${CHANNEL:-"WWV 10 MHz"}
        echo
        echo "Reprocessing date range: $START_DATE to $END_DATE for $CHANNEL"
        python3 scripts/reprocess_discrimination.py \
            --data-root "$DATA_ROOT" \
            --channel "$CHANNEL" \
            --start-date "$START_DATE" \
            --end-date "$END_DATE"
        ;;
    4)
        echo
        echo "⚠️  This will reprocess ALL available discrimination data for ALL channels!"
        read -p "Are you sure? [y/N]: " CONFIRM
        if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
            echo
            echo "Reprocessing all data for all channels..."
            
            for CHANNEL in "WWV 2.5 MHz" "WWV 5 MHz" "WWV 10 MHz" "WWV 15 MHz"; do
                echo
                echo "========================================="
                echo "Processing: $CHANNEL"
                echo "========================================="
                python3 scripts/reprocess_discrimination.py \
                    --data-root "$DATA_ROOT" \
                    --channel "$CHANNEL" \
                    --all
            done
        else
            echo "Cancelled."
            exit 0
        fi
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo
echo "========================================="
echo "✅ Reprocessing Complete!"
echo "========================================="
echo
echo "View results at:"
echo "  http://localhost:3000/discrimination.html"
echo
echo "To reprocess other channels, run:"
echo "  python3 scripts/reprocess_discrimination.py --help"
echo
