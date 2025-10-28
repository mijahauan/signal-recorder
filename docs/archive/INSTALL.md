# Installation Guide

## Quick Install

### Using pip (Recommended)

```bash
# Clone the repository
git clone https://github.com/mijahauan/signal-recorder.git
cd signal-recorder

# Install in development mode
pip install -e .

# Or install from requirements.txt
pip install -r requirements.txt
```

### Using setup.py

```bash
# Clone the repository
git clone https://github.com/mijahauan/signal-recorder.git
cd signal-recorder

# Install the package
python setup.py install
```

## System Requirements

### Operating System
- Linux (Ubuntu 22.04 or later recommended)
- Other Unix-like systems may work but are untested

### Python Version
- Python 3.10 or later
- Python 3.11 recommended (tested)

### Disk Space
- Minimum: 10 GB for software and temporary files
- Recommended: 100+ GB for GRAPE data storage (~1 GB/day for 9 channels)

### Network
- Multicast-capable network interface
- Access to ka9q-radio RTP streams (239.251.200.0/24)

## Dependencies

### Core Dependencies

The following packages are automatically installed:

- **toml** (>=0.10.2) - Configuration file parsing
- **numpy** (>=1.24.0) - Array operations and numerical computing
- **scipy** (>=1.10.0) - Signal processing and resampling
- **soundfile** (>=0.12.0) - Audio file I/O
- **digital_rf** (>=2.6.0) - Digital RF format I/O
- **zeroconf** (>=0.132.0) - mDNS/Avahi service discovery

### System Dependencies

#### Ubuntu/Debian

```bash
# Update package list
sudo apt update

# Install system dependencies
sudo apt install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    libhdf5-dev \
    libsndfile1 \
    avahi-daemon \
    avahi-utils

# For Digital RF (if not installing via pip)
sudo apt install -y \
    libhdf5-dev \
    cmake \
    build-essential
```

#### Fedora/RHEL

```bash
# Install system dependencies
sudo dnf install -y \
    python3.11 \
    python3-devel \
    python3-pip \
    hdf5-devel \
    libsndfile \
    avahi \
    avahi-tools
```

## Installation Steps

### 1. Install System Dependencies

See the System Dependencies section above for your distribution.

### 2. Clone Repository

```bash
git clone https://github.com/mijahauan/signal-recorder.git
cd signal-recorder
```

### 3. Create Virtual Environment (Recommended)

```bash
# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate
```

### 4. Install Python Dependencies

```bash
# Install core dependencies
pip install -r requirements.txt

# Or install with development dependencies
pip install -r requirements-dev.txt

# Or install the package itself
pip install -e .
```

### 5. Verify Installation

```bash
# Run component tests
python test_grape_components.py

# Expected output: 5/5 tests passed
```

## Configuration

### 1. Copy Configuration Template

```bash
cp config/grape-production.toml config/my-station.toml
```

### 2. Edit Configuration

Edit `config/my-station.toml` with your station details:

```toml
[station]
callsign = "YOUR_CALLSIGN"
grid_square = "YOUR_GRID"
id = "YOUR_STATION_ID"
instrument_id = "YOUR_RECEIVER"

[recorder]
archive_dir = "/path/to/your/data/archive"
```

### 3. Create Data Directories

```bash
# Create archive directory
sudo mkdir -p /mnt/grape-data/archive
sudo chown $USER:$USER /mnt/grape-data/archive
```

## Running the Recorder

### Test Run

```bash
# Activate virtual environment (if using)
source venv/bin/activate

# Run component tests
python test_grape_components.py

# Run integration test (requires active ka9q-radio channels)
python test_grape_recorder.py
```

### Production Run

```bash
# Create GRAPE channels (if not already created)
python -m signal_recorder.channel_manager \
    --config config/my-station.toml \
    --create-all

# Start recorder
python test_grape_recorder.py
```

### Systemd Service (Optional)

Create `/etc/systemd/system/grape-recorder.service`:

```ini
[Unit]
Description=GRAPE Digital RF Recorder
After=network.target radiod.service

[Service]
Type=simple
User=grape
Group=grape
WorkingDirectory=/home/grape/signal-recorder
ExecStart=/home/grape/signal-recorder/venv/bin/python test_grape_recorder.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable grape-recorder
sudo systemctl start grape-recorder
sudo systemctl status grape-recorder
```

## Troubleshooting

### Import Errors

If you get `ModuleNotFoundError`:

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Digital RF Installation Issues

If `digital_rf` fails to install:

```bash
# Install from source
git clone https://github.com/MITHaystack/digital_rf.git
cd digital_rf
pip install .
```

### Multicast Issues

If no RTP packets are received:

```bash
# Check multicast routing
ip mroute show

# Enable multicast loopback
sudo sysctl -w net.ipv4.conf.all.mc_forwarding=1

# Check firewall
sudo iptables -L -n | grep 239.251
```

### Permission Issues

If you get permission errors:

```bash
# Ensure data directory is writable
sudo chown -R $USER:$USER /mnt/grape-data

# Check file permissions
ls -la config/
```

## Verification

### Check Installation

```bash
# Verify Python version
python --version  # Should be 3.10+

# Verify dependencies
pip list | grep -E "scipy|digital_rf|numpy"

# Run tests
python test_grape_components.py
```

### Check ka9q-radio Integration

```bash
# Check for available streams
avahi-browse -ptr _rtp._udp

# Look for WWV/CHU channels
avahi-browse -ptr _rtp._udp | grep -i "wwv\|chu"

# Check status stream
avahi-browse -ptr _rtp._udp | grep status
```

## Upgrading

### Update Code

```bash
cd signal-recorder
git pull origin main
```

### Update Dependencies

```bash
# Activate virtual environment
source venv/bin/activate

# Update all dependencies
pip install --upgrade -r requirements.txt
```

### Verify After Upgrade

```bash
# Run tests
python test_grape_components.py

# Check for any issues
python test_grape_recorder.py
```

## Uninstallation

### Remove Package

```bash
# If installed with pip
pip uninstall signal-recorder

# Remove virtual environment
rm -rf venv
```

### Remove Data (Optional)

```bash
# Remove data directory (WARNING: deletes all recordings)
sudo rm -rf /mnt/grape-data
```

### Remove System Service (If Installed)

```bash
sudo systemctl stop grape-recorder
sudo systemctl disable grape-recorder
sudo rm /etc/systemd/system/grape-recorder.service
sudo systemctl daemon-reload
```

## Support

For installation issues:

1. Check logs: `/tmp/grape_recorder_test.log`
2. Review this installation guide
3. Check system requirements
4. Verify all dependencies are installed
5. Consult the main documentation: `docs/GRAPE_DIGITAL_RF_RECORDER.md`

## Additional Resources

- [GRAPE Documentation](docs/GRAPE_DIGITAL_RF_RECORDER.md)
- [Configuration Guide](docs/configuration.md)
- [Deployment Guide](DEPLOYMENT_GUIDE.md)
- [Development Status](DEVELOPMENT_STATUS.md)

