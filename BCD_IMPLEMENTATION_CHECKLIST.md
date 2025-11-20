# BCD Discrimination Implementation Checklist

## ✅ Completed Components

### 1. BCD Encoder (`wwv_bcd_encoder.py`)
- [x] Based on Phil Karn's wwvsim.c IRIG-H implementation
- [x] Little-endian BCD encoding (LSB first)
- [x] Correct field positions: year, minute, hour, day-of-year
- [x] Pulse width modulation: 800ms (marker), 500ms (1), 200ms (0)
- [x] HIGH/LOW amplitude envelope: -6 dB / -20 dB
- [x] 100 Hz sine wave modulation
- [x] Tested: generates 60-second template

### 2. Discrimination Method (`wwvh_discrimination.py`)
- [x] Sliding window correlation (15s windows, 1s steps)
- [x] AM demodulation + 0-150 Hz low-pass filter
- [x] Template generation using encoder
- [x] Peak detection (2 peaks separated by 5-30ms)
- [x] Amplitude extraction for WWV and WWVH
- [x] Differential delay measurement
- [x] Correlation quality metric
- [x] Time-series data output (~45 windows/minute)
- [x] Integration with analyze_minute_with_440hz

### 3. Data Model Updates
- [x] Added `bcd_wwv_amplitude` to DiscriminationResult
- [x] Added `bcd_wwvh_amplitude` to DiscriminationResult
- [x] Added `bcd_differential_delay_ms` to DiscriminationResult
- [x] Added `bcd_correlation_quality` to DiscriminationResult
- [x] Added `bcd_windows` (List[Dict]) for time-series

### 4. CSV Output (`reprocess_discrimination.py`)
- [x] Added 5 new columns to CSV header
- [x] Summary statistics: mean values
- [x] Time-series data: bcd_windows JSON array
- [x] JSON escaping for CSV compatibility
- [x] None-safe formatting

### 5. Web UI - HTML (`discrimination.html`)
- [x] Added BCD info card with description
- [x] Updated placeholder text (5 → 7 panels)
- [x] Updated legend title (Five → Seven panels)
- [x] Added Panel 6 legend (BCD Amplitude)
- [x] Added Panel 7 legend (BCD Differential Delay)
- [x] Color scheme consistency (green/red/purple)

### 6. Web UI - JavaScript (`discrimination.js`)
- [x] Parse bcd_windows JSON from CSV
- [x] Extract time-series arrays (~45 points/min)
- [x] Added BCD WWV amplitude trace
- [x] Added BCD WWVH amplitude trace
- [x] Added BCD differential delay trace
- [x] Quality-colored markers (Viridis colorscale)
- [x] Added xaxis6/yaxis6 (BCD amplitude)
- [x] Added xaxis7/yaxis7 (BCD delay)
- [x] Redistributed vertical space (7 panels)
- [x] Increased plot height (1400px → 1800px)
- [x] Hover tooltips with timestamps

### 7. Documentation
- [x] BCD_DISCRIMINATION_IMPLEMENTATION.md
- [x] SLIDING_WINDOW_BCD_SUMMARY.md
- [x] WEB_UI_BCD_UPDATE.md
- [x] This checklist

## 🔧 Testing & Verification Steps

### After Reprocessing
1. [ ] Run `./REPROCESS-DISCRIMINATION.sh` to populate BCD fields
2. [ ] Check CSV file has 5 new columns
3. [ ] Verify bcd_windows contains JSON arrays
4. [ ] Confirm ~45 windows per minute in bcd_windows

### Web UI Testing
1. [ ] Open discrimination.html in browser
2. [ ] Hard refresh (Ctrl+Shift+R) to clear cache
3. [ ] Select date and channel, click Load Data
4. [ ] Verify 7 panels render (height 1800px)
5. [ ] Check Panel 6 shows green/red BCD amplitude traces
6. [ ] Check Panel 7 shows purple delay trace with color-coded markers
7. [ ] Hover over BCD data points to verify tooltips
8. [ ] Verify ~45 data points per minute in panels 6 and 7

### Scientific Validation
1. [ ] Compare BCD vs tick-based discrimination results
2. [ ] Verify WWV/WWVH amplitude ratios are consistent
3. [ ] Check differential delay is in 5-30ms range
4. [ ] Look for correlation with ionospheric conditions
5. [ ] Observe rapid fading events in BCD amplitude
6. [ ] Verify coherence time visibility (1s resolution)

## 📊 Expected Results

### Panel 6 (BCD Amplitude)
- **WWV (green) and WWVH (red) lines** showing correlation peak amplitudes
- **~45 data points per minute** (1-second temporal resolution)
- **Amplitude variations** reflecting ionospheric fading
- **Typical range:** Depends on signal strength (could be 100-10000 units)

### Panel 7 (BCD Differential Delay)
- **Purple line with color-coded markers** (quality metric)
- **Delay range:** 5-30 milliseconds typical
- **Variations:** ±2-5 ms due to ionospheric height changes
- **Quality colorbar:** Higher values = better correlation

### Data Quality Indicators
- **Good data:** Smooth amplitude variations, consistent delay
- **Multipath:** Multiple peaks, erratic delay variations
- **Low SNR:** Missing windows, low quality values
- **Ionospheric disturbance:** Rapid amplitude fluctuations

## 🚀 Performance Expectations

### Processing Time
- **Per minute:** ~0.5-2 seconds (15 x 15s windows)
- **Full day (1440 minutes):** ~15-50 minutes
- **Depends on:** CPU, signal quality, number of valid windows

### Data Size
- **Per minute:** ~45 windows × 5 fields × 8 bytes ≈ 1.8 KB
- **Per day:** ~2.6 MB additional CSV data
- **Web UI:** ~65K data points/day (handles efficiently)

## 🎯 Success Criteria

1. ✅ **Code compiles** without errors
2. ⏳ **Reprocessing runs** to completion
3. ⏳ **CSV contains** bcd_windows JSON arrays
4. ⏳ **Web UI displays** 7 panels correctly
5. ⏳ **BCD data shows** ~45 points/minute
6. ⏳ **Differential delay** in 5-30ms range
7. ⏳ **Amplitude variations** correlate with ionospheric conditions

## 📝 Known Limitations

1. **Template accuracy** - Assumes DST bits, UT1 offsets are 0
2. **Peak assignment** - Assumes first peak = WWV (may vary)
3. **Two-station assumption** - Won't work if only one station present
4. **Window length fixed** - 15s may exceed Tc during severe scintillation
5. **Multipath handling** - Could create spurious peaks

## 🔬 Future Enhancements

1. **Adaptive window length** - Adjust based on observed coherence
2. **Phase analysis** - Add phase continuity metrics
3. **Confidence intervals** - Show uncertainty bars
4. **Spectrogram overlay** - Visual correlation quality
5. **Machine learning** - Automatic peak identification
6. **Multi-day comparison** - Long-term trend analysis

## 📚 References

- Phil Karn's wwvsim.c (ka9q-radio)
- NIST Special Publication 432
- IRIG-H time code specification
- Ionospheric coherence time literature
