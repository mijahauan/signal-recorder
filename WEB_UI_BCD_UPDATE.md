# Web UI Update for BCD Discrimination Visualization

## Summary

Updated `discrimination.html` and `discrimination.js` to visualize the new BCD discrimination time-series data, expanding from 5 panels to **7 panels** with two new BCD-specific visualizations.

## Changes to `discrimination.html`

### 1. Added BCD Info Card
New info card explaining the 100 Hz BCD discrimination method:
- **Matched filtering:** 15-second sliding windows
- **Integration:** 3000× longer than 5ms ticks  
- **Time resolution:** ~45 measurements/minute (1-second steps)
- **Purpose:** High SNR + captures ionospheric coherence time (Tc)

### 2. Updated Placeholder Text
Changed from "5 analysis panels" to "7 analysis panels" with new descriptions:
- **Panel 6:** 100 Hz BCD amplitude time series
- **Panel 7:** 100 Hz BCD differential delay

### 3. Updated Legend
Changed title from "Five-Panel Analysis Guide" to "Seven-Panel Analysis Guide" and added two new legend items:

**Panel 6: 100 Hz BCD Amplitude**
- Time-series of WWV (green) vs WWVH (red) correlation peak amplitudes
- 15-second sliding windows with 1-second steps → ~45 data points/minute
- Matched filtering provides massive SNR gain (15s integration)
- Observes rapid fading, TIDs, selective fading within ionospheric coherence time
- No carrier separation needed - works on 100 Hz only!

**Panel 7: BCD Differential Delay**
- Time-of-arrival (TOA) difference between WWV and WWVH (milliseconds)
- Derived from peak separation in BCD cross-correlation
- **Typical range:** 5-30ms (ionospheric path length difference)
- **Variations:** Track ionospheric height changes, multipath evolution
- High temporal resolution reveals rapid propagation mode transitions

## Changes to `discrimination.js`

### 1. BCD Data Parsing (Lines 184-209)
Added parsing for `bcd_windows` JSON field, similar to `tick_windows_10sec`:

```javascript
const bcdTimestamps = [], bcdWwvAmplitude = [], bcdWwvhAmplitude = [];
const bcdDifferentialDelay = [], bcdCorrelationQuality = [];

filteredData.forEach((d, i) => {
    if (d.bcd_windows) {
        const windows = Array.isArray(d.bcd_windows) ? 
            d.bcd_windows : JSON.parse(d.bcd_windows);
        windows.forEach(win => {
            // Extract timestamp and metrics for each window
            // ~45 windows per minute
        });
    }
});
```

### 2. New Plot Traces (Lines 499-543)
Added 3 new traces for BCD visualization:

**Panel 6 Traces:**
- WWV BCD Amplitude (green line+markers)
- WWVH BCD Amplitude (red line+markers)

**Panel 7 Trace:**
- BCD Differential Delay (purple line+markers with color-coded quality)
- Markers colored by correlation quality (Viridis colorscale)
- Quality colorbar displayed on right side

### 3. Updated Layout (Lines 563-656)
Redistributed vertical space for 7 panels:

| Panel | Domain | Height | Content |
|-------|--------|--------|---------|
| 1 - SNR Ratio | [0.88, 1.0] | 12% | WWV vs WWVH SNR comparison |
| 2 - 440 Hz | [0.76, 0.86] | 10% | Station ID tones |
| 3 - Power Ratio | [0.62, 0.74] | 12% | Relative signal strength |
| 4 - Dominance | [0.48, 0.60] | 12% | Station dominance timeline |
| 5 - Ticks | [0.32, 0.46] | 14% | 5ms tick discrimination |
| 6 - BCD Amp | [0.16, 0.30] | 14% | **NEW: BCD amplitudes** |
| 7 - BCD Delay | [0.0, 0.14] | 14% | **NEW: BCD TOA delay** |

Added axes:
- `xaxis6/yaxis6` for BCD amplitude panel
- `xaxis7/yaxis7` for BCD delay panel (shows time labels)

### 4. Plot Height
Increased from 1400px to **1800px** to accommodate 2 additional panels.

## Data Flow

```
CSV row with bcd_windows field
  ↓
API parses JSON array (~45 objects per minute)
  ↓
JavaScript extracts arrays:
  - bcdTimestamps (window start times)
  - bcdWwvAmplitude (WWV peak heights)
  - bcdWwvhAmplitude (WWVH peak heights)  
  - bcdDifferentialDelay (TOA difference in ms)
  - bcdCorrelationQuality (peak-to-noise ratio)
  ↓
Plotly renders:
  Panel 6: Amplitude time-series (green vs red)
  Panel 7: Delay with quality-colored markers
```

## Expected Visualization Benefits

### Panel 6 (BCD Amplitude)
- **Rapid fading events:** See amplitude fluctuations over 1-second intervals
- **Rayleigh fading:** Observe statistical amplitude distribution
- **Selective fading:** WWV and WWVH fade independently
- **TIDs:** Traveling Ionospheric Disturbances show as periodic oscillations
- **Dawn/dusk:** Rapid transitions visible

### Panel 7 (BCD Differential Delay)
- **Ionospheric height:** TOA changes with virtual height
- **Multipath evolution:** Delay spread and mode transitions
- **Coherence quality:** Color-coded markers show measurement confidence
- **Propagation mode changes:** E-layer vs F-layer transitions
- **Typical range:** 5-30ms corresponds to ~1500-9000 km path difference

## User Interaction

**Hover tooltips:**
- Panel 6: Shows WWV/WWVH amplitude values and precise timestamp
- Panel 7: Shows delay (ms), quality metric, and timestamp

**Legend toggle:**
- Click legend items to show/hide traces
- Particularly useful for comparing WWV vs WWVH amplitude evolution

**Zoom/Pan:**
- Standard Plotly controls work across all 7 panels
- Synchronized time axis for correlation analysis

## Testing

After reprocessing data with BCD fields populated:
1. Load discrimination.html in browser
2. Select a date and channel
3. Verify 7 panels render correctly
4. Check that panels 6 and 7 show BCD time-series data
5. Hover over BCD data points to verify tooltips
6. Look for correlation between BCD amplitude variations and tick SNR

## Performance Notes

- **~45 data points/minute** = ~2,700 points/hour = ~65,000 points/day
- Plotly handles this efficiently with markers+lines mode
- WebGL mode not needed unless displaying multiple days simultaneously
- JSON parsing happens once per page load (client-side)

## Files Modified

- `web-ui/discrimination.html` - Added BCD descriptions and legends
- `web-ui/discrimination.js` - Added BCD parsing, traces, and layout axes
- Total additions: ~80 lines of JavaScript, ~40 lines of HTML

## Next Steps

1. **Reprocess historical data** - Run `./REPROCESS-DISCRIMINATION.sh` to populate bcd_windows
2. **Verify API** - Ensure server correctly returns bcd_windows as JSON array
3. **Browser test** - Hard refresh (Ctrl+Shift+R) to clear cache
4. **Validate data** - Check that ~45 BCD windows appear per minute
5. **Scientific analysis** - Use panels 6 and 7 to observe ionospheric coherence time effects
