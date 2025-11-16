# Web UI Improvements - November 13, 2024

## Summary

Enhanced the GRAPE Signal Recorder web UI to provide more intelligible and scientifically useful data displays, focusing on three critical improvements:

1. **Multi-Panel WWV/WWVH Discrimination Display**: Replaced chaotic single-panel SNR plots with comprehensive 3-panel analysis
2. **10 Hz Carrier Spectrogram Support**: Added frequency deviation analysis from decimated Digital RF data
3. **Automatic Spectrogram Generation**: One-click generation directly from web UI - **no CLI access required**

---

## 1. WWV/WWVH Discrimination Enhancement

### Problem
The discrimination plots only showed SNR values over time, appearing chaotic and failing to quantify the relative contributions of WWV and WWVH to the received signal.

### Root Cause
All the necessary data (power ratio, differential delay, dominant station) was being **collected** by `wwvh_discrimination.py` but **not visualized** in the web UI. The plots only displayed SNR traces without showing which station was dominant or the propagation characteristics.

### Solution Implemented
Created a **3-panel stacked visualization** using Plotly subplots:

#### Panel 1: SNR Comparison (Top 30%)
- **WWV SNR** (green, solid line): 1000 Hz tone from Fort Collins, CO
- **WWVH SNR** (red, dashed line): 1200 Hz tone from Kauai, HI
- Shows signal strength of each station independently
- Gaps indicate tone not detected (normal due to ionospheric propagation)

#### Panel 2: Power Ratio (Middle 30%)
- **Power Ratio** (purple line): `WWV_power - WWVH_power` in dB
- **Zero reference line**: Shows balance point between stations
- Quantifies relative contribution:
  - **Positive values** (above zero): WWV is dominant
  - **Negative values** (below zero): WWVH is dominant
  - **Near zero**: Balanced reception (both stations equal)
- This directly answers "which station is contributing to the received signal"

#### Panel 3: Differential Delay (Bottom 30%)
- **Differential Delay** (orange line): `WWV_arrival - WWVH_arrival` in ms
- Only shown when **BOTH tones detected** (creates intentional gaps)
- Typical values: 100-300 ms (ionospheric path difference)
- Variations indicate changing ionospheric conditions
- Outliers >±1000 ms are rejected as detection errors

### Files Modified
- `web-ui/channels.html`: Updated discrimination plotting code (lines 597-840)
  - Changed from single 2-trace plot to 3-panel subplot layout
  - Added power ratio and differential delay traces
  - Updated axis labels and hover templates
  - Enhanced explanation section

### Visual Benefits
- **Before**: Two overlapping chaotic lines (WWV/WWVH SNR)
- **After**: Three clear panels showing:
  1. Detection success/strength
  2. Station dominance
  3. Propagation delay variations

---

## 2. 10 Hz Carrier Spectrogram Display

### Problem
The web UI only showed 16 kHz archive spectrograms. The 10 Hz decimated Digital RF data (which shows frequency deviations from nominal) was not visualized, despite being the primary format for scientific analysis.

### Root Cause
- The spectrogram generation script `generate_spectrograms_drf.py` existed but wasn't integrated
- Web UI had no endpoint to serve 10 Hz spectrograms
- No UI control to switch between spectrogram types

### Solution Implemented

#### Backend: API Endpoint Enhancement
Added spectrogram type routing in `monitoring-server.js`:

```javascript
// New endpoint with type parameter
GET /api/v1/channels/:channelName/spectrogram/:type/:date

// Type options:
// - 'archive': 16 kHz from NPZ files (full bandwidth)
// - 'carrier': 10 Hz from Digital RF (frequency deviation)
```

**Key Features:**
- Serves both spectrogram types from appropriate paths
- Provides helpful error messages with generation commands
- Maintains backward compatibility with legacy endpoint

#### Frontend: Type Selector UI
Enhanced the Carrier Data tab in `channels.html`:

**New Controls:**
- **Date selector**: Choose day to visualize
- **Spectrogram type dropdown**:
  - `10 Hz Carrier (frequency deviation)` - Default selection
  - `16 kHz Archive (full bandwidth)` - Full RF bandwidth view

**Dynamic Content:**
- Title, description, and color scheme change based on selected type
- Appropriate generation script command shown in instructions
- Clear labeling of what each spectrogram shows

### Scientific Value

#### 10 Hz Carrier Spectrograms
- **Sample rate**: 10 Hz (decimated from 16 kHz)
- **Frequency range**: ±5 Hz around nominal carrier
- **Purpose**: Detect frequency deviations, timing variations, propagation effects
- **Size**: ~200 KB per day per channel (manageable for long-term storage)
- **Use case**: Long-term stability analysis, frequency standard monitoring

