# GRAPE Recorder - systemd Service Installation

**Purpose:** Set up GRAPE recorder as a production systemd service with automatic restart and boot-time startup.

---

## What the Service Provides

✅ **Automatic start on boot** - Starts after power cycle/reboot  
✅ **Automatic restart on crash** - If process dies, restarts in 30 seconds  
✅ **Restart limiting** - Prevents infinite restart loops (max 5 attempts in 5 minutes)  
✅ **Dependency management** - Waits for network and radiod to be ready  
✅ **Resource limits** - Prevents runaway memory/CPU usage  
✅ **Security hardening** - Runs with minimal privileges  
✅ **Logging** - All output goes to systemd journal  

---

## Restart Behavior Explained

### With `Restart=always` (Production - Recommended)

| Event | Behavior |
|-------|----------|
| Process crashes (segfault, exception) | ✅ Restarts in 30s |
| Process exits with error (exit 1) | ✅ Restarts in 30s |
| Process exits cleanly (exit 0) | ✅ Restarts in 30s |
| Killed with SIGTERM/SIGKILL | ✅ Restarts in 30s |
| Manual `systemctl stop` | ❌ Stays stopped (as intended) |
| Manual `systemctl restart` | ✅ Restarts immediately |
| System reboot | ✅ Starts on boot |

### With `Restart=on-failure` (Testing - Current Default)

| Event | Behavior |
|-------|----------|
| Process crashes (segfault, exception) | ✅ Restarts in 30s |
| Process exits with error (exit 1) | ✅ Restarts in 30s |
| Process exits cleanly (exit 0) | ❌ Stays stopped |
| Killed with SIGTERM | ❌ Stays stopped |
| Manual `systemctl stop` | ❌ Stays stopped |
| System reboot | ✅ Starts on boot |

**Recommendation:** Use `Restart=always` for production!

---

## Installation Steps

### 1. Prepare the Environment

```bash
# Create production directories
sudo mkdir -p /var/lib/signal-recorder
sudo mkdir -p /var/log/signal-recorder
sudo mkdir -p /etc/signal-recorder

# Create dedicated user (security best practice)
sudo useradd -r -s /bin/false -d /var/lib/signal-recorder signal-recorder

# Set ownership
sudo chown -R signal-recorder:signal-recorder /var/lib/signal-recorder
sudo chown -R signal-recorder:signal-recorder /var/log/signal-recorder
```

### 2. Install the Application

```bash
# Option A: Install in system Python (recommended for services)
cd /home/mjh/git/signal-recorder
sudo pip3 install .

# Option B: Install in virtualenv (requires ExecStart adjustment)
# See "Alternative: Run from Virtual Environment" section below
```

### 3. Install Configuration

```bash
# Copy your working config to system location
sudo cp config/grape-config.toml /etc/signal-recorder/config.toml

# Update config for production paths
sudo sed -i 's|/tmp/grape-test|/var/lib/signal-recorder|g' /etc/signal-recorder/config.toml
sudo sed -i 's|mode = "test"|mode = "production"|g' /etc/signal-recorder/config.toml

# Verify config
cat /etc/signal-recorder/config.toml | grep -E "mode|data_root"

# Set proper permissions
sudo chown root:signal-recorder /etc/signal-recorder/config.toml
sudo chmod 640 /etc/signal-recorder/config.toml
```

### 4. Install systemd Service File

```bash
# Copy service file
sudo cp systemd/signal-recorder.service /etc/systemd/system/

# Reload systemd to recognize new service
sudo systemctl daemon-reload

# Verify service file is valid
sudo systemctl cat signal-recorder
```

### 5. Enable and Start Service

```bash
# Enable service (starts on boot)
sudo systemctl enable signal-recorder

# Start service now
sudo systemctl start signal-recorder

# Check status
sudo systemctl status signal-recorder
```

---

## Verify It's Working

### Check Service Status

```bash
# Quick status check
sudo systemctl status signal-recorder

# Should show:
# ● signal-recorder.service - GRAPE Signal Recorder
#    Loaded: loaded (/etc/systemd/system/signal-recorder.service; enabled; ...)
#    Active: active (running) since ...
#    Main PID: ...
```

### View Live Logs

```bash
# Follow logs in real-time
sudo journalctl -u signal-recorder -f

# View last 100 lines
sudo journalctl -u signal-recorder -n 100

# View logs from today
sudo journalctl -u signal-recorder --since today

# View logs with timestamps
sudo journalctl -u signal-recorder -o short-iso
```

### Check Data Directory

```bash
# Should be creating files
ls -lh /var/lib/signal-recorder/data/$(date +%Y%m%d)/

# Check disk usage
du -sh /var/lib/signal-recorder/
```

### Test Restart Behavior

```bash
# Kill the process (should restart in 30s)
sudo systemctl kill -s SIGKILL signal-recorder
sleep 35
sudo systemctl status signal-recorder  # Should be running again

# View restart in logs
sudo journalctl -u signal-recorder --since "5 minutes ago" | grep -E "Started|stopped"
```

---

## Management Commands

