# ------------------------------
# AI PROJECT CONTEXT MANIFEST
# ------------------------------
# Instructions: Paste this entire file at the start of any new chat session
# to provide ground-truth context for the GRAPE Signal Recorder project.

## 🚨 IMMEDIATE CONTEXT: Session 2025-11-26 Late Evening

### What Was Just Completed (Nov 26 Late Evening - Audio Streaming):

**Audio Streaming on Summary Page - IMPLEMENTED** ✅

Users can now listen to any WWV/CHU channel directly from the Summary page.

**Architecture:**
- **Audio SSRC:** IQ_SSRC + 999 (e.g., 10 MHz uses SSRC 10000999)
- **Channel Type:** AM demodulation with AGC enabled
- **Sample Rate:** 12 kHz audio
- **Transport:** WebSocket streaming of PCM audio to browser Web Audio API

**Files Created:**
- `web-ui/radiod_audio_client.py` - Python client for ka9q-radio AM channel management
  - `get_or_create_audio_channel()` - Creates AM channel with AGC
  - `stop_audio_channel()` - Deletes audio channel
  - Uses ka9q-python library from `/home/wsprdaemon/SWL-ka9q`

**Files Modified:**
- `web-ui/monitoring-server-v3.js`:
  - Added `Ka9qRadioProxy` class for RTP multicast → WebSocket forwarding
  - Added audio API endpoints:
    - `GET /api/v1/audio/channels` - List channels with audio SSRCs
    - `GET /api/v1/audio/stream/:channel` - Start audio stream
    - `DELETE /api/v1/audio/stream/:ssrc` - Stop audio stream
    - `GET /api/v1/audio/health` - Audio proxy health check
    - `WS /api/v1/audio/ws/:ssrc` - WebSocket for audio data
  - WebSocket server for audio streaming
  - Graceful shutdown handling

- `web-ui/summary.html`:
  - Added `GRAPEAudioPlayer` class (Web Audio API playback)
  - Audio player panel with volume control
  - Working audio buttons for each channel
  - Visual feedback (loading/playing/error states)

- `web-ui/package.json`:
  - Added `ws` dependency for WebSocket support

**Usage:**
1. Open Summary page: `http://localhost:3000/summary.html`
2. Click 🔈 button on any channel row
3. Audio player panel appears with Stop button and volume control
4. Click again or ⏹ to stop

**Audio SSRC Mapping:**
| Channel | IQ SSRC | Audio SSRC |
|---------|---------|------------|
| WWV 2.5 MHz | 2500000 | 2500999 |
| WWV 5 MHz | 5000000 | 5000999 |
| WWV 10 MHz | 10000000 | 10000999 |
| WWV 15 MHz | 15000000 | 15000999 |
| WWV 20 MHz | 20000000 | 20000999 |
| WWV 25 MHz | 25000000 | 25000999 |
| CHU 3.33 MHz | 3330000 | 3330999 |
| CHU 7.85 MHz | 7850000 | 7850999 |
| CHU 14.67 MHz | 14670000 | 14670999 |

---

### Previous Session (Nov 26 Evening - BCD Geographic & Spectrograms):

**1. Geographic ToA Prediction for BCD Dual Peaks:**
- **Problem:** BCD correlation discrimination was assuming WWV always arrives first (early peak)
- **Solution:** Added `classify_dual_peaks()` method to `WWVGeographicPredictor` that uses geographic propagation delay to determine which station (WWV or WWVH) corresponds to early/late peaks
- **Key Logic:** If `delta_geo < 0` (WWV closer), WWV = early peak; else WWVH = early peak
- **Files Changed:** 
  - `src/signal_recorder/wwv_geographic_predictor.py` (lines 367-434) - Added `classify_dual_peaks()`
  - `src/signal_recorder/wwvh_discrimination.py` (lines 1539-1616) - Use geographic predictor in `bcd_correlation_discrimination()`

**2. Test Signal ToA Offset Measurement:**
- **Purpose:** High-precision ionospheric channel characterization from test signals (minutes :08 and :44)
- **Implementation:** Calculate `toa_offset_ms = (detected_start - expected_start) * 1000`
- **Expected start:** 13.0 seconds into minute (after 10s voice + 2s noise + 1s blank)
- **Files Changed:**
  - `src/signal_recorder/wwv_test_signal.py` (lines 40-68, 396-428) - Added `toa_offset_ms` field to `TestSignalDetection`
  - `src/signal_recorder/wwvh_discrimination.py` (lines 80-89, 2046-2059) - Added `test_signal_toa_offset_ms` to `DiscriminationResult`
  - `src/signal_recorder/discrimination_csv_writers.py` (lines 87-92, 266-295) - Added ToA offset to CSV output
  - `src/signal_recorder/analytics_service.py` (lines 1389-1404) - Pass ToA offset to CSV writer

