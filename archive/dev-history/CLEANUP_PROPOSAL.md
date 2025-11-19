# Project Cleanup Proposal

## Executive Summary

This project has accumulated significant clutter from iterative development. This proposal identifies files that are:
- **OBSOLETE**: No longer used and should be archived or deleted
- **ACTIVE**: Currently used by core-recorder, analytics, or web-ui
- **DUPLICATE**: Session summaries and documentation that should be consolidated

## ⚠️ CRITICAL FINDING: Two Parallel Recording Systems

The codebase contains TWO complete recording implementations:

### 1. V2 Stack (Currently Running in Production)
- **Entry Point:** `grape_recorder.py` (used by systemd)
- **Path:** `grape_recorder.py` → `grape_rtp_recorder.py` → `grape_channel_recorder_v2.py`
- **Size:** ~2000 lines, integrated analytics
- **Last Modified:** Nov 17, 2025
- **Status:** ✅ **ACTIVE - DO NOT DELETE**

### 2. Core/Analytics Split (Newer Design, Not Yet Deployed)
- **Entry Point:** `core_recorder.py` (not used by systemd)
- **Path:** `core_recorder.py` → `packet_resequencer.py` + `core_npz_writer.py`
- **Size:** ~300 lines, minimal NPZ-only writer
- **Last Modified:** Nov 18, 2025 (very recent!)
- **Purpose:** Cleaner separation (see `CORE_ANALYTICS_SPLIT_DESIGN.md`)
- **Status:** ⚠️ **FUTURE REPLACEMENT - KEEP FOR NOW**

### Recommendation
**DO NOT DELETE EITHER STACK.** The Core stack is a planned improvement, not obsolete code. Once Core is production-ready and deployed, THEN archive the V2 stack.

## Current System Architecture

### Active Services (DO NOT DELETE)
1. **Current Recorder**: `grape_recorder.py` → V2 stack (production)
2. **Future Recorder**: `core_recorder.py` → Core stack (planned)
3. **Analytics Service**: `analytics_service.py` (works with both)
4. **Web UI**: `monitoring-server-v3.js`

---

## PART 1: Source Code Cleanup (`src/signal_recorder/`)

### ✅ ACTIVE - Keep These Files

**CURRENT RECORDING PATH (V2 - Production):**
- `grape_recorder.py` - Main entry point for systemd service
- `grape_rtp_recorder.py` - RTP receiver and manager (uses V2 recorders)
- `grape_channel_recorder_v2.py` - V2 channel recorder (current production code)
- `minute_file_writer.py` - File writer (used by V2)
- `live_quality_status.py` - Live status (used by V2)
- `grape_metadata.py` - Metadata generation (used by V2)

**ALTERNATIVE PATH (Core Recorder - Minimal Design):**
- `core_recorder.py` - Alternative minimal NPZ writer (300 lines)
- `core_npz_writer.py` - NPZ file format handler for core recorder
- `packet_resequencer.py` - RTP packet ordering (used by core_recorder)

**Analytics Stack:**
- `analytics_service.py` - Main analytics processor
- `tone_detector.py` - WWV/CHU/WWVH detection
- `wwvh_discrimination.py` - Differential delay analysis
- `decimation.py` - 16kHz → 10Hz downsampling
- `digital_rf_writer.py` - Digital RF output format
- `drf_writer_service.py` - Digital RF service wrapper
- `quality_metrics.py` - Data quality calculations

**Shared Infrastructure:**
- `config_utils.py` - Configuration parsing
- `paths.py` - Centralized path management
- `channel_manager.py` - Channel configuration
- `radiod_health.py` - ka9q-radio monitoring
- `session_tracker.py` - Session state management
- `gap_backfill.py` - Gap filling logic
- `uploader.py` - Upload management (used in __init__.py)
- `data_management.py` - Data management (used by cli.py)
- `cli.py` - CLI interface (used by __main__.py)
- `__init__.py` - Package exports
- `__main__.py` - Entry point for `python -m signal_recorder`
- `audio_stream.py` - Audio streaming (used by __main__.py)
- `audio_streamer.py` - Audio streaming backend

**Interfaces (data models):**
- `interfaces/` directory - Keep entire directory

**Legacy Code (Not Actively Used but Imported):**
- `legacy/` directory - Contains old app.py but references uploader, keep for now

### ⚠️ POTENTIALLY REDUNDANT - Needs Investigation

