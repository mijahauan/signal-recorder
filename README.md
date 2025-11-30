# GRAPE Signal Recorder

**Precision WWV/CHU time-standard recorder for ionospheric research** - Captures high-precision IQ data from ka9q-radio, performs 5-method WWV/WWVH discrimination, and uploads Digital RF to HamSCI PSWS.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

The [HamSCI GRAPE project](https://hamsci.org/grape) studies ionospheric disturbances through timing variations in WWV/CHU broadcasts. This recorder enables amateur radio operators to contribute scientifically valid data to the global observation network.

**Key Capabilities:**
- 📡 **Multi-channel recording** - Simultaneous WWV 2.5-25 MHz, CHU 3.33-14.67 MHz
- 🎯 **GPS-quality timing** - ±1ms via tone detection (time_snap mechanism)
- 🔬 **12 voting methods** - BCD, timing tones, ticks, 440/500/600 Hz, Doppler stability, test signal channel sounding
- 📊 **Digital RF output** - 10 Hz IQ + metadata (wsprdaemon-compatible)
- 🌐 **Web UI** - Real-time monitoring, configuration, quality metrics
- 🚀 **PSWS upload** - Automated rsync to HamSCI repository

## Quick Start (Beta)

**Prerequisites:** ka9q-radio running, Linux with multicast networking, Python 3.10+, Node.js 18+

```bash
# Clone repository
git clone https://github.com/mijahauan/signal-recorder.git
cd signal-recorder

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .

# Copy and edit configuration template
cp config/grape-config.toml.template config/grape-config.toml
# Edit config/grape-config.toml with your station details and ka9q-radio address

# Start all services
./scripts/grape-all.sh -start

# Check status
./scripts/grape-all.sh -status
```

**Service Control Scripts:**
```bash
./scripts/grape-all.sh -start|-stop|-status    # All services
./scripts/grape-core.sh -start|-stop|-status   # Core recorder only
./scripts/grape-analytics.sh -start|-stop|-status  # Analytics (9 channels)
./scripts/grape-ui.sh -start|-stop|-status     # Web UI only
```

**Modes:** Set `mode = "test"` (default, uses `/tmp/grape-test`) or `mode = "production"` (uses `/var/lib/signal-recorder`).

**Monitor:** Open `http://localhost:3000` for real-time channel health, quality metrics, and logs.

## Architecture

**Three-service design** for reliability and reprocessability:

```
ka9q-radio (RTP multicast) → Core Recorder → Analytics → DRF Writer/Upload
                              16kHz NPZ      10Hz NPZ   Digital RF HDF5
                              archives/      analytics/ → PSWS sftp
```

### 1. Core Recorder (`src/signal_recorder/core_recorder.py`)

Rock-solid RTP capture with scientific-grade metadata preservation:
- RTP → resequencing → gap fill → 16 kHz NPZ (960,000 samples/minute)
- Minimal dependencies, designed for maximum reliability

**16 kHz NPZ Metadata** (self-contained scientific record):
- **IQ Data:** Complex64 samples, gap-filled with zeros
- **Timing Reference:** RTP timestamp of first sample, sample rate, SSRC
- **Time_snap Anchor:** RTP/UTC calibration from WWV/CHU tone detection
- **Tone Powers:** 1000 Hz (WWV) and 1200 Hz (WWVH) power levels in dB
- **NTP Status:** Wall clock time, NTP offset at minute boundary
- **Gap Provenance:** Detailed gap locations, sizes, and packet loss counts
- **Quality Indicators:** Packets received vs expected, completeness

### 2. Analytics Service (`src/signal_recorder/analytics_service.py`)

Processes 16 kHz archives to derived products:

**Discrimination Methods** (each writes independent CSV):
- **Timing Tones:** 1000/1200 Hz power ratio (1/min)
- **Tick Windows:** 5ms coherent/incoherent SNR analysis (6/min)
- **440 Hz Station ID:** Unambiguous WWV/WWVH identification (2/hour)
- **BCD Correlation:** 100 Hz time code dual-peak detection (15/min)
- **Test Signals:** Minutes :08/:44 channel sounding (FSS, delay spread, noise coherence, ToA)
- **Weighted Voting:** Combines all methods for final determination

**Additional Analytics:**
- **Doppler Estimation:** Per-tick frequency shift measurement
- **Timing Metrics:** Time_snap quality, NTP drift, timing accuracy
- **Decimation:** 16 kHz → 10 Hz (optimized 3-stage FIR filter)

**Output:** Separated CSVs per method + 10 Hz NPZ with embedded metadata

### 3. DRF Writer (`src/signal_recorder/drf_batch_writer.py`)

Wsprdaemon-compatible Digital RF output:
- Reads 10 Hz NPZ → writes Digital RF HDF5 (float32 I/Q pairs)
- Multi-subchannel format: all 9 frequencies in single ch0
- Automated SFTP upload to HamSCI PSWS with trigger directories

### Design Principles

- **Reprocessability:** 16 kHz archives preserved, analytics can rerun
- **Self-Contained Files:** Each NPZ contains all metadata for standalone analysis
- **Separation:** Core never stops, analytics restartable, DRF independent
- **Time_snap:** WWV/CHU tones anchor RTP to UTC (±1ms GPS-quality timing)

## Quality Metrics

- **Completeness:** 🟢 ≥99% | 🟡 95-99% | 🔴 <95%
- **Timing Drift:** RTP vs system clock (<±50ms healthy)
- **Packet Loss:** <1% healthy (indicates network issues)
- **Time_snap Quality:** TONE_LOCKED (±1ms) > NTP_SYNCED (±10ms) > WALL_CLOCK (±seconds)

## 🔬 WWV/WWVH Discrimination (12 Voting Methods)

Separate WWV (Fort Collins) and WWVH (Kauai) signals on shared frequencies (2.5, 5, 10, 15 MHz) using complementary measurement techniques:

### Voting Methods

| Vote | Method | Weight | Description |
|------|--------|--------|-------------|
| 0 | **Test Signal** | 15 | Minutes :08/:44 scientific modulation test |
| 1 | **440 Hz Station ID** | 10 | WWVH min 1, WWV min 2 |
| 2 | **BCD Amplitude Ratio** | 2-10 | 100 Hz time code dual-peak detection |
| 3 | **1000/1200 Hz Power** | 1-10 | Timing tone power ratio |
| 4 | **Tick SNR Average** | 5 | 59-tick coherent integration |
| 5 | **500/600 Hz Ground Truth** | 10-15 | 12 exclusive minutes/hour (weight=15 for M16-19, M43-51) |
| 6 | **Doppler Stability** | 2 | Lower std = cleaner path (independent of power) |
| 7 | **Timing Coherence** | 3 | Test signal + BCD ToA agreement |
| 8 | **Harmonic Ratio** | 1.5 | 500→1000 Hz, 600→1200 Hz ratios |
| 9 | **FSS Path Signature** | 2 | Frequency Selectivity Score geographic validator |
| 10 | **Noise Coherence** | flag | Transient interference detection |
| 11 | **Burst ToA** | validation | High-precision timing cross-check |
| 12 | **Spreading Factor** | flag | Channel physics L = τ_D × f_D |

### Test Signal Channel Sounding (Minutes :08/:44)

The WWV/WWVH scientific test signal is fully exploited as a **channel sounding instrument**:

| Segment | Metric | Use |
|---------|--------|-----|
| **Multi-tone** (13-23s) | FSS = 10·log₁₀((P₂ₖ+P₃ₖ)/(P₄ₖ+P₅ₖ)) | Geographic path validation |
| **White Noise** (10-12s, 37-39s) | N1 vs N2 coherence | Transient interference detection |
| **Chirps** (24-32s) | Delay spread τ_D | Multipath characterization |
| **Bursts** (34-36s) | High-precision ToA | Sub-ms timing reference |

### Inter-Method Cross-Validation (12 checks)

Beyond voting, independent measurements validate each other:
- **Power vs Timing** - BCD delay should match power ratio direction
- **Geographic Delay** - Measured delay vs predicted from receiver location
- **Doppler-Power Agreement** - Δf_D magnitude correlates with power
- **Coherence Quality** - Low coherence (<0.3) downgrades confidence
- **Harmonic Signature** - 500→1000 Hz, 600→1200 Hz ratios confirm station
- **FSS Geographic** - Path fingerprint matches scheduled station
- **Noise Transient** - N1/N2 difference flags interference events
- **Spreading Factor** - L = τ_D × f_D validates channel physics

### Why 12 Methods?
- **Redundancy:** Multiple independent measurements validate each other
- **Adaptability:** Different methods excel under different propagation conditions  
- **Temporal Coverage:** From hourly calibration to sub-second dynamics
- **Ground Truth:** 14 minutes/hour with 440/500/600 Hz exclusive broadcasts
- **Channel Sounding:** Test signal provides complete ionospheric characterization
- **Cross-Validation:** Agreement confirms accuracy, disagreement reveals mixed propagation

**Quick Check:** View `http://localhost:3000/discrimination.html` for 7-panel analysis with method labels and performance statistics.

**Learn More:** [docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md](docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md)

## Web UI

**🔊 Live Audio:** Click any channel to stream WWV/CHU audio directly in the browser  
**Monitoring:** Real-time health, metrics, logs (auto-refresh 30s)  
**Discrimination:** 7-panel analysis with per-method visualization  
**Stack:** Node.js/Express, vanilla JS, WebSocket audio streaming

## Documentation

**Essential:**
- [INSTALLATION.md](INSTALLATION.md) - Detailed setup guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [CANONICAL_CONTRACTS.md](CANONICAL_CONTRACTS.md) - API standards
- [config/grape-config.toml.template](config/grape-config.toml.template) - Configuration template

**Reference:**
- [docs/](docs/) - Feature documentation and guides
- [TECHNICAL_REFERENCE.md](TECHNICAL_REFERENCE.md) - Implementation details


## Requirements

**Hardware:** SDR (RX888/Airspy/SDRPlay), HF antenna (2.5-25 MHz), Linux 2+ GB RAM  
**Software:** ka9q-radio, Python 3.10+, Node.js 18+, rsync, libhdf5-dev  
**Network:** Multicast-capable LAN, internet for PSWS upload

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

## Status

**Beta Release** - Core functionality complete and tested. Daily recording and PSWS upload operational at AC0G since November 2025.

### Recent Updates (Nov 29, 2025)
- **Test Signal Channel Sounding:** Full exploitation of :08/:44 scientific test signal
  - Frequency Selectivity Score (FSS) as geographic path validator
  - Dual noise segment comparison for transient detection
  - Chirp delay spread for multipath characterization
  - Spreading Factor L = τ_D × f_D for channel physics validation
- **12 Voting Methods:** Extended from 8 with FSS, noise coherence, spreading factor
- **12 Cross-Validation Checks:** Added FSS geographic, noise transient, spreading factor

### Previous Updates (Nov 28, 2025)
- **Discrimination Refinement:** 8 voting methods + 9 cross-validation checks
- **500/600 Hz Weight Boost:** Exclusive minutes (M16-19, M43-51) now weight=15
- **Doppler Stability Vote:** Uses std ratio for channel quality (independent of power)
- **440 Hz Detection:** Coherent integration for ~30 dB processing gain
- **Service Scripts:** `scripts/grape-*.sh` for easy start/stop/status

## Credits & Support

**Credits:** Phil Karn/KA9Q (ka9q-radio), MIT Haystack (Digital RF), Nathaniel Frissell/W2NAF (HamSCI GRAPE), Rob Robinett/AI6VN (wsprdaemon inspiration), Michael Hauan/AC0G (this implementation)

**Community:** [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io) | [GitHub Issues](https://github.com/mijahauan/signal-recorder/issues)

**PSWS Access:** Contact HamSCI coordinators to register station and receive credentials

**License:** MIT - See [LICENSE](LICENSE)

---

**🎯 Ready to contribute to ionospheric science? Install and start monitoring!**
