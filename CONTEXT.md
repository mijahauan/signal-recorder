# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-10  
**Version:** 5.0.0  
**Status:** ARCHITECTURE COMPLETE - time-manager separated

---

## 🎯 GRAPE-RECORDER MISSION

**Primary Deliverable:** Time- and gap-annotated Digital RF packages at 10 Hz around 9 channel carriers, decimated from 20 kHz RTP feed, for upload to the PSWS repository.

### Product Specification

```
Input:  20 kHz complex IQ from ka9q-radio (9 channels × 1,200,000 samples/minute)
Output: 10 Hz decimated Digital RF with timing metadata for PSWS upload

Quality Requirements:
├── Time annotation: D_clock from time-manager (sub-ms accuracy)
├── Gap annotation: Sample-accurate gap detection and flagging
├── Format: HDF5 Digital RF with complete metadata
└── Delivery: Daily upload to pswsnetwork.eng.ua.edu
```

### Data Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GRAPE-RECORDER PIPELINE                             │
│                                                                              │
│  ka9q-radio ──RTP──▶ RadiodStream ──▶ Phase 1: Raw Buffer (20 kHz)          │
│      │                    │                      │                           │
│      │              StreamQuality            minute.bin                      │
│      │              (gaps, RTP ts)               │                           │
│      │                    │                      ▼                           │
│      │                    └──────────▶ Phase 2: Decimation (10 Hz)          │
│      │                                           │                           │
│ time-manager ◀────────────────────────┐         │                           │
│      │                                │         ▼                           │
│      │  /dev/shm/grape_timing         │    Phase 3: Products                │
│      │  ├── d_clock_ms                │    ├── Digital RF (HDF5)            │
│      │  ├── station (WWV/WWVH)        │    ├── Spectrograms (PNG)           │
│      │  └── propagation_mode          │    └── PSWS Upload                  │
│      │                                │                                      │
│      └────────────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✅ COMPLETED: TWO-APPLICATION SEPARATION

### Application 1: time-manager (Infrastructure) - INDEPENDENT
**Repository:** https://github.com/mijahauan/time-manager  
**Location:** `/home/wsprdaemon/time-manager/`  
**Status:** v0.2.0 released, fully independent

A precision timing daemon that:
- Uses `ka9q.stream.RadiodStream` for RTP reception (9 channels)
- Extracts UTC(NIST) from WWV/WWVH/CHU via multi-broadcast fusion
- Computes per-station propagation delays using IRI2020 ionospheric model
- Owns station discrimination (required for propagation path calculation)
- Publishes D_clock to `/dev/shm/grape_timing`
- Feeds chronyd via SHM refclock (96-byte NTP struct)

**Key insight:** Discrimination is NOT a science product—it's a dependency of the clock. To recover UTC(NIST), you must know the propagation path. To know the path, you must know the station (WWV vs WWVH). Therefore, time-manager owns the discriminator.

### Application 2: grape-recorder (Science Client)
**Repository:** https://github.com/mijahauan/grape-recorder  
**Location:** `/home/wsprdaemon/grape-recorder/`  
**Status:** Pending TimingClient integration, needs quality verification

A GRAPE-specific science data recorder that:
- Consumes timing from time-manager via `TimingClient`
- Records IQ data with time and gap annotations
- Decimates 20 kHz → 10 Hz with `StatefulDecimator`
- Packages Digital RF for PSWS upload
- Generates spectrograms for monitoring

### Why Two Applications?
- **Reuse**: WSPR daemon, FT8 decoder can use time-manager for timing
- **Stability**: If PSWS upload crashes, system clock stays synchronized
- **Clean separation**: Timing physics in one box, data recording in another
- **Chrony integration**: Entire Linux OS gets "GPS-quality" time

---

## 🔄 NEXT SESSION: VERIFY GRAPE-RECORDER QUALITY

### Priority 1: Confirm Product Pipeline

