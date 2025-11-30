# GRAPE Signal Recorder - AI Context Document

**Last Updated:** 2025-11-30 (afternoon session)  
**Status:** Generic recording infrastructure complete, GRAPE refactor pending

---

## 🎯 Next Session Focus: GRAPE Recorder Refactor

The generic recording infrastructure is now complete and tested. The **next session should refactor `core_recorder.py`** to use the new `RecordingSession` class.

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

## 🔧 GRAPE Refactor Plan

### Files to Create

1. **`grape_npz_writer.py`** - Implements `SegmentWriter` protocol
   ```python
   class GrapeNPZWriter(SegmentWriter):
       def start_segment(self, segment_info, metadata): ...
       def write_samples(self, samples, rtp_timestamp, gap_info): ...
       def finish_segment(self, segment_info) -> Path: ...
   ```

2. **`grape_recorder.py`** - Two-phase GRAPE recorder
   ```python
   class GrapeRecorder:
       # Phase 1: Startup (2 minutes)
       # - Buffer samples
       # - Tone detection for time_snap
       # - Uses raw RTPReceiver callbacks
       
       # Phase 2: Recording (after time_snap)
       # - Create RecordingSession with GrapeNPZWriter
       # - Periodic tone re-validation
   ```

### Refactoring Steps

1. **Extract NPZ writing logic** from `ChannelProcessor` → `GrapeNPZWriter`
2. **Create `GrapeRecorder`** wrapper with startup/recording phases
3. **Simplify `ChannelProcessor`** to use `RecordingSession` after startup
4. **Update `CoreRecorder`** to use new classes
5. **Test with live radiod** to verify NPZ output matches current

### Key GRAPE-Specific Logic to Preserve

| Component | Location | Purpose |
|-----------|----------|---------|
| Startup buffering | `ChannelProcessor.__init__` | 120s buffer for tone detection |
| Tone detection | `StartupToneDetector` | Minute boundary → time_snap |
| NPZ format | `CoreNPZWriter` | Metadata, gap records |
| Periodic validation | `ChannelProcessor` | Every 5 min tone check |

### Test Verification

After refactor, verify:
```bash
# Run recorder for 5 minutes
./scripts/grape-core.sh -start
sleep 300
./scripts/grape-core.sh -stop

# Check NPZ output
ls -la data/local/raw/*/
python3 -c "import numpy as np; d = np.load('data/local/raw/.../file.npz'); print(d.files)"
```

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

### Nov 30: Generic Recording Infrastructure
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
