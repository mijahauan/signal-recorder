#!/bin/bash
# Start GRAPE Signal Recorder - Dual Service Architecture
# Starts: Core Recorder + Analytics Service (all channels) + Web-UI

set -e

# Configuration
CONFIG="${1:-config/grape-config.toml}"

if [ ! -f "$CONFIG" ]; then
    echo "❌ Config file not found: $CONFIG"
    echo "Usage: $0 [config-file]"
    exit 1
fi

echo "🚀 Starting GRAPE Signal Recorder (Dual-Service Architecture)"
echo "================================================================"
echo ""

# Get mode and data_root from config
MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
if [ "$MODE" = "production" ]; then
    DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
    MODE_ICON="🚀"
    MODE_TEXT="PRODUCTION"
else
    DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
    MODE_ICON="🧪"
    MODE_TEXT="TEST"
fi

if [ -z "$DATA_ROOT" ]; then
    DATA_ROOT="/tmp/grape-test"
    echo "⚠️  Could not read data_root from config, using default: $DATA_ROOT"
fi

# Get station metadata from config
CALLSIGN=$(grep '^callsign' "$CONFIG" | head -1 | cut -d'"' -f2)
GRID=$(grep '^grid_square' "$CONFIG" | head -1 | cut -d'"' -f2)
STATION_ID=$(grep '^id' "$CONFIG" | head -1 | cut -d'"' -f2)
INSTRUMENT_ID=$(grep '^instrument_id' "$CONFIG" | head -1 | cut -d'"' -f2)

echo "📋 Configuration:"
echo "   Config file: $CONFIG"
echo "   Mode: $MODE_ICON $MODE_TEXT"
echo "   Data root: $DATA_ROOT"
echo "   Station: $CALLSIGN ($GRID)"
echo ""

# ============================================================================
# Check System Timing
# ============================================================================
echo "🕐 Checking system timing..."

if timedatectl status 2>/dev/null | grep -q "System clock synchronized: yes"; then
    echo "   ✅ NTP synchronized"
    echo "   Cold start will use NTP_SYNCED quality (±10ms)"
else
    echo ""
    echo "   ⚠️  WARNING: NTP NOT synchronized"
    echo "   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "   Cold start will use WALL_CLOCK quality (±seconds)"
    echo ""
    echo "   Timing will improve when:"
    echo "   • NTP sync is established, OR"
    echo "   • WWV/CHU tone detected (→ GPS_LOCKED quality)"
    echo ""
    echo "   Data will still be recorded with quality annotations."
    echo "   Low-quality segments can be reprocessed later."
    echo "   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
fi
echo ""

# Stop any existing instances
echo "🛑 Stopping existing instances..."
pkill -f core_recorder 2>/dev/null || true
pkill -f analytics_service 2>/dev/null || true
pkill -f monitoring-server.js 2>/dev/null || true
sleep 2

# Create directories
mkdir -p "$DATA_ROOT/logs"
mkdir -p "$DATA_ROOT/state"
mkdir -p "$DATA_ROOT/status"
echo ""

# ============================================================================
# Step 1: Start Core Recorder
# ============================================================================
echo "▶️  Step 1: Starting Core Recorder..."
CORE_LOG="$DATA_ROOT/logs/core-recorder.log"

nohup python3 -m signal_recorder.core_recorder \
  --config "$CONFIG" \
  > "$CORE_LOG" 2>&1 &

CORE_PID=$!
sleep 3

# Verify core recorder started
if ps -p $CORE_PID > /dev/null 2>&1; then
    echo "   ✅ Core Recorder started (PID: $CORE_PID)"
    echo "   📄 Log: $CORE_LOG"
else
    echo "   ❌ Core Recorder failed to start"
    echo "   Check log: tail -f $CORE_LOG"
    exit 1
fi
echo ""

# ============================================================================
# Step 2: Start Analytics Services (one per channel)
# ============================================================================
echo "▶️  Step 2: Starting Analytics Services..."

# WWV Channels (6)
for freq_mhz in 2.5 5 10 15 20 25; do
    freq_hz=$(echo "$freq_mhz * 1000000" | bc | cut -d. -f1)
    # Match core recorder naming: "WWV 2.5 MHz" -> "WWV_2.5_MHz" (preserve dots)
    channel_dir="WWV_${freq_mhz}_MHz"
    
    echo "   Starting: WWV ${freq_mhz} MHz..."
    
    nohup python3 -m signal_recorder.analytics_service \
      --archive-dir "$DATA_ROOT/archives/$channel_dir" \
      --output-dir "$DATA_ROOT/analytics/$channel_dir" \
      --channel-name "WWV ${freq_mhz} MHz" \
      --frequency-hz "$freq_hz" \
      --state-file "$DATA_ROOT/state/analytics-wwv${freq_mhz}.json" \
      --poll-interval 10.0 \
      --log-level INFO \
      --callsign "$CALLSIGN" \
      --grid-square "$GRID" \
      --receiver-name "GRAPE" \
      --psws-station-id "$STATION_ID" \
      --psws-instrument-id "$INSTRUMENT_ID" \
      > "$DATA_ROOT/logs/analytics-wwv${freq_mhz}.log" 2>&1 &
    
    sleep 0.5
