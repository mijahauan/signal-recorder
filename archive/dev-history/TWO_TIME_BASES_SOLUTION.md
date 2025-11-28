# The Two Time Bases - Complete Solution

## Date: 2025-11-26

## 🎯 The Key Insight

**There are TWO independent time bases**, and we measure drift **BETWEEN** them:

1. **Data Time Base** (ADC Clock) - What we're characterizing
2. **Reference Time Base** (NTP Wall Clock) - What we compare against

## ⚡ The Breakthrough

### The Problem We Had
```python
# WRONG - Circular reference:
unix_timestamp = time_snap.calculate_time(rtp)  # Calculated FROM RTP
drift = unix_timestamp - time_snap.calculate_time(rtp)  # Compares to itself!
# Result: Always 0.000 drift
```

### The Solution
```python
# RIGHT - Independent references:
rtp_predicted = time_snap.calculate_time(rtp)     # Data time base (ADC clock)
ntp_actual = archive.ntp_wall_clock_time          # Reference time base (NTP)
drift = ntp_actual - rtp_predicted                 # BETWEEN the two bases
```

---

## 🕒 The Two Time Bases Explained

### 1. Data Time Base (ADC Clock) 📡

**Source:** Analog-to-Digital Converter clock inside ka9q-radio hardware

**Measurement:** RTP Timestamps
- Counts samples at ~16,000 samples/second
- Question: Is it **exactly** 16,000 Hz? Or 16,000.1 Hz? Or 15,999.9 Hz?

**Anchor:** WWV/CHU Time-Snap
- At RTP timestamp X, UTC time was exactly Y (±0.1ms precision)
- Gives us **offset**, but not **rate** (frequency)

**What We Don't Know:**
- ADC clock frequency drift
- Is it running fast or slow?
- How stable is it minute-to-minute?

### 2. Reference Time Base (NTP Wall Clock) 💻

**Source:** System wall clock on recording computer

**Synchronization:** NTP/PTP
- Keeps system time aligned with UTC
- Typically ±10ms precision
- Independent of ADC hardware

**Purpose:** Provides stable reference to judge ADC clock performance

**Stored In Archive:** `ntp_wall_clock_time`
- Captured at moment archive was written
- Independent measurement (not derived from RTP)

---

## 📐 The Drift Calculation

### What Drift Measures

**Question:** Is the ADC clock running at exactly 16,000 Hz?

```python
# At time_snap (minute 0):
time_snap: RTP = 1,000,000, UTC = 100.0

# At minute 1:
# ADC says (via RTP):
rtp = 1,960,000  # 960,000 samples later
rtp_predicted_time = 100.0 + (960,000 / 16,000) = 160.0 seconds

# NTP says (independent):
ntp_actual_time = 160.05 seconds  # Stored in archive

# Drift:
drift = 160.05 - 160.0 = +0.05 seconds = +50 ms

# Interpretation: ADC clock is running SLOW
# It thought 60 seconds passed, but actually 60.05 seconds passed
# ADC frequency ≈ 15,986.7 Hz (not 16,000 Hz!)
```

### Drift Sign Convention

```
Positive drift (+):  NTP ahead of RTP → ADC clock running SLOW
Negative drift (-):  NTP behind RTP → ADC clock running FAST
Zero drift (0):      ADC clock perfect at 16,000.0 Hz
```

---

## 💾 Implementation Details

### Core Recorder Changes

**Added to NPZ archives:**
```python
# NEW fields for independent time reference:
ntp_wall_clock_time: float  # time.time() when archive written
ntp_offset_ms: float        # NTP offset quality indicator

# Existing (RTP-derived):
unix_timestamp: float  # time_snap.calculate_time(rtp) - NOT independent!
```

**In `core_npz_writer.py`:**
```python
np.savez_compressed(
    ...
    unix_timestamp=self.current_minute_timestamp.timestamp(),  # RTP-derived
    ntp_wall_clock_time=time.time(),           # ← INDEPENDENT reference
    ntp_offset_ms=self._get_ntp_offset(),      # ← Quality indicator
    ...
)
```

### Analytics Changes

**In `analytics_service.py`:**
```python
# Use archive's stored NTP time (independent reference)
if archive.ntp_wall_clock_time is not None:
    self.timing_writer.write_snapshot(
        time_snap=archive_time_snap,          # ADC anchor (from tone)
        current_rtp=archive.rtp_timestamp,    # ADC measurement
        current_utc=archive.ntp_wall_clock_time,  # ← NTP reference (independent)
        ntp_offset_ms=archive.ntp_offset_ms,
        ntp_synced=(ntp_offset < 100ms)
    )
```

**In `timing_metrics_writer.py`:**
```python
def _calculate_drift_minute_to_minute(...):
    # ADC clock says:
    rtp_predicted = time_snap.calculate_sample_time(current_rtp)
    
    # NTP reference says:
    ntp_actual = current_time_utc  # From archive.ntp_wall_clock_time
    
    # Drift between time bases:
    drift_ms = (ntp_actual - rtp_predicted) * 1000
    return drift_ms
```

---

## 🎯 Why This Works