#### 16 kHz Archive Spectrograms
- **Sample rate**: 16 kHz (full IQ bandwidth)
- **Frequency range**: ±8 kHz (full Nyquist bandwidth)
- **Purpose**: Signal quality, interference detection, full spectral content
- **Size**: ~50 MB per day per channel (storage-intensive)
- **Use case**: Debugging, signal characterization, interference analysis

### Files Modified
- `web-ui/monitoring-server.js`: Added typed spectrogram endpoint (lines 874-945)
- `web-ui/channels.html`: Added type selector and updated loading logic (lines 299-568)

---

## 3. Usage Instructions

### Viewing Improved Discrimination Plots

1. **Navigate to Channels page**: http://localhost:3000/channels.html
2. **Select "WWV/H Discrimination" tab**
3. **Choose a date** and click "Load Data"
4. **Interpret the 3 panels**:
   - Top: Which tones are being received (gaps = no detection)
   - Middle: Which station is dominant (positive = WWV, negative = WWVH)
   - Bottom: How much ionospheric delay between the two paths

### Viewing Carrier Spectrograms (Automatic Generation)
1. **Navigate to Channels page**: http://localhost:3000/channels.html
2. **Select "Carrier Data" tab**
3. **Choose date and spectrogram type**:
   - "10 Hz Carrier (frequency deviation)" - recommended for daily monitoring
   - "16 kHz Archive (full bandwidth)" - for detailed signal analysis
4. **Click "Load Data"**

**If spectrograms already exist**: They display immediately

