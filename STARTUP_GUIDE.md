# GRAPE Signal Recorder - Complete Startup Guide
**For Dual-Service Architecture (Core Recorder + Analytics Service + Web-UI)**

---

## 🎯 Overview

The GRAPE Signal Recorder consists of three independent services:

1. **Core Recorder** - RTP packets → NPZ archives (critical path, rock-solid)
2. **Analytics Service** - NPZ archives → Derived products (tone detection, Digital RF, quality metrics)
3. **Web-UI Monitoring** - Dashboard for system status and data visualization

Each service runs independently and can be started/stopped without affecting the others.

---

## ⚙️ Prerequisites

### 1. Configuration File
```bash
# Verify config file exists
ls -la config/grape-config.toml

# Check mode (test or production)
grep '^mode' config/grape-config.toml
# test mode: Uses /tmp/grape-test (safe for development)
# production mode: Uses /var/lib/signal-recorder (permanent data)
```

### 2. Python Environment
```bash
# Activate your Python environment (if using virtual env)
source venv/bin/activate  # Or your environment path

# Verify Python packages installed
python -c "import numpy, scipy, toml; print('✅ Core packages OK')"
```

### 3. Node.js (for Web-UI)
```bash
# Verify Node.js and dependencies
cd web-ui
node --version  # Should be v14+ or higher
npm list express  # Verify Express installed
cd ..
```

---

## 🚀 Quick Start (All Services)

### Option 1: Manual Start (Recommended for Testing)

```bash
# Terminal 1: Core Recorder
python -m signal_recorder.core_recorder \
  --config config/grape-config.toml

# Terminal 2: Analytics Service  
python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/WWV_5MHz \
  --output-dir /tmp/grape-test/analytics/WWV_5MHz \
  --channel-name "WWV 5.0 MHz" \
  --frequency-hz 5000000 \
  --callsign AC0G \
  --grid-square EM38ww

# Terminal 3: Web-UI Monitoring
cd web-ui
export GRAPE_CONFIG="../config/grape-config.toml"
node monitoring-server.js

# Terminal 4: Monitor logs (optional)
tail -f /tmp/grape-test/logs/core-recorder.log
```

### Option 2: Background Processes

```bash
# Stop any existing instances
pkill -f core_recorder || true
pkill -f analytics_service || true
pkill -f monitoring-server.js || true

# Start Core Recorder
nohup python -m signal_recorder.core_recorder \
  --config config/grape-config.toml \
  > /tmp/grape-test/logs/core-recorder.log 2>&1 &

echo "Core Recorder PID: $!"

sleep 3

# Start Analytics Service (one per channel - example for WWV 5 MHz)
nohup python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/WWV_5MHz \
  --output-dir /tmp/grape-test/analytics/WWV_5MHz \
  --channel-name "WWV 5.0 MHz" \
  --frequency-hz 5000000 \
  --callsign AC0G \
  --grid-square EM38ww \
  > /tmp/grape-test/logs/analytics-wwv5.log 2>&1 &

echo "Analytics Service PID: $!"

sleep 3

# Start Web-UI
cd web-ui
export GRAPE_CONFIG="../config/grape-config.toml"
nohup node monitoring-server.js > monitoring-server.log 2>&1 &
echo "Web-UI PID: $!"
cd ..

# Wait for services to initialize
sleep 5

# Verify all services running
ps aux | grep -E "(core_recorder|analytics_service|monitoring-server)" | grep -v grep
```

---

## 📋 Detailed Startup Instructions

### Step 1: Start Core Recorder

The core recorder receives RTP packets and writes NPZ archives.

```bash
python -m signal_recorder.core_recorder --config config/grape-config.toml
```

**What it does:**
- Listens for RTP packets on multicast addresses
- Resequences packets and detects gaps
- Writes 1-minute NPZ archives to `/tmp/grape-test/archives/`
- Updates status file every 10 seconds: `/tmp/grape-test/status/core-recorder-status.json`

**Expected output:**
```
2024-11-10 18:06:00 - INFO - Starting GRAPE Core Recorder
2024-11-10 18:06:00 - INFO - Responsibility: RTP → NPZ archives (no analytics)
2024-11-10 18:06:00 - INFO - CoreRecorder initialized: 9 channels
2024-11-10 18:06:00 - INFO - RTPReceiver listening on 239.1.2.55:5004
2024-11-10 18:06:00 - INFO - Core recorder running. Press Ctrl+C to stop.
```

