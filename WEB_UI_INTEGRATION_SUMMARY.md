# Web UI Integration - Session Summary
**Date:** November 9, 2024  
**Task:** Review web-ui, design APIs for dual-service architecture, implement status endpoints

---

## ✅ Completed This Session

### 1. **Existing Web-UI Review** (30 minutes)

**Current State:**
- ✅ Monitoring server (`monitoring-server.js`) running on port 3000
- ✅ API v1 partially implemented (`/api/v1/system/status`, `/health`, `/errors`)
- ✅ Legacy endpoints maintained for backward compatibility
- ✅ Timing dashboard (`timing-dashboard.html`) with quality visualization
- ⚠️ **Problem:** Web-ui expects single V1 recorder, but we have dual-service architecture

**Key Files Reviewed:**
- `/home/mjh/git/signal-recorder/web-ui/monitoring-server.js` (769 lines)
- `/home/mjh/git/signal-recorder/web-ui/timing-dashboard.html` (650 lines)
- `/home/mjh/git/signal-recorder/web-ui/index.html` (redirects to dashboard)
- `/home/mjh/git/signal-recorder/WEB_UI_API_PROPOSAL.md` (759 lines - previous session)
- `/home/mjh/git/signal-recorder/WEB_UI_SESSION_SUMMARY.md` (386 lines - previous session)

**Findings:**
```javascript
// monitoring-server.js looks for:
const possibleStatusFiles = [
  join(dataRoot, 'status', 'recording-stats.json'),  // V1 recorder format
  '/tmp/signal-recorder-stats.json',
  '/var/lib/signal-recorder/status/recording-stats.json'
];
// ❌ These don't exist for new dual-service architecture!
```

---

### 2. **API Design for Dual-Service Architecture** (1 hour)

**Created:** `/home/mjh/git/signal-recorder/WEB_UI_DUAL_SERVICE_INTEGRATION.md`

**Design Principles:**
- Each service writes its own status JSON file
- Web-ui aggregates status from both sources
- Independent service monitoring (one can be down, other continues)
- Graceful degradation (show partial status if one service unavailable)

**Status File Locations:**
```
/tmp/grape-core-test/status/
├── core-recorder-status.json         # Core recorder (NEW)
└── analytics-service-status.json     # Analytics service (NEW)
```

**Status File Formats:**

**Core Recorder:**
```json
{
  "service": "core_recorder",
  "version": "2.0",
  "timestamp": "2024-11-09T20:30:00Z",
  "uptime_seconds": 3600,
  "pid": 1229736,
  "channels": {
    "0x12345678": {
      "channel_name": "WWV 5.0 MHz",
      "packets_received": 1000000,
      "npz_files_written": 312,
      "gaps_detected": 3,
      "status": "recording"
    }
  },
  "overall": {
    "channels_active": 9,
    "channels_total": 9,
    "total_npz_written": 2808
  }
}
```

**Analytics Service:**
```json
{
  "service": "analytics_service",
  "version": "1.0",
  "timestamp": "2024-11-09T20:30:00Z",
  "uptime_seconds": 3500,
  "pid": 1234567,
  "channels": {
    "WWV 5.0 MHz": {
      "npz_files_processed": 312,
      "time_snap": {
        "established": true,
        "source": "wwv_verified",
        "station": "WWV",
        "confidence": 0.95,
        "age_minutes": 2
      },
      "tone_detections": {
        "wwv": 120,
        "wwvh": 75,
        "total": 195
      },
      "digital_rf": {
        "samples_written": 36000,
        "output_dir": "/tmp/grape-core-test/digital_rf"
      }
    }
  },
  "overall": {
    "total_npz_processed": 2808,
    "pending_npz_files": 0
  }
}
```

---

### 3. **Status Endpoint Implementation** (2 hours)

#### 3.1 Core Recorder Status

**File:** `src/signal_recorder/core_recorder.py`

**Changes:**
- ✅ Added `import os, time, json` and `datetime, timezone`
- ✅ Added `self.start_time` and `self.status_file` tracking
- ✅ Created `_write_status()` method (writes JSON atomically)
- ✅ Modified `run()` loop to write status every 10 seconds
- ✅ Added `get_status()` method to `ChannelProcessor` for detailed stats

