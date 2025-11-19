# Project Cleanup - Final Plan (Corrected)

## What Changed Based on Your Feedback

### My Misunderstandings (Corrected):
1. ❌ Thought you used systemd → ✅ CLI only
2. ❌ Thought V2 was current → ✅ V2 is obsolete, archive it
3. ❌ Missed script analysis → ✅ Dozens of debug scripts to sort

### Current System (Confirmed):
- **Entry point:** `start-dual-service.sh`
- **Core recorder:** `core_recorder.py` (minimal NPZ writer)
- **Analytics:** `analytics_service.py` (processes NPZ → Digital RF)
- **Web UI:** `monitoring-server-v3.js`

---

## Execute Cleanup

```bash
./execute-cleanup-revised.sh
```

**What it archives:**

### Python V2 Stack → `archive/legacy-code/v2-recorder/`
- `grape_recorder.py` - V2 entry point (OBSOLETE)
- `grape_channel_recorder_v2.py` - V2 integrated recorder (OBSOLETE)
- `minute_file_writer.py` - V2 file writer (OBSOLETE)
- `live_quality_status.py` - V2 status (OBSOLETE)
- `grape_metadata.py` - V2 metadata (OBSOLETE)

**NOT archived:** `grape_rtp_recorder.py`
- **Why:** Contains `RTPReceiver` class used by current `core_recorder.py`
- **Issue:** File has BOTH current (RTPReceiver) and obsolete (GRAPERecorderManager) code
- **Future:** Extract RTPReceiver to separate file

### Shell Scripts - V2 → `archive/shell-scripts/v2-scripts/`
- `start-grape-recorder.sh` - Uses old `signal-recorder daemon` CLI
- `start-grape.sh` - Old V2 starter
- `RESTART-RECORDER.sh` - Old V2 CLI
- `restart-recorder-with-new-code.sh` - Old V2 CLI

### Shell Scripts - Debug → `archive/shell-scripts/debug/`
- `cleanup-buggy-tone-data.sh` - One-time bug fix
- `cleanup-corrupt-drf.sh` - One-time data fix
- `cleanup-logs.sh` - Log cleanup utility
- `cleanup-tmp-grape.sh` - Temp cleanup
- `clean-test-data.sh` - Test data cleanup
- `generate-carrier-comparison.sh` - Analysis script
- `test-health-runtime.sh` - Development test
- `test-health-monitoring.sh` - Development test
- `verify-mode-paths.sh` - Path verification (completed)
- `start-watchdog.sh` - Watchdog (may be obsolete)

### Shell Scripts - Systemd → `archive/shell-scripts/systemd/`
- `install-core-recorder-service.sh` - Not used (CLI only)
- `core-recorder-ctl.sh` - Not used (CLI only)

### Documentation (Same as Before)
- Session docs → `archive/dev-history/` (~50 files)
- Feature docs → `docs/features/` (~40 files)
- Web-UI docs → `docs/web-ui/` (~15 files)
- Test scripts → `archive/test-scripts/` (~30 files)

---

## After Cleanup - Root Directory

### Active Shell Scripts (Current Production)
```
start-dual-service.sh         ← PRIMARY entry point
start-core-recorder-direct.sh ← Alternative direct starter
start-all-carrier-analytics.sh ← Carrier analytics
restart-analytics.sh          ← Restart analytics only
restart-webui.sh              ← Restart web UI only
stop-dual-service.sh          ← Stop all services
start-radiod-monitor.sh       ← Radiod health monitor
```

### Core Documentation (7 files)
```
README.md
CONTEXT.md
ARCHITECTURE.md
QUICK_START.md
DEPENDENCIES.md
INSTALLATION.md
SYSTEMD_INSTALLATION.md (consider moving to docs/)
```

