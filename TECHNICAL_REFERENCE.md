# GRAPE Signal Recorder - Technical Reference

**Quick reference for developers working on the GRAPE Signal Recorder.**

---

## Current Operational Configuration

**9 channels** monitoring 9 frequencies at 16 kHz IQ:
- **Shared frequencies (4):** 2.5, 5, 10, 15 MHz - WWV and WWVH both transmit
- **WWV-only (2):** 20, 25 MHz
- **CHU (3):** 3.33, 7.85, 14.67 MHz

**Data products generated**:
1. **16 kHz NPZ archives** - Complete scientific record with embedded metadata
2. **10 Hz decimated NPZ** - For Digital RF conversion
3. **Discrimination CSVs** - Per-method analysis (BCD, tones, ticks, 440Hz, test signals)
4. **Digital RF HDF5** - Wsprdaemon-compatible format for PSWS upload
5. **Timing metrics** - Time_snap quality, NTP drift tracking

**Goal**: Archive raw 16 kHz IQ, generate 10 Hz Digital RF with metadata for PSWS upload, provide WWV/WWVH discrimination on 4 shared frequencies.

---

## System Architecture

### Three-Service Design

```
Core Recorder (core_recorder.py → GrapeRecorder)
├─ Generic: RTPReceiver → RecordingSession → SegmentWriter
├─ GRAPE-specific: GrapeRecorder (two-phase: startup → recording)
├─ Startup tone detection (time_snap establishment)
├─ Gap detection & zero-filling
└─ NPZ archive writing (960,000 samples/minute @ 16 kHz)

Analytics Service (analytics_service.py) - per channel
├─ 12 voting methods (BCD, tones, ticks, 440Hz, test signals, FSS, etc.)
├─ Doppler estimation
├─ Decimation (16 kHz → 10 Hz)
└─ Timing metrics

DRF Batch Writer (drf_batch_writer.py)
├─ 10 Hz NPZ → Digital RF HDF5
├─ Multi-subchannel format (9 frequencies in ch0)
└─ SFTP upload to PSWS with trigger directories
```

**Why split?** Core stability vs analytics experimentation. Analytics can restart without data loss.

---

## Critical Design Principles

### 1. RTP Timestamp is Primary Reference

**Not wall clock.** System time is derived from RTP via time_snap.

```python
# Precise time reconstruction:
utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate
```

**Source**: Phil Karn's ka9q-radio design (pcmrecord.c)

### 2. Sample Count Integrity

**Invariant**: 16 kHz × 60 sec = 960,000 samples (exactly)

- Gaps filled with zeros
- Sample count never adjusted
- Discontinuities logged for provenance

### 3. Each Channel Has Independent RTP Clock

**Cannot share time_snap between channels.** Each ka9q-radio stream has different RTP origin.

```
WWV 5 MHz:   RTP 304,122,240
WWV 10 MHz:  RTP 302,700,560  ← 1.4M sample offset!
```

### 4. Timing Quality > Rejection

**Always upload, annotate quality.** No binary accept/reject.

- GPS_LOCKED (±1ms): time_snap from WWV/CHU
- NTP_SYNCED (±10ms): NTP fallback
- INTERPOLATED: Aged time_snap
- WALL_CLOCK (±sec): Unsynchronized

---

## NPZ Archive Format

**16 kHz Archive Fields** (self-contained scientific record):