```bash
# Verify decimation output exists and is valid
ls -la /tmp/grape-test/products/*/decimated/$(date -u +%Y%m%d).bin

# Check decimated data quality (boundary transients fixed?)
python3 -c "
import numpy as np
from pathlib import Path
f = Path('/tmp/grape-test/products/WWV_10_MHz/decimated/$(date -u +%Y%m%d).bin')
if f.exists():
    iq = np.fromfile(f, dtype=np.complex64)
    print(f'Samples: {len(iq)} ({len(iq)/600:.1f} minutes)')
    print(f'Power: {10*np.log10(np.mean(np.abs(iq)**2)):.1f} dB')
"
```

### Priority 2: Digital RF Packaging

The 10 Hz decimated data must be packaged as HDF5 Digital RF with:

| Metadata Field | Source | Description |
|----------------|--------|-------------|
| `sample_rate` | 10 Hz | Decimated rate |
| `center_freq` | Channel config | e.g., 10,000,000 Hz |
| `start_time` | time-manager | UTC(NIST) via D_clock correction |
| `gap_samples` | StreamQuality | From RadiodStream gap detection |
| `d_clock_ms` | time-manager | System clock offset at recording time |
| `station` | time-manager | WWV, WWVH, or CHU |

### Priority 3: Refactor to Use RadiodStream

**Current:** grape-recorder uses custom `RTPReceiver` + `PacketResequencer`  
**Target:** Use `ka9q.stream.RadiodStream` like time-manager does

Benefits:
- Remove `src/grape_recorder/core/rtp_receiver.py`
- Remove `src/grape_recorder/core/packet_resequencer.py`
- Get automatic gap detection via `StreamQuality`
- Get GPS-disciplined RTP timestamps
- Consistent with time-manager architecture

### Priority 4: TimingClient Integration

```python
# src/grape_recorder/timing_client.py already exists
from grape_recorder.timing_client import TimingClient

client = TimingClient()
snapshot = client.get_snapshot()

# Use for Digital RF annotation:
d_clock_ms = snapshot['d_clock_ms']
station = snapshot['channels']['WWV_10_MHz']['station']
```

---

## INTERFACE CONTRACT

### time-manager → grape-recorder

**Path:** `/dev/shm/grape_timing`

```json
{
  "version": "1.0.0",
  "timestamp": 1733875200.0,
  "d_clock_ms": -1.25,
  "d_clock_uncertainty_ms": 0.55,
  "clock_status": "LOCKED",
  "fusion": {
    "contributing_broadcasts": 9,
    "d_clock_raw_ms": -1.30,
    "d_clock_calibrated_ms": -1.25
  },
  "channels": {
    "WWV_10_MHz": {
      "station": "WWV",
      "propagation_mode": "2F",
      "propagation_delay_ms": 6.83,
      "d_clock_ms": -1.30,
      "snr_db": 25.0
    }
  }
}
```

### D_clock Interpretation

```
D_clock = system_clock - UTC(NIST)

If D_clock = +5 ms:  System clock is 5 ms AHEAD of UTC
If D_clock = -3 ms:  System clock is 3 ms BEHIND UTC
If D_clock = 0:      System clock equals UTC(NIST)

To correct a timestamp:
    UTC_NIST = system_time - d_clock_ms/1000
```

---

## CURRENT SYSTEM STATUS (Dec 10, 2025)

**All systems operational on bee1:**

| Service | Status | Processes |
|---------|--------|-----------|
| grape-core-recorder | ✅ active | 1 |
| grape-analytics | ✅ active | 9 |
| Data pipeline | ✅ flowing | All 3 phases |

**Data freshness:** Raw ~3s, Decimated ~100s (all channels)

---

## CRITICAL ARCHITECTURE DECISIONS

### 1. RadiodStream Migration (TODO)

**Current:** grape-recorder uses custom `RTPReceiver` + `PacketResequencer`  
**Target:** Migrate to `ka9q.stream.RadiodStream` (like time-manager)

Files to remove after migration:
- `src/grape_recorder/core/rtp_receiver.py`
- `src/grape_recorder/core/packet_resequencer.py`

