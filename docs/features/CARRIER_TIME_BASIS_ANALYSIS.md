# Carrier Channel Time Basis Strategy

## Problem Statement

Narrow carrier channels (200 Hz bandwidth, ~98 Hz effective) need accurate timestamps for Doppler analysis but cannot use tone-based time_snap because they don't include the 1000 Hz/1200 Hz WWV tones.

**Requirements:**
- **Frequency resolution:** ±0.1 Hz Doppler shifts (ionospheric path variations)
- **Time resolution needed:** ~100ms (0.1 Hz = 1/10 second period)
- **Science goal:** Track smooth ionospheric Doppler variations over minutes/hours

## Option 1: NTP_SYNCED (Current Implementation)

### Description
Use system clock with NTP synchronization for carrier channel timestamps.

### Accuracy
- **Typical:** ±10-50ms (good NTP sync)
- **Best case:** ±1-10ms (local NTP server, good network)
- **Worst case:** ±100ms+ (poor network, high jitter)

### Advantages
✅ Simple implementation (already works)
✅ No dependency on wide channel
✅ Continuous operation (no gaps)
✅ Independent failure modes

### Disadvantages
❌ Lower accuracy than tone_snap (±10ms vs ±1ms)
❌ Network-dependent (NTP sync can degrade)
❌ No provenance link to GPS time standard

### Assessment
**Adequate for Doppler analysis** - ±10ms timing error produces <0.01 Hz frequency uncertainty, which is 10x better than our ±0.1 Hz measurement goal.

---

## Option 2: RTP Offset Correlation (Best Possible)

### Description
Channels tuned to the same frequency share the same hardware SDR receiver. Their RTP timestamps come from the same oscillator but have different starting offsets. Measure this offset and apply wide channel's time_snap to carrier channel.

### Theory
```
Wide channel:   RTP_wide, time_snap_wide (GPS_LOCKED ±1ms)
Carrier channel: RTP_carrier

Offset: RTP_carrier = RTP_wide + offset (constant for paired channels)

Carrier UTC: utc = time_snap_wide.utc + (RTP_carrier - time_snap_wide.rtp - offset) / sample_rate
```

### Accuracy
- **Theoretical:** ±1ms (inherits GPS_LOCKED from wide channel)
- **Practical:** ±1-5ms (depends on offset stability)

### Implementation Requirements

1. **Pair Detection**
   - Identify carrier/wide pairs by frequency
   - WWV 5 MHz → WWV 5 MHz carrier
   - CHU 3.33 MHz → CHU 3.33 MHz carrier

2. **Offset Measurement**
   - Collect simultaneous RTP timestamps from both channels
   - Calculate: offset = RTP_carrier - RTP_wide
   - Track stability over time (expect <100 sample variation)

3. **Offset Validation**
   - Monitor offset drift (should be <10 samples/hour)
   - Detect RTP clock resets (large jumps)
   - Fall back to NTP if offset unstable

4. **State Management**
   - Store offset in carrier channel state file
   - Update periodically (every 10 minutes)
   - Clear on service restart or large drift

### Advantages
✅ GPS-quality timing (±1ms) inherited from wide channel
✅ Scientific provenance (traceable to GPS via WWV tones)
✅ No network dependency (after time_snap established)
✅ Validates ka9q-radio architecture (same oscillator)

### Disadvantages
❌ Complex implementation (offset tracking, drift monitoring)
❌ Dependency on wide channel (single point of failure)
❌ Requires both channels recording simultaneously
❌ Offset may be unstable (needs validation testing)

### Open Questions

**Q1: Is the RTP offset actually stable?**
- **Test:** Monitor offset between WWV 5 MHz and WWV 5 MHz carrier over 24 hours
- **Expected:** <10 sample variation (0.625ms @ 16 kHz)
- **If unstable:** Offset correlation not viable

**Q2: Do paired channels share the same RTP clock?**
- **Evidence from logs:** RTP drift warnings suggest independent clocks per channel
- **Test:** Compare RTP sequences between paired channels
- **If independent:** Offset will drift significantly

**Q3: What happens during RTP clock reset?**
- **Known:** Each channel has independent RTP starting point
- **Unknown:** Do they reset together or independently?
- **Impact:** If independent resets, offset becomes invalid

---

## Option 3: Cross-Correlation Post-Processing

### Description
Use signal cross-correlation between carrier and wide channels to measure time offset after data collection.

### Accuracy
- **Theoretical:** Sub-millisecond (limited by sample rate)
- **Practical:** ±0.1-1ms (SNR dependent)

### Advantages
✅ Highest possible accuracy
✅ Works even if RTP clocks are independent
✅ Scientific gold standard for time alignment

### Disadvantages
❌ Post-processing only (not real-time)
❌ Computationally expensive
❌ Requires overlapping data (carrier must include 10 Hz carrier from wide)
❌ Complex implementation

### Assessment
**Research tool, not operational solution.** Better suited for validating other methods than for routine operation.

---

## Recommended Strategy: Hybrid Approach

### Phase 1: Immediate (Current)
**Use NTP_SYNCED** for carrier channels
- Adequate for ±0.1 Hz Doppler measurements
- Simple, reliable, working now
- Annotate timing quality clearly