```python
{
    # PRIMARY DATA
    "iq": complex64[960000],              # Gap-filled IQ samples (60 sec @ 16 kHz)
    
    # TIMING REFERENCE
    "rtp_timestamp": uint32,              # RTP timestamp of iq[0]
    "rtp_ssrc": uint32,                   # RTP stream identifier
    "sample_rate": int,                   # 16000 Hz
    
    # TIME_SNAP ANCHOR (embedded for self-contained files)
    "time_snap_rtp": uint32,              # RTP at timing anchor
    "time_snap_utc": float,               # UTC at timing anchor
    "time_snap_source": str,              # "wwv_startup", "ntp", etc.
    "time_snap_confidence": float,        # Confidence 0-1
    "time_snap_station": str,             # "WWV", "CHU", "NTP"
    
    # TONE POWERS (for discrimination - avoids re-detection)
    "tone_power_1000_hz_db": float,       # WWV/CHU marker tone
    "tone_power_1200_hz_db": float,       # WWVH marker tone
    "wwvh_differential_delay_ms": float,  # WWVH-WWV propagation delay
    
    # METADATA
    "frequency_hz": float,                # Center frequency
    "channel_name": str,                  # "WWV 10 MHz"
    "unix_timestamp": float,              # RTP-derived file timestamp
    "ntp_wall_clock_time": float,         # Wall clock at minute boundary
    "ntp_offset_ms": float,               # NTP offset from centralized cache
    
    # QUALITY INDICATORS
    "gaps_filled": int,                   # Total zero-filled samples
    "gaps_count": int,                    # Number of discontinuities
    "packets_received": int,              # Actual packets
    "packets_expected": int,              # Expected packets
    
    # GAP DETAILS (scientific provenance)
    "gap_rtp_timestamps": uint32[],       # RTP where each gap started
    "gap_sample_indices": uint32[],       # Sample index of each gap
    "gap_samples_filled": uint32[],       # Samples filled per gap
    "gap_packets_lost": uint32[]          # Packets lost per gap
}
```

**Why embedded time_snap?** Each file is self-contained - can reconstruct UTC without external state.

---

## RTP Packet Parsing (CRITICAL)

### Bug History (Oct 30, 2025)

Three sequential bugs corrupted all data before Oct 30 20:46 UTC:

#### Bug #1: Byte Order
```python
# WRONG:
samples = np.frombuffer(payload, dtype=np.int16)  # Little-endian

# CORRECT:
samples = np.frombuffer(payload, dtype='>i2')     # Big-endian (network order)
```

#### Bug #2: I/Q Phase
```python
# WRONG: I + jQ (carrier offset -500 Hz)
iq = samples[:, 0] + 1j * samples[:, 1]

# CORRECT: Q + jI (carrier centered at 0 Hz)
iq = samples[:, 1] + 1j * samples[:, 0]
```

#### Bug #3: Payload Offset
```python
# WRONG: Hardcoded
payload = data[12:]

# CORRECT: Calculate from header
payload_offset = 12 + (header.csrc_count * 4)
if header.extension:
    ext_length_words = struct.unpack('>HH', data[payload_offset:payload_offset+4])[1]
    payload_offset += 4 + (ext_length_words * 4)
payload = data[payload_offset:]
```

**Lesson**: Always parse RTP headers fully. Never hardcode offsets.

---

## Timing Architecture

### time_snap Mechanism

**Purpose**: Anchor RTP to UTC via WWV/CHU tone detection.

```
WWV 1000 Hz tone at :00.000
↓
Record RTP timestamp at detection
↓
Establish: time_snap_rtp = UTC minute boundary
↓
All samples: utc = time_snap_utc + (rtp - time_snap_rtp) / 16000
```

**Accuracy**: ±1ms when fresh, degrades ~1ms/hour

---

## WWV/WWVH Discrimination

### The 4 Shared Frequencies

On 2.5, 5, 10, and 15 MHz, both WWV (Fort Collins, CO) and WWVH (Kauai, HI) transmit simultaneously. Discrimination is required to separate these signals for ionospheric research.

### WWV/WWVH Tone Schedule

**440/500/600 Hz tones** provide ground truth discrimination during specific minutes:

