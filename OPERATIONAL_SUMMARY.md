# GRAPE Signal Recorder - Operational Summary

**Current Production Configuration**

---

## System Overview

The GRAPE signal recorder operates **18 input channels** to monitor **9 frequencies of interest**, requesting RTP streams from radiod via the ka9q-python package.

### Channel Configuration

**Per frequency (9 total)**:
- 1× **Wide bandwidth channel** (16 kHz IQ)
- 1× **Carrier channel** (200 Hz IQ)

**Total**: 18 channels (9 wide + 9 carrier)

### Frequencies Monitored

| Frequency | Station | Wide Channel | Carrier Channel | WWV/WWVH Overlap |
|-----------|---------|--------------|-----------------|------------------|
| 2.5 MHz   | WWV     | ✓ 16 kHz     | ✓ 200 Hz       | ✓ Both stations  |
| 5.0 MHz   | WWV     | ✓ 16 kHz     | ✓ 200 Hz       | ✓ Both stations  |
| 7.85 MHz  | CHU     | ✓ 16 kHz     | ✓ 200 Hz       | CHU only         |
| 10.0 MHz  | WWV     | ✓ 16 kHz     | ✓ 200 Hz       | ✓ Both stations  |
| 15.0 MHz  | WWV     | ✓ 16 kHz     | ✓ 200 Hz       | ✓ Both stations  |
| 20.0 MHz  | WWV     | ✓ 16 kHz     | ✓ 200 Hz       | WWV only         |
| 25.0 MHz  | WWV     | ✓ 16 kHz     | ✓ 200 Hz       | WWV only         |
| 3.33 MHz  | CHU     | ✓ 16 kHz     | ✓ 200 Hz       | CHU only         |
| 14.67 MHz | CHU     | ✓ 16 kHz     | ✓ 200 Hz       | CHU only         |

---

## Data Products Generated

### Product 1: Wide Bandwidth Archives (Primary Scientific Record)

**Format**: NPZ (NumPy compressed)  
**Sample Rate**: 16 kHz complex IQ  
**Channels**: 9 (one per frequency)  
**Timing**: GPS_LOCKED via WWV/CHU tone detection (±1ms)

**Contents**:
```python
{
    "iq": complex64[960000],      # 60 seconds @ 16 kHz
    "rtp_timestamp": int,         # RTP timestamp of iq[0]
    "sample_rate": 16000,
    "gaps_filled": int,           # Zero-filled samples
    "gaps_count": int,            # Discontinuities
    "packets_received": int,
    "packets_expected": int
}
```

**Purpose**:
- Complete scientific record with sample count integrity
- Reprocessable with improved algorithms
- **KEEP: Long-term archive**

---

### Product 2: Decimated 10 Hz (from 16 kHz Wide)

**Format**: NPZ with rich metadata  
**Sample Rate**: 10 Hz complex IQ  
**Decimation**: 16 kHz → 10 Hz (1600:1, anti-aliased)  
**Channels**: 9 (one per frequency)  
**Timing**: GPS_LOCKED (inherited from wide channel)

**Contents**:
```python
{
    "iq": complex64[600],         # 60 seconds @ 10 Hz
    "timing_metadata": {
        "quality": "GPS_LOCKED",
        "time_snap_age_seconds": float,
        "utc_timestamp": float,
        ...
    },
    "quality_metadata": {
        "completeness_pct": float,
        "packet_loss_pct": float,
        "gaps_count": int,
        "gaps_filled": int
    },
    "tone_metadata": {
        "detections": [...]        # WWV/CHU/WWVH detections
    }
}
```

**Purpose**:
- Doppler analysis (ionospheric path variations)
- High-quality timing from tone detection
- **CANDIDATE: Digital RF upload** (compete with Product 3)

---

### Product 3: Decimated 10 Hz (from 200 Hz Carrier)

**Format**: NPZ with metadata  
**Sample Rate**: 10 Hz complex IQ  
**Decimation**: 200 Hz → 10 Hz (20:1, anti-aliased)  
**Channels**: 9 (one per frequency)  
**Timing**: NTP_SYNCED (±10ms, adequate for Doppler)

**Contents**:
```python
{
    "iq": complex64[600],         # 60 seconds @ 10 Hz
    "timing_metadata": {
        "quality": "NTP_SYNCED",
        "ntp_offset_ms": float,
        "utc_timestamp": float,
        ...
    },
    "quality_metadata": {
        "completeness_pct": float,
        "packet_loss_pct": float,
        ...
    },
    "tone_metadata": {}           # Empty (no tones in 200 Hz)
}
```

**Purpose**:
- Direct carrier observation (minimal processing)
- Potentially cleaner Doppler signal
- Continuous data (no tone detection dependency)
- **CANDIDATE: Digital RF upload** (compete with Product 2)

**Trade-off**:
- ✅ Less processing → fewer artifacts
- ✅ Continuous (no propagation fade gaps)
- ⚠️ Lower timing accuracy (NTP vs GPS)
- ⚠️ ~49% packet reception (vs >95% for wide)

---

### Product 4: Tone Detection & Analysis Records

**Formats**: CSV, JSON state files  
**Channels**: 9 wide channels (carrier channels excluded)

**Components**:

#### 4a. Tone Detection Records
```csv
timestamp, station, frequency, tone_duration, snr_db, timing_error_ms
2025-11-18T20:00:00, WWV, 5.0, 0.801, 28.4, 2.3
```

#### 4b. time_snap State
```json
{
    "rtp_timestamp": 297419300,
    "utc_timestamp": 1763430540.0,
    "source": "wwv_verified",
    "confidence": 0.632,
    "station": "WWV",
    "age_seconds": 45.2
}
```

