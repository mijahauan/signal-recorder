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

## Credits & Support

**Credits:** Phil Karn/KA9Q (ka9q-radio), MIT Haystack (Digital RF), Nathaniel Frissell/W2NAF (HamSCI GRAPE), Rob Robinett/AI6VN (wsprdaemon inspiration), Michael Hauan/AC0G (this implementation)

**Community:** [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io) | [GitHub Issues](https://github.com/yourusername/signal-recorder/issues)

**PSWS Access:** Contact HamSCI coordinators to register station and receive credentials

**License:** MIT - See [LICENSE](LICENSE)

---

**🎯 Ready to contribute to ionospheric science? Install and start monitoring!**
