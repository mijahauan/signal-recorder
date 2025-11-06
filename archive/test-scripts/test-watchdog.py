#!/Users/mjh/Sync/GitHub/signal-recorder/venv/bin/python
"""
Watchdog script for monitoring the signal-recorder daemon
Provides reliable status information to the web server
"""

import time
import os
import json
import sys
import signal
from pathlib import Path

def write_status(status, details="", pid=None):
    """Write daemon status to a file that the web server can check"""
    script_dir = Path(__file__).parent
    status_file = script_dir / "data" / "daemon-status.json"  # Changed from test-data to data

    status_data = {
        "running": status,
        "pid": pid or os.getpid(),
        "watchdog_pid": os.getpid(),
        "start_time": time.time(),
        "details": details,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Ensure directory exists
    status_file.parent.mkdir(parents=True, exist_ok=True)

    # Write status file
    with open(status_file, 'w') as f:
        json.dump(status_data, f, indent=2)

def find_daemon_process():
    """Find the actual daemon process"""
    try:
        # Look for python processes running signal_recorder.cli daemon
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'signal_recorder.cli daemon'],
                              capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return pids[0] if pids else None
    except Exception:
        pass
    return None

def main():
    print("Starting daemon watchdog...")

    # Write initial status
    write_status(False, "Watchdog started")

    try:
        while True:
            daemon_pid = find_daemon_process()

            if daemon_pid:
                # Verify the process is actually a daemon
                try:
                    import subprocess
                    result = subprocess.run(['ps', '-p', daemon_pid, '-o', 'args='],
                                          capture_output=True, text=True)
                    if result.returncode == 0 and 'signal_recorder.cli daemon' in result.stdout:
                        write_status(True, f"Daemon running (PID: {daemon_pid})", daemon_pid)
                    else:
                        write_status(False, "Daemon process not found", daemon_pid)
                except Exception:
                    write_status(False, "Error checking daemon process", daemon_pid)
            else:
                write_status(False, "No daemon process found")

            time.sleep(5)  # Check every 5 seconds

    except KeyboardInterrupt:
        print("Watchdog stopping...")
        write_status(False, "Watchdog stopped")
        print("Watchdog stopped")

if __name__ == '__main__':
    main()
