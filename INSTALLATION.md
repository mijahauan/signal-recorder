# GRAPE Signal Recorder - Installation Guide

Complete setup guide for installing and configuring the GRAPE signal recorder.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Setup](#system-setup)
3. [ka9q-radio Installation](#ka9q-radio-installation)
4. [GRAPE Recorder Installation](#grape-recorder-installation)
5. [Web UI Setup](#web-ui-setup)
6. [Configuration](#configuration)
7. [First Run & Testing](#first-run--testing)
8. [Production Deployment](#production-deployment)
9. [PSWS Upload Setup](#psws-upload-setup)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Hardware Requirements
- **Receiver**: SDR supported by ka9q-radio
  - Recommended: RX888 MkII, Airspy HF+, SDRplay RSPdx
  - Minimum: Any RTL-SDR (reduced performance)
- **Antenna**: HF antenna covering 2.5-25 MHz
  - Dipole, long wire, or active antenna
- **Computer**: 
  - Linux system (Ubuntu 20.04+ recommended)
  - 2+ GB RAM
  - 10+ GB disk space for data archive
  - Gigabit Ethernet (for multicast)

### Software Requirements
- **Operating System**: Linux (Ubuntu 20.04, 22.04, or Debian 11+)
- **Python**: 3.8 or newer
- **Node.js**: 16 or newer (for web UI)
- **Git**: For cloning repository
- **SSH**: For PSWS uploads

---

## System Setup

### 1. Update System

```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Install Build Dependencies

```bash
sudo apt install -y \
    build-essential \
    git \
    cmake \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    libhdf5-dev \
    libfftw3-dev \
    libblas-dev \
    liblapack-dev \
    gfortran \
    rsync \
    openssh-client
```

### 3. Install Node.js (for Web UI)

```bash
# Using NodeSource repository
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Verify
node --version  # Should be 18.x or newer
npm --version
```

### 4. Install pnpm (optional but recommended)

```bash
npm install -g pnpm
```

### 5. Configure Multicast Networking

**Check multicast support:**
```bash
ip mroute show
# Should show kernel multicast routes
```

**If needed, enable multicast:**
```bash
# Add to /etc/sysctl.conf
echo "net.ipv4.conf.all.mc_forwarding=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

**Configure firewall:**
```bash
sudo ufw allow 5004/udp   # RTP packets
sudo ufw allow 3000/tcp   # Web UI
```

---

## ka9q-radio Installation

### 1. Install Dependencies

```bash
sudo apt install -y \
    libavahi-client-dev \
    libavahi-common-dev \
    libopus-dev \
    libportaudio2 \
    portaudio19-dev \
    libncurses-dev \
    libfftw3-dev \
    libiniparser-dev
```

### 2. Clone and Build

```bash
cd ~
git clone https://github.com/ka9q/ka9q-radio.git
cd ka9q-radio
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install
```

### 3. Verify Installation

```bash
which radiod
which control
which monitor
# All should return paths
```

### 4. Configure radiod

Create `/etc/radio/radiod@rx888.conf`:

```ini
[global]
hardware = rx888
description = GRAPE RX888 Station
status = 239.192.152.141  # Multicast address for status
data = 239.160.155.125    # Multicast address for data

[rx888]
device = 0
samprate = 64800000
antenna = HF
gain = 0

# Let GRAPE recorder create channels dynamically
```

### 5. Start radiod

```bash
# Test run
sudo radiod -c /etc/radio/radiod@rx888.conf

# Check status
control -v 239.192.152.141

# Set up as systemd service (recommended)
sudo systemctl enable radiod@rx888
sudo systemctl start radiod@rx888
```

---

## GRAPE Recorder Installation

### 1. Clone Repository

```bash
cd ~
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder
```

### 2. Create Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -e .
```

This installs:
- `digital_rf>=3.0.0` - Digital RF format support
- `scipy>=1.7.0` - Signal processing (decimation)
- `numpy>=1.20.0` - Array operations
- `toml>=0.10.0` - Configuration parsing

### 4. Verify Installation

```bash
signal-recorder --help
# Should show CLI help

python3 -c "import digital_rf; print('Digital RF OK')"
python3 -c "import scipy.signal; print('scipy OK')"
```

### 5. Create Data Directories

```bash
sudo mkdir -p /var/lib/signal-recorder/{archive,upload_queue}
sudo chown -R $USER:$USER /var/lib/signal-recorder
```

---

## Web UI Setup

### 1. Install Node Dependencies

```bash
cd ~/signal-recorder/web-ui
pnpm install  # or: npm install
```

### 2. Create Data Directory

```bash
mkdir -p data
```

### 3. Test Web Server

```bash
pnpm start  # or: npm start
# Should show: "Server running on http://localhost:3000"
```

### 4. Access Web Interface

Open browser: `http://localhost:3000`
- **Username**: `admin`
- **Password**: `admin`

**⚠️ Change default password in production!**

---

## Configuration

### Using Web UI (Recommended)

1. **Navigate to Configuration Tab**
2. **Fill in Station Information:**
   - Callsign (e.g., AC0G)
   - Grid square (e.g., EM38ww)
   - Instrument ID (e.g., RX888)
   - Description

3. **Add Channels:**
   - Click "Add WWV 2.5M", "Add WWV 10M", etc. for presets
   - Or manually add custom channels

4. **Configure PSWS Upload** (optional for now):
   - Remote host: `pswsnetwork.eng.ua.edu`
   - Remote user: (your PSWS username)
   - Remote path: `/var/psws/archive/data/GRAPE/<CALLSIGN>`
   - SSH key path: `~/.ssh/psws_key`

5. **Save Configuration:**
   - Click "Save Configuration"
   - File saved to: `config/grape-<callsign>.toml`

### Manual Configuration (Advanced)

Create `config/grape-<callsign>.toml`:

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
instrument_id = "RX888"
description = "GRAPE station with RX888 MkII"

[ka9q]
status_address = "239.192.152.141"

[recorder]
archive_dir = "/var/lib/signal-recorder/archive"
recording_interval = 60

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
preset = "iq"
sample_rate = 16000
description = "WWV 2.5 MHz"
enabled = true

[[recorder.channels]]
ssrc = 10000000
frequency_hz = 10000000
preset = "iq"
sample_rate = 16000
description = "WWV 10 MHz"
enabled = true

[uploader]
enabled = false  # Enable after PSWS setup
protocol = "rsync"
remote_host = "pswsnetwork.eng.ua.edu"
remote_user = "user_ac0g"
remote_path = "/var/psws/archive/data/GRAPE/AC0G"
ssh_key_path = "~/.ssh/psws_key"
upload_interval = 300

[logging]
level = "INFO"
console_output = true
```

---

## First Run & Testing

### 1. Verify radiod is Running

```bash
control -v 239.192.152.141
# Should show: "0 channels; choose SSRC, create new SSRC, or hit return"
```

### 2. Create Channels

```bash
cd ~/signal-recorder
source venv/bin/activate
signal-recorder create-channels --config config/grape-<callsign>.toml
```

**Verify channels created:**
```bash
control -v 239.192.152.141
# Should now list your WWV/CHU channels
```

### 3. Test Recording (5 minutes)

```bash
signal-recorder daemon --config config/grape-<callsign>.toml
```

**Watch for:**
- "Starting RTP→Digital RF recorder for X channels"
- Periodic status updates showing:
  - Completeness: ~99%
  - Packet loss: <1%
  - Samples received

**Press Ctrl+C to stop after 5 minutes.**

### 4. Verify Output Files

```bash
ls -lh /var/lib/signal-recorder/archive/
# Should show directories: WWV-2.5/, WWV-10.0/, etc.

ls -lh /var/lib/signal-recorder/archive/WWV-10.0/
# Should show rf@*.h5 files and metadata/ directory
```

### 5. Check Data Quality

```bash
# View stats file
cat /tmp/signal-recorder-stats.json | python3 -m json.tool

# Check logs
tail -50 /tmp/signal-recorder-daemon.log
```

**Look for:**
- `"completeness_pct": 99.x`
- `"packet_loss_pct": 0.x`
- `"timing_drift_mean_ms": -X.X` (should be < ±50ms)

---

## Production Deployment

### 1. Create systemd Service

Create `/etc/systemd/system/signal-recorder.service`:

```ini
[Unit]
Description=GRAPE Signal Recorder Daemon
After=network-online.target radiod@rx888.service
Requires=radiod@rx888.service

[Service]
Type=simple
User=YOUR_USERNAME
Group=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/signal-recorder
ExecStart=/home/YOUR_USERNAME/signal-recorder/venv/bin/signal-recorder daemon --config /home/YOUR_USERNAME/signal-recorder/config/grape-YOUR_CALLSIGN.toml
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Replace:**
- `YOUR_USERNAME` with your Linux username
- `YOUR_CALLSIGN` with your actual callsign

### 2. Create Web UI Service

Create `/etc/systemd/system/signal-recorder-webui.service`:

```ini
[Unit]
Description=GRAPE Signal Recorder Web UI
After=network-online.target

[Service]
Type=simple
User=YOUR_USERNAME
Group=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/signal-recorder/web-ui
ExecStart=/usr/bin/pnpm start
Restart=always
RestartSec=10
Environment="NODE_ENV=production"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 3. Enable and Start Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable signal-recorder
sudo systemctl enable signal-recorder-webui
sudo systemctl start signal-recorder
sudo systemctl start signal-recorder-webui
```

### 4. Check Service Status

```bash
sudo systemctl status signal-recorder
sudo systemctl status signal-recorder-webui

# View logs
sudo journalctl -u signal-recorder -f
sudo journalctl -u signal-recorder-webui -f
```

### 5. Set Up Log Rotation

Create `/etc/logrotate.d/signal-recorder`:

```
/tmp/signal-recorder-daemon.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}

/tmp/signal-recorder-upload.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
```

---

## PSWS Upload Setup

### 1. Request PSWS Account

Email HamSCI GRAPE coordinators via [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io):

```
Subject: PSWS Account Request - <YOUR_CALLSIGN>

I'd like to contribute GRAPE timing data from my station:

Callsign: <YOUR_CALLSIGN>
Grid Square: <YOUR_GRID>
Instrument: <RX888/Airspy/etc>
Location: <City, State/Country>

I have the GRAPE recorder installed and collecting data.
Please provide PSWS credentials for rsync uploads.
```

### 2. Generate SSH Key

```bash
ssh-keygen -t ed25519 -f ~/.ssh/psws_key -C "grape-<callsign>"
# No passphrase (for unattended uploads)
```

### 3. Send Public Key to PSWS

```bash
cat ~/.ssh/psws_key.pub
# Copy output and send to PSWS admin
```

### 4. Test SSH Access

```bash
ssh -i ~/.ssh/psws_key user_<callsign>@pswsnetwork.eng.ua.edu
# Should connect without password
```

### 5. Enable Uploads in Config

Edit `config/grape-<callsign>.toml`:

```toml
[uploader]
enabled = true  # Change from false
protocol = "rsync"
remote_host = "pswsnetwork.eng.ua.edu"
remote_user = "user_<callsign>"
remote_path = "/var/psws/archive/data/GRAPE/<CALLSIGN>"
ssh_key_path = "~/.ssh/psws_key"
upload_interval = 300  # 5 minutes
```

### 6. Restart Daemon

```bash
sudo systemctl restart signal-recorder
```

### 7. Monitor Uploads

```bash
# Check upload logs
tail -f /tmp/signal-recorder-upload.log

# Or use web UI monitoring tab
http://localhost:3000/monitoring
```

---

## Troubleshooting

### No Channels Discovered

**Symptom**: `control -v` shows "0 channels"

**Solutions:**
```bash
# 1. Check radiod is running
sudo systemctl status radiod@rx888

# 2. Verify multicast address
grep "status =" /etc/radio/radiod@rx888.conf

# 3. Test multicast connectivity
ping 239.192.152.141
# Should get "Destination Host Unreachable" (that's OK - multicast doesn't respond to ping)

# 4. Check network interface supports multicast
ip link show
# Look for "MULTICAST" flag

# 5. Manually create one channel to test
control 239.192.152.141 <<EOF
10000000
0
iq
16000
0
0
EOF

# Verify
control -v 239.192.152.141
```

### RTP Packets Not Received

**Symptom**: Recorder starts but shows 0% completeness

**Solutions:**
```bash
# 1. Verify channels exist
control -v 239.192.152.141

# 2. Check RTP multicast address
# Should match radiod config "data =" setting

# 3. Test RTP reception with tcpdump
sudo tcpdump -i any -n udp port 5004
# Should show RTP packets

# 4. Check firewall
sudo ufw status
sudo ufw allow 5004/udp

# 5. Verify SSRC in config matches radiod
control -v 239.192.152.141
# Compare SSRCs to config file
```

### Low Completeness (<95%)

**Symptom**: Recorder shows <95% completeness

**Causes & Solutions:**

**Network congestion:**
```bash
# Check dropped packets
ifconfig
# Look for "RX dropped" count

# Increase buffer size
sudo sysctl -w net.core.rmem_max=26214400
sudo sysctl -w net.core.rmem_default=26214400
```

**CPU overload:**
```bash
# Check CPU usage
top
# signal-recorder should use <50% per channel

# Reduce number of channels if needed
```

**Multicast routing:**
```bash
# Ensure multicast routes exist
ip mroute show

# Add route if missing
sudo route add -net 239.0.0.0 netmask 255.0.0.0 dev eth0
```

### Timing Drift High (>50ms)

**Symptom**: Dashboard shows timing drift > ±50ms

**Solutions:**
```bash
# 1. Verify NTP is running
timedatectl
# Should show "System clock synchronized: yes"

# 2. Enable NTP if needed
sudo systemctl enable systemd-timesyncd
sudo systemctl start systemd-timesyncd

# 3. Check NTP sync quality
ntpq -p  # If using ntpd
timedatectl timesync-status  # If using systemd-timesyncd

# 4. Wait for NTP to stabilize
# Timing drift should improve after 10-15 minutes
```

### PSWS Upload Fails

**Symptom**: Upload logs show errors

**Solutions:**
```bash
# 1. Test SSH key
ssh -i ~/.ssh/psws_key user_<callsign>@pswsnetwork.eng.ua.edu

# 2. Check SSH key permissions
chmod 600 ~/.ssh/psws_key

# 3. Verify remote path exists
ssh -i ~/.ssh/psws_key user_<callsign>@pswsnetwork.eng.ua.edu \
    "ls -ld /var/psws/archive/data/GRAPE/<CALLSIGN>"

# 4. Test manual rsync
rsync -avz --dry-run \
    -e "ssh -i ~/.ssh/psws_key" \
    /var/lib/signal-recorder/archive/WWV-10.0/ \
    user_<callsign>@pswsnetwork.eng.ua.edu:/var/psws/archive/data/GRAPE/<CALLSIGN>/WWV-10.0/
```

### Web UI Won't Start

**Symptom**: `pnpm start` fails

**Solutions:**
```bash
# 1. Check Node.js version
node --version  # Should be 16+

# 2. Reinstall dependencies
cd ~/signal-recorder/web-ui
rm -rf node_modules
pnpm install

# 3. Check port 3000 availability
sudo netstat -tlnp | grep 3000

# 4. Try different port
PORT=3001 pnpm start
```

---

## Next Steps

After successful installation:

1. **✅ Monitor for 24 hours** - Verify 🟢 healthy status
2. **✅ Enable PSWS uploads** - After SSH key setup
3. **✅ Set up email alerts** - (optional, see docs/monitoring.md)
4. **✅ Join HamSCI community** - [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io)

---

## Getting Help

### Documentation
- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **Configuration**: [docs/configuration.md](docs/configuration.md)
- **Web UI**: [web-ui/README.md](web-ui/README.md)

### Community Support
- **HamSCI Groups.io**: [grape@hamsci.groups.io](mailto:grape@hamsci.groups.io)
- **GitHub Issues**: Report bugs and request features

### Diagnostic Data to Include

When asking for help, provide:

```bash
# System info
uname -a
python3 --version
node --version

# Service status
sudo systemctl status radiod@rx888
sudo systemctl status signal-recorder

# Recent logs
sudo journalctl -u signal-recorder -n 100 --no-pager

# Configuration (redact passwords!)
cat config/grape-<callsign>.toml

# Stats snapshot
cat /tmp/signal-recorder-stats.json | python3 -m json.tool
```

---

**🎯 Installation complete! Your GRAPE station is now ready to contribute to ionospheric science.**
