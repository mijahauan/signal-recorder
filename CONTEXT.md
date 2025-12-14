# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-13  
**Version:** 3.13.0  
**Next Session Focus:** Monitor timing convergence, evaluate ionospheric propagation limits

---

## ✅ COMPLETED THIS SESSION (Dec 13, 2025 Evening)

### Timing Calibration Refinement - GPSDO-First Architecture

**Philosophy:** Leverage the GPSDO-disciplined RTP timestamps as the primary timing reference, then progressively refine with tone detections and multi-broadcast fusion.

#### 1. Station-Level Calibration (Not Per-Broadcast)

**Problem:** Calibrating each broadcast (station+frequency) independently introduced artificial variance because different frequencies from the same station have different ionospheric paths.

**Solution:** Calibrate at the **station level**. Each station (WWV, WWVH, CHU) transmits from a single location using a single atomic clock. The station mean is the ground truth; frequency-to-frequency variations reveal ionospheric propagation effects.

**Files Changed:**
- `multi_broadcast_fusion.py` - `_update_calibration()` now aggregates by station, not broadcast
- `multi_broadcast_fusion.py` - `_apply_calibration()` uses station-level offsets

**Calibration State:**
```json
{
  "WWV": {"offset_ms": 3.3, "uncertainty_ms": 0.47, "n_samples": 94},
  "CHU": {"offset_ms": 8.4, "uncertainty_ms": 0.58, "n_samples": 64},
  "WWVH": {"offset_ms": 9.5, "uncertainty_ms": 1.05, "n_samples": 12}
}
```

#### 2. Per-Second Tick SNR for Discrimination (Vote 4)

**Problem:** The 8-vote weighted discrimination system had Vote 4 (per-second tick SNR) implemented but not connected.

**Solution:** Added `detect_tick_windows()` call in Phase 2 engine and pass results to `finalize_discrimination()`.

**Files Changed:**
- `phase2_temporal_engine.py` - Added tick detection in Step 2B, pass to finalize_discrimination

**Impact:** 59 additional timing confirmations per minute (one per second, excluding minute marker).

#### 3. CHU FSK Timing Confirmation

**Problem:** CHU FSK decoder was implemented but timing wasn't used to confirm D_clock.

**Solution:** When CHU FSK is detected (seconds 31-39), compare FSK timing offset with D_clock:
- Agreement (<5ms): confidence +0.1, `utc_verified=True`
- Disagreement (>20ms): confidence -0.2, logged as warning

**Files Changed:**
- `phase2_temporal_engine.py` - Added CHU FSK timing confirmation in Step 3

#### 4. RTP-Based Station Prediction

**Problem:** On shared frequencies (2.5, 5, 10, 15 MHz), low-confidence discrimination caused flip-flopping between WWV and WWVH.

**Solution:** Use RTP calibration history to predict expected station:
- Store `detected_station` in RTP calibration data
- `predict_station()` method uses RTP offset to predict which station should be detected
- Override low-confidence discrimination with high-confidence RTP prediction

**Files Changed:**
- `timing_calibrator.py` - Added `predict_station()` method, extended `RPTCalibration` with `detected_station`
- `phase2_temporal_engine.py` - Added station predictor callback
- `pipeline_orchestrator.py` - Wired station predictor callback

#### 5. Reject Low-Confidence Discrimination on Shared Frequencies

**Problem:** Low-confidence discrimination results were accepted, causing station flip-flopping.

**Solution:** On shared frequencies, require at least MEDIUM confidence for discrimination. LOW confidence falls through to RTP prediction or channel name fallback.

**Files Changed:**
- `phase2_temporal_engine.py` - Added confidence check in station determination logic

#### 6. Multi-Process State File Coordination

**Problem:** 9 channel recorder processes each had their own `TimingCalibrator` instance, overwriting each other's state.

**Solution:**
- Reload state from disk before each update (merge with other processes)
- Save state after every detection during bootstrap
- Save every 5 detections after bootstrap

**Files Changed:**
- `timing_calibrator.py` - Added `_load_state()` call in `update_from_detection()`, more frequent saves

---

### CPU & Disk I/O Optimizations (Earlier)

**1. Fixed Path Inconsistency (Duplicate Directories)**
- **Problem**: `BinaryArchiveReader` used `.replace('.', '_')` but writer preserved dots
- **Impact**: CHU channels had duplicate directories (e.g., `CHU_7.85_MHz` AND `CHU_7_85_MHz`)
- **Fix**: Updated all path construction to use `channel_name_to_dir()` from `paths.py`
- **Files Changed**: `binary_archive_writer.py`, `phase2_analytics_service.py`

