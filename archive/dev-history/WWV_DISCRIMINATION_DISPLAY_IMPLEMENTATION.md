# WWV/WWVH Discrimination Display - Implementation Summary

**Date:** November 16, 2025  
**Status:** ✅ Complete

## Overview

Created a refined, dedicated web page for WWV/WWVH discrimination analysis that includes the 440 Hz tone analysis, which was missing from the previous display in `channels.html`.

## What Was Implemented

### 1. Enhanced API Endpoint (`monitoring-server.js`)

**Updated:** `/api/v1/channels/:channelName/discrimination/:date`

- **Backward Compatible:** Parses both old (10 field) and new (15 field) CSV formats
- **New Fields Added:**
  - `minute_number` (0-59)
  - `tone_440hz_wwv_detected` (boolean)
  - `tone_440hz_wwv_power_db` (float or null)
  - `tone_440hz_wwvh_detected` (boolean)
  - `tone_440hz_wwvh_power_db` (float or null)

**CSV Format (15 fields):**
```
timestamp_utc,minute_timestamp,minute_number,
wwv_detected,wwvh_detected,
wwv_power_db,wwvh_power_db,power_ratio_db,differential_delay_ms,
tone_440hz_wwv_detected,tone_440hz_wwv_power_db,
tone_440hz_wwvh_detected,tone_440hz_wwvh_power_db,
dominant_station,confidence
```

### 2. New Discrimination Page (`discrimination.html`)

**Location:** `/home/mjh/git/signal-recorder/web-ui/discrimination.html`

**Features:**
- Modern dark theme matching existing UI
- Responsive design (1600px max-width)
- Date and channel selector controls
- Real-time data loading with loading states
- Four-panel stacked Plotly visualization

**Navigation:**
- Summary → Carrier → **Discrimination** (NEW)
- Consistent across all pages

### 3. JavaScript Module (`discrimination.js`)

**Location:** `/home/mjh/git/signal-recorder/web-ui/discrimination.js`

**Key Functions:**
- `loadData()` - Fetches discrimination CSV data from API
- `renderDiscriminationPlots()` - Creates 4-panel Plotly visualization
- Automatic UTC time adjustment for display
- Statistics calculation (detection counts per station)

### 4. Four-Panel Visualization

**Panel Layout (1100px height total):**

#### Panel 1: SNR Comparison (Top 27%, 0.75-1.0)
- **WWV (1000 Hz):** Green line with circles
- **WWVH (1200 Hz):** Red dashed line with squares
- Shows signal strength over 24 hours
- Gaps = tone not detected (normal behavior)

#### Panel 2: Power Ratio (Middle-Top 23%, 0.50-0.72)
- **Power Ratio:** Purple line (WWV - WWVH in dB)
- Zero reference line (white dotted)
- Positive values = WWV dominant
- Negative values = WWVH dominant
- Near zero = balanced reception

#### Panel 3: Differential Delay (Middle-Bottom 23%, 0.25-0.47)
- **Delay:** Orange line (WWV - WWVH arrival time)
- Typically 100-300ms
- Only shown when BOTH tones detected
- Indicates ionospheric path differences

#### Panel 4: 440 Hz Station ID (Bottom 22%, 0.0-0.22)
- **WWV 440 Hz (minute 2):** Purple circles
- **WWVH 440 Hz (minute 1):** Cyan squares
- Confirms station identity
- Appears only in specific minutes (1 or 2)

### 5. Information Panels

**Educational Content:**
- Station descriptions (WWV Fort Collins, WWVH Kauai)
- Tone frequencies and timing
- Purpose of each analysis method
- Scientific context for discrimination

**Legend Panel:**
- Explains each of the 4 analysis panels
- Color-coded borders matching plot colors
- Interpretation guidance

### 6. Updated Navigation Links

**Modified Files:**
- `summary.html` - Added Discrimination link
- `carrier.html` - Standardized navigation format

### 7. Documentation Updates

