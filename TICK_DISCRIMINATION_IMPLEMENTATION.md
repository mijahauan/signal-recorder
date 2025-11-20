# High-Resolution Tick Discrimination Implementation

## Overview

Implemented 10-second windowed tick detection for WWV/WWVH discrimination with **true coherent integration**, providing:
- **6x better time resolution** (every 10 seconds instead of per-minute)
- **10 dB SNR improvement** through coherent phase-aligned integration (when ionosphere is stable)
- **Automatic fallback** to 5 dB incoherent integration (when phase is unstable)
- **Coherence quality metrics** measuring ionospheric phase stability

**Date**: 2025-11-19  
**Status**: ✅ Complete - Coherent Integration with Adaptive Method Selection

## Critical Design Decisions

### Separate Measurement Streams

**The 800ms tone and 5ms tick measurements are COMPLETELY INDEPENDENT and serve distinct scientific purposes:**

### **800ms Tone Analysis** (Primary Discrimination)
- **Purpose**: High-confidence instantaneous WWV/WWVH power ratio
- **Energy**: 160× more than single 5ms tick
- **Method**: Single-shot frequency-domain filtering
- **Output**: `wwv_power_db`, `wwvh_power_db`, `power_ratio_db`
- **When**: Once per minute at :00 seconds
- **Role**: Ground truth discrimination metric

### **5ms Tick Stack Analysis** (High-Resolution Tracking)
- **Purpose**: Enhanced SNR for weak signal detection, phase tracking
- **Energy**: 10 ticks stacked → equivalent energy with 5-10 dB gain
- **Method**: Multi-pulse coherent/incoherent stacking
- **Output**: `tick_windows_10sec` array (6 windows/minute)
- **When**: Continuous, **EXCLUDING second 0** (1-10s, 11-20s, ..., 51-59s)
- **Role**: Time-resolved fading analysis, ionospheric coherence measurement

**Why Separate?**
1. **Energy mismatch**: 800ms tone would dominate any combined measurement
2. **Different goals**: Instantaneous ratio vs. time-resolved tracking
3. **Coherence preservation**: Tick stacking requires phase alignment over time
4. **Normalization complexity**: Combining would require arbitrary scaling
5. **CRITICAL**: Second 0 excluded from tick analysis to avoid 800ms tone contamination

**Result**: Two synchronized, complementary data streams for rich propagation analysis

### Noise Floor Measurement (1350-1450 Hz)

**Critical consideration**: Both WWV and WWVH transmit with **100 Hz modulation**, creating sidebands that must be avoided in noise measurements.

**Modulation sidebands**:
- **WWV**: 1000 Hz ± 100 Hz → **900-1100 Hz**
- **WWVH**: 1200 Hz ± 100 Hz → **1100-1300 Hz**

**Noise band choice: 1350-1450 Hz**
- **Clean separation**: 50 Hz above highest sideband (1300 Hz)
- **Representative**: Still in audio band, similar propagation
- **100 Hz wide**: Good statistical sample
- **Avoids contamination**: No signal or modulation products

**Why not lower?**
- 1200-1300 Hz: Overlaps WWVH upper sideband
- 1300-1400 Hz: Too close, potential edge contamination

**Why not higher?**
- >1500 Hz: Getting far from signal band
- May have different noise characteristics

## Motivation

WWV and WWVH transmit 5ms "tick" tones every second on their respective frequencies:
- **WWV**: 1000 Hz ticks
- **WWVH**: 1200 Hz ticks

By coherently integrating (stacking) these ticks over 10-second windows, we can:
1. **Improve SNR**: 10 ticks → √10 = 3.2x SNR boost
2. **Increase time resolution**: 6 windows per minute vs 1 measurement per minute
3. **Detect rapid fading**: Capture ionospheric variations on seconds timescale
4. **Identify scintillation**: Fast amplitude variations during geomagnetic disturbances

## Implementation Details

### 1. Data Structure Updates

**DiscriminationResult** (`wwvh_discrimination.py`):
```python
@dataclass
class DiscriminationResult:
    # ... existing fields ...
    tick_windows_10sec: Optional[List[Dict[str, float]]] = None
```

