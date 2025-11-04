#!/bin/bash
# Check GRAPE Dashboard Status

echo "📊 GRAPE Dashboard Status Check"
echo "================================"
echo ""

# Get data_root from config based on mode
CONFIG="${GRAPE_CONFIG:-../config/grape-config.toml}"
if [ -f "$CONFIG" ]; then
    MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
    if [ "$MODE" = "production" ]; then
        DATA_ROOT=$(grep '^production_data_root' "$CONFIG" | cut -d'"' -f2)
        MODE_TEXT="🚀 PRODUCTION"
    else
        DATA_ROOT=$(grep '^test_data_root' "$CONFIG" | cut -d'"' -f2)
        MODE_TEXT="🧪 TEST"
    fi
    echo "📋 Config: $CONFIG"
    echo "📌 Mode: $MODE_TEXT"
    echo "📁 Data root: $DATA_ROOT"
else
    DATA_ROOT="/tmp/grape-test"
    echo "⚠️  Config not found, using default: $DATA_ROOT"
fi

echo ""

# Check recorder
RECORDER_PID=$(ps aux | grep test_v2_recorder | grep -v grep | awk '{print $2}')
if [ -n "$RECORDER_PID" ]; then
    UPTIME=$(ps -p $RECORDER_PID -o etime= | xargs)
    echo "✅ Recorder: Running (PID $RECORDER_PID, uptime: $UPTIME)"
else
    echo "❌ Recorder: Not running"
fi

# Check web server
WEB_PID=$(ps aux | grep monitoring-server | grep -v grep | awk '{print $2}')
if [ -n "$WEB_PID" ]; then
    WEB_UPTIME=$(ps -p $WEB_PID -o etime= | xargs)
    echo "✅ Web Server: Running (PID $WEB_PID, uptime: $WEB_UPTIME)"
else
    echo "❌ Web Server: Not running"
fi

echo ""
echo "📁 CSV Files:"
CSV_DIR="$DATA_ROOT/analytics/quality/$(date +%Y%m%d)"
if [ -d "$CSV_DIR" ]; then
    CSV_COUNT=$(ls -1 "$CSV_DIR"/*minute_quality*.csv 2>/dev/null | wc -l)
    echo "   Directory: $CSV_DIR"
    echo "   Files: $CSV_COUNT"
    
    if [ $CSV_COUNT -gt 0 ]; then
        # Check most recent file
        RECENT_FILE=$(ls -t "$CSV_DIR"/*minute_quality*.csv 2>/dev/null | head -1)
        LAST_MODIFIED=$(stat -c %y "$RECENT_FILE" | cut -d. -f1)
        LINES=$(wc -l < "$RECENT_FILE")
        echo "   Latest: $(basename "$RECENT_FILE")"
        echo "   Modified: $LAST_MODIFIED"
        echo "   Minutes: $((LINES - 1))"
        
        # Check if has new columns
        HEADER=$(head -1 "$RECENT_FILE")
        if echo "$HEADER" | grep -q "quality_grade"; then
            echo "   Format: ✅ NEW (has quality_grade column)"
        else
            echo "   Format: ⚠️  OLD (missing quality_grade column)"
        fi
    fi
else
    echo "   ⚠️  Directory not found"
fi

echo ""
echo "🌐 API Test:"
curl -s http://localhost:3000/api/monitoring/station-info | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('available'):
        print(f\"   ✅ Station: {d['station']['callsign']} ({d['station']['gridSquare']})\")
        print(f\"   ✅ Server Uptime: {d['server']['uptime']}\")
    else:
        print('   ❌ Station info not available')
except:
    print('   ❌ API error')
"

echo ""
echo "📊 Quality Data:"
curl -s http://localhost:3000/api/monitoring/timing-quality | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('available'):
        channels = len(d.get('channels', {}))
        total_min = d.get('overall', {}).get('totalMinutes', 0)
        print(f\"   ✅ Channels: {channels}\")
        print(f\"   ✅ Total Minutes: {total_min}\")
        if total_min > 0:
            print('   ✅ Dashboard has data!')
        else:
            print('   ⏳ Waiting for first CSV export...')
    else:
        print(f\"   ⚠️  {d.get('message', 'Not available')}\")
except Exception as e:
    print(f'   ❌ API error: {e}')
"

echo ""
echo "🔗 Dashboard: http://localhost:3000/"
echo ""
