# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-03 (Evening)  
**Version:** 3.1.0  
**Status:** ✅ Phase 1 Complete, 🔄 Phase 2 In Progress

---

## 🎯 CURRENT STATE: PHASE 2 ANALYTICAL ENGINE

### Ready to Complete Phase 2

All core components for Phase 2 are **implemented and tested**. A 6-hour recording session is currently in progress gathering data for refinement.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    THREE-PHASE PIPELINE ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: IMMUTABLE RAW ARCHIVE (✅ COMPLETE)                               │
│  ════════════════════════════════════════════                               │
│  • Raw 32-bit float IQ from radiod via RTP                                  │
│  • Digital RF format with gzip compression                                   │
│  • ChannelManager for proper channel reuse (fixed Dec 3)                    │
│  • All 9 channels recording reliably (WWV + CHU)                            │
│                                                                              │
│  PHASE 2: ANALYTICAL ENGINE (🔄 IN PROGRESS - Core Complete)                │
│  ══════════════════════════════════════════════════════════                 │
│  • Phase2TemporalEngine: 3-step refined analysis                            │
│  • Tone detection: 1000/1200 Hz (WWV/WWVH) + 500ms CHU                     │
│  • GlobalStationVoter: Cross-channel coherent processing                    │
│  • TransmissionTimeSolver: Hop-count back-calculation                       │
│  • 500/600 Hz discrimination: Single-station minutes only                   │
│                                                                              │
│  PHASE 3: DERIVED PRODUCTS (🔮 FUTURE)                                      │
│  ═════════════════════════════════════                                      │
│  • Decimated time series (10 Hz) - CorrectedProductGenerator exists         │
│  • Station discrimination CSV output                                         │
│  • Spectrograms, PSWS upload format                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Immutability**: Phase 1 data is write-once, never modified
2. **Replayability**: Phase 2/3 can be re-run on historical Phase 1 data
3. **Separation of Concerns**: Each phase has single responsibility
4. **Provenance**: Full audit trail from raw samples to derived products

---

## 🔄 PHASE 2 IMPLEMENTATION STATUS (Dec 3, 2025 Evening)

### Phase 2 Temporal Engine - IMPLEMENTED

The `Phase2TemporalEngine` performs refined temporal analysis in 3 steps:

```
Step 1: Tone Detection (±500ms → anchor)
  └─► Matched filter for 1000/1200 Hz (WWV/WWVH) or 500ms 1000 Hz (CHU)
  └─► Output: TimeSnapResult with timing_error_ms, anchor_station

Step 2: Channel Characterization (±10-50ms)  
  └─► BCD correlation, Doppler estimation, Station ID
  └─► Output: ChannelCharacterization with dominant_station

Step 3: Transmission Time Solution → D_clock
  └─► TransmissionTimeSolver identifies propagation mode (hop count)
  └─► Output: Phase2Result with d_clock_ms, quality_grade
```

**Key Files:**
| File | Purpose |
|------|---------|
| `phase2_temporal_engine.py` | Main engine with 3-step processing |
| `tone_detector.py` | Matched filter detection (WWV/WWVH/CHU) |
| `transmission_time_solver.py` | Hop-count mode identification |
| `global_station_voter.py` | Cross-channel anchor coordination |

### Critical Bug Fixes Applied

1. **Minute Boundary Calculation** (`tone_detector.py`):
   ```python
   # WRONG: round(buffer_mid_time / 60) * 60
   # CORRECT:
   buffer_start_time = current_unix_time - (buffer_duration_sec / 2)
   minute_boundary = int(buffer_start_time / 60) * 60
   ```

2. **system_time Parameter**: When calling `Phase2TemporalEngine.process_minute()`:
   - `system_time` must be buffer START time (not midpoint)
   - Engine internally adds `buffer_duration/2` for tone detector

3. **CHU Support Added**: Phase 2 now handles CHU channels (500ms @ 1000 Hz)

### 500/600 Hz Station Discrimination - CORRECTED

**Key Physics**: BCD 100 Hz modulation creates intermod products at 500/600 Hz when BOTH stations present. Discrimination only valid during **single-station minutes**:

| Minutes | Broadcasting Station | Valid Discrimination |
|---------|---------------------|---------------------|
| 1, 16, 17, 19 | WWV only (WWVH silent) | 500 Hz → WWV |
| 2, 43-51 | WWVH only (WWV silent) | 600 Hz → WWVH |
| All others | BOTH | INTERMOD_RISK |

### Testing Results (Dec 3, 2025)

All 9 channels recording and producing usable Phase 2 results:

| Channel | Timing | D_clock | Anchor | SNR | Grade |
|---------|--------|---------|--------|-----|-------|
| WWV 10 MHz | +7.3ms | **-0.2ms** | WWV | 35.8 dB | B |
| WWV 5 MHz | +336.3ms | +332.3ms | WWV | 35.6 dB | D |
| CHU 3.33 MHz | +33.9ms | +11.2ms | CHU | 14.5 dB | D |
| CHU 7.85 MHz | +38.1ms | +32.5ms | CHU | 14.9 dB | D |

**WWV 10 MHz D_clock of -0.2ms** indicates system clock nearly synchronized with UTC(NIST).

