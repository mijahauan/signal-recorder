# GRAPE Signal Recorder

**A specialized system for recording and archiving WWV/CHU time-standard signals for the HamSCI GRAPE (Grape Radio Aurora and Plasma Experiment) project.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What is GRAPE?

The [HamSCI GRAPE project](https://hamsci.org/grape) studies **ionospheric disturbances** by analyzing **timing variations** in WWV (Fort Collins, CO) and CHU (Ottawa, Canada) time-standard broadcasts. Amateur radio operators worldwide contribute data to build a global observation network.

This recorder:
- ✅ Captures **high-precision IQ data** from ka9q-radio
- ✅ Processes to **10 Hz Digital RF format** for timing analysis  
- ✅ Monitors **data quality metrics** (completeness, timing drift, packet loss)
- ✅ Uploads to **HamSCI PSWS repository** via rsync
- ✅ Provides **web-based management** and real-time monitoring

---

## Quick Start

### Prerequisites

1. **ka9q-radio** installed and configured ([installation guide](https://github.com/ka9q/ka9q-radio))
2. **Linux system** with multicast networking
3. **Python 3.8+** and **Node.js 16+**
4. **PSWS account** from HamSCI (for uploads)

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Install web UI dependencies
cd web-ui
pnpm install  # or: npm install
```

### Configuration

**Use the web interface** (easiest):

```bash
cd web-ui
pnpm start
# Open http://localhost:3000 (login: admin/admin)
```

The web UI guides you through:
1. Station info (callsign, grid square, instrument)
2. Channel selection (WWV/CHU presets available)
3. PSWS upload credentials
4. Export to `config/grape-config.toml`

**Or edit TOML manually** (advanced users): see [Configuration Guide](docs/configuration.md)

#### Test vs Production Mode

The config file (`config/grape-config.toml`) includes a mode flag:

```toml
[recorder]
mode = "test"  # or "production"
test_data_root = "/tmp/grape-test"
production_data_root = "/var/lib/signal-recorder"
```

- **Test mode** (default): Data stored in `/tmp/grape-test` (temporary, cleared on reboot)
- **Production mode**: Data stored in `/var/lib/signal-recorder` (persistent)

### Running

**Test mode** (recommended for initial setup):

```bash
# Ensure config has: mode = "test"
signal-recorder daemon --config config/grape-config.toml

# Data goes to /tmp/grape-test (temporary)
# Safe for testing - won't affect production data
```

**Production mode** (for operational data collection):

```bash
# Edit config: mode = "production"
signal-recorder daemon --config config/grape-config.toml

# Data goes to /var/lib/signal-recorder (persistent)
# Ensure proper permissions and disk space
```

**Or use the web UI** to start/stop: `http://localhost:3000`

### Monitoring

Real-time dashboard shows:
- 📊 Channel health (🟢/🟡/🔴)
- 📈 Completeness, packet loss, timing drift
- 📁 Files written and data uploaded
- 📋 Live daemon logs

Access: `http://localhost:3000/monitoring`

---

## Key Features

### 🎯 Purpose-Built for GRAPE

Unlike generic SDR recorders, this system is **optimized for continuous timing signal analysis**:

| Feature | GRAPE Recorder | Generic Recorders |
|---------|---------------|-------------------|
| **Data Format** | Digital RF (10 Hz IQ) | Audio/WAV/Raw IQ |
| **Timing Validation** | RTP clock tracking, drift monitoring | None |
| **Quality Metrics** | Completeness, packet loss, timing stats | File size only |
| **Upload** | rsync to PSWS | Manual/FTP |
| **Management** | Web UI + monitoring | Command-line only |

### 🔬 Precision Signal Processing

```
ka9q-radio RTP stream (16 kHz IQ)
    ↓ scipy.signal.decimate (anti-aliased FIR)
10 Hz IQ samples
    ↓ Digital RF Writer (HDF5 + metadata)
Time-indexed archive
    ↓ rsync with verification
HamSCI PSWS repository
```

**Why scipy instead of sox/wsprdaemon?**
- Direct RTP→Digital RF pipeline (no external tools)
- Sub-millisecond timing preservation
- Continuous data flow (not 2-minute WSPR cycles)
- Pure Python (no sox/jt9 dependencies)

### 📊 Real-Time Quality Monitoring

Every channel tracks:

**Completeness** - Percentage of expected samples received
- 🟢 ≥99% (healthy)
- 🟡 95-99% (warning)
- 🔴 <95% (error)

**Timing Drift** - RTP timestamp vs system clock offset
- Measured every 10 seconds
- Mean ± std deviation tracked
- Should be < ±50 ms

**Packet Loss** - RTP sequence gaps
- < 1% is healthy
- Indicates network/multicast issues

All metrics logged to JSON and displayed in web UI.

### 🌐 Web Management Interface

<img src="docs/images/web-ui-screenshot.png" alt="Web UI" width="600">

**Configuration Tab:**
- Station setup wizard
- WWV/CHU channel presets
- PSWS credentials
- TOML export

**Monitoring Tab:**
- Real-time health dashboard
- Channel-by-channel metrics
- Daemon logs (tail -100)
- Auto-refresh every 30 seconds

**Technology:**
- Node.js backend (Express.js)
- Vanilla HTML/CSS/JS frontend
- JSON file database (no PostgreSQL/MySQL)
- RESTful API

---

## Documentation

### Getting Started
- **[INSTALLATION.md](INSTALLATION.md)** - Detailed setup guide
- **[Configuration Guide](docs/configuration.md)** - TOML reference
- **[Web UI Guide](web-ui/README.md)** - Interface walkthrough

### Technical Details
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design & rationale
- **[GRAPE Digital RF Format](docs/GRAPE_DIGITAL_RF_RECORDER.md)** - Output specification
- **[PSWS Upload Setup](docs/PSWS_SETUP_GUIDE.md)** - rsync configuration

### Operations
- **[Monitoring Guide](docs/monitoring.md)** - Interpreting metrics
- **[Troubleshooting](docs/troubleshooting.md)** - Common issues
- **[Deployment Guide](DEPLOYMENT_GUIDE.md)** - systemd setup

---

## Architecture

```
┌─────────────────────────┐
│   Web UI (Node.js)      │  Configuration & Monitoring
│   http://localhost:3000 │
└────────────┬────────────┘
             │
┌────────────▼────────────┐
│  GRAPE Recorder Daemon  │  Python (signal-recorder)
│  • RTP reception        │
│  • scipy decimation     │
│  • Digital RF output    │
│  • Quality monitoring   │
└────────────┬────────────┘
             │
┌────────────▼────────────┐
│    ka9q-radio (radiod)  │  RTP stream source
│  • WWV/CHU channels     │
│  • 16 kHz IQ multicast  │
└────────────┬────────────┘
             │
┌────────────▼────────────┐
│  HamSCI PSWS Repository │  Data archive (rsync/SSH)
│  pswsnetwork.eng.ua.edu │
└─────────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design rationale.

---

## Requirements

### Hardware
- **Receiver**: Any SDR supported by ka9q-radio (RX888, Airspy, SDRPlay, etc.)
- **Antenna**: HF antenna for WWV/CHU bands (2.5-25 MHz)
- **Computer**: Linux system with 1+ GB RAM

### Software
- **ka9q-radio** (radiod + control utility)
- **Python 3.8+** with:
  - `digital_rf>=3.0.0`
  - `scipy>=1.7.0`
  - `numpy>=1.20.0`
- **Node.js 16+** (for web UI)
- **rsync** with SSH keys (for PSWS upload)

### Network
- **Multicast-capable network** (for RTP reception)
- **Internet connectivity** (for PSWS upload)
- **Open ports**: 3000 (web UI), 5004 (RTP)

---

## Example Configuration

**File**: `config/grape-config.toml`

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
instrument_id = "RX888"

[ka9q]
status_address = "239.192.152.141"

[recorder]
mode = "test"  # or "production"
test_data_root = "/tmp/grape-test"
production_data_root = "/var/lib/signal-recorder"
archive_dir = "/var/lib/signal-recorder/archive"

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
description = "WWV 2.5 MHz"
enabled = true

[[recorder.channels]]
ssrc = 10000000
frequency_hz = 10000000
description = "WWV 10 MHz"
enabled = true

[uploader]
enabled = true
protocol = "rsync"
remote_host = "pswsnetwork.eng.ua.edu"
remote_user = "user_ac0g"
remote_path = "/var/psws/archive/data/GRAPE/AC0G"
ssh_key_path = "~/.ssh/psws_key"
```

**Generate this automatically with the web UI!**

---

## Typical Workflow

### Setup (one-time)
1. Install ka9q-radio and configure for WWV/CHU
2. Install GRAPE recorder and dependencies
3. Use web UI to create `config/grape-config.toml`
4. **Test in test mode**: Set `mode = "test"`, run for 5 minutes, verify data in `/tmp/grape-test`
5. **Switch to production**: Set `mode = "production"`, ensure `/var/lib/signal-recorder` permissions
6. Set up PSWS SSH keys for uploads

### Daily Operation (Production Mode)
1. Daemon runs continuously via systemd with `mode = "production"`
2. Web UI shows real-time health metrics
3. Data persists in `/var/lib/signal-recorder`
4. Data auto-uploads to PSWS every 5 minutes
5. Monitor for 🟢 healthy status

### Maintenance
1. Check web UI monitoring weekly
2. Verify PSWS uploads are completing
3. Review logs if warnings/errors appear
4. Update software as needed

---

## Comparison: GRAPE vs wsprdaemon

| Aspect | wsprdaemon | GRAPE Recorder |
|--------|------------|----------------|
| **Project** | WSPR decoding | GRAPE timing analysis |
| **Data** | Audio (WAV) | IQ samples (Digital RF) |
| **Output Rate** | N/A (spots only) | 10 Hz IQ |
| **Tools** | sox, wsprd, jt9 | Pure Python (scipy) |
| **Upload** | wsprnet.org (HTTP) | PSWS (rsync/SSH) |
| **Monitoring** | Spot count | Completeness, drift, loss |
| **Cycle** | 2-minute WSPR windows | Continuous 60-second files |

**Bottom line**: If you're doing WSPR, use wsprdaemon. If you're doing GRAPE, use this!

---

## Troubleshooting

### No data recorded

**Check radiod is running:**
```bash
control -v 239.192.152.141  # Your radiod address
# Should list active channels
```

**Check multicast routing:**
```bash
ip mroute show  # Should show active routes
netstat -g      # Should show multicast group membership
```

**Check firewall:**
```bash
sudo ufw allow 5004/udp  # RTP packets
sudo ufw allow 3000/tcp  # Web UI
```

### Data quality issues

**Completeness < 99%:**
- Check network congestion
- Verify multicast switch configuration
- Look for packet loss in `ifconfig`

**Timing drift > 50ms:**
- Verify NTP is running (`timedatectl`)
- Check radiod clock sync
- Review system load

**Packet loss > 1%:**
- Increase RTP buffer size in config
- Check CPU usage during recording
- Test with fewer channels

See [Troubleshooting Guide](docs/troubleshooting.md) for more.

---

## Contributing

Contributions welcome! Areas of interest:

- **Testing**: Try on different SDRs/systems
- **Documentation**: Improve guides/tutorials
- **Features**: Multi-site monitoring, cloud upload
- **Bug reports**: GitHub issues

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT License - see [LICENSE](LICENSE) file.

---

## Credits

### Projects
- **[ka9q-radio](https://github.com/ka9q/ka9q-radio)** by Phil Karn (KA9Q) - Multichannel SDR
- **[Digital RF](http://digitalrf.readthedocs.io/)** by MIT Haystack - HDF5 time-series format
- **[HamSCI](https://hamsci.org/)** - Citizen science ionospheric research
- **[wsprdaemon](https://github.com/rrobinett/wsprdaemon)** by Rob Robinett (AI6VN) - Inspiration

### People
- **Nathaniel Frissell (W2NAF)** - HamSCI GRAPE project lead
- **Phil Karn (KA9Q)** - ka9q-radio author
- **Rob Robinett (AI6VN)** - wsprdaemon author
- **Michael Hauan (AC0G)** - This GRAPE recorder implementation

---

## Support

### Documentation
- **[Installation Guide](INSTALLATION.md)**
- **[Architecture Document](ARCHITECTURE.md)**
- **[Configuration Reference](docs/configuration.md)**

### Community
- **HamSCI Groups.io**: [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io)
- **GitHub Issues**: [Report bugs](https://github.com/yourusername/signal-recorder/issues)

### Getting PSWS Access
Contact HamSCI GRAPE coordinators via Groups.io to:
1. Register your station
2. Receive PSWS credentials
3. Get SSH key setup help

---

**🎯 Ready to contribute to ionospheric science? Install the recorder and start monitoring WWV/CHU today!**