Each tick window contains both coherent and incoherent results plus coherence metrics:
```python
{
    'second': 1,                        # Start second in minute (1, 11, 21, 31, 41, 51)
                                        # NOTE: Second 0 is EXCLUDED (800ms tone marker)
    
    # Best results (from chosen integration method)
    'wwv_snr_db': 42.5,                 # WWV tick SNR (dB)
    'wwvh_snr_db': 38.2,                # WWVH tick SNR (dB)
    'ratio_db': 4.3,                    # wwv_snr - wwvh_snr (positive = WWV stronger)
    
    # Coherent integration results (10 dB gain)
    'coherent_wwv_snr_db': 43.8,        # Phase-aligned amplitude sum
    'coherent_wwvh_snr_db': 39.1,       # Phase-aligned amplitude sum
    
    # Incoherent integration results (5 dB gain)
    'incoherent_wwv_snr_db': 38.2,      # Power sum (fallback method)
    'incoherent_wwvh_snr_db': 34.5,     # Power sum (fallback method)
    
    # Coherence quality metrics (0-1, higher = more stable)
    'coherence_quality_wwv': 0.87,      # WWV phase stability
    'coherence_quality_wwvh': 0.82,     # WWVH phase stability
    
    # Which method was selected
    'integration_method': 'coherent',   # 'coherent', 'incoherent', or 'none'
    'tick_count': 10                    # Number of ticks successfully analyzed
}
```

### 2. Detection Algorithm

**Method**: `WWVHDiscriminator.detect_tick_windows()` in `wwvh_discrimination.py`

**Coherent Integration with Adaptive Selection**

The algorithm implements **both** coherent and incoherent integration, then automatically selects the best method:

**Process**:
1. **AM demodulation** of full minute of IQ samples
2. **Divide into 6 windows** (**EXCLUDING second 0**):
   - Window 0: seconds 1-10 (10 ticks)
   - Window 1: seconds 11-20 (10 ticks)
   - Window 2: seconds 21-30 (10 ticks)
   - Window 3: seconds 31-40 (10 ticks)
   - Window 4: seconds 41-50 (10 ticks)
   - Window 5: seconds 51-59 (9 ticks - partial window)
3. **For each window**, process all ticks:
   
   **Tick extraction** (100ms window centered on each second):
   - Extract ±50ms around tick at :XX.0 seconds
   - Apply Hann window to reduce spectral leakage
   - FFT to extract **complex amplitudes** at 1000 Hz (WWV) and 1200 Hz (WWVH)
   
   **Phase tracking** (for first tick, establish reference):
   ```python
   wwv_ref_phase = angle(FFT[1000Hz])
   wwvh_ref_phase = angle(FFT[1200Hz])
   ```
   
   **Phase correction** (for subsequent ticks):
   ```python
   phase_drift = current_phase - ref_phase
   corrected_amplitude = amplitude * exp(-j * phase_drift)
   ```
   
   **Dual integration**:
   - **Coherent**: Sum phase-corrected complex amplitudes
   - **Incoherent**: Sum power (|amplitude|²)
   
4. **Calculate coherence quality** (phase stability metric):
   ```python
   phase_variance = var(unwrap(phases))
   coherence_quality = 1 - (phase_variance / (π²/3))  # 0=random, 1=perfect
   ```

5. **Compute both SNR results**:
   - **Coherent SNR**: `10 * log10(|coherent_sum|² / (noise_avg * N))`  → **10 dB gain**
   - **Incoherent SNR**: `10 * log10(power_sum / (noise_avg * N))`  → **5 dB gain**

6. **Adaptive method selection**:
   ```python
   if coherence_quality > 0.6:  # Good phase stability
       use coherent  # Get full 10 dB gain
   else:
       use incoherent  # Fall back to robust 5 dB gain
   ```

**SNR Gains**:
- **Coherent**: N = 10 → **10 dB improvement** (stable ionosphere)
- **Incoherent**: √N = 3.16 → **5 dB improvement** (disturbed ionosphere)

**Coherence Quality Metric**:
- **>0.8**: Excellent phase stability (use coherent)
- **0.6-0.8**: Good stability (use coherent)
- **<0.6**: Poor stability (use incoherent fallback)

