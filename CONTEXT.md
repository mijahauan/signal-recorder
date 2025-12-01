# Signal Recorder - AI Context Document

**Last Updated:** 2025-12-01  
**Version:** 2.0.0  
**Status:** Package restructure COMPLETE. **NEXT:** Update web-ui and startup scripts for new module paths.

---

## 🔴 NEXT SESSION: Web-UI Compliance with v2.0.0

### Problem Statement

The v2.0.0 package restructure moved GRAPE modules into the `grape/` subpackage. The startup scripts and web-ui still reference old module paths, causing startup failures:

```bash
$ ./scripts/grape-all.sh -start
❌ Failed to start
/home/wsprdaemon/signal-recorder/venv/bin/python3: No module named signal_recorder.core_recorder
```

### Root Cause

| Old Path (broken) | New Path (v2.0.0) |
|-------------------|-------------------|
| `signal_recorder.core_recorder` | `signal_recorder.grape.core_recorder` |
| `signal_recorder.analytics_service` | `signal_recorder.grape.analytics_service` |

### Files That Need Updates

#### 1. Startup Scripts (CRITICAL - services won't start)

| File | Issue |
|------|-------|
| `scripts/grape-core.sh` | Uses `python3 -m signal_recorder.core_recorder` |
| `scripts/grape-analytics.sh` | Uses `python3 -m signal_recorder.analytics_service` |
| `scripts/grape-all.sh` | Uses `pgrep -f "signal_recorder.core_recorder"` for status |

**Fix**: Change module paths from `signal_recorder.X` to `signal_recorder.grape.X`

#### 2. Web-UI (may have stale references)

| File | Check For |
|------|-----------|
| `web-ui/monitoring-server-v3.js` | Any Python module path references |
| `web-ui/grape-paths.js` | Already correct (uses file paths, not module paths) |
| `web-ui/utils/*.js` | Process name detection for status |

### Testing After Fixes

```bash
# 1. Stop any running services
./scripts/grape-all.sh -stop

# 2. Start services with new paths
./scripts/grape-all.sh -start

# 3. Verify status detection works
./scripts/grape-all.sh -status

# Expected output:
# ✅ Core Recorder:     RUNNING (PIDs: XXXX)
# ✅ Analytics:         RUNNING (9/9 channels)
# ✅ Web-UI:            RUNNING → http://localhost:3000/
```

---

## v2.0.0 Package Structure

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
from signal_recorder import GrapeRecorder, AnalyticsService

# But -m invocation requires FULL path:
python3 -m signal_recorder.grape.core_recorder      # ✅ Works
python3 -m signal_recorder.core_recorder            # ❌ Fails
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
nohup python3 -m signal_recorder.core_recorder --config "$CONFIG" \

# FIX:
nohup python3 -m signal_recorder.grape.core_recorder --config "$CONFIG" \
```

### grape-analytics.sh (lines 68, 91)

```bash
# CURRENT (broken):
nohup python3 -m signal_recorder.analytics_service \

# FIX:
nohup python3 -m signal_recorder.grape.analytics_service \
```

### grape-all.sh (status detection, lines 78-85)

```bash
# CURRENT (broken):
CORE_COUNT=$(pgrep -f "signal_recorder.core_recorder" 2>/dev/null | wc -l)

# FIX:
CORE_COUNT=$(pgrep -f "signal_recorder.grape.core_recorder" 2>/dev/null | wc -l)
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

## Session History

### Dec 1, 2025 (Morning): v2.0.0 Release
- **Merged** `feature/generic-rtp-recorder` to main
- **Tagged** v2.0.0
- **GitHub Release** created with release notes
- **Fixed** `TimingMetricsWriter.get_ntp_offset()` removal bug
- **Updated** README.md and TECHNICAL_REFERENCE.md
- **Discovered** startup scripts use old module paths (need fixing)

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
