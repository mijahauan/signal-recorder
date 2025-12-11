#!/bin/bash
# grape-stream.sh - Run the new RadiodStream-based recorder
#
# This script uses the refactored StreamRecorder which:
# - Uses ka9q.RadiodStream for RTP reception (replaces RTPReceiver)
# - Automatic gap detection via StreamQuality
# - Writes to BinaryArchiveWriter with detailed gap annotations
#
# Usage:
#   ./grape-stream.sh -start   # Start stream recording
#   ./grape-stream.sh -stop    # Stop stream recording
#   ./grape-stream.sh -status  # Check status

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

VENV_PYTHON="${VENV_PYTHON:-/opt/grape-recorder/venv/bin/python}"
DATA_ROOT="${DATA_ROOT:-/tmp/grape-test}"
STATUS_ADDRESS="${RADIOD_STATUS:-grape.local}"
PID_FILE="/tmp/grape-stream.pid"
LOG_FILE="/tmp/grape-stream.log"

start_stream() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "StreamRecorder already running (PID $pid)"
            exit 1
        fi
        rm -f "$PID_FILE"
    fi

    echo "Starting StreamRecorder..."
    echo "  Data root: $DATA_ROOT"
    echo "  Status address: $STATUS_ADDRESS"
    
    nohup $VENV_PYTHON -c "
import sys
import signal
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

from grape_recorder.grape.stream_recorder import StreamRecorder, StreamRecorderConfig

# Load station config
import tomli
config_path = Path('/opt/grape-recorder/config/grape-config.toml')
if config_path.exists():
    with open(config_path, 'rb') as f:
        full_config = tomli.load(f)
    station_config = full_config.get('station', {})
else:
    station_config = {'callsign': 'UNKNOWN', 'grid_square': 'XX00xx'}

config = StreamRecorderConfig(
    status_address='$STATUS_ADDRESS',
    data_root=Path('$DATA_ROOT'),
    station_config=station_config
)

recorder = StreamRecorder(config)

def signal_handler(signum, frame):
    print('Received shutdown signal')
    recorder.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Discover and start
count = recorder.discover_and_init_channels()
if count == 0:
    print('No channels discovered, exiting')
    sys.exit(1)

print(f'Recording {count} channels...')
recorder.start()

# Wait forever (until signal)
import time
while recorder.is_running():
    time.sleep(1)
" > "$LOG_FILE" 2>&1 &

    pid=$!
    echo $pid > "$PID_FILE"
    echo "StreamRecorder started (PID $pid)"
    echo "Log: $LOG_FILE"
}

stop_stream() {
    if [ ! -f "$PID_FILE" ]; then
        echo "StreamRecorder not running (no PID file)"
        exit 0
    fi

    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping StreamRecorder (PID $pid)..."
        kill "$pid"
        sleep 2
        if kill -0 "$pid" 2>/dev/null; then
            echo "Force killing..."
            kill -9 "$pid"
        fi
    fi
    rm -f "$PID_FILE"
    echo "StreamRecorder stopped"
}

status_stream() {
    if [ ! -f "$PID_FILE" ]; then
        echo "StreamRecorder: NOT RUNNING"
        exit 1
    fi

    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "StreamRecorder: RUNNING (PID $pid)"
        echo ""
        echo "Recent log:"
        tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log)"
    else
        echo "StreamRecorder: DEAD (stale PID file)"
        rm -f "$PID_FILE"
        exit 1
    fi
}

case "${1:-}" in
    -start|start)
        start_stream
        ;;
    -stop|stop)
        stop_stream
        ;;
    -status|status)
        status_stream
        ;;
    -restart|restart)
        stop_stream
        sleep 1
        start_stream
        ;;
    *)
        echo "Usage: $0 {-start|-stop|-status|-restart}"
        echo ""
        echo "RadiodStream-based recorder using ka9q.RadiodStream"
        echo "Replaces the legacy RTPReceiver with automatic gap detection"
        exit 1
        ;;
esac
