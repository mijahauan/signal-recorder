# Signal Recorder - AI Context Document

**Last Updated:** 2025-12-01  
**Status:** Stream API v1.1.0 complete. Next: Debug spectrogram 24-hour coverage.

---

## 🎯 Next Session: Spectrogram 24-Hour Coverage Issue

### Problem

Spectrograms are **not filling the whole 24-hour graph**. The user expects spectrograms to show a full 24-hour day (00:00-23:59 UTC), but they appear incomplete.

### Possible Causes to Investigate

1. **Data gaps in 10 Hz decimated NPZ files**
   - Check: `analytics/{channel}/decimated/` for missing minute files
   - Files named: `YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz`
   - Each file = 1 minute of 10 Hz data (600 samples)

2. **Analytics service not processing all minutes**
   - Check: `scripts/grape-analytics.sh` service status
   - Look for errors in analytics processing logs
   - Gap in 16 kHz NPZ files → gap in decimated files

3. **Spectrogram generation reading wrong time range**
   - Script: `scripts/generate_spectrograms_from_10hz.py`
   - X-axis may only show actual data range, not full 24 hours
   - See: `docs/features/PARTIAL_DAY_SPECTROGRAM_FIX.md` for context

4. **Channel restart causing data loss**
   - radiod restart or channel recreation causes gaps
   - Check: core_recorder.py logs for channel recovery events

5. **DRF writer not keeping up**
   - Digital RF writes from decimated NPZ
   - Check: `drf_batch_writer.py` backlog

### Diagnostic Commands

```bash
# Count decimated files per channel for a specific date
ls -la analytics/WWV_10_MHz/decimated/20251201*_iq_10hz.npz | wc -l
# Expected: 1440 files (one per minute)

# Check for gaps in file timestamps
ls analytics/WWV_10_MHz/decimated/20251201*_iq_10hz.npz | head -20
ls analytics/WWV_10_MHz/decimated/20251201*_iq_10hz.npz | tail -20

# Check analytics service
./scripts/grape-analytics.sh -status

# Check for errors in logs
journalctl -u grape-analytics --since "00:00" | grep -i error

# Generate spectrogram for today
python3 scripts/generate_spectrograms_from_10hz.py --date 20251201 --channel "WWV 10 MHz"
```

### Key Files for Investigation

| File | Purpose |
|------|---------|
| `scripts/generate_spectrograms_from_10hz.py` | Main spectrogram generator |
| `src/signal_recorder/analytics_service.py` | Creates decimated NPZ files |
| `scripts/check_and_generate_spectrograms.py` | Checks/triggers generation |
| `docs/features/PARTIAL_DAY_SPECTROGRAM_FIX.md` | Previous partial-day fix |
| `docs/features/AUTOMATIC_SPECTROGRAM_GENERATION.md` | Generation system docs |

### Data Flow for Spectrograms

```
radiod RTP → core_recorder.py → 16 kHz NPZ (1-minute files)
                                     ↓
                            analytics_service.py
                                     ↓
                            10 Hz decimated NPZ
                                     ↓
                     generate_spectrograms_from_10hz.py
                                     ↓
                            PNG spectrograms
                                     ↓
                            Web UI display
```

**Any gap in the pipeline = gap in spectrogram**

### Questions to Answer

1. How many decimated files exist for the problem date?
2. What time range do the files cover?
3. Are there gaps between files?
4. Is the spectrogram script reading all files?
5. Is the X-axis set to show full 24 hours or just data range?

---

## ✅ Stream API Complete (Dec 1, 2025)

The robust multi-application API is now implemented. Applications specify **what they want** (frequency, preset, sample rate) and the system handles **SSRC allocation internally**.

### Key Design Decision: SSRC Hidden from Apps

**Why:** SSRC is just an internal index that radiod uses - applications shouldn't care about it.

**Before (manual SSRC):**
```python
# Old way - app had to know/manage SSRC
control.create_channel(ssrc=20100, frequency_hz=10e6, preset="iq", ...)
receiver.register_callback(ssrc=20100, callback=...)
```

**After (SSRC-free):**
```python
# New way - just say what you want
stream = subscribe_stream(
    radiod="radiod.local",
    frequency_hz=10.0e6,
    preset="iq",
    sample_rate=16000
)
# System allocates SSRC, shares existing streams, handles lifecycle
```

### New Files Created

| File | Purpose |
|------|---------|
| `stream_spec.py` | `StreamSpec` - content-based stream identity |
| `stream_handle.py` | `StreamHandle` - opaque handle apps receive |
| `stream_manager.py` | `StreamManager` - lifecycle, SSRC allocation, sharing |
| `stream_api.py` | `subscribe_stream()` - high-level entry point |
| `examples/simple_stream_demo.py` | Demo of new API |

