# Installation Guide

Quick installation guide for GRAPE Signal Recorder.

## Prerequisites

- **Linux system** (tested on Ubuntu/Debian)
- **Python 3.9+**
- **Node.js 18+** (for web UI)
- **ka9q-radio** running on network

## Quick Start

### 1. Clone Repository
```bash
git clone <repository-url>
cd signal-recorder
```

### 2. Install System Dependencies
```bash
sudo apt-get update
sudo apt-get install avahi-utils libhdf5-dev
```

### 3. Setup Python Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Install WWV Timing Visualization (Optional)
```bash
pip install pandas matplotlib
```

### 5. Setup Web UI
```bash
cd web-ui
npm install  # or: pnpm install
cd ..
```

### 6. Configure
```bash
# Copy example config
cp config/grape-S000171.toml config/my-station.toml

# Edit with your station details
nano config/my-station.toml
```

### 7. Start Services

#### Start Daemon (in one terminal)
```bash
source venv/bin/activate
python -m signal_recorder.cli daemon
```

#### Start Web UI (in another terminal)
```bash
cd web-ui
node simple-server.js
```

#### Access Monitoring
Open browser to: `http://localhost:3000/monitoring.html`

## Verify Installation

### Check Python Dependencies
```bash
source venv/bin/activate
python -c "import numpy, scipy, toml; print('✅ Core OK')"
python -c "import digital_rf; print('✅ Digital RF OK')"
python -c "import pandas, matplotlib; print('✅ Visualization OK')" 2>/dev/null || echo "⚠️  Visualization tools not installed (optional)"
```

### Check Node Dependencies
```bash
cd web-ui && npm list express toml
```

### Test ka9q-radio Discovery
```bash
avahi-browse _ka9q-ctl._udp -t
```

Should show radiod control service.

## Troubleshooting

### digital_rf Fails to Install
```bash
# Install HDF5 development libraries first
sudo apt-get install libhdf5-dev pkg-config

# Then retry
pip install digital_rf
```

### No Channels Found
- Check radiod is running: `systemctl status radiod` (or equivalent)
- Verify multicast routing: `ip route show | grep 239`
- Test avahi discovery: `avahi-browse _ka9q-ctl._udp -t`

### Web UI Won't Start
```bash
# Check Node.js version (need 18+)
node --version

# Reinstall dependencies
cd web-ui
rm -rf node_modules
npm install
```

### WWV Timing Tab Shows No Data
- Wait for minute boundary (:00 seconds)
- Check daemon logs: `tail -f logs/daemon.log | grep "WWV tone"`
- Verify CSV file exists: `ls -lh logs/wwv_timing.csv`

## Next Steps

1. **Configure channels** in `config/my-station.toml`
2. **Monitor recording** at `http://localhost:3000/monitoring.html`
3. **View WWV timing** in the "WWV Timing" tab
4. **Check logs**: `logs/daemon.log`
5. **Access data**: `data/<station_name>/`

## Complete Documentation

- [DEPENDENCIES.md](DEPENDENCIES.md) - Full dependency list
- [README.md](README.md) - Project overview
- [WWV-TIMING-ANALYSIS.md](WWV-TIMING-ANALYSIS.md) - Timing analysis guide
