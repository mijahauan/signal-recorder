# Proper time_snap Architecture - Option B Implementation

**Date**: 2025-11-23 19:16 UTC-06:00  
**Status**: ✅ Implementation Complete  
**Priority**: CRITICAL - Ensures data collection accuracy

---

## Problem Addressed

**Original Issue**: time_snap was established by analytics AFTER core recorder wrote files, causing:
- Minute boundaries misaligned with actual RTP timestamps
- Potential resequencing when time_snap changed
- Analytics and decimation working on inconsistent time references

**Root Cause**: Chicken-and-egg problem where time_snap needed NPZ files to be created, but NPZ files needed time_snap for accurate timestamps.

---

## Solution: Startup Buffering + Embedded time_snap

### Architecture Overview

```
Core Recorder Startup Sequence:
┌──────────────────────────────────────────────────────┐
│ 1. Start RTP receiver                                │
│ 2. Buffer 120 seconds of samples                     │
│ 3. Detect WWV/CHU tone rising edge (±1ms precision)  │
│ 4. Establish time_snap (tone > NTP > wall_clock)     │
│ 5. Create NPZ writer with fixed time_snap            │
│ 6. Process buffered samples through writer           │
│ 7. Continue normal operation                         │
└──────────────────────────────────────────────────────┘

NPZ Files (Self-Contained):
┌──────────────────────────────────────────────────────┐
│ • iq samples (960,000 = 60 seconds @ 16kHz)          │
│ • rtp_timestamp (of first sample)                    │
│ • time_snap_rtp (anchor RTP timestamp)               │
│ • time_snap_utc (anchor UTC timestamp)               │
│ • time_snap_source (wwv_startup, ntp, wall_clock)    │
│ • time_snap_confidence (0.0-1.0)                     │
│ • time_snap_station (WWV, WWVH, CHU, NTP, etc.)      │
└──────────────────────────────────────────────────────┘

Analytics:
┌──────────────────────────────────────────────────────┐
│ 1. Read NPZ file                                      │
│ 2. Extract time_snap FROM file metadata              │
│ 3. Use for ALL timing calculations                   │
│ 4. Never modify or replace time_snap                 │
└──────────────────────────────────────────────────────┘
```

---

## Implementation Details

### 1. **Startup Tone Detector** (`startup_tone_detector.py`)

**Purpose**: Detect WWV/CHU tone rising edge with ±1ms precision

**Method**: Hilbert Transform + Sub-sample Interpolation
```python
def detect_rising_edge():
    """
    1. Bandpass filter: tone_freq ± 50 Hz (Butterworth order 4)
    2. Hilbert transform → analytic signal
    3. Envelope extraction: |analytic_signal|
    4. Derivative of envelope → find sharp rises
    5. Validate: SNR > 3dB, signal stability
    6. Sub-sample interpolation (parabolic fit)
    7. Return: RTP timestamp at rising edge (±1ms)
    """
```

**Key Features**:
- ✅ Separate from discrimination tone detector (different goals)
- ✅ Works for WWV (1000 Hz), WWVH (1200 Hz), CHU (1000 Hz)
- ✅ Phase-coherent edge detection (not just FFT power)
- ✅ Sub-millisecond precision via interpolation
- ✅ Fallback to NTP or wall clock if no tone

**Timing Hierarchy**:
1. **WWV/CHU tone** (±1ms) - Best
2. **NTP sync** (±10ms) - Good
3. **Wall clock** (±seconds) - Fallback

### 2. **Core Recorder** (`core_recorder.py`)

**New: Startup Buffering Phase**

```python
class ChannelProcessor:
    def __init__(self):
        self.startup_mode = True
        self.startup_buffer = []  # Buffer 120 seconds
        self.startup_buffer_duration = 120
        self.tone_detector = StartupToneDetector(...)
        self.npz_writer = None  # Created AFTER time_snap
    
    def process_rtp_packet(self):
        if self.startup_mode:
            self._handle_startup_buffering()
        else:
            self._handle_normal_operation()
    
    def _establish_time_snap(self):
        # Concatenate buffered samples
        # Run tone detection
        # Create NPZ writer with time_snap
```

**Sequence**:
1. Packets arrive → resequenced → buffered
2. After 120 seconds → establish time_snap
3. Create NPZ writer with time_snap
4. Process all buffered samples
5. Continue normal operation

**Buffer Duration**: 120 seconds
- Contains 120 potential tone marks
- High probability of detecting at least one clear tone
- Enough data for confident edge detection

### 3. **NPZ Writer** (`core_npz_writer.py`)

**Changes**:
- Accepts `time_snap` parameter at initialization (fixed, never changes)
- Embeds time_snap in every NPZ file metadata
- Uses time_snap for ALL timestamp calculations
- No more loading from external state files