### API Functions

```python
from signal_recorder import (
    subscribe_stream,      # Main entry point
    subscribe_iq,          # Convenience: IQ mode
    subscribe_usb,         # Convenience: USB mode  
    subscribe_am,          # Convenience: AM mode
    subscribe_batch,       # Multiple streams, same params
    discover_streams,      # See what exists
    find_stream,           # Find compatible existing stream
)
```

### Automatic Stream Sharing

Same `StreamSpec` (frequency + preset + sample_rate) = same stream:

```python
# Both get same underlying stream (efficient)
stream1 = subscribe_stream(radiod, frequency_hz=10e6, preset="iq", sample_rate=16000)
stream2 = subscribe_stream(radiod, frequency_hz=10e6, preset="iq", sample_rate=16000)
# stream1.multicast_address == stream2.multicast_address ✓
```

### Multi-App Coordination

Different apps, same frequency, different parameters = different streams:

```python
# GRAPE: IQ for Doppler analysis
grape = subscribe_stream(radiod, frequency_hz=10e6, preset="iq", sample_rate=16000)

# Audio monitor: AM for listening  
audio = subscribe_stream(radiod, frequency_hz=10e6, preset="am", sample_rate=12000)

# Different streams (different preset/rate), no collision
```

### Architecture (Updated)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              APPLICATION                                     │
│                                                                              │
│   stream = subscribe_stream(frequency_hz=10e6, preset="iq", ...)            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STREAM API (new)                                   │
│                                                                              │
│   StreamManager                                                              │
│   - SSRC allocation (internal, deterministic hash)                          │
│   - Stream sharing (same StreamSpec = same stream)                          │
│   - Discovery integration (find existing compatible streams)                │
│   - Reference counting (cleanup on release)                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RECORDING INFRASTRUCTURE (existing)                       │
│                                                                              │
│   RecordingSession → RTPReceiver → ka9q-python → radiod                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Next Steps

1. **Test with live radiod** - Run `examples/simple_stream_demo.py`
2. **Update GRAPE** to use new API (optional - current code still works)
3. **Update WSPR demo** to use new API
4. **Document** multi-app coordination patterns

---

## Previous: Key Learnings from WSPR Demo

1. **Payload Format Detection** - radiod sends different formats:
   - IQ mode (GRAPE): float32 interleaved I/Q → 120 complex samples/packet
   - USB/Audio mode (WSPR): float32 mono → 240 real samples/packet
   - Fixed by using `samples_per_packet` config to disambiguate

2. **Boundary Alignment** - WSPR requires exact 2-minute boundaries:
   - `align_to_boundary=True` with `segment_duration_sec=120.0`
   - Session waits until position-in-cycle < 2 seconds before starting

3. **Sample Rate Matching** - Session config must match radiod config:
   - WSPR: `samprate = 12000` in radiod, `sample_rate=12000` in session
   - GRAPE: `samprate = 16000` in radiod, `sample_rate=16000` in session

---

## ✅ WSPR Demo Complete & Validated (Nov 30)

The WSPR recorder demo was built to prove the pipeline works for applications beyond GRAPE.

### Result: First WSPR Decode

```
_usb -25 -0.7  10.140283  0  <...> EL87PT 37
```

- **Full 2-minute segment**: 1,440,000 samples (exactly 120.00 seconds)
- **Zero gaps**: Packet resequencing handled perfectly
- **wsprd decode**: Success on first properly-aligned recording

### Components Created

| Component | File | Description |
|-----------|------|-------------|
| **WsprWAVWriter** | `wspr_wav_writer.py` | SegmentWriter for 16-bit mono WAV @ 12 kHz |
| **WsprRecorder** | `wspr_recorder.py` | Simple recorder (no startup phase) |
| **WsprConfig** | `wspr_recorder.py` | Configuration dataclass |
| **wspr_demo.py** | `examples/wspr_demo.py` | Standalone demo script |

### Test Command (Working)

```bash
cd /home/wsprdaemon/signal-recorder
source venv/bin/activate

# Record 30m WSPR (must specify SSRC = freq in kHz)
python3 examples/wspr_demo.py \
    --frequency 10138700 --ssrc 10139 \
    --multicast 239.113.49.249 \
    --duration 250 --output wspr_test

# Decode with wsprd
./wsprd-x86-v27 -f 10.1387 wspr_test/*.wav
```

### WSPR vs GRAPE Comparison

