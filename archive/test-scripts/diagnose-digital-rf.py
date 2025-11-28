#!/usr/bin/env python3
"""
Diagnostic script to check why Digital RF files aren't being written
"""

import sys
from pathlib import Path

# Check 1: digital_rf availability
print("=" * 60)
print("DIAGNOSTIC: Digital RF Write Issue")
print("=" * 60)
print()

print("CHECK 1: digital_rf module")
try:
    import digital_rf as drf
    print(f"✓ digital_rf available (version {drf.__version__ if hasattr(drf, '__version__') else 'unknown'})")
    HAS_DIGITAL_RF = True
except ImportError as e:
    print(f"✗ digital_rf NOT available: {e}")
    HAS_DIGITAL_RF = False
    sys.exit(1)

print()
print("CHECK 2: Recorder status from logs")
print("-" * 60)

# Look for relevant log messages in the running process
import subprocess

try:
    # Find the recorder process
    result = subprocess.run(
        ['ps', 'aux'],
        capture_output=True,
        text=True
    )
    
    for line in result.stdout.split('\n'):
        if 'signal-recorder daemon' in line and 'grep' not in line:
            parts = line.split()
            pid = parts[1]
            print(f"Found recorder PID: {pid}")
            print()
            
            # Check if we can read from stdout (unlikely in background)
            fd_path = f"/proc/{pid}/fd/1"
            if Path(fd_path).exists():
                print("Process stdout accessible (running in foreground)")
            else:
                print("Process stdout not accessible (running in background/tmux)")
            
            break
    else:
        print("⚠️  Recorder process not found!")
        
except Exception as e:
    print(f"Error checking process: {e}")

print()
print("CHECK 3: Look for Digital RF output directories")
print("-" * 60)

data_root = Path('/tmp/grape-test/data')
if not data_root.exists():
    print(f"✗ Data root not found: {data_root}")
else:
    print(f"✓ Data root exists: {data_root}")
    
    # Look for ch0 directories (Digital RF structure)
    ch0_dirs = list(data_root.rglob('ch0'))
    if ch0_dirs:
        print(f"✓ Found {len(ch0_dirs)} ch0 directories:")
        for d in ch0_dirs:
            print(f"  {d}")
    else:
        print("✗ No ch0 directories found (Digital RF not being written)")
    
    # Look for .h5 files
    h5_files = list(data_root.rglob('*.h5'))
    if h5_files:
        print(f"✓ Found {len(h5_files)} .h5 files")
        print(f"  Most recent: {max(h5_files, key=lambda p: p.stat().st_mtime)}")
    else:
        print("✗ No .h5 files found")
    
    # Look for drf_properties.h5
    props_files = list(data_root.rglob('drf_properties.h5'))
    if props_files:
        print(f"✓ Found {len(props_files)} drf_properties.h5 files")
    else:
        print("✗ No drf_properties.h5 files found")

print()
print("CHECK 4: NPZ files (16 kHz archival) status")
print("-" * 60)

npz_files = list(data_root.rglob('*.npz'))
if npz_files:
    most_recent = max(npz_files, key=lambda p: p.stat().st_mtime)
    import time
    age = time.time() - most_recent.stat().st_mtime
    print(f"✓ Found {len(npz_files)} NPZ files")
    print(f"  Most recent: {most_recent}")
    print(f"  Age: {age:.0f} seconds ago")
    
    if age < 120:
        print("  ✓ Recorder is actively writing NPZ files")
    else:
        print("  ⚠️  NPZ files are stale (recorder may have stopped)")
else:
    print("✗ No NPZ files found")

print()
print("CHECK 5: Expected Digital RF path structure")
print("-" * 60)

from datetime import datetime, timezone
date_str = datetime.now(timezone.utc).strftime('%Y%m%d')

expected_paths = [
    data_root / date_str / "AC0G_EM38ww" / "172" / "WWV_5_MHz" / "ch0",
    data_root / date_str / "AC0G_EM38ww" / "172" / "WWV_10_MHz" / "ch0",
    data_root / date_str / "AC0G_EM38ww" / "172" / "WWV_15_MHz" / "ch0",
]

print(f"Today's date: {date_str}")
print(f"Expected structure: YYYYMMDD/CALLSIGN_GRID/INSTRUMENT/CHANNEL/ch0/")
print()

for path in expected_paths:
    if path.exists():
        print(f"✓ {path}")
        # Count files
        files = list(path.rglob('rf@*.h5'))
        print(f"  Contains {len(files)} .h5 files")
    else:
        print(f"✗ {path} (doesn't exist)")

print()
print("CHECK 6: Time-based write trigger")
print("-" * 60)

now = datetime.now(timezone.utc)
print(f"Current UTC time: {now.strftime('%H:%M:%S')}")
print(f"Current minute: {now.minute}")

if now.minute >= 1 and now.minute <= 5:
    print(f"✓ Within hourly write window (minute 1-5 of hour)")
    print(f"  Hourly write should have triggered at {now.hour:02d}:01:00")
else:
    print(f"  Outside hourly write window")
    print(f"  Next hourly write: {(now.hour+1) % 24:02d}:01:00 UTC")

print()
print("=" * 60)
print("DIAGNOSIS")
print("=" * 60)

if not ch0_dirs and not h5_files:
    print()
    print("❌ Digital RF output is NOT working")
    print()
    print("Possible causes:")
    print("  1. Buffer not accumulating (daily_buffer.add_samples not being called)")
    print("  2. Hourly write check not triggering")
    print("  3. Write function silently failing (check for errors in logs)")
    print("  4. HAS_DIGITAL_RF flag is False (but we verified it's True)")
    print()
    print("Next steps:")
    print("  1. Check tmux/terminal for 'Hourly write triggered' messages")
    print("  2. Check for any ERROR messages about Digital RF")
    print("  3. Add temporary debug logging to _write_digital_rf")
    print("  4. Verify samples are being decimated (check self.samples_received)")
else:
    print()
    print("✓ Digital RF output appears to be working!")
    print()

print()
print("To monitor in real-time, watch for these log messages:")
print("  'Hourly write triggered'")
print("  'Writing Digital RF for'")
print("  '✅ Digital RF write complete'")
print()