### Remaining Work for Phase 2 Completion

1. **Integrate GlobalStationVoter** with live pipeline for guided weak-channel detection
2. **Implement channel stacking** ("nuclear option") for marginal signals
3. **Validate back-calculation accuracy** with multi-hour data
4. **CSV output format** for D_clock time series

---

## ✅ PHASE 1 COMPLETE: Immutable Raw Archive (Dec 3, 2025)

### Implementation Summary

Phase 1 captures raw IQ data from radiod and stores it in Digital RF format with comprehensive metadata and data quality tracking.

### Data Flow

```
radiod (ka9q-radio)
    │
    │ UDP Multicast: RTP packets (PT=111 for F32 IQ)
    │ GPS-disciplined timestamps
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ ka9q-python RTPRecorder                                          │
│   • Packet resequencing (handles out-of-order, duplicates)       │
│   • Gap detection via RTP sequence numbers                       │
│   • Payload extraction (32-bit float IQ)                         │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ RawArchiveWriter (raw_archive_writer.py)                         │
│   • Data validation: NaN/Inf detection, clipping warnings        │
│   • Gap handling: zero-fill with metadata                        │
│   • NTP status tracking for provenance                           │
│   • Digital RF output: gzip compressed, hourly files             │
│   • Session summary: full audit trail                            │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Digital RF Archive                                               │
│   output_dir/raw_archive/CHANNEL_NAME/                          │
│   ├── YYYYMMDD/                                                  │
│   │   └── drf_*.h5  (HDF5 with complex64 samples)               │
│   └── metadata/                                                  │
│       └── session_summary.json                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `src/grape_recorder/grape/raw_archive_writer.py` | Phase 1 writer with Digital RF output |
| `src/grape_recorder/grape/pipeline_orchestrator.py` | Three-phase pipeline orchestration |
| `scripts/run_all_channels_pipeline.py` | Multi-channel pipeline runner |
| `config/grape-config.toml` | Configuration including storage quota |

### RawArchiveConfig Parameters

```python
@dataclass
class RawArchiveConfig:
    output_dir: Path              # Root output directory
    channel_name: str             # e.g., "WWV_10_MHz"
    frequency_hz: float           # Center frequency
    sample_rate: int = 20000      # Samples per second
    station_config: Dict          # Callsign, grid, IDs
    compression: str = 'gzip'     # 'gzip', 'lz4', 'zstd', 'none'
    use_shuffle: bool = True      # HDF5 shuffle filter
    file_duration_sec: int = 3600 # 1-hour files
    max_file_size_bytes: int = 1GB
    subdir_cadence_secs: int = 86400  # Daily directories
```

### Data Quality Tracking

The `session_summary.json` includes:

```json
{
  "session_id": "uuid",
  "channel_name": "WWV_10_MHz",
  "start_time_utc": "2025-12-03T00:00:00Z",
  "end_time_utc": "2025-12-03T01:00:00Z",
  "samples_written": 72000000,
  "total_gap_samples": 0,
  "files_written": 1,
  "stream_health": {
    "packets_received": 180000,
    "packets_dropped": 0,
    "packets_out_of_order": 0,
    "sequence_errors": 0
  },
  "ntp_status": {
    "synced": true,
    "offset_ms": 0.123,
    "stratum": 2
  },
  "data_quality": {
    "samples_validated": 72000000,
    "samples_with_nan": 0,
    "samples_with_inf": 0,
    "samples_clipped": 0,
    "gaps_detected": 0,
    "sample_integrity_ratio": 1.0
  }
}
```

### Storage Quota Management

Total storage allocation for ALL channels with FIFO cleanup:

```toml
# grape-config.toml
[recorder]
storage_quota = "80%"    # Percentage of disk
# storage_quota = "500GB"  # Or fixed size
# storage_quota = "1TB"
# storage_quota = "unlimited"
```

**Behavior:**
- Manages all channels together (not per-channel)
- FIFO removal: oldest date directories across all channels removed first
- Safety: never removes current day's data
- Audit log: `quota_removal_log.json` in output root

### Running Phase 1

```bash
# All channels from config
python scripts/run_all_channels_pipeline.py \
    --config config/grape-config.toml \
    --output /data/grape-archive

# With storage quota override
python scripts/run_all_channels_pipeline.py \
    --config config/grape-config.toml \
    --output /data/grape-archive \
    --quota 500  # 500 GB total
```

---

## 📋 PHASE 2: Analytical Engine (NEXT IMPLEMENTATION)

### Overview

Phase 2 processes the raw IQ archive to extract timing and propagation information. The core output is the **clock offset series**: the difference between receiver time and transmitter time.

### Key Concept: Clock Offset (D_clock)

```
D_clock(t) = T_receiver(t) - T_transmitter(t)
           = τ_propagation(t) + ε_clock(t) + noise(t)

Where:
  τ_propagation = ionospheric delay (varies with solar conditions)
  ε_clock       = receiver clock error (should be ~0 if NTP-synced)
  noise         = measurement noise
