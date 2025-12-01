# Signal Recorder - AI Context Document

**Last Updated:** 2025-12-01  
**Version:** 2.0.0  
**Status:** Package restructuring COMPLETE. Next: SSRC abstraction with ka9q-python.

---

## 🔴 PRIORITY: SSRC Abstraction Coordination

### Goal

Remove SSRC from application/user concern. Users specify **what they want** (frequency, mode, sample rate), and the system handles SSRC internally across both ka9q-python and signal-recorder.

### Current State

| Layer | SSRC Handling | Status |
|-------|---------------|--------|
| **signal-recorder** | Stream API hides SSRC | ✅ Complete |
| **ka9q-python** | Still requires SSRC in some APIs | 🔴 Needs work |

### What Works Now (signal-recorder side)

```python
# SSRC-free API - apps specify content, not identifiers
from signal_recorder import subscribe_stream

stream = subscribe_stream(
    radiod="radiod.local",
    frequency_hz=10.0e6,
    preset="iq",
    sample_rate=16000
)
# System allocates SSRC internally, shares streams, manages lifecycle
```

### What Needs Work (ka9q-python side)

```python
# Current ka9q-python API still exposes SSRC
from ka9q import RadiodControl

control = RadiodControl("radiod.local")
control.create_channel(
    ssrc=20100,              # ← User must provide SSRC
    frequency_hz=10e6,
    preset="iq",
    samprate=16000
)
```

### Proposed ka9q-python Changes

```python
# Option A: SSRC-free create_channel (recommended)
control.create_channel(
    frequency_hz=10e6,
    preset="iq", 
    samprate=16000
)  # Returns allocated SSRC

# Option B: Auto-allocate with deterministic hash
control.create_channel(
    frequency_hz=10e6,
    preset="iq",
    samprate=16000,
    ssrc="auto"  # System generates from content hash
)
```

### Coordination Points

1. **SSRC allocation strategy**: Should match between ka9q-python and signal-recorder
   - Current signal-recorder approach: `hash(freq_khz, preset, rate) % 65000 + 256`
   - ka9q-python needs compatible scheme

2. **Discovery API**: ka9q-python's `discover_channels()` returns SSRC - should also return content spec
   - Current: `{ssrc: 20100, frequency: 10000000, ...}`
   - Proposed: `{ssrc: 20100, frequency: 10000000, preset: "iq", sample_rate: 16000, ...}`

3. **Stream matching**: When app requests a stream, both layers need to find existing compatible streams
   - signal-recorder: `StreamManager.find_compatible(spec)` ✅ implemented
   - ka9q-python: needs equivalent in discovery/control

### Files to Reference

| File | Purpose |
|------|---------|
| `src/signal_recorder/stream/stream_manager.py` | SSRC allocation logic |
| `src/signal_recorder/stream/stream_spec.py` | Content-based stream identity |
| `ka9q-python/ka9q/control.py` | Channel creation (needs changes) |
| `ka9q-python/ka9q/discovery.py` | Channel discovery |

---

## ✅ COMPLETE: Package Restructuring (v2.0.0)

### New Package Structure

```
src/signal_recorder/
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
│   ├── analytics_service.py # Discrimination, decimation
│   ├── core_recorder.py     # GRAPE orchestration
│   ├── wwvh_discrimination.py
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
├── paths.py                 # Path utilities
└── ... (shared utilities)
```

### Import Patterns

```python
# Backward compatible (old imports still work)
from signal_recorder import GrapeRecorder, WsprRecorder, subscribe_stream

# New explicit imports (preferred)
from signal_recorder.core import RecordingSession, RTPReceiver, PacketResequencer
from signal_recorder.stream import subscribe_stream, StreamManager
from signal_recorder.grape import GrapeRecorder, AnalyticsService, WWVHDiscriminator
from signal_recorder.wspr import WsprRecorder, WsprWAVWriter
```

---

## Architecture: Three-Layer Stack

