# GRAPE Recorder - AI Context Document

**Last Updated:** 2025-12-02  
**Version:** 2.0.1  
**Status:** ✅ All systems operational. Dual-station time recovery, propagation modes display, timing dashboard fixes complete.

---

## 🚨 NEXT SESSION: Sample Rate Change (16 kHz → 20 kHz)

### Goal
Change the RTP stream sample rate from 16 kHz to 20 kHz to improve resolution for test signal analysis (channel sounding).

### Why 20 kHz?
- **Test signal bandwidth:** The WWV test signal (minutes :08 and :44) contains chirps and bursts designed for channel characterization
- **Nyquist margin:** 20 kHz allows clean capture of components up to 10 kHz (vs 8 kHz at 16 kHz)
- **Existing infrastructure:** radiod can provide any sample rate; only the receiver side needs updates

### Files Requiring Changes

| File | Changes Needed |
|------|----------------|
| `config/grape-config.toml` | Change `sample_rate = 16000` → `sample_rate = 20000` for each channel |
| `src/grape_recorder/grape/grape_recorder.py` | Update `sample_rate` default, verify `samples_per_packet` handling |
| `src/grape_recorder/core/recording_session.py` | Verify segment duration calculation: `20000 * 60 = 1,200,000` samples |
| `src/grape_recorder/core/packet_resequencer.py` | Update `MAX_GAP_SAMPLES = 1_200_000` (60s × 20 kHz) |
| `src/grape_recorder/grape/decimation.py` | Verify decimation factor: 20000 → 10 Hz = factor 2000 |
| `src/grape_recorder/grape/analytics_service.py` | Verify NPZ loading handles variable sample rates |
| `scripts/generate_spectrograms_from_10hz.py` | Should work unchanged (reads 10 Hz decimated) |
| `CONTEXT.md` | Update all references to 16 kHz |

### RTP Packet Structure at 20 kHz

```
Current (16 kHz):
- Packets per second: 50 (320 samples/packet)
- Samples per 60s segment: 960,000
- IQ samples per packet: 160 complex

New (20 kHz):
- Packets per second: 62.5 (320 samples/packet) or 50 (400 samples/packet)
- Samples per 60s segment: 1,200,000
- IQ samples per packet: depends on radiod configuration
```

### Verification Checklist
- [ ] radiod configured for 20 kHz on all 9 channels
- [ ] Archives contain 1,200,000 samples (60s × 20 kHz)
- [ ] Decimation produces correct 10 Hz output (600 samples/min)
- [ ] Spectrograms generate correctly
- [ ] Timing analysis still works (RTP timestamp math unchanged)
- [ ] Test signal analysis shows improved frequency resolution

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

### Dec 2, 2025: Dual-Station Time Recovery & Bug Fixes

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
