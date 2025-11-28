# GRAPE Signal Recorder - AI Context Document

**Last Updated:** 2025-11-28 (afternoon session)  
**Status:** Beta release ready - active discrimination refinement

---

## 🎯 Current Focus: Discrimination Refinement

The core system is complete. Current work focuses on **tuning the WWV/WWVH discrimination methodology** to maximize scientific value.

### Immediate Priorities for Next Session

1. **Discrimination Scoring Weights** - The weighted voting system needs tuning:
   - 500/600 Hz ground truth (weight=10) can be overridden by other methods (combined weight=12)
   - User chose to keep current balance - disagreements show mixed propagation
   - Consider adaptive weights based on signal conditions
   
2. **Differential Doppler Display** - Maximize information in Vote 6 panel:
   - Current: Shows WWV/WWVH Δf_D traces with solar elevation
   - Want: Better visualization of coherence window, quality metrics
   - Data available: `doppler_wwv_hz`, `doppler_wwvh_hz`, `doppler_quality`, coherence time
   
3. **440 Hz Detection Sensitivity** - Improved this session:
   - Changed from simple FFT to coherent integration (~30 dB gain)
   - Now matches 1000/1200 Hz detector sensitivity
   - Should see WWV 440 Hz at minute :02 more often

### Recent Session Work (Nov 28)

- ✅ **440 Hz Coherent Integration:** Quadrature matched filter with 44 one-second segments
- ✅ **Timing Dashboard:** Refined categories (TONE_LOCKED, TONE_STABLE, TONE_AGED)
- ✅ **Service Scripts:** `scripts/grape-*.sh` with -start|-stop|-status flags
- ✅ **Major Cleanup:** Organized 140+ files into `archive/` directories
- ✅ **Ground Truth Analysis:** Explained why disagreements occur (mixed propagation)

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

# Start all services
./scripts/grape-all.sh -start

# Or individually:
./scripts/grape-core.sh -start
./scripts/grape-analytics.sh -start
./scripts/grape-ui.sh -start

# Check status
./scripts/grape-all.sh -status

# Web UI: http://localhost:3000
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

## 5. � Discrimination System Details

### Weighted Voting (8 Methods)

The discrimination system uses weighted voting across multiple independent methods:

| Vote | Method | Weight | Minutes Active |
|------|--------|--------|----------------|
| 0 | Test Signal | 15 | :08, :44 only |
| 1 | 440 Hz Station ID | 10 | :01 (WWVH), :02 (WWV) |
| 2 | BCD Amplitude Ratio | 2-10 | All (higher in BCD minutes) |
| 3 | 1000/1200 Hz Power Ratio | 1-10 | All |
| 4 | Tick SNR Average | 5 | All |
| 5 | 500/600 Hz Ground Truth | 10 | 14 exclusive minutes/hour |
| 6 | Differential Doppler | 2 | When quality > 0.3 |
| 7 | Timing Coherence | 3 | :08, :44 when test signal + BCD |

**Key Insight:** Ground truth (Vote 5) can be overridden when other methods collectively disagree. This is by design - a "disagreement" shows mixed propagation where dominant station differs from ground truth detection.

### Key Files for Discrimination

| File | Purpose |
|------|---------|
| `src/signal_recorder/wwvh_discrimination.py` | Main discrimination logic, all 8 voting methods |
| `src/signal_recorder/tone_detector.py` | 1000/1200 Hz matched filter detection |
| `web-ui/discrimination.html` | 7-panel visualization UI |

### CSV Outputs (per channel)

```
analytics/{channel}/tone_detections/     # 1000/1200 Hz power, timing
analytics/{channel}/tick_windows/        # Per-second tick SNR
analytics/{channel}/station_id_440hz/    # 440 Hz ground truth
analytics/{channel}/bcd_discrimination/  # BCD correlation peaks
analytics/{channel}/discrimination/      # Final weighted voting result
analytics/{channel}/doppler/             # Differential Doppler measurements
```

---

## 6. 📋 Session History

### Nov 28 Afternoon: Discrimination Refinement
- **440 Hz Coherent Integration:** ~30 dB processing gain via quadrature matched filter
- **Timing Dashboard:** TONE_LOCKED (<5min), TONE_STABLE (low drift), TONE_AGED (>5min)
- **Service Scripts:** `grape-all.sh`, `grape-analytics.sh`, `grape-core.sh`, `grape-ui.sh`
- **Repository Cleanup:** 88 dev-history docs, 22 shell scripts, 14 test scripts → `archive/`
- **Analysis:** Ground truth disagreements explained (mixed propagation, not bugs)

### Nov 28 Morning: DRF Upload System
- **Multi-subchannel DRF Writer:** All 9 frequencies in single ch0 (wsprdaemon-compatible)
- **Upload Tracker:** JSON state file tracks successful uploads
- **Tested:** 35MB uploaded to PSWS in 28 seconds

### Nov 27: UI & Gap Analysis
- **Gap Analysis Page:** Batch NPZ processing, scatter timeline
- **Channel Sorting:** All pages sort by frequency

---

## 7. 📚 Documentation Structure

| Location | Content |
|----------|---------|
| `README.md` | Project overview, quick start, architecture |
| `ARCHITECTURE.md` | Detailed system design |
| `TECHNICAL_REFERENCE.md` | Implementation details |
| `INSTALLATION.md` | Setup guide |
| `docs/` | Feature-specific documentation |
| `archive/dev-history/` | Session notes and design docs |
| `archive/shell-scripts/` | Legacy scripts (superseded by grape-*.sh) |
| `archive/test-scripts/` | Development test scripts |

---

## 8. 🔧 Service Control

```bash
# All services
./scripts/grape-all.sh -start|-stop|-status

# Individual services
./scripts/grape-core.sh -start       # Core recorder (ka9q-radio → 16kHz NPZ)
./scripts/grape-analytics.sh -start  # Analytics (9 channels)
./scripts/grape-ui.sh -start         # Web UI (port 3000)
```

---

## 9. 🎯 Next Session Goals

1. **Tune Discrimination Weights:** Experiment with ground truth authority vs. mixed propagation detection
2. **Enhance Doppler Display:** Show coherence window (T_c), add statistics, improve visualization
3. **Validate 440 Hz Improvement:** Confirm WWV minute :02 detections with new coherent integration