**Key Code:**
```python
class CoreRecorder:
    def __init__(self, config: dict):
        # ... existing init ...
        
        # Status tracking
        self.start_time = time.time()
        self.status_file = self.output_dir / 'status' / 'core-recorder-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
    
    def run(self):
        # ... RTP receiver start ...
        
        # Write initial status
        self._write_status()
        
        last_status_time = 0
        while self.running:
            # ... packet processing ...
            
            # Periodic status update (every 10 seconds)
            now = time.time()
            if now - last_status_time >= 10:
                self._write_status()
                last_status_time = now
    
    def _write_status(self):
        """Write current status to JSON file for web-ui monitoring"""
        status = {
            'service': 'core_recorder',
            'version': '2.0',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': int(time.time() - self.start_time),
            'pid': os.getpid(),
            'channels': {},
            'overall': { ... }
        }
        
        # Gather per-channel stats
        for ssrc, processor in self.channels.items():
            status['channels'][hex(ssrc)] = processor.get_status()
        
        # Write atomically (temp file + rename)
        temp_file = self.status_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(status, f, indent=2)
        temp_file.replace(self.status_file)
```

**Status Fields:**
- Service identification (`service`, `version`, `pid`)
- Uptime tracking (`uptime_seconds`, `timestamp`)
- Per-channel stats (packets, NPZ files, gaps)
- Overall aggregates (active channels, total files)

---

#### 3.2 Analytics Service Status

**File:** `src/signal_recorder/analytics_service.py`

**Changes:**
- ✅ Added `import os` for PID tracking
- ✅ Added `self.start_time` and `self.status_file` tracking
- ✅ Added `self.stats` dict for per-channel statistics
- ✅ Created `_write_status()` method (writes JSON atomically)
- ✅ Modified `run()` loop to write status every 10 seconds
- ✅ Updated `process_archive()` to track detection and quality stats
- ✅ Fixed duplicate lines in run() method

**Key Code:**
```python
class AnalyticsService:
    def __init__(self, ...):
        # ... existing init ...
        
        # Status tracking
        self.start_time = time.time()
        self.status_file = self.output_dir / 'status' / 'analytics-service-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Per-channel statistics
        self.stats = {
            'drf_samples_written': 0,
            'wwv_detections': 0,
            'wwvh_detections': 0,
            'chu_detections': 0,
            'last_completeness_pct': 0.0,
            'last_quality_grade': 'UNKNOWN',
            ...
        }
    
    def run(self, poll_interval: float = 10.0):
        logger.info("Analytics service started")
        self.running = True
        
        # Write initial status
        self._write_status()
        
        last_status_time = 0
        while self.running:
            # ... NPZ processing ...
            
            # Write status periodically (every 10 seconds)
            now = time.time()
            if now - last_status_time >= 10:
                self._write_status()
                last_status_time = now
    
    def _write_status(self):
        """Write current status to JSON file for web-ui monitoring"""
        # Calculate time_snap age
        time_snap_dict = None
        if self.state.time_snap:
            age_minutes = int((time.time() - self.state.time_snap.established_at) / 60)
            time_snap_dict = {
                'established': True,
                'station': self.state.time_snap.station,
                'confidence': self.state.time_snap.confidence,
                'age_minutes': age_minutes
            }
        
        status = {
            'service': 'analytics_service',
            'version': '1.0',
            'channels': {
                self.channel_name: {
                    'time_snap': time_snap_dict,
                    'tone_detections': {...},
                    'digital_rf': {...},
                    'quality_metrics': {...}
                }
            }
        }
        
        # Write atomically
        temp_file = self.status_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(status, f, indent=2)
        temp_file.replace(self.status_file)
```

**Statistics Tracked:**
- NPZ processing progress
- time_snap establishment and age
- WWV/WWVH/CHU detection counts
- Digital RF samples written
- Quality metrics (completeness, packet loss, grade)

