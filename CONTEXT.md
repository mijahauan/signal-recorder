# ------------------------------
# AI PROJECT CONTEXT MANIFEST
# ------------------------------
# Instructions: Paste this entire file at the start of any new chat session
# to provide ground-truth context for the GRAPE Signal Recorder project.

## 0. 📜 CRITICAL: Canonical Contracts (NEW - 2025-11-20)

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

* **`src/signal_recorder/grape_channel_recorder_v2.py`**:
  * Core RTP recorder (rock-solid, changes <5x/year)
  * `GrapeChannelRecorder.__init__(config)`: Initialize recorder for single channel
  * `run()`: Main recording loop (RTP → resequence → gap fill → NPZ archive)
  * Output: `{timestamp}_iq.npz` (16 kHz IQ + RTP timestamps)

* **`src/signal_recorder/analytics_service.py`**:
  * `AnalyticsService.__init__(archive_dir, output_dir, channel_name, ...)`: Per-channel analytics
  * `process_archive(archive: NPZArchive)`: Full pipeline - tone detection, quality, decimation
  * `_write_decimated_npz()`: Creates 10 Hz NPZ with embedded metadata
  * Output: `{timestamp}_iq_10hz.npz` (10 Hz IQ + timing/quality/tone metadata)

* **`src/signal_recorder/drf_writer_service.py`**:
  * `DRFWriterService.__init__(...)`: Standalone Digital RF converter
  * Reads: 10 Hz NPZ files from `analytics/{channel}/decimated/`
  * Writes: Digital RF HDF5 to `analytics/{channel}/digital_rf/`

### Signal Processing Modules

* **`src/signal_recorder/tone_detector.py`**:
  * `MultiStationToneDetector.process_samples(timestamp, samples_3khz, rtp_ts)`: Detect WWV/WWVH/CHU tones
  * Returns: `List[ToneDetectionResult]` with station, SNR, timing_error, confidence
  * **CRITICAL:** Requires 3 kHz resampling of input

* **`src/signal_recorder/wwvh_discrimination.py`**:
  * `WWVHDiscriminator.analyze_minute_with_440hz(iq_16khz, sr, ts, detections)`: Full WWV-H analysis
  * Returns: `DiscriminationResult` with power ratio, differential delay, 440 Hz station ID
  * Station types: WWV (2.5/5/10/15/20/25 MHz), WWVH (2.5/5/10/15 MHz only)

* **`src/signal_recorder/decimation.py`**:
  * `decimate_for_upload(iq, input_rate, output_rate)`: 16 kHz → 10 Hz decimation
  * Optimized 3-stage pipeline: CIC (16kHz→400Hz) → compensation FIR (flatten passband) → final FIR (400Hz→ 10Hz)
  * Preserves ±0.1 Hz Doppler resolution with flat passband and >90 dB stopband attenuation

### Web UI Backend (Node.js)

* **`web-ui/monitoring-server-v3.js`**:
  * `GET /api/v1/summary`: System-wide status (all channels)
  * `GET /api/v1/channels/status`: Channel statuses with time_basis
  * `GET /api/v1/channels/:channelName/discrimination/:date`: Discrimination CSV data
  * `GET /api/monitoring/timing-quality`: Quality metrics and grading (timing dashboard)

### Web UI Pages

* **`web-ui/summary.html`**: System overview (all channels, detection counts, upload progress)
* **`web-ui/carrier.html`**: Spectrograms showing ionospheric Doppler (±5 Hz)
* **`web-ui/channels.html`**: Per-channel details (gaps, WWV timing, quality)
* **`web-ui/discrimination.html`**: WWV-H analysis (4 panels: SNR, power ratio, delay, 440 Hz)
* **`web-ui/timing-dashboard.html`**: Quality grading, time_snap monitoring, gap analysis (NEEDS INTEGRATION)

### Data Models (interfaces/data_models.py)

* `NPZArchive`: Parsed 16 kHz NPZ file with RTP timestamps
* `ToneDetectionResult`: Tone detection output (station, frequency, SNR, timing_error)
* `TimeSnapReference`: UTC anchor from WWV/CHU tone (utc_timestamp, rtp_timestamp, confidence)
* `QualityInfo`: Completeness, packet loss, gaps (for quality grading)
* `DiscriminationResult`: WWV-H analysis output (power_ratio, differential_delay, 440hz data)

## 4. ⚡ Recent Sessions Summary

