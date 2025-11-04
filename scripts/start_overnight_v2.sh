#!/bin/bash
# Start V2 Recorder Overnight Data Collection
# Captures all configured channels with WWV/CHU tone detection

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="${PROJECT_DIR}/config/grape-S000171.toml"
OUTPUT_DIR="/tmp/signal-recorder/overnight_$(date +%Y%m%d)"
LOG_DIR="${OUTPUT_DIR}/logs"
DURATION=$((24 * 3600))  # 24 hours in seconds

# Create directories
mkdir -p "${OUTPUT_DIR}"
mkdir -p "${LOG_DIR}"

# Log files
STDOUT_LOG="${LOG_DIR}/recorder_stdout.log"
STDERR_LOG="${LOG_DIR}/recorder_stderr.log"
COMBINED_LOG="${LOG_DIR}/recorder_combined.log"

echo "================================================================"
echo "GRAPE V2 Recorder - Overnight Data Collection"
echo "================================================================"
echo "Start time: $(date)"
echo "Config: ${CONFIG_FILE}"
echo "Output: ${OUTPUT_DIR}"
echo "Duration: ${DURATION}s (24 hours)"
echo "Logs: ${LOG_DIR}"
echo ""
echo "Channels configured:"
echo "  - WWV: 2.5, 5, 10, 15, 20, 25 MHz (with tone detection)"
echo "  - CHU: 3.33, 7.85, 14.67 MHz (with tone detection)"
echo "  - Plus any other configured channels"
echo ""
echo "WWV/CHU Detection:"
echo "  - Window: :01.0 to :02.5 each minute"
echo "  - Threshold: 0.5 (50% of peak envelope)"
echo "  - Detection logged to INFO level"
echo ""
echo "Monitoring:"
echo "  Live status: ${OUTPUT_DIR}/analytics/live_quality_status.json"
echo "  Quality CSVs: ${OUTPUT_DIR}/analytics/quality/"
echo "  Minute files: ${OUTPUT_DIR}/data/"
echo ""
echo "To monitor:"
echo "  tail -f ${COMBINED_LOG}"
echo "  watch -n 5 'jq \".channels | to_entries[] | select(.value.wwv.enabled) | {channel: .key, detections: .value.wwv.detections_today, last_error: .value.wwv.last_error_ms}\" ${OUTPUT_DIR}/analytics/live_quality_status.json'"
echo ""
echo "To stop:"
echo "  pkill -f test_v2_recorder_filtered"
echo ""
echo "================================================================"
echo ""

# Change to project directory
cd "${PROJECT_DIR}"

# Start recorder with combined logging
python3 scripts/test_v2_recorder_filtered.py \
    --config "${CONFIG_FILE}" \
    --duration ${DURATION} \
    --output-dir "${OUTPUT_DIR}" \
    2>&1 | tee "${COMBINED_LOG}"

echo ""
echo "================================================================"
echo "Recording Complete"
echo "================================================================"
echo "End time: $(date)"
echo ""
echo "Data summary:"
du -sh "${OUTPUT_DIR}/data" 2>/dev/null || echo "  Data: No data directory"
du -sh "${OUTPUT_DIR}/analytics" 2>/dev/null || echo "  Analytics: No analytics directory"
echo ""
echo "WWV Detection Summary:"
if [ -f "${OUTPUT_DIR}/analytics/live_quality_status.json" ]; then
    jq '.channels | to_entries[] | select(.value.wwv.enabled) | {channel: .key, detections: .value.wwv.detections_today}' \
        "${OUTPUT_DIR}/analytics/live_quality_status.json"
else
    echo "  No status file found"
fi
echo ""
echo "Output saved to: ${OUTPUT_DIR}"
echo "================================================================"
