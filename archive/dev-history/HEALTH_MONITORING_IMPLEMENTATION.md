# Health Monitoring & Gap Categorization Implementation

**Date:** 2024-11-09  
**Status:** Core modules completed, integration pending  
**Purpose:** Detect radiod restarts and recorder offline periods with automatic recovery

---

## What's Been Implemented

### 1. Enhanced Data Models ✅

**File:** `src/signal_recorder/interfaces/data_models.py`

**Changes:**
- Added `SOURCE_UNAVAILABLE` discontinuity type (radiod down/channel missing)
- Added `RECORDER_OFFLINE` discontinuity type (daemon not running)
- Removed subjective quality grading (`quality_grade`, `quality_score`)
- Added gap categorization fields to `QualityInfo`:
  - `network_gap_ms` - Packet-level losses (GAP, OVERFLOW, UNDERFLOW)
  - `source_failure_ms` - Radiod unavailability (SOURCE_UNAVAILABLE)
  - `recorder_offline_ms` - Daemon downtime (RECORDER_OFFLINE)
- Added `get_gap_breakdown()` method for analysis

**Key Principle:** Report what happened quantitatively, scientists decide usability.

### 2. Radiod Health Monitoring ✅

**File:** `src/signal_recorder/radiod_health.py`

**Class:** `RadiodHealthChecker`

**Features:**
- `is_radiod_alive()` - Check if radiod is broadcasting status packets
- `verify_channel_exists(ssrc)` - Verify specific channel exists via control utility
- `get_status()` - Comprehensive health report

**Usage:**
```python
checker = RadiodHealthChecker(status_address="239.192.152.141")

if not checker.is_radiod_alive():
    logger.warning("Radiod appears down")
    
if not checker.verify_channel_exists(2500000):
    logger.error("WWV 2.5 MHz channel missing - attempting recreation")
```

### 3. Session Boundary Detection ✅

**File:** `src/signal_recorder/session_tracker.py`

**Class:** `SessionBoundaryTracker`

**Features:**
- `check_for_offline_gap()` - Detects gaps from last session on startup
- Reads most recent archive file timestamp
- Creates `RECORDER_OFFLINE` discontinuity if gap >2 minutes
- Logs to persistent `session_boundaries.jsonl` file
- `get_session_history()` - Retrieve past offline periods

**Usage:**
```python
tracker = SessionBoundaryTracker(
    archive_dir="/var/lib/signal-recorder/archive",
    channel_name="WWV 5.0 MHz",
    sample_rate=16000
)

offline_gap = tracker.check_for_offline_gap(time.time())
if offline_gap:
    discontinuities.append(offline_gap)
    logger.warning(f"Recorder was offline for {offline_gap.magnitude_ms/3600000:.2f} hours")
```

---

## Integration Required

### Step 1: Add Health Monitoring to Recorder

**File to modify:** `src/signal_recorder/grape_rtp_recorder.py`

**In `GRAPEChannelRecorder.__init__()`:**
```python
# Add health tracking
self._last_packet_time = None
self._no_data_threshold_sec = 60  # Alert after 60s silence
self._session_tracker = SessionBoundaryTracker(
    archive_dir=config['recorder']['archive_dir'],
    channel_name=channel_config['description'],
    sample_rate=channel_config['sample_rate']
)

# Check for offline gap on startup
offline_gap = self._session_tracker.check_for_offline_gap(time.time())
if offline_gap:
    self._discontinuities.append(offline_gap)
```

