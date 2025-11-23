# WWV/WWVH Discrimination Display - Current State

**Last Updated:** November 23, 2025

---

## Web UI Files

### 1. `discrimination.html` + `discrimination.js` (Primary Interface)

**Layout:** 7-panel vertical stack using Plotly

**Panels:**
1. **SNR Ratio Timeline** 
   - Raw scatter + 10-min smoothed trend
   - Color-coded: Green (WWV) ↔ Gray (balanced) ↔ Red (WWVH)
   - Threshold lines at ±3 dB

2. **440 Hz Tone Power**
   - WWV (minute 2) and WWVH (minute 1) hourly calibration
   - Line + marker display
   - 2 points per hour per station

3. **Power Ratio (Enhanced)**
   - Raw + smoothed with color gradient
   - Shows dominance over time

4. **BCD High-Resolution Data**
   - WWV amplitude (positive)
   - WWVH amplitude (negative, mirrored)
   - ~15-50 data points per minute
   - Currently displayed but not prominently highlighted

5. **Differential Delay**
   - Ionospheric path difference (ms)
   - Scatter plot showing propagation variations

6. **Per-Second Tick Analysis**
   - 6 windows per minute (10-second integration)
   - Coherent vs incoherent SNR
   - Coherence quality indicators

7. **Dominance Timeline**
   - Classification: WWV dominant / WWVH dominant / balanced / only one detected
   - Color-coded bar chart

**Statistics Header:**
- WWV dominant percentage
- WWVH dominant percentage
- Both detected count
- 440 Hz tone count

**Data Source:** 
```javascript
GET /api/v1/channels/{channel}/discrimination/{YYYYMMDD}
```

**Strengths:**
- ✅ Comprehensive single-page view
- ✅ Good color coding and visual hierarchy
- ✅ Includes all 5 discrimination methods
- ✅ Statistics summary

**Limitations:**
- ⚠️ Methods not clearly labeled or explained
- ⚠️ BCD's high resolution advantage not emphasized
- ⚠️ No cross-method validation visualizations
- ⚠️ No method-specific quality/confidence indicators

---

### 2. `discrimination-enhanced.html` + `discrimination-enhanced.js` (Alternative View)

**Purpose:** Enhanced version with additional features

**Features:**
- Similar 7-panel layout
- Additional statistics cards grid
- More sophisticated controls

**Status:** Appears to be an experimental/improved version of the primary interface

---

## Data Flow

```
NPZ Archives (16 kHz IQ)
    ↓
Analytics Service processes each minute
    ↓
5 Discrimination Methods run in parallel:
    1. Timing Tones (1000/1200 Hz) → tone_detections/
    2. BCD Correlation (100 Hz)    → bcd_discrimination/
    3. 440 Hz ID                   → station_id_440hz/
    4. Tick Windows                → tick_windows/
    5. Weighted Voting             → discrimination/
    ↓
Consolidated CSV: {CHANNEL}_discrimination_{YYYYMMDD}.csv
    ↓
API serves data: /api/v1/channels/{channel}/discrimination/{date}
    ↓
Web UI plots 7 panels
```

---

## CSV Data Structure

```csv
timestamp_utc,minute_timestamp,minute_number,
wwv_detected,wwvh_detected,
wwv_power_db,wwvh_power_db,power_ratio_db,
differential_delay_ms,
tone_440hz_wwv_detected,tone_440hz_wwv_power_db,
tone_440hz_wwvh_detected,tone_440hz_wwvh_power_db,
dominant_station,confidence,
tick_windows_10sec,        # JSON array (6 windows)
bcd_wwv_amplitude,         # Mean of ~15-50 windows
bcd_wwvh_amplitude,
bcd_differential_delay_ms,
bcd_correlation_quality,
bcd_windows                # JSON array (~15-50 per minute)
```

**Key Fields:**

**Per-Minute Baseline (Method 3):**
- `wwv_power_db`, `wwvh_power_db` - From 1000/1200 Hz tone detection
- `power_ratio_db` - WWV - WWVH (dB)
- `differential_delay_ms` - Arrival time difference

**440 Hz Calibration (Method 1):**
- `tone_440hz_wwv_detected`, `tone_440hz_wwv_power_db` - Minute 2
- `tone_440hz_wwvh_detected`, `tone_440hz_wwvh_power_db` - Minute 1

**Tick Windows (Method 4):** JSON array with 6 elements
```json
{
  "second": 1,
  "wwv_snr_db": 45.2,
  "wwvh_snr_db": 38.7,
  "coherent_wwv_snr_db": 48.1,
  "coherent_wwvh_snr_db": 41.3,
  "incoherent_wwv_snr_db": 43.5,
  "incoherent_wwvh_snr_db": 37.2,
  "coherence_quality_wwv": 0.78,
  "coherence_quality_wwvh": 0.65,
  "integration_method": "coherent",
  "tick_count": 10
}
```

