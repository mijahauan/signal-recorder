# GRAPE Signal Recorder - AI Context Manifest

**Purpose:** This file provides AI assistants with the essential context needed to work on this project without drift. Paste this at the start of each new session.

---

## 1. 🎯 Core Mission & Objectives

**Project:** GRAPE Signal Recorder  
**Organization:** HamSCI (Ham Radio Science Citizen Investigation)  
**Mission:** Record and archive high-precision WWV/CHU time-standard signals for ionospheric propagation research.

**Core Goals:**
- **Precision Timing:** Sub-millisecond timing accuracy using RTP timestamps as primary reference
- **Data Quality:** Continuous monitoring of completeness, packet loss, and timing drift with full provenance
- **Scientific Integrity:** Complete discontinuity tracking - every gap, sync adjustment, and timing irregularity logged
- **HamSCI Integration:** Native Digital RF format (10 Hz IQ) with HamSCI-compliant metadata for PSWS repository
- **Reliable Upload:** Resilient rsync-based upload to PSWS with retry logic
- **Simple Management:** Web-based configuration and monitoring for amateur radio operators

**What This Is NOT:**
- Not a WSPR decoder (that's wsprdaemon)
- Not a general-purpose SDR recorder
- Not audio-based (we preserve IQ samples at 10 Hz)

---

## 2. 📜 Guiding Principles (Director's Mandate)

### Tech Stack

**Core Processing:**
- Python 3.8+ with scipy for signal processing
- `digital_rf` library for HDF5 time-series output
- RTP reception from `ka9q-radio` (Phil Karn's multichannel SDR)
- No external tools (no sox, pcmrecord, wsprd, jt9)

**Data Pipeline:**
```
ka9q-radio RTP (16 kHz IQ) → Resequencing → time_snap → Gap Fill → Fork to:
  1. Archive (16k NPZ compressed)
  2. Upload (10 Hz Digital RF)
  3. Monitoring (3k tone detection)
```

**Web Interface:**
- Backend: Node.js/Express.js
- Frontend: Vanilla HTML/CSS/JS (no React/Vue)
- Database: JSON files (no PostgreSQL/MySQL)
- API: RESTful JSON endpoints

### Critical Architecture Rules

**1. KA9Q Timing Architecture (SACRED)**
> "RTP timestamps are PRIMARY time reference. UTC time is DERIVED from RTP + time_snap anchor."

- RTP timestamp gaps = dropped packets → fill with zeros
- NEVER "stretch" time to fit wall clock
- time_snap mechanism: Maps RTP timestamp to UTC using WWV/CHU tone rising edge
- Formula: `utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate`
- Reference: `/home/mjh/git/ka9q-radio/src/pcmrecord.c` lines 607, 652-679, 843-899

**2. WWV/WWVH/CHU Purpose Separation (CRITICAL)**

| Station | Frequency | Duration | Purpose | `use_for_time_snap` |
|---------|-----------|----------|---------|---------------------|
| WWV     | 1000 Hz   | 0.8s     | Timing reference | ✅ `True` |
| WWVH    | 1200 Hz   | 0.8s     | Propagation study ONLY | ❌ `False` |
| CHU     | 1000 Hz   | 0.5s     | Timing reference | ✅ `True` |

**NEVER use WWVH for time_snap corrections.** It's 2500 miles farther than WWV - using it would introduce systematic timing error. WWVH exists to study WWV-WWVH differential delays (ionospheric path differences).

**3. Signal Processing Rules**

- **Anti-aliasing BEFORE decimation:** Use `scipy.signal.decimate()` with proper FIR filtering
- **NO external tools:** Pure Python pipeline (no sox/pcmrecord/wav2grape chain)
- **Sample rate:** Input 16 kHz IQ → Output 10 Hz IQ (factor of 1600)
- **Why 10 Hz?** Sufficient for <100ms timing precision, reduces data 1600x, matches HamSCI expectations

**4. Data Quality & Provenance (Updated Nov 2024)**

- **Every discontinuity MUST be logged:** Gap, sync adjustment, RTP reset, buffer overflow, source unavailable, recorder offline
- **Quantitative gap reporting ONLY:** No subjective quality grades - report raw ms by category:
  - Network gaps (packet loss, overflow, underflow)
  - Source failures (radiod down/channel missing)
  - Recorder offline (daemon stopped)
- **Embedded metadata:** Quality info in archive files AND Digital RF metadata
- **No silent corrections:** All timing adjustments logged with explanation
- **Health monitoring:** Automatic detection and recovery from radiod restarts

**5. Configuration & Testing**

- **Test vs Production Mode:**
  - Test: Data in `/tmp/grape-test` (temporary, safe for development)
  - Production: Data in `/var/lib/signal-recorder` (persistent)
- **Always test in test mode first** before switching to production
- **TOML configuration:** `config/grape-config.toml` is the source of truth

### Code Style

- **Type hints required** for all function signatures
- **Docstrings required** for all public functions (Google style)
- **Immutable data models:** Use `@dataclass(frozen=True)` for data structures
- **ABC for interfaces:** All API interfaces inherit from `ABC` with `@abstractmethod`
- **No magic numbers:** Use named constants

### Git & Development

- **Branch naming:** `feat/feature-name`, `fix/bug-name`, `docs/doc-name`
- **Commit messages:** Descriptive, explain WHY not just WHAT
- **Never delete tests** without explicit approval
- **Archive over delete:** Move deprecated code to `archive/legacy-code/` with README

### AI Persona

You are a **senior Python/RF engineer** with expertise in:
- Digital signal processing (scipy, numpy)
- RTP/UDP multicast networking
- Scientific data integrity and provenance
- Amateur radio and ionospheric propagation

**Your communication style:**
- **Terse and direct** - No fluff, state facts
- **Cite code locations** - Reference specific files/lines
- **Minimal edits** - Only change what's necessary
- **Test first** - Verify before implementing

**When writing code:**
- Provide **complete, runnable code** - No placeholders or "..." ellipsis
- Include **all imports** at the top of the file
- Follow **existing patterns** in the codebase
- Add **type hints and docstrings**
- **Preserve indentation** exactly as shown

---

## 3. 🗺️ Key Components (The API Map)

### Core Architecture: 6 Functions

```
Function 1 (Producer) → Functions 2-6 (Independent Consumers)
     ↓
SampleBatch (timestamp, samples, quality, time_snap)
     ├─→ Function 2: Archive (16k NPZ)
     ├─→ Function 3: Tone Detection (WWV/WWVH/CHU)
     ├─→ Function 4+5: Decimation + Digital RF (10 Hz)
     └─→ Function 6: Upload (rsync to PSWS)
```

### Data Models (Shared Structures)

**Location:** `src/signal_recorder/interfaces/data_models.py`

**Primary Container:**
```python
SampleBatch(
    timestamp: float,           # UTC (time_snap corrected)
    samples: np.ndarray,        # Complex IQ
    sample_rate: int,           # 16000
    quality: QualityInfo,       # Quality metadata
    time_snap: TimeSnapReference,  # Time anchor
    channel_name: str,          # "WWV 5.0 MHz"
    frequency_hz: float,        # 5000000.0
    ssrc: int                   # RTP identifier
)
```

**Quality Metadata:**
```python
QualityInfo(
    completeness_pct: float,    # 0-100
    gap_count: int,
    gap_duration_ms: float,
    packet_loss_pct: float,
    resequenced_count: int,
    time_snap_established: bool,
    time_snap_confidence: float,  # 0.0-1.0
    discontinuities: List[Discontinuity],
    quality_grade: str,         # A/B/C/D/F
    quality_score: float        # 0-100
)
```

**Time Anchor (KA9Q Architecture):**
```python
TimeSnapReference(
    rtp_timestamp: int,         # RTP at anchor
    utc_timestamp: float,       # UTC at anchor
    sample_rate: int,           # 16000
    source: str,                # 'wwv_verified', 'chu_verified', etc.
    confidence: float,          # 0.0-1.0
    station: str,               # 'WWV', 'CHU', 'initial'
    established_at: float       # Wall clock creation time
)
# Method: calculate_sample_time(rtp_timestamp) -> float
```

**Discontinuity Record (Updated Nov 2024):**
```python
Discontinuity(
    timestamp: float,
    sample_index: int,
    discontinuity_type: DiscontinuityType,  # GAP, RTP_RESET, SYNC_ADJUST, 
                                             # SOURCE_UNAVAILABLE, RECORDER_OFFLINE,
                                             # OVERFLOW, UNDERFLOW
    magnitude_samples: int,     # +gap, -overlap
    magnitude_ms: float,
    rtp_sequence_before: Optional[int],
    rtp_sequence_after: Optional[int],
    rtp_timestamp_before: Optional[int],
    rtp_timestamp_after: Optional[int],
    wwv_related: bool,
    explanation: str            # Human-readable cause
)
```

**Quality Info (Quantitative Only):**
```python
QualityInfo(
    total_samples: int,
    discontinuity_count: int,
    network_gap_ms: float,       # Packet loss, overflow, underflow
    source_failure_ms: float,    # Radiod down/channel missing  
    recorder_offline_ms: float,  # Daemon stopped
    rtp_drift_ppm: float,
    completeness_pct: float
)
# Method: get_gap_breakdown() -> Dict[str, float]
```

**Tone Detection:**
```python
ToneDetectionResult(
    station: StationType,       # WWV, WWVH, CHU
    frequency_hz: float,        # 1000 or 1200
    duration_sec: float,        # Measured duration
    timestamp_utc: float,       # Rising edge time
    timing_error_ms: float,     # Error vs :00.000
    snr_db: float,
    confidence: float,          # 0.0-1.0
    use_for_time_snap: bool,    # ⚠️ CRITICAL: True for WWV/CHU, False for WWVH
    correlation_peak: float,
    noise_floor: float
)
```

### API Interfaces

**Location:** `src/signal_recorder/interfaces/`

#### Function 1: Quality-Analyzed Sample Provider

**Interface:** `QualityAnalyzedSampleProvider` (`sample_provider.py`)

```python
get_sample_batch() -> Optional[SampleBatch]
    # Returns next quality-analyzed batch (blocking)
    
get_time_snap_reference() -> Optional[TimeSnapReference]
    # Returns current time anchor
    
get_discontinuities(since_timestamp: float) -> List[Discontinuity]
    # Returns gaps/jumps since timestamp
    
get_quality_summary() -> QualityInfo
    # Returns aggregate quality metrics
```

**Current Implementation:** `GRAPEChannelRecorderV2` in `grape_channel_recorder_v2.py`  
**Status:** ✅ Exists, needs adapter wrapper

#### Function 2: Archive Writer

**Interface:** `ArchiveWriter` (`archive.py`)

```python
write_samples(
    timestamp: float,
    samples: np.ndarray,
    quality: QualityInfo,
    time_snap: Optional[TimeSnapReference]
) -> Optional[Path]
    # Writes 16 kHz IQ to compressed NPZ
    # Returns path to created file
```

**Current Implementation:** `MinuteFileWriter` in `minute_file_writer.py`  
**Status:** ✅ Exists, needs adapter wrapper

#### Function 3: Tone Detector

**Interface:** `MultiStationToneDetector` (`tone_detection.py`)

```python
detect_tones(
    samples: np.ndarray,
    sample_rate: int,
    timestamp_utc: float
) -> List[ToneDetectionResult]
    # Phase-invariant quadrature matched filtering
    # Detects WWV (1000 Hz, 0.8s), WWVH (1200 Hz, 0.8s), CHU (1000 Hz, 0.5s)
    # Returns list with use_for_time_snap flag set correctly
```

**Current Implementation:** `MultiStationToneDetector` class in `grape_rtp_recorder.py` (lines 175-419)  
**Status:** ✅ Exists, embedded in recorder (needs extraction to standalone)

#### Functions 4+5: Decimator + Digital RF Writer (Combined)

**Interface:** `DecimatorWriter` (`decimation.py`)

```python
write_decimated(
    timestamp: float,
    samples: np.ndarray,
    quality: QualityInfo,
    time_snap: Optional[TimeSnapReference]
) -> Optional[Path]
    # 1. Decimate 16 kHz → 10 Hz (scipy.signal.decimate)
    # 2. Write to Digital RF HDF5
    # 3. Embed quality metadata
    # Returns path when file completed (every 60 seconds)
```

**Current Implementation:** `DigitalRFWriter` in `digital_rf_writer.py`  
**Status:** ✅ Exists, needs adapter wrapper

#### Function 6: Upload Queue

**Interface:** `UploadQueue` (`upload.py`)

```python
queue_file(
    local_path: Path,
    metadata: FileMetadata
) -> str
    # Queues Digital RF file for upload
    # Returns task_id
    
get_status(task_id: str) -> UploadTask
    # Returns upload status (PENDING, UPLOADING, COMPLETED, FAILED)
    
start() / stop()
    # Start/stop background upload worker
```

**Current Implementation:** `UploadManager` in `uploader.py`  
**Status:** ⚠️ EXISTS BUT NOT INTEGRATED - Files written but never uploaded

### Main Recorder Implementation

**Location:** `src/signal_recorder/grape_rtp_recorder.py` (~2200 lines)

**Key Classes:**

```python
GRAPERecorderManager:
    # Main daemon - manages multiple channel recorders
    # Methods: start(), stop(), get_status()
```

---

## 4. ⚡ Current Task & Git Context

**Current Branch:** `main`  
**Last Session:** November 12, 2024 (Morning)  
**Last Commit:** `c07f59a` - Fix tone detection and WWV/H discrimination for V2 dual-service architecture

**Current Architecture Status:**

### ✅ **V2 Dual-Service Architecture - OPERATIONAL**

**Phase 1: Core Recorder (RTP → NPZ Archives)**
- Implementation: `core_recorder.py`, `core_npz_writer.py`, `packet_resequencer.py`
- Status: ✅ Running successfully (9 channels: 6 WWV + 3 CHU)
- Output: `/tmp/grape-test/archives/{channel}/` (270+ NPZ files per channel)
- NPZ format: IQ samples + RTP timestamps + gap metadata
- Status file: `/tmp/grape-test/status/core-recorder-status.json` (updates every 10s)
- Documentation: `CORE_ANALYTICS_SPLIT_DESIGN.md`

**Phase 2: Analytics Service (NPZ → Derived Products)**
- ✅ **Phase 2A - Digital RF Integration** (Nov 9, 2024)
  - Tone detector: `src/signal_recorder/tone_detector.py` (558 lines)
  - Analytics service: `src/signal_recorder/analytics_service.py` (752 lines)
  - Digital RF writer: 16 kHz → 10 Hz decimation working
  - Quality metrics: Completeness, packet loss, gap tracking
  - Status: ✅ 9 services running (one per channel)
  - Output: `/tmp/grape-test/analytics/{channel}/`
  - Status files: Per-channel in `{channel}/status/analytics-service-status.json` (updates every 10s)
  - Documentation: `DIGITAL_RF_INTEGRATION_COMPLETE.md`

- ✅ **Phase 2B - PSWS Compatibility** (Nov 9, 2024)
  - PSWS directory structure: `YYYYMMDD/CALLSIGN_GRID/RECEIVER@STATION_ID_INSTRUMENT_ID/OBS{timestamp}/CHANNEL/`
  - Station metadata: psws_station_id, psws_instrument_id, receiver_name
  - Format verified: complex64 compatible with wsprdaemon expectations
  - Documentation: `PSWS_COMPATIBILITY_UPDATE.md`

- ✅ **Phase 2C - Web UI Integration** (Nov 10, 2024)
  - Monitoring server: Reads V2 JSON status files from both services
  - Dashboard: Displays dual-service metrics with per-channel data
  - Bug fix: DigitalRFWriter buffer timestamp IndexError resolved
  - Status: ✅ Real-time display at http://localhost:3000
  - Documentation: `WEB_UI_V2_INTEGRATION_SESSION.md`

- ✅ **Phase 2D - Tone Detection & WWV/H Discrimination** (Nov 12, 2024)
  - Cross-file buffering: Combines tail of previous file + head of current file to span minute boundaries
  - Tone detection working: WWV/WWVH/CHU tones detected at :00.0 minute boundaries
  - Time-snap establishment: 57% confidence from WWV tones
  - WWV/H discrimination: Differential delay measurements with outlier rejection (>±1000ms)
  - Typical delays: 100-300ms (ionospheric propagation)
  - Web UI: Displays WWV/H Δ Time in channel status table
  - Status: ✅ 3 WWV + 4 WWVH detections observed, 203ms mean differential delay
  - Documentation: Commit message `c07f59a`

- ⏳ **Phase 2E - Upload Integration** (Future priority)
  - Module exists: `uploader.py`
  - Needs: Wire to analytics service, implement rsync/sftp, trigger on directory completion

### **Current System Metrics** (Nov 10, 2024 19:45 UTC)

**Core Recorder:**
- 9/9 channels active (recording)
- 270+ NPZ files written per channel
- 600,000+ RTP packets received
- 0 gaps detected (100% completeness)
- 0 packet loss

**Analytics Services:**
- 9/9 services running and processing
- 1,370+ NPZ files processed per channel (cross-file buffering enabled)
- Quality metrics: 99.2% completeness, 0.8% packet loss
- Tone detections: WWV (3), WWVH (4), CHU (varies by propagation)
- Time-snap: Established at 57% confidence from WWV
- WWV/H discrimination: 18 measurements, 203ms mean differential delay
- Digital RF output: Writing successfully with outlier rejection

**Web UI:**
- Dashboard displaying V2 data
- System status: Core + Analytics health
- Data quality: Completeness, gaps, packet loss
- Channel Status tab: Real-time metrics with WWV/H Δ Time column
- WWV/H Discrimination tab: Daily plots (00:00-23:59 UTC) with SNR comparison
- Channel table: Per-channel real-time metrics including tone detections

---

## ✅ **Completed: Web UI Information Architecture** (Nov 10, 2024)

**Task:** Define comprehensive information display requirements for web UI monitoring and data visualization.

**Deliverables - Four-Document Specification Series:**

### 1. **System Monitoring** (`docs/WEB_UI_SYSTEM_MONITORING.md`)
   - Service health status (core recorder + analytics)
   - Data pipeline monitoring (archive, process, upload)
   - Resource utilization (disk, memory, CPU)
   - Error monitoring and system health scoring
   - Real-time update strategy

### 2. **Per-Channel Metrics** (`docs/WEB_UI_CHANNEL_METRICS.md`)
   - Core recording metrics (status, completeness, packet loss)
   - Analytics processing status
   - Tone detection performance (WWV/WWVH/CHU)
   - Time reference status per channel
   - Channel comparison table design

### 3. **Scientific Data Quality** (`docs/WEB_UI_SCIENTIFIC_QUALITY.md`)
   - Quantitative completeness reporting
   - Discontinuity tracking and classification
   - Timing provenance chain
   - WWV/WWVH propagation analysis
   - Metadata for scientific use
   - Data provenance audit trail

### 4. **Navigation & UX** (`docs/WEB_UI_NAVIGATION_UX.md`)
   - Three-level information hierarchy
   - Page layout and visual design
   - Navigation structure (current + future)
   - User workflows (daily check, troubleshoot, download)
   - Responsive design guidelines
   - Interactive features and accessibility

### 5. **Master Index** (`docs/WEB_UI_INFORMATION_ARCHITECTURE.md`)
   - Complete specification overview
   - Cross-cutting concerns (API, data sources, thresholds)
   - Implementation roadmap (5 phases)
   - Design principles and visual system
   - Testing and documentation requirements

**Status:** Specification complete - Ready for Phase 2 implementation (enhanced monitoring)

---

## ✅ **Completed: Tone Detection & WWV/H Discrimination** (Nov 12, 2024)

**Task:** Fix tone detection to work with 60-second NPZ files and implement WWV/WWVH discrimination analysis.

**Problem Solved:**
- Tone occurs AT minute boundary (between NPZ files, not within single file)
- Analytics was processing each file in isolation, missing boundary tones
- Differential delay showing outliers (~20 seconds) from bad timing measurements

**Solution Implemented:**

### Cross-File Buffering for Tone Detection
- Store last 30 seconds of previous NPZ file (16 kHz IQ samples)
- Combine with first 30 seconds of current file
- Creates 60-second buffer spanning minute boundary
- Tone at :00.0 is now in MIDDLE of detection buffer
- Properly calculates expected tone position relative to buffer start

**Key Changes:**
1. `analytics_service.py`: Add `previous_file_tail` and `previous_file_rtp_end` tracking
2. `tone_detector.py`: Fix timestamp calculation for expected tone position
3. `wwvh_discrimination.py`: Add outlier rejection (>±1000ms = detection error)
4. `monitoring-server.js`: Use mean differential delay when latest is null
5. `start-dual-service.sh` / `stop-dual-service.sh`: Fix python3 command, add service lifecycle management

**Results:**
- ✅ Tone detection working: 3 WWV + 4 WWVH detections
- ✅ Time-snap established: 57% confidence
- ✅ Differential delay: 203ms mean (WWV 5 MHz)
- ✅ Outlier rejection: Prevents crazy values from corrupting statistics
- ✅ Web UI displaying: WWV/H Δ Time column + discrimination plots

**Files Modified:**
- `src/signal_recorder/analytics_service.py` (cross-file buffering)
- `src/signal_recorder/tone_detector.py` (timestamp calculation fix)
- `src/signal_recorder/wwvh_discrimination.py` (outlier rejection)
- `web-ui/monitoring-server.js` (discrimination data display)
- `web-ui/channels.html` (new channel monitoring dashboard)
- `start-dual-service.sh`, `stop-dual-service.sh` (new service management scripts)

**Next Task - Phase 2F: 10 Hz Spectrogram Display**
- Implement carrier data spectrograms in web UI
- Display Digital RF data (10 Hz decimated) as time-frequency plots
- Show per-channel spectrograms for selected date range
- Enable visual inspection of carrier presence and signal quality
- Support daily views (00:00-23:59 UTC) with stacked channel displays

---

## 📋 Usage Instructions

### Starting a New AI Session

1. **Update Section 4** with your current branch and task goal (30 seconds)
2. **Start fresh chat session** (don't continue old conversations)
3. **Paste this entire file** as your first prompt
4. **Paste relevant code files** as second prompt
5. **State your specific request** as third prompt

### When to Update This File

**Section 1 (Mission):** Almost never (only if project pivots)  
**Section 2 (Principles):** Rarely (only when adding new tech or changing rules)  
**Section 3 (API Map):** As-needed (when core APIs change or stabilize)  
**Section 4 (Current Task):** EVERY SESSION (required)

### Maintenance Schedule

- **Daily:** Update Section 4 only
- **Weekly:** Review Section 3 for any major API changes
- **Monthly:** Review Section 2 for any principle changes
- **Yearly:** Review Section 1 for mission alignment

---

## 🔗 Related Documentation

**Core Architecture:**
- `ARCHITECTURE.md` - System design & rationale
- `INTERFACES_COMPLETE.md` - Complete API interface summary (Nov 2024)
- `src/signal_recorder/interfaces/README.md` - API usage guide

**Technical Details:**
- `docs/MULTI_STATION_TONE_DETECTION.md` - WWV/WWVH/CHU detection algorithm
- `docs/GRAPE_DIGITAL_RF_RECORDER.md` - Digital RF output specification
- `docs/TIMING_ARCHITECTURE_V2.md` - KA9Q timing implementation

**Health Monitoring (Nov 2024):**
- `HEALTH_MONITORING_IMPLEMENTATION.md` - Implementation guide and testing procedures
- `INTEGRATION_COMPLETE.md` - Complete integration summary
- `test-health-monitoring.sh` - Automated verification script

**Analytics Service (Nov 9, 2024):**
- `ANALYTICS_SERVICE_IMPLEMENTATION.md` - Complete implementation guide
- `SESSION_SUMMARY_NOV9_2024_ANALYTICS.md` - Session summary and next steps
- `src/signal_recorder/tone_detector.py` - Standalone tone detector module
- `src/signal_recorder/analytics_service.py` - NPZ processing pipeline
- `test-analytics-service.py` - Integration test suite

**Digital RF & PSWS Integration (Nov 9, 2024):**
- `DIGITAL_RF_INTEGRATION_COMPLETE.md` - Phase 2A implementation summary
- `PSWS_COMPATIBILITY_UPDATE.md` - Phase 2B wsprdaemon format verification
- `src/signal_recorder/digital_rf_writer.py` - PSWS-compatible Digital RF writer
- `test-drf-integration.py` - Digital RF end-to-end test
- `test-psws-format.py` - Directory structure validation

**Web UI V2 Integration (Nov 10, 2024):**
- `WEB_UI_V2_INTEGRATION_SESSION.md` - Phase 2C implementation summary
- `web-ui/monitoring-server.js` - V2 status aggregation and API endpoints
- `web-ui/timing-dashboard.html` - V2 dashboard with dual-service metrics
- Bug fix: DigitalRFWriter buffer timestamp tracking

**Web UI Information Architecture (Nov 10, 2024):**
- `docs/WEB_UI_INFORMATION_ARCHITECTURE.md` - Master index and specification overview
- `docs/WEB_UI_SYSTEM_MONITORING.md` - System-level operational metrics
- `docs/WEB_UI_CHANNEL_METRICS.md` - Per-channel data characterization
- `docs/WEB_UI_SCIENTIFIC_QUALITY.md` - Data quality and provenance reporting
- `docs/WEB_UI_NAVIGATION_UX.md` - User experience and information hierarchy

**Operations:**
- `INSTALLATION.md` - Setup & deployment
- `README.md` - Quick start guide
- `STARTUP_GUIDE.md` - Dual-service startup procedures
- `web-ui/README.md` - Web interface guide

---

**Last Updated:** 2024-11-12 Morning  
**Maintained By:** Michael Hauan (AC0G)  
**AI Context Version:** 1.5 (Tone Detection & WWV/H Discrimination Operational)