**SESSION_2025-11-20_CANONICAL_CONTRACTS.md**: Established foundational contracts ⭐ CRITICAL
- ✅ Created CANONICAL_CONTRACTS.md - Project standards overview
- ✅ Created DIRECTORY_STRUCTURE.md - Complete path specifications and naming conventions
- ✅ Unified docs/API_REFERENCE.md - Single API source of truth (Path Management, Tone Detection, Discrimination, CSV Writers, Data Models)
- ✅ Enhanced GRAPEPaths API with 4 new methods for separated discrimination directories
- ✅ Fixed all 14 path violations to use GRAPEPaths API
- ✅ Created validate_api_compliance.py - Automated enforcement tool
- ✅ Consolidated ARCHITECTURE.md - Single definitive architecture document
- ✅ **KEY RULES**: ALL paths via GRAPEPaths, ALL functions in API_REFERENCE.md, NO time-range suffixes on daily files

**5 Independent Discrimination Methods** (Nov 2025):
- ✅ Method 1: Timing Tones (1000/1200 Hz) → tone_detections/{CHANNEL}_tones_YYYYMMDD.csv
- ✅ Method 2: Tick Windows (5ms ticks) → tick_windows/{CHANNEL}_ticks_YYYYMMDD.csv
- ✅ Method 3: Station ID (440 Hz) → station_id_440hz/{CHANNEL}_440hz_YYYYMMDD.csv
- ✅ Method 4: BCD (100 Hz subcarrier) → bcd_discrimination/{CHANNEL}_bcd_YYYYMMDD.csv
- ✅ Method 5: Weighted Voting (final) → discrimination/{CHANNEL}_discrimination_YYYYMMDD.csv
- ✅ Each method independently reprocessable with dedicated CSV output
- ✅ Separated outputs enable clear provenance and isolated testing

**SESSION_2025-11-18_CARRIER_REMOVAL.md**: Wide channel optimization
- ✅ Removed 9 carrier channels (200 Hz) - cannot correlate using time_snap
- ✅ Implemented optimized 3-stage decimation: CIC → compensation FIR → final FIR
- ✅ Preserves Doppler precision with flat passband (0-5 Hz within 0.1 dB)
- ✅ All channels now 16 kHz wide channels with WWV/CHU tone detection

**SESSION_2025-11-17_TONE_DETECTOR_FIX.md**: Timing bug fix
- ✅ Fixed 30-second timing offset bug in tone detector (onset_time calculation)
- ✅ RTP offset correlation proven UNSTABLE (std dev 1.2B samples - independent clocks per channel)

---

## 📍 Quick Reference

### File Locations (Test Mode) - Use GRAPEPaths API!

**Archives (16 kHz):**
- Path: `/tmp/grape-test/archives/{channel}/*_iq.npz`
- API: `paths.get_archive_dir(channel_name)`

**Analytics (10 Hz + CSVs):**
- Decimated: `/tmp/grape-test/analytics/{channel}/decimated/*_iq_10hz.npz`
  - API: `paths.get_decimated_dir(channel_name)`
- Tone Detections: `/tmp/grape-test/analytics/{channel}/tone_detections/{CHANNEL}_tones_YYYYMMDD.csv`
  - API: `paths.get_tone_detections_dir(channel_name)`
- Tick Windows: `/tmp/grape-test/analytics/{channel}/tick_windows/{CHANNEL}_ticks_YYYYMMDD.csv`
  - API: `paths.get_tick_windows_dir(channel_name)`
- Station ID (440 Hz): `/tmp/grape-test/analytics/{channel}/station_id_440hz/{CHANNEL}_440hz_YYYYMMDD.csv`
  - API: `paths.get_station_id_440hz_dir(channel_name)`
- BCD Discrimination: `/tmp/grape-test/analytics/{channel}/bcd_discrimination/{CHANNEL}_bcd_YYYYMMDD.csv`
  - API: `paths.get_bcd_discrimination_dir(channel_name)`
- Final Discrimination: `/tmp/grape-test/analytics/{channel}/discrimination/{CHANNEL}_discrimination_YYYYMMDD.csv`
  - API: `paths.get_discrimination_dir(channel_name)`
- Quality: `/tmp/grape-test/analytics/{channel}/quality/{CHANNEL}_quality_YYYYMMDD.csv`
  - API: `paths.get_quality_dir(channel_name)`
- Digital RF: `/tmp/grape-test/analytics/{channel}/digital_rf/`
  - API: `paths.get_digital_rf_dir(channel_name)`

**Other:**
- **Spectrograms:** `/tmp/grape-test/spectrograms/{YYYYMMDD}/`
- **State:** `/tmp/grape-test/state/analytics-{channel}.json` (time_snap stored here)
- **Config:** `config/grape-config.toml`

**CRITICAL:** Never construct paths directly - always use GRAPEPaths API methods!

### Station Frequencies

**WWV (Fort Collins, CO):**
- 2.5, 5, 10, 15, 20, 25 MHz
- 1000 Hz tone (0.8s duration)
- Minute marker at :00.000 UTC

