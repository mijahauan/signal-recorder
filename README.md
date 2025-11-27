# GRAPE Signal Recorder

**Precision WWV/CHU time-standard recorder for ionospheric research** - Captures high-precision IQ data from ka9q-radio, performs 5-method WWV/WWVH discrimination, and uploads Digital RF to HamSCI PSWS.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

The [HamSCI GRAPE project](https://hamsci.org/grape) studies ionospheric disturbances through timing variations in WWV/CHU broadcasts. This recorder enables amateur radio operators to contribute scientifically valid data to the global observation network.

**Key Capabilities:**
- 📡 **Multi-channel recording** - Simultaneous WWV 2.5-25 MHz, CHU 3.33-14.67 MHz
- 🎯 **GPS-quality timing** - ±1ms via tone detection (time_snap mechanism)
- 🔬 **5 discrimination methods** - Timing tones, ticks, 440 Hz ID, BCD, weighted voting
- 📊 **Digital RF output** - 10 Hz IQ + metadata (wsprdaemon-compatible)
- 🌐 **Web UI** - Real-time monitoring, configuration, quality metrics
- 🚀 **PSWS upload** - Automated rsync to HamSCI repository

## Quick Start

**Prerequisites:** ka9q-radio, Linux with multicast, Python 3.8+, Node.js 16+

```bash
# Install
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder
python3 -m venv venv && source venv/bin/activate && pip install -e .
cd web-ui && pnpm install

# Configure via Web UI
cd web-ui && pnpm start  # http://localhost:3000
# OR edit config/grape-config.toml manually

# Run (test mode safe for initial setup)
signal-recorder daemon --config config/grape-config.toml
```

**Test vs Production:** Set `mode = "test"` in config for `/tmp/grape-test` (temporary), or `mode = "production"` for `/var/lib/signal-recorder` (persistent).

**Monitor:** `http://localhost:3000/monitoring` - Real-time channel health, quality metrics, logs

## Architecture

**Three-service design** for reliability and reprocessability:

```
ka9q-radio (RTP multicast) → Core Recorder → Analytics → DRF Writer/Upload
                              16kHz NPZ      10Hz NPZ   Digital RF HDF5
                              archives/      analytics/ → PSWS rsync
```

**1. Core Recorder** (`grape_channel_recorder_v2.py`) - Rock-solid archiving
- RTP → resequencing → gap fill → 16 kHz NPZ (complete record)
- ~300 lines, changes <5x/year, minimal dependencies

**2. Analytics Service** (`analytics_service.py`) - 5 discrimination methods
- Method 1: Timing Tones (1000/1200 Hz power ratio)
- Method 2: Tick Windows (5ms coherent analysis)
- Method 3: Station ID (440 Hz at minutes 1/2)
- Method 4: BCD (100 Hz subcarrier)
- Method 5: Weighted Voting (final determination)
- Decimation: 16 kHz → 10 Hz (optimized 3-stage FIR)
- Output: Separated CSVs per method + 10 Hz NPZ with embedded metadata

**3. DRF Writer** (`drf_writer_service.py`) - Wsprdaemon-compatible
- Reads 10 Hz NPZ → writes Digital RF HDF5 (float32 I/Q pairs)
- Two modes: wsprdaemon-compatible (default) or enhanced metadata
- Automated rsync upload to HamSCI PSWS

**Design Principles:**
- **Reprocessability:** 16 kHz archives preserved, analytics can rerun
- **Canonical contracts:** All paths via `GRAPEPaths` API ([CANONICAL_CONTRACTS.md](CANONICAL_CONTRACTS.md))
- **Separation:** Core never stops, analytics restartable, DRF independent
- **Time_snap:** WWV/CHU tones anchor RTP to UTC (±1ms GPS-quality)

## Quality Metrics

- **Completeness:** 🟢 ≥99% | 🟡 95-99% | 🔴 <95%
- **Timing Drift:** RTP vs system clock (<±50ms healthy)
- **Packet Loss:** <1% healthy (indicates network issues)
- **Time_snap Quality:** TONE_LOCKED (±1ms) > NTP_SYNCED (±10ms) > WALL_CLOCK (±seconds)

## 🔬 WWV/WWVH Discrimination (5 Methods)

Separate WWV (Fort Collins) and WWVH (Kauai) signals on shared frequencies (2.5, 5, 10, 15 MHz) using complementary measurement techniques:

**Method 1: 440 Hz ID Tones** (2/hour)  
Unambiguous station identification. WWVH transmits minute 1, WWV minute 2.  
✅ Highest confidence - ground truth calibration

**Method 2: BCD Correlation** (15/min) 🚀 PRIMARY  
Cross-correlation of 100 Hz BCD time code finds two peaks = two stations.  
✅ Highest temporal resolution - captures ionospheric dynamics  
✅ Measures amplitude AND differential delay simultaneously  
✅ Optimized performance: 3-second steps (Nov 2025)

**Method 3: Timing Tones** (1/min)  
Power ratio of 1000 Hz (WWV) vs 1200 Hz (WWVH) marker tones.  
✅ Reliable baseline - works even with weak signals

**Method 4: Tick Windows** (6/min)  
Per-second tick analysis with adaptive coherent/incoherent integration.  
✅ Sub-minute dynamics - tracks rapid propagation changes

**Method 5: Weighted Voting** (1/min)  
Combines all methods with minute-specific weighting for final determination.  
✅ Robust - leverages strengths of each method

**Why 5 Methods?**
- **Redundancy:** Multiple independent measurements validate each other
- **Adaptability:** Different methods excel under different propagation conditions  
- **Temporal Coverage:** From hourly calibration to sub-second dynamics
- **Cross-Validation:** Agreement confirms accuracy, disagreement reveals complexity

**Quick Check:** View `http://localhost:3000/discrimination.html` for 7-panel analysis with method labels and performance statistics.

**Learn More:** [docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md](docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md)

## Web UI

**Configuration:** Station setup, channel presets, PSWS credentials, TOML export  
**Monitoring:** Real-time health, metrics, logs (auto-refresh 30s)  
**Stack:** Node.js/Express, vanilla JS, JSON storage

## Documentation

**Core Contracts** (consult before code changes):
- [CANONICAL_CONTRACTS.md](CANONICAL_CONTRACTS.md) - Project standards ⭐ START HERE
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design (WHY)
- [DIRECTORY_STRUCTURE.md](DIRECTORY_STRUCTURE.md) - Paths & naming (WHERE)
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) - Functions (WHAT)
- [CONTEXT.md](CONTEXT.md) - AI assistant context transfer

