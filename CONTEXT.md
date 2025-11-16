# ------------------------------
# AI PROJECT CONTEXT MANIFEST
# ------------------------------
# Instructions: Paste this entire file at the start of any new chat session
# to provide ground-truth context for the GRAPE Signal Recorder project.

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
* Activate venv before testing: `source venv/bin/activate`
* Test scripts available: `test-drf-writer.py`, `test-wwvh-discrimination.py`

### Scientific Principles:
* **Doppler shifts are DATA, not artifacts** - Frequency variations in 10 Hz carrier are ionospheric measurements (±0.1 Hz = ±3 km path resolution)
* **Sample completeness > SNR** - 100% of samples (even noisy) beats 95% of clean signal
* **Gap transparency** - Document all discontinuities, never hide data quality issues
* **Reprocessability** - Original 16 kHz archives preserved forever, analytics can rerun

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
  * Three-stage anti-aliased FIR filtering (scipy.signal.decimate)

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

## 4. ⚡ Current Task & Git Context

* **Current Branch:** `main`
* **Task Goal:** Improve WWV-H discrimination quality and integrate timing/gap analysis dashboard
* **Key Steps:**
  1. Review and refine WWV-H discrimination algorithm (especially 440 Hz station ID detection)
  2. Link `timing-dashboard.html` into main web UI navigation
  3. Test timing dashboard with live data
  4. Verify gap analysis display is accurate and useful
  5. Update discrimination display if needed based on data quality
  6. Document any changes to discrimination algorithm or quality metrics

**Context:**
- Decimation pipeline just implemented (10 Hz NPZ files now being created)
- Time basis display fixed (TONE_LOCKED now shows correctly)
- Discrimination display working but may need quality improvements
- Timing dashboard exists (`timing-dashboard.html`) but not linked in main UI
- Quality metrics system (A-F grading) already implemented but not visible in main UI

---

## 📍 Quick Reference

### File Locations (Test Mode)

- **Raw archives (16 kHz):** `/tmp/grape-test/archives/{channel}/*_iq.npz`
- **Decimated (10 Hz):** `/tmp/grape-test/analytics/{channel}/decimated/*_iq_10hz.npz`
- **Digital RF:** `/tmp/grape-test/analytics/{channel}/digital_rf/`
- **Discrimination CSV:** `/tmp/grape-test/analytics/{channel}/discrimination/`
- **Quality CSV:** `/tmp/grape-test/analytics/{channel}/quality/`
- **Spectrograms:** `/tmp/grape-test/spectrograms/{YYYYMMDD}/`
- **State:** `/tmp/grape-test/state/analytics-{channel}.json` (time_snap stored here)
- **Config:** `config/grape-config.toml`

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

### Discrimination Methods (Shared WWV/WWVH Frequencies)

1. **Power Ratio:** 1000 Hz (WWV) vs 1200 Hz (WWVH) signal strength
2. **Differential Delay:** Time difference in arrival (ionospheric path)
3. **440 Hz Station ID:** Minute 1 = WWVH only, Minute 2 = WWV only

### Essential Documentation

- **`ARCHITECTURE_OVERVIEW.md`** - Complete system architecture (START HERE)
- **`docs/API_QUICK_REFERENCE.md`** - API contracts and data flow
- **`docs/API_REFERENCE.md`** - Complete function signatures
- **`WWVH_DISCRIMINATION_QUICKREF.md`** - WWV-H discrimination details
- **`web-ui/TIMING-DASHBOARD-IMPLEMENTATION.md`** - Quality dashboard docs
- **`DECIMATION_PIPELINE_COMPLETE.md`** - Recent 10 Hz NPZ implementation

### Timing Quality Hierarchy

1. **TONE_LOCKED** (±1ms): time_snap from WWV/CHU within last 3 hours
2. **NTP_SYNCED** (±10ms): System clock NTP-synchronized (offset <100ms, stratum ≤4)
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
