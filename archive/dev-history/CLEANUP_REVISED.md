# Project Cleanup - Revised Analysis (Nov 18, 2025)

## Critical Corrections Based on User Feedback

### What I Got Wrong
1. ❌ **Assumed systemd deployment** - System only runs from CLI
2. ❌ **Thought V2 was current** - It's obsolete and should be archived
3. ❌ **Missed script analysis** - Dozens of debug/start/stop scripts need sorting

### What's Actually Current
✅ **Core recorder** (`core_recorder.py`) via `start-dual-service.sh`
✅ **Analytics service** (`analytics_service.py`)
✅ **Web UI** (`monitoring-server-v3.js`)

---

## PART 1: Archive Obsolete V2 Recording Stack

### Files to Archive → `archive/legacy-code/v2-recorder/`

**Main V2 Components (OBSOLETE):**
- `src/signal_recorder/grape_recorder.py` - Old CLI entry point
- `src/signal_recorder/grape_channel_recorder_v2.py` - Old integrated recorder
- `src/signal_recorder/grape_rtp_recorder.py` - Old RTP manager (imports V2)
- `src/signal_recorder/minute_file_writer.py` - Old file writer (used by V2)
- `src/signal_recorder/live_quality_status.py` - Old status (used by V2)
- `src/signal_recorder/grape_metadata.py` - Old metadata (used by V2)

**Why archive these:**
- Not used by current `start-dual-service.sh` (which calls `core_recorder.py`)
- Confusing to have two complete stacks
- V2 was the integrated design (recorder + analytics together)
- Core is the split design (recorder separate from analytics)

**VERIFY FIRST:**
```bash
# Make absolutely sure nothing imports these
grep -r "from.*grape_channel_recorder_v2" src/ --include="*.py"
grep -r "from.*grape_recorder import" src/ --include="*.py"
```

---

## PART 2: Shell Scripts Cleanup

### ✅ CURRENT - Production Scripts

**Active Start Scripts:**
- `start-dual-service.sh` - **PRIMARY** - Starts core + analytics + web-ui
- `start-core-recorder-direct.sh` - Alternative core recorder start
- `start-all-carrier-analytics.sh` - Carrier channel analytics
- `restart-analytics.sh` - Restart analytics only
- `restart-webui.sh` - Restart web UI only
- `stop-dual-service.sh` - Stop all services

**Web-UI Scripts:**
- `web-ui/start-monitoring.sh` - Web UI starter

**Monitoring:**
- `start-radiod-monitor.sh` - ka9q-radio health monitoring
- `quick-verify.sh` - Quick status check (if exists)

### ⚠️ OBSOLETE - Scripts Using Old "signal-recorder daemon"

**Archive to `archive/shell-scripts/v2-scripts/`:**
- `start-grape-recorder.sh` - Uses `signal-recorder daemon` (V2 CLI)
- `start-grape.sh` - Likely old V2 starter
- `RESTART-RECORDER.sh` - Uses `pkill -f "signal-recorder daemon"`
- `restart-recorder-with-new-code.sh` - Uses V2 CLI
- `test-health-runtime.sh` - References V2 CLI
- `test-health-monitoring.sh` - References V2 CLI
- `clean-test-data.sh` - References V2 CLI

**Why obsolete:**
- All reference `signal-recorder daemon` which was V2's CLI
- Current system uses `python3 -m signal_recorder.core_recorder`
- Would confuse developers about current entry point

### 🧪 DEBUG/TEST - Archive to `archive/shell-scripts/debug/`

**One-time debug scripts:**
- `cleanup-buggy-tone-data.sh` - Specific bug cleanup (Nov 17)
- `cleanup-corrupt-drf.sh` - One-time data fix
- `cleanup-logs.sh` - Log cleanup utility
- `cleanup-tmp-grape.sh` - Temp cleanup
- `clean-test-data.sh` - Test data cleanup
- `generate-carrier-comparison.sh` - Analysis script
- `test-health-*.sh` - Development testing
- `verify-mode-paths.sh` - Path verification (completed)
- `start-watchdog.sh` - Watchdog script (may be obsolete)

