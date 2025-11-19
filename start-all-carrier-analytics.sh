#!/bin/bash
# Start analytics services for all carrier channels

DATA_ROOT="/tmp/grape-test"
LOG_DIR="$DATA_ROOT/logs"
STATE_DIR="$DATA_ROOT/state"

# WWV carrier channels (200 Hz)
declare -A WWV_CARRIERS=(
    ["2.5"]="2500000"
    ["5"]="5000000"
    ["10"]="10000000"
    ["15"]="15000000"
    ["20"]="20000000"
    ["25"]="25000000"
)

# CHU carrier channels (200 Hz)
declare -A CHU_CARRIERS=(
    ["3.33"]="3330000"
    ["7.85"]="7850000"
    ["14.67"]="14670000"
)

echo "Starting WWV carrier channel analytics..."
for freq in "${!WWV_CARRIERS[@]}"; do
    hz="${WWV_CARRIERS[$freq]}"
    channel_name="WWV ${freq} MHz carrier"
    channel_dir="WWV_${freq}_MHz_carrier"
    state_file="$STATE_DIR/analytics-wwv${freq}carrier.json"
    log_file="$LOG_DIR/analytics-wwv${freq}carrier.log"
    
    echo "  Starting: $channel_name"
    nohup python3 -m signal_recorder.analytics_service \
        --archive-dir "$DATA_ROOT/archives/$channel_dir" \
        --output-dir "$DATA_ROOT/analytics/$channel_dir" \
        --channel-name "$channel_name" \
        --frequency-hz "$hz" \
        --state-file "$state_file" \
        --poll-interval 10.0 \
        --backfill-gaps \
        --max-backfill 100 \
        --log-level INFO \
        --callsign AC0G \
        --grid-square EM38ww \
        --receiver-name GRAPE \
        --psws-station-id S000171 \
        --psws-instrument-id 172 \
        > "$log_file" 2>&1 &
    
    sleep 2
done

echo ""
echo "Starting CHU carrier channel analytics..."
for freq in "${!CHU_CARRIERS[@]}"; do
    hz="${CHU_CARRIERS[$freq]}"
    channel_name="CHU ${freq} MHz carrier"
    channel_dir="CHU_${freq}_MHz_carrier"
    state_file="$STATE_DIR/analytics-chu${freq}carrier.json"
    log_file="$LOG_DIR/analytics-chu${freq}carrier.log"
    
    echo "  Starting: $channel_name"
    nohup python3 -m signal_recorder.analytics_service \
        --archive-dir "$DATA_ROOT/archives/$channel_dir" \
        --output-dir "$DATA_ROOT/analytics/$channel_dir" \
        --channel-name "$channel_name" \
        --frequency-hz "$hz" \
        --state-file "$state_file" \
        --poll-interval 10.0 \
        --backfill-gaps \
        --max-backfill 100 \
        --log-level INFO \
        --callsign AC0G \
        --grid-square EM38ww \
        --receiver-name GRAPE \
        --psws-station-id S000171 \
        --psws-instrument-id 172 \
        > "$log_file" 2>&1 &
    
    sleep 2
done

echo ""
echo "All carrier analytics services started!"
echo ""
echo "Check status with:"
echo "  ps aux | grep analytics | grep carrier"
echo ""
echo "Check logs in: $LOG_DIR/analytics-*carrier.log"
