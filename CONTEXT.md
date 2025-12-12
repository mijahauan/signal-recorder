# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-12  
**Version:** 6.0.0  
**Status:** SIMPLIFIED - Lean architecture with external timing

---

## 🎯 GRAPE-RECORDER MISSION

**Primary Deliverable:** Daily Digital RF packages for the PSWS (Personal Space Weather Station) data repository containing time-annotated, gap-flagged, decimated IQ recordings of WWV/WWVH/CHU time station carriers.

---

## 📦 PSWS UPLOAD PRODUCT SPECIFICATION

### What We Upload Daily

Each day at 00:30 UTC, grape-recorder uploads a package to `pswsnetwork.eng.ua.edu` containing scientific-quality IQ recordings from 9 HF time station channels.

### Product Structure

```
upload/{YYYYMMDD}/
├── AC0G_WWV_2.5_MHz_{YYYYMMDD}.h5      # Digital RF HDF5
├── AC0G_WWV_2.5_MHz_{YYYYMMDD}.json    # Sidecar metadata
├── AC0G_WWV_5_MHz_{YYYYMMDD}.h5
├── AC0G_WWV_5_MHz_{YYYYMMDD}.json
├── AC0G_WWV_10_MHz_{YYYYMMDD}.h5
├── AC0G_WWV_10_MHz_{YYYYMMDD}.json
├── AC0G_WWV_15_MHz_{YYYYMMDD}.h5
├── AC0G_WWV_15_MHz_{YYYYMMDD}.json
├── AC0G_WWV_20_MHz_{YYYYMMDD}.h5
├── AC0G_WWV_20_MHz_{YYYYMMDD}.json
├── AC0G_WWV_25_MHz_{YYYYMMDD}.h5
├── AC0G_WWV_25_MHz_{YYYYMMDD}.json
├── AC0G_CHU_3.33_MHz_{YYYYMMDD}.h5
├── AC0G_CHU_3.33_MHz_{YYYYMMDD}.json
├── AC0G_CHU_7.85_MHz_{YYYYMMDD}.h5
├── AC0G_CHU_7.85_MHz_{YYYYMMDD}.json
├── AC0G_CHU_14.67_MHz_{YYYYMMDD}.h5
├── AC0G_CHU_14.67_MHz_{YYYYMMDD}.json
└── manifest.json                        # Upload inventory
```

### Digital RF HDF5 File Contents

Each `.h5` file is a standards-compliant Digital RF archive:

```
{STATION}_{CHANNEL}_{DATE}.h5
├── rf_data/                    # IQ sample data
│   └── {timestamp}/           # Sub-directory per hour
│       └── rf_data.h5         # Complex64 samples
├── rf_data_index/             # Sample index for random access
└── metadata/                  # Per-file metadata
    ├── H5Tget_order          # Byte order
    ├── sample_rate_numerator  # 10
    ├── sample_rate_denominator # 1
    ├── samples_per_second     # 10.0
    └── subdir_cadence_secs    # 3600 (1 hour)
```

### Sample Data Specifications

| Property | Value |
|----------|-------|
| **Sample rate** | 10 Hz (decimated from 20 kHz) |
| **Sample format** | complex64 (32-bit I + 32-bit Q) |
| **Samples per day** | 864,000 (10 Hz × 86,400 seconds) |
| **Bytes per day** | ~6.6 MB per channel (~60 MB total) |
| **Time alignment** | UTC(NIST) via D_clock correction |

### Sidecar JSON Metadata

Each `.json` sidecar contains scientific metadata not embedded in HDF5:

```json
{
  "version": "1.0.0",
  "station_id": "AC0G",
  "grid_square": "EM38ww",
  "receiver_latitude": 38.918461,
  "receiver_longitude": -92.127974,
  "channel": "WWV 10 MHz",
  "center_frequency_hz": 10000000,
  "sample_rate_hz": 10,
  "date": "2025-12-10",
  "samples_total": 864000,
  "samples_valid": 863500,
  "timing": {
    "source": "time-manager",
    "d_clock_mean_ms": -1.25,
    "d_clock_std_ms": 0.15,
    "clock_status": "LOCKED",
    "broadcast_station": "WWV",
    "propagation_mode": "2F"
  },
  "gaps": {
    "total_count": 3,
    "total_samples": 500,
    "intervals": [
      {"start_sample": 12000, "duration_samples": 200, "source": "rtp_loss"},
      {"start_sample": 45000, "duration_samples": 150, "source": "rtp_loss"},
      {"start_sample": 78000, "duration_samples": 150, "source": "rtp_loss"}
    ]
  },
  "quality": {
    "grade": "A",
    "completeness_percent": 99.94,
    "timing_uncertainty_ms": 0.55
  }
}
```

