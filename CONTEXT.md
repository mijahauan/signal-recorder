# ------------------------------
# AI PROJECT CONTEXT MANIFEST
# ------------------------------
# Instructions: Paste this entire file at the start of any new chat session
# to provide ground-truth context for the GRAPE Signal Recorder project.

## � IMMEDIATE CONTEXT: Session 2025-11-26 (CRITICAL FOR NEXT SESSION)

**NEXT SESSION GOAL:** Test the core recorder and analytics updates from Nov 26 session.

### What Was Just Committed (2 commits on Nov 26):

**Commit 1:** `acb371d` - Timing metrics system + discrimination enhancements
- NEW: `timing_metrics_writer.py` (628 lines) - Drift, jitter, tone-to-tone measurements
- Enhanced: `wwvh_discrimination.py` - Test signal detection (minutes 8 & 44)
- Fixed: `monitoring-server-v3.js` - Timing quality classification (5-minute threshold)
- Updated: Web-UI timing dashboards and discrimination display

**Commit 2:** `d81efb2` - Critical thread safety + NTP centralization
- CRITICAL: Complete thread safety in `CoreNPZWriter` and `ChannelProcessor`
- CRITICAL: Boundary-aligned time_snap updates (prevents phase discontinuities)
- CRITICAL: Fixed RTP wraparound handling (signed arithmetic)
- PERFORMANCE: Centralized NTP status (90% fewer subprocess calls)
- Removed: Dead code (`_check_ntp_sync` methods)

### Testing Priorities for Next Session:

1. **Start services and verify no errors:**
   ```bash
   cd /home/wsprdaemon/signal-recorder
   source venv/bin/activate
   ./start-dual-service.sh config/grape-config.toml
   tail -f /tmp/grape-test/logs/*.log
   ```

2. **Verify thread safety works:**
   - No deadlocks or hangs
   - Archives written correctly
   - No data corruption

3. **Verify NTP centralization:**
   - Look for "NTP status updated" logs every 10 seconds
   - No subprocess calls from ChannelProcessor or CoreNPZWriter

4. **Verify timing measurements:**
   - Check `/tmp/grape-test/timing/` for drift CSV files
   - Drift values should be realistic (< 100ms typically)
   - Jitter values should be small (< 10ms RMS)

5. **Verify discrimination:**
   - Check `/tmp/grape-test/discrimination/` for test signal CSVs
   - Minutes 8 and 44 should show test signal detections

### Key Documentation for Testing:
- `TIMING_TEST_PLAN.md` - Complete testing procedures
- `CRITICAL_FIXES_IMPLEMENTED.md` - What was fixed and why
- `API_FORMAT_ALIGNMENT.md` - NPZ format verification (27 fields)

### If Issues Arise:
- Thread safety issues → Check `CRITICAL_FIXES_IMPLEMENTED.md`
- NTP issues → Check `NTP_CENTRALIZATION_COMPLETE.md`
- Timing issues → Check `TWO_TIME_BASES_SOLUTION.md`

---

## 0. 📜 CRITICAL: Canonical Contracts

**Before writing ANY code, consult these contracts:**

1. **`CANONICAL_CONTRACTS.md`** - Overview of project standards
2. **`DIRECTORY_STRUCTURE.md`** - WHERE data goes, HOW to name files
3. **`docs/API_REFERENCE.md`** - WHAT functions exist, HOW to call them
4. **`ARCHITECTURE.md`** - WHY the system is designed this way

**Enforcement:** `scripts/validate_api_compliance.py` (must pass before commit)

**Key Rules:**
- ✅ ALL path operations use `GRAPEPaths` API - NO direct path construction
- ✅ ALL function calls match signatures in `API_REFERENCE.md`
- ✅ ALL files follow naming convention: `{CHANNEL}_{METHOD}_YYYYMMDD.csv`
- ✅ NO time-range suffixes on daily files

## 1. 🎯 Core Mission & Objectives

* **Project:** GRAPE Signal Recorder (Global Radio Amateur Propagation Experiment)
* **Mission:** Record and analyze WWV/CHU time-standard signals to study ionospheric disturbances through timing variations. Enables amateur radio operators worldwide to contribute data to HamSCI's global observation network.
* **Core Goal:** Maintain complete, scientifically valid data capture with GPS-quality timestamps (±1ms) via WWV/CHU tone detection. Sample count integrity is paramount - RTP timestamp is the primary reference, not system clock.