Benefits:
- Automatic gap detection via `StreamQuality`
- GPS-disciplined RTP timestamps from ka9q-radio
- Consistent architecture with time-manager

### 2. Timing Delegation to time-manager

grape-recorder should NOT compute D_clock or station discrimination.
These are now owned by time-manager. grape-recorder consumes via `TimingClient`.

**Modules that stay in grape-recorder (data recording):**
- `core_recorder.py` - RTP → binary files
- `decimation.py` - 20 kHz → 10 Hz (`StatefulDecimator`)
- `carrier_spectrogram.py` - PNG generation
- `raw_archive_writer.py` - Digital RF HDF5

**Modules that now live in time-manager (timing):**
- `tone_detector.py`
- `transmission_time_solver.py`
- `wwvh_discrimination.py`
- `clock_convergence.py`
- `multi_broadcast_fusion.py`
- `phase2_temporal_engine.py`

### 3. Path Management

Use `paths.py` exclusively for all path construction:
- `channel_name_to_dir()`: "WWV 2.5 MHz" → "WWV_2.5_MHz"
- `GRAPEPaths` class: Full path resolution

**Key file:** `src/grape_recorder/paths.py`

---

## DIGITAL RF OUTPUT SPECIFICATION

### Required Metadata for PSWS

```python
# Digital RF HDF5 structure
rf@{timestamp}.h5
├── rf_data          # Complex64 IQ samples at 10 Hz
├── rf_data_index    # Sample indices for random access
└── metadata/
    ├── sample_rate: 10.0                    # Hz
    ├── center_frequency: 10000000           # Hz (channel carrier)
    ├── uuid: "unique-recording-id"
    ├── station_id: "AC0G"                   # Callsign
    ├── grid_square: "EM38ww"
    ├── receiver_lat: 38.918461
    ├── receiver_lon: -92.127974
    ├── d_clock_ms: -1.25                    # From time-manager
    ├── d_clock_uncertainty_ms: 0.55
    ├── broadcast_station: "WWV"             # From time-manager
    ├── propagation_mode: "2F"               # From time-manager
    └── gap_intervals: [[start, end], ...]   # Sample-accurate gaps
```

### Gap Annotation

Gaps must be annotated at sample-level precision:

```python
# From StreamQuality
quality = stream.get_quality()
if quality.has_gaps:
    # Record gap intervals in metadata
    gap_intervals = quality.gap_intervals  # List of (start_sample, end_sample)
```

### Daily Upload Package

```
upload/{DATE}/
├── {STATION}_{CHANNEL}_{DATE}.h5    # Digital RF file
├── {STATION}_{CHANNEL}_{DATE}.json  # Metadata summary
└── manifest.json                     # Upload manifest
```

---

## SYSTEMD SERVICES

### Production Services

| Service | Purpose | Status |
|---------|---------|--------|
| `grape-core-recorder.service` | Phase 1: RTP → raw_buffer | ✅ Active |
| `grape-analytics.service` | Phase 2: Decimation | ✅ Active |
| `grape-web-ui.service` | Web monitoring | ✅ Active |
| `time-manager.service` | Timing daemon | 🔄 TODO |

### Timers

| Timer | Schedule | Purpose |
|-------|----------|---------|
| `grape-spectrograms.timer` | Every 10 min | PNG regeneration |
| `grape-daily-upload.timer` | 00:30 UTC | PSWS upload |

---

## KNOWN ISSUES AND FIXES

### 1. Decimation Boundary Transients (FIXED)

**Problem:** Horizontal banding in spectrograms at minute boundaries  
**Fix:** `StatefulDecimator` preserves filter state across calls  
**File:** `src/grape_recorder/grape/decimation.py`

### 2. Path Coordination (FIXED)

**Problem:** Modules constructed paths independently  
**Fix:** All paths via `paths.py`  
**Verification:** 14 files refactored, zero manual constructions

### 3. D_clock Drift (FIXED in time-manager)

