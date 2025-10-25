# Installation Guide

This guide provides instructions for installing Signal Recorder and its dependencies.

## 📋 **Quick Start (Recommended)**

For most users, the **web-based configuration UI** is the easiest way to get started:

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# 2. Start the configuration UI
cd web-ui
npm install
npm start

# 3. Access http://localhost:3000 (admin/admin)
# 4. Create your configuration through the guided interface
# 5. Save directly to the config/ directory
```

**The web UI will generate the correct configuration file automatically!**

---

## 1. Prerequisites

### 1.1 ka9q-radio

Signal Recorder requires a running instance of [ka9q-radio](https://github.com/ka9q/ka9q-radio) to provide the RTP signal streams. Please ensure radiod is installed, configured, and running.

### 1.2 System Dependencies

#### **For Signal Recorder:**
- **Python**: 3.10 or higher
- **Avahi**: For mDNS service discovery

#### **For Configuration UI:**
- **pnpm**: 10.0 or higher (recommended, faster than npm)
- **npm**: Alternative if pnpm is not available

#### **Installation on Debian/Ubuntu:**
```bash
# For signal-recorder
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv avahi-daemon avahi-utils

# For web UI (recommended: pnpm)
curl -fsSL https://get.pnpm.io/install.js | sh -

# Alternative: npm
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs npm
```

## 2. Installation

### 2.1 From Source

It is recommended to install Signal Recorder in a Python virtual environment.

```bash
# Clone the repository
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the package in editable mode
pip install -e .
```

### 2.2 From PyPI (Future)

Once published, you will be able to install from PyPI:

```bash
pip install signal-recorder
```

## 3. Configuration

### 3.1 Web-Based Configuration UI (Recommended)

The project includes a **simplified web-based configuration interface** that eliminates the need for manual TOML editing.

```bash
# Install dependencies with pnpm (recommended)
cd web-ui
pnpm install

# Alternative: npm
# npm install

# Start the configuration UI
pnpm start

# Alternative: npm
# npm start

# Access the interface
# URL: http://localhost:3000
# Login: admin / admin

# Create configuration through guided interface
# Save directly to config/ directory
```

**Features:**
- ✅ **Guided setup** with form validation
- ✅ **Channel presets** for WWV/CHU frequencies
- ✅ **Auto-generates** correct TOML format
- ✅ **Real-time validation** prevents configuration errors
- ✅ **Save to config directory** with one click

### 3.2 Manual Configuration (Advanced Users)

For advanced users or those preferring direct editing:

1. **Copy example configuration:**
   ```bash
   cp config/grape-production.toml config/grape-your-station.toml
   ```

2. **Edit configuration:**
   ```bash
   nano config/grape-your-station.toml
   ```

3. **Key sections to update:**
   - **`[station]`**: Your callsign, grid square, station ID
   - **`[ka9q]`**: ka9q-radio status address
   - **`[[recorder.channels]]`**: Channels to record (SSRC = frequency in Hz)
   - **`[uploader]`**: PSWS server settings (if participating)

4. **Validate configuration:**
   ```bash
   python3 -c "import toml; toml.load('config/grape-your-station.toml')"
   ```

### 3.3 Create Directories

Create the archive directory specified in the configuration:

```bash
# Create data directory
sudo mkdir -p /var/lib/signal-recorder/data

# Create archive directory
sudo mkdir -p /var/lib/signal-recorder/archive

# Set appropriate permissions
sudo chown -R $USER:$USER /var/lib/signal-recorder
```

## 4. Testing

### 4.1 Verify Configuration

Test if your configuration is valid:

```bash
# Validate TOML syntax and format
python3 -c "
import toml
config = toml.load('config/grape-your-station.toml')
print('✅ Configuration valid')
print(f'Station: {config[\"station\"][\"callsign\"]}')
print(f'Channels: {len(config.get(\"recorder\", {}).get(\"channels\", []))}')
"
```

### 4.2 Discover RTP Streams

Test if Signal Recorder can discover streams from your ka9q-radio:

```bash
# Activate virtual environment
source venv/bin/activate

# Discover available streams
python3 -c "
from signal_recorder.discovery import discover_streams
streams = discover_streams('your-radiod-hostname.local')
for stream in streams:
    print(f'Stream: {stream.name}, Channels: {len(stream.channels)}')
"
```

### 4.3 Run Test Recording

Run a short test to verify everything works:

```bash
# Test with your configuration
python3 test_grape_recorder.py --config config/grape-your-station.toml

# Monitor the logs
tail -f /tmp/grape_recorder_test.log
```

## 5. Running as a Service

### 5.1 Create systemd Service File

Create `/etc/systemd/system/signal-recorder.service`:

```ini
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
```

### 5.2 Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable signal-recorder.service

# Start the service
sudo systemctl start signal-recorder.service

# Check status
sudo systemctl status signal-recorder.service

# View logs
sudo journalctl -u signal-recorder -f
```

## 6. Configuration UI Setup (Optional)

The web UI can also be run as a service:

```bash
# Create service file for web UI
sudo tee /etc/systemd/system/grape-config-ui.service > /dev/null <<EOF
[Unit]
Description=GRAPE Configuration UI
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/signal-recorder/web-ui
Environment="NODE_ENV=production"
ExecStart=/usr/local/bin/pnpm start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Alternative: if using npm
# ExecStart=/usr/bin/node simple-server.js

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable grape-config-ui
sudo systemctl start grape-config-ui
```

**Access:** http://your-server:3000 (admin/admin)

## 7. Monitoring

### 7.1 Log Files

- **Signal Recorder logs:** `/tmp/grape_recorder_test.log`
- **System logs:** `sudo journalctl -u signal-recorder -f`
- **Web UI logs:** Check systemd journal or console output

### 7.2 Status Monitoring

```bash
# Check service status
sudo systemctl status signal-recorder

# Check web UI status
sudo systemctl status grape-config-ui

# Monitor recording activity
find /var/lib/signal-recorder/archive -name "drf_*.h5" -mmin -10
```

### 7.3 Quality Metrics

After 24 hours of recording, check quality metrics:

```bash
# Find recent quality reports
find /var/lib/signal-recorder/archive -name "*_summary.txt" -mtime -1

# Check data completeness
grep "Completeness:" /var/lib/signal-recorder/archive/*/*/*_summary.txt
```

## 8. Troubleshooting

### Configuration Issues
- **Use web UI** for guided configuration (recommended)
- **Validate TOML** syntax before running recorder
- **Check permissions** on config and data directories

### Network Issues
- **Verify ka9q-radio** is running and discoverable
- **Check multicast** routing and firewall rules
- **Test connectivity** using the discovery tools

### Recording Issues
- **Monitor logs** for error messages
- **Check disk space** in data directories
- **Verify channel** configuration matches ka9q-radio output

### Web UI Issues
```bash
# Check if server starts
cd web-ui
npm start

# Alternative port
PORT=8080 npm start

# Check login (admin/admin)
# Verify config directory permissions
```

## 9. Updates

### Update Signal Recorder
```bash
# Activate virtual environment
source venv/bin/activate

# Pull latest changes
git pull

# Reinstall package
pip install -e .
```

### Update Web UI
```bash
# Pull latest changes
git pull

# Update dependencies
cd web-ui
npm install
```

## 10. Support

For issues or questions:

1. **Check logs** in `/tmp/grape_recorder_test.log` or systemd journal
2. **Use web UI** for configuration (eliminates most setup issues)
3. **Validate configuration** using the Python validation script
4. **Test with minimal config** before full deployment

**The web-based configuration UI eliminates most common setup issues by providing guided configuration with validation!**

