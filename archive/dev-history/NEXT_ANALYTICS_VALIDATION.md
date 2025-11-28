# Analytics Service Validation - Next Steps

**Context:** Core recorder bugs fixed, tone detection working, NPZ files contain proper time_snap metadata.

---

## Objective

Ensure the analytics service properly uses the new time_snap metadata from core recorder NPZ files for accurate UTC timestamp reconstruction and tone analysis.

---

## Critical NPZ Metadata Fields (Now Available)

### Time_snap Fields
```python
'time_snap_rtp'          # RTP timestamp at tone detection (anchor point)
'time_snap_utc'          # UTC timestamp at tone (seconds since epoch)
'time_snap_source'       # 'wwv_startup', 'chu_startup', 'ntp', or 'wall_clock'
'time_snap_confidence'   # 0.0-1.0 (tone detection typically 0.80-0.95)
'time_snap_station'      # 'WWV', 'WWVH', 'CHU', 'NTP', etc.
```

### Tone Power Fields (from startup detection)
```python
'tone_power_1000_hz_db'           # WWV tone power at startup
'tone_power_1200_hz_db'           # WWVH tone power at startup  
'wwvh_differential_delay_ms'      # Propagation delay between WWV/WWVH
```

### Gap Records
```python
'gaps_count'              # Number of gaps in this minute
'gaps_filled'             # Total samples filled with zeros
'gap_rtp_timestamps'      # Array of RTP timestamps where gaps occurred
'gap_sample_indices'      # Array of sample indices where gaps start
'gap_samples_filled'      # Array of samples filled per gap
'gap_packets_lost'        # Array of packets lost per gap
```

---

## Analytics Validation Checklist

### 1. NPZ Reading ✓ Test
**File:** `analytics_service.py` or equivalent  
**Test:**
```python
import numpy as np

npz = np.load('/tmp/grape-test/archives/WWV_15_MHz/20251124T151800Z_15000000_iq.npz')

# Verify all new fields present
assert 'time_snap_rtp' in npz
assert 'time_snap_utc' in npz
assert 'time_snap_source' in npz
assert 'tone_power_1000_hz_db' in npz

print(f"Source: {npz['time_snap_source']}")
print(f"Confidence: {npz['time_snap_confidence']}")
print(f"UTC: {npz['time_snap_utc']}")
```

### 2. UTC Reconstruction ⚠️ Critical
**Current Issue:** Analytics may still be using old timing method  
**Correct Method:**
```python
# Use time_snap as anchor point
time_snap_rtp = npz['time_snap_rtp']
time_snap_utc = npz['time_snap_utc']
sample_rate = npz['sample_rate']
rtp_timestamp = npz['rtp_timestamp']  # RTP at start of this minute

# Calculate UTC for any sample
def rtp_to_utc(rtp_ts, sample_index=0):
    """Convert RTP timestamp to UTC using time_snap anchor"""
    rtp_at_sample = rtp_ts + sample_index
    samples_from_anchor = rtp_at_sample - time_snap_rtp
    seconds_from_anchor = samples_from_anchor / sample_rate
    return time_snap_utc + seconds_from_anchor

# Example: UTC at start of minute
utc_start = rtp_to_utc(rtp_timestamp, 0)
```

### 3. Gap Handling 🔍 Verify
**Check:** Does analytics skip or handle gap-filled regions?  
```python
if npz['gaps_count'] > 0:
    gap_indices = npz['gap_sample_indices']
    gap_samples = npz['gap_samples_filled']
    
    # Analytics should:
    # 1. Skip these regions for tone detection, OR
    # 2. Mark them as invalid data, OR
    # 3. Use interpolation (with appropriate flags)
    
    for i, (idx, count) in enumerate(zip(gap_indices, gap_samples)):
        print(f"Gap {i}: samples {idx} to {idx+count} (filled with zeros)")
```

### 4. Tone Detection Comparison 🔬 Validate
**Purpose:** Verify core recorder's startup detection matches analytics' full detection  

```python
# Core recorder's startup detection (from NPZ metadata)
startup_tone_1000 = npz['tone_power_1000_hz_db']
startup_tone_1200 = npz['tone_power_1200_hz_db']
startup_confidence = npz['time_snap_confidence']

# Analytics performs full tone detection on the minute
analytics_result = detect_tones(npz['iq'], sample_rate=16000)

# Compare results
print(f"Startup 1000Hz: {startup_tone_1000:.1f} dB")
print(f"Analytics 1000Hz: {analytics_result['1000_hz_db']:.1f} dB")
print(f"Difference: {abs(startup_tone_1000 - analytics_result['1000_hz_db']):.1f} dB")

# Expect: < 3 dB difference (noise/timing variations acceptable)
assert abs(startup_tone_1000 - analytics_result['1000_hz_db']) < 3.0
```

### 5. Differential Delay Usage 🌍 Geographic
**Purpose:** Use WWVH differential delay for station location verification

