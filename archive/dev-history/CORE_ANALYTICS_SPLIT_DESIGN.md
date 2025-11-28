# Core/Analytics Split Architecture Design

**Date:** November 9, 2024  
**Status:** Design Proposal  
**Priority:** High - Fundamental to Scientific Reliability

---

## Problem Statement

Current architecture tightly couples data acquisition with analytics, causing:

1. **Data Loss Risk:** Analytics bugs require restarting recorder → missed packets
2. **No Reprocessing:** Can't apply improved algorithms to historical data
3. **Complex Monolith:** ~2000 lines mixing critical and experimental code
4. **Testing Difficulty:** Can't test analytics without live RTP stream

**Impact:** Scientific reliability compromised by operational fragility.

---

## Solution: Separate Core Recorder from Analytics

### Two Independent Services

```
┌────────────────────────────────────┐
│  signal-recorder-core              │  ← Minimal, battle-tested
│  (RTP → NPZ archives)              │  ← Changes: < 5/year
└────────────────────────────────────┘
            ↓
    Archive files (NPZ)
    Complete scientific record
            ↓
┌────────────────────────────────────┐
│  signal-recorder-analytics         │  ← Experimental, evolving
│  (NPZ → All derived products)      │  ← Changes: > 50/year
└────────────────────────────────────┘
```

---

## Core Recorder Responsibilities

### What It Does (ONLY)

1. **Receive RTP packets** from ka9q-radio multicast
2. **Resequence packets** using circular buffer (handle out-of-order)
3. **Detect gaps** via RTP timestamp discontinuities
4. **Fill gaps with zeros** (maintain sample count integrity)
5. **Write NPZ files** one minute at a time

### What It Does NOT Do

- ❌ No WWV tone detection
- ❌ No quality metrics calculation
- ❌ No time_snap establishment
- ❌ No decimation
- ❌ No Digital RF writing
- ❌ No uploading

### Code Size: ~300 lines

```
RTPReceiver          (~100 lines) - Multicast socket, SSRC demux
PacketResequencer    (~80 lines)  - Circular buffer, gap detection
NPZWriter           (~80 lines)  - Minute file writing
CoreRecorder        (~40 lines)  - Main loop, channel management
```

---

## NPZ Archive Format (Scientific Record)

### Required Fields (Primary Data)

```python
np.savez_compressed(
    file_path,
    
    # === CRITICAL: Sample Data ===
    iq=complex_samples,              # Complex64 array (960,000 samples @ 16 kHz)
    
    # === CRITICAL: Timing Reference ===
    rtp_timestamp=first_sample_rtp,  # RTP timestamp of iq[0]
    rtp_ssrc=ssrc,                   # RTP stream identifier
    sample_rate=16000,               # Sample rate (Hz)
    
    # === Metadata ===
    frequency_hz=frequency_hz,       # Center frequency
    channel_name=channel_name,       # e.g., "WWV 2.5 MHz"
    unix_timestamp=wall_clock_utc,   # Approximate (for human reference)
    
    # === Quality Indicators ===
    gaps_filled=gap_samples,         # Total samples filled with zeros
    gaps_count=num_gaps,             # Number of discontinuities
    packets_received=pkt_count,      # Actual packets
    packets_expected=expected_pkt,   # Expected (for loss rate)
    
    # === Provenance ===
    recorder_version="2.0.0",        # Core recorder version
    created_timestamp=creation_time  # File creation time
)
```

### Why RTP Timestamp is Critical

```python
# Precise time reconstruction (analytics step):

# 1. Load archive
data = np.load('archive.npz')
rtp_start = data['rtp_timestamp']

# 2. For sample at index N:
rtp_ts_N = rtp_start + N

# 3. After establishing time_snap (via WWV):
utc_N = time_snap_utc + (rtp_ts_N - time_snap_rtp) / sample_rate

# Result: Sub-millisecond UTC accuracy for every sample
```

### KA9Q Timing Architecture (Phil Karn)

**Principle:** RTP timestamp is primary time reference, not wall clock.

- RTP timestamps define the time domain
- Wall clock is DERIVED from RTP via time_snap anchor
- Sample count integrity guaranteed (gap-filled with zeros)
- No time "stretching" or "compression"

**Reference:** `/home/mjh/git/ka9q-radio/src/pcmrecord.c` lines 607-899