done

# CHU Channels (3)
chu_freqs=(3.33 7.85 14.67)
chu_freqs_hz=(3330000 7850000 14670000)

for i in 0 1 2; do
    freq_mhz=${chu_freqs[$i]}
    freq_hz=${chu_freqs_hz[$i]}
    # Match core recorder naming: "CHU 3.33 MHz" -> "CHU_3.33_MHz" (preserve dots)
    channel_dir="CHU_${freq_mhz}_MHz"
    
    echo "   Starting: CHU ${freq_mhz} MHz..."
    
    nohup python3 -m signal_recorder.analytics_service \
      --archive-dir "$DATA_ROOT/archives/$channel_dir" \
      --output-dir "$DATA_ROOT/analytics/$channel_dir" \
      --channel-name "CHU ${freq_mhz} MHz" \
      --frequency-hz "$freq_hz" \
      --state-file "$DATA_ROOT/state/analytics-chu${freq_mhz}.json" \
      --poll-interval 10.0 \
      --log-level INFO \
      --callsign "$CALLSIGN" \
      --grid-square "$GRID" \
      --receiver-name "GRAPE" \
      --psws-station-id "$STATION_ID" \
      --psws-instrument-id "$INSTRUMENT_ID" \
      > "$DATA_ROOT/logs/analytics-chu${freq_mhz}.log" 2>&1 &
    
    sleep 0.5
done

# Count analytics services
sleep 2
ANALYTICS_COUNT=$(ps aux | grep analytics_service | grep -v grep | wc -l)
echo "   ✅ Analytics Services started: $ANALYTICS_COUNT/9"
if [ "$ANALYTICS_COUNT" -lt 9 ]; then
    echo "   ⚠️  Not all analytics services started successfully"
fi
echo ""

# ============================================================================
# Step 3: Start Web-UI Monitoring Server
# ============================================================================
echo "▶️  Step 3: Starting Web-UI Monitoring Server..."
cd web-ui

export GRAPE_CONFIG="../$CONFIG"

nohup node monitoring-server.js > monitoring-server.log 2>&1 &
WEB_PID=$!
sleep 3

if ps -p $WEB_PID > /dev/null 2>&1; then
    echo "   ✅ Web-UI started (PID: $WEB_PID)"
else
    echo "   ⚠️  Web-UI may have failed"
    echo "   Check log: tail -f web-ui/monitoring-server.log"
fi

cd ..
echo ""

# ============================================================================
# System Status
# ============================================================================
echo "================================================================"
echo "✅ GRAPE System Running"
echo "================================================================"
echo ""
echo "📊 Dashboard:"
echo "   http://localhost:3000/"
echo ""
echo "📊 API Endpoints:"
echo "   http://localhost:3000/api/v1/system/status"
echo "   http://localhost:3000/api/v1/system/health"
echo ""
echo "📁 Data Paths:"
echo "   Data root: $DATA_ROOT"
echo "   NPZ archives: $DATA_ROOT/archives/"
echo "   Digital RF: $DATA_ROOT/analytics/*/digital_rf/"
echo "   Quality CSVs: $DATA_ROOT/analytics/*/quality/"
echo "   Status files: $DATA_ROOT/status/"
echo ""
echo "📝 Logs:"
echo "   Core recorder: tail -f $DATA_ROOT/logs/core-recorder.log"
echo "   Analytics (WWV 5): tail -f $DATA_ROOT/logs/analytics-wwv5.log"
echo "   Web-UI: tail -f web-ui/monitoring-server.log"
echo "   All logs: tail -f $DATA_ROOT/logs/*.log"
echo ""
echo "🔍 Monitor Status:"
echo "   # Watch core recorder"
echo "   watch -n 2 'cat $DATA_ROOT/status/core-recorder-status.json | jq .overall'"
echo ""
echo "   # Watch analytics service"
echo "   watch -n 2 'cat $DATA_ROOT/status/analytics-service-status.json | jq .overall'"
echo ""
echo "   # Check all processes"
echo "   ps aux | grep -E '(core_recorder|analytics_service|monitoring-server)' | grep -v grep"
echo ""
echo "🛑 Stop All Services:"
echo "   pkill -f core_recorder"
echo "   pkill -f analytics_service"
echo "   pkill -f monitoring-server.js"
echo ""
echo "⏱️  Timeline:"
echo "   • Core recorder: Receiving RTP packets now"
echo "   • Analytics: Processing NPZ files (10s poll interval)"
echo "   • Time_snap: Requires WWV/CHU tone at minute :00"
echo "   • Digital RF: Starts after time_snap established"
echo "   • Dashboard: Updates every 5-10 seconds"
echo ""
echo "📖 Full documentation: STARTUP_GUIDE.md"
echo ""
