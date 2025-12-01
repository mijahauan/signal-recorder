# GRAPE Recorder - AI Context Document

**Last Updated:** 2025-12-01 (afternoon)  
**Version:** 2.0.0  
**Status:** ✅ All systems operational. Startup scripts, analytics, and venv enforcement complete.

---

## 🔵 RTP Timestamp Pipeline (Critical for Understanding)

### Overview

The RTP timestamp from `radiod` is the **authoritative timing reference** for all recorded data. Understanding this pipeline is essential for accurate timing analysis.

### RTP Packet Structure from radiod

```
┌─────────────────────────────────────────────────────────────────┐
│ RTP Header (12 bytes)                                           │
├─────────────┬─────────────┬─────────────────────────────────────┤
│ V=2, P, X   │ M, PT=97/120│ Sequence Number (16-bit)            │
├─────────────┴─────────────┴─────────────────────────────────────┤
│ RTP Timestamp (32-bit) - Increments at sample_rate (16 kHz)     │
├─────────────────────────────────────────────────────────────────┤
│ SSRC (32-bit) - Unique stream identifier                        │
├─────────────────────────────────────────────────────────────────┤
│ Payload (640 bytes for IQ mode)                                 │
│   • PT=97: Real audio, 320 int16 samples                        │
│   • PT=120: IQ complex, 160 complex samples (320 int16 I/Q)     │
└─────────────────────────────────────────────────────────────────┘
```

### Key Timing Properties

| Property | Value | Notes |
|----------|-------|-------|
| Sample Rate | 16,000 Hz | Fixed for GRAPE channels |
| RTP Timestamp Increment | 320 per packet | Regardless of payload type |
| Packets per Second | 50 | 16000 / 320 = 50 |
| IQ Samples per Packet | 160 complex | Payload is 640 bytes |
| Segment Duration | 60 seconds | 960,000 RTP timestamp units |

### ⚠️ Critical: IQ Mode Sample Count Mismatch

**Problem discovered Dec 1, 2025:** In IQ mode (PT=120), each RTP packet contains 160 complex samples, but the RTP timestamp increments by 320. This caused segments to take 120 seconds instead of 60.

```python
# WRONG: Counting payload samples
segment_sample_count += len(samples)  # 160 per packet → 120s segments

# CORRECT: Counting RTP timestamp progression  
segment_rtp_count += samples_per_packet  # 320 per packet → 60s segments
```

**Fix location:** `src/grape_recorder/core/recording_session.py`
- Added `segment_rtp_count` to track RTP timestamp-based progression
- Added `rtp_samples_per_segment` for segment completion check
- Gap fills also add to RTP count since they represent time progression

### RTP Timestamp Flow Through Pipeline

```
radiod (ka9q-radio)
    │
    │ UDP Multicast: RTP packets with precise timestamps
    │ GPS-disciplined: Timestamps locked to GPS 1PPS
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ RTPReceiver (core/rtp_receiver.py)                              │
│   • Receives multicast UDP                                       │
│   • Parses RTP header, extracts timestamp                        │
│   • Routes by SSRC to RecordingSession                           │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ PacketResequencer (core/packet_resequencer.py)                  │
│   • Reorders out-of-order packets by RTP timestamp              │
│   • Detects gaps via timestamp discontinuity                     │
│   • Creates zero-filled samples for gaps (gap_samples count)     │
│   • Returns GapInfo with gap position and size                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ RecordingSession (core/recording_session.py)                    │
│   • Tracks segment_rtp_count for accurate 60s segments          │
│   • Aligns segment start to minute boundaries                    │
│   • Writes samples + gap metadata to SegmentWriter              │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ GrapeNPZWriter (grape/grape_npz_writer.py)                      │
│   • Saves NPZ with: iq, rtp_timestamp, gaps_count, gaps_filled  │
│   • First RTP timestamp stored for file alignment               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ AnalyticsService (grape/analytics_service.py)                   │
│   • Reads NPZ, uses RTP timestamp for timing analysis           │
│   • Decimates to 10 Hz, preserves timestamp alignment           │
│   • Runs discrimination methods keyed to minute boundaries      │
└─────────────────────────────────────────────────────────────────┘
```