| Aspect | GRAPE | WSPR |
|--------|-------|------|
| **Segment duration** | 60 seconds | 120 seconds |
| **Output format** | NPZ (complex IQ) | WAV (real audio) |
| **Sample rate** | 16,000 Hz | 12,000 Hz |
| **Payload format** | float32 IQ | float32 mono |
| **Startup phase** | Yes (tone detection) | No |
| **Boundary alignment** | Minute | Even 2-minute |

---

## ✅ GRAPE Refactor Complete (Nov 30 evening)

The GRAPE recorder has been refactored to use the new generic recording infrastructure.

### New Components Created

| Component | File | Description |
|-----------|------|-------------|
| **GrapeNPZWriter** | `grape_npz_writer.py` | Implements `SegmentWriter` protocol for NPZ output |
| **GrapeRecorder** | `grape_recorder.py` | Two-phase recorder (startup buffering → recording) |
| **GrapeConfig** | `grape_recorder.py` | Configuration dataclass for GRAPE |

### Architecture (Refactored)

```
┌─────────────────────────────────────────────────────────────────┐
│                    CoreRecorder (orchestration)                  │
│  - Channel management, health monitoring, NTP cache             │
├─────────────────────────────────────────────────────────────────┤
│                    GrapeRecorder (per-channel)                   │
│  - Phase 1: Startup buffering + tone detection                 │
│  - Phase 2: RecordingSession with GrapeNPZWriter               │
├─────────────────────────────────────────────────────────────────┤
│                    RecordingSession (generic)                    │
│  - RTP reception + PacketResequencer                            │
│  - Time-based segmentation (60s)                                │
│  - Transport timing (wallclock from radiod)                     │
├─────────────────────────────────────────────────────────────────┤
│                    GrapeNPZWriter                                │
│  - SegmentWriter implementation                                  │
│  - NPZ output with time_snap, gap tracking                      │
├─────────────────────────────────────────────────────────────────┤
│                    rtp_receiver.py + ka9q-python                 │
│  - Multi-SSRC demultiplexing                                     │
│  - RTP parsing, GPS timing                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Completed Infrastructure (Nov 30)

| Component | Status | Location |
|-----------|--------|----------|
| **ka9q-python 2.5.0** | ✅ Released | `venv/lib/python3.11/site-packages/ka9q/` |
| `pass_all_packets` mode | ✅ | `rtp_recorder.py` |
| GPS_TIME/RTP_TIMESNAP | ✅ | `discovery.py`, `control.py` |
| `rtp_to_wallclock()` | ✅ | `rtp_recorder.py` |
| **signal-recorder** | | `src/signal_recorder/` |
| `rtp_receiver.py` | ✅ Updated | Uses ka9q for parsing/timing |
| `recording_session.py` | ✅ New | Generic session manager |
| `test_recording_session.py` | ✅ Passing | Live radiod test |

### Architecture Layers (Current)

```
┌─────────────────────────────────────────────────────────────────┐
│              Application (GRAPE, WSPR, CODAR, etc.)             │
│  Implements SegmentWriter protocol for app-specific storage     │
├─────────────────────────────────────────────────────────────────┤
│                    RecordingSession (NEW)                        │
│  - RTP reception + PacketResequencer                            │
│  - Time-based segmentation                                       │
│  - Transport timing (wallclock from radiod)                      │
│  - Callbacks to SegmentWriter                                    │
├─────────────────────────────────────────────────────────────────┤
│                    rtp_receiver.py                               │
│  - Multi-SSRC demultiplexing (efficient single socket)          │
│  - Uses ka9q.parse_rtp_header()                                 │
│  - Uses ka9q.rtp_to_wallclock() for timing                      │
├─────────────────────────────────────────────────────────────────┤
│                    ka9q-python 2.5.0                             │
│  - RTP parsing, timing (GPS_TIME/RTP_TIMESNAP)                  │
│  - Channel control, discovery                                    │
│  - pass_all_packets mode for external resequencing              │
└─────────────────────────────────────────────────────────────────┘
```

### Timing Model (Important!)

**Two layers of timing are now cleanly separated:**

| Layer | Source | Purpose |
|-------|--------|---------|
| **Transport Timing** | radiod GPS_TIME/RTP_TIMESNAP | When SDR sampled the data |
| **Payload Timing** | App-specific (e.g., WWV tones) | Timing markers in content |

- `rtp_to_wallclock()` provides transport timing (always available if radiod sends it)
- GRAPE still needs payload timing (tone detection) for sub-ms accuracy
- Other apps (WSPR, CODAR) may only need transport timing

---

## Critical Bug History (for context)

Three bugs corrupted all data before Oct 30, 2025:
1. **Byte Order:** `np.int16` (little) → `'>i2'` (big-endian network order)
2. **I/Q Phase:** `I + jQ` → `Q + jI` (carrier centered at 0 Hz)
3. **Payload Offset:** Hardcoded `12` → calculate from RTP header

---

## Recent Session Work (Nov 30)

### Generic Recording Infrastructure (Complete)

- **ka9q-python 2.5.0**: Added `pass_all_packets` mode, GPS timing
- **rtp_receiver.py**: Now uses ka9q for parsing, adds wallclock to callbacks
- **recording_session.py**: New generic session manager with SegmentWriter protocol
- **test_recording_session.py**: Live test passes (2 segments, timing, no gaps)

### Key Design Decisions

1. **Keep rtp_receiver.py** - Multi-SSRC demux on single socket is more efficient
2. **Separate transport vs payload timing** - Clean architectural boundary
3. **SegmentWriter protocol** - Apps implement storage, RecordingSession handles flow
4. **Don't flush between segments** - Resequencer state persists for continuous streams

---

## Previous Session Work (Nov 29)

### Test Signal Channel Sounding (Complete)

The WWV/WWVH scientific test signal is now fully exploited:

| Segment | Metric | Vote |
|---------|--------|------|
| **Multi-tone** (13-23s) | FSS = 10·log₁₀((P₂ₖ+P₃ₖ)/(P₄ₖ+P₅ₖ)) | Vote 9 (+2.0 weight) |
| **White Noise** (10-12s, 37-39s) | N1 vs N2 coherence diff | Vote 10 (flag) |
| **Chirps** (24-32s) | Delay spread τ_D | Vote 7b, 12 |
| **Bursts** (34-36s) | High-precision ToA | Vote 11 (validation) |

### New Discrimination Features

- **Vote 9 (FSS):** Geographic path validator - WWV < 3.0 dB, WWVH > 5.0 dB
- **Vote 10 (Noise):** Transient interference detection via N1/N2 comparison
- **Vote 11 (Burst):** High-precision ToA cross-validation with delay spread
- **Vote 12 (Spreading Factor):** L = τ_D × f_D channel physics validation

---

## 1. 📡 Project Overview

**GRAPE Signal Recorder** captures WWV/WWVH/CHU time station signals via ka9q-radio SDR and:
1. Records 16 kHz IQ archives (NPZ format, 1-minute files)
2. Analyzes for WWV/WWVH discrimination (12 voting methods)
3. Decimates to 10 Hz for Digital RF format
4. Uploads to PSWS (HamSCI Personal Space Weather Station network)

### Data Pipeline
```
ka9q-radio RTP → Core Recorder (16kHz NPZ) → Analytics Service
                                                    ↓
                                           Discrimination CSVs
                                                    ↓
                                           10 Hz Decimation (NPZ)
                                                    ↓
                                           DRF Writer Service
                                                    ↓
                                           Digital RF (HDF5)
                                                    ↓
                                           SFTP Upload to PSWS
