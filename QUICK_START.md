# GRAPE Signal Recorder - Quick Start

## 🚀 One-Command Startup (Recommended)

```bash
./start-dual-service.sh config/grape-config.toml
```

This starts all three services:
- ✅ Core Recorder (RTP → NPZ)
- ✅ Analytics Service × 9 (one per channel)
- ✅ Web-UI Monitoring (http://localhost:3000)

---

## 📊 Access Dashboard

Open in your browser:
```
http://localhost:3000
```

Or test API:
```bash
curl http://localhost:3000/api/v1/system/status | jq
```

---

## 🔍 Check Status

### Core Recorder
```bash
cat /tmp/grape-test/status/core-recorder-status.json | jq '.overall'
```

### Analytics Service
```bash
cat /tmp/grape-test/status/analytics-service-status.json | jq '.overall'
```

### Watch Status (Live Updates)
```bash
watch -n 2 'cat /tmp/grape-test/status/core-recorder-status.json | jq .overall'
```

---

## 📝 View Logs

### All logs together
```bash
tail -f /tmp/grape-test/logs/*.log
```

### Individual services
```bash
# Core recorder
tail -f /tmp/grape-test/logs/core-recorder.log

# Analytics (WWV 5 MHz)
tail -f /tmp/grape-test/logs/analytics-wwv5.log

# Web-UI
tail -f web-ui/monitoring-server.log
```

---

## 🛑 Stop Services

### Stop all
```bash
pkill -f core_recorder
pkill -f analytics_service
pkill -f monitoring-server.js
```

### Verify stopped
```bash
ps aux | grep -E "(core_recorder|analytics_service|monitoring-server)" | grep -v grep
# Should return empty
```

---

## 📁 Data Locations

```bash
# NPZ archives (core recorder output)
ls -lh /tmp/grape-test/archives/WWV_5MHz/

# Digital RF (analytics output)
ls -lh /tmp/grape-test/analytics/WWV_5MHz/digital_rf/

# Quality metrics (analytics output)
ls -lh /tmp/grape-test/analytics/WWV_5MHz/quality/

# Status files (for web-ui)
ls -lh /tmp/grape-test/status/
```

---

## 🐛 Quick Troubleshooting

### No packets received?
```bash
# Check KA9Q radiod is multicasting
ping bee1-hf-status.local

# Check core recorder log
tail -f /tmp/grape-test/logs/core-recorder.log | grep -i error
```

### Analytics not processing?
```bash
# Check if NPZ files exist
ls -lh /tmp/grape-test/archives/WWV_5MHz/*.npz

# Check analytics log
tail -f /tmp/grape-test/logs/analytics-wwv5.log | grep -i error
```

### Web-UI not showing data?
```bash
# Check status files exist and are recent
ls -la /tmp/grape-test/status/

# Check web-ui log
tail -f web-ui/monitoring-server.log
```

---

## 📖 Full Documentation

- **Complete startup guide:** [STARTUP_GUIDE.md](STARTUP_GUIDE.md)
- **Architecture details:** [WEB_UI_DUAL_SERVICE_INTEGRATION.md](WEB_UI_DUAL_SERVICE_INTEGRATION.md)
- **Status implementation:** [WEB_UI_INTEGRATION_SUMMARY.md](WEB_UI_INTEGRATION_SUMMARY.md)

---

## ⚡ Manual Startup (Alternative)

If you prefer manual control:

### 1. Core Recorder
```bash
python -m signal_recorder.core_recorder --config config/grape-config.toml
```

### 2. Analytics (one per channel - example for WWV 5 MHz)
```bash
python -m signal_recorder.analytics_service \
  --archive-dir /tmp/grape-test/archives/WWV_5MHz \
  --output-dir /tmp/grape-test/analytics/WWV_5MHz \
  --channel-name "WWV 5.0 MHz" \
  --frequency-hz 5000000 \
  --callsign AC0G \
  --grid-square EM38ww
```

### 3. Web-UI
```bash
cd web-ui
export GRAPE_CONFIG="../config/grape-config.toml"
node monitoring-server.js
```

---

**Last Updated:** November 10, 2024
