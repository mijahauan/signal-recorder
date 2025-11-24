# WWV/WWVH Discrimination Philosophy and Methodology

## Core Principle: Confidence First, Granularity Second

**Fundamental Rule**: Temporal resolution is worthless without confident discrimination.

It is better to have **one high-confidence measurement per minute** than **twenty uncertain measurements per minute**.

---

## Operating Philosophy

### The Problem with Premature Optimization

Traditional signal processing often optimizes for temporal resolution:
- More windows per minute = better time resolution
- Shorter integration times = faster response
- Higher update rates = more data points

However, **this approach fails when signals are weak or ambiguous**:
- Short windows sacrifice SNR
- Rapid updates produce conflicting results
- Abundant low-confidence data overwhelms analysis
- Users cannot act on uncertain information

### The Correct Priority Order

```
1. DETECTION        Can we see a signal at all?
2. DISCRIMINATION   Can we tell WWV from WWVH?
3. CONFIDENCE       Are we sure about our answer?
4. GRANULARITY      How often can we update?
```

**Only proceed to the next level when the previous level is solidly established.**

---

## Physical Justification

### Ionospheric Time Constants

Propagation conditions change on scales of:
- **Seconds to minutes**: Rapid fading (Rayleigh/Rician)
- **Minutes to hours**: Ionospheric layer height/density
- **Hours to days**: Solar/geomagnetic conditions

**Key insight**: If discrimination works at minute-level, finer granularity adds little value because:
1. Station identification doesn't change second-to-second
2. Propagation paths are stable over minutes
3. Integration improves SNR more than temporal resolution helps analysis

### Signal-to-Noise Ratio Scaling

Integration time vs SNR improvement:
- **60 sec vs 10 sec**: √6 improvement ≈ **+3.9 dB**
- **60 sec vs 20 sec**: √3 improvement ≈ **+2.4 dB**
- **30 sec vs 10 sec**: √3 improvement ≈ **+2.4 dB**

**At weak signal levels (0-3 dB SNR)**, this difference determines success vs failure.

### Multi-Method Convergence

Three independent discrimination methods:
1. **Tick stacking**: Second-tick impulse coherence
2. **Tone analysis**: 1000/1200 Hz power ratios
3. **BCD correlation**: 100 Hz template matching

**When all three agree with high confidence**, we can trust the result.  
**When they disagree or show low confidence**, we need more integration time.

---

## Methodology: Discrimination-First Architecture

### Stage 1: Maximum Sensitivity (60-Second Windows)

**Goal**: Establish confident discrimination under all conditions

**Configuration**:
- **BCD correlation window**: 60 seconds (full minute)
- **Tick stacking**: 60 seconds (all ticks in minute)
- **Tone analysis**: 60 seconds (per-minute power)
- **Update rate**: Once per minute

**Success Criteria**:
All three methods must:
- Detect a signal (not "NONE")
- Agree on dominant station (WWV, WWVH, or BALANCED)
- Achieve confidence > 0.7
- Maintain consistency over 5+ consecutive minutes

**When to stay at 60 seconds**:
- Initial startup (establishing baseline)
- Weak signals (SNR < 3 dB)
- Single-station scenarios (only one visible)
- Recent signal loss (degraded conditions)
- Methods disagree on discrimination

### Stage 2: Validation of Shorter Windows (Future: Adaptive)

**Goal**: Increase temporal granularity while maintaining discrimination

**Progression** (only when Stage 1 criteria met):
```
60 sec → Test 30 sec for 5 minutes
  ↓ Still confident?
30 sec → Test 20 sec for 5 minutes
  ↓ Still confident?
20 sec → Test 15 sec for 5 minutes
  ↓ Still confident?
15 sec → Test 10 sec for 5 minutes
  ↓ Maximum granularity achieved
```

**Immediate reversion to 60 sec if ANY**:
- Confidence drops below 0.5
- Any method fails to detect
- Methods disagree on station
- SNR drops below threshold
- Two consecutive uncertain measurements