### NPZ File Timestamp Metadata

Each 16kHz NPZ archive contains:

```python
{
    'iq': np.complex64[960000],      # 60 seconds of samples
    'rtp_timestamp': uint32,          # First sample's RTP timestamp
    'sample_rate': 16000,
    'gaps_count': int,                # Number of gap events
    'gaps_filled': int,               # Total samples zero-filled
    'gap_sample_indices': uint32[],   # Position of each gap
    'gap_samples_filled': uint32[],   # Size of each gap
}
```

### Leveraging RTP Timestamps

**For Timing Analysis:**
- RTP timestamp difference between files should be exactly 960,000 (60s)
- Gaps > 960,000 indicate missing files
- Gaps within file indicate RTP packet loss

**For GPS Accuracy:**
- radiod locks RTP timestamps to GPS 1PPS via `chrony` or similar
- First sample of each second aligns with GPS second boundary
- Typical accuracy: < 1 µs jitter when GPS-locked

**For Discrimination:**
- WWV/WWVH timing events (ticks, tones) occur at precise second offsets
- RTP timestamp provides sub-sample timing for ToA calculations
- Cross-correlate with known patterns for µs-level timing

---

## ✅ RESOLVED: Startup Scripts (Dec 1, 2025)

All startup scripts now:
- Use correct `grape_recorder.grape.*` module paths
- Enforce venv usage via `scripts/common.sh`
- Work with both test and production modes

---

## v2.0.0 Package Structure

```
src/grape_recorder/
├── core/                    # Application-agnostic infrastructure
│   ├── __init__.py
│   ├── rtp_receiver.py      # RTP multicast, SSRC demux
│   ├── recording_session.py # Segmentation, SegmentWriter protocol
│   └── packet_resequencer.py # Ordering, gap detection
│
├── stream/                  # SSRC-free Stream API
│   ├── __init__.py
│   ├── stream_api.py        # subscribe_stream(), high-level API
│   ├── stream_manager.py    # SSRC allocation, lifecycle, sharing
│   ├── stream_spec.py       # Content-based stream identity
│   └── stream_handle.py     # Opaque handle apps receive
│
├── grape/                   # GRAPE application (WWV/WWVH/CHU)
│   ├── __init__.py
│   ├── grape_recorder.py    # Two-phase recorder
│   ├── grape_npz_writer.py  # SegmentWriter → NPZ
│   ├── analytics_service.py # Discrimination, decimation  ← MOVED HERE
│   ├── core_recorder.py     # GRAPE orchestration         ← MOVED HERE
│   ├── wwvh_discrimination.py # 12 voting methods
│   ├── tone_detector.py
│   └── ... (22 files total)
│
├── wspr/                    # WSPR application
│   ├── __init__.py
│   ├── wspr_recorder.py     # Simple recorder
│   └── wspr_wav_writer.py   # SegmentWriter → WAV
│
├── __init__.py              # Re-exports for backward compatibility
├── channel_manager.py       # radiod channel control
├── radiod_health.py         # Health monitoring
├── paths.py                 # Path utilities (GRAPEPaths)
└── ... (shared utilities)
```

### Python Import Compatibility

The main `__init__.py` re-exports classes for backward compatibility:

```python
# These WORK (class imports):
from grape_recorder import GrapeRecorder, AnalyticsService

# But -m invocation requires FULL path:
python3 -m grape_recorder.grape.core_recorder      # ✅ Works
python3 -m grape_recorder.core_recorder            # ❌ Fails
```

---

## Web-UI Architecture

### Key Files

| File | Purpose |
|------|---------|
| `web-ui/monitoring-server-v3.js` | Express API server, serves all endpoints |
| `web-ui/grape-paths.js` | Centralized path management (synced with Python `paths.py`) |
| `web-ui/utils/timing-analysis-helpers.js` | Timing metrics parsing |
| `web-ui/discrimination.js` | Discrimination chart rendering |