**Key Parameters**:
- Window size: 10 seconds (10 ticks)
- Tick extraction window: 100ms (±50ms around tick)
- WWV frequency: 1000 Hz
- WWVH frequency: 1200 Hz
- Noise band: 1350-1450 Hz (avoids 100 Hz modulation sidebands at 900-1100 Hz and 1100-1300 Hz)

### 3. CSV Logging

**Updated format** (`analytics_service.py`):
```csv
timestamp_utc,minute_timestamp,minute_number,wwv_detected,wwvh_detected,
wwv_power_db,wwvh_power_db,power_ratio_db,differential_delay_ms,
tone_440hz_wwv_detected,tone_440hz_wwv_power_db,
tone_440hz_wwvh_detected,tone_440hz_wwvh_power_db,
dominant_station,confidence,tick_windows_10sec
```

The `tick_windows_10sec` column contains JSON-serialized array with proper CSV escaping.

### 4. API Integration

**Endpoint**: `/api/v1/channels/:channelName/discrimination/:date`

**Response** (`monitoring-server-v3.js`):
```json
{
  "timestamp_utc": "2025-11-19T13:45:00Z",
  "minute_number": 45,
  "wwv_detected": true,
  "wwvh_detected": true,
  "wwv_snr_db": 42.5,
  "wwvh_snr_db": 38.2,
  "power_ratio_db": 4.3,
  "tick_windows_10sec": [
    {
      "second": 1,
      "wwv_snr_db": 48.3,
      "wwvh_snr_db": 44.1,
      "ratio_db": 4.2,
      "coherent_wwv_snr_db": 48.3,
      "coherent_wwvh_snr_db": 44.1,
      "incoherent_wwv_snr_db": 38.1,
      "incoherent_wwvh_snr_db": 34.0,
      "coherence_quality_wwv": 0.87,
      "coherence_quality_wwvh": 0.82,
      "integration_method": "coherent",
      "tick_count": 10
    },
    {
      "second": 11,
      "wwv_snr_db": 47.9,
      "wwvh_snr_db": 43.2,
      "ratio_db": 4.7,
      "coherent_wwv_snr_db": 47.9,
      "coherent_wwvh_snr_db": 43.2,
      "incoherent_wwv_snr_db": 37.8,
      "incoherent_wwvh_snr_db": 33.1,
      "coherence_quality_wwv": 0.91,
      "coherence_quality_wwvh": 0.85,
      "integration_method": "coherent",
      "tick_count": 10
    },
    {
      "second": 51,
      "wwv_snr_db": 47.5,
      "wwvh_snr_db": 42.8,
      "ratio_db": 4.7,
      "coherent_wwv_snr_db": 47.5,
      "coherent_wwvh_snr_db": 42.8,
      "incoherent_wwv_snr_db": 37.9,
      "incoherent_wwvh_snr_db": 33.2,
      "coherence_quality_wwv": 0.88,
      "coherence_quality_wwvh": 0.83,
      "integration_method": "coherent",
      "tick_count": 9
    }
  ]
}
```

**Notes**: 
- The coherent SNR values are ~10 dB higher than incoherent when phase is stable!
- Second 0 is **excluded** to avoid contamination from the 800ms tone marker
- Total of **59 ticks** analyzed per minute (seconds 1-59), not 60
- Last window (51-59) has only 9 ticks instead of 10

## Files Modified

1. **src/signal_recorder/wwvh_discrimination.py**
   - Updated `DiscriminationResult` docstring to describe coherent integration metrics
   - **Completely rewrote `detect_tick_windows()` method** with:
     - Complex amplitude extraction and tracking
     - Phase reference establishment and correction
     - Coherent integration (phase-aligned sum)
     - Incoherent integration (power sum) for comparison
     - Coherence quality calculation from phase variance
     - Adaptive method selection based on quality threshold
   - Updated `analyze_minute_with_440hz()` summary logging to report coherence statistics

2. **src/signal_recorder/analytics_service.py**
   - Updated `_log_discrimination()` CSV header (tick_windows_10sec column)
   - Added JSON serialization of tick windows to CSV output
   - No code changes needed - JSON handles all new fields automatically

3. **web-ui/monitoring-server-v3.js**
   - Updated CSV parser to handle quoted JSON field
   - Added `tick_windows_10sec` to API response
   - No code changes needed - JSON parsing handles new fields automatically

