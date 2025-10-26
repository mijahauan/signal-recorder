# Signal Recorder - Linux System Service Setup

This guide explains how to deploy the Signal Recorder application as a systemd service on Linux systems.

## 🚀 Quick Installation

```bash
# 1. Copy files to your Linux system
# 2. Make the install script executable
chmod +x install-linux.sh

# 3. Run the installation script as root
sudo ./install-linux.sh

# 4. Start the services
sudo systemctl start signal-recorder-daemon
sudo systemctl start signal-recorder-web

# 5. Access the web interface
# Open http://localhost:3000/monitoring in your browser
```

## 📋 What Gets Installed

### System Services
- **signal-recorder-daemon.service**: Runs the data recording daemon
- **signal-recorder-web.service**: Runs the web configuration interface

### Files and Directories
- **Daemon script**: `/usr/local/bin/signal-recorder-daemon`
- **Web interface**: `/usr/local/bin/signal-recorder-web`
- **Configuration**: `/etc/signal-recorder/config.toml`
- **Data directory**: `/var/lib/signal-recorder/test-data/`
- **Log files**: `/var/log/signal-recorder/`
- **Source code**: `/usr/local/lib/signal-recorder/`

## 🔧 Management Commands

```bash
# Start services
sudo systemctl start signal-recorder-daemon
sudo systemctl start signal-recorder-web

# Stop services
sudo systemctl stop signal-recorder-daemon
sudo systemctl stop signal-recorder-web

# Restart services
sudo systemctl restart signal-recorder-daemon
sudo systemctl restart signal-recorder-web

# Check status
sudo systemctl status signal-recorder-daemon
sudo systemctl status signal-recorder-web

# View logs
sudo journalctl -f -u signal-recorder-daemon
sudo journalctl -f -u signal-recorder-web

# Enable auto-start on boot
sudo systemctl enable signal-recorder-daemon
sudo systemctl enable signal-recorder-web
```

## 🌐 Web Interface

- **URL**: http://localhost:3000/monitoring
- **Login**: admin / admin
- **Features**:
  - Monitor daemon status
  - Start/stop the recording daemon
  - View data collection statistics
  - Configure recording channels
  - Export configurations

## ⚙️ Configuration

### Main Configuration File
Edit `/etc/signal-recorder/config.toml` to configure:

```toml
[station]
callsign = "YOUR_CALLSIGN"
grid_square = "YOUR_GRID"
id = "YOUR_STATION_ID"

[recorder]
data_dir = "/var/lib/signal-recorder/data"
continuous = true
recording_interval = 60

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
preset = "iq"
sample_rate = 12000
description = "WWV 2.5 MHz"
```

### Environment Variables

For production deployment, set:
```bash
export NODE_ENV=production
```

## 🛠️ Development vs Production

### Development Mode (default)
- Uses paths relative to repository root
- Runs on port 3000
- Uses development settings

### Production Mode
Set `NODE_ENV=production` to:
- Use system installation paths (`/usr/local/lib/`, `/etc/`, `/var/lib/`)
- Optimized for system service deployment
- Production logging and error handling

## 🔍 Troubleshooting

### Check Service Status
```bash
sudo systemctl status signal-recorder-daemon
sudo systemctl status signal-recorder-web
```

### View Detailed Logs
```bash
sudo journalctl -u signal-recorder-daemon -n 50
sudo journalctl -u signal-recorder-web -n 50
```

### Test API Endpoints
```bash
# Check daemon status
curl -H "Authorization: Bearer admin-token" http://localhost:3000/api/monitoring/daemon-status

# Start daemon
curl -H "Authorization: Bearer admin-token" -X POST \
  -H "Content-Type: application/json" \
  -d '{"action":"start"}' \
  http://localhost:3000/api/monitoring/daemon-control
```

### Common Issues

1. **Permission Errors**: Ensure the `signal-recorder` user has access to data directories
2. **Port Conflicts**: Make sure port 3000 is available
3. **Missing Dependencies**: Install Node.js and Python3
4. **Path Issues**: Verify all files are in the correct system locations

## 📁 File Structure

After installation:
```
/usr/local/bin/
├── signal-recorder-daemon    # Main daemon script
├── signal-recorder-web       # Web interface launcher
└── signal-recorder-watchdog  # Daemon monitoring script

/usr/local/lib/signal-recorder/
├── src/                      # Source code
├── web-ui/                   # Web interface files
└── test-data/                # Test data directory

/etc/signal-recorder/
└── config.toml               # Main configuration

/var/lib/signal-recorder/
└── test-data/raw/            # Recording data

/var/log/
└── signal-recorder/          # Log files (via journald)
```

## 🔄 Updates and Maintenance

### Update Installation
```bash
# Stop services
sudo systemctl stop signal-recorder-daemon
sudo systemctl stop signal-recorder-web

# Copy new files
sudo cp -r /path/to/updated/signal-recorder/* /usr/local/lib/signal-recorder/

# Restart services
sudo systemctl restart signal-recorder-daemon
sudo systemctl restart signal-recorder-web
```

### Backup Configuration
```bash
sudo cp /etc/signal-recorder/config.toml /etc/signal-recorder/config.toml.backup
```

## 📊 Monitoring

The web interface provides real-time monitoring of:
- Daemon process status
- Data collection statistics
- Channel configurations
- System logs
- Recording activity

Access the monitoring dashboard at: http://localhost:3000/monitoring

## 🛡️ Security Notes

- Services run as the `signal-recorder` system user
- Web interface requires authentication (admin/admin by default)
- All data operations are logged via systemd journal
- Configuration files are protected with appropriate permissions

## 📝 Logs

View logs with:
```bash
sudo journalctl -f -u signal-recorder-daemon
sudo journalctl -f -u signal-recorder-web
sudo journalctl --since today -u signal-recorder-daemon
```

This setup provides a production-ready deployment of the Signal Recorder application as a proper Linux system service.