### Python Source (Active)
```
src/signal_recorder/
  ✅ core_recorder.py           - Current recorder
  ✅ core_npz_writer.py          - NPZ file format
  ✅ packet_resequencer.py       - RTP packet ordering
  ✅ analytics_service.py        - Analytics processor
  ✅ tone_detector.py            - WWV/CHU detection
  ✅ decimation.py               - 16kHz → 10Hz
  ✅ digital_rf_writer.py        - Digital RF output
  ⚠️  grape_rtp_recorder.py      - Contains BOTH current and obsolete
  ✅ [all other shared modules]  - Config, paths, health, etc.
```

---

## Critical Finding: grape_rtp_recorder.py

This file contains **BOTH** current and obsolete code:

**CURRENT (line 477):**
```python
class RTPReceiver:
    """Receives RTP packets from multicast and demultiplexes by SSRC"""
```
- Used by: `core_recorder.py` (line 31: `from .grape_rtp_recorder import RTPReceiver`)
- Purpose: Shared RTP packet receiver
- Status: **ACTIVE - DO NOT ARCHIVE**

**OBSOLETE (line 815):**
```python
class GRAPERecorderManager:
    """Manager for multiple GRAPE channel recorders"""
```
- Used by: Old V2 stack (grape_recorder.py)
- Purpose: V2 recorder manager that uses grape_channel_recorder_v2.py
- Status: **OBSOLETE - CANNOT ARCHIVE (same file as RTPReceiver)**

**Recommendation:**
1. **Now:** Archive V2 files, keep grape_rtp_recorder.py intact
2. **Future:** Extract `RTPReceiver` to `rtp_receiver.py`, then archive the rest

---

## Verification After Cleanup

```bash
# 1. Test current system starts
./start-dual-service.sh
# Wait for "✅ GRAPE System Running", then Ctrl+C
./stop-dual-service.sh

# 2. Verify imports work
python3 -c "import signal_recorder; print('OK')"

# 3. Check what imports V2 (should be none)
grep -r "grape_channel_recorder_v2\|grape_recorder" src/signal_recorder/*.py | grep -v "grape_channel_recorder_v2.py:" | grep -v "grape_recorder.py:" | grep -v "grape_rtp_recorder.py:"

# 4. Check git status
git status

# 5. If everything OK
git commit -m "Archive obsolete V2 recorder and debug scripts

- Archived V2 Python stack (5 modules)
- Archived V2 shell scripts (4 scripts)
- Archived debug scripts (~10 scripts)
- Archived systemd scripts (2 scripts)
- Organized ~100 documentation files
- Current core recorder stack preserved
- Note: grape_rtp_recorder.py kept (contains shared RTPReceiver)"

# 6. If something broke
git reset --hard pre-cleanup-v2-archive
```

---

## Summary

**Before:** 
- 70+ markdown files at root (confusing)
- 30+ shell scripts (mix of current/obsolete)
- V2 and Core stacks coexisting (confusion)
- Old "signal-recorder daemon" CLI still referenced

**After:**
- 7 core docs at root (clean)
- 7 production shell scripts (clear purpose)
- V2 archived (no confusion about entry point)
- Current CLI clearly documented: `start-dual-service.sh`

**What's Protected:**
- ✅ Current core recorder stack
- ✅ All analytics code
- ✅ All production scripts
- ✅ RTPReceiver class (in grape_rtp_recorder.py)
- ✅ All historical code (in archive, not deleted)

**What's Archived:**
- V2 recorder stack (grape_channel_recorder_v2.py, etc.)
- Old shell scripts (using "signal-recorder daemon")
- Debug/test scripts (one-time use)
- Session documentation (~100 files)

**Safety:** All changes reversible via `git reset --hard pre-cleanup-v2-archive`

---

## Files Created for This Cleanup

1. `CLEANUP_PROPOSAL.md` - Original analysis (before corrections)
2. `CLEANUP_REVISED.md` - Corrected analysis
3. `CLEANUP_PLAN_FINAL.md` - This summary
4. `execute-cleanup-revised.sh` - Automated cleanup script ← **USE THIS ONE**

Run: `./execute-cleanup-revised.sh`
