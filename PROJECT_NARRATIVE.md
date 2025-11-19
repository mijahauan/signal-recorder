# GRAPE Signal Recorder - Project Narrative

**Complete project history from conception to current production system**

---

## Table of Contents

1. [Project Genesis](#project-genesis)
2. [Early Architecture & Critical Bugs](#early-architecture--critical-bugs)
3. [The Core/Analytics Split](#the-coreanalytics-split)
4. [Timing Architecture Evolution](#timing-architecture-evolution)
5. [Carrier Channel Implementation](#carrier-channel-implementation)
6. [Web UI & Monitoring](#web-ui--monitoring)
7. [Current System Architecture](#current-system-architecture)
8. [Lessons Learned](#lessons-learned)

---

## Project Genesis

### Mission Statement

**GRAPE (Global Radio Amateur Propagation Experiment)** aims to record and analyze WWV/CHU time-standard radio signals to study ionospheric disturbances through timing variations. Amateur radio operators worldwide contribute data to HamSCI's global observation network.

### Core Scientific Goals

1. **Timing Precision**: Maintain GPS-quality timestamps (±1ms) via WWV/CHU tone detection
2. **Sample Integrity**: Complete data record with zero sample loss and gap transparency
3. **Doppler Analysis**: Track ionospheric Doppler shifts to ±0.1 Hz (±3 km path resolution)
4. **Continuous Operation**: 24/7 recording regardless of propagation conditions

### Technology Foundation

- **Data Source**: ka9q-radio RTP multicast streams (16 kHz IQ, 200 Hz carrier)
- **Backend**: Python 3.8+ with numpy/scipy for signal processing
- **Storage**: NPZ (NumPy compressed) for archives, Digital RF (HDF5) for uploads
- **Frontend**: Node.js (Express) with vanilla HTML/CSS/JS
- **Upload Target**: HamSCI PSWS repository

---

## Early Architecture & Critical Bugs

### V1: Integrated Monolithic Recorder (Pre-Nov 2024)

**Original Design**: Single ~2000-line program combining:
- RTP packet reception and resequencing
- Gap detection and filling
- WWV/CHU tone detection for timing
- Quality metrics calculation
- Decimation (16 kHz → 10 Hz)
- Digital RF writing and uploads

**Problem**: Tight coupling meant analytics bugs required recorder restarts → data loss.

### Critical Bug #1: Byte Order Corruption (Oct 30, 2025)

**Root Cause**: RTP payloads use network byte order (big-endian), but code parsed as little-endian.

**Symptom**: All IQ data was byte-swapped garbage.
```python
# WRONG: Little-endian default
samples = np.frombuffer(payload, dtype=np.int16)

# CORRECT: Big-endian (network order)
samples = np.frombuffer(payload, dtype='>i2')
```

**Impact**: All data before Oct 30 07:37 UTC corrupted and discarded.

### Critical Bug #2: I/Q Phase Swap (Oct 30, 2025)

**Root Cause**: ka9q-radio sends samples in Q, I order (not I, Q as assumed).

**Symptom**: Carrier offset by ~500 Hz instead of centered at DC.
```python
# WRONG: I + jQ
iq = samples[:, 0] + 1j * samples[:, 1]

# CORRECT: Q + jI
iq = samples[:, 1] + 1j * samples[:, 0]
```

**Verification**: Power spectrum showed symmetric sidebands at ±1 kHz only after Q+jI fix.

### Critical Bug #3: RTP Payload Offset (Oct 30, 2025)

**Root Cause**: Hardcoded payload at byte 12 ignored variable-length RTP headers.

**Symptom**: Header bytes parsed as IQ data → only narrow carrier visible, no modulation sidebands.

**Fix**: Calculate actual payload offset based on CSRC count and extension headers.
```python
# Base + CSRC list
payload_offset = 12 + (header.csrc_count * 4)

# Add extension header if present
if header.extension:
    ext_length_words = struct.unpack('>HH', data[payload_offset:payload_offset+4])[1]
    payload_offset += 4 + (ext_length_words * 4)

payload = data[payload_offset:]  # Correct samples
```

**Timeline**: All three bugs fixed by Oct 30 20:46 UTC. Data before this is scientifically invalid.

### Critical Bug #4: Sample Rate Misinterpretation (Nov 3, 2024)

**Root Cause**: Assumed 8 kHz complex IQ when radiod actually sends 16 kHz complex IQ.

**Symptom**: Tone detection failed, frequency analysis wrong.

**Fix**: Updated all calculations:
- Sample rate: 8000 → 16000 Hz
- Samples per minute: 480,000 → 960,000
- RTP increment: 160 → 320 per packet
- Tone detector resampling: 8k→3k to 16k→3k

**Impact**: Essential for WWV detection and all frequency analysis.

---

## The Core/Analytics Split

### Architectural Decision (Nov 9, 2024)

**Problem**: Monolithic recorder's tight coupling caused:
- Data loss during analytics bug fixes
- No ability to reprocess archives with improved algorithms
- ~2000 lines mixing critical (RTP) and experimental (analytics) code
- Testing required live RTP streams

**Solution**: Split into two independent services.

### Core Recorder (~300 lines, changes <5/year)

**Philosophy**: Rock-solid data acquisition, minimal dependencies, conservative error handling.

**Responsibilities**:
1. Receive RTP packets from multicast
2. Resequence packets (handle out-of-order)
3. Detect gaps via RTP timestamp discontinuities
4. Fill gaps with zeros (maintain sample count integrity)
5. Write NPZ archives (one minute each)

**What it does NOT do**:
- ❌ No tone detection
- ❌ No quality metrics
- ❌ No decimation
- ❌ No Digital RF
- ❌ No analytics

**Key File**: `src/signal_recorder/core_recorder.py`

### Analytics Service (changes >50/year)

**Philosophy**: Experimental, can crash/restart, processes archived data.

**Responsibilities**:
1. Watch archive directory for new NPZ files
2. Generate quality metrics (completeness, packet loss, jitter)
3. Detect WWV/CHU/WWVH tones (establish time_snap)
4. Decimate to 10 Hz for Doppler analysis
5. Write Digital RF format
6. Upload to PSWS repository

**Benefits**:
- Can reprocess historical data with improved algorithms
- Analytics bugs don't affect data collection
- Independent testing with synthetic/archived data
- Aggressive retry allowed (systemd restarts)

**Key File**: `src/signal_recorder/analytics_service.py`

### NPZ Archive Format (Scientific Record)

**Critical Fields**:
```python
np.savez_compressed(
    # Sample data
    iq=complex_samples,           # 960,000 samples @ 16 kHz
    
    # Timing reference (CRITICAL)
    rtp_timestamp=first_sample_rtp,  # RTP timestamp of iq[0]
    sample_rate=16000,
    
    # Quality indicators
    gaps_filled=gap_samples,      # Samples filled with zeros
    gaps_count=num_gaps,          # Number of discontinuities
    packets_received=pkt_count,
    packets_expected=expected_pkt
)
```

**Why RTP timestamp is critical**: Enables precise UTC reconstruction after time_snap establishment.
```python
utc = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate
```

---

## Timing Architecture Evolution

### KA9Q Principle: RTP Timestamp is Primary Reference

**Foundational Insight** (from Phil Karn's ka9q-radio design):
- RTP timestamps define the time domain
- Wall clock is DERIVED from RTP via time_snap anchor
- Sample count integrity guaranteed (gap-filled with zeros)
- No time "stretching" or "compression"

**Reference**: `/home/mjh/git/ka9q-radio/src/pcmrecord.c` lines 607-899

### time_snap Mechanism

**Purpose**: Anchor RTP timestamps to UTC via WWV/CHU tone detection.

**How it works**:
1. Detect WWV tone rising edge at :00.000 (1000 Hz, 0.8s duration)
2. Record RTP timestamp at detection point
3. Establish mapping: `time_snap_rtp` = known UTC minute boundary
4. All subsequent samples: `utc = time_snap_utc + (rtp - time_snap_rtp) / 16000`

**Accuracy**: ±1ms when established, degrades ~1ms/hour if aged.

### Critical Discovery: Independent RTP Clocks (Nov 17, 2025)

**Problem**: Can we share time_snap between channels?

**Test Result**: Each ka9q-radio channel has **independent RTP clock origin**.

**Evidence**:
```
Channel       RTP Timestamp (same wall-clock time)
WWV 5 MHz     304,122,240
WWV 10 MHz    302,700,560  ← 1.4M sample offset!
CHU 7.85 MHz  304,122,240
```

**Implication**: time_snap from one channel CANNOT be used for another. Each must establish its own or use NTP fallback.

### Timing Quality Hierarchy

**Implementation**: Continuous upload with quality annotations (not binary accept/reject).

#### 1. GPS_LOCKED (±1ms) - Best
- **Source**: WWV/CHU time_snap
- **When**: time_snap age < 5 minutes
- **Use**: All wide channels with good propagation

#### 2. NTP_SYNCED (±10ms) - Good
- **Source**: System clock via NTP
- **When**: No recent time_snap, NTP offset < 100ms
- **Use**: Propagation fades, carrier channels

#### 3. INTERPOLATED (degrades) - Acceptable
- **Source**: Aged time_snap (5-60 minutes old)
- **Accuracy**: ~1ms/hour drift
- **Use**: Temporary propagation fades

#### 4. WALL_CLOCK (±seconds) - Fallback
- **Source**: Unsynchronized system clock
- **When**: Cold start, no NTP
- **Use**: Mark for reprocessing

**Benefits**:
- Zero data loss during propagation fades
- Complete scientific record
- Selective reprocessing based on timing quality
- Enables continuous 24/7 operation

---

## Carrier Channel Implementation

### Scientific Goal: Doppler Analysis

**Purpose**: Track 10 Hz carrier frequency variations to measure ionospheric Doppler shifts.

**Resolution Goal**: ±0.1 Hz (corresponds to ±3 km path length change)

**Time Scale**: Minutes to hours (diurnal variation, solar disturbances)

### Technical Constraints

**Radiod Limitation**: Minimum sample rate = 200 Hz
- Carrier at ~10 Hz, measurement window ±5 Hz
- Only 200 Hz bandwidth available
- **Problem**: Cannot detect 1000 Hz WWV tones (too narrow)

**Packet Reception**: ~49% at 200 Hz (network/buffer limitations)
- Effective rate: ~98 Hz
- Still adequate for <10 Hz carrier analysis

### Timing Solution: NTP as Primary

**Decision** (Nov 17, 2025): Use NTP_SYNCED for carrier channels.

**Rationale**:
1. **Accuracy sufficient**: ±10ms → <0.01 Hz frequency uncertainty
2. **Independent RTP clocks**: Cannot share wide channel time_snap
3. **Continuous data**: No gaps during propagation fades
4. **Science valid**: Doppler shifts occur over minutes/hours

**Implementation**:
```python
def _get_channel_type(self, channel_name: str) -> str:
    if 'carrier' in channel_name.lower():
        return 'carrier'
    return 'wide'

# Carrier channels skip tone detection, use NTP
if channel_type == 'carrier':
    return TimingAnnotation(
        quality=TimingQuality.NTP_SYNCED,
        ntp_offset_ms=offset,
        notes="Carrier channel: NTP timing (±10ms, adequate for ±0.1 Hz Doppler)"
    )
```

### Unified Analytics Architecture

**Both channel types** receive identical processing:
- Quality metrics (completeness, packet loss)
- Decimation to 10 Hz NPZ
- Digital RF format
- Discontinuity logs
- **Difference**: Timing annotation (TONE_LOCKED vs NTP_SYNCED)

**Metadata Structure** (identical):
```python
{
    "timing_metadata": {
        "quality": "TONE_LOCKED" | "NTP_SYNCED",
        "time_snap_age_seconds": <float> | null,
        "ntp_offset_ms": <float> | null,
        ...
    },
    "quality_metadata": {...},
    "tone_metadata": {...} | {}  # Empty for carrier
}
```

---

## Critical Bug Fix: Tone Detector Timing (Nov 17, 2025)

### The Bug

**Location**: `src/signal_recorder/tone_detector.py` line 350

**Problem**: 30-second timing offset in all tone detections.

**Root Cause**:
```python
# WRONG:
onset_time = current_unix_time + (onset_sample_idx / self.sample_rate)
#            ^^^^^^^^^^^^^^^^^
#            Middle of buffer (60-second buffer → 30-second offset)

# CORRECT:
onset_time = buffer_start_time + (onset_sample_idx / self.sample_rate)
#            ^^^^^^^^^^^^^^^^^
#            Start of buffer (onset_sample_idx is relative to start)
```

### Symptoms

**Before Fix** (Nov 17 16:23 - Nov 18 01:45 UTC):
- Timing errors: ±29.5 seconds
- All discrimination data rejected (threshold: ±1 second)
- Differential delays: ±59 seconds (unrealistic)

**After Fix**:
- Timing errors: ±5-40 milliseconds (normal propagation)
- Discrimination recording resumed
- Differential delays: 169-624 ms (realistic ionospheric paths)

### Recovery Actions

1. **Code fix** applied to `tone_detector.py`
2. **Data cleanup**: Removed corrupt discrimination CSVs and decimated NPZ
3. **State cleared**: Forced time_snap re-establishment
4. **Services restarted**: Core + analytics
5. **Reprocessing**: 93 raw archives automatically reprocessed

**Preserved**: All 16 kHz NPZ archives (perfect data, just needed reprocessing)

---

## Web UI & Monitoring

### monitoring-server-v3.js (Current)

**Architecture**: Node.js Express backend, vanilla HTML/CSS/JS frontend.

**Key Features**:
- Real-time quality dashboard
- Carrier analysis screen (spectrograms, Doppler tracking)
- Discrimination visualization (WWV vs WWVH differential delays)
- Timing quality display (GPS_LOCKED vs NTP_SYNCED)
- Audio streaming (AM demodulated)

### Path Synchronization Protocol

**Critical Issue**: Python (analytics) and JavaScript (web UI) must use identical file paths.

**Solution**: Centralized path management.

**Python API**: `src/signal_recorder/paths.py`
```python
class GRAPEPaths:
    def get_quality_csv_path(self, channel):
        return self.analytics_dir / channel / "quality" / f"{channel}_quality.csv"
```

**JavaScript API**: `web-ui/grape-paths.js`
```javascript
class GRAPEPaths {
    getQualityCSVPath(channel) {
        return path.join(this.analyticsDir, channel, 'quality', `${channel}_quality.csv`);
    }
}
```

**Validation**: `./scripts/validate-paths-sync.sh` verifies both APIs return identical paths.

**Documentation**: `WEB_UI_ANALYTICS_SYNC_PROTOCOL.md`

---

## Migration to ka9q-python Library

### Extraction (Nov 2024)

**Before**: radiod control code embedded in signal-recorder.

**After**: Separate `ka9q-python` package at `/home/mjh/git/ka9q-python`.

**Benefits**:
- ✅ Reusable by other projects
- ✅ signal-recorder focuses on GRAPE logic
- ✅ Independent testing
- ✅ Community contributions

**Installation**:
```bash
pip install -e /home/mjh/git/ka9q-python
```

**Usage**:
```python
from ka9q import RadiodControl, discover_channels

control = RadiodControl("radiod.local")
channels = discover_channels("radiod.local")
```

---

## Current System Architecture

### Production Entry Point

**Primary**: `./start-dual-service.sh`
- Starts `core_recorder.py` (RTP → NPZ archives)
- Starts `analytics_service.py` per channel (NPZ → derived products)
- Starts `monitoring-server-v3.js` (web UI)

### Data Flow

```
ka9q-radio (radiod)
    ↓ RTP multicast (16 kHz IQ or 200 Hz carrier)
Core Recorder
    ↓ NPZ archives (960,000 samples/minute)
Analytics Service (per channel)
    ├→ Quality metrics CSV
    ├→ WWV tone detection → time_snap
    ├→ Decimated 10 Hz NPZ (timing + quality metadata)
    ├→ Digital RF HDF5
    └→ Upload to PSWS (future)
```

### File Organization (Post-Cleanup Nov 18, 2025)

**Active Code**:
- `src/signal_recorder/core_recorder.py` - Minimal RTP→NPZ recorder
- `src/signal_recorder/analytics_service.py` - NPZ processing
- `src/signal_recorder/tone_detector.py` - WWV/CHU/WWVH detection
- `src/signal_recorder/decimation.py` - 16kHz → 10Hz
- `src/signal_recorder/digital_rf_writer.py` - DRF format
- `web-ui/monitoring-server-v3.js` - Web dashboard

**Archived** (Nov 18, 2025):
- V2 monolithic recorder → `archive/legacy-code/v2-recorder/`
- Session docs (~50 files) → `archive/dev-history/`
- Feature docs (~40 files) → `docs/features/`
- Debug scripts → `archive/shell-scripts/debug/`

### Configuration

**Core**: `config/core-recorder.toml`
```toml
[core]
mode = "production"
data_root = "/tmp/grape-test"

[ka9q]
multicast_address = "239.103.26.231"
status_address = "239.192.152.141"

[channels]
[[channels.channel]]
ssrc = 5000000
frequency_hz = 5000000
sample_rate = 16000
description = "WWV 5 MHz"
```

**Analytics**: `config/grape-config.toml` (same file, different sections)
```toml
[analytics]
quality_enabled = true
tone_detection_enabled = true
decimation_enabled = true
digital_rf_enabled = true
```

---

## Lessons Learned

### 1. Timing Architecture

**Principle**: RTP timestamp is primary, wall clock is derived.
- KA9Q timing architecture is correct
- time_snap mechanism provides GPS-quality timing
- Each channel has independent RTP clock (no sharing)
- Quality annotations > binary rejection

### 2. Core/Analytics Split

**Impact**: Fundamental to scientific reliability.
- Zero data loss during analytics bugs/updates
- Reprocessing capability is essential
- Simple core = rock-solid (300 lines, rarely changes)
- Experimental analytics can iterate freely

### 3. Bug Prevention

**Critical lessons**:
- Always verify byte order with network protocols
- Test with known-good reference (ka9q-web)
- Parse RTP headers fully (no hardcoded offsets)
- Sanity check data ranges early
- Use spectrum analysis to verify IQ integrity
- Buffer reference points are critical (start vs middle vs end)

### 4. Multi-Service Architecture Benefits

**Proven during Nov 17 tone detector bug**:
- Core preserved perfect data
- Analytics fixed and restarted independently
- All data reprocessed automatically
- No manual intervention required

### 5. Frequency Variations Are Data, Not Errors

**Scientific understanding**:
- ✅ Smooth frequency drift = Ionospheric Doppler (real data!)
- ❌ Abrupt jumps = Processing artifacts (bugs!)
- Doppler shifts reveal ionospheric path changes
- ±0.1 Hz resolution → ±3 km path precision

### 6. Path Management

**Lesson**: Dual-language systems need strict path synchronization.
- Centralized path APIs (Python + JavaScript)
- Automated validation testing
- Documentation of sync protocol

### 7. Documentation vs Implementation

**Evolution**:
- Early: Many session docs (50+ files)
- Problem: Hard to find current architecture
- Solution: Distilled narrative + cleanup
- Result: Clear separation of history vs reference

### 8. Sample Count Invariant

**Critical**: 16 kHz × 60 seconds = 960,000 samples (exactly)
- Discrepancies indicate packet loss or timing issues
- All gaps filled with zeros (maintain count)
- Gap transparency > hiding problems

---

## Current Status & Future

### Production Status

**System**: ✅ Operational since Nov 18, 2025
- Core recorder: Stable, zero data loss
- Analytics: All channels processing
- Web UI: Real-time monitoring active

**Data Quality**:
- Wide channels: GPS_LOCKED (95%+ of time)
- Carrier channels: NTP_SYNCED (continuous)
- Discrimination: Recording WWV/WWVH differentials
- Archives: Complete, reprocessable

### Future Work

**Phase 1: Refactoring**
- Extract `RTPReceiver` from `grape_rtp_recorder.py` to `rtp_receiver.py`
- Complete V2 archive (currently partial due to shared RTPReceiver)

**Phase 2: Scientific Analysis**
- Compare carrier spectrograms (radiod 200 Hz) vs wide decimated (16kHz→10Hz)
- Long-term Doppler tracking studies
- Ionospheric disturbance correlation analysis

**Phase 3: Upload Integration**
- Enable automatic PSWS upload
- Metadata validation
- Bandwidth management

**Phase 4: Multi-Station**
- Coordinate timing across distributed stations
- Network-wide ionospheric mapping
- HamSCI integration

---

## Key Files Reference

### Core System
- `src/signal_recorder/core_recorder.py` - RTP → NPZ recorder
- `src/signal_recorder/core_npz_writer.py` - NPZ file format
- `src/signal_recorder/packet_resequencer.py` - RTP resequencing

### Analytics
- `src/signal_recorder/analytics_service.py` - Main processor
- `src/signal_recorder/tone_detector.py` - WWV/CHU/WWVH detection
- `src/signal_recorder/decimation.py` - 16kHz → 10Hz
- `src/signal_recorder/digital_rf_writer.py` - DRF format

### Configuration & Management
- `src/signal_recorder/paths.py` - Path management
- `src/signal_recorder/channel_manager.py` - Channel config
- `config/core-recorder.toml` - Main configuration

### Web UI
- `web-ui/monitoring-server-v3.js` - Express server
- `web-ui/grape-paths.js` - Path synchronization

### Documentation
- `CONTEXT.md` - Complete system reference
- `ARCHITECTURE.md` - Technical architecture
- `CORE_ANALYTICS_SPLIT_DESIGN.md` - Split design rationale
- `PROJECT_NARRATIVE.md` - This document

### Startup
- `start-dual-service.sh` - Production entry point
- `QUICK_START.md` - Getting started guide

---

**Document Version**: 1.0  
**Last Updated**: Nov 18, 2025  
**Status**: Current production system narrative  
**Supersedes**: All session summaries and implementation docs in archive/