| Minute | WWV Tone | WWVH Tone | Ground Truth |
|--------|----------|-----------|--------------|
| 1 | 600 Hz | **440 Hz** | WWVH 440 Hz ID |
| 2 | **440 Hz** | 600 Hz | WWV 440 Hz ID |
| 3-15 | 500/600 Hz | 500/600 Hz | (alternating) |
| 16, 17, 19 | 500/600 Hz | **silent** | WWV-only |
| 43-51 | **silent** | 500/600 Hz | WWVH-only |

**Ground truth minutes (14 per hour):**
- **WWV-only**: Minutes 1, 16, 17, 19 (WWVH silent or different tone)
- **WWVH-only**: Minutes 2, 43-51 (WWV silent or different tone)

**Timing tones (constant):**
- **1000 Hz**: WWV/CHU marker tone (first 0.8 sec of each minute)
- **1200 Hz**: WWVH marker tone (first 0.8 sec of each minute)

### 12 Voting Methods + 12 Cross-Validation Checks

Each method writes to its own daily CSV for independent reprocessing:

#### Voting Methods

| Vote | Method | Weight | Description |
|------|--------|--------|-------------|
| 0 | Test Signal | 15 | Minutes :08/:44 scientific modulation |
| 1 | 440 Hz Station ID | 10 | WWVH min 1, WWV min 2 |
| 2 | BCD Amplitude Ratio | 2-10 | 100 Hz time code dual-peak |
| 3 | 1000/1200 Hz Power | 1-10 | Timing tone ratio |
| 4 | Tick SNR Average | 5 | 59-tick coherent integration |
| 5 | 500/600 Hz Ground Truth | **10-15** | 12 exclusive min/hour |
| 6 | Doppler Stability | 2 | std ratio (independent of power) |
| 7 | Timing Coherence | 3 | Test + BCD ToA agreement |
| 8 | Harmonic Ratio | 1.5 | 500→1000 Hz, 600→1200 Hz ratios |
| 9 | FSS Path Signature | 2 | Frequency Selectivity Score |
| 10 | Noise Coherence | flag | Transient interference detection |
| 11 | Burst ToA | validation | High-precision timing cross-check |
| 12 | Spreading Factor | flag | Channel physics L = τ_D × f_D |

**Vote 9 (FSS Geographic Validator):**
```python
# FSS = 10*log10((P_2kHz + P_3kHz) / (P_4kHz + P_5kHz))
w_fss = 2.0
if scheduled_station == 'WWV' and fss < 3.0:  # Continental path
    wwv_score += w_fss
elif scheduled_station == 'WWVH' and fss > 5.0:  # Trans-oceanic path
    wwvh_score += w_fss
```

**Vote 12 (Spreading Factor):**
```python
# L = τ_D × f_D where f_D = 1/(π × τ_c)
if L > 1.0:  # Overspread channel
    disagreements.append('channel_overspread')
elif L < 0.05:  # Clean channel
    agreements.append('channel_underspread_clean')
```

#### Cross-Validation Checks (Phase 6)

| # | Check | Agreement Token | Effect |
|---|-------|-----------------|--------|
| 1 | Power vs Timing | `power_timing_agree` | +agreement |
| 2 | Per-tick voting | `tick_power_agree` | +agreement |
| 3 | Geographic delay | `geographic_timing_agree` | +agreement |
| 4 | 440 Hz ground truth | `440hz_ground_truth_agree` | +agreement |
| 5 | BCD correlation | `bcd_minute_validated` | +agreement |
| 6 | 500/600 Hz ground truth | `500_600hz_ground_truth_agree` | +agreement |
| 7 | Doppler-Power | `doppler_power_agree` | +agreement |
| 8 | Coherence quality | `high_coherence_boost` / `low_coherence_downgrade` | ± |
| 9 | Harmonic signature | `harmonic_signature_wwv/wwvh` | +agreement |
| 10 | FSS geographic | `TS_FSS_WWV` / `TS_FSS_WWVH` | +agreement |
| 11 | Noise transient | `transient_noise_event` | +disagreement |
| 12 | Spreading factor | `channel_overspread` / `channel_underspread_clean` | ± |

