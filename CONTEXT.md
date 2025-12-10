# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-10  
**Version:** 4.0.0  
**Status:** REFACTORING IN PROGRESS - time-manager + grape-recorder

---

## 🎯 TWO-APPLICATION ARCHITECTURE (In Progress)

The system is being refactored into two separate applications. **Phase A complete.**

### Application 1: time-manager (Infrastructure)
**Location:** `/home/wsprdaemon/time-manager/`  
**Status:** Package structure created, daemon implemented

A general-purpose precision timing daemon that:
- Receives RTP streams from ka9q-radio (radiod)
- Extracts UTC(NIST) from WWV/WWVH/CHU broadcasts
- Computes D_clock via multi-broadcast fusion
- Owns station discrimination (prerequisite for timing!)
- Publishes to `/dev/shm/grape_timing` for consumers
- Optionally feeds chronyd via SHM refclock

**Key insight:** Discrimination is NOT a science product—it's a dependency of the clock. To recover UTC(NIST), you must know the path length. To know the path length, you must know the station. Therefore, time-manager must own the discriminator.

### Application 2: grape-recorder (Science Client)
**Location:** `/home/wsprdaemon/grape-recorder/`  
**Status:** TimingClient created, pending integration

A GRAPE-specific science data recorder that:
- Consumes timing from time-manager via `TimingClient`
- Records IQ data with corrected timestamps
- Generates spectrograms and science products
- Uploads to PSWS network
- Focused on HamSCI GRAPE experiment requirements

### Why This Architecture?
- **Reuse**: WSPR daemon, FT8 decoder can use time-manager for timing
- **Stability**: If PSWS upload crashes, system clock stays synchronized
- **Clean separation**: Physics/math in one box, data logging in another
- **Chrony integration**: Entire Linux OS gets "GPS-quality" time

### Key Files Created

| Application | File | Purpose |
|-------------|------|---------|
| time-manager | `src/time_manager/main.py` | Main daemon entry point |
| time-manager | `src/time_manager/output/shm_writer.py` | SHM output for consumers |
| time-manager | `src/time_manager/output/chrony_shm.py` | Chrony refclock driver |
| time-manager | `src/time_manager/interfaces/timing_result.py` | Data contract |
| grape-recorder | `src/grape_recorder/timing_client.py` | Consumes time-manager |

### Interface Contract

**Shared Memory:** `/dev/shm/grape_timing`

```json
{
  "version": "1.0.0",
  "d_clock_ms": -1.25,
  "d_clock_uncertainty_ms": 0.55,
  "clock_status": "LOCKED",
  "channels": {
    "WWV_10_MHz": {
      "station": "WWV",
      "confidence": "high",
      "propagation_mode": "1F2"
    }
  }
}
```

### Next Steps
1. Copy timing modules from grape-recorder to time-manager
2. Test time-manager standalone
3. Integrate TimingClient into grape-recorder
4. Enable Chrony SHM for system clock discipline

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

## CRITICAL FIXES APPLIED (Dec 9-10, 2025)

### 1. Path Coordination (ROOT CAUSE OF MANY BUGS)

**Problem:** Different modules constructed paths independently, causing mismatches.

**Fix:** Enforced centralized path management via `paths.py`:
- `channel_name_to_dir()`: "WWV 2.5 MHz" → "WWV_2.5_MHz" (dots PRESERVED)
- `dir_to_channel_name()`: reverse conversion
- `GRAPEPaths` class: full path resolution

**14 files refactored** to use `paths.py` exclusively. Zero manual path constructions remain.

**Key file:** `src/grape_recorder/paths.py`

### 2. Systemd Service Fixes

| Issue | Fix |
|-------|-----|
| `User=grape-recorder` | Changed to `User=wsprdaemon` |
| `Type=simple` for analytics | Changed to `Type=oneshot` + `RemainAfterExit=yes` |
| `ProtectHome=read-only` | Disabled (matplotlib needs ~/.config) |
| `${GRAPE_PROJECT}` variables | Hardcoded paths in `/etc/systemd/system/` |

### 3. Raw Buffer vs Raw Archive

**Current architecture:**
- Phase 1 writes to `raw_buffer/` (binary files, minute-aligned)
- Phase 2 reads from `raw_buffer/` (not `raw_archive/`)
- `raw_archive/` intended for Digital RF format (not currently used)

**Data flow:**
```
radiod (RTP) → core_recorder → raw_buffer/{CHANNEL}/{DATE}/{minute}.bin
                                    ↓
                            phase2_analytics_service
                                    ↓
                            products/{CHANNEL}/decimated/
                                    ↓
                            products/{CHANNEL}/spectrograms/
```

---

## THREE-PHASE ARCHITECTURE

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

---

## PROPOSED MODULE SPLIT FOR REFACTORING

### Modules → time-manager (Timing-specific)

