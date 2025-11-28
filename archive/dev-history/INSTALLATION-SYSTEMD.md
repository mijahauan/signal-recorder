# Signal Recorder - Systemd Installation Guide

Complete guide for installing signal-recorder as a systemd service with standardized paths.

---

## Prerequisites

- Linux system with systemd
- Python 3.8 or later
- Node.js 16 or later
- ka9q-radio (radiod) installed and running
- Root access for system installation

---

## Installation Steps

### 1. Create System User

Create a dedicated user for running the signal-recorder service:

```bash
sudo useradd -r -s /bin/false -c "GRAPE Signal Recorder" signal-recorder
```

### 2. Create Directory Structure

Create the standardized FHS-compliant directory structure:

```bash
# Data directories
sudo mkdir -p /var/lib/signal-recorder/{data,analytics,upload,status}
sudo mkdir -p /var/lib/signal-recorder/analytics/{quality,timing,reports}
sudo mkdir -p /var/lib/signal-recorder-web

# Configuration
sudo mkdir -p /etc/signal-recorder/credentials

# Logs
sudo mkdir -p /var/log/signal-recorder

# Application installation
sudo mkdir -p /opt/signal-recorder
```

### 3. Set Permissions

```bash
# Data directories (signal-recorder user)
sudo chown -R signal-recorder:signal-recorder /var/lib/signal-recorder
sudo chown -R signal-recorder:signal-recorder /var/lib/signal-recorder-web
sudo chown -R signal-recorder:signal-recorder /var/log/signal-recorder

# Configuration (readable by signal-recorder)
sudo chown -R root:signal-recorder /etc/signal-recorder
sudo chmod 750 /etc/signal-recorder

# Credentials (restrictive)
sudo chmod 700 /etc/signal-recorder/credentials
sudo chown signal-recorder:signal-recorder /etc/signal-recorder/credentials
```

### 4. Install Application

```bash
# Clone repository
cd /opt
sudo git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# Install Python dependencies
sudo pip3 install -e .

# Install Node.js dependencies (web UI)
cd web-ui
sudo npm install --production
cd ..

# Set ownership
sudo chown -R root:root /opt/signal-recorder
```

### 5. Configure Application

```bash
# Copy configuration template
sudo cp config/grape-production-v2.toml /etc/signal-recorder/config.toml

# Edit configuration
sudo nano /etc/signal-recorder/config.toml
```

**Important configuration items:**
- `[station]` - Your callsign, grid square, station ID
- `[ka9q]` - Multicast addresses for your radiod instance
- `[[recorder.channels]]` - Enable/disable channels

### 6. Set Up Credentials

#### SSH Key for PSWS Uploads

If you'll be uploading to HamSCI PSWS:

```bash
# Generate SSH key (if you don't have one)
sudo -u signal-recorder ssh-keygen -t rsa -b 4096 -f /etc/signal-recorder/credentials/psws_ssh_key -N ""

# Set restrictive permissions
sudo chmod 600 /etc/signal-recorder/credentials/psws_ssh_key

# Copy public key to PSWS (you'll need to provide this to HamSCI)
cat /etc/signal-recorder/credentials/psws_ssh_key.pub
```

#### JWT Secret for Web UI

```bash
# Generate random JWT secret
openssl rand -base64 32 | sudo tee /etc/signal-recorder/credentials/jwt_secret.txt
sudo chmod 600 /etc/signal-recorder/credentials/jwt_secret.txt
sudo chown signal-recorder:signal-recorder /etc/signal-recorder/credentials/jwt_secret.txt
```

#### Web UI Admin User

```bash
# Initialize default admin user (first time only)
cd /opt/signal-recorder/web-ui
sudo -u signal-recorder node scripts/create-admin.js admin <your-secure-password>
```

### 7. Install Systemd Services

```bash
# Copy service files
sudo cp systemd/signal-recorder.service /etc/systemd/system/
sudo cp systemd/signal-recorder-web.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable signal-recorder.service
sudo systemctl enable signal-recorder-web.service
```

### 8. Start Services

```bash
# Start recorder service
sudo systemctl start signal-recorder.service

# Check status
sudo systemctl status signal-recorder.service

# View logs
sudo journalctl -u signal-recorder.service -f

# Start web UI
sudo systemctl start signal-recorder-web.service

# Check status
sudo systemctl status signal-recorder-web.service
```

### 9. Verify Installation

#### Check Data Recording

```bash
# Check for Digital RF files
ls -lh /var/lib/signal-recorder/data/

# Check status file
cat /var/lib/signal-recorder/status/recording-stats.json | jq
```

#### Access Web UI

Open browser to: `http://your-server:3000`

Default credentials:
- Username: `admin`
- Password: (the password you set in step 6)

**IMPORTANT:** Change the default password immediately!

#### Check Logs

```bash
# Recorder logs
sudo journalctl -u signal-recorder.service -n 100

# Web UI logs
sudo journalctl -u signal-recorder-web.service -n 100

# All signal-recorder logs
sudo journalctl -t signal-recorder -t signal-recorder-web -f
```

---

## Data Management

### Check Data Usage

```bash
# Show storage summary
signal-recorder data summary

# Or manually check
du -sh /var/lib/signal-recorder/data
du -sh /var/lib/signal-recorder/analytics
```

### Clean Old Data

```bash
# Preview what would be deleted (dry run)
signal-recorder data clean-all --dry-run

# Delete all RTP data (with confirmation)
signal-recorder data clean-all

# Delete only recordings (keep analytics)
signal-recorder data clean-data

# Delete only analytics (can be regenerated)
signal-recorder data clean-analytics
```

