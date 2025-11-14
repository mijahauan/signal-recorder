# ------------------------------
# AI PROJECT CONTEXT MANIFEST
# ------------------------------
# Instructions: Paste this entire file at the start of any new chat session
# to provide ground-truth context for the project.

## 1. 🎯 Core Mission & Objectives

**Project:** GRAPE Signal Recorder (HamSCI)  
**Mission:** Record high-precision WWV/CHU time-standard signals for ionospheric propagation research with sub-millisecond timing accuracy.  
**Core Goal:** Complete scientific record with full provenance - every gap, timing adjustment, and quality metric logged for reproducible research.

**Key Principles:**
- RTP timestamps are PRIMARY (UTC is derived, not the reverse)
- Continuous upload with quality annotations (never skip data during propagation fades)
- Dual-service architecture: rock-solid core recorder + flexible analytics
- Native Digital RF format (10 Hz IQ) for HamSCI PSWS repository

## 2. 📜 Guiding Principles (Non-Negotiable Rules)

### Tech Stack
- **Language:** Python 3.8+ (scipy for signal processing, digital_rf for HDF5)
- **Input:** RTP from ka9q-radio (Phil Karn's multichannel SDR)
- **Web:** Node.js/Express backend, vanilla HTML/CSS/JS frontend, JSON file DB
- **NO external tools:** Pure Python (no sox, pcmrecord, wsprd, jt9)

### Code Style
- **RTP is PRIMARY:** UTC is derived from `RTP + time_snap`. Never stretch time to fit wall clock.
- **Single calculation principle:** Calculate timing ONCE per archive, pass to all consumers (tone detection, Digital RF, metadata)
- **Explicit logging:** Every gap, adjustment, quality degradation must be logged with quantitative metrics
- **Sample integrity:** RTP gaps = dropped packets → fill with zeros. Never drop samples silently.

### Testing
- **Test data location:** `/tmp/grape-test/` (for testing), `/data/grape-prod/` (production)
- **Clean restart:** Delete state files + Digital RF output when debugging timing issues
- **Validation:** 960,000 samples/minute invariant at 16 kHz

### Critical Rules

**1. KA9Q Timing (SACRED)**
```
utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate
```
- time_snap: WWV/CHU 1000Hz tone rising edge at :00.000 of minute
- Each channel has independent RTP clock (cannot share time_snap)
- Reference: `/home/mjh/git/ka9q-radio/src/pcmrecord.c:607,652-679,843-899`

**2. WWV/WWVH/CHU Usage**
- **WWV (1000Hz, 0.8s)** + **CHU (1000Hz, 0.5s)**: Use for `time_snap` (timing reference)
- **WWVH (1200Hz, 0.8s)**: NEVER for timing (propagation study ONLY, 2500mi farther)
- WWV-WWVH differential delay = ionospheric path difference

**3. Timing Quality Hierarchy**
1. **GPS_LOCKED** (±1ms): time_snap < 5min old
2. **NTP_SYNCED** (±10ms): System NTP sync (offset <100ms, stratum ≤4)
3. **INTERPOLATED**: time_snap 5-60min old (degrades)
4. **WALL_CLOCK** (±sec): Fallback (mark for reprocessing)

### Git Process
- Commit messages: Problem/Solution/Changes/Testing format
- Document in `docs/` for major features
- Update CONTEXT.md Section 4 at session start

## 3. 🗺️ Key Components (The API Map)

### Architecture Overview
```
ka9q-radio RTP (16 kHz IQ) → Core Recorder → Analytics Service
                               ├─ NPZ archives (1/minute)
                               └─ Status files

Analytics Service reads NPZ → Fork to:
  ├─ Tone detection (WWV/CHU/WWVH)
  ├─ Digital RF writer (10 Hz IQ)
  ├─ Quality metrics
  └─ Gap/discontinuity logs
```

### Core Recorder
**File:** `src/signal_recorder/core_recorder.py` (~300 lines)
**Purpose:** Rock-solid RTP→NPZ pipeline. Changes <5/year.

**Key Functions:**
```python
start_recording(channel_config) -> None
    # Main loop: receive RTP, resequence, fill gaps, write NPZ

_handle_packet(rtp_packet) -> None
    # Resequencing buffer, gap detection

_write_minute_file(samples, metadata) -> Path
    # Write NPZ with: IQ, RTP timestamps, gap stats
```

**Data Flow:**
- Input: RTP packets from ka9q-radio multicast
- Output: NPZ archives in `{data_root}/archives/{channel}/YYYYMMDD/`
- Metadata: RTP timestamps, gaps, packet stats (NOT quality-analyzed)

### Analytics Service
**File:** `src/signal_recorder/analytics_service.py` (~1280 lines)
**Purpose:** Process NPZ archives, generate products, can restart independently.

**Key Functions:**
```python
process_archive(archive: NPZArchive) -> Dict
    # Main orchestrator: quality → timing → tones → Digital RF

_get_timing_annotation(archive) -> TimingAnnotation
    # CRITICAL: Calculate timing ONCE (GPS_LOCKED/NTP/INTERPOLATED/WALL_CLOCK)
    # Returns UTC timestamp from best available source

_detect_tones(archive, timing) -> List[ToneDetectionResult]
    # WWV/CHU/WWVH detection, uses timing product for buffer calculation

_decimate_and_write_drf(archive, quality, timing) -> int
    # 16k→10Hz decimation, writes Digital RF with timing metadata

_update_time_snap(detections) -> bool
    # Updates time_snap from WWV/CHU (NOT WWVH) detections
```

**Data Flow:**
- Input: NPZ archives from core recorder
- Output: Digital RF (10 Hz HDF5), quality logs, discontinuity logs
- State: Persistent JSON (`time_snap`, last processed file)

### Data Models
**File:** `src/signal_recorder/interfaces/data_models.py`

**Primary Structures:**
```python
TimeSnapReference(rtp_timestamp, utc_timestamp, sample_rate, station, confidence)
    # KA9Q anchor point for RTP→UTC conversion
    # Method: calculate_sample_time(rtp_timestamp) -> float

TimingAnnotation(quality, utc_timestamp, time_snap_age_seconds, ntp_offset_ms)
    # Single timing product passed to all consumers

ToneDetectionResult(station, frequency_hz, timestamp_utc, confidence, use_for_time_snap)
    # use_for_time_snap: True for WWV/CHU, False for WWVH

NPZArchive(samples, rtp_timestamps, metadata)
    # Method: calculate_utc_timestamp(time_snap) -> float
```

### Digital RF Writer
**File:** `src/signal_recorder/digital_rf_writer.py`

**Key Functions:**
```python
add_samples(timestamp, samples, timing_annotation) -> None
    # Decimates 16k→10Hz, writes to Digital RF
    # Embeds timing quality in metadata channel

_decimate_samples(samples) -> np.ndarray
    # scipy.signal.decimate with anti-aliasing filter
```

### Tone Detector
**File:** `src/signal_recorder/tone_detector.py`

**Key Functions:**
```python
detect_tones_in_buffer(audio_buffer, current_unix_time, minute_boundary) -> List[ToneDetectionResult]
    # Phase-invariant quadrature matched filtering
    # Cross-file buffering to span minute boundaries

_correlate_with_template(audio, template, station_type, minute_boundary, current_unix_time) -> Optional[ToneDetectionResult]
    # Returns result with use_for_time_snap flag set correctly
```

### Web UI Monitoring
**Files:** `web-ui/monitoring-server.js`, `web-ui/channels.html`

**API Endpoints:**
```javascript
GET /api/status -> Combined status from core + analytics
GET /api/channels -> Per-channel details
GET /api/quality/:channel -> Quality metrics for channel
GET /api/spectrograms -> Available spectrogram files
```

**Status Files (JSON):**
- Core: `{data_root}/status/core-recorder-status.json` (RTP stats, channels active)
- Analytics: `{data_root}/analytics/{channel}/status/analytics-service-status.json` (tone detections, time_snap, DRF writes)

### Configuration
**File:** `config/grape-config.toml` (TOML format)

**Key Sections:**
```toml
[recorder]
data_root = "/tmp/grape-test"  # or "/data/grape-prod"
sample_rate = 16000
samples_per_minute = 960000

[channels.WWV_5_MHz]
frequency = 5000000.0
multicast_address = "239.20.1.1:5005"
```

## 4. ⚡ Current Task & Git Context

**Current Branch:** `main`  
**Last Commit:** fd82a38 - Phase 2E: Timing Quality Framework  
**Status:** ✅ Operational, overnight validation run in progress

**Recent Accomplishments:**
- ✅ Dual-service architecture (core recorder + analytics)
- ✅ WWV/CHU tone detection with time_snap establishment
- ✅ Timing quality framework (4-tier hierarchy)
- ✅ Digital RF integration with quality metadata
- ✅ Web UI for real-time monitoring
- ✅ WWV/H discrimination for propagation analysis

**Next Session Goals:**
1. **Review overnight run results** (timing quality distribution, stability, any crashes)
2. **Web UI enhancements:**
   - Display timing quality per channel (GPS_LOCKED/NTP_SYNCED/etc.)
   - Visualize time_snap establishment and age
   - Gap analysis dashboard (packet loss, timing degradation visualization)
   - Timing quality distribution chart (pie/bar chart)
3. **Address any issues** discovered in overnight logs

**Known Issues:**
- None currently blocking (pending overnight validation)

**Development Focus:**
- Web UI gap analysis and timing visualization
- Long-term stability monitoring
- Potential future: automated reprocessing for low-quality segments

---

## 📚 Quick Reference

**Documentation:**
- `docs/TIMING_QUALITY_FRAMEWORK.md` - Timing architecture (comprehensive)
- `DIGITAL_RF_UPLOAD_TIMING.md` - Quick reference
- `docs/SESSION_NOV13_TIMING_QUALITY.md` - Latest session summary

**Monitoring:**
- Web UI: http://localhost:3000 (when monitoring-server running)
- Logs: `{data_root}/logs/analytics-{channel}.log`
- Status: `{data_root}/status/*.json`

**Common Commands:**
```bash
# Start services
./start-dual-service.sh

# Check status
ps aux | grep -E "(core_recorder|analytics_service)"

# View logs
tail -f /tmp/grape-test/logs/analytics-wwv10.log

# Clean restart (debugging timing)
pkill -f analytics_service
rm -rf /tmp/grape-test/analytics/*/digital_rf/*
rm -rf /tmp/grape-test/state/analytics-*.json
```

**Test Data Locations:**
- Archives: `/tmp/grape-test/archives/{channel}/YYYYMMDD/*.npz`
- Digital RF: `/tmp/grape-test/analytics/{channel}/digital_rf/YYYYMMDD/*.h5`
- State: `/tmp/grape-test/state/*.json`
- Logs: `/tmp/grape-test/logs/*.log`