### Stage 3: Continuous Monitoring (Future: State Machine)

**Goal**: Maintain optimal window size as conditions change

**State tracking**:
- Current window size
- Confidence history (last 10 minutes)
- Signal strength trends
- Method agreement statistics

**Adaptation rules**:
- Conditions improving → Test shorter window
- Conditions degrading → Revert to longer window
- Stable conditions → Maintain current window

---

## Discrimination Method Rankings

### By Sensitivity (Ability to Discriminate Weak Signals)

1. **Test Signal Detection** (Minutes 8/44)
   - Sensitivity: ⭐⭐⭐⭐⭐
   - Availability: 2 min/hour
   - Window: 60 seconds (full minute)
   - Unambiguous when detected

2. **440 Hz Station ID Tone** (Minutes 1-2)
   - Sensitivity: ⭐⭐⭐⭐½
   - Availability: 2 min/hour
   - Window: 60 seconds (full minute)
   - Direct station identification

3. **BCD 100 Hz Correlation**
   - Sensitivity: ⭐⭐⭐⭐ (with 60 sec) → ⭐⭐⭐ (with 10 sec)
   - Availability: Every minute
   - Window: **Variable** (currently 10 sec, implementing 60 sec)
   - Uses distinctive modulation pattern

4. **Geographic ToA Prediction**
   - Sensitivity: ⭐⭐⭐½
   - Availability: Every minute (with BCD)
   - Assists single-station discrimination
   - Context dependent (location, propagation)

5. **Tick Window Coherence**
   - Sensitivity: ⭐⭐⭐ (with 60 sec) → ⭐⭐ (with 10 sec)
   - Availability: Continuous
   - Window: **Variable** (currently 10 sec, implementing 60 sec)
   - Benefits from longer stacking

6. **1000/1200 Hz Power Ratio**
   - Sensitivity: ⭐⭐
   - Availability: Every minute
   - Window: 60 seconds (per-minute)
   - Least definitive (both stations transmit both)

### Priority Order for Discrimination

```
FOR EACH MINUTE:
  1. Check minute number
     - If min 8 or 44: Use Test Signal Detector (60 sec)
     - If min 1 or 2: Use 440 Hz Tone Detector (60 sec)
     
  2. Run comprehensive analysis with current window size:
     - BCD Correlation (60 sec baseline)
     - Tick Stacking (60 sec baseline)
     - Tone Power Ratio (always 60 sec)
     
  3. Apply Geographic ToA if single-peak detected
  
  4. Evaluate confidence across all methods
     - All agree + high confidence → Report result
     - Disagree or low confidence → Report UNCERTAIN
     
  5. Future: Adapt window size based on confidence history
```

---

## Implementation Phases

### Phase 1: Maximum Discrimination (This Session)

**Immediate changes**:
1. Set BCD correlation to 60-second windows
2. Set tick stacking to 60 seconds
3. Remove overlapping windows (one measurement per minute)
4. Document baseline performance

**Expected outcomes**:
- Higher confidence scores
- Better method agreement
- More definitive station identification
- Fewer "BALANCED" or "NONE" results

**Validation**:
- Monitor next test signal (00:08 UTC)
- Compare discrimination confidence vs. previous 10-sec windows
- Check if all three methods agree more consistently

### Phase 2: Adaptive Windowing (Next Session)

**After validating 60-second baseline**:
1. Implement confidence tracking state machine
2. Add automatic window size adjustment
3. Create progression logic (60→30→20→15→10)
4. Add reversion triggers (back to 60 when uncertain)

### Phase 3: Optimization and Monitoring (Future)

**Long-term refinement**:
1. Dashboard visualization of window size and confidence
2. Historical analysis of optimal windows by frequency/time
3. Machine learning for propagation prediction
4. Per-frequency adaptive parameters

---

## Design Rationale Summary

### Why 60 Seconds is the Baseline