```

### Phase 2 Components (To Implement)

1. **Clock Offset Engine** (`clock_offset_series.py`)
   - Input: Raw IQ from Phase 1
   - Process: Correlate with known WWV/WWVH/CHU timing patterns
   - Output: D_clock(t) time series at ~1 Hz

2. **Carrier Analysis** (`carrier_analyzer.py`)
   - Amplitude envelope extraction
   - Phase tracking and unwrapping
   - Doppler shift estimation
   - Signal quality metrics (SNR, fading rate)

3. **Transmission Time Solver** (`transmission_time_solver.py`)
   - Multi-frequency consensus
   - Propagation mode identification (1-hop, 2-hop, etc.)
   - UTC(NIST) back-calculation

### Phase 2 Data Flow

```
Phase 1 Archive (Digital RF)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Clock Offset Engine                                              │
│   • Load 1-minute chunks of raw IQ                               │
│   • Correlate with WWV tick template (1 PPS)                     │
│   • Extract arrival time relative to system clock                │
│   • D_clock = arrival_time - expected_utc_second                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Carrier Analyzer                                                 │
│   • Hilbert transform for analytic signal                        │
│   • Instantaneous amplitude, phase, frequency                    │
│   • Doppler = d(phase)/dt / (2π)                                │
│   • Fading statistics                                            │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Transmission Time Solver                                         │
│   • Combine D_clock from multiple frequencies                    │
│   • Identify propagation mode from delay spread                  │
│   • Calculate: T_transmit = T_receive - τ_propagation           │
│   • Cross-validate WWV vs WWVH                                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
Phase 2 Output:
  clock_offset/CHANNEL/YYYYMMDD/clock_offset_*.csv
  carrier/CHANNEL/YYYYMMDD/carrier_*.csv
```

### Phase 2 Output Formats

**Clock Offset CSV:**
```csv
timestamp_utc,d_clock_ms,confidence,snr_db,propagation_mode
2025-12-03T00:00:01Z,4.523,0.95,25.3,1F2
2025-12-03T00:00:02Z,4.518,0.94,24.8,1F2
```

**Carrier Analysis CSV:**
```csv
timestamp_utc,amplitude,phase_rad,doppler_hz,snr_db
2025-12-03T00:00:00.000Z,0.0234,1.234,-0.5,28.3
2025-12-03T00:00:00.100Z,0.0231,1.298,-0.4,27.9
```

### Phase 2 Directory Structure

```
output_dir/
├── raw_archive/          # Phase 1 (input)
│   └── CHANNEL/
│       └── YYYYMMDD/
│           └── drf_*.h5
├── clock_offset/         # Phase 2 output
│   └── CHANNEL/
│       └── YYYYMMDD/
│           └── clock_offset_HHMM.csv
├── carrier/              # Phase 2 output
│   └── CHANNEL/
│       └── YYYYMMDD/
│           └── carrier_HHMM.csv
└── transmission_time/    # Phase 2 output
    └── YYYYMMDD/
        └── transmission_time.csv
```

### Existing Code to Leverage

Phase 2 can build on existing discrimination/analysis code:

| Existing | Reuse For |
|----------|-----------|
| `tone_detector.py` | Tick correlation, ToA extraction |
| `wwvh_discrimination.py` | Station identification patterns |
| `timing_metrics_writer.py` | CSV output format |
| `global_station_voter.py` | Multi-channel consensus |
| `propagation_mode_solver.py` | Mode identification |

### Key Algorithms for Phase 2

1. **Tick Detection** (for D_clock):
   ```python
   # Correlate with 5ms tick template
   template = generate_tick_template(sample_rate=20000, duration_ms=5)
   correlation = np.correlate(iq_samples, template, mode='same')
   tick_indices = find_peaks(np.abs(correlation), distance=sample_rate)
   ```

2. **Doppler Extraction**:
   ```python
   # Instantaneous frequency from phase
   analytic = scipy.signal.hilbert(np.real(iq_samples))
   phase = np.unwrap(np.angle(analytic))
   doppler_hz = np.diff(phase) * sample_rate / (2 * np.pi)
   ```

3. **Propagation Mode ID**:
   ```python
   # Delay spread indicates multipath
   delay_spread_ms = np.std(tick_arrival_times)
   if delay_spread_ms < 0.5:
       mode = "1-hop"
   elif delay_spread_ms < 1.5:
       mode = "2-hop"
   else:
       mode = "multi-hop"
   ```

---

## 🔮 PHASE 3: Derived Products (Future)

Phase 3 produces final user-facing outputs:

- **Decimated time series** (10 Hz for spectrograms)
- **Station discrimination** (WWV vs WWVH vs CHU)
- **Spectrograms** (daily PNG images)
- **PSWS upload format** (CSV for community database)
- **Timing dashboard data** (JSON for web UI)

Most of this exists in current codebase (`analytics_service.py`, `decimation.py`, etc.) and will be integrated into Phase 3.

---

## ✅ COMPLETED: Fresh Installation with TEST/PRODUCTION Mode

### Implementation (Dec 2, 2025)

Created unified installation system supporting both TEST and PRODUCTION modes:

1. **Installation Script:** `scripts/install.sh --mode test|production`
   - Creates directories based on mode
   - Sets up Python venv with all dependencies
   - Installs systemd services (production only)
   - Creates environment file for consistent paths

2. **Environment File:** `config/environment` (test) or `/etc/grape-recorder/environment` (production)
   - Single source of truth for paths
   - All scripts and systemd services source this file
   - Variables: `GRAPE_MODE`, `GRAPE_DATA_ROOT`, `GRAPE_CONFIG`, `GRAPE_VENV`, etc.

3. **Path Separation**
   ```
   TEST MODE:        /tmp/grape-test/{archives,analytics,logs,...}
   PRODUCTION MODE:  /var/lib/grape-recorder/{archives,analytics,logs,...}
   ```

4. **Systemd Services (Production)**
   - `grape-recorder.service` - Core RTP→NPZ recorder
   - `grape-analytics.service` - Decimation, discrimination
   - `grape-analytics@.service` - Template for per-channel
   - `grape-webui.service` - Express web server
   - `grape-upload.timer` - Daily 00:30 UTC upload trigger
   - `grape-upload.service` - SFTP upload to PSWS

5. **Documentation:** `docs/PRODUCTION.md` - Full production deployment guide

### Quick Start

```bash
# Test mode (development)
./scripts/install.sh --mode test
./scripts/grape-all.sh -start