```

---

## 2. 🗂️ Key Production Files

### Core Recording (Focus for Next Session)
| File | Purpose |
|------|---------|
| `src/signal_recorder/grape_rtp_recorder.py` | RTP multicast reception |
| `src/signal_recorder/core_recorder.py` | Main recording orchestration |
| `src/signal_recorder/core_npz_writer.py` | 16 kHz NPZ with embedded metadata |
| `src/signal_recorder/packet_resequencer.py` | RTP packet ordering, gap detection |
| `src/signal_recorder/startup_tone_detector.py` | Time_snap establishment |
| `src/signal_recorder/channel_manager.py` | Channel configuration |

### Analytics
| File | Purpose |
|------|---------|
| `src/signal_recorder/analytics_service.py` | Discrimination, decimation, tone detection |
| `src/signal_recorder/wwvh_discrimination.py` | 12 voting methods, cross-validation |
| `src/signal_recorder/wwv_test_signal.py` | Test signal channel sounding |

### Upload System
| File | Purpose |
|------|---------|
| `src/signal_recorder/drf_batch_writer.py` | Multi-subchannel DRF creator |
| `scripts/daily-drf-upload.sh` | Daily upload orchestration |

---

## 3. 🌐 Station Configuration

| Parameter | Value |
|-----------|-------|
| **Callsign** | AC0G |
| **Grid Square** | EM38ww |
| **PSWS Station ID** | S000171 |
| **Location** | Kansas, USA (38.92°N, 92.17°W) |

### Channels (9 total)
| Frequency | Station | SSRC |
|-----------|---------|------|
| 2.5 MHz | WWV | 20025 |
| 3.33 MHz | CHU | 20333 |
| 5.0 MHz | WWV | 20050 |
| 7.85 MHz | CHU | 20785 |
| 10.0 MHz | WWV | 20100 |
| 14.67 MHz | CHU | 21467 |
| 15.0 MHz | WWV | 20150 |
| 20.0 MHz | WWV | 20200 |
| 25.0 MHz | WWV | 20250 |

---

## 4. 🔬 Discrimination System (12 Methods)

### Weighted Voting

| Vote | Method | Weight | Description |
|------|--------|--------|-------------|
| 0 | Test Signal | 15 | Minutes :08/:44 |
| 1 | 440 Hz Station ID | 10 | WWVH min 1, WWV min 2 |
| 2 | BCD Amplitude | 2-10 | 100 Hz time code |
| 3 | 1000/1200 Hz Power | 1-10 | Timing tone ratio |
| 4 | Tick SNR | 5 | 59-tick coherent |
| 5 | 500/600 Hz | 10-15 | Exclusive minutes |
| 6 | Doppler Stability | 2 | std ratio |
| 7 | Timing Coherence | 3 | Test + BCD ToA |
| 8 | Harmonic Ratio | 1.5 | 500→1000, 600→1200 |
| 9 | FSS Path | 2 | Geographic validator |
| 10 | Noise Coherence | flag | Transient detection |
| 11 | Burst ToA | validation | Timing cross-check |
| 12 | Spreading Factor | flag | L = τ_D × f_D |

### Cross-Validation Checks (12 total)

| # | Check | Token |
|---|-------|-------|
| 1-6 | Power, timing, geographic, ground truth | Various |
| 7 | Doppler-Power agreement | `doppler_power_agree` |
| 8 | Coherence quality | `high_coherence_boost` |
| 9 | Harmonic signature | `harmonic_signature_*` |
| 10 | FSS geographic | `TS_FSS_WWV/WWVH` |
| 11 | Noise transient | `transient_noise_event` |
| 12 | Spreading factor | `channel_overspread` |

---

## 5. 🔧 Service Control

```bash
# All services
./scripts/grape-all.sh -start|-stop|-status

