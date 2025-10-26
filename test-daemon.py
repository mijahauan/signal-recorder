#!/Users/mjh/Sync/GitHub/signal-recorder/venv/bin/python
"""
Simple test daemon for signal-recorder web UI testing
"""

import time
import os
import json
import sys
from pathlib import Path

def write_status(status, details=""):
    """Write daemon status to a file that the web server can check"""
    script_dir = Path(__file__).parent
    status_file = script_dir / "test-data" / "daemon-status.json"

    status_data = {
        "running": status,
        "pid": os.getpid(),
        "start_time": time.time(),
        "details": details,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Ensure directory exists
    status_file.parent.mkdir(parents=True, exist_ok=True)

    # Write status file
    with open(status_file, 'w') as f:
        json.dump(status_data, f, indent=2)

def main():
    config_file = sys.argv[2] if len(sys.argv) > 2 else 'config/grape-S000171.toml'

    print(f"Starting test daemon with config: {config_file}")
    print("Test daemon running (Ctrl+C to stop)...")

    # Create test data directory (relative to script location)
    script_dir = Path(__file__).parent
    test_data_dir = script_dir / "test-data" / "raw"
    test_data_dir.mkdir(parents=True, exist_ok=True)

    # Load config file (relative to script location)
    config_path = script_dir / config_file
    print(f"Loading config from: {config_path}")

    try:
        while True:
            # Create a test data file every 10 seconds
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            test_file = Path(test_data_dir) / f"test_{timestamp}.drf"

            # Write a simple test file
            with open(test_file, 'w') as f:
                f.write(f"Test data file created at {time.strftime('%H:%M:%S')}\n")

            print(f"Created test file: {test_file}")
            time.sleep(10)

    except KeyboardInterrupt:
        print("Test daemon stopping...")
        print("Test daemon stopped")

if __name__ == '__main__':
    main()
