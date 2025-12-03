#!/bin/bash
# =============================================================================
# Daily DRF Upload Script (Multi-Subchannel Version)
# =============================================================================
# Creates wsprdaemon-compatible Digital RF with all frequencies in single ch0
# and uploads to PSWS server with trigger directory signaling.
#
# Designed to run daily via systemd timer at 00:30 UTC
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source common settings (includes environment file loading)
source "$SCRIPT_DIR/common.sh"

# Configuration (from environment or fallback to defaults)
CONFIG_FILE="${GRAPE_CONFIG:-$PROJECT_ROOT/config/grape-config.toml}"
DATA_ROOT="${GRAPE_DATA_ROOT:-$(get_data_root "$CONFIG_FILE")}"
VENV_PATH="${GRAPE_VENV:-$PROJECT_ROOT/venv}"
LOG_DIR="${GRAPE_LOG_DIR:-$DATA_ROOT/logs}"
LOG_FILE="${LOG_DIR}/daily-upload.log"

# PSWS upload settings (can be overridden via environment)
SFTP_HOST="${GRAPE_PSWS_HOST:-pswsnetwork.eng.ua.edu}"
SFTP_USER="${GRAPE_PSWS_USER:-S000171}"
SSH_KEY="${GRAPE_SSH_KEY:-$HOME/.ssh/id_rsa}"
BANDWIDTH_LIMIT="${GRAPE_BANDWIDTH_LIMIT:-0}"

# Station info - read from config file
read_config_value() {
    local key="$1"
    local default="$2"
    grep "^$key" "$CONFIG_FILE" 2>/dev/null | cut -d'"' -f2 || echo "$default"
}

CALLSIGN="${GRAPE_CALLSIGN:-$(read_config_value 'callsign' 'AC0G')}"
GRID_SQUARE="${GRAPE_GRID_SQUARE:-$(read_config_value 'grid_square' 'EM38ww')}"
RECEIVER_NAME="GRAPE"
PSWS_STATION_ID="${GRAPE_STATION_ID:-$(read_config_value 'id' 'S000171')}"
PSWS_INSTRUMENT_ID="${GRAPE_INSTRUMENT_ID:-$(read_config_value 'instrument_id' '172')}"

# Extended metadata flag (from config)
INCLUDE_EXTENDED_METADATA="${INCLUDE_EXTENDED_METADATA:-false}"

# Upload state tracking
UPLOAD_STATE_FILE="${DATA_ROOT}/upload/upload-state.json"

# Date handling
if [[ -n "${TARGET_DATE:-}" ]]; then
    YESTERDAY="$TARGET_DATE"
else
    YESTERDAY=$(date -u -d "yesterday" +%Y-%m-%d)
fi
YESTERDAY_YYYYMMDD=$(date -u -d "$YESTERDAY" +%Y%m%d)

# Logging function
log() {
    local level="$1"
    shift
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [$level] $*" | tee -a "$LOG_FILE"
}

# Ensure directories exist
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$UPLOAD_STATE_FILE")"

log "INFO" "=========================================="
log "INFO" "Daily DRF Upload Starting"
log "INFO" "Target date: $YESTERDAY ($YESTERDAY_YYYYMMDD)"
log "INFO" "Data root: $DATA_ROOT"
log "INFO" "=========================================="

# Activate virtual environment
if [[ -d "$VENV_PATH" ]]; then
    source "$VENV_PATH/bin/activate"
    log "INFO" "Activated venv: $VENV_PATH"
else
    log "ERROR" "Virtual environment not found: $VENV_PATH"
    exit 1
fi

# Check if already uploaded using tracker
ALREADY_UPLOADED=$(python -m grape_recorder.upload_tracker \
    --state-file "$UPLOAD_STATE_FILE" \
    --station-id "$PSWS_STATION_ID" \
    check --date "$YESTERDAY" 2>/dev/null || echo "false")

if [[ "$ALREADY_UPLOADED" == "true" ]]; then
    log "INFO" "Date $YESTERDAY already uploaded successfully, skipping"
    exit 0
fi

# Output directories
OUTPUT_DIR="$DATA_ROOT/upload/$YESTERDAY_YYYYMMDD"
OBS_DATE=$(date -u -d "$YESTERDAY" +%Y-%m-%dT00-00)
OBS_DIR_NAME="OBS$OBS_DATE"

log "INFO" "Output directory: $OUTPUT_DIR"

# Build extended metadata flag
EXTENDED_FLAG=""
if [[ "$INCLUDE_EXTENDED_METADATA" == "true" ]]; then
    EXTENDED_FLAG="--include-extended-metadata"
    log "INFO" "Extended metadata: ENABLED"
else
    log "INFO" "Extended metadata: disabled (wsprdaemon-compatible only)"
fi

# Run multi-subchannel DRF batch writer
log "INFO" "Creating multi-subchannel DRF dataset..."
START_TIME=$(date +%s)

python -m grape_recorder.drf_batch_writer \
    --analytics-root "$DATA_ROOT/analytics" \
    --output-dir "$OUTPUT_DIR" \
    --date "$YESTERDAY" \
    --callsign "$CALLSIGN" \
    --grid-square "$GRID_SQUARE" \
    --receiver-name "$RECEIVER_NAME" \
    --psws-station-id "$PSWS_STATION_ID" \
    --psws-instrument-id "$PSWS_INSTRUMENT_ID" \
    $EXTENDED_FLAG \
    --log-level INFO 2>&1 | tee -a "$LOG_FILE"

DRF_STATUS=${PIPESTATUS[0]}

