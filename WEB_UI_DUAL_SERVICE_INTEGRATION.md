# Web UI Integration for Dual-Service Architecture
**Date:** November 9, 2024  
**Purpose:** Adapt web-ui to monitor Core Recorder + Analytics Service

---

## Architecture Overview

### Current Reality: Two Independent Services

```
┌─────────────────────────────────────────────────────────────────┐
│                      GRAPE Signal Recorder                       │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐        ┌──────────────────────────────┐
│   CORE RECORDER          │        │   ANALYTICS SERVICE          │
│   (PID: 1229736)         │───────>│   (Not running yet)          │
│                          │  NPZ   │                              │
│  RTP → Resequence → NPZ  │        │  NPZ → DRF + Metrics + Tones│
│                          │        │                              │
│  Status: ???             │        │  Status: ???                 │
└──────────────────────────┘        └──────────────────────────────┘
         │                                    │
         │                                    │
         └────────────────┬───────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │   WEB UI        │
                 │   Port 3000     │
                 │                 │
                 │ Looking for:    │
                 │ recording-stats │
                 │    .json        │
                 └─────────────────┘
                     ⚠️ NOT FOUND
```

---

## Problem Statement

### Web UI Expectations (from V1 Recorder)
```javascript
// monitoring-server.js looks for:
const possibleStatusFiles = [
  join(dataRoot, 'status', 'recording-stats.json'),
  '/tmp/signal-recorder-stats.json',
  '/var/lib/signal-recorder/status/recording-stats.json'
];
```

### What V1 Recorder Provided
```json
{
  "timestamp": "2024-11-09T...",
  "uptime_seconds": 86400,
  "pid": 12345,
  "recorders": {
    "0x12345678": {
      "channel_name": "WWV 5.0 MHz",
      "total_packets": 1000000,
      "time_snap_established": true,
      "time_snap_source": "wwv_verified",
      "wwv_detections": 120,
      "wwvh_detections": 75,
      "quality_grade": "A"
    }
  }
}
```

### What We Have Now
**Core Recorder:** ✅ Running, writing NPZ  
**Status File:** ❌ None  

**Analytics Service:** ❌ Not deployed yet  
**Status File:** ❌ None  

**Result:** Web UI shows "Recorder not running"

---

## Solution: Dual-Service Status Files

### Design Principle
Each service writes its own status file independently. Web-ui aggregates them.

---

## Phase 1: Add Status Output to Core Recorder

### Status File Format
**Location:** `/tmp/grape-core-test/status/core-recorder-status.json`

```json
{
  "service": "core_recorder",
  "version": "2.0",
  "timestamp": "2024-11-09T20:30:00Z",
  "uptime_seconds": 3600,
  "pid": 1229736,
  
  "channels": {
    "0x12345678": {
      "ssrc": "0x12345678",
      "channel_name": "WWV 5.0 MHz",
      "frequency_hz": 5000000,
      "sample_rate": 16000,
      
      "packets_received": 1000000,
      "packets_expected": 1000100,
      "packet_loss_pct": 0.01,
      
      "npz_files_written": 312,
      "last_npz_file": "/tmp/grape-core-test/data/20241109/WWV_5p0_MHz_minute_20241109_203000.npz",
      "last_npz_time": "2024-11-09T20:30:00Z",
      
      "gaps_detected": 3,
      "total_gap_samples": 4800,
      
      "status": "recording",
      "last_packet_time": "2024-11-09T20:30:15Z"
    }
  },
  
  "overall": {
    "channels_active": 9,
    "channels_total": 9,
    "total_npz_written": 2808,
    "disk_bytes_written": 12345678901
  }
}
```

### Implementation: Add to CoreRecorder

```python
# In src/signal_recorder/core_recorder.py

class CoreRecorder:
    def __init__(self, config: dict):
        # ... existing init ...
        
        # Status tracking
        self.start_time = time.time()
        self.status_file = Path(config['output_dir']) / 'status' / 'core-recorder-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
    def _write_status(self):
        """Write current status to JSON file"""
        status = {
            'service': 'core_recorder',
            'version': '2.0',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': int(time.time() - self.start_time),
            'pid': os.getpid(),
            'channels': {},
            'overall': {
                'channels_active': len([ch for ch in self.channels.values() if ch.is_active()]),
                'channels_total': len(self.channels),
                'total_npz_written': sum(ch.npz_count for ch in self.channels.values()),
            }
        }
        
        for ssrc, processor in self.channels.items():
            status['channels'][hex(ssrc)] = processor.get_status()
        
        with open(self.status_file, 'w') as f:
            json.dump(status, f, indent=2)
    
    def run(self):
        """Main loop with periodic status updates"""
        # ... existing loop ...
        
        # Write status every 10 seconds
        last_status_time = 0
        
        while self.running:
            # ... process RTP packets ...
            
            # Periodic status update
            now = time.time()
            if now - last_status_time > 10:
                self._write_status()
                last_status_time = now
```