## 2. 📜 Guiding Principles (Director's Mandate)

These are the non-negotiable rules for all development.

### Tech Stack:
* **Backend:** Python 3.8+ (signal_recorder package)
* **Core Recorder:** Minimal dependencies (numpy, scipy for decimation)
* **Analytics:** Full scientific stack (scipy, numpy, matplotlib optional)
* **Web UI:** Node.js (Express.js) backend, vanilla HTML/CSS/JS frontend
* **Data Format:** NPZ (NumPy compressed), Digital RF (HDF5), CSV for exports
* **Input:** ka9q-radio RTP multicast streams

### Timing Architecture (KA9Q-Based - CRITICAL):
* **RTP timestamp is PRIMARY reference** - Never "stretch" time to fit wall clock
* **time_snap mechanism:** WWV/CHU tone rising edge at :00.000 anchors RTP to UTC
* **UTC reconstruction:** `utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate`
* **Gap handling:** Fill with zeros to maintain sample count integrity
* **Monotonic indexing:** No backwards time, even during NTP adjustments
* **Quality annotation:** Always upload, annotate timing quality (tone_locked/ntp_synced/wall_clock)

**✅ FIXED (2025-11-23):** Core recorder now uses RTP timestamp as primary reference with timing hierarchy (time_snap > NTP > wall_clock). Files written when sample count reaches 960,000 (60 seconds @ 16kHz). See `CORE_RECORDER_BUG_NOTES.md` for fix details.

**✅ FIXED (2025-11-26):** Critical thread safety and performance fixes:
- **Thread Safety:** All shared state in `CoreNPZWriter` and `ChannelProcessor` protected by `threading.Lock`
- **Phase Continuity:** Time_snap updates only applied at minute boundaries (no mid-file discontinuities)
- **RTP Wraparound:** Fixed signed arithmetic for 32-bit RTP timestamp wraparound (~74 hours @ 16kHz)
- **NTP Centralization:** Single subprocess call point in `CoreRecorder` (90% reduction, zero blocking in critical path)
- See `CRITICAL_FIXES_IMPLEMENTED.md` for complete details.

### Code Style:
* Follow PEP 8 for Python code
* Type hints required for all public functions
* Docstrings required (Google style preferred)
* Use numpy-style docstrings for scientific functions
* Preserve line-by-line traceability for signal processing

### Testing:
* All signal processing changes must be tested with real WWV data
* Test data location: `/tmp/grape-test/archives/WWV_5_MHz/`
* Activate venv before testing or running and code: `source venv/bin/activate`
* Test scripts available: `test-drf-writer.py`, `test-wwvh-discrimination.py`

### Scientific Principles:
* **Doppler shifts are DATA, not artifacts** - Frequency variations in 10 Hz carrier are ionospheric measurements (±0.1 Hz = ±3 km path resolution)
* **Sample completeness > SNR** - 100% of samples (even noisy) beats 95% of clean signal
* **Gap transparency** - Document all discontinuities, never hide data quality issues
* **Reprocessability** - Original 16 kHz archives preserved forever, analytics can rerun

### Web-UI/Analytics Synchronization:
* **CRITICAL**: Use centralized GRAPEPaths API for all file paths
* **Python API**: `src/signal_recorder/paths.py`
* **JavaScript API**: `web-ui/grape-paths.js`
* **Protocol**: `WEB_UI_ANALYTICS_SYNC_PROTOCOL.md` (comprehensive guide)
* **Validation**: Run `./scripts/validate-paths-sync.sh` before committing path changes
* **Rule**: When adding analytics paths, update BOTH Python and JavaScript implementations simultaneously
* **Server**: Use `monitoring-server-v3.js` (NOT deprecated `monitoring-server.js`)

### Git Process:
* Main branch is `main`
* Commit messages should be descriptive with technical details
* Include file change summaries and test results in commits
* Document architecture changes in markdown files

## 3. 🗺️ Key Components (The API Map)

This is a high-level map of the project's most important, stable interfaces.

### Core Services

* **`grape_channel_recorder_v2.py`**: Core RTP recorder (~300 lines, changes <5x/year)
  * `run()`: RTP → resequence → gap fill → 16kHz NPZ archive
  * Output: `{timestamp}_iq.npz` with RTP timestamps