### API Endpoints (unchanged)

```
GET /api/v1/summary              # System status overview
GET /api/v1/channels             # All channel status
GET /api/v1/channels/:channel    # Single channel detail
GET /api/v1/discrimination/:channel/:date  # Discrimination data
GET /api/v1/spectrograms/:channel/:date    # Spectrogram images
```

### Path Management

`grape-paths.js` mirrors Python's `paths.py` for consistent file access:

```javascript
const paths = new GRAPEPaths('/tmp/grape-test');
paths.getArchiveDir('WWV 10 MHz')      // /tmp/grape-test/archives/WWV_10_MHz/
paths.getAnalyticsDir('WWV 10 MHz')    // /tmp/grape-test/analytics/WWV_10_MHz/
paths.getDiscriminationDir('WWV 10 MHz') // .../discrimination/
```

---

## Startup Script Details

### grape-core.sh (line 59)

```bash
# CURRENT (broken):
nohup python3 -m grape_recorder.core_recorder --config "$CONFIG" \

# FIX:
nohup python3 -m grape_recorder.grape.core_recorder --config "$CONFIG" \
```

### grape-analytics.sh (lines 68, 91)

```bash
# CURRENT (broken):
nohup python3 -m grape_recorder.analytics_service \

# FIX:
nohup python3 -m grape_recorder.grape.analytics_service \
```

### grape-all.sh (status detection, lines 78-85)

```bash
# CURRENT (broken):
CORE_COUNT=$(pgrep -f "grape_recorder.core_recorder" 2>/dev/null | wc -l)

# FIX:
CORE_COUNT=$(pgrep -f "grape_recorder.grape.core_recorder" 2>/dev/null | wc -l)
```

---

## Data Directory Structure

```
/tmp/grape-test/                          # Test mode root
├── archives/{CHANNEL}/                   # Raw 16 kHz NPZ files
│   └── YYYYMMDDTHHMMSSZ_{freq}_iq.npz
├── analytics/{CHANNEL}/
│   ├── decimated/                        # 10 Hz NPZ files
│   ├── discrimination/                   # Final voting CSVs
│   ├── bcd_discrimination/               # BCD method CSVs
│   ├── tone_detections/                  # 1000/1200 Hz CSVs
│   ├── tick_windows/                     # Tick SNR CSVs
│   ├── station_id_440hz/                 # 440 Hz detection CSVs
│   ├── test_signal/                      # Minutes 8/44 CSVs
│   ├── doppler/                          # Doppler shift CSVs
│   ├── timing/                           # Timing metrics
│   └── status/                           # analytics-service-status.json
├── spectrograms/{YYYYMMDD}/              # Daily spectrogram PNGs
├── state/                                # Service persistence
├── status/                               # System-wide status
└── logs/                                 # Service logs
```

---

## Service Control Commands

```bash
# Current (after fixes):
./scripts/grape-all.sh -start    # Start all services
./scripts/grape-all.sh -stop     # Stop all services
./scripts/grape-all.sh -status   # Check status

# Web UI
http://localhost:3000            # Main dashboard
http://localhost:3000/carrier.html        # Carrier analysis
http://localhost:3000/discrimination.html # WWV/WWVH discrimination
```

---

## Session History

### Dec 1, 2025 (Afternoon): RTP Timing Fix & Infrastructure

**Critical Bug Fix:**
- **IQ mode 2-minute cadence bug:** Segments took 120s instead of 60s
  - Root cause: Counting payload samples (160) vs RTP timestamp increment (320)
  - Fix: Added `segment_rtp_count` in `recording_session.py` to track RTP progression
  - Files now correctly generated every 60 seconds

**Infrastructure Improvements:**
- **Created `scripts/common.sh`:** Centralized venv enforcement
  - All shell scripts source this for `$PYTHON`, `$PROJECT_DIR`, `get_data_root()`
  - Scripts fail with clear error if venv not found