### Phase 2: Experimental (1-2 weeks)
**Test RTP offset stability**
1. Implement offset measurement in analytics service
2. Log offset history for paired channels over 24-48 hours
3. Analyze drift characteristics:
   - Mean offset and standard deviation
   - Drift rate (samples/hour)
   - Reset behavior (if any)

### Phase 3: Decision Point
**If offset is stable (std < 10 samples):**
- Implement RTP correlation for GPS-quality timing
- Fall back to NTP if offset drifts
- Document as "TONE_LOCKED_INHERITED"

**If offset is unstable (std > 100 samples):**
- Continue with NTP_SYNCED
- Document RTP clocks as truly independent
- Consider cross-correlation for scientific papers

---

## Implementation: RTP Offset Tracker

### Data Structure
```python
@dataclass
class RTPOffsetTracker:
    """Track RTP offset between paired channels"""
    wide_channel_name: str
    carrier_channel_name: str
    frequency_hz: float
    
    # RTP offset: rtp_carrier = rtp_wide + offset
    measured_offset: Optional[int] = None
    offset_measurements: List[Tuple[float, int]] = field(default_factory=list)
    max_history: int = 100
    
    # Statistics
    offset_mean: Optional[float] = None
    offset_std: Optional[float] = None
    last_update: Optional[float] = None
```

### Measurement Algorithm
```python
def measure_offset(wide_npz: Path, carrier_npz: Path) -> Optional[int]:
    """
    Measure RTP offset between simultaneous archives
    
    Returns:
        RTP offset in samples, or None if not simultaneous
    """
    wide = np.load(wide_npz)
    carrier = np.load(carrier_npz)
    
    # Check if files are from same minute (simultaneous)
    if abs(wide['unix_timestamp'] - carrier['unix_timestamp']) > 60:
        return None
    
    # Calculate offset
    offset = carrier['rtp_timestamp'] - wide['rtp_timestamp']
    
    return offset
```

### Stability Criteria
```python
def is_offset_stable(tracker: RTPOffsetTracker) -> bool:
    """Check if offset is stable enough for use"""
    if len(tracker.offset_measurements) < 10:
        return False
    
    # Standard deviation should be < 10 samples (0.625ms @ 16 kHz)
    if tracker.offset_std > 10:
        return False
    
    # No large jumps in recent measurements
    recent = [o for _, o in tracker.offset_measurements[-10:]]
    if max(recent) - min(recent) > 100:
        return False
    
    return True
```

---

## Testing Protocol

### Step 1: Offset Collection (24 hours)
```bash
# Monitor offset between WWV 5 MHz and WWV 5 MHz carrier
cd /home/mjh/git/signal-recorder
python3 scripts/measure_rtp_offset.py \
  --wide-channel "WWV 5 MHz" \
  --carrier-channel "WWV 5 MHz carrier" \
  --duration 86400 \
  --output rtp_offset_analysis.csv
```

### Step 2: Analysis
```bash
# Generate statistics and plots
python3 scripts/analyze_rtp_offset.py \
  --input rtp_offset_analysis.csv \
  --plot rtp_offset_stability.png
```

### Step 3: Decision
- **Mean offset:** Expected ~2.7M samples (previous observation)
- **Std deviation:** Goal <10 samples (0.625ms)
- **Drift rate:** Goal <1 sample/hour
- **Resets:** Should be zero (or simultaneous)

---

## Timing Quality Levels

### TONE_LOCKED (±1ms)
Wide channels with successful WWV/CHU detection

### TONE_LOCKED_INHERITED (±1-5ms)
Carrier channels using stable RTP offset from paired wide channel

### NTP_SYNCED (±10ms)
- Carrier channels without stable offset
- Wide channels between tone detections (cold start)

### WALL_CLOCK (±seconds)
Fallback when NTP not synchronized

---

## Comparison Table

| Method | Accuracy | Complexity | Dependencies | Status |
|--------|----------|------------|--------------|--------|
| NTP_SYNCED | ±10ms | Low | Network | ✅ Working |
| RTP Correlation | ±1ms | Medium | Wide channel | 🧪 Experimental |
| Cross-Correlation | ±0.1ms | High | Post-processing | 🔬 Research |

---

## Recommendation

**Start with NTP_SYNCED, test RTP correlation in parallel.**

1. **Immediate:** Continue using NTP_SYNCED (adequate for science goals)
2. **Next session:** Implement RTP offset measurement script
3. **Week 1:** Collect 24-48 hours of offset data
4. **Week 2:** Analyze stability and make final decision

If RTP offset proves stable (std < 10 samples), upgrade to TONE_LOCKED_INHERITED for carrier channels. If unstable, document findings and continue with NTP_SYNCED.

---

## Files to Create

1. `scripts/measure_rtp_offset.py` - Offset measurement tool
2. `scripts/analyze_rtp_offset.py` - Statistical analysis
3. `src/signal_recorder/rtp_offset_tracker.py` - Runtime offset tracking
4. `docs/RTP_OFFSET_CORRELATION.md` - Full technical documentation