**BCD Correlation (Method 2):** Summary + detailed windows
- `bcd_wwv_amplitude`, `bcd_wwvh_amplitude` - Mean amplitudes
- `bcd_differential_delay_ms` - Mean delay
- `bcd_correlation_quality` - Mean quality
- `bcd_windows` - JSON array (~15-50 per minute):
```json
{
  "window_start_sec": 5.0,
  "wwv_amplitude": 0.68,
  "wwvh_amplitude": 0.42,
  "differential_delay_ms": 12.3,
  "correlation_quality": 5.8
}
```

**Weighted Voting (Method 5):**
- `dominant_station` - Final determination: 'WWV' / 'WWVH' / 'BALANCED' / 'NONE'
- `confidence` - 'high' / 'medium' / 'low'

---

## Visualization Techniques Currently Used

### Color Schemes

**Station Identification:**
- 🟢 Green (`#10b981`) - WWV (Fort Collins)
- 🔴 Red (`#ef4444`) - WWVH (Hawaii)
- ⚪ Gray (`#94a3b8`) - Balanced / noise
- 🟣 Purple (`#8b5cf6`) - Combined/voting results

**Method-Specific:**
- 🟣 Violet (`#a78bfa`) - WWV 440 Hz
- 🔵 Cyan (`#22d3ee`) - WWVH 440 Hz
- 🟡 Amber (`#f59e0b`) - Quality indicators

### Plot Types

1. **Scatter plots** - Raw data points (SNR, power ratio)
2. **Line plots** - Trends, 440 Hz connections
3. **Line + markers** - Tick windows, high-res BCD
4. **Color gradients** - Heat map effects for dominance
5. **Smoothing** - 10-minute moving average overlays
6. **Threshold lines** - ±3 dB discrimination boundaries

### Interactive Features

- Hover tooltips with precise values
- UTC time formatting
- Auto-refresh capability
- Date/channel selectors
- Zoom/pan (Plotly built-in)

---

## Gaps in Current Display

### 1. **Method Attribution**
- Panels don't clearly label which discrimination method they represent
- Users may not understand WHY there are 7 different views
- No explanation of method strengths/weaknesses

### 2. **BCD Underutilized**
- BCD produces 15-50 points/minute but displayed alongside 1/minute methods
- High temporal resolution advantage not emphasized
- Joint Least Squares sophistication not highlighted

### 3. **No Cross-Validation View**
- Can't easily compare Method 1 vs Method 2 vs Method 4
- No scatter plots showing agreement/disagreement
- Missing: "How well do methods correlate?"

### 4. **Confidence Not Prominent**
- `confidence` field exists but not visualized strongly
- No color-coding by confidence level
- Can't filter by high-confidence only

### 5. **Method Performance Metrics**
- No "which method worked best today?" summary
- No data completeness indicators per method
- Missing: coherent integration % for ticks

### 6. **Real-Time Status**
- Shows historical data well
- No live status of which methods are currently providing good data
- No "next 440 Hz tone in X minutes" countdown

---

## Display Enhancement Opportunities

### Quick Wins
1. Add method labels to each panel ("Method 2: BCD Correlation")
2. Add info tooltips explaining each method
3. Highlight BCD panel with "High Resolution" badge
4. Color-code data points by confidence level

### Medium Effort
5. Create "Method Comparison" tab showing all 5 side-by-side
6. Add cross-method scatter plots (BCD amplitude vs 440 Hz power)
7. Show method agreement indicators
8. Add per-method quality metrics cards

### Advanced
9. Live discrimination status dashboard
10. Animated view showing methods updating at different rates
11. Machine learning confidence prediction
12. Exportable multi-method analysis reports

---

## Recommended Next Steps

1. **Label Enhancement** - Add clear method identification to existing panels
2. **BCD Spotlight** - Create dedicated high-resolution BCD view
3. **Method Comparison Dashboard** - New page showing all methods side-by-side
4. **Quality Indicators** - Visual confidence/quality metrics per method
5. **User Guide** - Documentation explaining what each visualization shows

---

## Files to Reference

**Web UI:**
- `web-ui/discrimination.html` - Main interface HTML
- `web-ui/discrimination.js` - Plotting and data handling (683 lines)
- `web-ui/discrimination-enhanced.html` - Alternative enhanced view
- `web-ui/monitoring-server-v3.js` - API endpoints

**Backend:**
- `src/signal_recorder/wwvh_discrimination.py` - All 5 methods implemented
- `src/signal_recorder/analytics_service.py` - CSV generation

**Documentation:**
- `WWV_WWVH_DISCRIMINATION_METHODS.md` - Technical method descriptions
- `BCD_DISCRIMINATION_IMPLEMENTATION.md` - BCD details
- `docs/features/WWVH_DISCRIMINATION_QUICKREF.md` - Quick reference

---

## Summary

**Current State:** ✅ Comprehensive, functional, includes all 5 methods

**Opportunity:** Make the sophistication more visible and help users understand why multiple methods provide better discrimination than any single approach.