```
┌─────────────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER (grape/, wspr/, future apps)                         │
│  - Implements SegmentWriter for app-specific storage                   │
│  - May derive payload timing (e.g., GRAPE tone detection)              │
│  - Domain-specific processing                                           │
├─────────────────────────────────────────────────────────────────────────┤
│  Examples:                                                               │
│  • GrapeRecorder → GrapeNPZWriter → .npz (complex IQ + time_snap)      │
│  • WsprRecorder → WsprWAVWriter → .wav (16-bit mono @ 12kHz)           │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ Delivers: payload + transport timing + quality metadata
┌─────────────────────────────────────────────────────────────────────────┐
│  DELIVERY LAYER (core/, stream/)                                        │
│  - Stream API: SSRC hidden from apps                                   │
│  - RecordingSession: segmentation, boundary alignment                  │
│  - PacketResequencer: ordering, gap detection/filling                  │
│  - RTPReceiver: multicast reception, SSRC demux                        │
├─────────────────────────────────────────────────────────────────────────┤
│  Key Principle: PASSES THROUGH transport timing unchanged              │
│  ADDS: quality metadata (gap counts, completeness, resequence stats)   │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ Provides: RTP packets + GPS-quality wallclock
┌─────────────────────────────────────────────────────────────────────────┐
│  TRANSPORT LAYER (ka9q-python + radiod)                                 │
│  - SDR capture with GPS timing (GPS_TIME/RTP_TIMESNAP)                 │
│  - RTP multicast delivery                                               │
│  - Channel control (create/delete/tune)                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Stream API Reference

### High-Level Functions

```python
from signal_recorder import (
    subscribe_stream,      # Main entry point - get a stream handle
    subscribe_iq,          # Convenience: IQ mode
    subscribe_usb,         # Convenience: USB mode  
    subscribe_am,          # Convenience: AM mode
    subscribe_batch,       # Multiple streams, same parameters
    discover_streams,      # See existing streams
    find_stream,           # Find compatible existing stream
    get_manager,           # Access StreamManager singleton
    close_all,             # Clean shutdown
)
```

### Usage Examples

```python
# Basic usage - SSRC allocated automatically
stream = subscribe_stream(
    radiod="radiod.local",
    frequency_hz=10.0e6,
    preset="iq",
    sample_rate=16000
)
print(f"Listening on {stream.multicast_address}:{stream.port}")
print(f"SSRC (internal): {stream.ssrc}")

# Stream sharing - same spec = same stream
stream1 = subscribe_iq(radiod, 10e6, sample_rate=16000)
stream2 = subscribe_iq(radiod, 10e6, sample_rate=16000)
assert stream1.ssrc == stream2.ssrc  # Shared!

# Batch subscription
specs = [
    StreamSpec(frequency_hz=10e6, preset="iq", sample_rate=16000),
    StreamSpec(frequency_hz=15e6, preset="iq", sample_rate=16000),
]
streams = subscribe_batch(radiod, specs)
```

### SegmentWriter Protocol

Applications implement this to receive segmented data:

```python
class SegmentWriter(Protocol):
    def start_segment(self, segment_info: SegmentInfo, metadata: Dict) -> None:
        """Called when new segment begins"""
        
    def write_samples(self, samples: np.ndarray, rtp_timestamp: int,
                      gap_info: Optional[GapInfo] = None) -> None:
        """Called for each batch of samples"""
        
    def finish_segment(self, segment_info: SegmentInfo) -> Optional[Any]:
        """Called when segment completes, returns result (e.g., file path)"""
```

---

## Key Data Structures

### StreamSpec (content-based identity)

```python
@dataclass(frozen=True)
class StreamSpec:
    frequency_hz: float      # Center frequency
    preset: str              # "iq", "usb", "am", etc.
    sample_rate: int         # Samples per second
    
    def ssrc_hash(self) -> int:
        """Deterministic SSRC from content"""
        freq_khz = int(self.frequency_hz / 1000)
        return (hash((freq_khz, self.preset, self.sample_rate)) % 65000) + 256