---

## Phase 2: Add Status Output to Analytics Service

### Status File Format
**Location:** `/tmp/grape-core-test/status/analytics-service-status.json`

```json
{
  "service": "analytics_service",
  "version": "1.0",
  "timestamp": "2024-11-09T20:30:00Z",
  "uptime_seconds": 3500,
  "pid": 1234567,
  
  "channels": {
    "WWV 5.0 MHz": {
      "channel_name": "WWV 5.0 MHz",
      "frequency_hz": 5000000,
      
      "npz_files_processed": 312,
      "last_processed_file": "WWV_5p0_MHz_minute_20241109_203000.npz",
      "last_processed_time": "2024-11-09T20:30:05Z",
      
      "time_snap": {
        "established": true,
        "source": "wwv_verified",
        "station": "WWV",
        "rtp_timestamp": 123456789,
        "utc_timestamp": 1699561800.0,
        "confidence": 0.95,
        "age_minutes": 2
      },
      
      "tone_detections": {
        "wwv": 120,
        "wwvh": 75,
        "chu": 0,
        "total": 195,
        "last_detection_time": "2024-11-09T20:29:00Z"
      },
      
      "digital_rf": {
        "samples_written": 36000,
        "files_written": 312,
        "last_write_time": "2024-11-09T20:30:05Z",
        "output_dir": "/tmp/grape-core-test/digital_rf"
      },
      
      "quality_metrics": {
        "last_completeness_pct": 99.8,
        "last_quality_grade": "A",
        "avg_packet_loss_pct": 0.1
      }
    }
  },
  
  "overall": {
    "channels_processing": 9,
    "total_npz_processed": 2808,
    "pending_npz_files": 0
  }
}
```

### Implementation: Add to AnalyticsService

```python
# In src/signal_recorder/analytics_service.py

class AnalyticsService:
    def __init__(self, ...):
        # ... existing init ...
        
        # Status tracking
        self.start_time = time.time()
        self.status_file = self.output_dir / 'status' / 'analytics-service-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Per-channel stats
        self.stats = {
            'npz_processed': 0,
            'last_processed': None,
            'detections': {'wwv': 0, 'wwvh': 0, 'chu': 0},
            'drf_samples_written': 0
        }
    
    def _write_status(self):
        """Write current status to JSON file"""
        status = {
            'service': 'analytics_service',
            'version': '1.0',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': int(time.time() - self.start_time),
            'pid': os.getpid(),
            'channels': {
                self.channel_name: {
                    'channel_name': self.channel_name,
                    'frequency_hz': self.frequency_hz,
                    'npz_files_processed': self.state.files_processed,
                    'last_processed_file': str(self.state.last_processed_file) if self.state.last_processed_file else None,
                    'time_snap': self.state.time_snap.to_dict() if self.state.time_snap else None,
                    'tone_detections': {
                        'total': len(self.state.detection_history),
                        'last_detection_time': self.state.detection_history[-1].timestamp_utc if self.state.detection_history else None
                    },
                    'digital_rf': {
                        'samples_written': self.drf_writer.total_samples_written if self.drf_writer else 0,
                        'output_dir': str(self.drf_dir)
                    }
                }
            },
            'overall': {
                'channels_processing': 1,
                'total_npz_processed': self.state.files_processed,
                'pending_npz_files': len(self.discover_new_files())
            }
        }
        
        with open(self.status_file, 'w') as f:
            json.dump(status, f, indent=2)
    
    def run(self, poll_interval: float = 10.0):
        """Main loop with status updates"""
        # ... existing loop ...
        
        last_status_time = 0
        
        while self.running:
            # ... process NPZ files ...
            
            # Write status every 10 seconds
            now = time.time()
            if now - last_status_time > 10:
                self._write_status()
                last_status_time = now
```

---

## Phase 3: Update Monitoring Server to Aggregate Status

### New Helper Functions

