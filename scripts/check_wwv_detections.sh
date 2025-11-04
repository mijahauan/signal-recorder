#!/bin/bash
# Check WWV/CHU Detection Status
# Shows live detection statistics from running recorder

# Find most recent output directory
if [ -n "$1" ]; then
    OUTPUT_DIR="$1"
else
    OUTPUT_DIR=$(ls -dt /tmp/signal-recorder/overnight_* 2>/dev/null | head -1)
fi

if [ -z "$OUTPUT_DIR" ] || [ ! -d "$OUTPUT_DIR" ]; then
    echo "❌ No output directory found"
    echo "Usage: $0 [output_directory]"
    exit 1
fi

STATUS_FILE="${OUTPUT_DIR}/analytics/live_quality_status.json"

if [ ! -f "$STATUS_FILE" ]; then
    echo "❌ Status file not found: $STATUS_FILE"
    exit 1
fi

echo "================================================================"
echo "WWV/CHU Detection Status"
echo "================================================================"
echo "Output: ${OUTPUT_DIR}"
echo "Time: $(date)"
echo ""

# Last update time
LAST_UPDATE=$(jq -r '.last_update // "never"' "$STATUS_FILE")
echo "Last update: ${LAST_UPDATE}"
echo ""

echo "Detection Summary:"
echo "================================================================"
printf "%-15s %12s %15s %12s\n" "Channel" "Detections" "Last Error (ms)" "Minutes"

jq -r '.channels | to_entries[] | select(.value.wwv.enabled) | 
    "\(.key)\t\(.value.wwv.detections_today // 0)\t\(.value.wwv.last_error_ms // "none")\t\(.value.minutes_written)"' \
    "$STATUS_FILE" | \
while IFS=$'\t' read -r channel detections error minutes; do
    printf "%-15s %12s %15s %12s\n" "$channel" "$detections" "$error" "$minutes"
done

echo ""
echo "Recent Activity:"
echo "================================================================"

# Check for recent WWV detections in logs
LOG_FILE="${OUTPUT_DIR}/logs/recorder_combined.log"
if [ -f "$LOG_FILE" ]; then
    echo "Last 10 WWV tone detections:"
    grep "WWV tone detected" "$LOG_FILE" | tail -10 | \
        sed 's/^/  /' || echo "  No detections found in log"
else
    echo "  Log file not found"
fi

echo ""
echo "Data Collection:"
echo "================================================================"
if [ -d "${OUTPUT_DIR}/data" ]; then
    DATA_SIZE=$(du -sh "${OUTPUT_DIR}/data" | cut -f1)
    MINUTE_FILES=$(find "${OUTPUT_DIR}/data" -name "*.npz" | wc -l)
    echo "  Data size: ${DATA_SIZE}"
    echo "  Minute files: ${MINUTE_FILES}"
else
    echo "  No data directory yet"
fi

if [ -d "${OUTPUT_DIR}/analytics/quality" ]; then
    CSV_FILES=$(find "${OUTPUT_DIR}/analytics/quality" -name "*.csv" | wc -l)
    echo "  Quality CSVs: ${CSV_FILES}"
else
    echo "  No quality directory yet"
fi

echo ""
echo "================================================================"
echo "To monitor live: tail -f ${OUTPUT_DIR}/logs/recorder_combined.log"
echo "To stop: pkill -f test_v2_recorder_filtered"
echo "================================================================"