### Gap Handling

Gaps in the RTP stream are:
1. **Detected** by `ka9q.RadiodStream` via `StreamQuality`
2. **Filled** with zeros to maintain sample alignment
3. **Annotated** in both HDF5 metadata and sidecar JSON
4. **Flagged** with sample-accurate start/duration

Scientists can use gap annotations to exclude corrupted intervals from analysis.

---

## 🏗️ SIMPLIFIED ARCHITECTURE (Dec 2025)

### Two-Application Design

```
┌────────────────────────────────────────────────────────────────────────┐
│                         PRODUCTION SYSTEM                               │
│                                                                         │
│  ┌─────────────────┐         ┌─────────────────────────────────────┐  │
│  │  time-manager   │         │         grape-recorder              │  │
│  │  (Infrastructure)│         │         (Science Data)              │  │
│  │                 │         │                                      │  │
│  │ • D_clock       │ ──SHM──▶│ • StreamRecorder (RadiodStream)     │  │
│  │ • Station ID    │         │ • Decimation (20kHz → 10Hz)         │  │
│  │ • Chrony feed   │         │ • Digital RF packaging              │  │
│  │                 │         │ • PSWS upload                        │  │
│  └─────────────────┘         └─────────────────────────────────────┘  │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────────┐                                                   │
│  │     chronyd     │  ← System clock disciplined to UTC(NIST)         │
│  └─────────────────┘                                                   │
└────────────────────────────────────────────────────────────────────────┘
```

### grape-recorder Module Structure (Post-Cleanup)

```
src/grape_recorder/
├── __init__.py              # Package exports
├── timing_client.py         # Consumes D_clock from time-manager
├── paths.py                 # All path construction
├── channel_manager.py       # Channel discovery
├── uploader.py              # PSWS SFTP upload
├── grape/
│   ├── stream_recorder.py   # RadiodStream-based RTP intake (NEW)
│   ├── binary_archive_writer.py  # Phase 1: Raw minute files
│   ├── decimation.py        # StatefulDecimator (20kHz → 10Hz)
│   ├── phase3_product_engine.py  # Digital RF + metadata
│   ├── pipeline_orchestrator.py  # Coordinates phases
│   ├── daily_drf_packager.py     # Daily PSWS package
│   ├── carrier_spectrogram.py    # PNG generation
│   ├── tone_detector.py     # Shared with time-manager
│   └── wwvh_discrimination.py    # Shared with time-manager
└── stream/                  # Stream API utilities
```

**Removed in Dec 2025 cleanup (20,200 lines):**
- All Phase 2 timing modules (now in time-manager)
- RTPReceiver, PacketResequencer (replaced by RadiodStream)
- WSPR recorder (separate application)
- 27 obsolete Python files

---

## 🔌 INTERFACE: time-manager → grape-recorder

**Path:** `/dev/shm/grape_timing`

```json
{
  "version": "1.0.0",
  "timestamp": 1733875200.0,
  "d_clock_ms": -1.25,
  "d_clock_uncertainty_ms": 0.55,
  "clock_status": "LOCKED",
  "channels": {
    "WWV_10_MHz": {
      "station": "WWV",
      "propagation_mode": "2F",
      "d_clock_ms": -1.30,
      "snr_db": 25.0
    }
  }
}
```

### D_clock Usage

```python
from grape_recorder.timing_client import TimingClient, get_time_manager_status

# Check time-manager health
status = get_time_manager_status()
print(f"Running: {status['running']}, Healthy: {status['healthy']}")

# Get timing for annotation
client = TimingClient()
d_clock = client.get_d_clock()  # Milliseconds
station = client.get_station("WWV 10 MHz")  # "WWV" or "WWVH"

# Correct timestamp to UTC(NIST)
utc_nist = system_time - (d_clock / 1000.0)
```

---

## 🖥️ NEXT SESSION: WEB-UI SIMPLIFICATION

### Current State

The web-ui (`web-ui/`) is a Node.js Express application that provides:
- Real-time spectrogram display
- Channel status monitoring
- Timing status display
- API endpoints for data access

### Simplification Goals

1. **Remove obsolete endpoints** that reference deleted modules
2. **Simplify status displays** to reflect new architecture
3. **Update timing display** to show time-manager status
4. **Remove Phase 2 analytics UI** (timing is now external)

### Key Files to Review

