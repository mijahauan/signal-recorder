# GRAPE Signal Recorder - Technical Reference

**Quick reference for developers. For full history see PROJECT_NARRATIVE.md**

---

## Current Operational Configuration

**18 input channels** monitoring **9 frequencies of interest**:
- 9× Wide bandwidth (16 kHz IQ) - WWV/CHU tone detection
- 9× Carrier channels (200 Hz IQ) - Direct Doppler observation

**Data products generated**:
1. **16 kHz wide NPZ** - Primary scientific record (KEEP)
2. **10 Hz decimated from 16 kHz** - High-quality timing (UPLOAD CANDIDATE)
3. **10 Hz decimated from 200 Hz** - Clean carrier (UPLOAD CANDIDATE)
4. **Tone detection records** - time_snap, gap analysis
5. **WWV/WWVH discrimination** - Differential delays (4 shared frequencies)

**Goal**: Archive wide NPZ, upload best 10 Hz product with metadata, provide WWV/WWVH discrimination data.

**See**: `OPERATIONAL_SUMMARY.md` for complete details.

---

## System Architecture (Current)

### Two-Service Design

```
Core Recorder (core_recorder.py)
├─ RTP reception & resequencing (18 channels)
├─ Gap detection & filling
└─ NPZ archive writing (960,000 or 12,000 samples/minute)

Analytics Service (analytics_service.py)
├─ Quality metrics
├─ Tone detection (time_snap) - wide channels only
├─ Decimation (16kHz → 10Hz or 200Hz → 10Hz)
└─ Digital RF writing (future)
```

**Why split?** Core stability vs analytics experimentation. Analytics bugs don't stop data collection.

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

**Critical fields** (scientific record):

```python
{
    "iq": complex64[960000],          # IQ samples
    "rtp_timestamp": int,              # CRITICAL: RTP of iq[0]
    "sample_rate": 16000,
    "gaps_filled": int,                # Zero-filled samples
    "gaps_count": int,                 # Number of discontinuities
    "packets_received": int,
    "packets_expected": int
}
```

**Why RTP timestamp?** Enables precise UTC reconstruction after time_snap.

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

### Carrier Channels: NTP Timing

**Problem**: 200 Hz bandwidth cannot capture 1000 Hz tones.

**Solution**: Use NTP_SYNCED (±10ms) for carrier channels.

**Rationale**: 
- ±10ms → <0.01 Hz frequency uncertainty
- Science goal: ±0.1 Hz Doppler → 10× margin
- Continuous data (no propagation fade gaps)

---

## Tone Detector Timing Bug (Nov 17, 2025)

**Bug**: 30-second offset in all detections.

```python
# WRONG: current_unix_time is buffer MIDDLE
onset_time = current_unix_time + (onset_sample_idx / self.sample_rate)

# CORRECT: onset_sample_idx relative to buffer START
onset_time = buffer_start_time + (onset_sample_idx / self.sample_rate)
```

**Symptoms**: ±29.5 sec errors (half of 60-sec buffer)

**Fix**: Use buffer_start_time as reference

**Lesson**: Always document buffer reference points (start vs middle vs end)

---

## Channel Types

### Wide Channels (16 kHz)

**Purpose**: Full WWV/CHU signal capture
- Sample rate: 16 kHz complex IQ
- Bandwidth: ±8 kHz
- Timing: TONE_LOCKED (GPS quality)
- Detections: WWV (1000 Hz), WWVH (1200 Hz), CHU (1000 Hz)

### Carrier Channels (200 Hz)

**Purpose**: Doppler analysis of 10 Hz carrier
- Sample rate: 200 Hz complex IQ (radiod minimum)
- Effective rate: ~98 Hz (49% packet reception)
- Bandwidth: ±100 Hz
- Timing: NTP_SYNCED (no tones)
- Science goal: ±0.1 Hz Doppler → ±3 km path resolution

---

## WWV/WWVH Purpose Separation

**Critical distinction**:

```
WWV (1000 Hz)  → TIME_SNAP (timing reference)
WWVH (1200 Hz) → PROPAGATION STUDY (science data)
CHU (1000 Hz)  → TIME_SNAP (timing reference)
```

**Code pattern**:
```python
for detection in results:
    if detection.use_for_time_snap:
        update_time_snap_reference(detection)  # WWV or CHU
    else:
        analyze_differential_delay(detection)   # WWVH propagation
```

**Differential delay** = WWV - WWVH (ionospheric path difference)

---

## File Paths: Python/JavaScript Sync

**Problem**: Dual-language system needs identical paths.

**Solution**: Centralized APIs

**Python** (`src/signal_recorder/paths.py`):
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

### Core Recorder

**File**: `config/core-recorder.toml`

```toml
[core]
mode = "production"
data_root = "/tmp/grape-test"

[ka9q]
multicast_address = "239.103.26.231"
status_address = "239.192.152.141"
port = 5004

[channels]
[[channels.channel]]
ssrc = 5000000
frequency_hz = 5000000
sample_rate = 16000
description = "WWV 5 MHz"
```

### Analytics Service

```toml
[analytics]
quality_enabled = true
tone_detection_enabled = true
decimation_enabled = true
digital_rf_enabled = true
```

---

## Startup

**Production**:
```bash
./start-dual-service.sh
```

Starts:
1. `core_recorder.py` - RTP → NPZ
2. `analytics_service.py` per channel - NPZ → products
3. `monitoring-server-v3.js` - Web UI

**Direct**:
```bash
./start-core-recorder-direct.sh
```

---

## Data Flow

