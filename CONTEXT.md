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

**4. Data Quality & Provenance**

- **Every discontinuity MUST be logged:** Gap, sync adjustment, RTP reset, buffer overflow
- **Quality grades:** A (≥99%), B (95-99%), C (90-95%), D (85-90%), F (<85%)
- **Embedded metadata:** Quality info in archive files AND Digital RF metadata
- **No silent corrections:** All timing adjustments logged with explanation

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

**Discontinuity Record:**
```python
Discontinuity(
    timestamp: float,
    sample_index: int,
    discontinuity_type: DiscontinuityType,  # GAP, RTP_RESET, SYNC_ADJUST
    magnitude_samples: int,     # +gap, -overlap
    magnitude_ms: float,
    rtp_sequence_before: int,
    rtp_sequence_after: int,
    rtp_timestamp_before: int,
    rtp_timestamp_after: int,
    wwv_related: bool,
    explanation: str            # Human-readable cause
)
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

**Location:** `src/signal_recorder/grape_rtp_recorder.py` (94,231 lines)

**Key Classes:**

```python
GRAPERTPRecorder:
    # Main daemon - manages multiple channel recorders
    # Methods: start(), stop(), get_status()
    
GRAPEChannelRecorder:
    # Per-channel RTP → Digital RF pipeline
    # Implements: RTP reception, resequencing, gap fill, tone detection
    # Line ~450-1400
    
MultiStationToneDetector:
    # WWV/WWVH/CHU discrimination using quadrature matched filtering
    # Line ~175-419
    # Critical: Sets use_for_time_snap flag correctly
```

### Web Interface

**Location:** `web-ui/`

**Backend:** `simple-server.js` (Express.js API server)

```javascript
// Configuration endpoints
GET  /api/config                    // Get current config
POST /api/config/save               // Save TOML config

// Monitoring endpoints  
GET  /api/monitoring/recording-stats // Live quality metrics (JSON)
GET  /api/monitoring/daemon-logs     // Recent daemon logs

// Channel management
GET  /api/channels/discover          // Discover ka9q-radio channels
POST /api/channels/create            // Create new channel via radiod
```

**Frontend:** `index.html` (configuration), `monitoring.html` (dashboard)

### Configuration

**Location:** `config/grape-config.toml`

**Key Sections:**
```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
instrument_id = "RX888"

[recorder]
mode = "test" | "production"
test_data_root = "/tmp/grape-test"
production_data_root = "/var/lib/signal-recorder"

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
description = "WWV 2.5 MHz"
enabled = true

[uploader]
enabled = true
protocol = "rsync"
remote_host = "pswsnetwork.eng.ua.edu"
```

### Directory Structure

```
src/signal_recorder/
├── interfaces/              # API definitions (NEW - Nov 2024)
│   ├── data_models.py      # Shared data structures
│   ├── sample_provider.py  # Function 1 interface
│   ├── archive.py          # Function 2 interface
│   ├── tone_detection.py   # Function 3 interface
│   ├── decimation.py       # Functions 4+5 interface
│   └── upload.py           # Function 6 interface
├── grape_rtp_recorder.py   # Main V1 implementation (ACTIVE)
├── grape_channel_recorder_v2.py  # V2 (reference, not in use)
├── digital_rf_writer.py    # Digital RF output
├── minute_file_writer.py   # Archive writer
├── uploader.py             # Upload manager (not integrated)
├── quality_metrics.py      # Quality calculation
└── cli.py                  # Command-line interface

web-ui/
├── simple-server.js        # Node.js API server
├── index.html              # Configuration UI
└── monitoring.html         # Real-time dashboard
```

---

## 4. ⚡ Current Task & Git Context

**Current Branch:** `main`  
**Task Goal:** [UPDATE THIS SECTION AT START OF EACH SESSION]

**Example Task Entry:**
```
Current Branch: feat/upload-integration
Task Goal: Wire up Function 6 (UploadManager) into the daemon

Key Steps:
1. Create UploadQueue adapter for UploadManager
2. Instantiate in GRAPERTPRecorder at startup
3. Connect to DigitalRFWriter completion callback
4. Start background upload worker
5. Test with actual Digital RF files

Files to Modify:
- src/signal_recorder/grape_rtp_recorder.py (add upload integration)
- src/signal_recorder/uploader.py (verify adapter compatibility)
```

**Session Notes:**
- [Add any session-specific context here]
- [E.g., "Working around line 850 in grape_rtp_recorder.py"]
- [E.g., "Bug: Upload fails with permission error - need to check SSH keys"]

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

**Operations:**
- `INSTALLATION.md` - Setup & deployment
- `README.md` - Quick start guide
- `web-ui/README.md` - Web interface guide

---

**Last Updated:** 2024-11-08  
**Maintained By:** Michael Hauan (AC0G)  
**AI Context Version:** 1.0