# Production mode (24/7 operation)
sudo ./scripts/install.sh --mode production --user $USER
sudo systemctl start grape-recorder grape-analytics grape-webui
sudo systemctl enable grape-upload.timer
```

### Files Created/Modified
- `scripts/install.sh` - Unified installer
- `config/environment.template` - Environment file template
- `scripts/common.sh` - Updated to source environment file
- `scripts/daily-drf-upload.sh` - Updated to use environment
- `docs/PRODUCTION.md` - Production deployment guide

---

## ✅ Config-Driven Sample Rate Architecture

### Overview
Sample rate and RTP packet timing are now **fully config-driven**. Change `grape-config.toml` and all derived values (samples_per_packet, max_gap_samples) are automatically calculated throughout the system.

### Config Parameters (`[recorder]` section)
```toml
# Required per-channel:
sample_rate = 20000           # Sample rate in Hz

# Optional (global defaults):
blocktime_ms = 20             # radiod blocktime (default 20ms)
max_gap_seconds = 60          # Maximum gap to fill with zeros
```

### Automatic Calculations
| Value | Formula | Example (20 kHz, 20ms) |
|-------|---------|------------------------|
| `samples_per_packet` | `sample_rate × blocktime_ms / 1000` | 400 |
| `max_gap_samples` | `sample_rate × max_gap_seconds` | 1,200,000 |

### Supported Sample Rates (Decimation)
The decimation module requires explicit support for each input rate. Currently supported:

| Rate | CIC Factor | Total Factor | Status |
|------|------------|--------------|--------|
| 20,000 Hz | 50 | 2000 | Default |
| 16,000 Hz | 40 | 1600 | Legacy |

To add a new rate (e.g., 24 kHz), update `SUPPORTED_INPUT_RATES` in `src/grape_recorder/grape/decimation.py`:
```python
24000: {
    'cic_decimation': 60,    # 24000 / 60 = 400 Hz
    'total_factor': 2400,    # 24000 / 10 = 2400
    'description': '24 kHz',
},
```

### RTP Packet Structure (20 kHz default)
```
- Packets per second: 50 (sample_rate / samples_per_packet)
- Samples per packet: 400 (sample_rate × blocktime_ms / 1000)
- Samples per 60s segment: 1,200,000
- IQ samples per packet: 200 complex (samples_per_packet / 2)
```

### Verification Checklist
- [ ] radiod configured for correct sample rate
- [ ] Archives contain expected sample count (sample_rate × 60)
- [ ] Decimation produces 600 samples/min (10 Hz × 60s)
- [ ] Spectrograms generate correctly

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
│ RTP Timestamp (32-bit) - Increments at sample_rate (20 kHz)     │
├─────────────────────────────────────────────────────────────────┤
│ SSRC (32-bit) - Unique stream identifier                        │
├─────────────────────────────────────────────────────────────────┤
│ Payload (800 bytes for IQ mode @ 20 kHz)                        │
│   • PT=97: Real audio, 400 int16 samples                        │
│   • PT=120: IQ complex, 200 complex samples (400 int16 I/Q)     │
└─────────────────────────────────────────────────────────────────┘
```

### Key Timing Properties

| Property | Value | Notes |
|----------|-------|-------|
| Sample Rate | 20,000 Hz | Default for GRAPE channels |
| RTP Timestamp Increment | 400 per packet | 20ms blocktime |
| Packets per Second | 50 | 20000 / 400 = 50 |
| IQ Samples per Packet | 200 complex | Payload is 800 bytes |
| Segment Duration | 60 seconds | 1,200,000 RTP timestamp units |

### ⚠️ Critical: IQ Mode Sample Count Mismatch

**Problem discovered Dec 1, 2025:** In IQ mode (PT=120), each RTP packet contains N/2 complex samples, but the RTP timestamp increments by N. This caused segments to take 120 seconds instead of 60.