if [[ $DRF_STATUS -ne 0 ]]; then
    log "ERROR" "DRF batch writer failed"
    python -m grape_recorder.upload_tracker \
        --state-file "$UPLOAD_STATE_FILE" \
        --station-id "$PSWS_STATION_ID" \
        record --date "$YESTERDAY" --status failed --error "DRF batch writer failed"
    exit 1
fi

# Find the generated OBS directory
OBS_PATH="$OUTPUT_DIR/${CALLSIGN}_${GRID_SQUARE}/${RECEIVER_NAME}@${PSWS_STATION_ID}_${PSWS_INSTRUMENT_ID}/$OBS_DIR_NAME"

if [[ ! -d "$OBS_PATH" ]]; then
    log "ERROR" "OBS directory not found: $OBS_PATH"
    python -m grape_recorder.upload_tracker \
        --state-file "$UPLOAD_STATE_FILE" \
        --station-id "$PSWS_STATION_ID" \
        record --date "$YESTERDAY" --status failed --error "OBS directory not created"
    exit 1
fi

# Calculate upload size
UPLOAD_SIZE=$(du -sb "$OBS_PATH" | cut -f1)
log "INFO" "OBS directory size: $(numfmt --to=iec $UPLOAD_SIZE)"

# Count channels (subchannels in ch0)
NUM_CHANNELS=$(python3 -c "
import digital_rf as drf
import os
ch_dir = '$OBS_PATH/ch0'
if os.path.exists(ch_dir + '/drf_properties.h5'):
    reader = drf.DigitalRFReader(os.path.dirname(ch_dir))
    props = reader.get_properties('ch0')
    print(props.get('num_subchannels', 1))
else:
    print(1)
" 2>/dev/null || echo "9")

log "INFO" "Number of subchannels: $NUM_CHANNELS"

# Create SFTP batch file
# Trigger dir format: cOBS{date}_#{instrument_id}_#{timestamp}
# The # characters must be escaped as \# for SFTP
TRIGGER_TIMESTAMP=$(date -u +%Y-%m%dT%H-%M)
TRIGGER_DIR="c${OBS_DIR_NAME}_\#${PSWS_INSTRUMENT_ID}_\#${TRIGGER_TIMESTAMP}"
SFTP_BATCH="/tmp/sftp_daily_upload_$$.txt"

# Need to upload from parent of OBS directory
UPLOAD_BASE="$OUTPUT_DIR/${CALLSIGN}_${GRID_SQUARE}/${RECEIVER_NAME}@${PSWS_STATION_ID}_${PSWS_INSTRUMENT_ID}"

# Write SFTP batch file - # chars are escaped with backslash
cat > "$SFTP_BATCH" << EOF
put -r $OBS_DIR_NAME
mkdir $TRIGGER_DIR
EOF

log "INFO" "=========================================="
log "INFO" "Uploading to PSWS"
log "INFO" "  Host: $SFTP_HOST"
log "INFO" "  User: $SFTP_USER"
log "INFO" "  OBS: $OBS_DIR_NAME"
log "INFO" "  Trigger: $TRIGGER_DIR"
if [[ "$BANDWIDTH_LIMIT" -gt 0 ]]; then
    log "INFO" "  Bandwidth limit: ${BANDWIDTH_LIMIT} kbps"
else
    log "INFO" "  Bandwidth limit: unlimited"
fi
log "INFO" "=========================================="

# Execute upload
cd "$UPLOAD_BASE"
log "INFO" "Working directory: $(pwd)"

UPLOAD_START=$(date +%s)

# Build sftp command - only add bandwidth limit if non-zero
SFTP_CMD="sftp -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=60"
if [[ "$BANDWIDTH_LIMIT" -gt 0 ]]; then
    SFTP_CMD="$SFTP_CMD -l $BANDWIDTH_LIMIT"
fi
SFTP_CMD="$SFTP_CMD -b $SFTP_BATCH ${SFTP_USER}@${SFTP_HOST}"

log "DEBUG" "Running: $SFTP_CMD"
$SFTP_CMD 2>&1 | tee -a "$LOG_FILE"
UPLOAD_STATUS=${PIPESTATUS[0]}
UPLOAD_END=$(date +%s)
UPLOAD_DURATION=$((UPLOAD_END - UPLOAD_START))

rm -f "$SFTP_BATCH"

END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))

if [[ $UPLOAD_STATUS -eq 0 ]]; then
    log "INFO" "✅ Upload successful!"
    log "INFO" "  Duration: ${UPLOAD_DURATION}s (total: ${TOTAL_DURATION}s)"
    log "INFO" "  Size: $(numfmt --to=iec $UPLOAD_SIZE)"
    
    # Record success
    python -m grape_recorder.upload_tracker \
        --state-file "$UPLOAD_STATE_FILE" \
        --station-id "$PSWS_STATION_ID" \
        record \
        --date "$YESTERDAY" \
        --status success \
        --channels "$NUM_CHANNELS" \
        --obs-dir "$OBS_DIR_NAME" \
        --trigger-dir "$TRIGGER_DIR" \
        --bytes "$UPLOAD_SIZE" \
        --duration "$UPLOAD_DURATION"
    
    log "INFO" "Upload recorded in state file"
else
    log "ERROR" "❌ Upload failed with status $UPLOAD_STATUS"
    
    # Record failure
    python -m grape_recorder.upload_tracker \
        --state-file "$UPLOAD_STATE_FILE" \
        --station-id "$PSWS_STATION_ID" \
        record \
        --date "$YESTERDAY" \
        --status failed \
        --error "SFTP upload failed with status $UPLOAD_STATUS"
    
    exit 1
fi

log "INFO" "=========================================="
log "INFO" "Daily DRF Upload Complete"
log "INFO" "=========================================="
