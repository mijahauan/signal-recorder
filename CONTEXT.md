# GRAPE Signal Recorder - AI Context Document

**Last Updated:** 2025-11-28  
**Next Session Goal:** Repository cleanup and beta release preparation

---

## 🎯 IMMEDIATE TASK: Beta Release Preparation

### Current State: Core Functionality Complete ✅

The GRAPE Signal Recorder is now functionally complete for beta testing:
- **Recording:** 16 kHz IQ capture from ka9q-radio working
- **Analytics:** WWV/WWVH discrimination with 8 voting methods operational
- **Decimation:** 10 Hz NPZ files generated for all 9 channels
- **DRF Upload:** Multi-subchannel Digital RF uploaded to PSWS (tested Nov 28)

### Next Session: Repository Cleanup

**Goal:** Clean up the repository of interim artifacts before creating a beta release for external testers.

#### Files/Directories to Review for Removal

**Interim Test Scripts (root directory):**
```
test-*.py                    # Various test scripts
check-*.py                   # Debug/check scripts  
debug-*.py                   # Debug scripts
*_test.py                    # Test files
```

**Session Notes (may consolidate or archive):**
```
SESSION_*.md                 # Development session notes
*_SUCCESS.md                 # Success verification docs
*_QUICKSTART.md              # May keep or consolidate
```

**Potentially Obsolete:**
```
src/signal_recorder/drf_writer_service.py   # Superseded by drf_batch_writer.py?
src/signal_recorder/uploader.py             # Check if still needed
DIFFERENTIAL_DELAY_LOGIC.md                 # Development notes
```

**Review for Relevance:**
```
docs/*.md                    # Keep useful, remove obsolete
wsprdaemon/                  # Reference code - keep or document
nohup.out                    # Runtime artifact - gitignore
```

#### Beta Release Checklist

- [ ] Remove or archive development session notes
- [ ] Consolidate test scripts or move to `tests/` directory
- [ ] Update README.md for beta users
- [ ] Create INSTALLATION.md with step-by-step setup
- [ ] Verify all systemd service files are current
- [ ] Clean up `config/grape-config.toml` comments
- [ ] Ensure `.gitignore` covers runtime artifacts
- [ ] Tag release as v0.1.0-beta

### Quick Reference: Working System

```bash
# Daily DRF upload (automatic via systemd timer, or manual)
TARGET_DATE="2025-11-28" /home/wsprdaemon/signal-recorder/scripts/daily-drf-upload.sh

# Check upload state
cat /tmp/grape-test/upload/upload-state.json | python3 -m json.tool

# Verify PSWS connection
echo "ls OBS2025*" | sftp -i ~/.ssh/id_rsa S000171@pswsnetwork.eng.ua.edu
```

---

## 1. 📡 Project Overview

**GRAPE Signal Recorder** captures WWV/WWVH/CHU time station signals via ka9q-radio SDR and:
1. Records 16 kHz IQ archives (NPZ format, 1-minute files)
2. Analyzes for WWV/WWVH discrimination (8 voting methods)
3. Decimates to 10 Hz for Digital RF format
4. Uploads to PSWS (HamSCI Personal Space Weather Station network)

### Data Pipeline
```
ka9q-radio RTP → Core Recorder (16kHz NPZ) → Analytics Service
                                                    ↓
                                           Discrimination CSVs
                                                    ↓
                                           10 Hz Decimation (NPZ)
                                                    ↓
                                           DRF Writer Service
                                                    ↓
                                           Digital RF (HDF5)
                                                    ↓
                                           SFTP Upload to PSWS
```

---

## 2. 🗂️ Key Production Files

### Core Services
| File | Purpose |
|------|---------|
| `src/signal_recorder/core_recorder.py` | 16 kHz IQ recording from ka9q-radio |
| `src/signal_recorder/analytics_service.py` | Discrimination, decimation, tone detection |
| `src/signal_recorder/drf_batch_writer.py` | Multi-subchannel DRF creator (9 channels → ch0) |
| `src/signal_recorder/upload_tracker.py` | JSON state tracking for uploads |

### Upload System
| File | Purpose |
|------|---------|
| `scripts/daily-drf-upload.sh` | Daily upload orchestration script |
| `systemd/grape-daily-upload.service` | Systemd service unit |
| `systemd/grape-daily-upload.timer` | Systemd timer (00:30 UTC daily) |
| `docs/DRF_UPLOAD_SYSTEM.md` | Complete upload system documentation |