**Process Archive Updates:**
```python
def process_archive(self, archive: NPZArchive) -> Dict:
    # ... detection processing ...
    
    # Update detection stats
    for det in detections:
        if det.station == StationType.WWV:
            self.stats['wwv_detections'] += 1
        elif det.station == StationType.WWVH:
            self.stats['wwvh_detections'] += 1
        elif det.station == StationType.CHU:
            self.stats['chu_detections'] += 1
    
    # Update DRF stats
    self.stats['drf_samples_written'] += decimated_count
    
    # Update quality stats
    self.stats['last_completeness_pct'] = quality.completeness_pct
    self.stats['last_quality_grade'] = quality.quality_grade
```

---

## 📋 Next Steps (Not Started)

### 4. **Update Monitoring Server** (2 hours) - NOT DONE YET

**File:** `web-ui/monitoring-server.js`

**Tasks:**
```javascript
// Add helper functions:
async function getCoreRecorderStatus() {
  const statusFile = join(dataRoot, 'status', 'core-recorder-status.json');
  // Read and parse, check file age
}

async function getAnalyticsServiceStatus() {
  const statusFile = join(dataRoot, 'status', 'analytics-service-status.json');
  // Read and parse, check file age
}

// Update endpoint:
app.get('/api/v1/system/status', async (req, res) => {
  const coreStatus = await getCoreRecorderStatus();
  const analyticsStatus = await getAnalyticsServiceStatus();
  
  // Aggregate data from both services
  res.json({
    services: {
      core_recorder: { ... },
      analytics_service: { ... }
    },
    time_snap: { ... },  // From analytics service
    channels: { ... },    // From core recorder
    ...
  });
});
```

---

### 5. **Update Dashboard UI** (2 hours) - NOT DONE YET

**File:** `web-ui/timing-dashboard.html`

**Add Service Status Cards:**
```html
<div class="services-status">
  <div class="service-card">
    <span class="service-name">📦 Core Recorder</span>
    <span class="service-status" id="core-status">●</span>
    <span id="core-uptime">Uptime: --</span>
    <span id="core-npz">NPZ Files: --</span>
  </div>
  
  <div class="service-card">
    <span class="service-name">📊 Analytics Service</span>
    <span class="service-status" id="analytics-status">●</span>
    <span id="analytics-processed">Processed: --</span>
    <span id="analytics-pending">Pending: --</span>
  </div>
</div>
```

**JavaScript Updates:**
```javascript
async function updateServiceStatus() {
  const response = await fetch('/api/v1/system/status');
  const data = await response.json();
  
  // Update core recorder status
  document.getElementById('core-status').className = 
    data.services.core_recorder.running ? 'status-online' : 'status-offline';
  
  // Update analytics service status
  document.getElementById('analytics-status').className = 
    data.services.analytics_service.running ? 'status-online' : 'status-offline';
}

setInterval(updateServiceStatus, 5000);
```

---

### 6. **Testing** (1 hour) - NOT DONE YET

**Test Checklist:**
- [ ] Start core recorder with new code
- [ ] Verify status file written: `/tmp/grape-core-test/status/core-recorder-status.json`
- [ ] Verify file updates every 10 seconds
- [ ] Check JSON structure matches spec
- [ ] Start analytics service
- [ ] Verify status file written: `/tmp/grape-core-test/status/analytics-service-status.json`
- [ ] Verify time_snap, detections, DRF stats tracking correctly
- [ ] Start web-ui monitoring server
- [ ] Access http://localhost:3000/api/v1/system/status
- [ ] Verify aggregated status from both services
- [ ] Open http://localhost:3000/timing-dashboard.html
- [ ] Verify both services shown as "RUNNING"
- [ ] Kill core recorder, verify UI shows offline
- [ ] Kill analytics service, verify UI shows offline

---

## 📊 File Changes Summary

### Modified Files (2)

**1. `src/signal_recorder/core_recorder.py`**
```
Lines changed: +70
- Added status file output (JSON format)
- 10-second update interval
- Per-channel and overall statistics
- Atomic writes (temp file + rename)
```

**2. `src/signal_recorder/analytics_service.py`**
```
Lines changed: +100
- Added status file output (JSON format)
- 10-second update interval
- time_snap, detections, DRF, quality stats
- Atomic writes (temp file + rename)
```

### Created Files (2)

