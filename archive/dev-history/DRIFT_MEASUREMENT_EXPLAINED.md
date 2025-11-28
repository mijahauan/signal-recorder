# RTP Drift Measurement - How It Works

## The Problem

We need to measure if the RTP clock is running at exactly 16000 Hz, or if it's drifting.

## Challenges

### Circular Reference Pitfall
❌ **Wrong:** Compare RTP-derived time to RTP-derived time
- If we calculate UTC from RTP using time_snap
- Then compare it back to RTP
- We get 0 drift (circular!)

### What We Need
✅ **Two independent time sources:**
1. RTP clock (what we're testing)
2. External reference (what we compare against)

## Current Implementation

### Method: RTP vs Wall Clock

```python
# time_snap provides anchor (from tone detection)
# at RTP=X, UTC=Y (tone-locked precision)

# Current measurement:
rtp_predicted_utc = Y + (current_rtp - X) / 16000

# Actual time:
wall_clock_utc = time.time()

# Drift:
drift = wall_clock_utc - rtp_predicted_utc
```

**Interpretation:**
- Positive drift: Wall clock ahead of RTP (RTP running slow)
- Negative drift: Wall clock behind RTP (RTP running fast)

**Limitations:**
- Includes wall clock jitter
- Wall clock itself may drift if NTP not synced
- Best for short-term monitoring

## Ideal Implementation (Future)

### Method: Tone-to-Tone

**Your proposed approach:**

```python
# time_snap A (tone detection at minute 0)
RTP_A = 1000000
UTC_A = 100.0  # From WWV tone

# time_snap B (tone detection at minute 5)  
RTP_B = 5760000
UTC_B = 400.0  # From WWV tone

# Expected samples based on tone times:
expected_samples = (UTC_B - UTC_A) * 16000
                 = 300.0 * 16000 = 4,800,000

# Actual samples:
actual_samples = RTP_B - RTP_A = 4,760,000

# Drift:
drift_samples = actual_samples - expected_samples = -40,000
drift_ms = (drift_samples / 16000) * 1000 = -2500 ms

# This shows RTP clock lost 40,000 samples over 5 minutes
# RTP running slow by 2.5 seconds
```

**Advantages:**
- Uses tone detections as ground truth
- No wall clock jitter
- Most accurate measurement
- Shows true RTP clock stability

**Requirements:**
- Need consecutive tone detections
- Happens every ~5 minutes
- Sparser data, but highest quality

## Why We're Seeing 0.000 Drift

### Possible Causes

1. **Circular calculation** (what we fixed)
   - Was comparing RTP-derived time to itself
   - Always showed 0.000

2. **Very stable system**
   - RTP clock + wall clock both stable
   - True drift is < 1ms
   - Possible, but unlikely to be perfect 0.000

3. **Measurement not working**
   - Need to verify wall clock is truly independent
   - Check that time.time() is being used correctly

## Verification Steps

### Check Current State

```bash
# See if we're getting non-zero drift now:
tail /tmp/grape-test/analytics/WWV_10_MHz/timing/*_timing_metrics_*.csv | \
  awk -F',' '{print "Drift: " $10 " ms, Jitter: " $11 " ms"}'
```

### Expected Results

With wall clock measurement:
- Drift: -50 to +50 ms (typical wall clock jitter with NTP)
- Jitter: 10-100 ms (variation in wall clock)

With tone-to-tone measurement:
- Drift: ±1 ms (very stable RTP clock)
- Jitter: < 5 ms (RTP clock stability)

## Recommendations

### Short Term (Current)
Keep wall clock measurement for:
- Real-time monitoring
- Detecting gross RTP failures
- Every-minute updates

### Long Term (Better)
Implement tone-to-tone measurement for:
- Definitive RTP clock characterization
- Scientific-grade timing analysis
- Validation of time_snap accuracy

### Implementation Plan

1. ✅ Fix circular reference (done)
2. ✅ Use wall clock as independent reference (done)
3. ⏳ **Add tone-to-tone measurement** (next step)
   - Track time_snap updates
   - Calculate drift between consecutive tones
   - Write to separate CSV: `timing_tone_to_tone.csv`
   - Update every ~5 minutes when fresh tones detected

## Summary

**Current:** Comparing RTP (via tone-locked time_snap) to wall clock
- Shows combined RTP + wall clock variation
- Good for real-time monitoring
- Updates every minute

**Ideal:** Comparing consecutive tone detections
- Shows pure RTP clock stability
- Ground truth measurement
- Updates every ~5 minutes

Both measurements are valuable for different purposes!