**Add health check method:**
```python
def _check_channel_health(self) -> bool:
    """Returns True if channel is receiving data."""
    if self._last_packet_time is None:
        return True  # Still starting up
    
    silence_duration = time.time() - self._last_packet_time
    
    if silence_duration > self._no_data_threshold_sec:
        # Create SOURCE_UNAVAILABLE discontinuity
        expected_samples = int(silence_duration * self.sample_rate)
        
        discontinuity = Discontinuity(
            timestamp=self._last_packet_time,
            sample_index=self._total_samples_written,
            discontinuity_type=DiscontinuityType.SOURCE_UNAVAILABLE,
            magnitude_samples=expected_samples,
            magnitude_ms=silence_duration * 1000,
            rtp_sequence_before=self._last_rtp_sequence,
            rtp_sequence_after=None,
            rtp_timestamp_before=self._last_rtp_timestamp,
            rtp_timestamp_after=None,
            wwv_related=False,
            explanation=(
                f"No RTP packets received for {silence_duration:.1f}s. "
                f"Likely cause: radiod restarted or channel {self.ssrc} deleted. "
                f"Estimated {expected_samples} samples lost."
            )
        )
        
        self._discontinuities.append(discontinuity)
        self.logger.error(f"SOURCE_UNAVAILABLE: {discontinuity.explanation}")
        return False
    
    return True

# Update _last_packet_time in RTP packet handler
def _handle_rtp_packet(self, packet):
    # ... existing code ...
    self._last_packet_time = time.time()
```

### Step 2: Add Auto-Recovery in Manager

**File to modify:** `src/signal_recorder/grape_rtp_recorder.py`

**In `GRAPERTPRecorder.__init__()`:**
```python
self._health_checker = RadiodHealthChecker(config['ka9q']['status_address'])
self._recovery_thread = threading.Thread(target=self._health_monitor_loop, daemon=True)
self._channel_configs = {}  # Store configs for recreation
```

**Add health monitoring loop:**
```python
def _health_monitor_loop(self):
    """Background thread: Check health every 30 seconds."""
    while self._running:
        time.sleep(30)
        
        # Check if radiod is alive
        if not self._health_checker.is_radiod_alive():
            self.logger.warning("Radiod appears down - waiting for restart")
            time.sleep(30)
            continue
        
        # Check each channel
        for ssrc, channel in self._channels.items():
            if not channel._check_channel_health():
                # Channel silent - verify it exists
                if not self._health_checker.verify_channel_exists(ssrc):
                    self.logger.error(
                        f"Channel {channel.channel_name} (SSRC {ssrc}) "
                        f"missing from radiod - attempting recreation"
                    )
                    self._recreate_channel(self._channel_configs[ssrc])

def _recreate_channel(self, channel_config: dict):
    """Recreate a missing channel."""
    try:
        from signal_recorder.channel_manager import create_channel
        
        success = create_channel(
            status_address=self.config['ka9q']['status_address'],
            ssrc=channel_config['ssrc'],
            frequency_hz=channel_config['frequency_hz'],
            preset=channel_config.get('preset', 'iq'),
            sample_rate=channel_config.get('sample_rate', 16000),
            description=channel_config.get('description', '')
        )
        
        if success:
            self.logger.info(f"Successfully recreated channel {channel_config['description']}")
            # Reset packet timer
            self._channels[channel_config['ssrc']]._last_packet_time = time.time()
        else:
            self.logger.error(f"Failed to recreate channel {channel_config['description']}")
            
    except Exception as e:
        self.logger.error(f"Channel recreation exception: {e}")

def start(self):
    # ... existing start code ...
    self._recovery_thread.start()
```

### Step 3: Update Quality Metrics Calculation

**File to modify:** `src/signal_recorder/quality_metrics.py`

**Update quality calculation to populate gap breakdown fields:**
```python
def calculate_quality_info(discontinuities: List[Discontinuity], ...) -> QualityInfo:
    # Calculate categorized gap durations
    network_gap_ms = sum(
        d.magnitude_ms for d in discontinuities
        if d.discontinuity_type in [
            DiscontinuityType.GAP,
            DiscontinuityType.OVERFLOW,
            DiscontinuityType.UNDERFLOW
        ]
    )
    
    source_failure_ms = sum(
        d.magnitude_ms for d in discontinuities
        if d.discontinuity_type == DiscontinuityType.SOURCE_UNAVAILABLE
    )
    
    recorder_offline_ms = sum(
        d.magnitude_ms for d in discontinuities
        if d.discontinuity_type == DiscontinuityType.RECORDER_OFFLINE
    )
    
    return QualityInfo(
        completeness_pct=...,
        gap_count=len(discontinuities),
        gap_duration_ms=sum(d.magnitude_ms for d in discontinuities),
        packet_loss_pct=...,
        resequenced_count=...,
        time_snap_established=...,
        time_snap_confidence=...,
        discontinuities=discontinuities,
        network_gap_ms=network_gap_ms,
        source_failure_ms=source_failure_ms,
        recorder_offline_ms=recorder_offline_ms
    )
```