---

## Analytics Service Responsibilities

### Input: NPZ Archive Files

Watches archive directory for new files (inotify or polling).

### Outputs: Derived Products

```
NPZ archives
    ↓
    ├─→ Quality Metrics CSV
    │   └─ Completeness, jitter, packet loss
    │   └─ Gap categorization (network/source/recorder)
    │
    ├─→ WWV Tone Detection
    │   └─ Establish time_snap reference
    │   └─ Timing error measurements
    │   └─ WWV/WWVH/CHU differential delays
    │
    ├─→ Discontinuity Logs
    │   └─ Every gap, sync adjust, overflow
    │   └─ RTP timestamps + explanations
    │
    ├─→ Decimated Digital RF (10 Hz)
    │   └─ Anti-aliasing decimation (16k → 10 Hz)
    │   └─ Time-aligned to UTC midnight
    │   └─ PSWS format compliance
    │
    └─→ Upload to PSWS
        └─ Rsync to hamsci.org
        └─ Metadata validation
```

### Processing Pipeline

```python
# Analytics daemon pseudocode:

while True:
    # 1. Discover new NPZ files
    new_files = scan_archive_for_new_files()
    
    for npz_file in new_files:
        # 2. Load archive
        data = load_npz(npz_file)
        
        # 3. Quality metrics (always)
        metrics = calculate_quality_metrics(data)
        write_quality_csv(metrics)
        
        # 4. WWV detection (if applicable)
        if is_wwv_channel(data['channel_name']):
            wwv_result = detect_wwv_tone(data['iq'])
            if wwv_result:
                update_time_snap(wwv_result, data['rtp_timestamp'])
        
        # 5. Decimation (if time_snap established)
        if time_snap_available():
            drf_data = decimate_to_10hz(data['iq'], data['rtp_timestamp'])
            write_digital_rf(drf_data)
        
        # 6. Upload (when complete)
        if ready_for_upload():
            upload_to_psws(npz_file)
    
    sleep(10)  # Check every 10 seconds
```

---

## Benefits of Split Architecture

### 1. Zero Data Loss ✅

```
Analytics crash → Core keeps recording
Analytics update → Core unaffected
Analytics experiment → Safe in test mode
```

### 2. Reprocessing Historical Data ✅

```bash
# Improved WWV detector? Reprocess all archives:
signal-recorder-analytics --reprocess \
    --input /archive/20241001-20241031/ \
    --output /analytics/v2/

# Changed quality metrics? Regenerate CSVs:
signal-recorder-analytics --regenerate-quality \
    --archives /archive/20241109/
```

### 3. Independent Testing ✅

```python
# Test analytics with synthetic data:
def test_wwv_detection():
    synthetic_npz = create_synthetic_wwv_signal()
    result = detect_wwv_tone(synthetic_npz['iq'])
    assert result.timing_error_ms < 1.0

# Test with real data offline:
def test_quality_metrics():
    real_data = np.load('test_data/gap_example.npz')
    metrics = calculate_quality_metrics(real_data)
    assert metrics.completeness_pct == 99.5
```

### 4. Flexible Deployment ✅

```
Option A: Both services on same machine
    ├─ Core: High priority, real-time
    └─ Analytics: Normal priority

Option B: Separate machines
    ├─ Core: On station (near radio)
    └─ Analytics: On server (more CPU/RAM)

Option C: Cloud analytics
    ├─ Core: Local
    └─ Analytics: AWS batch processing
```

### 5. Simpler Core = Rock-Solid Reliability ✅

```python
# Core recorder: ~300 lines, few dependencies
# Less code = fewer bugs
# Fewer dependencies = fewer security issues
# No analytics experiments = stable behavior

# Mean time between changes:
# Core: ~2-3 months (only for critical bugs)
# Analytics: ~2-3 days (continuous improvement)
```

---

## Migration Path

### Phase 1: Extract Core Recorder (Week 1)

**New File:** `src/signal_recorder/core_recorder.py`

