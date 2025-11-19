# Radiod Health Monitoring System

## Overview

Robust multi-layer monitoring system to ensure radiod status is accurately reported in the web UI, eliminating false "STOPPED" alerts.

## Problem Solved

**Previous Issue**: Web UI showed radiod as "STOPPED" even when running because:
1. Core recorder didn't write status file
2. Web UI inferred radiod status from packet counts (which were zero in status)
3. No direct process monitoring

**Solution**: Dedicated health monitor with multiple verification layers and fallbacks.

---

## Architecture

### Three-Layer Monitoring

```
┌─────────────────────────────────────────────────────────┐
│                  Web UI (Browser)                       │
│              Shows radiod health status                 │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP GET /api/v1/system/status
                       ▼
┌─────────────────────────────────────────────────────────┐
│           Web Server (monitoring-server-v3.js)          │
│     Reads: /tmp/grape-test/state/radiod-status.json    │
│     Fallback: Direct pgrep if file missing              │
└──────────────────────┬──────────────────────────────────┘
                       │ Reads status file
                       ▼
┌─────────────────────────────────────────────────────────┐
│      Radiod Health Monitor (monitor_radiod_health.py)   │
│  - Checks radiod process every 10s (pgrep)              │
│  - Verifies multicast connectivity (ss -lun)            │
│  - Calculates uptime from /proc                         │
│  - Writes atomic status updates                         │
└──────────────────────┬──────────────────────────────────┘
                       │ Monitors
                       ▼
┌─────────────────────────────────────────────────────────┐
│              radiod (KA9Q Software Radio)               │
│          RTP multicast streaming to recorder            │
└─────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Health Monitor Script
**File**: `scripts/monitor_radiod_health.py`

**Features**:
- Process detection via `pgrep -x radiod`
- Uptime calculation from `/proc/{pid}/stat`
- Network connectivity check via `ss -lun` (multicast detection)
- Atomic status file writes (temp file + rename)
- Consecutive failure tracking
- Health states: `healthy`, `degraded`, `critical`, `unknown`

**Status File Format**:
```json
{
  "timestamp": "2025-11-18T01:23:38.739634+00:00",
  "process": {
    "running": true,
    "pid": 1466108,
    "count": 1
  },
  "uptime_seconds": 16889,
  "connectivity": true,
  "health": "healthy",
  "alerts": []
}
```

**Alert Levels**:
- `healthy`: Process running with multicast detected
- `degraded`: Process running but no multicast
- `critical`: Process not found
- `unknown`: Cannot determine connectivity status

### 2. Web Server Integration
**File**: `web-ui/monitoring-server-v3.js`

**New Function**: `getRadiodStatus(paths)`
- **Primary**: Reads `/tmp/grape-test/state/radiod-status.json`
- **Fallback 1**: Direct `pgrep -x radiod` if file missing
- **Fallback 2**: Returns error status if all checks fail

**API Response**:
```json
{
  "radiod": {
    "running": true,
    "connected": true,
    "uptime_seconds": 16889,
    "health": "healthy",
    "alerts": [],
    "status_age_seconds": 0,
    "method": "health_monitor"
  }
}
```

### 3. Systemd Service (Optional)
**File**: `systemd/grape-radiod-monitor.service`

**Features**:
- Auto-starts with radiod
- Auto-restarts on failure
- Logs to systemd journal
- User-level service (no root required)

---

## Installation & Usage

### Manual Start (Testing)
```bash
# Start the monitor (foreground)
python3 scripts/monitor_radiod_health.py /tmp/grape-test/state/radiod-status.json 10

# Start in background
./start-radiod-monitor.sh
```

### Systemd Installation (Production)
```bash
# Copy service file
sudo cp systemd/grape-radiod-monitor.service /etc/systemd/system/

# Edit paths if needed
sudo nano /etc/systemd/system/grape-radiod-monitor.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable grape-radiod-monitor.service
sudo systemctl start grape-radiod-monitor.service

# Check status
sudo systemctl status grape-radiod-monitor.service
journalctl -u grape-radiod-monitor.service -f
```

### Verify Operation
```bash
# Check monitor is running
ps aux | grep monitor_radiod_health

# Check status file
cat /tmp/grape-test/state/radiod-status.json | python3 -m json.tool

# Check web API
curl -s http://localhost:3000/api/v1/system/status | python3 -m json.tool | grep -A5 radiod