```
web-ui/
├── server.js              # Express server, API routes
├── public/
│   ├── index.html         # Main dashboard
│   ├── js/
│   │   ├── main.js        # Client-side logic
│   │   └── grape-paths.js # Path utilities (sync with paths.py)
│   └── css/
│       └── style.css
├── views/                  # EJS templates (if used)
└── package.json
```

### API Endpoints to Review

| Endpoint | Current Purpose | Action |
|----------|----------------|--------|
| `/api/v1/status` | System status | Keep, simplify |
| `/api/v1/channels` | Channel list | Keep |
| `/api/v1/spectrograms` | PNG list | Keep |
| `/api/v1/timing/*` | Phase 2 timing | **Remove or redirect to time-manager** |
| `/api/v1/analytics/*` | Phase 2 analytics | **Remove** |

### Recommended Changes

1. **Add time-manager status widget** showing:
   - D_clock value and uncertainty
   - Clock status (LOCKED/ACQUIRING/HOLDOVER)
   - Channels contributing to fusion

2. **Remove Phase 2 timing displays** (no longer computed locally)

3. **Simplify channel status** to show:
   - Recording status (active/stopped)
   - Gap count
   - Last sample time

4. **Update grape-paths.js** to match cleaned-up Python paths.py

---

## 📋 QUICK REFERENCE

### Channels (9 Total)

| Station | Frequencies |
|---------|-------------|
| WWV | 2.5, 5, 10, 15, 20, 25 MHz |
| CHU | 3.33, 7.85, 14.67 MHz |

### Sample Rates

| Stage | Rate |
|-------|------|
| ka9q-radio input | 20,000 Hz |
| PSWS output | 10 Hz |

### Key Commands

```bash
# Start recording
./scripts/grape-stream.sh -start

# Check time-manager status
python -c "from grape_recorder.timing_client import get_time_manager_status; print(get_time_manager_status())"

# Run integration tests
python scripts/test_refactored_pipeline.py
```

### File Locations

| Purpose | Path |
|---------|------|
| Raw data (production) | `/var/lib/grape-recorder/raw_archive/{CHANNEL}/{YYYYMMDD}/` |
| Products (production) | `/var/lib/grape-recorder/products/{CHANNEL}/` |
| Spectrograms (production) | `/var/lib/grape-recorder/products/{CHANNEL}/spectrograms/` |
| Timing SHM | `/dev/shm/grape_timing` |
| Config (production) | `/etc/grape-recorder/grape-config.toml` |

---

## ✅ CURRENT SESSION STATE (2025-12-11 to 2025-12-12)

### Derived Products: Spectrogram + Power Plot

**Primary script (ad-hoc, for now):** `scripts/generate_spectrograms_from_raw.py`

Key improvements made:

- **X-axis alignment** between the power plot and spectrogram:
  - Uses Matplotlib `GridSpec` with a dedicated colorbar axis so both plots have identical widths.
- **Spectrogram carrier detail**:
  - Uses PSD mode with a **Blackman window** and longer FFT (`nperseg=600` at 10 Hz = 60 s) to sharpen carrier structure.
  - Uses percentile-based scaling (1st–99th) and `viridis` colormap.
- **Power plot scaling**:
  - Uses **dBFS** (`20*log10(|x|)`) and converts near-zero samples to `NaN` so gaps don’t pin the plot near 0 dB.

**Inputs/Outputs:**

- Input: `products/{CHANNEL}/decimated/{YYYYMMDD}.bin` (10 Hz complex64)
- Output: `products/{CHANNEL}/spectrograms/{YYYYMMDD}_spectrogram.png`

**Decimation script (ad-hoc):** `scripts/decimate_raw_to_10hz.py`

- Reads: `raw_archive/{CHANNEL}/{YYYYMMDD}/{minute_ts}.bin`
- Writes: `products/{CHANNEL}/decimated/{YYYYMMDD}.bin` (864,000 samples)

### Web UI: Production data root and config parsing

**Monitoring server:** `web-ui/monitoring-server-v3.js`

- Fixed argument parsing so `--config /etc/grape-recorder/grape-config.toml` is actually honored.
- Previously, `process.argv[2]` was treated as the config path; when started with `--config`, it silently fell back to `/tmp/grape-test` and the UI showed “no data” for dates that existed.

Verification:

```bash
# Confirm the server is serving the production data root
node web-ui/monitoring-server-v3.js --config /etc/grape-recorder/grape-config.toml

# Confirm a known spectrogram is reachable (example channel/date)
curl -I "http://localhost:3000/spectrograms/WWV_10_MHz/20251211_spectrogram.png"
```

