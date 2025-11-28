# Differential Delay Detection Logic

## Valid Measurement Criteria

For WWV/WWVH differential delay to be valid, both tones must be **simultaneous** (transmitted on the same second).

### Tone Duration Windows:
- **WWV/WWVH**: 800ms tone duration
- **CHU**: 500ms tone duration

### Detection Logic:
```python
# Both tones detected
peak_1000 = correlation_peak_for_1000Hz_tone
peak_1200 = correlation_peak_for_1200Hz_tone

time_diff_ms = abs(peak_1200 - peak_1000) / sample_rate * 1000

# Check if within tone duration (simultaneous transmission)
if time_diff_ms < 800ms:  # WWV/WWVH
    # VALID: Both tones from same second
    differential_delay_ms = (peak_1200 - peak_1000) / sample_rate * 1000
else:
    # INVALID: Tones from different seconds
    differential_delay_ms = 0.0
```

## Examples

### Valid (Simultaneous):
```
1000 Hz peak at sample 100000 → 6.250s
1200 Hz peak at sample 100160 → 6.260s
Difference: 160 samples = 10ms

10ms < 800ms ✅ Valid simultaneous detection
Differential delay = +10ms (WWVH 10ms after WWV)
```

### Invalid (Different Seconds):
```
1000 Hz peak at sample 830895 → 51.93s
1200 Hz peak at sample 917984 → 57.37s  
Difference: 87089 samples = 5443ms

5443ms > 800ms ❌ Different second marks
Differential delay = 0.0 (no valid measurement)
```

## Interpretation

### When differential_delay_ms ≠ 0:
- **Positive** (+1 to +100ms): WWVH arrives after WWV
  - Typical for continental US (WWVH farther from most receivers)
  - Larger values indicate longer propagation path difference
  
- **Negative** (-1 to -100ms): WWVH arrives before WWV
  - Unusual but possible for receivers closer to Hawaii
  - Or unusual ionospheric propagation

### When differential_delay_ms = 0:
- No simultaneous transmission detected
- Could be alternating seconds (WWV only or WWVH only)
- Or only one station detected
- Or CHU channel (no WWVH)

## Startup vs Analytics

### Startup Detector (120-second buffer):
- Finds strongest peaks across entire buffer
- Often from **different** second marks
- Usually results in `differential_delay_ms = 0.0`
- Still provides valuable tone power measurements

### Analytics Detector (per minute):
- Looks for tones at **specific** minute boundary (:00.0)
- When both WWV & WWVH transmit on same second → valid differential delay
- Tracks propagation changes over time
- More likely to find simultaneous transmissions

## Physical Constraints

Valid differential delay must satisfy:
```
|differential_delay_ms| < 200ms
```

Why? Maximum propagation difference:
- WWV (Fort Collins) to receiver: ~0-10ms
- WWVH (Hawaii) to receiver: ~0-30ms
- Typical difference: 1-100ms
- Extreme difference: <200ms

Anything larger indicates detection from different seconds.
