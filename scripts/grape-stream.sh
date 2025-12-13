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
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

from grape_recorder.grape.stream_recorder import StreamRecorder, StreamRecorderConfig

# Load station config
import tomli
config_path = Path(os.environ.get('GRAPE_CONFIG', '/opt/grape-recorder/config/grape-config.toml'))
if config_path.exists():
    with open(config_path, 'rb') as f:
        full_config = tomli.load(f)
    station_config = full_config.get('station', {})
else:
    station_config = {'callsign': 'UNKNOWN', 'grid_square': 'XX00xx'}

ka9q_cfg = full_config.get('ka9q', {}) if config_path.exists() else {}
rec_cfg = full_config.get('recorder', {}) if config_path.exists() else {}

status_address = ka9q_cfg.get('status_address') or '$STATUS_ADDRESS'

mode = (rec_cfg.get('mode') or 'test').lower()
if mode == 'production':
    data_root_str = rec_cfg.get('production_data_root', '$DATA_ROOT')
else:
    data_root_str = rec_cfg.get('test_data_root', '$DATA_ROOT')

data_root = Path(os.environ.get('DATA_ROOT', data_root_str))

# Optionally auto-create channels in radiod to ensure correct stream definitions
auto_create = bool(ka9q_cfg.get('auto_create_channels', False))
channel_defaults = rec_cfg.get('channel_defaults', {})
channel_specs = rec_cfg.get('channels', [])

configured_freqs = []
required_channels = []
for ch in channel_specs:
    freq = ch.get('frequency_hz')
    if not freq:
        continue
    configured_freqs.append(float(freq))
    required_channels.append({
        'ssrc': ch.get('ssrc', 0) or 0,
        'frequency_hz': float(freq),
        'preset': ch.get('preset', channel_defaults.get('preset', 'iq')),
        'sample_rate': int(ch.get('sample_rate', channel_defaults.get('sample_rate', 20000))),
        'agc': int(ch.get('agc', channel_defaults.get('agc', 0))),
        'gain': float(ch.get('gain', channel_defaults.get('gain', 0.0))),
        'encoding': ch.get('encoding', channel_defaults.get('encoding', 'float')),
        'description': ch.get('description', '')
    })

if auto_create and required_channels:
    try:
        from grape_recorder.channel_manager import ChannelManager
        mgr = ChannelManager(status_address)
        for spec in required_channels:
            mgr.create_channel(
                frequency_hz=spec['frequency_hz'],
                preset=spec['preset'],
                sample_rate=spec['sample_rate'],
                agc=spec['agc'],
                gain=spec['gain'],
                destination=None,
                ssrc=(spec['ssrc'] if spec['ssrc'] != 0 else None),
                description=spec['description'],
                encoding=spec['encoding'],
            )
    except Exception as e:
        logging.getLogger(__name__).warning(f'Auto-create channels failed: {e}')

config = StreamRecorderConfig(
    status_address=status_address,
    data_root=data_root,
    station_config=station_config
)

if configured_freqs:
    config.channel_frequencies = configured_freqs

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