### Start/Stop/Restart

```bash
# Start service
sudo systemctl start signal-recorder

# Stop service (won't auto-restart)
sudo systemctl stop signal-recorder

# Restart service (graceful)
sudo systemctl restart signal-recorder

# Reload config without restart (if supported)
sudo systemctl reload signal-recorder
```

### Enable/Disable Auto-Start

```bash
# Enable auto-start on boot
sudo systemctl enable signal-recorder

# Disable auto-start (still can be started manually)
sudo systemctl disable signal-recorder

# Check if enabled
sudo systemctl is-enabled signal-recorder
```

### Status and Logs

```bash
# Check current status
sudo systemctl status signal-recorder

# View logs
sudo journalctl -u signal-recorder

# Follow logs
sudo journalctl -u signal-recorder -f

# View only errors
sudo journalctl -u signal-recorder -p err

# Export logs to file
sudo journalctl -u signal-recorder --since yesterday > recorder.log
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check for errors in service file
sudo systemctl status signal-recorder -l

# Check logs
sudo journalctl -u signal-recorder -n 50

# Test manually as the service user
sudo -u signal-recorder signal-recorder daemon --config /etc/signal-recorder/config.toml
```

### Permission Errors

```bash
# Ensure service user owns data directories
sudo chown -R signal-recorder:signal-recorder /var/lib/signal-recorder

# Check SELinux (if enabled)
sudo ausearch -m avc -ts recent

# Temporarily disable SELinux to test
sudo setenforce 0  # For testing only!
```

### Memory/CPU Issues

Edit `/etc/systemd/system/signal-recorder.service`:
```ini
[Service]
MemoryMax=4G        # Increase if needed
CPUQuota=100%       # Remove CPU limit
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart signal-recorder
```

### Restart Loops

If service keeps crashing:
```bash
# View crash logs
sudo journalctl -u signal-recorder --since "10 minutes ago" | grep -i error

# Check if hitting restart limit
sudo systemctl status signal-recorder | grep "start-limit"

# Reset restart limit counter
sudo systemctl reset-failed signal-recorder
```

---

## Alternative: Run from Virtual Environment

If you want to keep the application in a venv instead of system-wide:

### Modify Service File

Edit `/etc/systemd/system/signal-recorder.service`:

```ini
[Service]
# Point to venv installation
WorkingDirectory=/home/mjh/git/signal-recorder
ExecStart=/home/mjh/git/signal-recorder/venv/bin/signal-recorder daemon --config /etc/signal-recorder/config.toml

# Run as mjh user instead of dedicated user
User=mjh
Group=mjh

# Update paths for mjh user
ReadWritePaths=/var/lib/signal-recorder /home/mjh/git/signal-recorder
```

Then reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart signal-recorder
```

---

## Monitoring and Alerts

### Set Up Systemd Email Alerts

Install postfix or similar MTA, then create `/etc/systemd/system/signal-recorder-notify@.service`:

```ini
[Unit]
Description=Send email when signal-recorder fails

[Service]
Type=oneshot
ExecStart=/usr/local/bin/systemd-email-notify.sh %i
```

### Create Notification Script

`/usr/local/bin/systemd-email-notify.sh`:
```bash
#!/bin/bash
SERVICE=$1
STATUS=$(systemctl status $SERVICE)
echo "Service $SERVICE failed: $STATUS" | mail -s "ALERT: $SERVICE failed" you@example.com
```

### Enable Alerts

```ini
# Add to [Unit] section of signal-recorder.service
OnFailure=signal-recorder-notify@%n.service
```

---

## Production Checklist

Before production deployment:

- [ ] Service file updated with `Restart=always`
- [ ] Config uses production paths (`/var/lib/signal-recorder`)
- [ ] Config has `mode = "production"`
- [ ] Dedicated user created (`signal-recorder`)
- [ ] Proper file permissions set
- [ ] Service enabled: `sudo systemctl enable signal-recorder`
- [ ] Service started: `sudo systemctl start signal-recorder`
- [ ] Logs verified: `sudo journalctl -u signal-recorder -f`
- [ ] Data files being created: `ls /var/lib/signal-recorder/data/`
- [ ] Restart behavior tested
- [ ] Boot behavior tested (reboot system)
- [ ] Monitoring/alerts configured

---

## Summary

**To answer your question directly:**

✅ **YES - Will restart if daemon stops** (with `Restart=always`)  
✅ **YES - Will start on power cycle** (after `systemctl enable`)  

The updated service file now uses `Restart=always` which ensures the recorder restarts automatically under ANY exit condition (crash, error, kill, etc.) except manual `systemctl stop`.

**Commands to install:**
```bash
sudo cp systemd/signal-recorder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signal-recorder
sudo systemctl start signal-recorder
```

**To verify:**
```bash
# Check it's running
sudo systemctl status signal-recorder

# Test restart
sudo systemctl kill signal-recorder
sleep 35
sudo systemctl status signal-recorder  # Should be running again!

# Test boot behavior
sudo reboot
# After boot:
sudo systemctl status signal-recorder  # Should be running
```