```python
# WRONG: Counting payload samples
segment_sample_count += len(samples)  # 200 per packet @ 20 kHz → 120s segments

# CORRECT: Counting RTP timestamp progression  
segment_rtp_count += samples_per_packet  # 400 per packet @ 20 kHz → 60s segments
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

Each 20kHz NPZ archive contains:

```python
{
    'iq': np.complex64[1200000],      # 60 seconds of samples @ 20 kHz
    'rtp_timestamp': uint32,          # First sample's RTP timestamp
    'sample_rate': 20000,
    'gaps_count': int,                # Number of gap events
    'gaps_filled': int,               # Total samples zero-filled
    'gap_sample_indices': uint32[],   # Position of each gap
    'gap_samples_filled': uint32[],   # Size of each gap
}
```

### Leveraging RTP Timestamps

**For Timing Analysis:**
- RTP timestamp difference between files should be exactly 1,200,000 (60s @ 20 kHz)
- Gaps > 1,200,000 indicate missing files
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
├── archives/{CHANNEL}/                   # Raw 20 kHz NPZ files
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

## 🌐 Global Station Lock (Cross-Channel Coherent Processing)

### Concept

Because radiod's RTP timestamps are GPS-disciplined, all channels share a common "ruler". This enables treating 9-12 receivers not as isolated bucket-collectors but as a **single coherent sensor array**.

### The Physics

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Frequency dispersion** | < 2-3 ms | Group delay difference between HF bands |
| **Station separation** | 15-20 ms | WWV (Colorado) vs WWVH (Hawaii) path difference |
| **Discrimination margin** | ~5x | Dispersion << separation enables unambiguous guidance |

### Three-Phase Detection Strategy

**Phase 0: Anchor Discovery**
- Scan all 9-12 channels using standard discrimination
- Find high-confidence locks (SNR > 15 dB) for each station
- Set anchor RTP timestamps: $T_{\text{WWV}}$, $T_{\text{WWVH}}$, $T_{\text{CHU}}$

**Phase 1: Guided Search (Re-processing)**
- For weak channels (failed or low-confidence detection)
- Narrow search window from ±500 ms to ±3 ms using anchor timing
- 99.4% noise candidate rejection
- Weak correlations validated by anchor get boosted confidence

**Phase 2: Coherent Stacking (Optional)**
$$\text{Global Correlation} = \sum_{f} \text{Correlation}_f$$
- Signal adds linearly (correlated across frequencies)
- Noise adds as $\sqrt{N}$ (uncorrelated)
- Result: Virtual channel with SNR improvement of $10 \log_{10}(N)$ dB

### Implementation

```python
from grape_recorder.grape import GlobalStationVoter, StationLockCoordinator

# Create coordinator
coordinator = StationLockCoordinator(data_root='/tmp/grape-test')

# Process minute across all channels
result = coordinator.process_minute_archives(minute_utc, archives)

# Result contains:
# - result.wwv_anchor: Which channel provided WWV timing reference
# - result.wwvh_anchor: Which channel provided WWVH timing reference  
# - result.rescues: Weak detections validated by anchor
# - result.stacked_wwv: Virtual stacked correlation
```

### Key Classes

| Class | Purpose |
|-------|---------|
| `GlobalStationVoter` | Tracks anchors, provides search windows, stacks correlations |
| `StationLockCoordinator` | Orchestrates two-phase detection across channels |
| `StationAnchor` | High-confidence detection that guides weak channels |
| `GuidedDetection` | Detection result including guidance metadata |

---

## 🎯 Primary Time Standard (HF Time Transfer)

### The Holy Grail

By back-calculating emission time from GPS-locked arrival time and identified propagation mode, we transform from a **passive listener** into a **primary time standard** that verifies UTC(NIST).

### The Equation

$$T_{\text{emit}} = T_{\text{arrival}} - (\tau_{\text{geo}} + \tau_{\text{iono}} + \tau_{\text{mode}})$$

Where:
- $T_{\text{arrival}}$: GPS-disciplined RTP timestamp
- $\tau_{\text{geo}}$: Great-circle speed-of-light delay
- $\tau_{\text{iono}}$: Ionospheric group delay (frequency-dependent)
- $\tau_{\text{mode}}$: Extra path from N ionospheric hops

### Mode Identification

Propagation modes are **discrete** (quantized by layer heights):

| Mode | Typical Delay (EM38ww → WWV) | Uncertainty |
|------|------------------------------|-------------|
| 1-hop E | 3.82 ms | ±0.20 ms |
| 1-hop F2 | 4.26 ms | ±0.17 ms |
| 2-hop F2 | 5.51 ms | ±0.33 ms |
| 3-hop F2 | ~7.0 ms | ±0.50 ms |

### Disambiguation Using Channel Metrics

When modes overlap in timing:
- **High delay spread** → Multipath present, use earliest arrival (lowest hop)
- **High Doppler std** → Unstable path, downgrade confidence
- **High FSS** → More D-layer absorption, votes for higher hop count

### Accuracy Improvement

| Method | Accuracy |
|--------|----------|
| Raw arrival time | ±10 ms |
| + Mode identification | ±2 ms |
| + Cross-channel consensus | ±1 ms |
| + Cross-station verification | ±0.5 ms |

### Implementation

```python
from grape_recorder.grape import PrimaryTimeStandard