**NPZ Metadata (New Fields)**:
```python
np.savez_compressed(
    file_path,
    iq=data,
    rtp_timestamp=...,
    
    # === TIME_SNAP (EMBEDDED) ===
    time_snap_rtp=self.time_snap.rtp_timestamp,
    time_snap_utc=self.time_snap.utc_timestamp,
    time_snap_source=self.time_snap.source,
    time_snap_confidence=self.time_snap.confidence,
    time_snap_station=self.time_snap.station,
    
    # ... rest of metadata
)
```

---

## Key Architectural Decisions

### ✅ **time_snap Established BEFORE File Writing**
- Core recorder buffers samples first
- Detects tone rising edge
- THEN creates NPZ writer
- All files use same time_snap

### ✅ **Self-Contained NPZ Files**
- time_snap embedded in file metadata
- No dependency on external state files
- Reprocessable years later with same timing

### ✅ **Separate Tone Detectors**

| Aspect | Startup (Core) | Discrimination (Analytics) |
|--------|----------------|----------------------------|
| **Goal** | Rising edge timing | Power ratio measurement |
| **Precision** | ±1ms | ±0.1dB |
| **Method** | Hilbert + edge detection | Spectral integration |
| **Duration** | ~50ms at onset | 0.8s full tone or 60s |
| **Output** | RTP timestamp | WWV/WWVH power ratio |

### ✅ **Analytics Consumes, Doesn't Create**
- Reads time_snap FROM NPZ metadata
- Uses for all timing calculations
- Never modifies or replaces it
- All analytics use same time reference

---

## File Changes

### **New Files**:
1. **`startup_tone_detector.py`** - Precise rising edge detection
2. **`SESSION_2025-11-23_PROPER_TIMESNAP_ARCHITECTURE.md`** - This document

### **Modified Files**:
1. **`core_recorder.py`**:
   - Added startup buffering phase
   - Added `_establish_time_snap()`
   - Added `_handle_startup_buffering()`
   - Added `_detect_rising_edge()` methods
   - Removed state_file dependency

2. **`core_npz_writer.py`**:
   - Changed `__init__` to accept `time_snap` parameter
   - Removed dynamic time_snap loading
   - Added time_snap fields to NPZ metadata
   - Simplified `_calculate_utc_from_rtp()` (uses fixed time_snap)

### **To Be Modified** (Next Step):
1. **`analytics_service.py`**:
   - Read time_snap from NPZ metadata
   - Don't create new time_snap
   - Use NPZ time_snap for all analysis

---

## Benefits

### 1. **Consistent Minute Boundaries**
```
File 1: 18:00:00.000 → 18:01:00.000 (RTP: 960000-1920000)
File 2: 18:01:00.000 → 18:02:00.000 (RTP: 1920000-2880000)
File 3: 18:02:00.000 → 18:03:00.000 (RTP: 2880000-3840000)

✅ Perfect alignment, no gaps, no overlaps
✅ All files use SAME time_snap
✅ No resequencing when time_snap changes
```

### 2. **Accurate 960,000 Sample Counts**
- Minute boundaries aligned with RTP timestamps
- Sample count matches duration exactly
- No fractional samples or rounding errors

### 3. **Reprocessability**
- NPZ files are self-contained
- Can reprocess years later
- Same results guaranteed

### 4. **Progressive Accuracy**
- Starts with best available (tone > NTP > wall_clock)
- Never degrades
- Logged for provenance

### 5. **Two-Pipeline Integrity**

**Pipeline 1: 10 Hz Carrier (Upload to GRAPE)**
```
NPZ (16kHz) → [Read time_snap] → Decimate to 10Hz → Digital RF
              ↑
              Same time_snap used for all samples
```

**Pipeline 2: Discrimination Analytics**
```
NPZ (16kHz) → [Read time_snap] → Analyze tones → CSV results
              ↑
              Same time_snap used for timing
```

Both pipelines use IDENTICAL time reference!

---

## Testing Plan

### 1. **Startup Behavior**
```bash
# Start core recorder
python3 -m signal_recorder.core_recorder --config config.toml

# Watch logs for:
# - "Starting startup buffer..."
# - "Startup buffer complete (120.0s), establishing time_snap..."
# - "✅ time_snap established: WWV tone at ..."
# - "Startup complete, normal recording started"
```

**Expected**: 2 minute delay before first NPZ file written

### 2. **NPZ File Validation**
```python
import numpy as np

# Load NPZ file
npz = np.load('20251123T180200Z_10000000_iq.npz')

# Check time_snap fields
print(f"time_snap_rtp: {npz['time_snap_rtp']}")
print(f"time_snap_utc: {npz['time_snap_utc']}")
print(f"time_snap_source: {npz['time_snap_source']}")
print(f"time_snap_confidence: {npz['time_snap_confidence']}")
print(f"time_snap_station: {npz['time_snap_station']}")

# Verify sample count
print(f"Samples: {len(npz['iq'])}")  # Should be 960,000
```