**Core Recorder vs V2 Recorder:**
The system appears to have TWO complete recording stacks:

1. **V2 Stack (Currently Active):**
   - Entry: `grape_recorder.py` → `grape_rtp_recorder.py` → `grape_channel_recorder_v2.py`
   - Used by: `systemd/grape-core-recorder.service`
   - Features: Full analytics, tone detection, quality metrics

2. **Core Stack (Alternative Design?):**
   - Entry: `core_recorder.py` → `core_npz_writer.py` + `packet_resequencer.py`
   - Purpose: Minimal, rock-solid NPZ-only writer (no analytics)
   - Status: **Not currently used by systemd services**

**QUESTION:** Is `core_recorder.py` an alternative design that should replace V2, or is it obsolete?

### 🗑️ TRULY OBSOLETE - Can Safely Archive

- None identified yet - need to resolve core_recorder vs V2 question first

### 🔍 INVESTIGATE - Check Dependencies

These files may be transitional or partially used:
- `__init__.py` - Check what it exports
- `__main__.py` - Used for `python -m signal_recorder`

---

## PART 2: Scripts Cleanup (`scripts/`)

### ✅ ACTIVE - Production Scripts

**Currently Used:**
- `generate_spectrograms.py` - Spectrogram generation (referenced by systemd timer)
- `monitor_radiod_health.py` - Health monitoring (referenced by systemd service)
- `auto-generate-spectrograms.sh` - Automated spectrogram wrapper

### 🧪 USEFUL - Diagnostic/Admin Tools

**Keep for troubleshooting:**
- `show_quality_summary.py` - Data quality checks
- `generate_quality_report.py` - Quality reporting
- `check_wwv_detections.sh` - WWV detection verification
- `backfill-now.sh` - Manual gap backfilling

### 📊 ANALYSIS - One-time Investigation Scripts

**Archive to `archive/test-scripts/`:**
- `analyze_correlations.py` - Completed RTP correlation analysis
- `analyze_decimation_quality.py` - Completed decimation validation
- `analyze_timing.py` - Completed timing analysis
- `compare_timing_methods.py` - Completed timing comparison
- `compare_tone_detectors.py` - Completed detector comparison
- `measure_rtp_offset.py` - Completed RTP investigation
- `quick_decimate_for_comparison.py` - Test script

### 🔧 DEVELOPMENT - Test/Debug Scripts

**Archive to `archive/test-scripts/`:**
- `test_timing_quality.sh` - Development testing
- `validate-paths-sync.sh` - Path API validation (completed)
- `test-*.sh` - All test scripts
- `generate_spectrograms_v2.py` - Old version (replaced)
- `generate_spectrograms_drf.py` - Experimental version
- `generate_spectrograms_from_*.py` - Experimental variants

### 🔄 DATA MIGRATION - One-time Use

**Archive (historical record):**
- `migrate-data-storage.sh` - Historical data migration
- `regenerate_drf_from_npz.py` - Data reprocessing (completed)
- `reprocess_drf_timestamps.py` - Timestamp correction (completed)
- `generate_10hz_npz.py` - Migration script

---

## PART 3: Documentation Cleanup (Root `.md` Files)

### Current State: 70+ Markdown Files at Root

### ✅ ESSENTIAL - Keep at Root

**Primary Documentation:**
- `README.md` - Project overview
- `CONTEXT.md` - Current system state
- `ARCHITECTURE.md` - System architecture
- `QUICK_START.md` - Getting started guide
- `DEPENDENCIES.md` - System requirements

**Installation Guides:**
- `INSTALLATION.md` - Main installation
- `SYSTEMD_INSTALLATION.md` - Service setup

### 📁 MOVE TO `docs/`

**Feature Documentation:**
- `TIMING_*` - All timing-related docs
- `QUALITY_*` - All quality metric docs
- `CARRIER_*` - All carrier channel docs
- `WWV_*` / `WWVH_*` - Tone detection docs
- `DIGITAL_RF_*` - Digital RF docs
- `DRF_*` - Digital RF docs
- `SPECTROGRAM_*` - Spectrogram docs

### 🗄️ ARCHIVE - Session Summaries

**Move to `archive/dev-history/`:**
- `SESSION_*.md` - All session summaries (50+ files)
- `*_COMPLETE.md` - All completion summaries
- `*_IMPLEMENTATION.md` - Implementation notes
- `*_SUMMARY.md` - Summary documents
- `PHASE*_COMPLETE.md` - Phase completion docs
- `OVERNIGHT_STATUS.md` - Status snapshots
- `NEXT_STEPS.md` - Historical planning
- `REVIEW_SUMMARY.md` - Historical reviews