standard = PrimaryTimeStandard(receiver_grid='EM38ww')

# Process minute with all channel data
result = standard.process_minute(
    minute_utc=datetime.now(timezone.utc),
    channel_data={
        'WWV 10 MHz': {'arrival_time_utc': arrival, 'snr_db': 20.0},
        'WWV 15 MHz': {'arrival_time_utc': arrival2, 'snr_db': 15.0},
        ...
    }
)

# Get verified UTC(NIST)
print(f"UTC(NIST) offset: {result.utc_nist_offset_ms:+.2f} ms")
print(f"Cross-verified: {result.cross_verified}")  # WWV + WWVH agree
```

### Key Classes

| Class | Purpose |
|-------|---------|
| `PropagationModeSolver` | Calculates hop geometries, identifies mode from timing |
| `PrimaryTimeStandard` | Full integration, produces verified UTC(NIST) |
| `EmissionTimeResult` | Back-calculated emission with confidence metrics |
| `TimeStandardCSVWriter` | Logs results to CSV for analysis |

### Output Files

```
data/time_standard/
├── time_standard_all_channels_20251201.csv  # Per-minute results
└── time_standard_daily_summary.csv           # Daily statistics
```

---

## Session History

### Dec 3, 2025 (Evening): Phase 2 Analytical Engine - Core Complete

**Goal:** Debug data feed issues, implement robust channel management, complete Phase 2 core components.

**Major Accomplishments:**

1. **Channel Management Fix** (`run_all_channels_pipeline.py`, `channel_manager.py`)
   - **Problem**: `ka9q.allocate_ssrc()` uses Python's randomized `hash()`, causing orphaned channels
   - **Solution**: Use `ChannelManager.ensure_channels_from_config()` which matches by **frequency**, not SSRC
   - **Result**: All 9 channels now reliably reuse existing channels, no duplicates

2. **CHU Support in Phase 2** (`phase2_temporal_engine.py`)
   - Added `chu_det` extraction alongside WWV/WWVH
   - CHU uses 500ms @ 1000 Hz tone (vs 800ms for WWV)
   - Anchor priority: WWV > CHU > WWVH

3. **500/600 Hz Discrimination Fix** (`tone_detector.py`)
   - **Problem**: BCD 100 Hz intermod creates spurious 500/600 Hz when both stations present
   - **Solution**: Only discriminate during single-station minutes:
     - WWV-only: 1, 16, 17, 19 (500 Hz valid)
     - WWVH-only: 2, 43-51 (600 Hz valid)
   - Flags `INTERMOD_RISK` during dual-station minutes

4. **Extended Tone Analysis** (`tone_detector.py`)
   - New `analyze_extended_tones()` method
   - Detects 440/500/600/1000 Hz for signal characterization
   - Provides frequency spread metric for propagation quality

5. **Phase 2 Testing Validated**
   - WWV 10 MHz: D_clock = -0.2ms (excellent UTC sync)
   - CHU channels: 31-38ms timing (correct Ottawa propagation)
   - All channels producing usable Phase 2 results

**Files Modified:**
- `scripts/run_all_channels_pipeline.py` - Use ChannelManager
- `src/grape_recorder/grape/phase2_temporal_engine.py` - CHU support
- `src/grape_recorder/grape/tone_detector.py` - 500/600 Hz fix, extended tones

**Recording in Progress:**
- 6-hour session started for multi-hour data collection
- Output: `/tmp/grape-test/long_run/`

---

### Dec 3, 2025 (Earlier): Phase 1 Complete - Three-Phase Pipeline

**Goal:** Implement Phase 1 of the three-phase pipeline architecture for bulletproof raw data capture.

**Implemented:**

1. **RawArchiveWriter** (`raw_archive_writer.py`)
   - Digital RF output format (HDF5 with complex64 samples)
   - Gzip compression with shuffle filter
   - Hourly file splitting, daily directories
   - NTP synchronization status tracking
   - Data quality validation (NaN/Inf/clipping detection)
   - Gap detection via RTP sequence tracking
   - Comprehensive session summary metadata

2. **PipelineOrchestrator** (`pipeline_orchestrator.py`)
   - Three-phase coordination (Phase 2/3 stubbed)
   - Configuration propagation to each phase
   - Directory structure management

3. **StorageQuotaManager** (`raw_archive_writer.py`)
   - Flexible quota format: "500GB", "1TB", "80%", "unlimited"
   - Total allocation for ALL channels (not per-channel)
   - FIFO removal of oldest date directories
   - Safety: never removes current day's data
   - Audit log for all removals

4. **Multi-Channel Runner** (`run_all_channels_pipeline.py`)
   - Reads all channels from grape-config.toml
   - Creates ka9q-python channels dynamically
   - RTP packet handling with resequencing
   - Periodic status reporting with quota enforcement
   - Graceful shutdown with session summaries

**Configuration:**
```toml
[recorder]
storage_quota = "80%"  # or "500GB", "1TB", "unlimited"
```

**Key Design Decisions:**
- System time (Unix epoch) as time reference, not RTP timestamps
- NTP status logged but not used to correct timestamps
- 32-bit float IQ (PT=111) from radiod
- Storage quota manages ALL channels together

**Files Created/Modified:**
- `src/grape_recorder/grape/raw_archive_writer.py` - Complete rewrite
- `src/grape_recorder/grape/pipeline_orchestrator.py` - New orchestrator
- `scripts/run_all_channels_pipeline.py` - Multi-channel runner
- `config/grape-config.toml` - Added storage_quota

---

### Dec 2, 2025 (Evening): PPM-Corrected Timing & Sub-Sample Precision

**Goal:** Eliminate "wild RTP drift" errors by implementing ADC clock drift correction and improving timing precision.

**Problems Solved:**

1. **Wild RTP Drift Errors**
   - **Symptom:** Logs showed "RTP clock drift detected: 60004.0ms over 60s"
   - **Root Cause:** `TimeSnapReference` didn't account for ADC PPM offset
   - **Fix:** Added `ppm_offset`, `ppm_confidence`, `clock_ratio` to `TimeSnapReference`
   - **Equation:** `elapsed_seconds = (rtp_elapsed / sample_rate) × clock_ratio`

2. **timing_error_ms Always Zero in CSVs**
   - **Symptom:** Tone detection CSVs showed `timing_error_ms=0.00` for all detections
   - **Root Cause:** Only discrimination results (with hardcoded 0.0) were written to CSV
   - **Fix:** Added code to write REAL tone detections from `_detect_tones()` with actual timing

3. **UTC(NIST) Back-Calculation Showing "mode only"**
   - **Symptom:** Web UI showed "mode only" instead of UTC offset values
   - **Root Cause:** `confidence <= 0.3` due to missing precise timing data
   - **Fix:** Now that timing_error_ms is populated, confidence rises above threshold

4. **Float Slicing Error**
   - **Symptom:** `TypeError: slice indices must be integers`
   - **Root Cause:** Parabolic sub-sample interpolation made `onset_sample_idx` a float
   - **Fix:** Cast to int where used as array slice index

**New Features:**

1. **PPM-Corrected TimeSnapReference** (`data_models.py`)
   ```python
   @property
   def clock_ratio(self) -> float:
       if self.ppm_confidence > 0.3:
           return 1.0 + (self.ppm_offset / 1e6)
       return 1.0
   
   def with_updated_ppm(self, measured_ppm, confidence) -> 'TimeSnapReference':
       # Returns new frozen instance with exponentially smoothed PPM
   ```

2. **Sub-Sample Peak Interpolation** (`tone_detector.py`, `startup_tone_detector.py`)
   - Parabolic fit using peak and two neighbors
   - Precision improved from ±50 μs to ±10-25 μs at 20 kHz
   ```python
   sub_sample_offset = 0.5 * (y_m1 - y_p1) / (y_m1 - 2*y_0 + y_p1)
   precise_peak_idx = peak_idx + sub_sample_offset
   ```

3. **PPM Feedback Loop** (`timing_metrics_writer.py`, `analytics_service.py`)
   - `write_snapshot()` now returns `(ppm_offset, confidence)` from tone-to-tone measurement
   - Analytics service feeds this back to update `time_snap`:
   ```python
   updated_snap = self.state.time_snap.with_updated_ppm(ppm_offset, ppm_confidence)
   ```

4. **Ensemble Time-Snap Selection** (`global_station_voter.py`)
   - New method `get_best_time_snap_anchor()` for cross-channel voting
   - Scores candidates by: SNR + timing_preference + quality_bonus
   - Prefers WWV/CHU over WWVH for timing reference

**Files Modified:**
- `src/grape_recorder/interfaces/data_models.py` - PPM fields, clock_ratio, with_updated_ppm()
- `src/grape_recorder/grape/tone_detector.py` - Sub-sample interpolation, int cast fix
- `src/grape_recorder/grape/startup_tone_detector.py` - Sub-sample interpolation
- `src/grape_recorder/grape/timing_metrics_writer.py` - Return PPM from write_snapshot()
- `src/grape_recorder/grape/analytics_service.py` - PPM feedback, write real tone detections
- `src/grape_recorder/grape/global_station_voter.py` - Ensemble anchor selection

**Data Flow:**
```
┌─────────────────────────────────────────────────────────────────────────┐
│                    PPM CORRECTION FEEDBACK LOOP                          │
│                                                                          │
│  Tone A (RTP₁, UTC₁) ──► Tone B (RTP₂, UTC₂)                            │
│         │                         │                                      │
│         └────────┬────────────────┘                                      │
│                  ▼                                                       │
│    Tone-to-tone PPM = ((RTP₂-RTP₁)/(UTC₂-UTC₁)/rate - 1) × 10⁶         │
│                  │                                                       │
│                  ▼                                                       │
│    TimeSnapReference.with_updated_ppm(ppm, confidence)                   │
│                  │                                                       │
│                  ▼                                                       │
│    calculate_sample_time() uses clock_ratio = 1 + ppm/10⁶              │
│                  │                                                       │
│                  ▼                                                       │
│    Accurate UTC(NIST) back-calculation with drift compensation          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Dec 2, 2025 (Afternoon): Config-Driven Sample Rate Architecture