* **`analytics_service.py`**: Per-channel analytics
  * `process_archive()`: Tone detection → 5 discrimination methods → decimation → quality metrics
  * Output: `{timestamp}_iq_10hz.npz` + separated CSVs per method

* **`drf_writer_service.py`**: Digital RF converter (wsprdaemon-compatible)
  * Reads: 10 Hz NPZ → Writes: Digital RF HDF5 (float32 I/Q pairs)
  * Two modes: `--wsprdaemon-compatible` (default) | `--enhanced-metadata`
  * Closes writer after each file to flush data (Digital RF requirement)

### Signal Processing Modules

* **`tone_detector.py`**: `MultiStationToneDetector.process_samples()` → `List[ToneDetectionResult]`
  * **CRITICAL:** Requires 3 kHz resampling

* **`wwvh_discrimination.py`**: `WWVHDiscriminator.analyze_minute_with_440hz()` → `DiscriminationResult`
  * WWV: 2.5/5/10/15/20/25 MHz | WWVH: 2.5/5/10/15 MHz only (frequency-aware)

* **`decimation.py`**: `decimate_for_upload(iq, input_rate, output_rate)`
  * 3-stage: CIC (16kHz→400Hz) → compensation FIR → final FIR (400Hz→10Hz)
  * Flat passband 0-5 Hz, ±0.1 Hz Doppler resolution

### Web UI (Node.js/Express + vanilla JS)

* **`monitoring-server-v3.js`**: REST API for real-time metrics
* **Pages:** summary.html (overview), carrier.html (spectrograms), channels.html (details), discrimination.html (WWV-H analysis)

### Data Models (interfaces/data_models.py)

`NPZArchive` | `ToneDetectionResult` | `TimeSnapReference` | `QualityInfo` | `DiscriminationResult`

## 4. ⚡ Recent Sessions Summary

**SESSION_2025-11-26**: Critical Thread Safety + Timing System ⭐⭐⭐ (JUST COMMITTED)
- ✅ **Thread Safety:** Complete lock protection in `CoreNPZWriter` and `ChannelProcessor`
- ✅ **Phase Continuity:** Boundary-aligned time_snap updates (no mid-file discontinuities)
- ✅ **RTP Wraparound:** Fixed signed arithmetic for 32-bit timestamp wraparound
- ✅ **NTP Centralization:** 90% reduction in subprocess calls, zero blocking in critical path
- ✅ **Timing Metrics:** NEW `timing_metrics_writer.py` with drift, jitter, tone-to-tone measurements
- ✅ **Test Signal Detection:** Enhanced discrimination for minutes 8 and 44
- ✅ **Web-UI Fixes:** Timing quality classification, test signal display
- 📁 Core files: `core_recorder.py`, `core_npz_writer.py`, `analytics_service.py`
- 📁 New: `timing_metrics_writer.py` (628 lines)
- 📁 Documentation: 16 new files including `CRITICAL_FIXES_IMPLEMENTED.md`, `TIMING_TEST_PLAN.md`
- 🧪 **NEXT:** Test the updates - verify thread safety, timing measurements, discrimination
- **Commits:** `acb371d` (timing/discrimination), `d81efb2` (thread safety/NTP)

**SESSION_2025-11-24_ANALYTICS_METADATA_INTEGRATION.md**: Analytics Metadata Integration Complete ⭐⭐
- ✅ Analytics now reads and uses time_snap metadata from recorder NPZ files
- ✅ Archive time_snap adoption: Analytics automatically adopts recorder-provided time_snap when superior
- ✅ Tone power comparison: Cross-validates analytics detections against recorder startup measurements
- ✅ All 6 analytics pipelines validated end-to-end with comprehensive test suite
- ✅ NPZArchive extended with new fields: time_snap_rtp/utc/source/confidence/station, tone_power_1000/1200_hz_db
- ✅ Methods added: _store_time_snap(), _maybe_adopt_archive_time_snap(), _compare_recorder_tones()
- ✅ Metadata flow verified: Recorder → NPZ → Analytics → Decimated 10Hz NPZ → DRF/Upload
- 📁 Modified: src/signal_recorder/analytics_service.py (lines 111-122, 147-156, 178-224, 410-440, 811-878, 945-946, 1041-1042)
- 🧪 Test script: /tmp/test_analytics_pipelines.py (comprehensive validation of all pipelines)

**SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md**: DRF Writer Production Ready ⭐
- ✅ Digital RF output now matches wsprdaemon format exactly (PSWS-compatible)
- ✅ Two modes: wsprdaemon-compatible (default) | enhanced metadata (optional)
- ✅ Data format: float32 (N,2) for I/Q pairs (not complex64) with is_complex=True
- ✅ Writer lifecycle: Explicit close after each file to flush data to disk
- ✅ All tests passing: Directory structure ✅ | Metadata format ✅ | Sample data ✅
- 📁 New files: docs/DRF_WRITER_MODES.md, test-drf-wsprdaemon-compat.py, test-drf-quick.sh

**SESSION_2025-11-20_CANONICAL_CONTRACTS.md**: Foundational contracts ⭐
- ✅ CANONICAL_CONTRACTS.md, DIRECTORY_STRUCTURE.md, unified API_REFERENCE.md
- ✅ GRAPEPaths API mandatory for ALL path operations
- ✅ validate_api_compliance.py enforces contracts
- ✅ File naming: {CHANNEL}_{METHOD}_YYYYMMDD.csv (NO time-range suffixes)

**5 Independent Discrimination Methods** (Nov 2025):
- Method 1: Timing Tones (1000/1200 Hz power ratio) → tone_detections/
- Method 2: Tick Windows (5ms coherent) → tick_windows/
- Method 3: Station ID (440 Hz min 1/2) → station_id_440hz/
- Method 4: BCD (100 Hz subcarrier) → bcd_discrimination/
- Method 5: Weighted Voting (final) → discrimination/

**Earlier Key Changes:**
- Optimized 3-stage decimation: CIC → compensation FIR → final FIR (flat passband 0-5 Hz)
- Fixed 30-second timing offset bug in tone detector
- RTP offset correlation proven UNSTABLE (independent clocks per channel)

## 5. 🎯 Next Session: Test Core Recorder and Analytics Updates

**Objective:** Verify the Nov 26 critical fixes work correctly in production.

**What to Test:**

### 1. Thread Safety Verification
```bash
# Start services
./start-dual-service.sh config/grape-config.toml

# Monitor for deadlocks or errors
tail -f /tmp/grape-test/logs/core-recorder.log | grep -E "(ERROR|WARN|Lock|Deadlock)"

# Verify archives being written (should see new files every minute)
watch -n 5 'ls -la /tmp/grape-test/archives/WWV_10_MHz/*.npz | tail -5'
```

### 2. NTP Centralization Verification
```bash
# Should see NTP status updates every 10 seconds in main loop
grep "NTP status" /tmp/grape-test/logs/core-recorder.log

# Should NOT see subprocess calls from ChannelProcessor
grep -E "(chronyc|ntpq)" /tmp/grape-test/logs/core-recorder.log
```

### 3. Timing Metrics Verification
```bash
# Check timing CSV files exist
ls -la /tmp/grape-test/timing/WWV_10_MHz/

# Verify drift values are realistic (< 100ms)
tail -20 /tmp/grape-test/timing/WWV_10_MHz/*timing*.csv

# Check for tone-to-tone measurements
grep "tone_to_tone" /tmp/grape-test/timing/WWV_10_MHz/*timing*.csv
```

### 4. Discrimination Verification
```bash
# Check test signal detection (minutes 8 and 44)
ls -la /tmp/grape-test/discrimination/WWV_10_MHz/test_signal/

# Verify discrimination results
tail -20 /tmp/grape-test/discrimination/WWV_10_MHz/*discrimination*.csv
```

### 5. NPZ Format Verification
```python
# Quick Python check of NPZ format (27 fields expected)
import numpy as np
npz = np.load('/tmp/grape-test/archives/WWV_10_MHz/LATEST.npz')
print(f"Fields: {len(npz.files)}")
print(f"Has time_snap: {'time_snap_rtp' in npz.files}")
print(f"Has NTP wall clock: {'ntp_wall_clock_time' in npz.files}")
```

**Success Criteria:**
- ✅ No errors in logs
- ✅ Archives written every minute
- ✅ NTP status updates every 10 seconds
- ✅ Drift values < 100ms
- ✅ No deadlocks after 30+ minutes
- ✅ All 27 NPZ fields present

**If Issues:**
- Thread issues → `CRITICAL_FIXES_IMPLEMENTED.md`
- NTP issues → `NTP_CENTRALIZATION_COMPLETE.md`
- Timing issues → `TWO_TIME_BASES_SOLUTION.md`
- Format issues → `API_FORMAT_ALIGNMENT.md`