**2. Optional zstd/lz4 Compression**
- **Feature**: Raw IQ files can now be compressed to reduce disk I/O by 2-3x
- **Configuration** (in `grape-config.toml`):
  ```toml
  [recorder]
  compression = "zstd"  # 'none', 'zstd', or 'lz4'
  compression_level = 3  # zstd: 1-22, lz4: 1-12
  ```
- **Storage Impact**:
  | Mode | Rate | Daily | Monthly |
  |------|------|-------|---------|
  | none | 86 MB/min | 124 GB | 3.7 TB |
  | zstd | ~35 MB/min | ~50 GB | ~1.5 TB |
  | lz4 | ~50 MB/min | ~72 GB | ~2.2 TB |
- **Dependencies** (optional):
  ```bash
  pip install zstandard  # for zstd
  pip install lz4        # for lz4
  ```
- **Files Changed**: `binary_archive_writer.py`, `phase2_analytics_service.py`, `pipeline_orchestrator.py`, `stream_recorder_v2.py`, `core_recorder_v2.py`

**3. Backward Compatible Reading**
- Phase 2 analytics now auto-detects file format (`.bin`, `.bin.zst`, `.bin.lz4`)
- Uncompressed files use memory-mapping (zero-copy)
- Compressed files are decompressed on read

### Storage Calculations

| Component | Rate (uncompressed) | Rate (zstd) | Daily (zstd) |
|-----------|---------------------|-------------|--------------|
| raw_buffer (9 ch) | 86 MB/min | ~35 MB/min | ~50 GB |
| Phase 2 CSVs | ~1 KB/min | ~1 KB/min | 1.4 MB |
| Fusion CSV | ~0.2 KB/min | ~0.2 KB/min | 0.3 MB |

---

### 1. ka9q-python Upgrade to 3.2.2

**Problem:** ka9q-python 3.2.0 had a bug where `StreamQuality.last_packet_utc` returned year 2075 instead of correct UTC.

**Fix:** Upgraded to ka9q-python 3.2.2 from the correct repository:
```bash
pip install git+https://github.com/mijahauan/ka9q-python.git
```

**Files Changed:**
- `src/grape_recorder/grape/stream_recorder_v2.py` - Restored GPS-derived system_time from quality.last_packet_utc

### 2. Chrony SHM Integration (UTC(NIST) → System Clock)

**Implemented:** Fusion service now writes fused D_clock to Chrony's SHM refclock.

**Data Flow:**
```
WWV/WWVH/CHU → Phase 2 Analytics → D_clock per channel
                        ↓
              Multi-Broadcast Fusion → Fused D_clock (±0.5 ms)
                        ↓
              Chrony SHM (unit 0, refid TMGR)
                        ↓
              Chrony disciplines system clock
```

**Files Created/Modified:**
- `src/grape_recorder/grape/chrony_shm.py` - NEW: SHM refclock writer (copied from time-manager)
- `src/grape_recorder/grape/multi_broadcast_fusion.py` - Added chrony SHM integration
- `scripts/grape-analytics.sh` - Added `--enable-chrony` flag

**Chrony Configuration** (already in `/etc/chrony/chrony.conf`):
```
refclock SHM 0 refid TMGR poll 6 precision 1e-3 offset 0.0
```

**Verification:**
```bash
chronyc sources  # Look for TMGR with Reach > 0
```

**Dependencies Added:**
```bash
pip install sysv_ipc  # For System V shared memory
```

### 3. Web UI Fix (snrDb null check)

**Problem:** Timing dashboard crashed with "can't access property 'toFixed', snrDb is null"

**Fix:** Changed null check from `!== undefined` to `!= null` in `timing-dashboard-enhanced.html`

### 4. Mode Switching & Configuration Cleanup

**Single Source of Truth:** `grape-config.toml` is now authoritative for mode setting.

**Files Modified:**
- `scripts/common.sh` - `get_mode()`, `get_data_root()`, `get_log_dir()` now read from config file
- `/etc/grape-recorder/environment` - Simplified to only point to config file
- `scripts/grape-analytics.sh` - Updated to read from `raw_buffer` instead of `raw_archive`

### 5. Analytics Path Fix for raw_buffer

**Problem:** Analytics was looking for data in wrong directory structure.