**Setup & Operations:**
- [INSTALLATION.md](INSTALLATION.md) - Detailed setup
- [docs/DRF_WRITER_MODES.md](docs/DRF_WRITER_MODES.md) - Wsprdaemon vs enhanced metadata
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - systemd configuration
- [docs/troubleshooting.md](docs/troubleshooting.md) - Common issues


## Requirements

**Hardware:** SDR (RX888/Airspy/SDRPlay), HF antenna (2.5-25 MHz), Linux 1+ GB RAM  
**Software:** ka9q-radio, Python 3.8+ (digital_rf≥3.0, scipy≥1.7, numpy≥1.20), Node.js 16+, rsync  
**Network:** Multicast-capable, internet for upload, ports 3000 (web UI), 5004 (RTP)

## Configuration Example

Edit `config/grape-config.toml` or use Web UI (recommended):

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"

[recorder]
mode = "test"  # or "production"

[[recorder.channels]]
ssrc = 10000000
frequency_hz = 10000000
description = "WWV 10 MHz"
enabled = true

[uploader]
enabled = false  # Set true after PSWS credentials configured
```

## Workflow

**Setup:** Install ka9q-radio → Install recorder → Configure via Web UI → Test mode (5 min) → Production mode → PSWS SSH keys  
**Daily:** Daemon runs via systemd, monitor web UI for 🟢 status, auto-upload every 5 min  
**Maintenance:** Check weekly, verify uploads, review logs


## Troubleshooting

**No data:** Check `radiod` running, multicast routing, firewall (allow 5004/udp, 3000/tcp)  
**Completeness <99%:** Network congestion, multicast switch config  
**Timing drift >50ms:** Verify NTP (`timedatectl`), check radiod clock sync  
**Packet loss >1%:** Increase RTP buffer, check CPU, reduce channels

See [docs/troubleshooting.md](docs/troubleshooting.md) for details.

## Recent Updates

**November 26, 2025 - Geographic BCD Discrimination & Spectrogram Solar Overlays** ✅
- **Geographic Peak Assignment:** BCD dual-peak discrimination now uses geographic ToA prediction to correctly assign WWV/WWVH to early/late correlation peaks based on receiver location
- **Test Signal ToA Offset:** Added time-of-arrival offset measurement for test signals (minutes :08/:44) providing high-precision ionospheric channel characterization
- **Carrier Page Fixed:** Date picker now scans 10 Hz NPZ files in `analytics/{channel}/decimated/` instead of requiring pre-existing spectrograms
- **Solar Zenith Overlays:** Spectrograms now include WWV path (red) and WWVH path (purple) solar elevation curves
- **Spectrogram Generation:** `scripts/generate_spectrograms_from_10hz.py` generates 24-hour spectrograms from decimated NPZ files with automatic solar zenith overlay
- See `CONTEXT.md` for technical details and next session goals

**November 26, 2025 - Timing Dashboard & Wall Clock Stability** ✅
- **Fixed:** `ntp_wall_clock_time` now uses stable RTP-derived prediction instead of jittery `time.time()` capture
- **Result:** Sub-microsecond wall clock stability (was ±2 seconds due to packet arrival jitter)
- **New:** Interactive timing dashboard with drift analysis and time source timeline charts
- **New:** Quality level legend explaining TONE_LOCKED, NTP_SYNCED, INTERPOLATED, WALL_CLOCK
- **Web UI:** `http://localhost:3000/timing-dashboard-enhanced.html` - Real-time timing visualization
- See timing documentation in `docs/TIMING_ANALYSIS_UI_DESIGN.md`