# Check web UI
# Navigate to: http://localhost:3000/summary.html
# Look for radiod status (should show green "RUNNING")
```

---

## Failure Scenarios & Handling

### Scenario 1: Radiod Stops
**Detection**: Process check fails → `running: false`  
**Response**: 
- Status: `critical`
- Alert: "Radiod process not found (failed N checks)"
- Web UI: Shows red "STOPPED" with alert

### Scenario 2: Radiod Loses Network
**Detection**: Process running but no multicast → `connectivity: false`  
**Response**:
- Status: `degraded`
- Alert: "Radiod running but no multicast detected"
- Web UI: Shows yellow warning

### Scenario 3: Monitor Crashes
**Detection**: Status file age > 30s  
**Response**:
- Web server uses pgrep fallback
- Shows `method: "pgrep_fallback"`
- Systemd restarts monitor (if using service)

### Scenario 4: Status File Deleted
**Detection**: File doesn't exist  
**Response**:
- Web server performs direct pgrep
- Shows `method: "pgrep_fallback"`
- Monitor recreates file on next cycle

---

## Configuration

### Monitor Settings
Edit in `scripts/monitor_radiod_health.py` or pass as arguments:
```python
output_file = '/tmp/grape-test/state/radiod-status.json'  # Status file location
poll_interval = 10  # Check every 10 seconds
```

### Web Server Settings
Status file location in `web-ui/monitoring-server-v3.js`:
```javascript
const radiodStatusFile = join(paths.getStateDir(), 'radiod-status.json');
```

---

## Monitoring Best Practices

### 1. Always Use Dedicated Monitor
Don't rely on inferred status from packet counts. Process monitoring is definitive.

### 2. Watch for Degraded State
If radiod shows `degraded` (running but no multicast), check:
- Network interface configuration
- Firewall rules
- Multicast routing

### 3. Monitor the Monitor
Check status file age. If > 30s old, the monitor may have crashed:
```bash
stat -c %Y /tmp/grape-test/state/radiod-status.json
```

### 4. Log Analysis
Monitor logs to systemd journal:
```bash
journalctl -u grape-radiod-monitor.service -f
```

---

## Troubleshooting

### Monitor Not Starting
```bash
# Check Python path
which python3

# Check script permissions
ls -l scripts/monitor_radiod_health.py

# Run manually to see errors
python3 scripts/monitor_radiod_health.py /tmp/test.json 5
```

### Status Always Shows "STOPPED"
```bash
# Verify radiod is actually running
ps aux | grep radiod
pgrep -x radiod

# Check status file
cat /tmp/grape-test/state/radiod-status.json

# Check web server logs
tail -f /tmp/monitoring-server.log

# Test API directly
curl http://localhost:3000/api/v1/system/status
```

### "Degraded" Health Status
```bash
# Check for multicast traffic
ss -lun | grep 239

# Check radiod configuration
cat /etc/radio/radiod@ac0g-bee1-rx888.conf

# Verify network interface
ip addr show
```

---

## Performance Impact

**CPU Usage**: Minimal (~0.1% per 10s check)  
**Memory**: ~20 MB Python process  
**Disk I/O**: 1 small JSON write every 10s (~500 bytes)  
**Network**: None (local process monitoring only)

**Recommendation**: Safe to run continuously on production systems.

---

## Integration with Existing Systems

### Core Recorder
- **No changes needed** - operates independently
- Core recorder focuses on data capture
- Monitor handles health reporting

### Analytics Service
- **No changes needed** - separate concern
- Analytics processes data
- Monitor reports system health

### Web UI
- **Already integrated** - reads status automatically
- Fallback to pgrep if status unavailable
- Graceful degradation

---

## Future Enhancements

### Potential Additions
1. **Email/SMS Alerts**: Notify on radiod failure
2. **Restart Automation**: Auto-restart radiod if down > threshold
3. **Historical Tracking**: Log uptime history for reliability metrics
4. **Network Quality**: Monitor packet loss, jitter
5. **Disk Space Monitoring**: Alert when storage low
6. **Temperature Monitoring**: Track SDR hardware temperature

### Not Recommended
❌ **Don't** have monitor restart radiod automatically - operator should investigate  
❌ **Don't** poll faster than 5s - unnecessary load  
❌ **Don't** add complex analytics - keep monitor simple and robust  

---

## Files Added

- `scripts/monitor_radiod_health.py` - Health monitor script
- `start-radiod-monitor.sh` - Easy startup script
- `systemd/grape-radiod-monitor.service` - Systemd service unit
- `RADIOD_MONITORING_SYSTEM.md` - This documentation

## Files Modified

- `web-ui/monitoring-server-v3.js`:
  - Added `getRadiodStatus()` function
  - Updated `getProcessStatuses()` to use dedicated radiod status
  - Added pgrep fallback for robustness

---

## Summary

**Problem**: Web UI incorrectly showed radiod as stopped  
**Root Cause**: No direct process monitoring, relied on inferred status  
**Solution**: Dedicated health monitor with multi-layer fallbacks  
**Result**: Accurate, reliable radiod status in web UI  

**Robustness Features**:
- ✅ Direct process monitoring (pgrep)
- ✅ Network connectivity verification
- ✅ Atomic status file updates
- ✅ Multiple fallback layers
- ✅ Systemd auto-restart capability
- ✅ Zero impact on data recording

**Status**: Production-ready, tested with live radiod instance
