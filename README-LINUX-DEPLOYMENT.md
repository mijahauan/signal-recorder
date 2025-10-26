## 🎉 **System Status: FULLY OPERATIONAL!**

✅ **Web Interface**: http://localhost:3000/monitoring  
✅ **Daemon Control**: Start/stop via web interface or API  
✅ **Channel Addresses**: Using correct multicast address (239.192.152.141:5004)  
✅ **Background Processes**: Daemon and watchdog running properly  
✅ **Status Monitoring**: Real-time status updates via JSON file  

### **Channel Configuration Details:**
- **Multicast Address**: 239.192.152.141:5004 (your radio system addresses)
- **Channel Count**: 9 channels (6 WWV + 3 CHU time/frequency stations)
- **Sample Rate**: 12kHz per channel for high-quality signal capture
- **Format**: IQ mode for full bandwidth signal processing
- **Discovery Method**: CLI discovery prioritizes real radio addresses

## 🚀 Quick Start

### Option 1: Development Setup (Recommended for Testing)

```bash
# 1. Navigate to web-ui directory
cd web-ui

# 2. Run the setup script to copy files to Linux environment
../setup-linux-dev.sh

# 3. Start the web server
pnpm start

# 4. Access the web interface
# Open http://localhost:3000/monitoring in your browser
```

### Option 2: Production Systemd Service

```bash
# 1. Make the install script executable
chmod +x install-linux.sh

# 2. Run the installation script as root
sudo ./install-linux.sh

# 3. Start the services
sudo systemctl start signal-recorder-daemon
sudo systemctl start signal-recorder-web

# 4. Access the web interface
# Open http://localhost:3000/monitoring in your browser
```

## 📋 What Gets Set Up

### Development Setup
- Copies signal-recorder files to Linux environment paths
- Creates necessary directories (`config/`, `test-data/`)
- Makes scripts executable
- Preserves development workflow

### Production Setup
- **System Services**: `signal-recorder-daemon.service`, `signal-recorder-web.service`
- **Files**: `/usr/local/bin/signal-recorder-*`, `/usr/local/lib/signal-recorder/`
- **Config**: `/etc/signal-recorder/config.toml`
- **Data**: `/var/lib/signal-recorder/test-data/`
- **Logs**: `/var/log/signal-recorder/` (via systemd journal)

## 🔧 Management Commands

### Development Mode
```bash
# Start web server
pnpm start

# Test daemon directly
python3 ../test-daemon.py --config ../config/grape-S000171.toml

# Check daemon status
curl -H "Authorization: Bearer admin-token" http://localhost:3000/api/monitoring/daemon-status

# Start daemon via API
curl -H "Authorization: Bearer admin-token" -X POST \
  -H "Content-Type: application/json" \
  -d '{"action":"start"}' \
  http://localhost:3000/api/monitoring/daemon-control
```

### Production Mode
```bash
# Start services
sudo systemctl start signal-recorder-daemon
sudo systemctl start signal-recorder-web

# Check status
sudo systemctl status signal-recorder-daemon
sudo systemctl status signal-recorder-web

# View logs
sudo journalctl -f -u signal-recorder-daemon
sudo journalctl -f -u signal-recorder-web

# Enable auto-start
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

### Development Mode
Configuration files are read from the repository structure:
- `config/grape-S000171.toml` - main configuration
- `test-daemon.py` - daemon script
- `test-watchdog.py` - monitoring script

### Production Mode
Files are installed in system locations:
- `/etc/signal-recorder/config.toml` - main configuration
- `/usr/local/bin/signal-recorder-daemon` - daemon script
- `/usr/local/lib/signal-recorder/` - source code and web UI

## 🔍 Troubleshooting

### Check Path Resolution
```bash
# Test if paths are correct
cd web-ui
node -e "
import { join } from 'path';
import { fileURLToPath } from 'url';
const __dirname = join(fileURLToPath(import.meta.url), '..');
const installDir = join(__dirname, '..');
console.log('Web UI directory:', __dirname);
console.log('Install directory:', installDir);
console.log('Config path:', join(installDir, 'config', 'grape-S000171.toml'));
console.log('Daemon path:', join(installDir, 'test-daemon.py'));
"
```

### Common Issues

1. **Path Errors**: Files not found in expected locations
   - **Development**: Run `../setup-linux-dev.sh` to copy files
   - **Production**: Run `sudo ./install-linux.sh` to install properly

2. **Permission Errors**: Cannot access files or directories
   - **Development**: Ensure files are readable in Linux environment
   - **Production**: Check that systemd services have proper permissions

3. **Port Conflicts**: Port 3000 already in use
   - **Development**: Stop other processes using port 3000
   - **Production**: Configure different port in service files

4. **Missing Dependencies**: Python3 or Node.js not available
   - Install required packages: `sudo apt install python3 nodejs npm`

### API Testing
```bash
# Check daemon status
curl -H "Authorization: Bearer admin-token" http://localhost:3000/api/monitoring/daemon-status

# Start daemon
curl -H "Authorization: Bearer admin-token" -X POST \
  -H "Content-Type: application/json" \
  -d '{"action":"start"}' \
  http://localhost:3000/api/monitoring/daemon-control

# Stop daemon
curl -H "Authorization: Bearer admin-token" -X POST \
  -H "Content-Type: application/json" \
  -d '{"action":"stop"}' \
  http://localhost:3000/api/monitoring/daemon-control
```

## 📁 File Structure

### Development Mode
```
/home/mjh/git/signal-recorder/
├── config/
│   └── grape-S000171.toml
├── test-daemon.py
├── test-watchdog.py
├── test-discover.py
├── src/
├── web-ui/
│   └── simple-server.js
└── test-data/
```

### Production Mode
```
/usr/local/bin/
├── signal-recorder-daemon
├── signal-recorder-web
└── signal-recorder-watchdog

/usr/local/lib/signal-recorder/
├── src/
├── web-ui/
└── test-data/

/etc/signal-recorder/
└── config.toml

/var/lib/signal-recorder/
└── test-data/raw/
```

## 🔄 Updates

### Development Mode
```bash
# Pull latest changes
git pull

# Restart web server
# The server will automatically pick up file changes
```

### Production Mode
```bash
# Stop services
sudo systemctl stop signal-recorder-daemon
sudo systemctl stop signal-recorder-web

# Update files
sudo cp -r /path/to/updated/signal-recorder/* /usr/local/lib/signal-recorder/

# Restart services
sudo systemctl restart signal-recorder-daemon
sudo systemctl restart signal-recorder-web
```

## 🛡️ Security

- **Development**: Runs as current user, requires manual authentication
- **Production**: Runs as `signal-recorder` system user with restricted permissions
- **Authentication**: Web interface requires Bearer token authentication
- **Logs**: All operations logged via systemd journal in production

## 📊 Monitoring

Access the monitoring dashboard at: http://localhost:3000/monitoring

The dashboard provides real-time information about:
- Daemon process status and verification
- Data collection statistics
- Active channel configurations
- System logs and error messages
- Recording activity and file generation

This setup provides both development flexibility and production-ready deployment options for Linux systems.

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