**Verify status:**
```bash
# Check status file (should update every 10 seconds)
watch -n 2 "cat /tmp/grape-test/status/core-recorder-status.json | jq '.overall'"

# Check NPZ files being written
ls -lh /tmp/grape-test/archives/*/

# Monitor packet reception
tail -f /tmp/grape-test/logs/core-recorder.log | grep "packets"
```

---

### Step 2: Start Analytics Service

The analytics service processes NPZ archives into derived products. **Start one instance per channel.**

#### Example: WWV 5 MHz Channel

```bash
python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/WWV_5MHz \
  --output-dir /tmp/grape-test/analytics/WWV_5MHz \
  --channel-name "WWV 5.0 MHz" \
  --frequency-hz 5000000 \
  --state-file /tmp/grape-test/state/analytics-wwv5.json \
  --poll-interval 10.0 \
  --log-level INFO \
  --callsign AC0G \
  --grid-square EM38ww \
  --receiver-name "GRAPE" \
  --psws-station-id S000171 \
  --psws-instrument-id 172
```

**Command line arguments:**

| Argument | Description | Example |
|----------|-------------|---------|
| `--archive-dir` | NPZ archive directory (from core recorder) | `/tmp/grape-test/archives/WWV_5MHz` |
| `--output-dir` | Output directory for derived products | `/tmp/grape-test/analytics/WWV_5MHz` |
| `--channel-name` | Channel identifier (for tone detector) | `"WWV 5.0 MHz"` |
| `--frequency-hz` | Center frequency in Hz | `5000000` |
| `--state-file` | State persistence file (optional) | `/tmp/grape-test/state/analytics-wwv5.json` |
| `--poll-interval` | Directory scan interval (seconds) | `10.0` |
| `--log-level` | Log level | `INFO`, `DEBUG` |
| `--callsign` | Station callsign (for Digital RF metadata) | `AC0G` |
| `--grid-square` | Maidenhead grid square | `EM38ww` |
| `--receiver-name` | Receiver name | `GRAPE` |
| `--psws-station-id` | PSWS station ID | `S000171` |
| `--psws-instrument-id` | PSWS instrument number | `172` |

**What it does:**
- Scans archive directory for new NPZ files every 10 seconds
- Processes each NPZ file through:
  - Quality metrics calculation
  - WWV/WWVH/CHU tone detection (if applicable)
  - Time_snap establishment/update
  - Decimation (16 kHz → 10 Hz)
  - Digital RF HDF5 output
  - Quality CSV export
  - Discontinuity logging
- Updates status file every 10 seconds: `/tmp/grape-test/status/analytics-service-status.json`

**Expected output:**
```
2024-11-10 18:06:30 - INFO - AnalyticsService initialized for WWV 5.0 MHz
2024-11-10 18:06:30 - INFO - Archive dir: /tmp/grape-test/archives/WWV_5MHz
2024-11-10 18:06:30 - INFO - Output dir: /tmp/grape-test/analytics/WWV_5MHz
2024-11-10 18:06:30 - INFO - Files processed: 0
2024-11-10 18:06:30 - INFO - Time snap established: False
2024-11-10 18:06:30 - INFO - Analytics service started
2024-11-10 18:07:00 - INFO - Discovered 1 new NPZ files
2024-11-10 18:07:01 - INFO - Processed: WWV_5MHz_20241110_180700.npz (completeness=99.8%, detections=1)
```

**Verify status:**
```bash
# Check status file
cat /tmp/grape-test/status/analytics-service-status.json | jq '.channels'

# Check time_snap establishment
cat /tmp/grape-test/status/analytics-service-status.json | jq '.channels[].time_snap'

# Check tone detections
cat /tmp/grape-test/status/analytics-service-status.json | jq '.channels[].tone_detections'

# Check Digital RF output
ls -lh /tmp/grape-test/analytics/WWV_5MHz/digital_rf/

# Monitor processing
tail -f /tmp/grape-test/logs/analytics-wwv5.log | grep "Processed"
```