- **Created `venv_check.py`:** Python-side venv verification
- **Updated startup scripts:** `grape-core.sh`, `grape-analytics.sh`, `grape-ui.sh`
- **Restarted analytics services:** Now using `grape_recorder` (was `signal_recorder`)

**Spectrogram Cleanup:**
- **Consolidated scripts:** Kept `generate_spectrograms_from_10hz.py` (reads 10Hz decimated)
- **Archived deprecated:** `generate_spectrograms.py`, `generate_spectrograms_v2.py`
- **Fixed bug:** `archive_dir_name` → `archive_dir.name`

**API Enhancements:**
- **Added `/api/v1/rtp-gaps`:** Exposes RTP-level gap analysis
- **Updated `carrier.html`:** Quality panel shows RTP gap metrics

### Dec 1, 2025 (Morning): v2.0.0 Release
- **Merged** `feature/generic-rtp-recorder` to main
- **Tagged** v2.0.0
- **GitHub Release** created with release notes
- **Fixed** `TimingMetricsWriter.get_ntp_offset()` removal bug
- **Updated** README.md and TECHNICAL_REFERENCE.md

### Dec 1, 2025 (Earlier): SSRC Abstraction Complete
- **ka9q-python 3.1.0**: Added `allocate_ssrc()` and SSRC-free `create_channel()`
- **Cross-library compatibility**: Both libraries use identical SSRC hash

### Nov 30, 2025: Stream API + WSPR Demo
- Stream API: `subscribe_stream()` hides SSRC
- WSPR demo validated multi-app pipeline
- GRAPE refactor: GrapeRecorder + GrapeNPZWriter

### Nov 29, 2025: Discrimination Enhancements
- 12 voting methods + 12 cross-validation checks
- Test signal channel sounding (FSS, noise, burst, chirps)

---

## Station Configuration

| Parameter | Value |
|-----------|-------|
| **Callsign** | AC0G |
| **Grid Square** | EM38ww |
| **PSWS Station ID** | S000171 |

### Channels (9 total)

| Frequency | Station |
|-----------|---------|
| 2.5 MHz | WWV |
| 3.33 MHz | CHU |
| 5.0 MHz | WWV |
| 7.85 MHz | CHU |
| 10.0 MHz | WWV |
| 14.67 MHz | CHU |
| 15.0 MHz | WWV |
| 20.0 MHz | WWV |
| 25.0 MHz | WWV |

---

## GRAPE Discrimination System (12 Voting Methods)

| Vote | Method | Weight | Description |
|------|--------|--------|-------------|
| 0 | Test Signal | 15 | Minutes :08/:44 scientific modulation |
| 1 | 440 Hz Station ID | 10 | WWVH min 1, WWV min 2 |
| 2 | BCD Amplitude | 2-10 | 100 Hz time code dual-peak |
| 3 | 1000/1200 Hz Power | 1-10 | Timing tone ratio |
| 4 | Tick SNR | 5 | 59-tick coherent integration |
| 5 | 500/600 Hz | 10-15 | 14 exclusive min/hour |
| 6 | Doppler Stability | 2 | Lower std = cleaner path |
| 7 | Timing Coherence | 3 | Test + BCD ToA agreement |
| 8 | Harmonic Ratio | 1.5 | 500→1000, 600→1200 Hz |
| 9 | FSS Path | 2 | Frequency Selectivity Score |
| 10 | Noise Coherence | flag | Transient detection |
| 11 | Burst ToA | validation | High-precision timing |
| 12 | Spreading Factor | flag | Channel physics L = τ_D × f_D |

---

## Critical Bug History

Three bugs corrupted all data before Oct 30, 2025:
1. **Byte Order:** `np.int16` (little) → `'>i2'` (big-endian network order)
2. **I/Q Phase:** `I + jQ` → `Q + jI` (carrier centered at 0 Hz)
3. **Payload Offset:** Hardcoded `12` → calculate from RTP header