### 🛠️ SYSTEMD/INSTALL - Archive to `archive/shell-scripts/systemd/`

**Not used (CLI only, no systemd):**
- `install-core-recorder-service.sh` - Systemd installer
- `core-recorder-ctl.sh` - Systemd control script

### ❓ UNKNOWN - Need Investigation

**Check if still used:**
- `commit-and-cleanup.sh` - What does this do?
- `cleanup-codebase.sh` - Old cleanup script?
- `install-linux.sh` - Installation script (keep?)

---

## PART 3: Python Source Code

### ✅ KEEP - Current Core Stack

**Core Recorder:**
- `core_recorder.py` - Minimal NPZ writer
- `core_npz_writer.py` - NPZ file format
- `packet_resequencer.py` - RTP packet ordering

**Analytics:**
- `analytics_service.py` - Main analytics processor
- `tone_detector.py` - WWV/CHU/WWVH detection
- `wwvh_discrimination.py` - Differential delay
- `decimation.py` - 16kHz → 10Hz
- `digital_rf_writer.py` - Digital RF output
- `drf_writer_service.py` - DRF service wrapper
- `quality_metrics.py` - Quality calculations

**Shared:**
- `config_utils.py` - Config parsing
- `paths.py` - Path management
- `channel_manager.py` - Channel config
- `radiod_health.py` - Health monitoring
- `session_tracker.py` - Session tracking
- `gap_backfill.py` - Gap filling
- `uploader.py` - Upload management
- `data_management.py` - Data management
- `cli.py` - CLI interface
- `__init__.py` - Package exports
- `__main__.py` - Module entry point
- `audio_stream.py` - Audio streaming
- `audio_streamer.py` - Audio backend

**Interfaces:**
- `interfaces/` - All data models

### 🗄️ ARCHIVE - Old V2 Stack

Move to `archive/legacy-code/v2-recorder/`:
- `grape_recorder.py`
- `grape_channel_recorder_v2.py`
- `grape_rtp_recorder.py`
- `minute_file_writer.py`
- `live_quality_status.py`
- `grape_metadata.py`

### 🗂️ KEEP - Legacy Directory

- `legacy/` - Keep as-is (already archived, may have imports)

---

## PART 4: Documentation Cleanup

### Same as before:
- Session docs → `archive/dev-history/`
- Feature docs → `docs/features/`
- Web-ui docs → `docs/web-ui/`

---

## PART 5: Web-UI Cleanup

### Same as before:
- Archive `monitoring-server.js` (deprecated)
- Archive `test-*.js`, `test-*.sh`
- Move `*.md` to `docs/web-ui/`

---

## Revised Cleanup Script