**Fix:** Updated `phase2_analytics_service.py` to handle when `archive_dir` points directly to `raw_buffer/{channel}`.

**Current Data Structure:**
```
{data_root}/
├── raw_buffer/{CHANNEL}/{YYYYMMDD}/{timestamp}.bin  # Phase 1 output
├── raw_buffer/{CHANNEL}/{YYYYMMDD}/{timestamp}.json # Metadata sidecar
├── phase2/{CHANNEL}/clock_offset/                   # Phase 2 output
└── phase2/fusion/fused_d_clock.csv                  # Fusion output
```

### 6. IRI-2020 Upgrade (Earlier in Session)

**Completed:** Ionospheric model upgraded from IRI-2016 to IRI-2020 with fallback.

---

## COMPLETED EARLIER (Dec 13, 2025)

### ka9q-python RadiodStream Refactoring

**Major refactoring completed** - Core recorder now uses ka9q-python directly:

| Component | Before | After |
|-----------|--------|-------|
| RTP Reception | Custom `RTPReceiver` | ka9q-python `RadiodStream` |
| Resequencing | Custom `PacketResequencer` | Built into `RadiodStream` |
| Channel Management | Custom `ChannelManager` wrapper | ka9q-python `RadiodControl` directly |
| Code Reduction | ~1000+ lines custom | ~400 lines using ka9q-python |

**New Files Created:**
- `src/grape_recorder/grape/core_recorder_v2.py` - Uses RadiodControl directly
- `src/grape_recorder/grape/stream_recorder_v2.py` - Uses RadiodStream

**Anti-Hijacking:**
- Deterministic multicast IP from station_id + instrument_id
- Only modifies channels with our destination
- Safe multi-client operation on same radiod

**Startup Script Updated:**
- `scripts/grape-core.sh` now uses `core_recorder_v2`

---

## KEY ARCHITECTURE (Current)

### Pre-Installation Checklist

| Area | Status | Reference |
|------|--------|-----------|
| **Core Recording** | ✅ Stable | `core/` modules, `core-recorder.toml` |
| **Phase 2 Analytics** | ✅ Stable | `docs/PHASE2_CRITIQUE.md` - 16 fixes applied |
| **Phase 3 Products** | ✅ Stable | `docs/PHASE3_CRITIQUE.md` - 7 fixes applied |
| **Decimation** | ✅ Fixed | `StatefulDecimator` eliminates boundary artifacts |
| **Spectrogram Gen** | ✅ Canonical | `carrier_spectrogram.py` is the one to use |
| **Daily Upload** | ⚠️ Test | `daily-drf-upload.sh` exists but needs PSWS testing |
| **Systemd Services** | ✅ Updated | All use `EnvironmentFile=`, three-phase naming |
| **Install Script** | ✅ Updated | `scripts/install.sh` supports test/production modes |
| **Web UI** | ✅ Working | `grape-ui.sh`, port 3000 |

### Key Configuration Files

```
config/
├── grape-config.toml     # Main config: station, channels, paths, uploader
├── core-recorder.toml    # Core recorder: ka9q connection, DRF writer
└── environment           # Environment variables (create from .template)
```

### Production Path Structure

```toml
# grape-config.toml - PRODUCTION settings
[recorder]
mode = "production"
data_root = "/var/lib/grape-recorder"   # vs /tmp/grape-test

[station]
callsign = "AC0G"
grid_square = "EM38ww40pk"
latitude = 38.xxxx
longitude = -90.xxxx
```

### Systemd Services

**Continuous Services** (run 24/7):

| Service | Purpose |
|---------|---------|
| `grape-core-recorder.service` | Phase 1: RTP → DRF raw archive |
| `grape-analytics.service` | Phase 2: Timing analysis (9 channels + fusion) |
| `grape-web-ui.service` | Web monitoring UI |

**Periodic Timers** (Phase 3 products):

| Timer | Interval | Purpose |
|-------|----------|---------|
| `grape-spectrograms.timer` | Every 10 min | Regenerate spectrograms |
| `grape-daily-upload.timer` | Daily 00:30 UTC | Package 10 Hz DRF + PSWS upload |

### PSWS Upload Configuration

```toml
# grape-config.toml [uploader] section
[uploader]
enabled = true                              # Enable for production
protocol = "sftp"
host = "pswsnetwork.eng.ua.edu"
user = "YOUR_PSWS_USERNAME"
ssh_key = "/home/wsprdaemon/.ssh/psws_key"  # Must exist!
remote_base = "/incoming/grape"
bandwidth_limit_kbps = 0                    # 0 = unlimited
```

