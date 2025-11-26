# Timing Implementation Test Plan

## Date: 2025-11-26
## Goal: Verify new two-time-bases drift measurement implementation

---

## Test Objectives

1. ✅ Verify archives contain `ntp_wall_clock_time` (independent reference)
2. ✅ Verify drift measurements are realistic (not 0.000)
3. ✅ Verify tone-to-tone measurements work
4. ✅ Verify measurements work across RTP sessions
5. ✅ Verify quality classification is correct

---

## Test Procedure

### Phase 1: Initial Startup (0-5 minutes)

**Start Services:**
```bash
./start-dual-service.sh config/grape-config.toml
```

**Expected Behavior:**
- Core recorder starts receiving RTP packets
- Initial time_snap from NTP or startup tone
- Archives begin writing (1 per minute per channel)
- Analytics starts processing archives

**Monitor:**
```bash
# Watch for first archives
watch -n 2 'ls -lh /tmp/grape-test/archives/WWV_10_MHz/*.npz 2>/dev/null | tail -3'
```

**Success Criteria:**
- [ ] Archives appear within 2 minutes
- [ ] 9 channels recording (WWV 2.5, 5, 10, 15, 20, 25 MHz + CHU 3.33, 7.85, 14.67 MHz)

---

### Phase 2: Verify New Archive Format (5-7 minutes)

**Check Latest Archive:**
```bash
python3 << 'EOF'
import numpy as np
import glob

archives = sorted(glob.glob('/tmp/grape-test/archives/WWV_10_MHz/*.npz'))
if not archives:
    print("❌ No archives yet")
    exit(1)

npz = np.load(archives[-1])
print(f"Archive: {archives[-1].split('/')[-1]}")
print(f"\n=== Time References ===")
print(f"unix_timestamp (RTP-derived):     {npz['unix_timestamp']:.3f}")

if 'ntp_wall_clock_time' in npz.files:
    print(f"ntp_wall_clock_time (independent): {npz['ntp_wall_clock_time']:.3f}")
    print(f"ntp_offset_ms:                     {npz.get('ntp_offset_ms', 'N/A')}")
    
    # Calculate difference
    diff = npz['ntp_wall_clock_time'] - npz['unix_timestamp']
    print(f"\nDifference: {diff:.3f}s = {diff*1000:.1f}ms")
    print("\n✅ NEW FORMAT - Has independent NTP reference!")
else:
    print("\n❌ OLD FORMAT - Missing ntp_wall_clock_time")
    print("   (Need to wait for new archives from updated code)")

print(f"\n=== Embedded Time_Snap ===")
if 'time_snap_rtp' in npz.files:
    print(f"RTP:    {int(npz['time_snap_rtp']):,}")
    print(f"UTC:    {float(npz['time_snap_utc']):.1f}")
    print(f"Source: {str(npz['time_snap_source'])}")
    print(f"Conf:   {float(npz['time_snap_confidence']):.2f}")
else:
    print("No embedded time_snap")
EOF
```

**Success Criteria:**
- [ ] Archive contains `ntp_wall_clock_time`
- [ ] Archive contains `ntp_offset_ms`
- [ ] Archive contains embedded `time_snap_*` fields
- [ ] Difference between NTP and unix_timestamp is small (< 1 second)

---

### Phase 3: Verify Drift Measurements (7-10 minutes)

**Monitor Timing Metrics:**
```bash
# Wait for timing metrics to be written
sleep 120

# Check latest measurements
tail -5 /tmp/grape-test/analytics/WWV_10_MHz/timing/*_timing_metrics_*.csv | \
  awk -F',' 'BEGIN {
    printf "%-19s | %-15s | %12s | %12s | %6s\n", "Time", "Quality", "Drift (ms)", "Jitter (ms)", "Health"
  } {
    printf "%-19s | %-15s | %12s | %12s | %6s\n", substr($1,1,19), $4, $10, $11, $13
  }'
```

**Expected Results:**
- Drift: ±5-50 ms (realistic ADC vs NTP measurement)
- NOT 0.000 (unless extremely lucky)
- Quality: TONE_LOCKED, INTERPOLATED, or NTP_SYNCED
- Health: 70-95

**Success Criteria:**
- [ ] Drift measurements are non-zero
- [ ] Drift values are realistic (< 200ms)
- [ ] Jitter values are reasonable (< 100ms)
- [ ] Quality classification makes sense

---

### Phase 4: Verify Tone-to-Tone Measurements (10-15 minutes)

**Wait for Second Tone Detection:**
```bash
# Monitor logs for tone detections
tail -f /tmp/grape-test/logs/analytics-wwv10.log | grep -i "tone-to-tone"
```

**Expected:**
```
[INFO] Baseline tone established for A/D clock measurement
[INFO] Tone-to-tone A/D clock drift: +2.34 ppm (over 300.0s, 4800000 samples)
```

**Success Criteria:**
- [ ] First tone establishes baseline
- [ ] Second tone (5+ minutes later) calculates PPM drift
- [ ] PPM drift is realistic (±1-10 ppm for typical oscillator)

---

### Phase 5: Test Across RTP Session (15-20 minutes)

**Restart Core Recorder:**
```bash
# Stop core recorder only (not analytics)
pkill -f core_recorder
sleep 5

# Restart core recorder (new RTP session)
# Start command from start-dual-service.sh core recorder section
```

**Monitor Analytics:**
```bash
# Analytics should continue processing new archives
# Even though RTP session changed
tail -f /tmp/grape-test/logs/analytics-wwv10.log | grep -i "drift\|measurement"
```

**Success Criteria:**
- [ ] Analytics continues processing
- [ ] Drift measurements still work (using archive's embedded time_snap)
- [ ] No errors about RTP session mismatch
- [ ] Measurements remain realistic

---

## Success Metrics Summary

### Critical (Must Pass)
1. Archives contain `ntp_wall_clock_time` ✅
2. Drift measurements are non-zero ✅
3. Drift values are realistic (±5-200ms) ✅
4. Works across RTP sessions ✅

### Important (Should Pass)
5. Tone-to-tone measurements work ✅
6. Quality classification correct ✅
7. Jitter calculation reasonable ✅

### Nice-to-Have
8. Health scores make sense
9. UI displays correctly
10. No excessive warnings in logs

---

## Timeline

```
T+0:00   Start services (clean slate)
T+0:02   First archives appear
T+0:05   Verify archive format
T+0:07   First drift measurements
T+0:10   Monitor for stability
T+0:15   Second tone detection (if propagation good)
T+0:20   Test RTP session restart
T+0:25   Final verification

Total: ~25 minutes for complete test
```

---

## Rollback Plan

If tests fail:
1. Check logs for errors
2. Verify NTP is synchronized (`chronyc tracking`)
3. Check if time_snap is being established
4. Verify archives are being written
5. Fall back to previous version if critical failure

---

## Next Phase

After successful timing tests:
- **Core Recorder Thread Safety Improvements**
  - Add threading.Lock to ChannelProcessor
  - Protect shared state
  - Add RTP frequency verification
  - Improve NTP status integration