These are valuable historical records but clutter the workspace.

---

## PART 4: Web UI Cleanup (`web-ui/`)

### ✅ ACTIVE - Production Files

**Server:**
- `monitoring-server-v3.js` - **CURRENT** production server
- `grape-paths.js` - Path API integration
- `middleware/validation.js` - Security validation
- `utils/*.js` - Utility modules

**HTML Pages:**
- `index.html` - Landing page
- `simple-dashboard.html` - Main dashboard
- `timing-dashboard.html` - Timing analysis
- `channels.html` - Channel management
- `carrier.html` - Carrier analysis
- `discrimination.html` - WWV/WWVH discrimination
- `summary.html` - Summary view
- `analysis.html` - Analysis view

**Scripts:**
- `discrimination.js` - Discrimination page logic
- `start-monitoring.sh` - Server startup script

### ⚠️ OBSOLETE - Archive or Delete

**Deprecated Servers:**
- `monitoring-server.js` - **DEPRECATED** (file explicitly warns)
- `simple-server.js.ARCHIVED-config-ui` - Already archived

**Test/Debug:**
- `test-*.js` - Test scripts
- `test-*.cjs` - Test scripts
- `test-*.sh` - Test scripts

**Development Artifacts:**
- `monitoring-server.log` - Log file (should be in logs/)
- `build-output.txt` - Build log
- `cookies.txt` - Test artifact

### 📄 Documentation in Web UI

**Move to main `docs/web-ui/`:**
- All `*.md` files in web-ui root
- Consolidate with main documentation

---

## PART 5: Archive Organization

### Current Archive Structure
```
archive/
├── dev-history/     # Development session summaries
├── legacy-code/     # V1 code and old implementations
├── shell-scripts/   # Obsolete shell scripts
└── test-scripts/    # One-time analysis/test scripts
```

### Recommended Actions

1. **Move obsolete Python modules:**
   ```
   src/signal_recorder/grape_channel_recorder_v2.py → archive/legacy-code/
   src/signal_recorder/minute_file_writer.py → archive/legacy-code/
   src/signal_recorder/data_management.py → archive/legacy-code/
   src/signal_recorder/uploader.py → archive/legacy-code/
   src/signal_recorder/audio_stream.py → archive/legacy-code/
   src/signal_recorder/audio_streamer.py → archive/legacy-code/
   src/signal_recorder/live_quality_status.py → archive/legacy-code/
   src/signal_recorder/grape_metadata.py → archive/legacy-code/
   ```

2. **Move test/analysis scripts:**
   ```
   scripts/analyze_*.py → archive/test-scripts/
   scripts/compare_*.py → archive/test-scripts/
   scripts/measure_*.py → archive/test-scripts/
   scripts/*test*.sh → archive/test-scripts/
   scripts/quick_*.py → archive/test-scripts/
   scripts/generate_spectrograms_v2.py → archive/test-scripts/
   scripts/generate_spectrograms_drf.py → archive/test-scripts/
   scripts/generate_spectrograms_from_*.py → archive/test-scripts/
   ```

3. **Move session docs:**
   ```
   *_COMPLETE.md → archive/dev-history/
   *_IMPLEMENTATION.md → archive/dev-history/
   *_SUMMARY.md → archive/dev-history/
   SESSION_*.md → archive/dev-history/
   PHASE*.md → archive/dev-history/
   ```

4. **Move web-ui test files:**
   ```
   web-ui/test-*.* → archive/test-scripts/web-ui/
   web-ui/monitoring-server.js → archive/legacy-code/web-ui/
   ```

---

## PART 6: Root Directory Organization

### Proposed Root Structure

```
signal-recorder/
├── README.md                    # Project overview
├── CONTEXT.md                   # Current system state
├── ARCHITECTURE.md              # System architecture
├── QUICK_START.md               # Getting started
├── DEPENDENCIES.md              # Requirements
├── INSTALLATION.md              # Installation guide
├── SYSTEMD_INSTALLATION.md      # Systemd setup
├── LICENSE                      # License
├── MANIFEST.in                  # Package manifest
├── setup.py / pyproject.toml    # Package config
│
├── config/                      # Configuration files
├── src/                         # Source code
├── scripts/                     # Production & admin scripts
├── systemd/                     # Service definitions
├── web-ui/                      # Web interface
├── examples/                    # Usage examples
├── docs/                        # Feature documentation
├── archive/                     # Historical code & docs
├── logs/                        # Log files
└── data/                        # Runtime data
```