**Pre-requisite:** Generate SSH key and register with PSWS:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/psws_key -N ""
# Send public key to PSWS administrators
```

---

## CRITICAL FIXES APPLIED (Dec 8, 2025)

### 1. Decimation Filter Transients (SPECTROGRAM BUG)

**Problem:** Spectrograms showed periodic horizontal banding at minute boundaries.

**Root Cause:** 3-stage decimation filter (401-tap FIR) reset state every minute, causing ~1 second transients.

**Fix:** Created `StatefulDecimator` class that preserves filter state across calls.

**Files Changed:**
- `src/grape_recorder/grape/decimation.py` - Added `StatefulDecimator` class
- `src/grape_recorder/grape/phase2_analytics_service.py` - Uses `StatefulDecimator`

**Verification:**
```bash
# After restart, new data should have low boundary/mid variance ratio
source venv/bin/activate && python3 -c "
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

date = datetime.now(timezone.utc).strftime('%Y%m%d')
f = Path(f'/tmp/grape-test/products/WWV_10_MHz/decimated/{date}.bin')
if f.exists():
    iq = np.fromfile(f, dtype=np.complex64)
    mins = len(iq) // 600
    bv, mv = [], []
    for m in range(mins):
        s = m * 600
        b, mid = iq[s:s+10], iq[s+300:s+310]
        if np.any(b != 0):
            bv.append(np.var(np.abs(b)))
            mv.append(np.var(np.abs(mid)))
    if bv:
        r = np.mean(bv) / np.mean(mv)
        print(f'Ratio: {r:.2f}x', '✅ Fixed!' if r < 2 else '⚠️ Still elevated')
"
```

### 2. Path Consolidation

| Component | Old Path | New Path |
|-----------|----------|----------|
| DecimatedBuffer | `phase2/{CH}/decimated/` | `products/{CH}/decimated/` |
| Spectrograms | `spectrograms/{DATE}/` | `products/{CH}/spectrograms/` |
| Upload script | `signal-recorder/scripts/` | `grape-recorder/scripts/` |

### 3. Spectrogram Consolidation

**Canonical:** `carrier_spectrogram.py` with `CarrierSpectrogramGenerator`
**Deprecated:** `spectrogram_generator.py` (warnings added)
**Archived:** `scripts/generate_spectrograms_from_10hz.py`

---

## THREE-PHASE ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 1: RAW ARCHIVE (core_recorder_v2.py)                          │
│   RTP → Binary IQ @ 20 kHz (complex64)                              │
│   Output: raw_buffer/{CHANNEL}/{YYYYMMDD}/{timestamp}.bin           │
│   Metadata: raw_buffer/{CHANNEL}/{YYYYMMDD}/{timestamp}.json        │
├─────────────────────────────────────────────────────────────────────┤
│ PHASE 2: ANALYTICAL ENGINE (phase2_analytics_service.py × 9)        │
│   Tone detection, D_clock, discrimination                           │
│   Output: phase2/{CHANNEL}/clock_offset/*.csv                       │
│   Fusion: phase2/fusion/fused_d_clock.csv → Chrony SHM              │
├─────────────────────────────────────────────────────────────────────┤
│ PHASE 3: DERIVED PRODUCTS                                           │
│   Spectrograms, decimation, PSWS upload                             │
│   Output: products/{CHANNEL}/spectrograms/, upload/{DATE}/          │
└─────────────────────────────────────────────────────────────────────┘
```

### Path Synchronization

**SYNC VERSION:** `2025-12-04-v2-three-phase`

Both files must stay synchronized:
- Python: `src/grape_recorder/paths.py`
- JavaScript: `web-ui/grape-paths.js`

---

## KEY DOCUMENTATION

| Document | Purpose |
|----------|---------|
| `INSTALLATION.md` | Complete setup guide (hardware, software, configuration) |
| `ARCHITECTURE.md` | System design, data flow, module responsibilities |
| `TECHNICAL_REFERENCE.md` | API details, data formats, algorithms |
| `docs/PHASE2_CRITIQUE.md` | Phase 2 issues and fixes (16 items) |
| `docs/PHASE3_CRITIQUE.md` | Phase 3 issues and fixes (7 items) |
| `docs/PATH_CONVENTIONS.md` | Three-phase path structure |
| `CRITIC_CONTEXT.md` | Deep technical context for code review |