---

#### Start Analytics for All 9 Channels

For a complete system, you need **9 analytics service instances** (one per channel):

```bash
# WWV Channels (6)
for freq in 2.5 5 10 15 20 25; do
  nohup python -m signal_recorder.analytics_service \
    --archive-dir /tmp/grape-test/archives/WWV_${freq}MHz \
    --output-dir /tmp/grape-test/analytics/WWV_${freq}MHz \
    --channel-name "WWV ${freq} MHz" \
    --frequency-hz ${freq}000000 \
    --state-file /tmp/grape-test/state/analytics-wwv${freq}.json \
    --callsign AC0G --grid-square EM38ww \
    > /tmp/grape-test/logs/analytics-wwv${freq}.log 2>&1 &
  sleep 1
done

# CHU Channels (3)
nohup python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/CHU_3.33MHz \
  --output-dir /tmp/grape-test/analytics/CHU_3.33MHz \
  --channel-name "CHU 3.33 MHz" \
  --frequency-hz 3330000 \
  --state-file /tmp/grape-test/state/analytics-chu3.json \
  --callsign AC0G --grid-square EM38ww \
  > /tmp/grape-test/logs/analytics-chu3.log 2>&1 &

nohup python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/CHU_7.85MHz \
  --output-dir /tmp/grape-test/analytics/CHU_7.85MHz \
  --channel-name "CHU 7.85 MHz" \
  --frequency-hz 7850000 \
  --state-file /tmp/grape-test/state/analytics-chu7.json \
  --callsign AC0G --grid-square EM38ww \
  > /tmp/grape-test/logs/analytics-chu7.log 2>&1 &

nohup python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/CHU_14.67MHz \
  --output-dir /tmp/grape-test/analytics/CHU_14.67MHz \
  --channel-name "CHU 14.67 MHz" \
  --frequency-hz 14670000 \
  --state-file /tmp/grape-test/state/analytics-chu14.json \
  --callsign AC0G --grid-square EM38ww \
  > /tmp/grape-test/logs/analytics-chu14.log 2>&1 &

# Verify all started
ps aux | grep analytics_service | grep -v grep | wc -l
# Should show: 9
```

---

### Step 3: Start Web-UI Monitoring Server

The web-ui provides a dashboard for monitoring system status.

```bash
cd web-ui

# Set config file path (monitoring server will read data_root from it)
export GRAPE_CONFIG="../config/grape-config.toml"

# Start monitoring server
node monitoring-server.js
```

**What it does:**
- Reads configuration from `grape-config.toml`
- Serves dashboard at http://localhost:3000
- Provides API endpoints:
  - `/api/v1/system/status` - Aggregated system status
  - `/api/v1/system/health` - System health check
  - `/api/v1/errors` - Recent error logs
- Reads status files from both core recorder and analytics service
- Updates dashboard every 5-10 seconds

**Expected output:**
```
🚀 Starting GRAPE Monitoring Server
📋 Configuration:
   Config: ../config/grape-config.toml
   Mode: TEST
   Data root: /tmp/grape-test
   Port: 3000

✅ Server started successfully!

📊 Dashboard: http://localhost:3000/
📊 API: http://localhost:3000/api/v1/system/status

Press Ctrl+C to stop
```

**Verify status:**
```bash
# Test API endpoint
curl http://localhost:3000/api/v1/system/status | jq

# Open dashboard in browser
xdg-open http://localhost:3000  # Linux
# or
open http://localhost:3000      # macOS
```

---

## 🔍 Verification Checklist

After starting all services, verify everything is working:

### 1. Core Recorder Status
```bash
# Status file exists and updates
ls -lh /tmp/grape-test/status/core-recorder-status.json

# Recent update (within last 10 seconds)
stat /tmp/grape-test/status/core-recorder-status.json

# Check JSON content
cat /tmp/grape-test/status/core-recorder-status.json | jq '.overall'

# Expected output:
# {
#   "channels_active": 9,
#   "channels_total": 9,
#   "total_npz_written": 156,
#   "total_packets_received": 468000,
#   "total_gaps_detected": 0
# }
```