---

## 🚨 CURRENT KNOWN ISSUES (MOST IMPORTANT)

### 1) “Blank” minutes that are present but zero-filled

Observed behavior:

- Raw archive minutes exist and metadata reports **100% completeness**, but the IQ samples are **>90% zeros**.
- These zero-filled minutes occur **at different times on different channels**, creating non-aligned “blanks” in spectrograms.

Implications:

- The current “gap analysis” concept (missing minutes / RTP sequence gaps) is insufficient.
- We need to treat **mostly-zero minutes** as a first-class quality failure (likely `EMPTY_PAYLOAD` / upstream silence) even if all packets arrived.

Field checks (fast, deterministic):

```bash
# Count “mostly zero” minutes for a channel on a date (example)
python3 -c "
import numpy as np
from pathlib import Path
ch='WWV_10_MHz'; date='20251212'
root=Path('/var/lib/grape-recorder/raw_archive')/ch/date
mins=sorted(root.glob('*.bin'))
bad=0
for f in mins:
    x=np.fromfile(f,dtype=np.complex64)
    if (np.abs(x)<1e-10).mean()>0.9:
        bad+=1
print(f'{ch} {date}: {bad}/{len(mins)} minutes >90% zeros')
" 
```

### 2) ka9q resequencer warnings (real discontinuities)

Logs show frequent warnings like:

- `WARNING:ka9q.resequencer:Gap: 960000 samples (48000.0ms), ~2400 packets`
- `WARNING:ka9q.resequencer:Lost packet recovery: skip to seq=...`

These indicate RTP discontinuities / resequencing behavior that should map to a **gap source** (e.g. `NETWORK_LOSS`, `RESEQUENCE_TIMEOUT`).

Field checks:

```bash
journalctl -u grape-core-recorder --since "today" --no-pager | egrep -i "Lost packet recovery|Gap:" | tail -50
```

### 3) Gap metadata under-reporting

Even when resequencer warnings occur, per-minute JSON may still show `gap_count=0`.
This suggests a mismatch between:

- ka9q stream-quality gap events
- what the minute-writer records into `{minute}.json`

This is a data-contract issue and directly affects UI + PSWS product quality.

### 4) Recorder memory usage

`grape-core-recorder` has been observed around **1.6 GB** RAM after several hours.
This needs profiling/leak-checking to improve robustness.

Field checks:

```bash
systemctl status grape-core-recorder --no-pager | head -25
ps -o pid,rss,cmd -p "$(systemctl show -p MainPID --value grape-core-recorder)"
```

---

## 🔒 NEXT SESSION GOALS (QUALITY + SECURITY + PSWS UPLOAD READINESS)

### Quality / Scientific integrity

- Define and implement **authoritative gap accounting** for the day:
  - Missing minute files (writer-level)
  - ka9q-reported discontinuities (resequencer/stream-quality)
  - “Mostly-zero minute” detection (payload-level)
- Ensure the daily products (10 Hz + DRF + sidecars) carry these as explicit, machine-readable annotations.

### Security / operational hygiene

- Validate how uploader credentials are stored/loaded:
  - No secrets in repo
  - Prefer systemd EnvironmentFile, restricted permissions, or secret manager
- Validate path/mode coordination:
  - Production must read/write under `/var/lib/grape-recorder`
  - Test mode must be explicitly selected
- Add explicit **schema versioning** for any status/state files consumed by the web UI.

### Packaging / PSWS upload readiness

- Confirm product spec alignment:
  - File naming
  - Required metadata fields
  - Checksums/manifest
- Add a pre-upload “quality gate”:
  - Minimum coverage threshold
  - Reject/flag days with excessive zero-filled minutes or large resequencer gaps

---

## 📜 SESSION HISTORY

| Date | Focus | Outcome |
|------|-------|---------|
| **Dec 10** | **Major cleanup** | Removed 27 files (20,200 lines), RadiodStream + TimingClient |
| Dec 10 | time-manager separation | v0.2.0 released, IRI2020, Chrony SHM |
| Dec 9-10 | Path coordination | 14 files refactored to paths.py |
| Dec 8 | Production deployment | Systemd services, StatefulDecimator |

---

## 🔗 DEPENDENCIES

**Required:**
- ka9q-radio (radiod) - RTP source
- ka9q-python ≥0.3.0 - `RadiodStream`, `StreamQuality`
- time-manager - D_clock and station identification
- digital_rf - HDF5 format

**Python packages:** scipy, numpy, matplotlib, h5py