---

## STARTUP COMMANDS

### Test Mode
```bash
# Start all services
./scripts/grape-core.sh -start       # Phase 1
./scripts/grape-analytics.sh -start  # Phase 2
./scripts/grape-ui.sh -start         # Web UI (port 3000)

# Generate spectrograms
source venv/bin/activate
python3 -m grape_recorder.grape.carrier_spectrogram \
    --data-root /tmp/grape-test --all-channels --date $(date -u +%Y%m%d) --grid EM38ww
```

### Production Mode (after installation)
```bash
sudo systemctl enable grape-core-recorder grape-analytics grape-web-ui
sudo systemctl start grape-core-recorder grape-analytics grape-web-ui
sudo systemctl enable --now grape-daily-upload.timer
```

---

## RECOVERY COMMANDS

### D_clock Drift (Kalman State Corruption)
```bash
./scripts/grape-analytics.sh -stop
rm -f /tmp/grape-test/phase2/*/status/convergence_state.json
rm -f /tmp/grape-test/phase2/*/clock_offset/*.csv
./scripts/grape-analytics.sh -start
```

### DRF Writer Stall
```bash
./scripts/grape-core.sh -stop
# Check for locked HDF5 files
lsof +D /tmp/grape-test/raw_archive/
./scripts/grape-core.sh -start
```

### Web UI Not Responding
```bash
./scripts/grape-ui.sh -restart
# Check port 3000
ss -tlnp | grep 3000
```

---

## ENVIRONMENT VARIABLES

```bash
# Standard GRAPE environment (set in systemd or shell)
export GRAPE_DATA_ROOT=/tmp/grape-test          # or /var/lib/grape-recorder
export GRAPE_CONFIG=/home/wsprdaemon/grape-recorder/config/grape-config.toml
export GRAPE_VENV=/home/wsprdaemon/grape-recorder/venv
export GRAPE_LOG_DIR=/tmp/grape-test/logs
```

---

## SESSION HISTORY (Recent)

| Date | Focus | Key Changes |
|------|-------|-------------|
| Dec 13 PM | Chrony Integration | ka9q-python 3.2.2, Chrony SHM refclock, web UI fix, raw_buffer paths |
| Dec 13 AM | IRI-2020 Upgrade | Ionospheric model upgraded, mode switching cleanup |
| Dec 8 Night | Production Deployed | Systemd services running, matplotlib added, docs updated |
| Dec 8 Eve | Production Mode | TEST/PRODUCTION architecture, install.sh, systemd services |
| Dec 8 PM | Phase 3 Fixes | StatefulDecimator, path consolidation, spectrogram canonical |
| Dec 8 AM | Clock Drift | RTP timestamp bug, Kalman state reset, channel discovery |
| Dec 7 PM | Phase 2 Critique | 16 methodology fixes, uncertainty replaces grades |
| Dec 7 AM | BCD Correlation | Fixed BCD detection, 440Hz filtering, noise floor band |

---

## ARCHITECTURE CHANGES (Dec 13, 2025)

### Data Storage Format Change

| Component | Before | After |
|-----------|--------|-------|
| Phase 1 Output | `raw_archive/{CH}/` (DRF HDF5) | `raw_buffer/{CH}/` (binary IQ) |
| File Format | Digital RF HDF5 | Raw complex64 binary + JSON sidecar |
| Analytics Input | Read from DRF | Read from raw_buffer binary |

### New Dependencies

```bash
pip install sysv_ipc                                    # Chrony SHM
pip install git+https://github.com/mijahauan/ka9q-python.git  # ka9q-python 3.2.2
```

### Key Configuration

**grape-config.toml** is now the single source of truth for:
- `mode` ("test" or "production")
- `test_data_root` / `production_data_root`
- All channel definitions

---

## CHANNELS (9 Total)

| Station | Frequencies |
|---------|-------------|
| WWV (Ft. Collins, CO) | 2.5, 5, 10, 15, 20, 25 MHz |
| WWVH (Kauai, HI) | 2.5, 5, 10, 15 MHz (shared with WWV) |
| CHU (Ottawa, Canada) | 3.33, 7.85, 14.67 MHz |

**Channel naming convention:**
- Directory format: `WWV_10_MHz`, `CHU_7.85_MHz`
- Display format: `WWV 10 MHz`, `CHU 7.85 MHz`