```javascript
// monitoring-server.js

/**
 * Read core recorder status
 */
async function getCoreRecorderStatus() {
  const statusFile = join(dataRoot, 'status', 'core-recorder-status.json');
  
  if (!fs.existsSync(statusFile)) {
    return { running: false, service: 'core_recorder' };
  }
  
  try {
    const stats = fs.statSync(statusFile);
    const ageSeconds = (Date.now() - stats.mtimeMs) / 1000;
    
    // Consider running if updated in last 30 seconds
    if (ageSeconds < 30) {
      const data = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
      return { running: true, ...data };
    }
  } catch (error) {
    console.error('Error reading core recorder status:', error);
  }
  
  return { running: false, service: 'core_recorder' };
}

/**
 * Read analytics service status
 */
async function getAnalyticsServiceStatus() {
  const statusFile = join(dataRoot, 'status', 'analytics-service-status.json');
  
  if (!fs.existsSync(statusFile)) {
    return { running: false, service: 'analytics_service' };
  }
  
  try {
    const stats = fs.statSync(statusFile);
    const ageSeconds = (Date.now() - stats.mtimeMs) / 1000;
    
    if (ageSeconds < 30) {
      const data = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
      return { running: true, ...data };
    }
  } catch (error) {
    console.error('Error reading analytics service status:', error);
  }
  
  return { running: false, service: 'analytics_service' };
}
```

### Updated API Endpoint

```javascript
/**
 * GET /api/v1/system/status
 * Comprehensive dual-service status
 */
app.get('/api/v1/system/status', async (req, res) => {
  try {
    const coreStatus = await getCoreRecorderStatus();
    const analyticsStatus = await getAnalyticsServiceStatus();
    const diskUsage = await getDiskUsage(dataRoot);
    
    // Aggregate time_snap from analytics service
    let timeSnapStatus = { established: false };
    if (analyticsStatus.running && analyticsStatus.channels) {
      for (const ch of Object.values(analyticsStatus.channels)) {
        if (ch.time_snap && ch.time_snap.established) {
          timeSnapStatus = {
            established: true,
            source: ch.channel_name,
            station: ch.time_snap.station,
            confidence: ch.time_snap.confidence,
            age_minutes: ch.time_snap.age_minutes
          };
          break;
        }
      }
    }
    
    // Aggregate channel counts
    const coreChannels = coreStatus.running ? coreStatus.overall.channels_total : 0;
    const activeChannels = coreStatus.running ? coreStatus.overall.channels_active : 0;
    
    res.json({
      timestamp: new Date().toISOString(),
      
      services: {
        core_recorder: {
          running: coreStatus.running,
          uptime_seconds: coreStatus.uptime_seconds || 0,
          pid: coreStatus.pid || null,
          channels_active: activeChannels,
          npz_written: coreStatus.running ? coreStatus.overall.total_npz_written : 0
        },
        analytics_service: {
          running: analyticsStatus.running,
          uptime_seconds: analyticsStatus.uptime_seconds || 0,
          pid: analyticsStatus.pid || null,
          npz_processed: analyticsStatus.running ? analyticsStatus.overall.total_npz_processed : 0,
          pending_files: analyticsStatus.running ? analyticsStatus.overall.pending_npz_files : 0
        }
      },
      
      channels: {
        total: coreChannels,
        active: activeChannels
      },
      
      time_snap: timeSnapStatus,
      
      data_paths: {
        archive: join(dataRoot, 'data'),
        analytics: join(dataRoot, 'analytics'),
        digital_rf: join(dataRoot, 'digital_rf')
      },
      
      disk: diskUsage,
      
      station: {
        callsign: config.station?.callsign || 'UNKNOWN',
        grid_square: config.station?.grid_square || 'UNKNOWN',
        mode: mode
      }
    });
    
  } catch (error) {
    console.error('Failed to get system status:', error);
    res.status(500).json({
      error: 'Failed to get system status',
      details: error.message
    });
  }
});
```

---

## Phase 4: Update Dashboard UI

### New Service Status Section

Add to `timing-dashboard.html`:

```html
<div class="services-status">
  <h2>System Services</h2>
  
  <div class="service-card">
    <div class="service-header">
      <span class="service-name">📦 Core Recorder</span>
      <span class="service-status" id="core-status">●</span>
    </div>
    <div class="service-details">
      <span id="core-uptime">Uptime: --</span>
      <span id="core-npz">NPZ Files: --</span>
    </div>
  </div>
  
  <div class="service-card">
    <div class="service-header">
      <span class="service-name">📊 Analytics Service</span>
      <span class="service-status" id="analytics-status">●</span>
    </div>
    <div class="service-details">
      <span id="analytics-uptime">Uptime: --</span>
      <span id="analytics-processed">Processed: --</span>
      <span id="analytics-pending">Pending: --</span>
    </div>
  </div>
</div>

<script>
async function updateServiceStatus() {
  const response = await fetch('/api/v1/system/status');
  const data = await response.json();
  
  // Core Recorder
  const coreStatus = data.services.core_recorder;
  document.getElementById('core-status').className = 
    coreStatus.running ? 'status-online' : 'status-offline';
  document.getElementById('core-uptime').textContent = 
    `Uptime: ${formatUptime(coreStatus.uptime_seconds)}`;
  document.getElementById('core-npz').textContent = 
    `NPZ Files: ${coreStatus.npz_written}`;
  
  // Analytics Service
  const analyticsStatus = data.services.analytics_service;
  document.getElementById('analytics-status').className = 
    analyticsStatus.running ? 'status-online' : 'status-offline';
  document.getElementById('analytics-uptime').textContent = 
    `Uptime: ${formatUptime(analyticsStatus.uptime_seconds)}`;
  document.getElementById('analytics-processed').textContent = 
    `Processed: ${analyticsStatus.npz_processed}`;
  document.getElementById('analytics-pending').textContent = 
    `Pending: ${analyticsStatus.pending_files}`;
}

// Update every 5 seconds
setInterval(updateServiceStatus, 5000);
updateServiceStatus();
</script>
```

