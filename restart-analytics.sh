#!/bin/bash
# Restart Analytics Services ONLY (keeps core recorder and web-ui running)
# Use this when: updating analytics code, reprocessing data, fixing analytics issues

set -e

# Activate virtual environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"

CONFIG="${1:-config/grape-config.toml}"

if [ ! -f "$CONFIG" ]; then
    echo "❌ Config file not found: $CONFIG"
    echo "Usage: $0 [config-file]"
    exit 1
fi

echo "🔄 Restarting Analytics Services ONLY"
echo "================================================"
echo ""

# Get configuration
MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
if [ "$MODE" = "production" ]; then
    DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
else
    DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
fi

CALLSIGN=$(grep '^callsign' "$CONFIG" | head -1 | cut -d'"' -f2)
GRID=$(grep '^grid_square' "$CONFIG" | head -1 | cut -d'"' -f2)
STATION_ID=$(grep '^id' "$CONFIG" | head -1 | cut -d'"' -f2)
INSTRUMENT_ID=$(grep '^instrument_id' "$CONFIG" | head -1 | cut -d'"' -f2)

echo "📋 Config: $CONFIG"
echo "📁 Data root: $DATA_ROOT"
echo ""

# Stop existing analytics services
echo "🛑 Stopping existing analytics services..."
pkill -f analytics_service 2>/dev/null || true
sleep 2

# Check they're stopped
REMAINING=$(ps aux | grep analytics_service | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "   ⚠️  Force killing remaining processes..."
    pkill -9 -f analytics_service 2>/dev/null || true
    sleep 1
fi

echo "   ✅ All analytics services stopped"
echo ""

# Start analytics services
echo "▶️  Starting Analytics Services..."

# WWV Channels (6)
for freq_mhz in 2.5 5 10 15 20 25; do
    freq_hz=$(echo "$freq_mhz * 1000000" | bc | cut -d. -f1)
    channel_dir="WWV_${freq_mhz}_MHz"
    
    echo "   Starting: WWV ${freq_mhz} MHz..."
    
    nohup python3 -m signal_recorder.analytics_service \
      --archive-dir "$DATA_ROOT/archives/$channel_dir" \
      --output-dir "$DATA_ROOT/analytics/$channel_dir" \
      --channel-name "WWV ${freq_mhz} MHz" \
      --frequency-hz "$freq_hz" \
      --state-file "$DATA_ROOT/state/analytics-wwv${freq_mhz}.json" \
      --poll-interval 10.0 \
      --backfill-gaps \
      --max-backfill 100 \
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
    channel_dir="CHU_${freq_mhz}_MHz"
    
    echo "   Starting: CHU ${freq_mhz} MHz..."
    
    nohup python3 -m signal_recorder.analytics_service \
      --archive-dir "$DATA_ROOT/archives/$channel_dir" \
      --output-dir "$DATA_ROOT/analytics/$channel_dir" \
      --channel-name "CHU ${freq_mhz} MHz" \
      --frequency-hz "$freq_hz" \
      --state-file "$DATA_ROOT/state/analytics-chu${freq_mhz}.json" \
      --poll-interval 10.0 \
      --backfill-gaps \
      --max-backfill 100 \
      --log-level INFO \
      --callsign "$CALLSIGN" \
      --grid-square "$GRID" \
      --receiver-name "GRAPE" \
      --psws-station-id "$STATION_ID" \
      --psws-instrument-id "$INSTRUMENT_ID" \
      > "$DATA_ROOT/logs/analytics-chu${freq_mhz}.log" 2>&1 &
    
    sleep 0.5
done

# Verify
sleep 2
ANALYTICS_COUNT=$(ps aux | grep analytics_service | grep -v grep | wc -l)
echo ""
echo "✅ Analytics Services restarted: $ANALYTICS_COUNT/9"

if [ "$ANALYTICS_COUNT" -lt 9 ]; then
    echo "   ⚠️  Not all services started - check logs"
fi

echo ""
echo "📝 Check logs:"
echo "   tail -f $DATA_ROOT/logs/analytics-*.log"
echo ""