**Problem:** Kalman state corruption caused 6.5ms/min drift  
**Fix:** Reset on REACQUIRE, proper RTP timestamp handling  
**Recovery:** Delete `convergence_state.json` files

---

## CONFIGURATION

### grape-config.toml

```toml
[recorder]
mode = "test"  # or "production"
data_root = "/tmp/grape-test"  # or /var/lib/grape-recorder

[station]
callsign = "AC0G"
grid_square = "EM38ww"
latitude = 38.918461
longitude = -92.127974

[uploader]
enabled = false  # Enable for production
protocol = "sftp"
host = "pswsnetwork.eng.ua.edu"
```

---

## CHANNELS (9 Total)

| Station | Frequencies | Approx Distance* |
|---------|-------------|------------------|
| WWV (Ft. Collins, CO) | 2.5, 5, 10, 15, 20, 25 MHz | ~1600 km |
| WWVH (Kauai, HI) | 2.5, 5, 10, 15 MHz | ~4000 km |
| CHU (Ottawa, Canada) | 3.33, 7.85, 14.67 MHz | ~3700 km |

*From receiver at EM38ww (configured in grape-config.toml)

**Channel naming:**
- Directory: `WWV_10_MHz`, `CHU_7.85_MHz` (dots preserved!)
- Display: `WWV 10 MHz`, `CHU 7.85 MHz`
- Use `channel_name_to_dir()` from `paths.py`

---

## SAMPLE RATES

| Stage | Rate | Format |
|-------|------|--------|
| ka9q-radio RTP | 20,000 Hz | complex64 |
| Decimated output | 10 Hz | complex64 |
| File boundaries | Minute-aligned | 1,200,000 samples/min |

---

## STARTUP COMMANDS

```bash
# Test Mode
./scripts/grape-core.sh -start       # Phase 1
./scripts/grape-analytics.sh -start  # Phase 2
./scripts/grape-ui.sh -start         # Web UI (port 3000)

# Production Mode
sudo systemctl start grape-core-recorder grape-analytics grape-web-ui

# Start time-manager (for timing)
cd /home/wsprdaemon/time-manager
sudo PYTHONPATH=src /opt/grape-recorder/venv/bin/python -m time_manager \
    --config config/dev-config.toml --live
```

---

## RECOVERY COMMANDS

```bash
# D_clock drift (delete corrupted Kalman state)
rm -f /tmp/grape-test/phase2/*/status/convergence_state.json
./scripts/grape-analytics.sh -restart

# DRF writer stall
./scripts/grape-core.sh -stop
lsof +D /tmp/grape-test/raw_archive/  # Check for locked files
./scripts/grape-core.sh -start

# Web UI
./scripts/grape-ui.sh -restart
```

---

## SESSION HISTORY

| Date | Focus | Outcome |
|------|-------|---------|
| **Dec 10** | **time-manager separation** | v0.2.0 released to GitHub, per-station propagation, IRI2020, Chrony SHM |
| Dec 9-10 | Path coordination | 14 files refactored to paths.py |
| Dec 8 | Production deployment | Systemd services, StatefulDecimator |
| Dec 7 | Phase 2 critique | 16 methodology fixes |
| Dec 5-6 | Multi-broadcast fusion | 13-broadcast fusion for ±0.5ms |

---

## KEY DOCUMENTATION

| Document | Purpose |
|----------|---------|
| `INSTALLATION.md` | Setup guide |
| `docs/PHASE2_CRITIQUE.md` | Phase 2 fixes (16 items) |
| `docs/PHASE3_CRITIQUE.md` | Phase 3 fixes (7 items) |
| `docs/PATH_CONVENTIONS.md` | Three-phase path structure |
| **time-manager** | https://github.com/mijahauan/time-manager |

---

## DEPENDENCIES

**Required:**
- ka9q-radio (radiod) - RTP source
- ka9q-python - `RadiodStream`, `StreamQuality`
- scipy, numpy, matplotlib

**Optional:**
- digital_rf - HDF5 format support
- time-manager - D_clock and station discrimination