---

## 📍 Quick Reference

### File Locations (Test Mode)

**CRITICAL:** Use `GRAPEPaths` API - never construct paths directly!

```
archives/{channel}/               → paths.get_archive_dir()        | 16kHz NPZ
analytics/{channel}/
  decimated/                      → paths.get_decimated_dir()      | 10Hz NPZ
  tone_detections/                → paths.get_tone_detections_dir()| Method 1 CSV
  tick_windows/                   → paths.get_tick_windows_dir()   | Method 2 CSV
  station_id_440hz/               → paths.get_station_id_440hz_dir()| Method 3 CSV
  bcd_discrimination/             → paths.get_bcd_discrimination_dir()| Method 4 CSV
  discrimination/                 → paths.get_discrimination_dir()  | Method 5 CSV (final)
  quality/                        → paths.get_quality_dir()        | Quality CSV
  digital_rf/                     → paths.get_digital_rf_dir()     | DRF HDF5
spectrograms/{YYYYMMDD}/                                           | PNG
state/analytics-{channel}.json                                     | time_snap
```

### Station Frequencies

**WWV:** 2.5/5/10/15/20/25 MHz | 1000 Hz tone (0.8s) | Voice ID minute 2  
**WWVH:** 2.5/5/10/15 MHz ONLY | 1200 Hz tone (0.8s) | Voice ID minute 1 (440 Hz)  
**CHU:** 3.33/7.85/14.67 MHz | 1000 Hz tone (0.5s)

### 5 Discrimination Methods (separated CSVs)

1. **Timing Tones** (1000/1200 Hz power ratio) → tone_detections/
2. **Tick Windows** (5ms coherent integration) → tick_windows/
3. **Station ID** (440 Hz min 1=WWVH, 2=WWV) → station_id_440hz/
4. **BCD** (100 Hz subcarrier analysis) → bcd_discrimination/
5. **Weighted Voting** (final determination) → discrimination/

### Essential Documentation

**⭐ FOUR PILLARS (before code changes):**
- `CANONICAL_CONTRACTS.md` - Standards (START HERE)
- `DIRECTORY_STRUCTURE.md` - Paths & naming
- `docs/API_REFERENCE.md` - Functions
- `ARCHITECTURE.md` - Design rationale

**⭐ Nov 26 Session Docs (for testing):**
- `CRITICAL_FIXES_IMPLEMENTED.md` - Thread safety, phase continuity, RTP wraparound
- `NTP_CENTRALIZATION_COMPLETE.md` - Centralized NTP status architecture
- `TIMING_TEST_PLAN.md` - Complete testing procedures
- `API_FORMAT_ALIGNMENT.md` - NPZ format verification (27 fields)
- `TWO_TIME_BASES_SOLUTION.md` - Timing measurement methodology

**Key Docs:**
- `docs/DRF_WRITER_MODES.md` - Wsprdaemon vs enhanced metadata
- `SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md` - DRF writer completion
- `scripts/validate_api_compliance.py` - Enforcement tool

### Timing & Quality

**Timing Quality:** TONE_LOCKED (±1ms) > NTP_SYNCED (±10ms) > WALL_CLOCK (±seconds)  
**Quality Grades:** A (95-100) excellent | B (85-94) good | C (70-84) acceptable | D (50-69) poor | F (<50) failed  
**Weighting:** Sample integrity 40% | RTP continuity 30% | Time_snap 20% | Network 10%

### Key Implementation Details (Nov 26)

**Thread Safety Pattern:**
```python
# All shared state access in CoreNPZWriter and ChannelProcessor:
with self._lock:
    # Access or modify shared state
```

**NTP Status Access Pattern:**
```python
# In ChannelProcessor or CoreNPZWriter:
if self.get_ntp_status:
    ntp_status = self.get_ntp_status()  # Returns cached dict
    offset_ms = ntp_status.get('offset_ms')
    synced = ntp_status.get('synced')
```

**Boundary-Aligned Time_snap:**
```python
# In CoreNPZWriter.update_time_snap():
self.pending_time_snap = new_time_snap  # Schedule, don't apply

# In CoreNPZWriter.add_samples() after minute file written:
if self.pending_time_snap:
    self.time_snap = self.pending_time_snap
    self.pending_time_snap = None
```