---

## Testing Plan

### Test 1: Recorder Offline Detection

```bash
# Terminal 1: Start recorder
signal-recorder daemon --config config/grape-config.toml

# Let it run for 5 minutes, then Ctrl+C

# Wait 3 minutes (offline period)

# Start again
signal-recorder daemon --config config/grape-config.toml

# Expected: Log shows "Detected recorder offline gap: 0.05 hours"
# Check: cat /var/lib/signal-recorder/archive/session_boundaries.jsonl
```

### Test 2: Radiod Restart Detection

```bash
# Terminal 1: Start recorder
signal-recorder daemon --config config/grape-config.toml

# Terminal 2: Monitor logs
tail -f /var/lib/signal-recorder/logs/recorder_*.log

# Terminal 3: Simulate radiod crash
sudo systemctl stop radiod

# Expected after 60s: "No RTP packets received for 60s"
# Expected after 90s: "Channel missing from radiod - attempting recreation"

# Restart radiod
sudo systemctl start radiod

# Expected: "Successfully recreated channel WWV 2.5 MHz"
# Verify: grep "SOURCE_UNAVAILABLE" logs/recorder_*.log
```

### Test 3: Quality Report Verification

```bash
# After running tests above, check quality summary
python3 -c "
import json
data = json.load(open('/var/lib/signal-recorder/status/recording-stats.json'))
for ch in data['recorders']:
    print(f\"Channel: {ch['channel']}\")
    print(f\"  Network gaps: {ch['quality']['network_gap_ms']}ms\")
    print(f\"  Source failures: {ch['quality']['source_failure_ms']}ms\")
    print(f\"  Recorder offline: {ch['quality']['recorder_offline_ms']}ms\")
"
```

---

## Expected Output

### Session Boundaries Log

**File:** `/var/lib/signal-recorder/archive/session_boundaries.jsonl`

```json
{"channel": "WWV 5.0 MHz", "gap_type": "RECORDER_OFFLINE", "previous_session_end": 1699876543.21, "previous_session_end_str": "2024-11-09T03:15:43", "current_session_start": 1699876723.45, "current_session_start_str": "2024-11-09T03:18:43", "gap_duration_sec": 180.24, "gap_duration_hours": 0.05, "explanation": "Recorder was offline for 0.05 hours...", "detected_at": "2024-11-09T03:18:43.456"}
```

### Quality Summary

```json
{
  "completeness_pct": 94.2,
  "gap_count": 3,
  "gap_duration_ms": 312680.0,
  "network_gap_ms": 180.0,
  "source_failure_ms": 312500.0,
  "recorder_offline_ms": 0.0,
  "gap_breakdown": {
    "network": {
      "count": 2,
      "total_ms": 180.0,
      "gaps": [...]
    },
    "source_failure": {
      "count": 1,
      "total_ms": 312500.0,
      "gaps": [...]
    },
    "recorder_offline": {
      "count": 0,
      "total_ms": 0.0,
      "gaps": []
    }
  }
}
```

---

## Next Steps

1. **Review this implementation plan**
2. **Integrate health monitoring into grape_rtp_recorder.py** (Steps 1-2 above)
3. **Update quality_metrics.py** (Step 3 above)
4. **Test with simulated failures** (Testing plan above)
5. **Monitor in production for 24 hours**
6. **Document any edge cases discovered**

---

## Benefits

✅ **Complete data provenance** - Every gap categorized and explained  
✅ **Automatic recovery** - Recreates channels after radiod restarts  
✅ **Session tracking** - Knows when daemon was offline  
✅ **Quantitative reporting** - Scientists apply their own thresholds  
✅ **Production ready** - Handles real-world operational issues

---

**Implementation Status:** Core modules complete, integration in progress  
**Estimated Integration Time:** 2-3 hours  
**Testing Time:** 1-2 hours