**Confidence Adjustment:**
- ≥2 agreements + 0 disagreements → HIGH
- ≥2 disagreements → MEDIUM
- More disagreements than agreements → LOW
- Low coherence (<0.3) → LOW (forced)
- Channel overspread → timing unreliable

### Timing Purpose

```
WWV (1000 Hz)  → time_snap (timing reference)
CHU (1000 Hz)  → time_snap (timing reference)
WWVH (1200 Hz) → Propagation study (science data)
```

**Differential delay** = WWVH - WWV arrival time difference (ionospheric path)

---

## File Paths: Python/JavaScript Sync

**Problem**: Dual-language system needs identical paths.

**Solution**: Centralized APIs

**Python** (`src/grape_recorder/paths.py`):
```python
class GRAPEPaths:
    def get_quality_csv_path(self, channel):
        return self.analytics_dir / channel / "quality" / f"{channel}_quality.csv"
```

**JavaScript** (`web-ui/grape-paths.js`):
```javascript
class GRAPEPaths {
    getQualityCSVPath(channel) {
        return path.join(this.analyticsDir, channel, 'quality', `${channel}_quality.csv`);
    }
}
```

**Validation**: `./scripts/validate-paths-sync.sh`

---

## Configuration

**File**: `config/grape-config.toml` (copy from `config/grape-config.toml.template`)

```toml
[station]
callsign = "W1ABC"
grid_square = "FN31pr"

[ka9q]
status_address = "myhost-hf-status.local"  # mDNS name from radiod config

[recorder]
mode = "test"                              # "test" or "production"
test_data_root = "/tmp/grape-test"
production_data_root = "/var/spool/grape-recorder"

[[recorder.channels]]
ssrc = 10000000
frequency_hz = 10000000
preset = "iq"
sample_rate = 16000
description = "WWV 10 MHz"
enabled = true
processor = "grape"
```

---

## Startup

**Beta Testing** (manual execution):
```bash
# Terminal 1: Core recorder
cd ~/grape-recorder
source venv/bin/activate
python -m grape_recorder.grape_recorder --config config/grape-config.toml

# Terminal 2: Web UI
cd ~/grape-recorder/web-ui
npm start
```

**Production** (post-beta): Will use systemd services in `systemd/` directory.

---

## Data Flow

```
ka9q-radio (radiod)
    ↓ RTP multicast (mDNS discovery via ka9q-python)
Core Recorder (grape_recorder.py)
    ↓ 16 kHz NPZ archives with embedded metadata
    ↓ {data_root}/archives/{channel}/
Analytics Service (per channel)
    ├→ Discrimination CSVs: analytics/{channel}/bcd_discrimination/
    ├→ Discrimination CSVs: analytics/{channel}/tone_detections/
    ├→ Discrimination CSVs: analytics/{channel}/tick_windows/
    ├→ Discrimination CSVs: analytics/{channel}/station_id_440hz/
    ├→ Discrimination CSVs: analytics/{channel}/test_signals/
    ├→ Doppler CSVs: analytics/{channel}/doppler/
    ├→ Timing metrics: analytics/{channel}/timing_metrics/
    ├→ Decimated NPZ: analytics/{channel}/decimated/
    └→ Final voting: analytics/{channel}/discrimination/
DRF Batch Writer
    ├→ Digital RF HDF5: digital_rf/{date}/{station}/
    └→ SFTP upload to PSWS with trigger directories
```

---

## Key Modules

### Core Infrastructure (`src/grape_recorder/core/`)
- `recording_session.py` - Generic RTP→segments session manager
- `rtp_receiver.py` - Multi-SSRC RTP demultiplexer
- `packet_resequencer.py` - RTP packet ordering & gap detection

