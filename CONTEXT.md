# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-13  
**Version:** 3.12.0  
**Next Session Focus:** CPU Usage and Disk I/O Optimization

---

## 🎯 NEXT SESSION: CPU & DISK I/O OPTIMIZATION

### Objective
Analyze and optimize CPU usage and disk I/O to improve efficiency and reduce burden on the disk.

### Current System Profile

**Running Processes:**
- `core_recorder_v2.py` - Phase 1: RTP reception, binary IQ archiving (9 channels)
- `phase2_analytics_service.py` - Phase 2: Tone detection, D_clock (9 instances)
- `multi_broadcast_fusion.py` - Fusion service with Chrony SHM output
- `monitoring-server-v3.js` - Web UI server

**Data Flow (per channel @ 20 kHz sample rate):**
```
RTP packets → binary_archive_writer → raw_buffer/{CHANNEL}/{DATE}/{timestamp}.bin
                                                    ↓
                                    phase2_analytics_service reads every minute
                                                    ↓
                                    clock_offset_series.csv (append)
```

**Disk Write Patterns:**
- **raw_buffer**: 9.6 MB/min per channel (20 kHz × 8 bytes × 60 sec)
- **Total raw**: ~86 MB/min for 9 channels
- **Phase 2 output**: Small CSV appends (~100 bytes/min per channel)
- **Fusion output**: ~200 bytes/min

### Optimization Opportunities

1. **Binary Archive Writer** (`binary_archive_writer.py`)
   - Currently writes one 9.6 MB file per minute per channel
   - Consider: memory-mapped files, larger buffers, async I/O

2. **Phase 2 Analytics** (`phase2_analytics_service.py`)
   - Reads entire minute file for each analysis cycle
   - Consider: streaming analysis, incremental processing

3. **Disk I/O Reduction Strategies:**
   - Compress raw IQ data (complex64 → int16 with scaling?)
   - Reduce write frequency (buffer multiple minutes?)
   - Use tmpfs for intermediate data
   - Implement circular buffer with fixed disk footprint

4. **CPU Profiling Commands:**
   ```bash
   # CPU usage by process
   top -b -n 1 | grep -E "grape|python|node"
   
   # Detailed CPU profile
   py-spy record -o profile.svg --pid $(pgrep -f core_recorder_v2)
   
   # I/O statistics
   iotop -b -n 5 -P | grep -E "grape|python"
   
   # Disk write rate
   iostat -x 1 5
   ```

5. **Key Files to Analyze:**
   - `src/grape_recorder/grape/binary_archive_writer.py` - Disk write logic
   - `src/grape_recorder/grape/pipeline_orchestrator.py` - Data flow coordination
   - `src/grape_recorder/grape/phase2_analytics_service.py` - Read patterns
   - `src/grape_recorder/grape/stream_recorder_v2.py` - Sample processing

### Storage Calculations

| Component | Rate | Daily | Monthly |
|-----------|------|-------|---------|
| raw_buffer (9 ch) | 86 MB/min | 124 GB | 3.7 TB |
| Phase 2 CSVs | ~1 KB/min | 1.4 MB | 43 MB |
| Fusion CSV | ~0.2 KB/min | 0.3 MB | 9 MB |

**Current Retention:** Configurable via `storage_quota` in grape-config.toml

---

## ✅ COMPLETED THIS SESSION (Dec 13, 2025)

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
