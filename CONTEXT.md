# GRAPE Signal Recorder - AI Context Document

**Last Updated:** 2025-11-28  
**Status:** Beta release ready - repository cleaned up

---

## 🎯 Current State: Beta Release Ready

The GRAPE Signal Recorder is functionally complete for beta testing:
- **Recording:** 16 kHz IQ capture from ka9q-radio ✅
- **Analytics:** WWV/WWVH discrimination with 5 voting methods ✅
- **Decimation:** 10 Hz NPZ files for all 9 channels ✅
- **DRF Upload:** Multi-subchannel Digital RF to PSWS ✅ (tested Nov 28)
- **Repository:** Cleaned up for external testers ✅

### Quick Start for Beta Testers

```bash
# Clone and setup
git clone https://github.com/mijahauan/signal-recorder.git
cd signal-recorder
python3 -m venv venv && source venv/bin/activate
pip install -e .

# Configure
cp config/grape-config.toml.template config/grape-config.toml
# Edit with your station info and ka9q-radio address

# Run recorder
python -m signal_recorder.grape_recorder --config config/grape-config.toml

# Web UI (separate terminal)
cd web-ui && npm install && npm start
# Open http://localhost:3000
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