### 2. Analytics Service Status
```bash
# Status file exists
ls -lh /tmp/grape-test/status/analytics-service-status.json

# Check time_snap establishment
cat /tmp/grape-test/status/analytics-service-status.json | jq '.channels[].time_snap.established'
# Should show: true (after a few minutes)

# Check processing progress
cat /tmp/grape-test/status/analytics-service-status.json | jq '.overall'

# Expected output:
# {
#   "channels_processing": 1,
#   "total_npz_processed": 156,
#   "pending_npz_files": 0
# }
```

### 3. Web-UI Status
```bash
# Test API endpoint
curl -s http://localhost:3000/api/v1/system/status | jq '.services'

# Should return aggregated status from both core and analytics
```

### 4. Data Flow Verification
```bash
# 1. Check NPZ archives being written (Core Recorder output)
ls -lh /tmp/grape-test/archives/WWV_5MHz/ | tail -5

# 2. Check Digital RF output (Analytics Service output)
ls -lh /tmp/grape-test/analytics/WWV_5MHz/digital_rf/

# 3. Check quality CSVs (Analytics Service output)
ls -lh /tmp/grape-test/analytics/WWV_5MHz/quality/

# 4. Check discontinuity logs
ls -lh /tmp/grape-test/analytics/WWV_5MHz/logs/
```

---

## 🛑 Stopping Services

### Stop All Services
```bash
# Core recorder
pkill -f core_recorder

# Analytics services (all instances)
pkill -f analytics_service

# Web-UI
pkill -f monitoring-server.js

# Verify all stopped
ps aux | grep -E "(core_recorder|analytics_service|monitoring-server)" | grep -v grep
# Should return empty
```

### Stop Individual Services
```bash
# Core recorder only
pkill -f "signal_recorder.core_recorder"

# Specific analytics instance (e.g., WWV 5 MHz)
pkill -f "WWV 5.0 MHz"

# Web-UI only
pkill -f monitoring-server.js
```

### Graceful Shutdown (Recommended)
```bash
# Send SIGTERM (allows cleanup)
pkill -TERM -f core_recorder
pkill -TERM -f analytics_service
pkill -TERM -f monitoring-server.js

# Wait for graceful shutdown
sleep 5

# Force kill if still running
pkill -KILL -f core_recorder
pkill -KILL -f analytics_service
pkill -KILL -f monitoring-server.js
```

---

## 📊 Monitoring & Logs

### Real-Time Monitoring
```bash
# Watch core recorder status (updates every 2 seconds)
watch -n 2 'cat /tmp/grape-test/status/core-recorder-status.json | jq ".overall"'

# Watch analytics service status
watch -n 2 'cat /tmp/grape-test/status/analytics-service-status.json | jq ".overall"'

# Monitor all logs simultaneously
tail -f /tmp/grape-test/logs/*.log

# Monitor NPZ file creation
watch -n 5 'ls -lh /tmp/grape-test/archives/WWV_5MHz/ | tail -10'
```

### Log Files
```bash
# Core recorder log
tail -f /tmp/grape-test/logs/core-recorder.log

# Analytics service logs (per channel)
tail -f /tmp/grape-test/logs/analytics-wwv5.log

# Web-UI log
tail -f web-ui/monitoring-server.log

# Search for errors across all logs
grep -i error /tmp/grape-test/logs/*.log
```

---

## 🐛 Troubleshooting

### Core Recorder Not Receiving Packets

**Symptoms:**
- `packets_received: 0` in status file
- No NPZ files created

**Solutions:**
```bash
# 1. Check KA9Q radiod is running and multicasting
ping bee1-hf-status.local

# 2. Check multicast route
ip route show | grep 239

# 3. Check firewall rules
sudo iptables -L | grep 5004

# 4. Test multicast reception manually
socat UDP-RECV:5004,ip-add-membership=239.1.2.55:0.0.0.0 -
```

### Analytics Service Not Processing Files

**Symptoms:**
- `npz_files_processed: 0` in status file
- `pending_npz_files` not decreasing

**Solutions:**
```bash
# 1. Check archive directory exists
ls -la /tmp/grape-test/archives/WWV_5MHz/

# 2. Check NPZ files present
ls -lh /tmp/grape-test/archives/WWV_5MHz/*.npz

# 3. Check file permissions
ls -l /tmp/grape-test/archives/WWV_5MHz/*.npz

# 4. Check analytics service log for errors
grep -i error /tmp/grape-test/logs/analytics-wwv5.log
```

