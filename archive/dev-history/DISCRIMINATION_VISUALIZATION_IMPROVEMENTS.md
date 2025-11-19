# Discrimination Visualization Improvements

**Date**: November 16, 2025  
**Purpose**: Enhanced WWV/WWVH discrimination plots to better expose propagation trends

## Problem

The discrimination graphs showed "very random" patterns, making it difficult to identify:
- Underlying propagation trends
- Diurnal patterns (day/night changes)
- Which station is dominant over time
- Long-term ionospheric conditions

## Root Cause

**The randomness is REAL data** - it represents:
- Signal fading (multipath interference)
- Short-term ionospheric disturbances
- Measurement noise in weak signal conditions

However, without smoothing, the underlying **trends were hidden** in the noise.

## Solutions Implemented

### 1. **10-Minute Moving Average Overlay**

**What**: Smoothed trend lines overlaid on raw data points

**Implementation**:
- Raw data: Small semi-transparent markers (opacity 0.4)
- Smoothed: Bold lines (width 3) with full opacity
- Window: 10-minute centered moving average

**Benefits**:
- Reveals hourly and diurnal trends
- Shows propagation stability
- Raw data still visible for detailed inspection

**Code**:
```javascript
function movingAverage(data, windowSize) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        const start = Math.max(0, i - Math.floor(windowSize / 2));
        const end = Math.min(data.length, i + Math.floor(windowSize / 2) + 1);
        const window = data.slice(start, end).filter(v => v !== null && v !== undefined);
        result.push(window.length > 0 ? window.reduce((a,b) => a+b) / window.length : null);
    }
    return result;
}
```

### 2. **Color-Coded Power Ratio**

**What**: Power ratio markers colored by dominance

**Color Scale**:
- 🟢 Green (+20 to 0 dB): WWV dominant
- ⚪ Gray (0 dB): Balanced
- 🔴 Red (0 to -20 dB): WWVH dominant

**Benefits**:
- Instant visual identification of dominant station
- Easy to spot propagation mode changes
- Reveals frequency-dependent propagation patterns

**Implementation**:
```javascript
marker: {
    color: powerRatio,
    colorscale: [
        [0, '#ef4444'],      // Red = WWVH dominant
        [0.5, '#94a3b8'],    // Gray = balanced
        [1, '#10b981']       // Green = WWV dominant
    ],
    cmin: -20, cmax: 20
}
```

### 3. **Enhanced All Panels**

Applied smoothing to all three quantitative panels:
- **Panel 1**: SNR comparison (WWV vs WWVH)
- **Panel 2**: Power ratio with color coding
- **Panel 3**: Differential delay (propagation path difference)
- **Panel 4**: 440 Hz detection (unchanged - discrete events)

## Scientific Interpretation

### What the Smoothed Lines Reveal

**SNR Trends** (Panel 1):
- Diurnal pattern: Daytime vs nighttime propagation
- Frequency-dependent fading: Different for WWV vs WWVH
- Propagation mode transitions: F-layer vs E-layer

**Power Ratio** (Panel 2):
- **Green dominant**: Short path (WWV closer or better conditions)
- **Red dominant**: Long path (WWVH via trans-Pacific)
- **Transitions**: Ionospheric mode changes (sunrise/sunset effects)

**Differential Delay** (Panel 3):
- **Positive**: WWV arrives later (longer path or lower ionosphere)
- **Negative**: WWVH arrives later (typical for most observers)
- **Magnitude**: Proportional to path length difference (ionospheric height × 2)

### Expected Patterns

**Typical Day** (for mid-latitude observer):
1. **Dawn**: Rapid changes as D-layer forms
2. **Day**: Stable, WWVH often dominant (F2-layer propagation)
3. **Dusk**: Transitions, mode mixing
4. **Night**: More variable, multipath, possible E-layer

**Geomagnetic Storm**:
- Rapid swings in power ratio
- Large differential delay variations
- Loss of detections (absorption)

## Usage Guide

### Reading the Enhanced Plots

**Look for**:
1. **Smooth trends** = Real propagation changes
2. **Scatter around trends** = Fading and multipath
3. **Color transitions** = Propagation mode changes
4. **Missing data gaps** = Signal too weak to detect

**Don't worry about**:
- Minute-to-minute variations (expected)
- Occasional outliers (measurement noise)
- Short gaps (normal for weak signals)

**Do investigate**:
- Large sustained trend changes
- Unusual color patterns
- Correlation with solar/geomagnetic indices

## Future Enhancements (Possible)

### 1. Time-of-Day Aggregation
- Group by hour of day
- Show average + std dev
- Reveal diurnal patterns over multiple days

### 2. Toggle Controls
- Switch between raw/smoothed/hourly views
- Adjust smoothing window size
- Filter by SNR threshold

### 3. Correlation Plots
- WWV SNR vs WWVH SNR
- SNR vs power ratio
- Reveal measurement relationships

### 4. Spectral Analysis
- FFT of power ratio time series
- Detect periodic variations (tidal effects?)
- Identify oscillation modes

## References

- NIST WWV/WWVH Documentation: https://www.nist.gov/time-distribution/radio-station-wwv
- Ionospheric Propagation: Davies, K. "Ionospheric Radio" (1990)
- HF Propagation Prediction: ITU-R P.533

## Files Modified

- `web-ui/discrimination.js`: Added moving average calculation and enhanced visualization
- `web-ui/discrimination.html`: No changes needed (uses external JS)

## Testing

Refresh browser and navigate to:
```
http://localhost:3000/discrimination.html
```

Select a channel and date with good data coverage to see the enhanced visualization.
