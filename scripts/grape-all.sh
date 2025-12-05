#!/bin/bash
# GRAPE All Services Control: Core + Analytics + Web-UI + Phase 3
#
# Three-Phase Pipeline Architecture:
#   Phase 1: Core Recorder → raw_archive/ (20 kHz Digital RF)
#   Phase 2: Analytics → phase2/ (timing analysis, D_clock)
#   Phase 3: Products → products/ (10 Hz DRF for PSWS upload)
#
# Usage: grape-all.sh -start|-stop|-status [config-file]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ACTION=""
CONFIG=""

for arg in "$@"; do
    case $arg in
        -start) ACTION="start" ;;
        -stop) ACTION="stop" ;;
        -status) ACTION="status" ;;
        *) CONFIG="$arg" ;;
    esac
done

CONFIG="${CONFIG:-$PROJECT_DIR/config/grape-config.toml}"

if [ -z "$ACTION" ]; then
    echo "Usage: $0 -start|-stop|-status [config-file]"
    exit 1
fi

get_data_root() {
    if [ -f "$CONFIG" ]; then
        MODE=$(grep '^mode' "$CONFIG" | cut -d'"' -f2)
        if [ "$MODE" = "production" ]; then
            grep '^production_data_root' "$CONFIG" | cut -d'"' -f2
        else
            grep '^test_data_root' "$CONFIG" | cut -d'"' -f2
        fi
    else
        echo "/tmp/grape-test"
    fi
}

DATA_ROOT=$(get_data_root)

case $ACTION in
start)
    echo "🚀 Starting All GRAPE Services (Three-Phase Pipeline)"
    echo "================================================================"
    echo "📋 Config: $CONFIG"
    echo "📁 Data: $DATA_ROOT"
    echo ""
    echo "📦 Phase 1: Core Recorder (20 kHz raw archive)"
    "$SCRIPT_DIR/grape-core.sh" -start "$CONFIG"
    echo ""
    echo "📊 Phase 2: Analytics (timing analysis, D_clock)"
    "$SCRIPT_DIR/grape-analytics.sh" -start "$CONFIG"
    echo ""
    echo "🌐 Web-UI (monitoring dashboard)"
    "$SCRIPT_DIR/grape-ui.sh" -start "$CONFIG"
    
    echo ""
    echo "================================================================"
    echo "✅ All real-time services started"
    echo "📊 Dashboard: http://localhost:3000/"
    echo ""
    echo "📝 Phase 3 (batch processing) runs separately:"
    echo "   python scripts/run_phase3_processor.py --data-root $DATA_ROOT --all-channels --yesterday"
    ;;

stop)
    echo "🛑 Stopping All GRAPE Services"
    echo "================================================================"
    
    "$SCRIPT_DIR/grape-ui.sh" -stop
    "$SCRIPT_DIR/grape-analytics.sh" -stop
    "$SCRIPT_DIR/grape-core.sh" -stop
    
    echo ""
    echo "✅ All services stopped"
    ;;

status)
    echo "📊 GRAPE Service Status (Three-Phase Pipeline)"
    echo "================================================================"
    
    # Phase 1: Core Recorder
    CORE_COUNT=$(pgrep -f "grape_recorder.grape.core_recorder" 2>/dev/null | wc -l)
    if [ "$CORE_COUNT" -gt 0 ]; then
        echo "✅ Phase 1 (Core):    RUNNING (PIDs: $(pgrep -f 'grape_recorder.grape.core_recorder' | tr '\n' ' '))"
    else
        echo "⭕ Phase 1 (Core):    STOPPED"
    fi
    
    # Phase 2: Analytics
    ANALYTICS_COUNT=$(pgrep -f "grape_recorder.grape.phase2_analytics_service" 2>/dev/null | wc -l)
    if [ "$ANALYTICS_COUNT" -gt 0 ]; then
        echo "✅ Phase 2 (Analytics): RUNNING ($ANALYTICS_COUNT/9 channels)"
    else
        echo "⭕ Phase 2 (Analytics): STOPPED"
    fi
    
    # Web-UI
    WEBUI_COUNT=$(pgrep -f "monitoring-server" 2>/dev/null | wc -l)
    if [ "$WEBUI_COUNT" -gt 0 ]; then
        echo "✅ Web-UI:            RUNNING → http://localhost:3000/"
    else
        echo "⭕ Web-UI:            STOPPED"
    fi
    
    echo ""
    echo "📁 Data Structure:"
    echo "   $DATA_ROOT/"
    echo "   ├── raw_archive/     Phase 1: 20 kHz Digital RF"
    echo "   ├── phase2/          Phase 2: Timing analysis, D_clock"
    echo "   ├── products/        Phase 3: 10 Hz DRF for PSWS"
    echo "   └── logs/            Service logs"
    
    # Show disk usage if data exists
    if [ -d "$DATA_ROOT/raw_archive" ]; then
        RAW_SIZE=$(du -sh "$DATA_ROOT/raw_archive" 2>/dev/null | cut -f1)
        echo ""
        echo "💾 Storage: raw_archive=$RAW_SIZE"
    fi
    ;;
esac