### Stream API (`src/grape_recorder/stream/`)
- `stream_api.py` - `subscribe_stream()` and convenience functions
- `stream_manager.py` - SSRC allocation, lifecycle, stream sharing
- `stream_spec.py` - Content-based stream identity
- `stream_handle.py` - Opaque handle returned to applications

### GRAPE Application (`src/grape_recorder/grape/`)
- `grape_recorder.py` - Two-phase recorder (startup → recording)
- `grape_npz_writer.py` - SegmentWriter for NPZ output
- `core_recorder.py` - Top-level GRAPE orchestration
- `analytics_service.py` - NPZ watcher, 12-method processor
- `wwvh_discrimination.py` - 12 voting methods, cross-validation
- `tone_detector.py` - 1000/1200 Hz timing tones
- `startup_tone_detector.py` - Initial time_snap establishment
- `decimation.py` - 16 kHz → 10 Hz (3-stage FIR)
- `discrimination_csv_writers.py` - Per-method CSV output

### WSPR Application (`src/grape_recorder/wspr/`)
- `wspr_recorder.py` - Simple recorder for WSPR
- `wspr_wav_writer.py` - SegmentWriter for 16-bit WAV output

### DRF & Upload
- `drf_batch_writer.py` - 10 Hz NPZ → Digital RF HDF5
- Wsprdaemon-compatible multi-subchannel format

### Infrastructure
- `paths.py` - Centralized path management (GRAPEPaths API)
- `channel_manager.py` - Channel configuration

### Web UI (`web-ui/`)
- `monitoring-server-v3.js` - Express API server
- `grape-paths.js` - JavaScript path management (synced with Python)

---

## Dependencies

**Python** (installed via `pip install -e .`):
- `ka9q-python` - Interface to ka9q-radio (from github.com/mijahauan/ka9q-python)
- `numpy>=1.24.0` - Array operations
- `scipy>=1.10.0` - Signal processing, decimation
- `digital_rf>=2.6.0` - Digital RF HDF5 format
- `zeroconf` - mDNS discovery for radiod
- `toml` - Configuration parsing
- `soundfile` - Audio file I/O (compatibility)

**Node.js** (for web-ui):
- `express` - API server
- `ws` - WebSocket support
- See `web-ui/package.json` for full list