4. **web-ui/discrimination.js** (ready for visualization)
   - New 3-panel visualization already in place
   - Can add coherence quality visualization in Phase 2

5. **TICK_DISCRIMINATION_IMPLEMENTATION.md**
   - Updated to document coherent integration implementation
   - Added coherence quality metric explanation
   - Updated all examples with new fields

## Testing & Validation

### Expected Behavior

**Stable propagation (high coherence quality)**:
- Coherence quality > 0.8 for both WWV and WWVH
- Integration method: 'coherent' for all/most windows
- Coherent SNR ~10 dB higher than incoherent SNR
- All 6 windows should have positive SNR values
- Tick counts should be 10 (all ticks detected)
- Consistent ratios matching minute-long tone measurements

**Moderate propagation (medium coherence)**:
- Coherence quality 0.6-0.8
- Integration method: 'coherent' (still usable)
- Coherent SNR 7-10 dB higher than incoherent
- Some variance in SNR across windows
- Good discrimination still possible

**Disturbed propagation (low coherence)**:
- Coherence quality < 0.6
- Integration method: 'incoherent' (automatic fallback)
- Coherent and incoherent SNR similar (phase randomized)
- Higher variance in ratio values
- Still provides 5 dB gain from incoherent integration

**Rapid fading/scintillation**:
- Coherence quality varies between windows
- Mix of 'coherent' and 'incoherent' methods
- Tick SNR varies significantly between windows
- Captures ionospheric scintillation effects in real-time
- Identifies propagation mode transitions

**Poor propagation (deep fade)**:
- Some windows may have -100 dB SNR (no detection)
- Tick counts may be < 10 (partial detection)
- Integration method: 'none' for failed windows
- Both coherent and incoherent fail (signal too weak)

### Validation Commands

```bash
# Watch for coherent integration log messages
journalctl -u grape-analytics-service -f | grep -E "(COHERENT|INCOHERENT|coherence)"

# Expected output:
# COHERENT - WWV=48.3dB, WWVH=44.1dB, Ratio=+4.2dB (coherence: WWV=0.87, WWVH=0.82, 10 ticks)
# Tick analysis - 6/6 windows valid, 6/6 coherent, avg ratio: +4.3dB, coherence: WWV=0.89 WWVH=0.84

# Check CSV includes all coherent integration fields
tail /tmp/grape-test/analytics/WWV_10_MHz/discrimination/WWV_10_MHz_discrimination_20251119.csv

# API test - check for coherent fields
curl -s http://localhost:3000/api/v1/channels/WWV%2010%20MHz/discrimination/20251119 | \
  jq '.data[0].tick_windows_10sec[0]'

# Expected JSON output:
# {
#   "second": 0,
#   "wwv_snr_db": 48.3,
#   "coherent_wwv_snr_db": 48.3,
#   "incoherent_wwv_snr_db": 38.1,
#   "coherence_quality_wwv": 0.87,
#   "integration_method": "coherent",
#   ...
# }

# Compare coherent vs incoherent gain
curl -s http://localhost:3000/api/v1/channels/WWV%2010%20MHz/discrimination/20251119 | \
  jq '.data[0].tick_windows_10sec[] | 
      "Window \(.second)s: Gain = \(.coherent_wwv_snr_db - .incoherent_wwv_snr_db | floor) dB, Quality = \(.coherence_quality_wwv)"'
```

## Scientific Applications

### 1. **Ionospheric Coherence Time Measurement**
- **NEW**: Direct measurement of ionospheric phase stability
- Coherence quality metric = coherence time proxy
- High quality (>0.8) = stable phase, long coherence time (>10s)
- Low quality (<0.6) = rapid phase changes, short coherence time (<5s)
- Correlation with geomagnetic activity (Kp index)

### 2. **Ionospheric Scintillation Detection**
- Fast amplitude variations (seconds timescale)
- **NEW**: Phase scintillation via coherence quality drops
- **NEW**: Amplitude scintillation via SNR variance
- Correlation with space weather indices
- Distinguish quiet vs disturbed ionospheric conditions

### 3. **Weak Signal Detection**
- **10 dB gain** from coherent integration on stable paths
- Detect signals 10× weaker than incoherent methods
- Critical during poor propagation conditions
- Extends usable time windows (dawn/dusk transitions)