```python
diff_delay_ms = npz['wwvh_differential_delay_ms']

if abs(diff_delay_ms) > 0.1:  # Valid measurement
    print(f"WWVH differential delay: {diff_delay_ms:+.2f} ms")
    
    # Positive: WWVH arrives later (western/central US)
    # Negative: WWV arrives later (Hawaii/Pacific)
    # Near zero: Equidistant or single station
    
    # Analytics can use this to:
    # 1. Validate station location configuration
    # 2. Improve timing by selecting better reference
    # 3. Detect propagation anomalies
```

---

## Test Files Available

Recent NPZ files with valid time_snap:
```
/tmp/grape-test/archives/WWV_15_MHz/20251124T151800Z_15000000_iq.npz
/tmp/grape-test/archives/WWV_10_MHz/20251124T151900Z_10000000_iq.npz
/tmp/grape-test/archives/CHU_14.67_MHz/20251124T151900Z_14670000_iq.npz
```

**Characteristics:**
- Source: `wwv_startup` or `chu_startup` (tone-based)
- Confidence: 0.80-0.95
- UTC: Correct 2025-11-24 timestamps
- Tone powers: 11-48 dB SNR
- No gaps or minimal gaps

---

## Common Issues to Check

### Issue 1: Analytics Ignoring time_snap
**Symptom:** Analytics still using NTP or wall clock for timing  
**Fix:** Update analytics to read and use `time_snap_rtp` + `time_snap_utc`  
**Check:** Look for NTP client calls in analytics that should now be unnecessary

### Issue 2: Old NPZ Format Assumptions
**Symptom:** KeyError when reading new metadata fields  
**Fix:** Add backward compatibility or version detection  
```python
if 'time_snap_source' in npz:
    # New format with tone detection
    use_time_snap(npz)
else:
    # Old format, fall back to legacy method
    use_legacy_timing(npz)
```

### Issue 3: Tone Detection Duplication
**Symptom:** Analytics re-detecting tones already detected by core recorder  
**Optimization:** Use core recorder's detection for validation, not primary timing  
**Benefit:** Reduce computational load, faster processing

### Issue 4: Gap Regions Not Excluded
**Symptom:** False tone detections or anomalies in gap-filled regions  
**Fix:** Mask or skip gap regions before tone detection  
```python
mask = np.ones(len(iq), dtype=bool)
for idx, count in zip(gap_indices, gap_samples):
    mask[idx:idx+count] = False
    
clean_iq = iq[mask]  # Process only valid samples
```

---

## Expected Analytics Workflow

```
1. Read NPZ file
   ├─ Load IQ samples
   ├─ Load time_snap metadata
   └─ Load gap records
   
2. Reconstruct timing
   ├─ Use time_snap as anchor (±1ms precision)
   ├─ Calculate UTC for each sample
   └─ Validate against expected timing
   
3. Perform analysis
   ├─ Skip gap-filled regions
   ├─ Detect tones on valid data
   ├─ Compare with core recorder's startup detection
   └─ Calculate additional metrics
   
4. Generate results
   ├─ Tone detection quality metrics
   ├─ Timing precision measurements
   ├─ Propagation delay analysis
   └─ Station identification confidence
   
5. Write DRF files
   ├─ Use accurate UTC timestamps
   ├─ Include quality flags
   └─ Reference time_snap source in metadata
```

---

## Success Criteria

✅ Analytics reads all new NPZ metadata fields without errors  
✅ UTC reconstruction uses time_snap anchor (not NTP)  
✅ Timing precision matches core recorder (±1ms)  
✅ Tone detection results consistent between core/analytics (< 3dB difference)  
✅ Gap regions properly handled (skipped or flagged)  
✅ Differential delay used for validation/optimization  
✅ DRF output includes proper timing metadata  

---

## Files to Review

1. `analytics_service.py` - Main analytics processing
2. `tone_detector.py` - Full tone detection (compare with startup)
3. `npz_reader.py` or equivalent - NPZ loading logic
4. `drf_writer.py` - Output file generation
5. `time_utils.py` - Timing/UTC conversion utilities

---

## Test Command

```bash
# Process a recent NPZ file through analytics
venv/bin/python -m signal_recorder.analytics_service \
  --input /tmp/grape-test/archives/WWV_15_MHz/20251124T151800Z_15000000_iq.npz \
  --output /tmp/analytics-test/ \
  --verbose

# Check output for:
# - Correct UTC timestamps
# - Tone detection results
# - Time_snap source acknowledgment
# - No errors about missing fields
```

---

## Documentation to Update

After validation:
- [ ] Update `README.md` with new metadata fields
- [ ] Document analytics integration in `ARCHITECTURE.md`
- [ ] Add time_snap usage examples
- [ ] Update DRF format specification if needed

---

**Status:** Ready to begin analytics validation  
**Priority:** High - Ensures end-to-end timing accuracy  
**Owner:** Next phase of testing