**Installation**:
```bash
cd ~/grape-recorder
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

---

## Testing

### Verify Installation
```bash
source venv/bin/activate
python3 -c "import digital_rf; print('Digital RF OK')"
python3 -c "from ka9q import discover_channels; print('ka9q-python OK')"
```

### Test Recorder
```bash
python -m grape_recorder.grape_recorder --config config/grape-config.toml
# Should see: channel connections, NPZ file writes
```

### Verify Output Files
```bash
ls /tmp/grape-test/archives/WWV_10_MHz/*.npz
# Should show timestamped NPZ files
```

---

## Debugging

### Check NPZ Contents
```bash
python3 -c "
import numpy as np
from pathlib import Path
f = sorted(Path('/tmp/grape-test/archives/WWV_10_MHz/').glob('*.npz'))[-1]
d = np.load(f, allow_pickle=True)
print(f'File: {f.name}')
print(f'Samples: {len(d[\"iq\"])}')
print(f'Gaps: {d[\"gaps_count\"]}')
print(f'Completeness: {100*(1 - d[\"gaps_filled\"]/len(d[\"iq\"])):.1f}%')
print(f'Time_snap source: {d[\"time_snap_source\"]}')
print(f'1000 Hz power: {d[\"tone_power_1000_hz_db\"]:.1f} dB')
"
```

### Check Web UI API
```bash
curl http://localhost:3000/api/v1/summary | jq
```

---

## Common Issues

### Issue: Cannot connect to radiod

**Symptom**: "Failed to discover channels" error

**Causes**:
1. radiod not running
2. mDNS name not resolving
3. Multicast network issue

**Fix**: 
```bash
# Check radiod is running
sudo systemctl status radiod@rx888

# Test mDNS resolution
avahi-resolve -n myhost-hf-status.local

# Test ka9q-python discovery
python3 -c "from ka9q import discover_channels; print(discover_channels('myhost-hf-status.local'))"
```

### Issue: High packet loss

**Symptom**: Completeness < 95%, many gaps

**Causes**:
1. Network congestion
2. CPU overload
3. radiod issues

**Fix**: Check network buffers, reduce channel count if needed:
```bash
sudo sysctl -w net.core.rmem_max=26214400
```

### Issue: Timing quality degraded

**Symptom**: time_snap_source shows "ntp" instead of "wwv_startup"

**Causes**:
1. Poor propagation (no WWV/CHU signal)
2. Startup tone detection failed

**Fix**: Normal during poor propagation. System falls back to NTP timing (±10ms vs ±1ms).

---

## Performance Targets

### Core Recorder
- CPU: <5% per channel
- Memory: ~100 MB total
- Disk write: ~2 MB/min per channel (compressed NPZ)
- Latency: <100 ms (RTP → disk)

### Analytics
- CPU: Variable (batch processing)
- Processing: Can lag behind real-time
- 6 discrimination methods per minute per channel

---

## Quality Metrics

### Timing Quality Levels
- **TONE_LOCKED** (±1ms): time_snap from WWV/CHU startup tone
- **NTP_SYNCED** (±10ms): NTP fallback
- **WALL_CLOCK** (±seconds): Unsynchronized

### Data Completeness
- Target: >99% samples received
- Gaps: Zero-filled, logged in NPZ metadata
- Packet loss: <1% healthy

---

## References

### Key Documents
- `ARCHITECTURE.md` - System design decisions
- `DIRECTORY_STRUCTURE.md` - Path conventions
- `CANONICAL_CONTRACTS.md` - API standards
- `INSTALLATION.md` - Setup guide

### External
- ka9q-radio: https://github.com/ka9q/ka9q-radio
- ka9q-python: https://github.com/mijahauan/ka9q-python
- Digital RF: MIT Haystack Observatory

---

**Version**: 3.1  
**Last Updated**: December 1, 2025  
**Purpose**: Technical reference for GRAPE Signal Recorder developers

**v2.0.0 Release (Dec 1, 2025):**
- **Package Restructure** - `core/`, `stream/`, `grape/`, `wspr/` packages
- **Stream API** - SSRC-free `subscribe_stream()` interface
- **ka9q-python 3.1.0** - Compatible SSRC allocation algorithm
- **WSPR Demo** - Multi-application pipeline validation

**Previous Changes (Nov 30, 2025):**
- **Generic Recording Infrastructure** - Protocol-based design for multi-app support
  - `RecordingSession` - Generic RTP→segments manager
  - `SegmentWriter` protocol - App-specific storage abstraction
  - Transport timing (radiod GPS_TIME) vs Payload timing (app-specific)
- **GRAPE Refactor** - Uses new infrastructure
  - `GrapeRecorder` - Two-phase startup/recording
  - `GrapeNPZWriter` - SegmentWriter implementation for NPZ
  - `ChannelProcessor` removed (deprecated)

**Previous Changes (Nov 29, 2025):**
- 12 voting methods (was 8) - added FSS, noise coherence, spreading factor
- 12 cross-validation checks (was 9)
- Test signal fully exploited as channel sounding instrument:
  - Frequency Selectivity Score (FSS) for geographic path validation
  - Dual noise segment comparison for transient detection
  - Chirp delay spread for multipath characterization
  - Spreading Factor L = τ_D × f_D for channel physics

**Previous Changes (Nov 28, 2025):**
- 8 voting methods (was 6)
- 9 cross-validation checks added
- 500/600 Hz weight boosted to 15 for exclusive minutes
- Doppler vote changed to std ratio (independent of power)
- Coherence quality check downgrades/boosts confidence
- Harmonic signature validation (500→1000, 600→1200 Hz)