**3. Carrier Page Date Selection Fixed:**
- **Problem:** Date picker showed "No data available" because it was looking for spectrograms in wrong location
- **Solution:** Modified `/api/v1/carrier/available-dates` endpoint to scan 10 Hz NPZ files in `analytics/{channel}/decimated/` directories
- **Files Changed:** `web-ui/monitoring-server-v3.js` (lines 1016-1108) - Rewrote available-dates endpoint
- **Files Changed:** `web-ui/carrier.html` (lines 314-322) - Updated date picker display

**4. Solar Zenith Overlays on Spectrograms:**
- **Purpose:** Visualize solar illumination of WWV and WWVH propagation paths
- **Implementation:** Added secondary y-axis with WWV path (red) and WWVH path (purple) solar elevation curves
- **Files Changed:** `scripts/generate_spectrograms_from_10hz.py` (lines 147-161, 232-263, 289-310, 381-388)
- **Usage:** `python3 scripts/generate_spectrograms_from_10hz.py --date YYYYMMDD --data-root /tmp/grape-test`
- **Output:** `/tmp/grape-test/spectrograms/YYYYMMDD/{channel}_YYYYMMDD_decimated_spectrogram.png`

---

### Previous Session (Nov 26 - Timing Fixes):

**Wall Clock Stability Fix:**
- **Problem:** `ntp_wall_clock_time` in NPZ archives was unstable (±2 seconds) due to capturing `time.time()` at packet arrival
- **Solution:** Predict wall clock at minute boundary using `rtp_derived_utc + ntp_offset` 
- **Result:** Sub-microsecond stability - wall clock now phase-aligned with RTP-derived UTC
- **Files Changed:** `core_npz_writer.py` (lines 128-173, 198-217, 226-242)

**Timing Dashboard Implementation:**
- **Drift Analysis Chart:** Time series of drift_ms per channel with reference bands (±1ms excellent, ±5ms good)
- **Time Source Timeline:** Gantt-style chart showing quality states (TONE_LOCKED/NTP_SYNCED/INTERPOLATED/WALL_CLOCK)
- **Files Changed:** `web-ui/timing-dashboard-enhanced.html` (lines 806-862, 874-1098)

---

### Pending Work: WWV/WWVH Discrimination Testing & Display

**Objective:** Test all 6 discrimination methods and make them display informatively on the discrimination page.

**Key Documentation:**
- `WWV_WWVH_DISCRIMINATION_METHODS.md` - Detailed method descriptions (READ FIRST)
- `docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md` - User-facing guide

**The 6 Discrimination Methods:**

1. **440 Hz Station ID** (2/hour at minutes 1 & 2)
   - Ground truth calibration - WWVH minute 1, WWV minute 2
   - File: `station_id_440hz/` CSVs

2. **Test Signal** (2/hour at minutes 8 & 44)
   - Ground truth calibration - WWV minute 8, WWVH minute 44
   - File: `test_signal/` CSVs

3. **BCD Correlation** (15/min) - PRIMARY METHOD
   - Cross-correlation of 100 Hz BCD time code finds two peaks = two stations
   - Measures amplitude AND differential delay simultaneously
   - File: `bcd_discrimination/` CSVs
   - **Key insight:** 100 Hz BCD signal IS the carrier - both stations modulate it

4. **Timing Tones** (1/min)
   - Power ratio of 1000 Hz (WWV) vs 1200 Hz (WWVH) marker tones
   - File: `tone_detections/` CSVs

5. **Tick Windows** (6/min)
   - Per-second tick analysis with adaptive coherent/incoherent integration
   - File: `tick_windows/` CSVs

6. **Weighted Voting** (1/min)
   - Combines all methods with minute-specific weighting
   - File: `discrimination/` CSVs (final determination)

**Testing Steps:**

1. **Verify data is being generated:**
   ```bash
   ls -la /tmp/grape-test/analytics/WWV_10_MHz/bcd_discrimination/
   ls -la /tmp/grape-test/analytics/WWV_10_MHz/station_id_440hz/
   ls -la /tmp/grape-test/analytics/WWV_10_MHz/tick_windows/
   ```

2. **Check discrimination page:**
   - Open `http://localhost:3000/discrimination.html`
   - Verify each method panel shows data
   - Check for proper labeling and statistics

3. **Validate BCD correlation output:**
   ```bash
   tail -20 /tmp/grape-test/analytics/WWV_10_MHz/bcd_discrimination/*_bcd_*.csv
   # Should show: bcd_wwv_amplitude, bcd_wwvh_amplitude, bcd_differential_delay_ms
   ```

**Web UI Files to Modify:**
- `web-ui/discrimination.html` - Main discrimination page
- `web-ui/monitoring-server-v3.js` - API endpoints for discrimination data

**Key API Endpoints:**
- `GET /api/v1/channels/:name/discrimination/:date/methods` - All methods for a channel
- `GET /api/v1/channels/:name/discrimination/:date/bcd` - BCD correlation data
- `GET /api/v1/channels/:name/discrimination/:date/station_id` - 440 Hz ID data

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

