# GRAPE Signal Recorder - AI Context Document

**Last Updated:** 2025-11-29 (evening session)  
**Status:** Beta release ready - test signal channel sounding complete

---

## 🎯 Next Session Focus: Recording Architecture Deep Dive

The discrimination system is now complete with 12 voting methods and 12 cross-validation checks. The **next session should focus on the recording architecture** - understanding how RTP data flows from ka9q-radio through to NPZ archives.

### Key Areas to Explore

1. **RTP Reception & Resequencing**
   - `grape_rtp_recorder.py` - RTPReceiver class handles multicast reception
   - `packet_resequencer.py` - Handles out-of-order packets, gap detection
   - Critical: Big-endian byte order (`'>i2'`), Q+jI phase convention

2. **Core Recorder Architecture**
   - `core_recorder.py` - Main orchestration, channel management
   - `core_npz_writer.py` - NPZ archive creation with embedded metadata
   - Invariant: 960,000 samples/minute (exactly), gaps zero-filled

3. **Time_snap Mechanism**
   - `startup_tone_detector.py` - Initial RTP→UTC calibration via tone detection
   - Formula: `utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate`
   - Accuracy: ±1ms when fresh, degrades ~1ms/hour

4. **Channel Manager**
   - `channel_manager.py` - SSRC mapping, ka9q-radio discovery
   - Each channel has independent RTP clock (cannot share time_snap between channels)

### Recording Architecture Files

| File | Purpose | Key Classes |
|------|---------|-------------|
| `grape_rtp_recorder.py` | RTP multicast reception | `RTPReceiver` |
| `core_recorder.py` | Main recording loop | `GrapeRecorder` |
| `core_npz_writer.py` | NPZ with metadata | `NPZWriter` |
| `packet_resequencer.py` | Packet ordering | `PacketResequencer` |
| `startup_tone_detector.py` | Initial timing | `StartupToneDetector` |
| `channel_manager.py` | Channel config | `ChannelManager` |
| `radiod_health.py` | ka9q-radio status | `RadiodHealthChecker` |
| `session_tracker.py` | Session boundaries | `SessionBoundaryTracker` |

### Architecture Questions to Address

- How does RTP timestamp relate to sample index?
- What happens when packets arrive out of order?
- How are gaps detected and filled?
- How does time_snap calibration work?
- What metadata is embedded in each NPZ?
- How do multiple channels coordinate?

### Critical Bug History (for context)

Three bugs corrupted all data before Oct 30, 2025:
1. **Byte Order:** `np.int16` (little) → `'>i2'` (big-endian network order)
2. **I/Q Phase:** `I + jQ` → `Q + jI` (carrier centered at 0 Hz)
3. **Payload Offset:** Hardcoded `12` → calculate from RTP header

---

## Recent Session Work (Nov 29)

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

---

## 7. 🎯 Next Session: Recording Architecture

**Goal:** Understand and potentially optimize the RTP→NPZ recording pipeline.

**Files to Read:**
1. `grape_rtp_recorder.py` - Start here, understand RTPReceiver
2. `core_recorder.py` - Main orchestration
3. `packet_resequencer.py` - Gap detection logic
4. `core_npz_writer.py` - Metadata embedding

**Questions to Answer:**
1. What is the packet loss rate in practice?
2. How often do packets arrive out of order?
3. Is the resequencer buffer size optimal?
4. Can we improve time_snap accuracy?
5. Are there race conditions in multi-channel recording?