**November 24, 2025 - Analytics Metadata Integration** ✅
- Analytics now reads and validates recorder-provided time_snap metadata
- Archive time_snap adoption: Analytics automatically uses superior timing references from NPZ files
- Tone power cross-validation: Compares recorder startup measurements with analytics detections
- Complete metadata flow verified: Recorder → NPZ → Analytics → Decimated NPZ → DRF/Upload
- All 6 analytics pipelines tested and validated end-to-end
- See [SESSION_2025-11-24_ANALYTICS_METADATA_INTEGRATION.md](SESSION_2025-11-24_ANALYTICS_METADATA_INTEGRATION.md) for details

**November 20, 2025 - DRF Writer Production Ready** ✅
- Digital RF output now fully wsprdaemon-compatible (PSWS upload ready)
- Two modes: wsprdaemon-compatible (default) or enhanced metadata
- Float32 I/Q pairs with is_complex=True flag
- Proper writer lifecycle with explicit close after each file
- See [SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md](SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md)

**November 20, 2025 - Canonical Contracts** ✅
- Established project-wide standards and enforcement
- GRAPEPaths API mandatory for all file operations
- Unified API_REFERENCE.md with complete function signatures
- Validation tool: scripts/validate_api_compliance.py
- See [CANONICAL_CONTRACTS.md](CANONICAL_CONTRACTS.md)

**November 23, 2025 - Core Recorder Timing Fix** ✅
- Fixed incomplete NPZ files caused by wall clock boundary check
- RTP timestamp now primary reference (sample count = sole trigger)
- Files correctly contain 960,000 samples (60 seconds @ 16 kHz)
- Embedded time_snap, tone powers, and gap metadata in all NPZ files
- See [CORE_RECORDER_BUG_NOTES.md](CORE_RECORDER_BUG_NOTES.md)

## Credits & Support

**Credits:** Phil Karn/KA9Q (ka9q-radio), MIT Haystack (Digital RF), Nathaniel Frissell/W2NAF (HamSCI GRAPE), Rob Robinett/AI6VN (wsprdaemon inspiration), Michael Hauan/AC0G (this implementation)

**Community:** [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io) | [GitHub Issues](https://github.com/yourusername/signal-recorder/issues)

**PSWS Access:** Contact HamSCI coordinators to register station and receive credentials

**License:** MIT - See [LICENSE](LICENSE)

---

**🎯 Ready to contribute to ionospheric science? Install and start monitoring!**