| Module | Purpose | Notes |
|--------|---------|-------|
| `tone_detector.py` | Detect WWV/WWVH 1000/1200 Hz tones | Core timing extraction |
| `transmission_time_solver.py` | Compute propagation delay | Uses lat/lon, ionospheric model |
| `clock_convergence.py` | Kalman filter for D_clock | Welford's algorithm deprecated |
| `multi_broadcast_fusion.py` | Fuse 13 broadcasts to UTC(NIST) | Station calibration |
| `wwvh_discrimination.py` | Distinguish WWV vs WWVH | 8 discrimination methods |
| `wwv_bcd_encoder.py` | Decode BCD time code | 100 Hz subcarrier |
| `wwv_tone_schedule.py` | Minute-specific tone schedule | Station ID timing |
| `gpsdo_monitor.py` | Monitor GPSDO lock state | Set/Monitor/Intervene |
| `utc_calibration.py` | Generate UTC calibration | From tone arrivals |
| `phase2_temporal_engine.py` | Orchestrate timing pipeline | Process minute → D_clock |

### Modules → grape-recorder (GRAPE-specific)

| Module | Purpose | Notes |
|--------|---------|-------|
| `core_recorder.py` | RTP → binary files | Phase 1 ingestion |
| `binary_archive_writer.py` | Write raw_buffer | Minute-aligned files |
| `raw_archive_writer.py` | Write Digital RF | HDF5 format (future) |
| `decimation.py` | 20 kHz → 10 Hz | StatefulDecimator |
| `decimated_buffer.py` | Store decimated data | Binary + JSON metadata |
| `carrier_spectrogram.py` | Generate PNG spectrograms | Phase 3 product |
| `phase2_analytics_service.py` | Orchestrate Phase 2 | Would use time-manager API |
| `phase3_products_service.py` | Orchestrate Phase 3 | Spectrograms, uploads |

### Shared/Utility Modules

| Module | Purpose | Goes To |
|--------|---------|---------|
| `paths.py` | Centralized path management | Both (or shared library) |
| `wwv_constants.py` | Station coordinates, frequencies | time-manager |
| `async_disk_writer.py` | Non-blocking disk I/O | grape-recorder |

### API Interface (time-manager → grape-recorder)