---

## Implementation Order

### Step 1: Core Recorder Status (1 hour)
- [ ] Add `_write_status()` method to `CoreRecorder`
- [ ] Add periodic status writes to main loop
- [ ] Test: verify status file appears and updates

### Step 2: Analytics Service Status (1 hour)
- [ ] Add `_write_status()` method to `AnalyticsService`
- [ ] Track detection counts and DRF stats
- [ ] Add periodic status writes to main loop
- [ ] Test: verify status file appears and updates

### Step 3: Monitoring Server Update (2 hours)
- [ ] Add `getCoreRecorderStatus()` helper
- [ ] Add `getAnalyticsServiceStatus()` helper
- [ ] Update `/api/v1/system/status` to aggregate both
- [ ] Test: verify API returns correct data

### Step 4: Dashboard UI Update (2 hours)
- [ ] Add dual-service status section
- [ ] Update JavaScript to fetch and display
- [ ] Add CSS styling for service cards
- [ ] Test: verify UI updates correctly

### Step 5: End-to-End Testing (1 hour)
- [ ] Start core recorder
- [ ] Start analytics service
- [ ] Verify status files written
- [ ] Verify web UI shows both services
- [ ] Verify all metrics updating correctly

---

## Testing Checklist

### Core Recorder
- [ ] Status file written to `/tmp/grape-core-test/status/core-recorder-status.json`
- [ ] File updates every 10 seconds
- [ ] Contains correct channel data
- [ ] NPZ file counts incrementing
- [ ] Packet statistics accurate

### Analytics Service
- [ ] Status file written to `/tmp/grape-core-test/status/analytics-service-status.json`
- [ ] File updates every 10 seconds
- [ ] time_snap status correct
- [ ] Tone detection counts accurate
- [ ] Digital RF stats valid

### Web UI
- [ ] `/api/v1/system/status` returns both services
- [ ] Dashboard shows "Core Recorder: RUNNING"
- [ ] Dashboard shows "Analytics Service: RUNNING"
- [ ] time_snap status displayed correctly
- [ ] Channel counts accurate
- [ ] Disk usage shown

---

## Backward Compatibility

### Legacy Endpoints
Keep these working for existing dashboards:
- `/api/monitoring/station-info` ✅
- `/api/monitoring/timing-quality` ✅ (reads CSV files)
- `/api/monitoring/live-quality` ⚠️ (needs update for dual services)

### Migration Strategy
1. Add new status files (no breaking changes)
2. Update API endpoints to read from both sources
3. Gracefully handle missing services (show as offline)
4. Provide clear indicators in UI for service status

---

## Next Steps After Implementation

1. **Add service health checks**
   - Monitor status file age
   - Alert if either service hasn't updated in 60 seconds
   - Automatic restart via systemd

2. **Add detailed per-channel endpoints**
   - `/api/v1/channels/<channel_id>/status`
   - Core recorder stats + analytics stats combined

3. **Add time-series metrics**
   - Track NPZ write rate over time
   - Track processing lag (core vs analytics)
   - Visualize in dashboard

4. **Add upload monitoring**
   - Integrate uploader status when Phase 2C implemented
   - Show files queued, uploaded, failed

---

## Summary

**Current Problem:**  
Web-ui looks for single V1 recorder status. New architecture has two separate services.

**Solution:**  
Each service writes its own status JSON. Monitoring server aggregates them.

**Benefits:**  
- ✅ Independent service monitoring
- ✅ Clear separation of concerns
- ✅ Easy to debug which service has issues
- ✅ Graceful degradation (one service down = partial UI)
- ✅ Future-proof for additional services

**Estimated Implementation:** 6-7 hours total