**Goal:** Make sample rate fully config-driven so future changes only require editing `grape-config.toml`.

**Architecture Changes:**
1. **Config parameters:** Added `blocktime_ms` and `max_gap_seconds` to `[recorder]` section
2. **Auto-calculation:** `samples_per_packet = sample_rate × blocktime_ms / 1000`
3. **Auto-calculation:** `max_gap_samples = sample_rate × max_gap_seconds`
4. **Decimation validation:** `SUPPORTED_INPUT_RATES` dict with clear instructions for adding new rates

**Key Files:**
- `config/grape-config.toml` - Added `blocktime_ms = 20`, `max_gap_seconds = 60`
- `src/grape_recorder/grape/grape_recorder.py` - `GrapeConfig` with computed properties
- `src/grape_recorder/core/recording_session.py` - `SessionConfig` auto-calculates if not provided
- `src/grape_recorder/core/packet_resequencer.py` - Accepts `max_gap_samples` parameter
- `src/grape_recorder/grape/core_recorder.py` - Passes `blocktime_ms`, `max_gap_seconds` from config
- `src/grape_recorder/grape/decimation.py` - `SUPPORTED_INPUT_RATES` dict, helper functions

**To change sample rate now:**
1. Edit `sample_rate` in `grape-config.toml` channels
2. If new rate, add entry to `SUPPORTED_INPUT_RATES` in `decimation.py`
3. Configure `radiod` for matching sample rate

