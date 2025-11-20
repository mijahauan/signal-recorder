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

**Key Docs:**
- `docs/DRF_WRITER_MODES.md` - Wsprdaemon vs enhanced metadata
- `SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md` - DRF writer completion
- `scripts/validate_api_compliance.py` - Enforcement tool

### Timing & Quality

**Timing Quality:** TONE_LOCKED (±1ms) > NTP_SYNCED (±10ms) > WALL_CLOCK (±seconds)  
**Quality Grades:** A (95-100) excellent | B (85-94) good | C (70-84) acceptable | D (50-69) poor | F (<50) failed  
**Weighting:** Sample integrity 40% | RTP continuity 30% | Time_snap 20% | Network 10%
