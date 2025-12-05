# GRAPE Signal Recorder

**Precision WWV/CHU time-standard recorder for ionospheric research** - Captures high-precision IQ data from ka9q-radio, performs 12-method WWV/WWVH discrimination, and uploads Digital RF to HamSCI PSWS.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

The [HamSCI GRAPE project](https://hamsci.org/grape) studies ionospheric disturbances through timing variations in WWV/CHU broadcasts. This recorder enables amateur radio operators to contribute scientifically valid data to the global observation network.

**Key Capabilities:**
- 📡 **Multi-channel recording** - Simultaneous WWV 2.5-25 MHz, CHU 3.33-14.67 MHz
- 🎯 **GPS-quality timing** - ±1ms via tone detection, PPM-corrected sub-sample precision
- 🔗 **Cross-channel coherent processing** - Global station lock, ensemble timing, 10·log₁₀(N) dB SNR gain
- ⏱️ **Primary time standard** - Back-calculate UTC(NIST) from arrival time + propagation mode
- 🔬 **12 voting methods** - BCD, timing tones, ticks, 440/500/600 Hz, Doppler, test signal channel sounding
- 📊 **Digital RF output** - 10 Hz IQ + metadata (wsprdaemon-compatible)
- 🌐 **Web UI** - Real-time monitoring, configuration, quality metrics
- 🚀 **PSWS upload** - Automated SFTP to HamSCI repository

## Quick Start

**Prerequisites:** ka9q-radio running, Linux with multicast networking, Python 3.10+, Node.js 18+

### Test Mode (Development)

```bash
# Clone repository
git clone https://github.com/mijahauan/grape-recorder.git
cd grape-recorder

# Run installer in test mode
./scripts/install.sh --mode test

# Edit configuration with your station details
nano config/grape-config.toml

# Start all services
./scripts/grape-all.sh -start

# Check status
./scripts/grape-all.sh -status
```

### Production Mode (24/7 Operation)

```bash
# Run installer in production mode
sudo ./scripts/install.sh --mode production --user $USER

# Edit configuration
sudo nano /etc/grape-recorder/grape-config.toml

# Start and enable services
sudo systemctl start grape-recorder grape-analytics grape-webui
sudo systemctl enable grape-recorder grape-analytics grape-webui

# Enable daily uploads (after SSH key setup)
sudo systemctl enable --now grape-upload.timer
```

### Service Control

**Test Mode (scripts):**
```bash
./scripts/grape-all.sh -start|-stop|-status    # All services
./scripts/grape-core.sh -start|-stop|-status   # Core recorder only
./scripts/grape-analytics.sh -start|-stop|-status  # Analytics (9 channels)
./scripts/grape-ui.sh -start|-stop|-status     # Web UI only
```

**Production Mode (systemd):**
```bash
sudo systemctl start|stop|status grape-recorder
sudo systemctl start|stop|status grape-analytics
sudo systemctl start|stop|status grape-webui
journalctl -u grape-recorder -f    # View logs
```

### Directory Structure

| Mode | Data | Logs | Config |
|------|------|------|--------|
| **Test** | `/tmp/grape-test/` | `/tmp/grape-test/logs/` | `config/grape-config.toml` |
| **Production** | `/var/lib/grape-recorder/` | `/var/log/grape-recorder/` | `/etc/grape-recorder/` |

**Monitor:** Open `http://localhost:3000` for real-time channel health, quality metrics, and logs.

## Architecture

**Three-service design** built on a **generic recording infrastructure**:

```
ka9q-radio (RTP multicast) → Core Recorder → Analytics → DRF Writer/Upload
                              20kHz NPZ      10Hz NPZ   Digital RF HDF5
                              archives/      analytics/ → PSWS sftp
```

### Generic Recording Infrastructure (New in V3)

The recording layer uses a **protocol-based design** enabling multiple applications:

```
Application Layer (GrapeRecorder, WsprRecorder, etc.)
        ↓
SegmentWriter Protocol (GrapeNPZWriter, WAVWriter, etc.)
        ↓
RecordingSession (generic RTP → segments)
        ↓
RTPReceiver + ka9q-python (multicast, parsing, timing)
```

**Key Abstractions:**
- **SegmentWriter Protocol** - Apps implement storage format
- **RecordingSession** - Generic packet flow, resequencing, segmentation
- **RTPReceiver** - Multi-SSRC demultiplexing, transport timing

### 1. Core Recorder (`src/grape_recorder/grape/core_recorder.py`)

Rock-solid RTP capture with scientific-grade metadata preservation:
- Uses `GrapeRecorder` with two-phase operation (startup → recording)
- RTP → resequencing → gap fill → 20 kHz NPZ (1,200,000 samples/minute)
- Minimal dependencies, designed for maximum reliability

**20 kHz NPZ Metadata** (self-contained scientific record):
- **IQ Data:** Complex64 samples, gap-filled with zeros
- **Timing Reference:** RTP timestamp of first sample, sample rate, SSRC
- **Time_snap Anchor:** RTP/UTC calibration from WWV/CHU tone detection
- **Tone Powers:** 1000 Hz (WWV) and 1200 Hz (WWVH) power levels in dB
- **NTP Status:** Wall clock time, NTP offset at minute boundary
- **Gap Provenance:** Detailed gap locations, sizes, and packet loss counts
- **Quality Indicators:** Packets received vs expected, completeness

### 2. Analytics Service (`src/grape_recorder/grape/analytics_service.py`)

Processes 20 kHz archives to derived products:

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
- **Decimation:** 20 kHz → 10 Hz (optimized multi-stage CIC+FIR filter)

**Output:** Separated CSVs per method + 10 Hz NPZ with embedded metadata

### 3. DRF Writer (`src/grape_recorder/grape/drf_batch_writer.py`)

Wsprdaemon-compatible Digital RF output:
- Reads 10 Hz NPZ → writes Digital RF HDF5 (float32 I/Q pairs)
- Multi-subchannel format: all 9 frequencies in single ch0
- Automated SFTP upload to HamSCI PSWS with trigger directories

### Design Principles

- **Reprocessability:** 20 kHz archives preserved, analytics can rerun
- **Self-Contained Files:** Each NPZ contains all metadata for standalone analysis
- **Separation:** Core never stops, analytics restartable, DRF independent
- **Time_snap:** WWV/CHU tones anchor RTP to UTC (±1ms GPS-quality timing)

## Quality Metrics

- **Completeness:** 🟢 ≥99% | 🟡 95-99% | 🔴 <95%
- **Timing Drift:** RTP vs system clock (<±50ms healthy)
- **Packet Loss:** <1% healthy (indicates network issues)
- **Time_snap Quality:** TONE_LOCKED (±1ms) > NTP_SYNCED (±10ms) > WALL_CLOCK (±seconds)

## 🎯 Cross-Channel Coherent Timing

### Global Station Lock

Because radiod's RTP timestamps are **GPS-disciplined**, all 9 channels share a common timing reference. This enables treating multiple receivers as a **single coherent sensor array**:

| Parameter | Value | Significance |
|-----------|-------|--------------|
| **Ionospheric dispersion** | 2-3 ms | Group delay between HF bands |
| **Station separation** | 15-20 ms | WWV (CO) vs WWVH (HI) path difference |
| **Discrimination margin** | ~5× | Dispersion ≪ separation enables unambiguous ID |

**Three-Phase Detection:**
1. **Anchor Discovery** - Find high-confidence locks (SNR > 15 dB) across all channels
2. **Guided Search** - Use anchor timing to narrow weak-channel search from ±500 ms to ±3 ms (99.4% noise rejection)
3. **Coherent Stacking** - Virtual channel with SNR improvement of 10·log₁₀(N) dB

### Primary Time Standard (HF Time Transfer)

Back-calculate emission time from GPS-locked arrival time to **verify UTC(NIST)**:

```
T_emit = T_arrival - (τ_geo + τ_iono + τ_mode)
```

| Component | Description |
|-----------|-------------|
| **T_arrival** | GPS-disciplined RTP timestamp |
| **τ_geo** | Great-circle speed-of-light delay |
| **τ_iono** | Ionospheric group delay (frequency-dependent) |
| **τ_mode** | Extra path from N ionospheric hops |

**Propagation Mode Identification** (quantized by layer heights):

| Mode | Typical Delay | Uncertainty |
|------|---------------|-------------|
| 1-hop E | ~3.8 ms | ±0.20 ms |
| 1-hop F2 | ~4.3 ms | ±0.17 ms |
| 2-hop F2 | ~5.5 ms | ±0.33 ms |

**Accuracy Progression:**
- Raw arrival time: ±10 ms
- \+ Mode identification: ±2 ms
- \+ Cross-channel consensus: ±1 ms
- \+ Cross-station verification: ±0.5 ms

### PPM-Corrected Timing

ADC clock drift compensation with **sub-sample precision**:

- **Tone-to-tone PPM measurement** - Measures actual ADC clock vs nominal
- **Exponential smoothing** - Filters PPM estimates for stability
- **Parabolic interpolation** - Sub-sample peak detection (±10-25 μs at 20 kHz)
- **Clock ratio correction** - `elapsed_seconds = (rtp_elapsed / sample_rate) × clock_ratio`

**Ensemble Anchor Selection** - Cross-channel voting selects best time_snap source based on SNR, timing preference (WWV/CHU over WWVH), and quality metrics.

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
- [docs/PRODUCTION.md](docs/PRODUCTION.md) - Production deployment (systemd, 24/7, uploads)
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [DIRECTORY_STRUCTURE.md](DIRECTORY_STRUCTURE.md) - Data paths and file formats

**Reference:**
- [docs/](docs/) - Feature documentation and guides
- [TECHNICAL_REFERENCE.md](TECHNICAL_REFERENCE.md) - Implementation details
- [CANONICAL_CONTRACTS.md](CANONICAL_CONTRACTS.md) - API standards


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

**Setup:**
1. Install ka9q-radio
2. Run `./scripts/install.sh --mode test`
3. Edit `config/grape-config.toml` with station details
4. Test with `./scripts/grape-all.sh -start` (verify 5 min)
5. Deploy production: `sudo ./scripts/install.sh --mode production`
6. Configure PSWS SSH keys for uploads

**Daily Operation:** systemd services run 24/7, monitor web UI for 🟢 status, daily 00:30 UTC upload  
**Maintenance:** Check weekly via `journalctl -u grape-recorder`, verify uploads, review logs


## Troubleshooting

**No data:** Check `radiod` running, multicast routing, firewall (allow 5004/udp, 3000/tcp)  
**Completeness <99%:** Network congestion, multicast switch config  
**Timing drift >50ms:** Verify NTP (`timedatectl`), check radiod clock sync  
**Packet loss >1%:** Increase RTP buffer, check CPU, reduce channels

See [docs/troubleshooting.md](docs/troubleshooting.md) for details.

## Status

**Production Ready** - Core functionality complete and tested. Daily recording and PSWS upload operational at AC0G since November 2025.

### v3.9.0 (Dec 5, 2025)
- **Multi-Broadcast Fusion** - Combines 13 broadcasts (WWV/WWVH/CHU) to converge on UTC(NIST)
  - Auto-calibration learns per-station offsets via EMA
  - Fused D_clock achieves ±0.5 ms accuracy (vs ±5-10 ms single-broadcast)
  - Real-time convergence indicators per station
- **Timing Dashboard Consolidation** - Simplified to fusion panel + 13-broadcast table
  - UTC(NIST) Alignment panel shows fused result
  - Per-broadcast raw D_clock with confidence, SNR, convergence status
- **Advanced Timing Visualizations** - Fusion-corrected graphs
  - Kalman funnel: 24-hour default, drag-to-zoom, scroll zoom
  - Constellation radar: All stations clustered at center when calibrated
  - Consensus KDE: Sharp peak at 0 ms after convergence
- **Timing Methodology Documentation** - `/docs/timing-methodology.html`
  - Info links (?) on all graphs explain calculations
  - D_clock measurement, fusion algorithm, accuracy expectations
- **UI Reorganization** - Removed redundant phase2-dashboard.html
  - Diurnal patterns → discrimination.html
  - Reception matrix → summary.html
  - Station distances → summary.html

### v3.8.0 (Dec 5, 2025)
- **Clock Convergence Model** - "Set, Monitor, Intervention" architecture for GPSDO timing
  - Converges to locked D_clock estimate, then monitors for anomalies
  - Welford's algorithm for running mean/variance
  - 3σ anomaly detection reveals real propagation events
- **Propagation Mode Discrimination** - Gaussian likelihood-based hop identification
  - Sharp mode probabilities after convergence (<3ms uncertainty)
- **UTC Time Standardization** - All web-UI displays use UTC consistently
- **Phase 2 Dashboard** - New visualization page for reception matrix, D_clock consensus

### v3.7.0 (Dec 4, 2025)
- **Three-Phase Pipeline** - Raw archive → Analytics → Products architecture
- **Advanced Timing Visualizations** - Kalman funnel, constellation radar, mode ridge
- **Audio Streaming** - Browser-based WWV/CHU audio via ka9q-python

### v2.2.0 (Dec 2, 2025)
- **Unified Installer** - `scripts/install.sh --mode test|production`
- **Systemd Services** - Production-ready with auto-restart, daily uploads
- **FHS-Compliant Paths** - `/var/lib/grape-recorder/`, `/var/log/grape-recorder/`, `/etc/grape-recorder/`
- **Environment File** - Single source of truth for all paths
- **PPM-Corrected Timing** - Sub-sample precision via ADC drift compensation
- **Config-Driven Sample Rate** - 20 kHz default, fully configurable

### v2.0.0 (Dec 1, 2025)
- **Package Restructure** - Clean separation into `core/`, `stream/`, `grape/`, `wspr/` packages
- **ka9q-python 3.1.0** - SSRC-free API integration
- **Stream API** - `subscribe_stream()` hides SSRC from applications
- **Generic Recording Infrastructure** - Protocol-based design for multi-app support

### Previous (Nov 28-30, 2025)
- **12 Voting Methods** - BCD, timing tones, ticks, 440/500/600 Hz, Doppler, test signal
- **12 Cross-Validation Checks** - FSS geographic, noise transient, spreading factor
- **Test Signal Channel Sounding** - FSS, delay spread, ToA from :08/:44 minutes

## Credits & Support

**Credits:** Phil Karn/KA9Q (ka9q-radio), MIT Haystack (Digital RF), Nathaniel Frissell/W2NAF (HamSCI GRAPE), Rob Robinett/AI6VN (wsprdaemon inspiration), Michael James Hauan/AC0G (this implementation)

**Community:** [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io) | [GitHub Issues](https://github.com/mijahauan/grape-recorder/issues)

**PSWS Access:** Contact HamSCI coordinators to register station and receive credentials

**License:** MIT - See [LICENSE](LICENSE)

---

**🎯 Ready to contribute to ionospheric science? Install and start monitoring!**
