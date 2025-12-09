# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-08  
**Version:** 3.16.0  
**Next Session Focus:** Monitor Production Stability

---

## 🎯 NEXT SESSION: MONITOR PRODUCTION STABILITY

Production mode is now running on bee1. Focus areas for next session:

1. **Verify data flow** - Check `/var/lib/grape-recorder/phase2/` for D_clock outputs
2. **Monitor spectrograms** - Timer runs every 10 min, check `products/*/spectrograms/`
3. **Test daily upload** - First PSWS upload at 00:30 UTC (Dec 9)
4. **Web UI stability** - Monitor http://bee1:3000

Key architecture is in place:

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
- Directory format: `WWV_10_MHz`, `CHU_7.85_MHz`
- Display format: `WWV 10 MHz`, `CHU 7.85 MHz`