### For Live Data ✅
- Archive written with current `time.time()` = NTP wall clock
- Provides independent reference
- Measures ADC clock drift vs NTP

### For Historical Data ✅
- Archive contains stored `ntp_wall_clock_time`
- Still independent (captured at recording time)
- Works regardless of processing lag
- Works across RTP sessions (core recorder restarts)

### For Old Archives Without NTP Time ⚠️
- Skip drift measurement (no independent reference)
- Use tone-to-tone instead (gold standard)

---

## 📊 The Three Measurement Types

### 1. **Minute-to-Minute Drift** (RTP vs NTP)

**Measures:** ADC clock stability between minutes
**Reference:** NTP wall clock (±10ms precision)
**Update:** Every minute
**Use Case:** Operational monitoring

```python
Drift: ±5-50 ms     # Typical with good ADC + NTP
Jitter: ±2-20 ms    # RMS variation
```

### 2. **Tone-to-Tone Drift** (Gold Standard)

**Measures:** ADC clock frequency error
**Reference:** WWV/CHU atomic clock (±0.1 ppm precision)
**Update:** Every ~5 minutes (when tones detected)
**Use Case:** Scientific characterization

```python
Drift: ±1-5 ppm     # Parts per million frequency error
Example: +2.5 ppm = ADC at 16,000.04 Hz instead of 16,000.00 Hz
```

### 3. **Time Basis Comparison**

**Measures:** How much time_snap and NTP disagree
**Purpose:** Validate time_snap quality
**Use Case:** Debugging, quality assessment

---

## 🔄 Time Basis Transitions

### Normal Operation (Tone-Locked)
```
Data Basis: ADC clock anchored by WWV tone (±0.1ms offset)
Reference:  NTP wall clock (±10ms precision)
Quality:    TONE_LOCKED
Drift:      ADC vs NTP (±5-50ms typical)
```

### Tone Loss (Fallback to NTP)
```
Data Basis: ADC clock anchored by stale tone or NTP
Reference:  NTP wall clock  
Quality:    NTP_SYNCED or INTERPOLATED
Drift:      Less meaningful (both using NTP basis)
Action:     Wait for fresh tone, use tone-to-tone when available
```

### Complete Loss (Wall Clock Only)
```
Data Basis: ADC clock anchored by wall clock
Reference:  Wall clock
Quality:    WALL_CLOCK
Drift:      Meaningless (circular)
Action:     Restore NTP or wait for tone
```

---

## ✅ Verification

### Test the Implementation

```bash
# Restart core recorder to generate new archives with NTP time
pkill -f core_recorder
./start-dual-service.sh config/grape-config.toml

# Wait 2-3 minutes for new archives
sleep 180

# Check new archive has NTP time
python3 << 'EOF'
import numpy as np, glob
archives = sorted(glob.glob('/tmp/grape-test/archives/WWV_10_MHz/*.npz'))
npz = np.load(archives[-1])
print(f"Archive: {archives[-1].split('/')[-1]}")
print(f"unix_timestamp (RTP-derived): {npz['unix_timestamp']}")
if 'ntp_wall_clock_time' in npz.files:
    print(f"ntp_wall_clock_time (independent): {npz['ntp_wall_clock_time']}")
    print(f"ntp_offset_ms: {npz.get('ntp_offset_ms', 'N/A')}")
    print("✅ New format with independent NTP reference!")
else:
    print("❌ Old format - need new archives")
EOF

# Monitor drift measurements
tail -f /tmp/grape-test/analytics/WWV_10_MHz/timing/*_timing_metrics_*.csv | \
  awk -F',' '{printf "%s | Drift: %8s ms | Jitter: %8s ms\n", substr($1,12,8), $10, $11}'
```

### Expected Results

**With New Archives:**
```
Drift: ±5-50 ms     # Realistic ADC vs NTP measurement
Jitter: ±2-20 ms    # RMS variation
Quality: TONE_LOCKED or INTERPOLATED
```

**Interpretation:**
- Drift shows ADC clock stability
- Positive = ADC slow, Negative = ADC fast
- Jitter shows short-term stability
- Tone-to-tone provides definitive characterization

---

## 🎓 Key Lessons

### 1. Two Independent Time Bases Required
- Can't measure drift within a single time basis
- Need ADC clock AND independent reference (NTP)

### 2. Store Independent Reference
- `unix_timestamp` is RTP-derived (circular)
- `ntp_wall_clock_time` is independent (correct)

### 3. Works Across Sessions
- Archive's embedded time_snap + NTP time
- Independent of core recorder restarts
- Works for historical analysis

### 4. NTP Quality Matters
- With NTP: ±10ms drift measurement precision
- Without NTP: ±seconds (unreliable)
- Tone-to-tone bypasses NTP entirely (best)

---

## 🙏 Credit

**Key insight from user:**

> "The WWV/CHU time-snap is the gold standard for our data's time base. The confusion arises from the distinction between the local clock drift (what the WWV/CHU tone measures) and the network packet handling (which is subject to jitter)."

This clarified:
- Two independent time bases exist
- Drift is measured BETWEEN them, not within
- NTP wall clock must be stored independently
- Time basis transitions happen during tone loss

**Result:** Proper ADC clock characterization with independent reference!