**WWVH (Kauai, HI):**
- 2.5, 5, 10, 15 MHz ONLY (frequency-aware!)
- 1200 Hz tone (0.8s duration)
- Minute marker at :00.000 UTC
- 440 Hz station ID: Minute 1 (beginning)

**CHU (Ottawa, Canada):**
- 3.33, 7.85, 14.67 MHz
- 1000 Hz tone (0.5s duration)
- Different timing pattern than WWV

### 5 Independent Discrimination Methods (Nov 2025)

**Method 1: Timing Tones (1000/1200 Hz)**
- WWV: 1000 Hz (0.8s), WWVH: 1200 Hz (0.8s)
- Power ratio, differential delay (ms)
- CSV: `tone_detections/{CHANNEL}_tones_YYYYMMDD.csv`
- API: `WWVHDiscriminator.detect_timing_tones(iq, sr, ts)` → `(wwv_pwr, wwvh_pwr, delay, detections)`

**Method 2: Tick Windows (5ms Tick Analysis)**
- Coherent/incoherent integration of 5ms tick marks
- 6 windows per minute (every 10 seconds)
- CSV: `tick_windows/{CHANNEL}_ticks_YYYYMMDD.csv`
- API: `WWVHDiscriminator.detect_tick_windows(iq, sr)` → `List[Dict]`

**Method 3: Station ID (440 Hz Tones)**
- Minute 1: WWVH only (voice ID)
- Minute 2: WWV only (voice ID)
- CSV: `station_id_440hz/{CHANNEL}_440hz_YYYYMMDD.csv`
- API: `WWVHDiscriminator.detect_440hz_tone(iq, sr, minute_num)` → `(detected, power_db)`

**Method 4: BCD Discrimination (100 Hz Subcarrier)**
- Sliding window analysis of 100 Hz BCD time code
- WWV/WWVH amplitude, differential delay, correlation quality
- CSV: `bcd_discrimination/{CHANNEL}_bcd_YYYYMMDD.csv`
- API: `WWVHDiscriminator.detect_bcd_discrimination(iq, sr, ts)` → `(wwv_amp, wwvh_amp, delay, quality, windows)`

**Method 5: Weighted Voting (Final Determination)**
- Combines all 4 methods with confidence levels
- Dominant station: WWV/WWVH/BALANCED/UNKNOWN
- CSV: `discrimination/{CHANNEL}_discrimination_YYYYMMDD.csv`
- API: `WWVHDiscriminator.analyze_minute_with_440hz(iq, sr, ts, detections)` → `DiscriminationResult`

### Essential Documentation (Nov 2025 Canonical Contracts)

**⭐ THE FOUR PILLARS (Consult Before All Code Changes):**
- **`CANONICAL_CONTRACTS.md`** - Project standards overview (START HERE)
- **`DIRECTORY_STRUCTURE.md`** - WHERE data goes, HOW to name files
- **`docs/API_REFERENCE.md`** - WHAT functions exist, HOW to call them
- **`ARCHITECTURE.md`** - WHY the system is designed this way

**Enforcement & Validation:**
- **`scripts/validate_api_compliance.py`** - Automated path/API compliance checker (must pass)

**Implementation Details:**
- **`SESSION_2025-11-20_CANONICAL_CONTRACTS.md`** - Complete session summary
- **`WWV_WWVH_DISCRIMINATION_METHODS.md`** - 5 discrimination methods explained
- **`BCD_DISCRIMINATION_IMPLEMENTATION.md`** - BCD analysis details
- **`COHERENT_TICK_REPROCESSING_STATUS.md`** - Tick analysis implementation

### Timing Quality Hierarchy

1. **TONE_LOCKED** (±1ms): time_snap from WWV/CHU tone detection
   - All 16 kHz channels use this method (tone detection available)
   - Anchors RTP timestamp to UTC via tone rising edge at :00.000
   
2. **NTP_SYNCED** (±10ms): System clock NTP-synchronized (offset <100ms, stratum ≤4)
   - Fallback when tone detection unavailable (propagation fades)
   
3. **WALL_CLOCK** (±seconds): Unsynchronized fallback (recommend reprocessing)

### Quality Grading System

- **A (95-100)**: Excellent - Sample integrity perfect, time_snap verified
- **B (85-94)**: Good - Minor packet loss, timing valid
- **C (70-84)**: Acceptable - Some gaps, usable for analysis
- **D (50-69)**: Poor - Significant issues, verify before use
- **F (<50)**: Failed - Not suitable for scientific analysis

**Weighting:**
- Sample Count Integrity: 40% (MOST CRITICAL)
- RTP Continuity: 30%
- Time_snap Quality: 20%
- Network Stability: 10%