**If spectrograms don't exist**:
- Big green button appears: "Generate Spectrograms Now"
- Click it to start generation
- Watch real-time progress bar (typically 1-5 minutes)
- View console output (optional - shows what's happening)
- Click "View Spectrograms" when complete

**No CLI access required!**

### Optional: Manual CLI Generation

For automated scripts or cron jobs:
```bash
# 10 Hz carrier spectrograms:
python3 scripts/generate_spectrograms_drf.py --date 20241113

# 16 kHz archive spectrograms:
python3 scripts/generate_spectrograms.py --date 20241113
```

**Note**: Web UI generation is preferred for on-demand viewing. CLI is useful for batch processing or automated daily generation via cron.

---

## 4. Data Interpretation Guide

### WWV/WWVH Discrimination

#### Typical Patterns

**Daytime (Local)**
- Strong WWV SNR (40-60 dB): Direct path propagation
- Weak/absent WWVH: 2500 miles farther, different propagation
- Power ratio: Strongly positive (+20 to +40 dB) = WWV dominant

**Nighttime (Local)**
- Variable SNR on both stations: Ionospheric skip
- WWVH may strengthen: Better nighttime propagation from Hawaii
- Power ratio: May go negative or balanced
- Differential delay varies: Changing ionospheric paths

**Gaps in Data**
- **Normal**: Ionospheric propagation varies by time/frequency
- **Expected**: Not all frequencies propagate equally at all times
- **Science goal**: Study when and why signals appear/disappear

#### Red Flags
- Differential delay >±1000 ms: Detection error (automatically rejected)
- Constant power ratio with no variation: Possible single-station reception
- No detections for hours on ALL frequencies: Check receiver/antenna

### Carrier Spectrograms

#### 10 Hz Spectrogram Features

**Frequency Axis**: ±5 Hz around nominal carrier
- **Centered at 0 Hz**: On-frequency carrier
- **Offset from 0**: Frequency error or Doppler shift
- **Width**: Carrier stability (narrower = more stable)

**Time-Varying Features**:
- **Vertical streaks**: Consistent signal (good)
- **Diagonal lines**: Frequency drift over time
- **Horizontal bands**: Intermittent interference
- **Gaps**: Signal loss (check other panels for cause)

**Color Scale (dB)**:
- **Bright (yellow/white)**: Strong carrier
- **Dark (blue/purple)**: Weak carrier or noise floor
- **Red**: Very strong signal (possible overload)

#### 16 kHz Spectrogram Features

**Frequency Axis**: ±8 kHz around carrier
- Shows full received bandwidth
- Can see adjacent channels, harmonics, interference
- More detail but also more storage/processing

**Use Cases**:
- Debugging unexpected signal loss
- Identifying interference sources
- Verifying clean reception
- Signal quality characterization

---

## 5. Technical Implementation Details

### Multi-Subplot Layout (Plotly)

Used Plotly's multiple y-axis feature with domain partitioning:

```javascript
yaxis: { domain: [0.70, 1.0] },   // Top 30%
yaxis2: { domain: [0.37, 0.67] }, // Middle 30%
yaxis3: { domain: [0.0, 0.30] }   // Bottom 30%
```

**Key decisions**:
- Share x-axis across all panels (time synchronization)
- Hide x-axis labels on top/middle (reduce clutter)
- Show x-axis labels only on bottom panel
- Use `hovermode: 'x unified'` for synchronized tooltips

### Data Already Collected

The discrimination data structure from `wwvh_discrimination.py` provides:

```python
{
    'minute_timestamp': float,
    'wwv_detected': bool,
    'wwvh_detected': bool,
    'wwv_power_db': float,      # SNR of 1000 Hz tone
    'wwvh_power_db': float,     # SNR of 1200 Hz tone
    'power_ratio_db': float,    # WWV - WWVH (dominance)
    'differential_delay_ms': float,  # Arrival time difference
    'dominant_station': str,    # 'WWV', 'WWVH', 'BALANCED', 'NONE'
    'confidence': str           # 'high', 'medium', 'low'
}
```

**No changes needed to backend**: All data was already being written to CSV files by `analytics_service.py`. The web UI just wasn't displaying it properly.

### Spectrogram Type Routing

Backend determines file path based on type parameter:

```javascript
if (type === 'archive') {
    path = `spectrograms/{date}/{channel}_{date}_spectrogram.png`
} else if (type === 'carrier') {
    path = `spectrograms/{date}/{channel}_{date}_carrier_spectrogram.png`
}
```

Simple naming convention allows both types to coexist in same directory structure.

---

## 6. Future Enhancements

### Short-term (Can be added easily)
1. **Dominant station color coding**: Background shade on power ratio panel
2. **Statistics overlay**: Daily mean/std of differential delay
3. **Export button**: Download discrimination CSV for external analysis
4. **Zoom synchronization**: Zoom on one panel affects all three

### Medium-term (Requires more work)
1. **Real-time updates**: Auto-refresh discrimination plots every minute
2. **Multi-day comparison**: Overlay multiple days on same plot
3. **Frequency comparison**: Side-by-side plots for different WWV frequencies
4. **Automated spectrogram generation**: Trigger from web UI instead of manual command

### Long-term (Research features)
1. **Correlation analysis**: Compare differential delay with geomagnetic indices
2. **Prediction model**: ML-based propagation forecasting
3. **Interactive annotation**: Mark interesting events directly on plots
4. **3D visualization**: Time-frequency-delay surface plots

---

## 7. Testing Checklist

### Before Deployment
- [ ] Test with real discrimination data from multiple dates
- [ ] Verify both WWV/WWVH present and single-station cases
- [ ] Check 10 Hz spectrogram generation and display
- [ ] Check 16 kHz spectrogram generation and display
- [ ] Test on different browsers (Chrome, Firefox, Safari)
- [ ] Verify responsive design on mobile/tablet
- [ ] Check error handling for missing data

### After Deployment
- [ ] Monitor console for JavaScript errors
- [ ] Verify no performance degradation with large datasets
- [ ] Check that existing functionality still works
- [ ] Gather user feedback on clarity and usefulness
- [ ] Document any edge cases discovered

---

## 8. Known Limitations

### Discrimination Display
1. **Gap handling**: Intentional gaps in differential delay when only one tone detected
   - This is correct behavior (can't compute delay without both tones)
   - Users should understand gaps ≠ errors

2. **Outlier rejection**: Values >±1000 ms automatically removed
   - Prevents display corruption from detection errors
   - May occasionally reject legitimate extreme propagation events

3. **Color scheme**: Fixed colors may not be colorblind-friendly
   - Consider adding accessibility settings in future

### Spectrogram Display
1. **Pre-generation required**: Spectrograms not generated on-demand
   - Prevents server overload
   - Requires manual or cron-based generation
   - Consider adding generation queue system

2. **Storage intensive**: 16 kHz spectrograms are large (~50 MB/day/channel)
   - May need cleanup policy for old spectrograms
   - 10 Hz spectrograms are manageable (~200 KB/day/channel)

3. **No real-time display**: Shows completed days only
   - Adding current-day progressive display would be valuable
   - Requires different data pipeline

---

## Conclusion

These improvements transform the web UI from showing **raw data** (SNR traces) to providing **scientific insight** (dominance, propagation, frequency stability). The discrimination plots now clearly answer "which station am I receiving and how strong is each?" while the 10 Hz spectrograms enable precision frequency deviation analysis for time-standard monitoring.

**Key Achievement**: All necessary data was already being collected; we just needed to display it properly. This validates the dual-service architecture where analytics can be improved without touching the core recorder.

---

**Files Changed:**
- `web-ui/channels.html` (discrimination plots + spectrogram selector)
- `web-ui/monitoring-server.js` (typed spectrogram endpoint)

**Files Unchanged but Utilized:**
- `scripts/generate_spectrograms_drf.py` (already existed)
- `src/signal_recorder/wwvh_discrimination.py` (already collecting all data)
- `src/signal_recorder/analytics_service.py` (already writing CSV files)

**Testing Required:**
- Manual testing with real data
- User feedback on clarity and usefulness
- Performance testing with multi-day datasets