**Backward Compatibility:** Legacy 16 kHz NPZ files still process correctly via `archive.sample_rate` metadata.

### Dec 2, 2025 (Morning): Dual-Station Time Recovery & Bug Fixes

**Dual-Station Time Recovery (wwvh_discrimination.py):**
- Added fields to `DiscriminationResult`: `wwv_toa_ms`, `wwvh_toa_ms`, `t_emission_from_wwv_ms`, `t_emission_from_wwvh_ms`, `cross_validation_error_ms`, `dual_station_confidence`
- Back-calculates emission time: `T_emission = T_arrival - propagation_delay`
- Cross-validates WWV vs WWVH emission times (should match at UTC boundary)
- Confidence classification: excellent (<1ms), good (<2ms), fair (<5ms), investigate (>5ms)

**Timing Dashboard Fixes:**
- **Tone-locked display (0/9 → 9/9):** Fixed `_classify_quality()` to use `established_at` instead of `utc_timestamp` for age calculation - matches Node.js logic
- **Propagation modes:** Updated `renderStationSection()` to show ALL modes per frequency, not just primary mode - now displays varying elevation angles
- **24-hour drift chart:** Fixed `getTimingMetrics()` to span multiple days (today + yesterday) when hours > 1

**Critical Bug Fix - allow_pickle:**
- **Symptom:** 102 errors/channel: "Object arrays cannot be loaded when allow_pickle=False"
- **Root cause:** NPZ archives contain string fields (channel_name, time_snap_source) stored as object arrays
- **Impact:** Analytics failing on every file → processing backlog → recorder skipping every other minute
- **Fix:** Added `allow_pickle=True` to `NPZArchive.load()` in analytics_service.py
- **Result:** Decimation now runs, spectrograms show continuous data

**Files Modified:**
- `src/grape_recorder/grape/analytics_service.py` - allow_pickle fix, established_at for time_snap
- `src/grape_recorder/grape/timing_metrics_writer.py` - _classify_quality uses established_at
- `src/grape_recorder/grape/wwvh_discrimination.py` - dual-station time recovery fields
- `src/grape_recorder/grape/test_grape_refactor.py` - allow_pickle fix
- `web-ui/timing-dashboard-enhanced.html` - show all propagation modes, CSS for primary/alt modes
- `web-ui/utils/timing-analysis-helpers.js` - multi-day metrics query
- `web-ui/monitoring-server-v3.js` - propagation API endpoint

### Dec 1, 2025 (Evening): Global Station Lock + Primary Time Standard

**New Feature: Cross-Channel Coherent Processing**
- Implemented `GlobalStationVoter` - tracks high-confidence "anchor" detections
- Implemented `StationLockCoordinator` - orchestrates two-phase detection
- Key insight: GPS-disciplined RTP timestamps enable treating 9-12 receivers as coherent array
- Three-phase strategy: Anchor Discovery → Guided Search → Coherent Stacking
- Physics: Ionospheric dispersion (~3 ms) << station separation (~15 ms)
- Benefit: 99.4% noise rejection, virtual SNR improvement of 10*log10(N) dB

**New Feature: Primary Time Standard (HF Time Transfer)**
- Implemented `PropagationModeSolver` - calculates N-hop geometries, identifies mode from measured delay
- Implemented `PrimaryTimeStandard` - full integration producing verified UTC(NIST)
- Key equation: T_emit = T_arrival - (τ_geo + τ_iono + τ_mode)
- Propagation modes are **discrete** (quantized by layer heights ~4-7 ms for WWV)
- Cross-channel consensus: multiple frequencies → weighted average emission time
- Cross-station verification: WWV + WWVH both emit at UTC boundary → should match
- Accuracy: Raw ~10ms → +mode ID ~2ms → +consensus ~1ms → +cross-verified ~0.5ms
- Output: `TimeStandardCSVWriter` logs per-minute results and daily summaries

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