**CONTEXT.md:**
- Updated "Web UI" section from "3 Screens + Next" to "4 Screens"
- Added discrimination.html description with 4-panel breakdown
- Updated data sources to mention 440 Hz data

## Key Design Decisions

### 1. Separate 440 Hz Panel
Dedicated panel (Panel 4) for 440 Hz detection instead of overlaying on SNR comparison. This makes it clear when station-specific ID tones are detected.

### 2. 4-Panel Layout
- More informative than previous 3-panel display
- Each panel has distinct scientific purpose
- Vertical stacking maintains time alignment

### 3. Color Scheme
- **WWV:** Green (#10b981) - primary timing reference
- **WWVH:** Red (#ef4444) - propagation study
- **Power Ratio:** Purple (#8b5cf6) - dominance indicator
- **Differential Delay:** Orange (#f59e0b) - ionospheric metric
- **440 Hz WWV:** Light purple (#a78bfa) - station ID
- **440 Hz WWVH:** Cyan (#22d3ee) - station ID

### 4. Statistics Display
Channel header shows real-time counts:
- WWV (1000 Hz) detections
- WWVH (1200 Hz) detections
- 440 Hz WWV detections (minute 2)
- 440 Hz WWVH detections (minute 1)

## Testing Recommendations

1. **Verify API Endpoint:**
   ```bash
   curl http://localhost:3000/api/v1/channels/WWV%2010%20MHz/discrimination/20251116
   ```

2. **Check CSV Parsing:**
   - Test with new 15-field format
   - Test with old 10-field format (backward compatibility)
   - Verify null handling for missing 440 Hz data

3. **Visual Inspection:**
   - Load discrimination page: http://localhost:3000/discrimination.html
   - Select date with known data
   - Select each channel (WWV 2.5, 5, 10, 15 MHz)
   - Verify all 4 panels render correctly
   - Check hover tooltips
   - Verify time range (00:00-23:59 UTC)

4. **Edge Cases:**
   - Date with no data
   - Date with only WWV detections
   - Date with only WWVH detections
   - Minutes without 440 Hz tones (minutes 0, 3-59)

## Files Modified

1. `/home/mjh/git/signal-recorder/web-ui/monitoring-server.js` - API endpoint enhancement
2. `/home/mjh/git/signal-recorder/web-ui/summary.html` - Navigation update
3. `/home/mjh/git/signal-recorder/web-ui/carrier.html` - Navigation update
4. `/home/mjh/git/signal-recorder/CONTEXT.md` - Documentation update

## Files Created

1. `/home/mjh/git/signal-recorder/web-ui/discrimination.html` - Main display page (13 KB)
2. `/home/mjh/git/signal-recorder/web-ui/discrimination.js` - Visualization logic (12 KB)
3. `/home/mjh/git/signal-recorder/WWV_DISCRIMINATION_DISPLAY_IMPLEMENTATION.md` - This document

## Scientific Value

### Enhanced Discrimination Analysis
1. **1000 Hz vs 1200 Hz comparison** - Basic station differentiation
2. **Power ratio** - Quantifies relative strength (dominance)
3. **Differential delay** - Measures ionospheric path differences
4. **440 Hz station ID** - Confirms identity when both stations received

### Research Applications
- Identify which station is being received at different times of day
- Study diurnal propagation patterns (WWV vs WWVH)
- Analyze ionospheric path variations via differential delay
- Correlate 440 Hz detection success with SNR levels
- Validate discrimination algorithms with independent 440 Hz check

## Next Steps (Optional Enhancements)

1. **Time-of-day analysis** - Aggregate statistics by hour
2. **Export functionality** - Download discrimination data as CSV
3. **Multi-channel comparison** - Side-by-side view of different frequencies
4. **Alert thresholds** - Notify when discrimination confidence is low
5. **Historical trends** - Week/month aggregated views

## Conclusion

✅ **Objective Achieved:** Refined discrimination display with 440 Hz analysis now complete and deployed.

The new page provides comprehensive WWV/WWVH discrimination analysis with four complementary measurement methods, making it significantly more informative than the previous 3-panel display.