```python
class CoreRecorder:
    """
    Minimal RTP-to-NPZ recorder (no analytics)
    
    Responsibilities:
    1. Receive RTP packets
    2. Resequence and detect gaps
    3. Fill gaps with zeros
    4. Write NPZ archives
    """
    
    def __init__(self, config):
        self.rtp_receiver = RTPReceiver(config['multicast'])
        self.resequencer = PacketResequencer(buffer_size=64)
        self.npz_writer = NPZWriter(config['output_dir'])
    
    def run(self):
        """Main loop: packets → archives"""
        for packet in self.rtp_receiver:
            samples, gaps = self.resequencer.process(packet)
            if samples is not None:
                self.npz_writer.write_minute(samples, gaps)
```

**Changes:**
1. ✅ Create `core_recorder.py` (~300 lines)
2. ✅ Update NPZ format to include RTP timestamps
3. ✅ Add gap statistics to NPZ files
4. ✅ Test with current recorder running (parallel)

### Phase 2: Extract Analytics Service (Week 2)

**New File:** `src/signal_recorder/analytics_service.py`

```python
class AnalyticsService:
    """
    Process NPZ archives to create derived products
    """
    
    def __init__(self, archive_dir, output_dir):
        self.archive_dir = Path(archive_dir)
        self.output_dir = Path(output_dir)
        self.time_snap_tracker = TimeSnapTracker()
    
    def run(self):
        """Watch for new NPZ files and process"""
        for npz_file in self.watch_archives():
            self.process_archive(npz_file)
    
    def process_archive(self, npz_file):
        """Generate all derived products"""
        data = self.load_npz(npz_file)
        
        # Always generate quality metrics
        self.generate_quality_metrics(data)
        
        # WWV detection if applicable
        if self.is_wwv_channel(data):
            self.detect_wwv_tone(data)
        
        # Decimation if time_snap available
        if self.time_snap_tracker.is_established():
            self.decimate_to_digital_rf(data)
```

**Changes:**
1. ✅ Move quality metrics to analytics
2. ✅ Move WWV detection to analytics
3. ✅ Move decimation to analytics
4. ✅ Move Digital RF writing to analytics
5. ✅ Test with archived data

### Phase 3: Cutover (Week 3)

1. **Test Phase:**
   - Run core + analytics in parallel with current system
   - Verify identical outputs
   - Monitor for 48 hours

2. **Cutover:**
   - Stop current monolithic recorder
   - Start core recorder
   - Start analytics service
   - Monitor for 1 week

3. **Validation:**
   - Verify zero data loss
   - Confirm all derived products generated
   - Test reprocessing on old archives

---

## Interface Alignment

This architecture aligns perfectly with `INTERFACES_COMPLETE.md`:

### Function 1: QualityAnalyzedSampleProvider ✅

```python
# Analytics service implements this:
class NPZQualityAnalyzer(QualityAnalyzedSampleProvider):
    """Load NPZ archives and analyze quality"""
    
    def read_samples(self, start_time, duration) -> np.ndarray:
        # Load from NPZ files
        return samples
    
    def get_quality_info(self, start_time, duration) -> QualityInfo:
        # Calculate or load from quality CSV
        return quality_info
```

### Function 2: ArchiveWriter ✅

```python
# Core recorder implements this:
class NPZArchiveWriter(ArchiveWriter):
    """Write gap-filled NPZ archives"""
    
    def write_samples(self, samples: np.ndarray, metadata: dict):
        # Write minute NPZ files
        pass
```

### Function 3: ToneDetector ✅

```python
# Analytics service implements this:
class WWVToneDetector(ToneDetector):
    """Detect WWV tones from archived NPZ"""
    
    def detect(self, samples: np.ndarray) -> Optional[ToneDetection]:
        # Process archived samples
        return detection
```

---

## Configuration

### Core Recorder Config

```toml
[core]
mode = "production"  # or "test"
data_root = "/var/lib/signal-recorder"

[core.rtp]
multicast_address = "239.103.26.231"
port = 5004
buffer_size = 64  # packets

[core.channels]
[[core.channels.channel]]
ssrc = 2500000
frequency_hz = 2500000
sample_rate = 16000
description = "WWV 2.5 MHz"
```

### Analytics Service Config

```toml
[analytics]
archive_dir = "/var/lib/signal-recorder/data"
output_dir = "/var/lib/signal-recorder/analytics"
watch_interval = 10  # seconds

[analytics.quality]
enabled = true
csv_output = true

[analytics.wwv]
enabled = true
threshold = 0.5

[analytics.decimation]
enabled = true
output_rate = 10  # Hz
digital_rf_enabled = true

[analytics.upload]
enabled = false  # Enable when ready
destination = "hamsci.org"
```