**SESSION_2025-11-26 (Part 3 - Evening)**: Geographic BCD & Spectrogram Solar Overlays ⭐⭐⭐
- ✅ **Geographic Peak Assignment:** BCD dual-peak now uses `classify_dual_peaks()` for correct WWV/WWVH assignment
- ✅ **Test Signal ToA:** Added `toa_offset_ms` measurement for channel characterization
- ✅ **Carrier Page Fixed:** Date picker now scans NPZ files in `decimated/` directories
- ✅ **Solar Zenith Overlays:** Spectrograms include WWV (red) and WWVH (purple) solar elevation curves
- 📁 Modified: `wwv_geographic_predictor.py`, `wwvh_discrimination.py`, `wwv_test_signal.py`, `discrimination_csv_writers.py`, `analytics_service.py`, `monitoring-server-v3.js`, `carrier.html`, `generate_spectrograms_from_10hz.py`
- 🧪 **NEXT:** Enable "Audio" button using reference implementation from `/home/wsprdaemon/SWL-ka9q/`

**SESSION_2025-11-26 (Part 2)**: Wall Clock Stability + Timing Dashboard ⭐⭐⭐
- ✅ **Wall Clock Fix:** `ntp_wall_clock_time` now uses stable RTP-derived prediction (was ±2s jitter)
- ✅ **Root Cause:** `time.time()` captured at packet arrival varies with network jitter and gap-filling
- ✅ **Solution:** Predict wall clock as `rtp_derived_utc + ntp_offset` at minute boundary
- ✅ **Result:** Sub-microsecond stability, phase-aligned with RTP-derived UTC
- ✅ **Timing Dashboard:** Interactive drift analysis and time source timeline charts
- ✅ **Quality Legend:** Explains TONE_LOCKED, NTP_SYNCED, INTERPOLATED, WALL_CLOCK
- 📁 Modified: `core_npz_writer.py` (wall clock prediction), `timing-dashboard-enhanced.html` (charts)

**SESSION_2025-11-26 (Part 1)**: Critical Thread Safety + Timing System ⭐⭐⭐
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

## 5. 🎯 Next Session: Enable Audio Button on Summary Page

**Objective:** Add real-time audio streaming capability to allow users to listen to WWV/CHU channels via the web UI.

### Reference Implementation

The `/home/wsprdaemon/SWL-ka9q/` project provides a working implementation:

```bash
# Key files to examine:
/home/wsprdaemon/SWL-ka9q/server.js        # 48KB - Express server with audio streaming
/home/wsprdaemon/SWL-ka9q/radiod_client.py # Python ka9q-radio multicast client
/home/wsprdaemon/SWL-ka9q/discover_multicast.py # Multicast discovery utilities
```

### Implementation Approach

1. **Study SWL-ka9q audio streaming:**
   - How does `server.js` handle audio streaming endpoints?
   - How does it interface with ka9q-radio multicast?
   - What audio format/encoding is used for web playback?

2. **Add audio endpoint to monitoring-server-v3.js:**
   - Create `/api/v1/channels/:name/audio` endpoint
   - Stream audio from ka9q-radio multicast source
   - Convert to web-compatible format (likely MP3 or WebM)

3. **Update Summary page UI:**
   - Add click handler to existing "Audio" button
   - Implement HTML5 audio player or Web Audio API
   - Show streaming status indicator

### Files to Modify

- `web-ui/monitoring-server-v3.js` - Add audio streaming endpoint
- `web-ui/summary.html` - Wire up Audio button
- Possibly add Python helper for ka9q-radio integration

### Success Criteria
- ✅ Audio button plays live channel audio in browser
- ✅ Audio quality sufficient for WWV/CHU identification
- ✅ Minimal latency (<5 seconds)
- ✅ Works with existing ka9q-radio multicast setup

---

## 5b. 🎯 Pending: WWV/WWVH Discrimination Testing & Web UI Display

**Objective:** Test all 6 discrimination methods and make them display informatively on the web UI discrimination page.

### Background: The 6 Methods

| Method | Rate | Strengths | Output Directory |
|--------|------|-----------|------------------|
| 440 Hz Station ID | 2/hour | Ground truth (min 1=WWVH, 2=WWV) | station_id_440hz/ |
| Test Signal | 2/hour | Ground truth (min 8=WWV, 44=WWVH) | test_signal/ |
| BCD Correlation | ~50/min | Amplitude + delay, 10s windows | bcd_discrimination/ |
| Timing Tones | 1/min | Reliable baseline | tone_detections/ |
| Tick Windows | 6/min | Sub-minute dynamics | tick_windows/ |
| Weighted Voting | 1/min | Final determination | discrimination/ |

### Success Criteria
- ✅ All 6 method directories have CSV files
- ✅ BCD shows two distinct amplitudes (WWV and WWVH)
- ✅ 440 Hz ID detected at minutes 1 (WWVH) and 2 (WWV)
- ✅ Test signal detected at minutes 8 (WWV) and 44 (WWVH)
- ✅ Web UI displays all methods with proper charts

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