1. **Full minute integration**:
   - Captures all second ticks (60 impulses)
   - Aligns with station modulation timing
   - Matches per-minute tone transmission
   - Natural boundary for BCD time code

2. **Maximum SNR improvement**:
   - Best possible integration gain
   - Critical for weak signal discrimination
   - Overcomes noise and interference

3. **Matches physics**:
   - Propagation stable over minute scales
   - Station doesn't change within minute
   - No useful information lost

4. **User-friendly**:
   - "WWV dominant this minute" is actionable
   - Clear temporal reference
   - Aligns with standard time service usage

### Why Not Start Shorter

**The case against 10-second windows as default**:
- Fragments the test signal (6 windows per minute, signal spans ~40 sec)
- Reduces tick coherence (only 10 impulses stacked)
- Lower SNR means more false negatives
- Creates conflicting measurements within same minute
- Forces user to reconcile contradictory results

**When 10-second windows make sense**:
- After establishing confident discrimination at 60 sec
- Strong signals (SNR > 10 dB)
- Studying rapid fading characteristics
- Research applications needing time resolution

---

## Success Metrics

### Discrimination Quality Indicators

**High-quality discrimination** (Stay at current window or try shorter):
- ✅ All methods detect a signal
- ✅ All methods agree on dominant station
- ✅ Confidence > 0.7 for 5+ consecutive minutes
- ✅ SNR > 6 dB
- ✅ Consistent with geographic ToA expectations

**Marginal discrimination** (Stay at current window):
- ⚠️ All methods detect but some uncertainty
- ⚠️ Confidence 0.5 - 0.7
- ⚠️ SNR 3 - 6 dB
- ⚠️ Occasional disagreements

**Poor discrimination** (Revert to longer window):
- ❌ Methods disagree on station
- ❌ Confidence < 0.5
- ❌ Frequent "NONE" or "BALANCED" results
- ❌ SNR < 3 dB
- ❌ High variability between measurements

### System Performance Goals

**Primary goal**: Confident discrimination
- Target: >90% of minutes with confidence >0.7
- Acceptable: >75% with confidence >0.5
- Unacceptable: <50% confident discrimination

**Secondary goal**: Temporal resolution
- Maximum granularity that maintains primary goal
- Adapt to propagation conditions
- Never sacrifice confidence for resolution

---

## Operational Guidelines

### For System Operators

**Normal operation**:
1. System starts in 60-second mode (maximum sensitivity)
2. Monitor confidence for first hour
3. If consistently high (>0.7), system may adapt to shorter windows
4. If confidence drops, system reverts to 60-second mode

**Troubleshooting low confidence**:
- Check if system is using 60-second windows (should be automatic)
- Verify signal is actually present (check spectrum/audio)
- Review propagation conditions (solar indices, time of day)
- Consider that both stations may be weak (true "BALANCED")

**Interpreting results**:
- High confidence + specific station = Trust it
- Low confidence + "BALANCED" = Both stations similar strength
- Low confidence + specific station = Uncertain, use caution
- "NONE" = No usable signal detected

### For Researchers

**Analyzing discrimination performance**:
- CSV contains window size used (future enhancement)
- Confidence scores indicate reliability
- Method agreement shows consistency
- Time-series reveals propagation patterns

**Comparing frequencies**:
- Different frequencies may need different windows
- Lower frequencies often need longer integration
- Daytime vs nighttime propagation varies by band

---

## Conclusion

This discrimination-first philosophy ensures:
- ✅ Reliable station identification
- ✅ High-confidence results users can trust
- ✅ Automatic adaptation to propagation conditions
- ✅ Efficient use of integration time
- ✅ Foundation for future enhancements

**The guiding principle**: Better to confidently say "I don't know" than to unreliably guess wrong.

---

**Document Version**: 1.0  
**Date**: 2025-11-23  
**Author**: WWV/WWVH Discrimination System  
**Next Review**: After Phase 1 validation (00:08 UTC test signal)