The time-manager should expose:
```python
class TimeManager:
    def get_current_d_clock(channel: str) -> DClockResult
    def get_station_for_frequency(freq_hz: int, minute: int) -> str
    def get_propagation_delay(station: str, freq_hz: int) -> float
    def get_fusion_result() -> FusionResult
    def subscribe_to_timing_events(callback) -> None
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
│ PHASE 1: RAW ARCHIVE                                                │
│   RTP → DRF @ 20 kHz                                                │
│   Output: raw_archive/{CHANNEL}/rf@*.h5                             │
├─────────────────────────────────────────────────────────────────────┤
│ PHASE 2: ANALYTICAL ENGINE                                          │
│   Tone detection, D_clock, discrimination, decimation               │
│   Output: phase2/{CHANNEL}/*.csv, products/{CH}/decimated/*.bin     │
├─────────────────────────────────────────────────────────────────────┤
│ PHASE 3: DERIVED PRODUCTS                                           │
│   Spectrograms, DRF packaging, PSWS upload                          │
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
| **Dec 9-10** | **Path Coordination Fix** | 14 files refactored to use paths.py, systemd fixes, pipeline verified |
| Dec 8 Night | Production Deployed | Systemd services running, matplotlib added, docs updated |
| Dec 8 Eve | Production Mode | TEST/PRODUCTION architecture, install.sh, systemd services |
| Dec 8 PM | Phase 3 Fixes | StatefulDecimator, path consolidation, spectrogram canonical |
| Dec 8 AM | Clock Drift | RTP timestamp bug, Kalman state reset, channel discovery |
| Dec 7 PM | Phase 2 Critique | 16 methodology fixes, uncertainty replaces grades |
| Dec 7 AM | BCD Correlation | Fixed BCD detection, 440Hz filtering, noise floor band |
| Dec 6 | Audio Simplification | Removed radiod audio, AM demod from IQ |
| Dec 5 | Multi-Broadcast Fusion | 13-broadcast fusion for ±0.5ms accuracy |

---

## NEXT SESSION PRIORITIES

1. **Monitor Production** - Verify Phase 2 outputs in `/var/lib/grape-recorder/phase2/`
2. **Check Spectrograms** - Timer runs every 10 min, verify PNG generation
3. **Daily Upload Test** - First PSWS upload scheduled for 00:30 UTC (Dec 9)
4. **Storage Quota** - Configure cleanup for production disk space
5. **Backup Strategy** - Decide what to preserve, what to rotate

### Completed This Session (Dec 8 Night)

- ✅ Deployed production mode with systemd services on bee1
- ✅ Fixed systemd service paths (hardcoded instead of env vars for WorkingDirectory)
- ✅ Added matplotlib and pandas to `setup.py` install_requires
- ✅ Updated `ka9q` dependency to use PyPI instead of git URL
- ✅ Updated carrier.html with 10-minute auto-refresh and regenerate button
- ✅ Updated timing-methodology.html for production (systemd commands, fusion service)
- ✅ Updated discrimination-methodology.html (8 methods, correct weights)
- ✅ Fixed web-ui service to use `monitoring-server-v3.js`

### Completed Dec 8 Evening

- ✅ Renamed `signal-recorder` → `grape-recorder` in all paths
- ✅ Updated `grape-config.toml` with correct production path
- ✅ Created `config/environment.template` with full documentation
- ✅ Updated all systemd services to use `EnvironmentFile=`
- ✅ Updated `scripts/install.sh` with three-phase directory structure
- ✅ Updated `INSTALLATION.md` with mode switching guide

### Key Architecture Changes

| Component | Before | After |
|-----------|--------|-------|
| Production data root | `/var/lib/signal-recorder` | `/var/lib/grape-recorder` |
| Systemd paths | Hardcoded | Via `EnvironmentFile=/etc/grape-recorder/environment` |
| Service names | `grape-recorder` | `grape-core-recorder` (Phase 1) |
| Install directories | Legacy `archives/`, `analytics/` | Three-phase: `raw_archive/`, `phase2/`, `products/` |

---

## CHANNELS (9 Total)

| Station | Frequencies |
|---------|-------------|
| WWV (Ft. Collins, CO) | 2.5, 5, 10, 15, 20, 25 MHz |
| WWVH (Kauai, HI) | 2.5, 5, 10, 15 MHz (shared with WWV) |
| CHU (Ottawa, Canada) | 3.33, 7.85, 14.67 MHz |

**Channel naming convention:**
- Directory format: `WWV_10_MHz`, `CHU_7.85_MHz` (dots preserved!)
- Display format: `WWV 10 MHz`, `CHU 7.85 MHz`
- **CRITICAL:** Use `channel_name_to_dir()` from `paths.py`, never manual string replace

---

## KEY TECHNICAL DETAILS FOR REFACTORING

### Timing Architecture (Two-Tier)

1. **Operational timing** (Phase 1): NTP + GPSDO offset (~1-10ms)
   - Used for file boundaries and real-time operations
   - Stable, non-disruptive

2. **Scientific timing** (Phase 2): Tone-based calibration (~50µs)
   - Generated when Kalman filter reaches Grade A
   - Stored in `state/utc_calibration.json`
   - Formula: `rtp_to_utc_offset = (utc_minute + prop_delay) - (tone_rtp / sample_rate)`

### Multi-Broadcast Fusion

**13 broadcasts from 9 frequencies:**
- 5 unique: CHU 3.33/7.85/14.67, WWV 20/25 MHz
- 8 shared (need discrimination): 2.5/5/10/15 MHz × (WWV + WWVH)

**Fusion formula:**
```python
fused_d_clock = Σ(weight × (raw + calibration_offset)) / Σ(weight)
```

### Station Discrimination (8 Methods)

1. BCD correlation (100 Hz subcarrier)
2. Power ratio (WWV typically stronger for US receivers)
3. Geographic ToA prediction
4. 440 Hz station ID (minute 2)
5. 500/600 Hz tone detection (29/30, 59/00 second windows)
6. Test signal (minutes 8/44)
7. Tick window timing
8. Overall 1000/1200 Hz tone strength

### GPSDO Monitor States

- `STARTUP`: No anchor, need full search
- `STEADY_STATE`: Projecting time, verifying with tones
- `HOLDOVER`: Drift alarm, data flagged
- `REANCHOR`: Discontinuity detected, must re-anchor

### Important Bug Fixes to Preserve

1. **Floating point precision** (tone_detector.py:249): `int((time + 0.5) / 60) * 60`
2. **Kalman state reset** (clock_convergence.py): Reset on REACQUIRE state
3. **RTP timestamp** (phase2_analytics_service.py): Read from metadata, don't synthesize
4. **StatefulDecimator** (decimation.py): Preserves filter state across calls

### Dependencies

**External:**
- ka9q-radio (radiod) - RTP source
- ka9q-python - RTP/multicast handling
- digital_rf (optional) - HDF5 format support
- scipy, numpy, matplotlib

**Internal flow:**
```
ka9q-radio → RTP multicast → core_recorder → raw_buffer
                                    ↓
                           phase2_analytics → decimated → spectrograms
```

### Station Coordinates (Precise)

```python
WWV_COORDS = (40.67805, -105.04694)   # Ft. Collins, CO
WWVH_COORDS = (21.9914, -159.7644)    # Kauai, HI
CHU_COORDS = (45.2958, -75.7544)      # Ottawa, Canada
```

Receiver: lat=38.918461, lon=-92.127974 (configured in grape-config.toml)

### Sample Rates

- Raw IQ from radiod: 20,000 Hz (complex64)
- Decimated for spectrograms: 10 Hz
- Tone detection: Matched filter at 20 kHz
- File boundaries: Minute-aligned (1,200,000 samples/minute)
