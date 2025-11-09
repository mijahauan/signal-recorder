# Restart Recorder to Enable Real-Time Digital RF

## What Changed

Switched from **V2 recorder** (NPZ-only, batch processing) to **original recorder** (real-time Digital RF):

- ✅ Real-time decimation (8 kHz → 10 Hz)
- ✅ Hourly Digital RF writes (at XX:01 UTC)
- ✅ Incremental HDF5 files for near-real-time upload
- ✅ Debug logging to diagnose write triggers
- ✅ **Full KA9Q time_snap correction from WWV tones** (NEW!)

See `TIME_SNAP_IMPLEMENTATION.md` for details on timing architecture.

## Restart Steps

### In tmux (Recommended)

```bash
# Attach to tmux session
./start-grape-recorder.sh attach

# In left pane (recorder):
# Press Ctrl+C to stop recorder

# Start it again:
source venv/bin/activate
signal-recorder daemon --config config/grape-config.toml

# Watch for messages at next XX:01 boundary:
# "DEBUG - HAS_DIGITAL_RF=True, should_write=True, has_data=True"
# "Hourly write triggered"
```

### Or Restart tmux Session

```bash
./start-grape-recorder.sh stop
./start-grape-recorder.sh start
./start-grape-recorder.sh attach
```

## What to Expect

**Immediate:**
- Recorder enters 'startup' state, waits for UTC :00 boundary
- Establishes initial time_snap reference at :00
- Real-time decimation begins

**At each minute (:00 of each minute):**
- WWV tone detection attempts
- Timing error measurements logged
- If |error| > 50ms: Time_snap correction may be applied
  ```
  ⚠️  TIME_SNAP CORRECTION APPLIED
     Timing error: +52.3 ms
  ```

**At next XX:01 UTC (e.g., 23:01, 00:01, 01:01):**
- DEBUG messages showing write trigger check
- "Hourly write triggered" message
- Digital RF files created in subdirectories:
  - `/tmp/grape-test/data/WWV 2.5 MHz/ch0/2025-11-06T*/`
  - `/tmp/grape-test/data/WWV 5 MHz/ch0/2025-11-06T*/`
  - etc.

**File structure:**
```
/tmp/grape-test/data/
├── WWV 2.5 MHz/
│   ├── ch0/
│   │   ├── 2025-11-06T22-00-00/    # Hourly subdirectories
│   │   │   └── rf@1730923200.000.h5
│   │   └── 2025-11-06T23-00-00/
│   └── metadata/
├── WWV 5 MHz/
└── ...
```

## Verify

After restart + next hourly boundary:

```bash
# Check for Digital RF files
find /tmp/grape-test/data -name "*.h5" -type f

# Should show files like:
# /tmp/grape-test/data/WWV 2.5 MHz/ch0/2025-11-06T23-00-00/rf@1730926800.000.h5
```

## Notes

- Old NPZ files are still there, safe to archive/delete
- Web dashboard will still work (uses quality CSV files)
- Digital RF files compatible with wsprdaemon upload format