**1. `WEB_UI_DUAL_SERVICE_INTEGRATION.md` (457 lines)**
- Complete integration architecture design
- Status file format specifications
- Implementation steps and testing checklist

**2. `WEB_UI_INTEGRATION_SUMMARY.md` (this file)**
- Session summary and progress tracking
- Code changes documentation
- Next steps roadmap

---

## 🎯 Architecture Benefits

**Independent Monitoring:**
- Core recorder can be monitored independently
- Analytics service has its own status
- One service down ≠ total failure

**Detailed Status:**
- Core: NPZ write progress, packet stats, gaps
- Analytics: time_snap, detections, DRF output, quality

**Web-UI Friendly:**
- 10-second updates (near real-time)
- JSON format (easy parsing)
- Atomic writes (no partial reads)
- File age checking (detect stale status)

**Future-Proof:**
- Easy to add new services
- Each service defines own status format
- Web-ui aggregates transparently

---

## 🔧 Implementation Quality

**Code Quality:**
- ✅ Type hints maintained
- ✅ Docstrings added
- ✅ Error handling (try/except on status writes)
- ✅ Atomic writes (no partial JSON)
- ✅ Minimal performance impact (10s interval)

**Testing Required:**
- ⚠️ Status files not tested yet (services not restarted)
- ⚠️ Web-ui aggregation not implemented yet
- ⚠️ Dashboard UI not updated yet

---

## ⏱️ Time Estimate

**Completed:** 3.5 hours
- Review: 0.5 hours
- Design: 1 hour
- Implementation: 2 hours

**Remaining:** 5 hours
- Monitoring server update: 2 hours
- Dashboard UI update: 2 hours
- Testing: 1 hour

**Total Project:** 8.5 hours

---

## 🚀 How to Continue

### Immediate Next Session

**Step 1: Update Monitoring Server**
```bash
cd /home/mjh/git/signal-recorder/web-ui
# Edit monitoring-server.js
# - Add getCoreRecorderStatus()
# - Add getAnalyticsServiceStatus()  
# - Update /api/v1/system/status endpoint
```

**Step 2: Test Backend**
```bash
# Restart core recorder with new code
# Wait 10 seconds
ls -la /tmp/grape-core-test/status/
cat /tmp/grape-core-test/status/core-recorder-status.json

# Start monitoring server
cd web-ui
node monitoring-server.js &

# Test endpoint
curl http://localhost:3000/api/v1/system/status | jq
```

**Step 3: Update Dashboard**
```bash
# Edit timing-dashboard.html
# - Add service status cards
# - Add updateServiceStatus() JavaScript
# - Style with CSS
```

**Step 4: End-to-End Test**
```bash
# Open browser: http://localhost:3000
# Verify both services shown
# Kill core recorder, verify UI updates
# Restart, verify UI recovers
```

---

## 📝 Notes

**Design Decisions:**
- 10-second status interval (balance between freshness and overhead)
- Atomic writes prevent partial JSON reads
- File age checking detects hung services (>30 seconds = dead)
- Each service independent (crash in one doesn't affect other)

**Alternative Approaches Considered:**
- IPC/sockets: More complex, overkill for status updates
- Shared memory: Not cross-platform, harder to debug
- Database: Adds dependency, overkill for simple status

**Chosen Approach:**
- JSON files: Simple, debuggable, language-agnostic
- Works great for local monitoring
- Could extend to remote monitoring via file sync

---

## ✅ Success Criteria

**When Complete:**
- [ ] Core recorder writes status every 10s
- [ ] Analytics service writes status every 10s
- [ ] Web-ui reads and aggregates both
- [ ] Dashboard shows dual-service status
- [ ] Graceful degradation (one service down = partial UI)
- [ ] Real-time updates (5-10s latency)
- [ ] No breaking changes to existing API

**Future Enhancements:**
- Add systemd integration (auto-restart dead services)
- Add email/SMS alerts on service failures
- Add historical uptime tracking
- Add performance metrics (CPU, memory, disk I/O)
- Add upload status when Phase 2C implemented

---

**Last Updated:** 2024-11-09 Evening  
**Status:** Phase 1-3 Complete, Phase 4-6 Pending  
**Next Session:** Monitoring server update + testing