---

## Performance Characteristics

### Core Recorder

- **CPU:** < 5% per channel (minimal processing)
- **Memory:** ~100 MB per channel (circular buffer)
- **Disk I/O:** ~2 MB/min write (compressed NPZ)
- **Network:** ~5 Mbps per channel (RTP input)
- **Latency:** < 100 ms (packet → NPZ write)

### Analytics Service

- **CPU:** 20-40% per channel (FFT, decimation)
- **Memory:** ~500 MB per channel (processing buffers)
- **Disk I/O:** Read NPZ + write derived products
- **Batch Processing:** Can lag behind real-time
- **Latency:** Not critical (offline processing)

---

## Error Handling

### Core Recorder (Conservative)

```python
# Never crash - just log and continue
try:
    samples = process_packet(packet)
except Exception as e:
    logger.error(f"Packet processing failed: {e}")
    continue  # Drop packet, keep running

# Disk full? Switch to emergency mode
if disk_space_low():
    switch_to_emergency_compression()
    alert_operator()
```

### Analytics Service (Aggressive)

```python
# Can retry, skip, or crash
try:
    process_archive(npz_file)
except ToneDetectionError:
    logger.warning(f"No tone in {npz_file}, skipping")
except DiskFullError:
    logger.error("Disk full, pausing analytics")
    sleep(3600)  # Wait for cleanup
except Exception as e:
    logger.error(f"Fatal error: {e}")
    raise  # Crash and restart (systemd will restart)
```

---

## Testing Strategy

### Core Recorder Tests

1. **Unit Tests:**
   - Packet resequencing with gaps
   - Gap detection accuracy
   - NPZ format validation

2. **Integration Tests:**
   - Synthetic RTP stream → NPZ archives
   - Verify sample count integrity
   - Verify RTP timestamp preservation

3. **Stress Tests:**
   - Handle 50% packet loss
   - Handle out-of-order delivery
   - Handle RTP timestamp resets

### Analytics Tests

1. **Regression Tests:**
   - Known archives → verify quality metrics
   - Known WWV signals → verify detection
   - Known gaps → verify categorization

2. **Reprocessing Tests:**
   - Process same archive twice → identical results
   - Update algorithm → reprocess → verify improvements

---

## Rollback Plan

If split architecture has issues:

1. **Immediate:** Restart old monolithic recorder
2. **Data:** No loss - NPZ archives are complete
3. **Analytics:** Rerun analytics service on archives
4. **Investigation:** Core and analytics logs separate
5. **Fix:** Update one service without affecting other

---

## Success Metrics

### Core Recorder

- ✅ Zero crashes for 30 days
- ✅ 100% sample count integrity
- ✅ < 0.01% packet loss (not counting network)
- ✅ < 1 second restart time

### Analytics Service

- ✅ Process all archives within 2x real-time
- ✅ WWV detection rate > 90% (strong signals)
- ✅ Quality CSV generation: 100%
- ✅ Can reprocess 1 month in < 12 hours

### Scientific Reliability

- ✅ All data archived with RTP timestamps
- ✅ Can regenerate all derived products
- ✅ Time_snap accuracy < 1 ms (when detected)
- ✅ Gap provenance: 100% categorized

---

## Next Steps

1. **Review & Approve** this design (stakeholder feedback)
2. **Create `core_recorder.py`** minimal implementation
3. **Update NPZ format** to include RTP timestamps
4. **Test core recorder** in parallel with current system
5. **Extract analytics** into separate service
6. **Integration testing** for 48 hours
7. **Production cutover** with rollback plan ready

---

## Conclusion

This architecture split provides:

- **Scientific Reliability:** Complete data preservation with precise timing
- **Operational Stability:** Core rarely changes, analytics can iterate
- **Reprocessing Capability:** Apply improved algorithms retroactively
- **Independent Testing:** Validate analytics without live streams
- **Flexible Deployment:** Separate services, independent scaling

**The core principle:** Battle-tested data acquisition, experimental analytics.

---

**Document Status:** Design Proposal  
**Next Review:** After stakeholder feedback  
**Implementation Start:** TBD