```

### SessionConfig

```python
@dataclass
class SessionConfig:
    ssrc: int
    multicast_address: str
    port: int
    sample_rate: int
    samples_per_packet: int      # 120 for IQ, 240 for audio
    segment_duration_sec: float  # 60.0 for GRAPE, 120.0 for WSPR
    align_to_boundary: bool      # Wait for cycle alignment
```

### GapInfo

```python
@dataclass
class GapInfo:
    sequence_start: int      # First missing sequence number
    sequence_end: int        # Last missing sequence number
    gap_samples: int         # Samples filled with zeros
    rtp_timestamp_gap: int   # RTP timestamp discontinuity
```

---

## Timing Architecture

### Two Layers of Timing (Cleanly Separated)

| Layer | Source | Purpose | Precision |
|-------|--------|---------|-----------|
| **Transport** | radiod GPS_TIME/RTP_TIMESNAP | When SDR sampled data | ~1ms |
| **Payload** | App-specific (WWV tones) | Content timing markers | Sub-ms |

### Transport Timing (Always Available)

```python
from ka9q import rtp_to_wallclock

# Every RTP packet carries GPS-quality wallclock
wallclock = rtp_to_wallclock(rtp_timestamp, sample_rate, rtp_header)
```

### Payload Timing (App-Specific)

GRAPE derives sub-ms `time_snap` from WWV/CHU tone detection.
Other apps (WSPR, CODAR) may only need transport timing.

---

## Application-Specific Notes

### GRAPE

- **Segment**: 60 seconds, minute-aligned
- **Output**: NPZ with complex IQ + time_snap metadata
- **Startup phase**: Buffers samples for tone detection
- **Sample rate**: 16,000 Hz

### WSPR

- **Segment**: 120 seconds, even-minute aligned
- **Output**: 16-bit mono WAV @ 12 kHz
- **No startup phase**: Direct recording
- **Boundary alignment**: `align_to_boundary=True`

---

## File Reference (Updated for v2.0.0)

### Core Infrastructure (`core/`)

| File | Purpose |
|------|---------|
| `rtp_receiver.py` | Multi-SSRC multicast reception |
| `recording_session.py` | Segmentation, SegmentWriter dispatch |
| `packet_resequencer.py` | Ordering, gap detection |

### Stream API (`stream/`)

| File | Purpose |
|------|---------|
| `stream_api.py` | `subscribe_stream()` and conveniences |
| `stream_manager.py` | SSRC allocation, lifecycle, sharing |
| `stream_spec.py` | Content-based stream identity |
| `stream_handle.py` | Opaque handle returned to apps |

### GRAPE Application (`grape/`)

| File | Purpose |
|------|---------|
| `grape_recorder.py` | Two-phase recorder |
| `grape_npz_writer.py` | SegmentWriter → NPZ |
| `core_recorder.py` | GRAPE orchestration |
| `analytics_service.py` | Discrimination, decimation |
| `wwvh_discrimination.py` | 12 voting methods |
| `startup_tone_detector.py` | time_snap establishment |
| `tone_detector.py` | WWV/WWVH/CHU tone detection |

### WSPR Application (`wspr/`)

| File | Purpose |
|------|---------|
| `wspr_recorder.py` | Simple recorder |
| `wspr_wav_writer.py` | SegmentWriter → WAV |

---

## Next Session: SSRC Abstraction in ka9q-python

### Proposed Changes

1. **`ka9q/control.py`**: Add SSRC-free `create_channel()` variant
2. **`ka9q/discovery.py`**: Include content spec in discovery results
3. **Shared SSRC allocation**: Use same hash algorithm as signal-recorder
4. **Documentation**: Update ka9q-python docs for SSRC-free usage

### Testing Plan

```bash
# Test signal-recorder Stream API (already works)
python3 examples/simple_stream_demo.py