### Clean Scripts Directory

**Production/Admin Only:**
```
scripts/
├── generate_spectrograms.py         # Production
├── monitor_radiod_health.py         # Production
├── auto-generate-spectrograms.sh    # Production
├── show_quality_summary.py          # Admin tool
├── generate_quality_report.py       # Admin tool
├── check_wwv_detections.sh          # Admin tool
├── backfill-now.sh                  # Admin tool
├── today-quality.sh                 # Quick check
└── run-quality-analysis.sh          # Quick check
```

All analysis/test scripts moved to `archive/test-scripts/`.

---

## PART 7: Recommended Cleanup Sequence

### Phase 1: Safe Archive (Reversible)
1. Create backup: `git tag pre-cleanup-backup`
2. Move obsolete source files to `archive/legacy-code/`
3. Move test scripts to `archive/test-scripts/`
4. Move session docs to `archive/dev-history/`

### Phase 2: Documentation Organization
1. Move feature docs to `docs/`
2. Create `docs/web-ui/` and consolidate web UI docs
3. Update cross-references in remaining docs

### Phase 3: Verification
1. Verify core-recorder starts: `systemctl status grape-core-recorder`
2. Verify analytics service starts: `python -m signal_recorder.analytics_service`
3. Verify web UI starts: `cd web-ui && node monitoring-server-v3.js`
4. Run test suite (if exists)

### Phase 4: Final Cleanup
1. Delete obvious garbage (`.log`, build artifacts, etc.)
2. Update `.gitignore` if needed
3. Commit with detailed message documenting cleanup

---

## Implementation Notes

### Files Requiring Careful Review

**`src/signal_recorder/__init__.py`:**
- Check what symbols it exports
- Ensure nothing imports from moved modules

**`src/signal_recorder/cli.py`:**
- Verify if still used as entry point
- Check if referenced in setup.py/pyproject.toml

**Systemd Services:**
- Ensure all `ExecStart` commands point to existing files
- Update paths if modules are moved

### Testing After Cleanup

```bash
# Test core recorder
python3 -m signal_recorder.grape_recorder --config config/grape-config.toml

# Test analytics service
python3 -m signal_recorder.analytics_service --config config/grape-config.toml

# Test web UI
cd web-ui && node monitoring-server-v3.js

# Verify imports
python3 -c "import signal_recorder; print('OK')"
```

---

## Risk Assessment

### Low Risk (Safe to Archive)
- Session summaries and historical docs
- Test/analysis scripts (one-time use)
- Deprecated web server files (marked as deprecated)

### Medium Risk (Verify First)
- Old Python modules (check for hidden imports)
- Scripts with unclear usage

### High Risk (Manual Review Required)
- `__init__.py` exports
- Systemd service entry points
- Any file with recent modification dates

---

## Expected Outcomes

### Before Cleanup
- 70+ markdown files at root
- 30+ scripts (unclear which are used)
- 20+ Python modules (mix of active/legacy)
- Confusing file names (v2 that's actually v1)

### After Cleanup
- 7 core docs at root
- 10 production/admin scripts
- 15 active Python modules
- Clear separation: active vs archived

### Benefits
- **Clarity**: Easy to find current code
- **Maintainability**: Reduced confusion about what's in use
- **Onboarding**: New developers see clean structure
- **Safety**: Historical code preserved in archive

---

## Questions for Review

1. **Are any of the "obsolete" Python modules still imported somewhere?**
   - Run: `grep -r "import.*<module_name>" src/`

2. **Are any scripts called by cron or other automation?**
   - Check: `crontab -l`, systemd timers

3. **Are there any hard-coded paths that need updating?**
   - Search for absolute paths in code

4. **Should we keep multiple versions of spectrogram generators?**
   - Or consolidate to single production version?

---

## Next Steps

1. **Review this proposal** - Confirm archive vs delete decisions
2. **Create git tag** - Safety backup before changes
3. **Execute Phase 1** - Archive obsolete files (reversible)
4. **Test thoroughly** - Verify all services work
5. **Execute Phases 2-4** - Complete cleanup
6. **Update CONTEXT.md** - Document clean structure

**Estimated Time:** 2-3 hours for full cleanup and verification