### Backup Important Data

```bash
# Backup configuration and credentials
sudo tar -czf signal-recorder-config-backup.tar.gz \
  /etc/signal-recorder \
  /var/lib/signal-recorder-web

# Backup RTP data (large!)
sudo tar -czf signal-recorder-data-backup.tar.gz \
  /var/lib/signal-recorder/data
```

---

## Upgrading

### Application Update

```bash
# Stop services
sudo systemctl stop signal-recorder.service signal-recorder-web.service

# Update code
cd /opt/signal-recorder
sudo git pull

# Update Python dependencies
sudo pip3 install -e . --upgrade

# Update Node.js dependencies
cd web-ui
sudo npm install --production
cd ..

# Restart services
sudo systemctl start signal-recorder.service signal-recorder-web.service
```

### Configuration Update

```bash
# Edit configuration
sudo nano /etc/signal-recorder/config.toml

# Restart services to apply changes
sudo systemctl restart signal-recorder.service
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check service status
sudo systemctl status signal-recorder.service

# Check for errors in logs
sudo journalctl -u signal-recorder.service -n 100

# Check configuration
signal-recorder validate-config /etc/signal-recorder/config.toml

# Check permissions
sudo -u signal-recorder ls -l /var/lib/signal-recorder
```

### No Data Being Recorded

```bash
# Check if radiod is running
systemctl status ka9q-radio.service

# Check multicast reception
sudo tcpdump -i any 'net 239.192.152.0/24'

# Check channel configuration
signal-recorder channels list

# Verify output directory
ls -lh /var/lib/signal-recorder/data/
```

### Web UI Not Accessible

```bash
# Check if service is running
sudo systemctl status signal-recorder-web.service

# Check if port is listening
sudo netstat -tlnp | grep 3000

# Check logs
sudo journalctl -u signal-recorder-web.service -n 50

# Try accessing locally
curl http://localhost:3000/
```

### High Memory Usage

```bash
# Check current memory usage
systemctl status signal-recorder.service | grep Memory

# Adjust memory limit in service file
sudo nano /etc/systemd/system/signal-recorder.service
# Change: MemoryMax=2G

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart signal-recorder.service
```

### Disk Space Issues

```bash
# Check disk usage
df -h /var/lib/signal-recorder

# Check which channels are using most space
du -sh /var/lib/signal-recorder/data/*

# Clean old data
signal-recorder data clean-data --older-than 30d

# Or manually delete specific channels
sudo rm -rf /var/lib/signal-recorder/data/WWV-2.5
```

---

## Security Best Practices

### File Permissions

Verify restrictive permissions on sensitive files:

```bash
# Credentials should be 0600 or 0700
ls -la /etc/signal-recorder/credentials/

# Fix if needed
sudo chmod 700 /etc/signal-recorder/credentials
sudo chmod 600 /etc/signal-recorder/credentials/*
```

### Network Security

```bash
# Firewall: Allow only necessary ports
sudo ufw allow 3000/tcp  # Web UI (adjust as needed)

# Consider using nginx reverse proxy with HTTPS
# See: nginx-setup.md
```

### Regular Updates

```bash
# Set up automatic security updates
sudo apt install unattended-upgrades

# Or manually update regularly
sudo apt update && sudo apt upgrade
```

---

## Monitoring

### Systemd Status

```bash
# Check all signal-recorder services
systemctl status 'signal-recorder*'

# Set up systemd email alerts
# Edit: /etc/systemd/system/signal-recorder.service
# Add: OnFailure=status-email@%n.service
```

### Data Quality Monitoring

```bash
# Check recording stats
cat /var/lib/signal-recorder/status/recording-stats.json | jq

# Check WWV timing validation
tail -f /var/lib/signal-recorder/analytics/timing/wwv_timing.csv

# Check for gaps
signal-recorder data check-quality --date 2025-11-03
```

### Log Rotation

Logs are automatically managed by journald, but you can configure rotation:

```bash
# Edit journald config
sudo nano /etc/systemd/journald.conf

# Recommended settings:
# SystemMaxUse=1G
# SystemMaxFileSize=100M
# MaxRetentionSec=1month

# Restart journald
sudo systemctl restart systemd-journald
```

---

## Uninstallation

If you need to completely remove the installation:

```bash
# Stop and disable services
sudo systemctl stop signal-recorder.service signal-recorder-web.service
sudo systemctl disable signal-recorder.service signal-recorder-web.service

# Remove service files
sudo rm /etc/systemd/system/signal-recorder*.service
sudo systemctl daemon-reload

# Remove application
sudo rm -rf /opt/signal-recorder

# Remove data (CAREFUL - this deletes all recordings!)
sudo rm -rf /var/lib/signal-recorder
sudo rm -rf /var/lib/signal-recorder-web
sudo rm -rf /etc/signal-recorder
sudo rm -rf /var/log/signal-recorder

# Remove user
sudo userdel signal-recorder
```

---

## Migration from Old Installation

If you have an existing installation in a different location:

```bash
# Run migration script
cd /opt/signal-recorder
sudo ./scripts/migrate-data-storage.sh

# Or dry-run first
./scripts/migrate-data-storage.sh --dry-run

# Follow the migration prompts
```

See: [DATA-STORAGE-AUDIT.md](DATA-STORAGE-AUDIT.md) for details on the new structure.

---

## Support

- Documentation: `/opt/signal-recorder/docs/`
- Issue Tracker: https://github.com/yourusername/signal-recorder/issues
- HamSCI: https://hamsci.org/grape

---

**Last Updated:** 2025-11-03