```
ka9q-radio (radiod)
    ↓ RTP multicast
Core Recorder
    ↓ NPZ archives (16 kHz or 200 Hz)
    ↓ /tmp/grape-test/archives/{channel}/
Analytics Service
    ├→ Quality CSV: /tmp/grape-test/analytics/{channel}/quality/
    ├→ Tone detection → time_snap state
    ├→ Decimated NPZ: /tmp/grape-test/analytics/{channel}/decimated/
    ├→ Digital RF: /tmp/grape-test/analytics/{channel}/digital_rf/
    └→ Discrimination: /tmp/grape-test/analytics/{channel}/discrimination/
```

---

## Key Modules

### Core
- `core_recorder.py` - Main RTP → NPZ recorder
- `core_npz_writer.py` - NPZ file format
- `packet_resequencer.py` - RTP packet ordering & gap detection

### Analytics
- `analytics_service.py` - Main processor (watches NPZ files)
- `tone_detector.py` - WWV/CHU/WWVH detection
- `decimation.py` - 16kHz → 10Hz anti-aliasing
- `digital_rf_writer.py` - DRF HDF5 format

### Infrastructure
- `paths.py` - Path management (Python)
- `channel_manager.py` - Channel configuration
- `radiod_health.py` - ka9q-radio health monitoring

### Web UI
- `monitoring-server-v3.js` - Express server
- `grape-paths.js` - Path management (JavaScript)

---

## Dependencies

**Core** (minimal):
- numpy, scipy (signal processing)
- No analytics dependencies

**Analytics**:
- numpy, scipy (decimation)
- digital_rf (HDF5 writing)

**Both**:
- ka9q-python library (radiod control)
- toml (configuration)

**Installation**:
```bash
pip install -r requirements.txt
pip install -e /home/mjh/git/ka9q-python
```

---

## Testing

### Verify Imports
```bash
source venv/bin/activate
python3 -c "import signal_recorder; print('OK')"
```

### Test Core Recorder
```bash
./start-core-recorder-direct.sh
# Should see RTP packets → NPZ files
```

### Test Analytics
```bash
# Requires NPZ archives in data_root
ls /tmp/grape-test/archives/WWV_5_MHz/*.npz
python3 -m signal_recorder.analytics_service \
    --archive-dir /tmp/grape-test/archives/WWV_5_MHz \
    --output-dir /tmp/grape-test/analytics/WWV_5_MHz \
    --channel-name "WWV 5 MHz"
```

---

## Debugging

### Monitor Core Recorder
```bash
tail -f /tmp/grape-test/logs/core-recorder.log
```

### Monitor Analytics
```bash
tail -f /tmp/grape-test/logs/analytics-wwv5.log | grep -E '(time_snap|quality|tone)'
```

### Check time_snap Status
```bash
jq '.time_snap' /tmp/grape-test/state/analytics-wwv5.json
```

### Verify Data Quality
```bash
# Check recent NPZ
python3 -c "
import numpy as np
from pathlib import Path
f = sorted(Path('/tmp/grape-test/archives/WWV_5_MHz/').glob('*.npz'))[-1]
d = np.load(f)
print(f'Samples: {len(d[\"iq\"])}')
print(f'Non-zero: {np.count_nonzero(d[\"iq\"])}')
print(f'Gaps: {d[\"gaps_count\"]}')
print(f'Completeness: {100*(1 - d[\"gaps_filled\"]/len(d[\"iq\"])):.1f}%')
"
```

---

## Common Issues

### Issue: No time_snap established

**Symptom**: WALL_CLOCK or NTP_SYNCED timing, no GPS_LOCKED

**Causes**:
1. Poor propagation (no WWV tone detected)
2. Wrong channel (carrier channels use NTP, not tone)
3. Tone detector threshold too strict

**Fix**: Check logs for tone detection attempts. Adjust threshold if needed.

### Issue: High packet loss

**Symptom**: Completeness < 95%, many gaps

**Causes**:
1. Network congestion
2. CPU overload
3. radiod issues

**Fix**: Check `radiod` health, reduce channel count, check network.

### Issue: Timing jumps

**Symptom**: INTERPOLATED or WALL_CLOCK after GPS_LOCKED

**Causes**:
1. Propagation fade (time_snap expired)
2. System clock adjusted
3. NTP sync lost

**Fix**: Normal for propagation fades. Check NTP status: `chronyc tracking`

---

## Performance Targets

### Core Recorder
- CPU: <5% per channel
- Memory: ~100 MB per channel
- Disk write: ~2 MB/min (compressed NPZ)
- Latency: <100 ms (RTP → disk)

### Analytics
- CPU: 20-40% per channel (FFT heavy)
- Memory: ~500 MB per channel
- Processing: <2× real-time
- Can lag behind (batch processing)

---

## Scientific Quality Metrics

### Timing Quality
- GPS_LOCKED: >90% of time (good propagation)
- NTP_SYNCED: Continuous for carrier channels
- Time_snap accuracy: ±1ms

### Data Completeness
- Target: >95% samples received
- Gaps: Transparently logged
- Zero-filled: Maintains sample count

### Doppler Resolution
- Wide channels: Sub-Hz (after tone correction)
- Carrier channels: ±0.1 Hz (goal: ±3 km path)

---

## References

### Key Documents
- `PROJECT_NARRATIVE.md` - Complete history
- `CONTEXT.md` - System overview
- `ARCHITECTURE.md` - Technical details
- `CORE_ANALYTICS_SPLIT_DESIGN.md` - Split rationale

### External
- ka9q-radio source: `/home/mjh/git/ka9q-radio/`
- KA9Q timing: `pcmrecord.c` lines 607-899
- RTP RFC 3550: Network byte order specification

---

**Version**: 1.0  
**Last Updated**: Nov 18, 2025  
**Purpose**: Quick technical reference for developers