#### 4c. Gap Analysis Logs
```
2025-11-18T20:15:23 UTC - Gap detected: 960 samples (60ms) at RTP 297450000
  Cause: Network packet loss (3 consecutive packets)
  Action: Zero-filled, completeness=99.9%
```

**Purpose**:
- Scientific provenance for timing quality
- Reprocessing decisions
- Quality assurance

---

### Product 5: WWV/WWVH Discrimination Records

**Format**: CSV  
**Channels**: 4 (frequencies with both WWV and WWVH: 2.5, 5, 10, 15 MHz)

**Contents**:
```csv
timestamp, wwv_timing_error_ms, wwvh_timing_error_ms, differential_delay_ms, wwv_snr_db, wwvh_snr_db
2025-11-18T20:00:00, -4.81, 5.14, 169.33, 28.4, 22.1
```

**Purpose**:
- Separate WWV (Fort Collins, CO) from WWVH (Kauai, HI) signals
- Differential delay → ionospheric path difference
- Relative signal strength → propagation conditions
- **CRITICAL**: Both stations transmit simultaneously on shared frequencies

**Science Value**:
- Path difference: ~4000 km (Fort Collins → receiver vs Kauai → receiver)
- Differential delay: Typically 169-624 ms (realistic ionospheric paths)
- Propagation analysis: Day/night patterns, solar disturbances

---

## Upload Strategy (Future)

### Decision: Select Best 10 Hz Product

**Product 2 (from 16 kHz)** vs **Product 3 (from 200 Hz)**

**Evaluation Criteria**:
1. **Spectral purity** - Cleaner Doppler signal?
2. **Timing quality** - GPS_LOCKED vs NTP_SYNCED
3. **Completeness** - Packet reception rate
4. **Artifacts** - Decimation quality

**Current Plan**:
- Generate both products
- Compare spectrograms and quality metrics
- Select winner per frequency (may differ)
- Convert to Digital RF format
- Upload to HamSCI/GRAPE repository

### Digital RF Format

**Structure** (HDF5-based):
```
/digital_rf/
  ├── WWV_2.5_MHz/
  │   ├── data/          # 10 Hz IQ samples
  │   ├── metadata/      # Timing quality, gaps, tone detections
  │   └── properties/    # Channel config
  ├── WWV_5.0_MHz/
  ...
```

**Metadata Included**:
- Timing quality (GPS_LOCKED or NTP_SYNCED)
- time_snap reference points
- Gap analysis (completeness, discontinuities)
- WWV/WWVH discrimination (if applicable)

---

## Data Retention Strategy

### Keep Long-Term

1. **Wide bandwidth NPZ archives** (Product 1)
   - Complete scientific record
   - Reprocessable
   - ~2 MB/min/channel compressed

2. **WWV/WWVH discrimination CSV** (Product 5)
   - Unique science product
   - Cannot regenerate without original data

### Upload to PSWS

**Selected 10 Hz Digital RF** (Product 2 or 3)
- Community access
- Standardized format
- Rich metadata

### Optionally Delete After Upload

- Non-selected 10 Hz product (2 or 3)
- Intermediate decimation files
- (Can regenerate from Product 1 if needed)

---

## System Data Flow

```
ka9q-radio (radiod)
    ↓ RTP multicast
    ├─→ 9× Wide channels (16 kHz)
    │   ↓ Core Recorder
    │   ↓ Product 1: Wide NPZ archives [KEEP]
    │   ↓ Analytics Service
    │   ├─→ Product 2: 10 Hz decimated [CANDIDATE UPLOAD]
    │   ├─→ Product 4: Tone detection, time_snap, gaps
    │   └─→ Product 5: WWV/WWVH discrimination [KEEP]
    │
    └─→ 9× Carrier channels (200 Hz)
        ↓ Core Recorder
        ↓ Carrier NPZ archives
        ↓ Analytics Service
        └─→ Product 3: 10 Hz decimated [CANDIDATE UPLOAD]

Final Step (Future):
    ↓ Select best of Product 2 or 3
    ↓ Convert to Digital RF format
    └─→ Upload to HamSCI/GRAPE PSWS
```

---

## Current Status

**Operational**: ✅ All 18 channels recording  
**Products 1-5**: ✅ All generating correctly  
**Upload**: ⏭️ Pending product selection and Digital RF integration

---

## Configuration Summary

**Startup**: `./start-dual-service.sh`

**Config**: `config/core-recorder.toml`
```toml
# 9 wide channels @ 16 kHz
[[channels.channel]]
ssrc = 2500000
frequency_hz = 2500000
sample_rate = 16000
description = "WWV 2.5 MHz"
# ... (8 more wide channels)

# 9 carrier channels @ 200 Hz
[[channels.channel]]
ssrc = 2500001
frequency_hz = 2500000
sample_rate = 200
description = "WWV 2.5 MHz carrier"
# ... (8 more carrier channels)
```

---

## Key Metrics

**Wide Channels**:
- Data rate: ~2 MB/min/channel (compressed NPZ)
- Timing: GPS_LOCKED >90% of time
- Completeness: >95% typical

**Carrier Channels**:
- Data rate: ~0.1 MB/min/channel (compressed NPZ)
- Timing: NTP_SYNCED continuous
- Completeness: ~49% (radiod limitation at 200 Hz)

**Total**: ~20 MB/min for all 18 channels (~30 GB/day)

---

**Document Version**: 1.0  
**Last Updated**: Nov 18, 2025  
**Status**: Current operational configuration