### DRF Format (wsprdaemon-compatible)
- **Structure:** Single `ch0` with 9 subchannels (all frequencies)
- **Data:** Horizontally stacked IQ: `[WWV2.5 | CHU3.33 | ... | WWV25]`
- **Metadata:** `callsign`, `grid_square`, `lat`, `long`, `center_frequencies[]`, `uuid_str`
- **Trigger:** `cOBS{date}_\#{instrument}_\#{timestamp}` signals PSWS to process

### Configuration (`config/grape-config.toml`)
```toml
[uploader.sftp]
host = "pswsnetwork.eng.ua.edu"
user = "S000171"
ssh_key = "/home/wsprdaemon/.ssh/id_rsa"
bandwidth_limit_kbps = 0  # 0 = unlimited

[uploader.metadata]
include_extended_metadata = false  # Set true for timing/gap data
```

---

## 3. 🌐 Station Configuration

| Parameter | Value |
|-----------|-------|
| **Callsign** | AC0G |
| **Grid Square** | EM38ww |
| **PSWS Station ID** | S000171 |
| **Instrument ID** | 172 |
| **Location** | Kansas, USA (38.92°N, 92.17°W) |

### Channels (9 total, sorted by frequency)
| Frequency | Station | SSRC |
|-----------|---------|------|
| 2.5 MHz | WWV | 20025 |
| 3.33 MHz | CHU | 20333 |
| 5.0 MHz | WWV | 20050 |
| 7.85 MHz | CHU | 20785 |
| 10.0 MHz | WWV | 20100 |
| 14.67 MHz | CHU | 21467 |
| 15.0 MHz | WWV | 20150 |
| 20.0 MHz | WWV | 20200 |
| 25.0 MHz | WWV | 20250 |

---

## 4. 🔧 Quick Reference Commands

```bash
# Activate environment
cd /home/wsprdaemon/signal-recorder && source venv/bin/activate

# Start web UI (port 3000)
cd web-ui && node monitoring-server-v3.js

# Check services
systemctl status grape-core-recorder grape-radiod-monitor

# Data locations
ls /tmp/grape-test/archives/WWV_10_MHz/          # Raw 16kHz NPZ
ls /tmp/grape-test/analytics/WWV_10_MHz/decimated/  # 10Hz NPZ
ls /tmp/grape-test/analytics/WWV_10_MHz/digital_rf/ # DRF output
```

---

## 5. 📋 Recent Completions

### Nov 28: DRF Upload System ✅
- **Multi-subchannel DRF Writer:** All 9 frequencies in single ch0 (wsprdaemon-compatible)
- **Upload Tracker:** JSON state file tracks successful uploads
- **Daily Upload Script:** Orchestrates DRF creation → SFTP upload → trigger directory
- **Tested:** 35MB uploaded to PSWS in 28 seconds, trigger processed by server

### Nov 27: UI & Gap Analysis
- **Gap Analysis Page:** Functional with batch NPZ processing, scatter timeline
- **Channel Sorting:** All pages sort by frequency (WWV 2.5 → WWV 25)
- **Quota Manager:** Disk cleanup integrated
- **Discrimination UI:** Plotly charts with proper loading states

### Earlier Milestones
- **Core Recording:** 16 kHz IQ capture from ka9q-radio
- **Analytics:** WWV/WWVH discrimination with 8 voting methods
- **Decimation:** 10 Hz NPZ files for all channels
- **Web UI:** Real-time monitoring on port 3000

---

## 6. 📚 Key Documentation

| Document | Content |
|----------|---------|
| `docs/DRF_UPLOAD_SYSTEM.md` | Complete upload system documentation |
| `docs/DISCRIMINATION_SYSTEM.md` | WWV/WWVH discrimination methods |
| `docs/GAP_ANALYSIS.md` | Gap detection and analysis |
| `README.md` | Project overview (needs beta update) |

### Development Notes (candidates for cleanup)
| File | Status |
|------|--------|
| `SESSION_*.md` | Development session notes - archive or remove |
| `*_SUCCESS.md` | Verification docs - consolidate |
| `*_QUICKSTART.md` | Quick references - consolidate into README |
| `DIFFERENTIAL_DELAY_LOGIC.md` | Implementation notes - archive |