```bash
#!/bin/bash
# cleanup-current-vs-obsolete.sh

set -e

echo "🧹 GRAPE Project Cleanup - Current vs Obsolete"
echo "==============================================="
echo ""
echo "This will:"
echo "  1. Archive old V2 recorder stack"
echo "  2. Archive obsolete shell scripts"
echo "  3. Organize documentation"
echo "  4. Keep current core recorder + analytics"
echo ""

read -p "Continue? (y/N) " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 1

# Safety tag
git tag -f pre-cleanup-v2-archive

# Create archive structure
mkdir -p archive/legacy-code/v2-recorder
mkdir -p archive/shell-scripts/v2-scripts
mkdir -p archive/shell-scripts/debug
mkdir -p archive/shell-scripts/systemd
mkdir -p archive/dev-history

# CRITICAL: Verify V2 not imported by core
echo "Verifying V2 stack not imported by current code..."
if grep -r "grape_channel_recorder_v2\|grape_recorder" src/signal_recorder/*.py | grep -v "^src/signal_recorder/grape_channel_recorder_v2.py" | grep -v "^src/signal_recorder/grape_recorder.py" | grep -v "^src/signal_recorder/grape_rtp_recorder.py"; then
    echo "❌ ERROR: V2 components still imported!"
    echo "Cannot archive safely. Manual review needed."
    exit 1
fi

echo "✓ Safe to archive V2"
echo ""

# Archive V2 Python stack
echo "Archiving V2 recorder stack..."
git mv src/signal_recorder/grape_recorder.py archive/legacy-code/v2-recorder/
git mv src/signal_recorder/grape_channel_recorder_v2.py archive/legacy-code/v2-recorder/
git mv src/signal_recorder/grape_rtp_recorder.py archive/legacy-code/v2-recorder/
git mv src/signal_recorder/minute_file_writer.py archive/legacy-code/v2-recorder/
git mv src/signal_recorder/live_quality_status.py archive/legacy-code/v2-recorder/
git mv src/signal_recorder/grape_metadata.py archive/legacy-code/v2-recorder/

# Archive V2 shell scripts
echo "Archiving V2 shell scripts..."
git mv start-grape-recorder.sh archive/shell-scripts/v2-scripts/
git mv start-grape.sh archive/shell-scripts/v2-scripts/
git mv RESTART-RECORDER.sh archive/shell-scripts/v2-scripts/
git mv restart-recorder-with-new-code.sh archive/shell-scripts/v2-scripts/

# Archive debug scripts
echo "Archiving debug scripts..."
git mv cleanup-buggy-tone-data.sh archive/shell-scripts/debug/
git mv cleanup-corrupt-drf.sh archive/shell-scripts/debug/
git mv cleanup-logs.sh archive/shell-scripts/debug/
git mv cleanup-tmp-grape.sh archive/shell-scripts/debug/
git mv clean-test-data.sh archive/shell-scripts/debug/
git mv generate-carrier-comparison.sh archive/shell-scripts/debug/
git mv test-health-runtime.sh archive/shell-scripts/debug/
git mv test-health-monitoring.sh archive/shell-scripts/debug/
git mv verify-mode-paths.sh archive/shell-scripts/debug/

# Archive systemd scripts (not used)
echo "Archiving systemd scripts..."
git mv install-core-recorder-service.sh archive/shell-scripts/systemd/
git mv core-recorder-ctl.sh archive/shell-scripts/systemd/

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Next steps:"
echo "  1. Verify core recorder still works:"
echo "     ./start-dual-service.sh"
echo "  2. If OK, commit:"
echo "     git commit -m 'Archive obsolete V2 recorder stack'"
echo "  3. If broken, revert:"
echo "     git reset --hard pre-cleanup-v2-archive"
```

---

## Root Directory After Cleanup

### Active Shell Scripts (10 files)
- `start-dual-service.sh` - PRIMARY starter
- `start-core-recorder-direct.sh` - Direct starter
- `start-all-carrier-analytics.sh` - Carrier analytics
- `restart-analytics.sh` - Restart analytics
- `restart-webui.sh` - Restart web UI
- `stop-dual-service.sh` - Stop all
- `start-radiod-monitor.sh` - Monitoring
- `execute-cleanup.sh` - This cleanup script
- `quick-verify.sh` - Quick check (if exists)
- `install-linux.sh` - Installation (if needed)

### Core Docs (7 files)
- `README.md`
- `CONTEXT.md`
- `ARCHITECTURE.md`
- `QUICK_START.md`
- `DEPENDENCIES.md`
- `INSTALLATION.md`
- `SYSTEMD_INSTALLATION.md` (move to docs/?)

---

## Verification Commands

```bash
# 1. Check what imports V2 components
grep -r "grape_channel_recorder_v2\|from.*grape_recorder" src/ --include="*.py"

# 2. Check what uses old CLI
grep -r "signal-recorder daemon" *.sh

# 3. Test current system
./start-dual-service.sh
# Check it starts successfully, then Ctrl+C

# 4. Verify imports still work
python3 -c "import signal_recorder; print('OK')"
```

---

## Summary

**What changes:**
- V2 recorder stack → archived (6 Python files)
- V2 shell scripts → archived (~10 scripts)
- Debug scripts → archived (~10 scripts)
- Session docs → archived (~50 md files)

**What stays:**
- Core recorder stack (3 Python files)
- Analytics service (7 Python files)
- Shared infrastructure (13 Python files)
- Current shell scripts (10 scripts)
- Core documentation (7 md files)

**Result:**
- Clean separation: current vs historical
- No confusion about entry points
- All production code preserved
- History available in archive
