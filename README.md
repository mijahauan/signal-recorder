# Signal Recorder

A modular, extensible system for recording and uploading scientific signal data from ka9q-radio.

## Overview

Signal Recorder is designed to work with [ka9q-radio](https://github.com/ka9q/ka9q-radio) to automatically:

1. **Discover** available signal streams via Avahi/mDNS
2. **Record** time-synchronized audio/IQ data from multiple frequencies
3. **Process** recordings with signal-specific plugins (GRAPE, CODAR, etc.)
4. **Upload** processed data to remote repositories (HamSCI PSWS, etc.)

## Key Features

- **Automatic Stream Discovery**: No manual configuration of multicast addresses, ports, or SSRCs
- **Dynamic Adaptation**: Automatically handles radiod restarts and configuration changes
- **Plugin Architecture**: Easy to add new signal types without modifying core code
- **Reliable Upload**: Queue-based upload with retry logic and verification
- **Minimal Configuration**: Users specify stream names, not low-level networking parameters
- **Web Configuration UI**: User-friendly web interface for managing configurations (see `web-ui/`)

## 📋 **Quick Start (Recommended)**

### **Use the Web Configuration UI**

For the easiest setup experience:

```bash
# Clone the repository
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# Start the configuration UI
cd web-ui
npm install
npm start

# Access http://localhost:3000 (admin/admin)
# Create your configuration through the guided interface
# Save directly to config/ directory
```

**The web UI generates the correct configuration automatically!**

---

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .
```

## Configuration

### **Web-Based Configuration UI (Recommended)**

The project includes a **simplified web-based configuration interface**:

```bash
cd web-ui
npm install
npm start
```

**Features:**
- ✅ **Guided setup** with form validation
- ✅ **Channel presets** for WWV/CHU frequencies
- ✅ **Auto-generates** correct TOML format
- ✅ **Real-time validation** prevents configuration errors
- ✅ **Save to config directory** with one click

**Access:** http://localhost:3000 (login: admin/admin)

### **Manual Configuration (Advanced)**

For advanced users, create a configuration file:

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
id = "AC0G"
instrument_id = "RX888"
description = "GRAPE station with RX888 MkII and ka9q-radio"

[ka9q]
status_address = "239.251.200.193"
auto_create_channels = true

[recorder]
data_dir = "/var/lib/signal-recorder/data"
archive_dir = "/var/lib/signal-recorder/archive"
recording_interval = 60
continuous = true

[[recorder.channels]]
ssrc = 10000000
frequency_hz = 10000000
preset = "iq"
sample_rate = 12000
description = "WWV 10 MHz"
enabled = true
processor = "grape"

[processor]
enabled = false

[processor.grape]
process_time = "00:05"
process_timezone = "UTC"
expected_files_per_day = 1440
output_sample_rate = 10
output_format = "digital_rf"

[uploader]
enabled = false
protocol = "rsync"
# ... PSWS configuration when enabled

[logging]
level = "INFO"
console_output = true

[monitoring]
enable_metrics = false
```

## Usage

### **Test Configuration**
```bash
# Validate your configuration
python3 -c "
import toml
config = toml.load('config/grape-your-station.toml')
print('✅ Configuration valid')
print(f'Station: {config[\"station\"][\"callsign\"]}')
print(f'Channels: {len(config.get(\"recorder\", {}).get(\"channels\", []))}')
"
```

### **Run GRAPE Recorder**
```bash
# Test with your configuration
python3 test_grape_recorder.py --config config/grape-your-station.toml

# Monitor logs
tail -f /tmp/grape_recorder_test.log
```

### **Service Installation**
```bash
# Create systemd service
sudo tee /etc/systemd/system/signal-recorder.service > /dev/null <<EOF
[Unit]
Description=Signal Recorder Daemon
After=network-online.target

[Service]
User=$USER
Group=$USER
WorkingDirectory=/home/$USER/signal-recorder
ExecStart=/home/$USER/signal-recorder/venv/bin/python3 test_grape_recorder.py --config config/grape-your-station.toml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable signal-recorder
sudo systemctl start signal-recorder
```

## Architecture

```
ka9q-radio (radiod)
    ↓ RTP streams + Status metadata
Stream Discovery Module
    ↓ Discovered SSRCs and parameters
Stream Recorder Module
    ↓ Time-synchronized Digital RF files
Storage Manager
    ↓ Organized archive
Signal Processor Plugins (GRAPE, CODAR, etc.)
    ↓ Processed datasets
Upload Manager
    ↓ SSH/rsync, HTTP, S3
Remote Repository (HamSCI PSWS, etc.)
```

## Web Configuration UI

The project includes a **simplified web-based configuration interface** that eliminates the need for manual TOML editing:

```bash
cd web-ui
npm install
npm start
```

**Features:**
- Visual form-based configuration (no TOML editing required)
- Real-time validation of grid squares, PSWS IDs, and frequencies
- One-click WWV/CHU channel presets
- TOML export for use with the signal recorder
- Multi-configuration management

**Technology:**
- **Backend**: Node.js with Express.js (single file)
- **Frontend**: Pure HTML/CSS/JavaScript (single file)
- **Database**: JSON files (no database server required)
- **Dependencies**: Only Express.js (minimal)

See [web-ui/README.md](web-ui/README.md) for detailed usage instructions.

## Documentation

### Signal Recorder (Python)
- [Installation Guide](docs/installation.md)
- [Configuration Reference](docs/configuration.md)
- [GRAPE Digital RF Recorder](docs/GRAPE_DIGITAL_RF_RECORDER.md)
- [PSWS Setup Guide](docs/PSWS_SETUP_GUIDE.md)

### Web Configuration UI (Node.js)
- [Web UI README](web-ui/README.md)

## Status

### ✅ **Completed**
- **Configuration UI** - Web interface fully functional
- **TOML Export** - Generates correct format for signal-recorder
- **Channel Management** - Presets and custom channels working
- **Cross-platform Compatibility** - Verified on Linux, macOS, Windows

### ⚠️ **Pending Integration Testing**
- **signal-recorder with web UI configs** - Integration testing needed
- **End-to-end PSWS upload** - Full pipeline verification
- **Long-term reliability** - Production deployment testing

## License

MIT License - see LICENSE file for details

## Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.

## Acknowledgments

- [ka9q-radio](https://github.com/ka9q/ka9q-radio) by Phil Karn, KA9Q
- [wsprdaemon](https://github.com/rrobinett/wsprdaemon) by Rob Robinett, AI6VN
- [HamSCI](https://hamsci.org/) GRAPE project

---

**🎯 The web-based configuration UI eliminates most setup complexity - try it first!**