### Web-UI Not Showing Status

**Symptoms:**
- Dashboard shows "Service offline"
- API returns errors

**Solutions:**
```bash
# 1. Check status files exist
ls -la /tmp/grape-test/status/*.json

# 2. Check status file age (should be < 30 seconds)
stat /tmp/grape-test/status/core-recorder-status.json

# 3. Check web-ui log for errors
tail -f web-ui/monitoring-server.log

# 4. Test API endpoint directly
curl http://localhost:3000/api/v1/system/status
```

### Time_snap Not Establishing

**Symptoms:**
- `time_snap.established: false` after several minutes
- Digital RF files not created

**Solutions:**
```bash
# 1. Check signal strength (need strong WWV/CHU signal)
# View quality metrics
cat /tmp/grape-test/analytics/WWV_5MHz/quality/*.csv | tail -20

# 2. Check tone detection in logs
grep -i "tone detected" /tmp/grape-test/logs/analytics-wwv5.log

# 3. Verify correct channel for time_snap
# Only WWV and CHU channels establish time_snap

# 4. Wait for :00 second of each minute
# WWV/CHU tones occur at minute boundary
```

---

## 🎓 Understanding the Architecture

### Data Flow
```
KA9Q radiod (multicast RTP)
    ↓
Core Recorder (RTP → NPZ)
    ├─ /tmp/grape-test/archives/WWV_5MHz/*.npz
    └─ /tmp/grape-test/status/core-recorder-status.json
        ↓
Analytics Service (NPZ → Derived Products)
    ├─ Digital RF: /tmp/grape-test/analytics/WWV_5MHz/digital_rf/
    ├─ Quality: /tmp/grape-test/analytics/WWV_5MHz/quality/*.csv
    ├─ Logs: /tmp/grape-test/analytics/WWV_5MHz/logs/*.log
    └─ Status: /tmp/grape-test/status/analytics-service-status.json
        ↓
Web-UI (Monitoring & Visualization)
    └─ Dashboard: http://localhost:3000
```

### Service Independence

**Core Recorder:**
- **Critical path** - must never crash
- Minimal dependencies (numpy, scipy)
- No analytics or processing
- Just: RTP → Resequence → Gap fill → NPZ write

**Analytics Service:**
- Can crash and restart without data loss
- Reprocesses from NPZ archives
- Can update algorithms and reprocess historical data
- Each channel is independent

**Web-UI:**
- Pure monitoring - doesn't affect data collection
- Can be stopped/started anytime
- Aggregates status from both services

---

## 📈 Next Steps

After starting the system:

1. **Verify Data Collection** (first 5 minutes)
   - Check NPZ files being created
   - Verify packet reception
   - Check for gaps

2. **Wait for Time_snap** (first 10-60 minutes)
   - Requires strong WWV/CHU signal at minute boundary
   - Check analytics service logs for tone detection
   - Digital RF output starts after time_snap established

3. **Monitor Quality** (ongoing)
   - Watch completeness percentage
   - Track packet loss
   - Monitor gap frequency

4. **Optimize** (after 24 hours)
   - Analyze quality trends
   - Adjust antenna/receiver if needed
   - Fine-tune detector thresholds

---

## 🚀 Production Deployment

For production use:

1. **Switch to production mode:**
   ```toml
   # config/grape-config.toml
   [recorder]
   mode = "production"
   production_data_root = "/var/lib/signal-recorder"
   ```

2. **Install systemd services:**
   ```bash
   sudo cp systemd/*.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable signal-recorder.service
   sudo systemctl enable signal-recorder-web.service
   sudo systemctl start signal-recorder.service
   sudo systemctl start signal-recorder-web.service
   ```

3. **Setup log rotation:**
   ```bash
   sudo cp config/logrotate/signal-recorder /etc/logrotate.d/
   ```

4. **Enable monitoring:**
   - Setup email alerts for service failures
   - Configure Prometheus/Grafana for metrics
   - Add uptime monitoring

---

**Last Updated:** November 10, 2024  
**Version:** 2.0 (Dual-Service Architecture)