### 3. **Minute Boundary Alignment**
```python
# Calculate UTC for each sample
rtp_start = npz['rtp_timestamp']
time_snap_rtp = npz['time_snap_rtp']
time_snap_utc = npz['time_snap_utc']
sample_rate = npz['sample_rate']

# First sample
utc_first = time_snap_utc + (rtp_start - time_snap_rtp) / sample_rate
print(f"First sample UTC: {utc_first}")  # Should be :XX:00.000

# Last sample
rtp_end = rtp_start + 960000 - 1
utc_last = time_snap_utc + (rtp_end - time_snap_rtp) / sample_rate
print(f"Last sample UTC: {utc_last}")    # Should be :XX:59.999937
```

### 4. **Edge Detection Precision**
```bash
# Check startup logs for:
# "SNR=XX.XdB, precision=±1ms"

# Verify confidence scores:
# - >0.85 for good signals
# - Fallback to NTP if needed
```

---

## Deployment Instructions

### 1. **Stop Existing Services**
```bash
pkill -f core_recorder
pkill -f analytics_service
```

### 2. **Backup Existing Data**
```bash
# Optional: backup current archives
cp -r /tmp/grape-test/archives /tmp/grape-test/archives.backup
```

### 3. **Start Core Recorder**
```bash
cd /home/wsprdaemon/signal-recorder
source venv/bin/activate

python3 -m signal_recorder.core_recorder --config config/recorder.toml
```

### 4. **Wait for Startup**
- **Duration**: 2 minutes (120 second buffer)
- **Watch logs** for time_snap establishment
- **First file** written ~2-3 minutes after start

### 5. **Validate First Files**
```bash
# Check file sizes
ls -lh /tmp/grape-test/archives/WWV_10_MHz/*.npz | tail -5

# Verify sample counts
python3 test-core-recorder-fix.py --archive-dir /tmp/grape-test/archives/WWV_10_MHz --latest 3
```

### 6. **Start Analytics** (After NPZ Files Available)
```bash
# Analytics will now READ time_snap from NPZ files
# (Update analytics_service.py first - see next section)
```

---

## Next Steps

### **Immediate (This Session)**:
1. ✅ Implement precise edge detection - DONE
2. ✅ Add startup buffering to core recorder - DONE
3. ✅ Embed time_snap in NPZ metadata - DONE
4. ⏳ Update analytics to read time_snap from NPZ - PENDING

### **Deployment**:
1. Test startup sequence
2. Validate time_snap detection
3. Verify 960,000 sample counts
4. Check minute boundary alignment

### **Analytics Update** (Next):
```python
# analytics_service.py changes needed:

def process_archive(self, npz_file):
    archive = np.load(npz_file)
    
    # READ time_snap from NPZ (don't create new one)
    time_snap = TimeSnapReference(
        rtp_timestamp=int(archive['time_snap_rtp']),
        utc_timestamp=float(archive['time_snap_utc']),
        sample_rate=int(archive['sample_rate']),
        source=str(archive['time_snap_source']),
        confidence=float(archive['time_snap_confidence']),
        station=str(archive['time_snap_station']),
        established_at=float(archive['unix_timestamp'])
    )
    
    # Use THIS time_snap for all analysis
    # Don't update or replace it
```

---

## Success Criteria

### ✅ **Data Collection Right**:
- [ ] Core recorder starts successfully
- [ ] 120-second startup buffer completes
- [ ] time_snap established (tone or NTP)
- [ ] First NPZ file written with 960,000 samples
- [ ] time_snap embedded in metadata
- [ ] Minute boundaries aligned with RTP

### ✅ **Analytics Integrity**:
- [ ] Analytics reads time_snap from NPZ
- [ ] 10 Hz decimation uses NPZ time_snap
- [ ] Discrimination uses NPZ time_snap
- [ ] Both pipelines use same time reference

### ✅ **Reprocessability**:
- [ ] NPZ files self-contained
- [ ] Can process files from different sessions
- [ ] Consistent results across reprocessing

---

## Architecture Compliance

This implementation fully aligns with documented principles:

✅ **RTP timestamp is PRIMARY reference** (CONTEXT.md)  
✅ **Sample count integrity** (960,000 samples)  
✅ **No time stretching** (fixed time_snap)  
✅ **Timing hierarchy**: tone > NTP > wall_clock  
✅ **Gap handling**: Zero-fill preserves sample count  
✅ **Self-contained archives**: NPZ files have all metadata  
✅ **Reprocessability**: Archives processable independently

---

**Implementation Status**: Core recorder complete, analytics update pending  
**Ready for**: Deployment and testing  
**Next Action**: Update analytics_service.py to read time_snap from NPZ

**End of Architecture Document**