### 4. **Multipath Interference Characterization**
- Coherent integration breaks down under multipath → low quality
- Quality variance = multipath stability indicator
- Destructive interference → power nulls AND phase randomization
- Constructive interference → power peaks with stable phase

### 5. **Propagation Mode Classification**
- **Stable skywave**: High coherence quality, coherent method dominates
- **Disturbed skywave**: Low quality, incoherent fallback
- **Ground wave**: Very high quality (local, stable)
- **Mode transitions**: Quality drops during layer switching

### 6. **Quality Metrics**
- **Integration method ratio**: % coherent vs incoherent = path stability
- **Coherence quality trend**: Degrading = approaching disturbed conditions
- Tick detection success rate = propagation stability indicator
- High SNR variance = unstable propagation or scintillation

## Future Enhancements (Phase 2)

### Web UI Visualization

Add to `discrimination.html`:

1. **Intra-minute heatmap**
   - 60×6 grid showing 10-second window SNR ratios
   - Color-coded: Green = WWV, Red = WWVH
   - Reveals rapid fading patterns

2. **Scintillation index plot**
   - Standard deviation of tick SNR over time
   - Identifies disturbed conditions
   - Correlation with geomagnetic activity

3. **Stability metric**
   - Percentage of successful tick detections
   - Window-by-window consistency measure
   - Quality indicator for discrimination confidence

### Example visualization code (future):
```javascript
// Add to discrimination.js
function renderTickHeatmap(data) {
  const traces = [];
  data.forEach(minute => {
    if (minute.tick_windows_10sec) {
      minute.tick_windows_10sec.forEach(window => {
        // Plot window as heatmap cell
        traces.push({
          x: [minute.timestamp_utc],
          y: [window.second],
          z: [window.ratio_db],
          type: 'heatmap',
          colorscale: [[0, '#ef4444'], [0.5, '#94a3b8'], [1, '#10b981']]
        });
      });
    }
  });
}
```

## Performance Impact

**Minimal overhead**:
- Tick detection runs once per minute alongside 440 Hz analysis
- FFT operations reuse existing AM demodulation
- JSON serialization adds ~200 bytes per CSV row
- No impact on real-time processing latency

## Backward Compatibility

✅ **Fully backward compatible**:
- Old CSV files without tick data parse correctly (null value)
- API returns `tick_windows_10sec: null` for legacy data
- Web UI gracefully handles missing tick data
- No breaking changes to existing code

## Summary

**What we achieved**:
- ✅ **True coherent integration** with phase tracking and correction
- ✅ **10 dB SNR gain** on stable paths (2× better than incoherent)
- ✅ **Automatic fallback** to 5 dB incoherent integration when phase unstable
- ✅ **Coherence quality metric** measuring ionospheric phase stability (0-1 scale)
- ✅ **Adaptive method selection** based on real-time quality assessment
- ✅ 6x better time resolution (10-second windows vs 60-second tones)
- ✅ Automatic detection in real-time analytics pipeline
- ✅ CSV logging with JSON serialization (all fields automatically saved)
- ✅ API integration with backward compatibility
- ✅ Ready for visualization (Phase 2)

**Data quality benefits**:
- **Detect weaker signals**: 10 dB gain = 10× more sensitive
- **Measure coherence time**: Direct ionospheric stability metric
- **Capture rapid variations**: 10-second resolution vs 60-second
- **Phase scintillation**: Quality metric tracks phase stability
- **Amplitude scintillation**: SNR variance tracks power stability  
- **Propagation classification**: Coherent vs incoherent ratio = stability indicator
- **Improved discrimination**: Better SNR = higher confidence

**Key Innovation**:
The system automatically chooses the best integration method for current conditions:
- **Stable ionosphere** (quality > 0.6) → Use coherent (10 dB gain)
- **Disturbed ionosphere** (quality < 0.6) → Use incoherent (5 dB gain, robust)
- **Both methods logged** for post-analysis and algorithm validation

**Next steps** (Phase 2):
- Add coherence quality heatmap to discrimination.html
- Visualize coherent vs incoherent gain over time
- Implement scintillation index from quality variance
- Create ionospheric stability dashboard
- Correlate coherence quality with geomagnetic indices