# Individual services
./scripts/grape-core.sh -start       # Core recorder
./scripts/grape-analytics.sh -start  # Analytics (9 channels)
./scripts/grape-ui.sh -start         # Web UI (port 3000)
```

---

## 6. 📋 Session History

### Dec 1: Stream API Implementation (Morning)
- **`stream_spec.py`** - StreamSpec content-based identity (freq + preset + rate)
- **`stream_handle.py`** - StreamHandle opaque handle for apps
- **`stream_manager.py`** - SSRC allocation, stream sharing, lifecycle
- **`stream_api.py`** - `subscribe_stream()` high-level entry point
- **`docs/STREAM_API.md`** - Comprehensive documentation
- **`examples/simple_stream_demo.py`** - Demo of SSRC-free API
- Version bump to 1.1.0
- Key insight: SSRC is internal index, apps specify content (freq/preset/rate)

### Nov 30: GRAPE Refactor (Evening)
- **`grape_npz_writer.py`** - SegmentWriter implementation for GRAPE
- **`grape_recorder.py`** - Two-phase recorder (startup → recording)
- **`core_recorder.py`** updated to use GrapeRecorder
- **`test_grape_refactor.py`** - Live test script
- ChannelProcessor preserved but now deprecated

### Nov 30: Generic Recording Infrastructure (Afternoon)
- **ka9q-python 2.5.0** released with `pass_all_packets` mode
- GPS_TIME/RTP_TIMESNAP timing support
- `rtp_receiver.py` updated to use ka9q for parsing/timing
- **`recording_session.py`** - New generic session manager
- `SegmentWriter` protocol for app-specific storage
- Live test passing with radiod (segments, timing, no gaps)
- Branch: `feature/generic-rtp-recorder`

### Nov 29: Test Signal Channel Sounding
- FSS geographic validator (Vote 9)
- Noise coherence transient detection (Vote 10)
- Burst ToA cross-validation (Vote 11)
- Spreading Factor physics check (Vote 12)
- Extended to 12 voting methods + 12 cross-validation checks

### Nov 28: Discrimination Refinement
- 440 Hz coherent integration (~30 dB gain)
- Service scripts (`grape-*.sh`)
- 500/600 Hz weight boost (15 for exclusive minutes)
- Doppler stability vote (std ratio)

### Nov 27: DRF Upload & UI
- Multi-subchannel DRF writer
- Gap analysis page
- Upload tracker