# After ka9q-python changes:
python3 -c "
from ka9q import RadiodControl
control = RadiodControl('radiod.local')
# New SSRC-free API
ssrc = control.create_channel(frequency_hz=10e6, preset='iq', samprate=16000)
print(f'Allocated SSRC: {ssrc}')
"
```

---

## Delivery Metadata Contract

What signal-recorder guarantees with each delivery:

```python
@dataclass
class DeliveryMetadata:
    # From radiod (passed through unchanged)
    wallclock_start: float       # GPS-quality timestamp
    wallclock_end: float
    frequency_hz: float
    sample_rate: int
    
    # From signal-recorder (added)
    samples_delivered: int
    samples_expected: int
    gap_count: int
    gap_samples: int
    completeness: float          # samples_delivered / samples_expected
    packets_resequenced: int
```

---

## Future Work: Gap Analysis API

A unified gap event API remains a potential enhancement:

```python
@dataclass
class GapEvent:
    timestamp: float           # When gap detected
    channel: str               # Channel name
    layer: str                 # CORE | RADIOD | APPLICATION
    gap_type: str              # RTP_PACKET_LOSS, RADIOD_DOWN, etc.
    duration_samples: int
    severity: str              # INFO | WARNING | ERROR | CRITICAL

# API endpoints (not yet implemented)
# GET /api/v1/channels/{channel}/gaps/{date}
# GET /api/v1/gaps/summary/{date}
```

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

## Service Control

```bash
# All services
./scripts/grape-all.sh -start|-stop|-status

# Individual services
./scripts/grape-core.sh -start       # Core recorder
./scripts/grape-analytics.sh -start  # Analytics (9 channels)
./scripts/grape-ui.sh -start         # Web UI (port 3000)
```

---

## Session History

### Dec 1, 2025: Package Restructuring (v2.0.0)
- **Reorganized into `core/`, `stream/`, `grape/`, `wspr/` packages**
- Moved 22 GRAPE-specific files to `grape/`
- Moved 4 stream API files to `stream/`
- Moved 3 core infrastructure files to `core/`
- Updated all imports for new structure
- Backward compatibility via re-exports in main `__init__.py`
- Combined power + spectrogram chart (matplotlib 2-panel)
- Fixed spectrogram 24-hour coverage issue

### Nov 30, 2025: Stream API + WSPR Demo
- **Stream API**: `subscribe_stream()` hides SSRC from apps
- **WSPR demo**: First successful decode with new infrastructure
- **GRAPE refactor**: GrapeRecorder + GrapeNPZWriter using SegmentWriter
- **ka9q-python 2.5.0**: `pass_all_packets` mode, GPS timing

### Nov 29, 2025: Discrimination Enhancements
- Extended to 12 voting methods + 12 cross-validation checks
- Test signal channel sounding (FSS, noise, burst, chirps)

---

## Critical Bug History

Three bugs corrupted all data before Oct 30, 2025:
1. **Byte Order:** `np.int16` (little) → `'>i2'` (big-endian network order)
2. **I/Q Phase:** `I + jQ` → `Q + jI` (carrier centered at 0 Hz)
3. **Payload Offset:** Hardcoded `12` → calculate from RTP header

---

## GRAPE Discrimination System (12 Methods)

| Vote | Method | Weight |
|------|--------|--------|
| 0 | Test Signal | 15 |
| 1 | 440 Hz Station ID | 10 |
| 2 | BCD Amplitude | 2-10 |
| 3 | 1000/1200 Hz Power | 1-10 |
| 4 | Tick SNR | 5 |
| 5 | 500/600 Hz | 10-15 |
| 6 | Doppler Stability | 2 |
| 7 | Timing Coherence | 3 |
| 8 | Harmonic Ratio | 1.5 |
| 9 | FSS Path | 2 |
| 10 | Noise Coherence | flag |
| 11 | Burst ToA | validation |
| 12 | Spreading Factor | flag |

---

## Data Pipeline (GRAPE)

```
ka9q-radio RTP → Core Recorder (16kHz NPZ) → Analytics Service
                                                    ↓
                                           Discrimination CSVs
                                                    ↓
                                           10 Hz Decimation → DRF → PSWS Upload
```
