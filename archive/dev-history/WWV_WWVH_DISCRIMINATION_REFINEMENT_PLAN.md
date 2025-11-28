# WWV/WWVH Discrimination Refinement & Display Enhancement Plan

**Date:** November 23, 2025  
**Goal:** Refine discrimination methods and improve visualization to showcase the strengths of each method

---

## Current State Analysis

### ✅ Strong Foundation

**5 Independent Methods Implemented:**
1. **440 Hz Hourly Tone** - Highest confidence calibration (2 points/hour)
2. **BCD Cross-Correlation** - Primary continuous method (~50 points/minute)
3. **1000/1200 Hz Marker Tones** - Baseline per-minute (1 point/minute)
4. **Per-Second Tick Windows** - Fine-grained with coherent integration (6 points/minute)
5. **Weighted Voting** - Final determination combining all methods

**Web UI Features:**
- 7-panel Plotly visualization
- Per-channel day view
- Statistics dashboard
- BCD and tick window data parsing
- Smoothing and trend analysis

**Data Quality:**
- BCD uses Joint Least Squares to overcome temporal leakage
- Tick detection uses adaptive coherent/incoherent integration
- Proper harmonic filtering (440/500/600 Hz notches)
- Noise floor measurements in clean guard bands

---

## Identified Opportunities for Improvement

### 1. **Performance Optimization - BCD Method** (Quick Win)

**Current State:**
- ✅ Uses `method='fft'` in correlation (optimal)
- ⚠️ Uses `step_seconds=1` (45 windows/minute)
- Impact: ~22.7 seconds per minute for reprocessing

**Optimization:**
```python
# File: src/signal_recorder/wwvh_discrimination.py, line 939
# Change default from step_seconds=1 to step_seconds=3

def detect_bcd_discrimination(
    self,
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float,
    window_seconds: int = 10,
    step_seconds: int = 3,  # Changed from 1 → 3x speedup
    adaptive: bool = True
)
```

**Benefits:**
- 3x speedup: ~7.5 seconds per minute (vs 22.7)
- Still provides 15 data points/minute (excellent temporal resolution)
- Stays well within ionospheric coherence time (Tc ~15-20 seconds)
- Reduces storage/bandwidth for high-res time-series

**Trade-offs:**
- Reduces from ~50 to ~15 BCD windows per minute
- Still captures all relevant ionospheric dynamics (>1 second variations)
- Faster than tick method (6 points/minute)

**Recommendation:** ✅ Implement immediately

---

### 2. **Display Enhancement - Method Comparison Dashboard**

**Current State:**
- Single discrimination.html with combined 7-panel view
- Good for individual channels
- Doesn't highlight unique strengths of each method

**Enhancement Proposal: "Discrimination Methods Comparison" Page**

Create new view: `discrimination-methods.html`

**4-Column Layout:**

| Time | Method 1: Timing Tones | Method 2: BCD | Method 3: 440 Hz | Method 4: Ticks | Method 5: Voting |
|------|----------------------|---------------|-----------------|----------------|------------------|
| Temporal Resolution | 1/min | 15-50/min | 2/hour | 6/min | 1/min |
| Strengths | Baseline, robust | Continuous, high-res | Clean calibration | Sub-minute dynamics | Final determination |

**Visualization Panels:**
1. **Method Strength Timeline** - Stacked area showing which method(s) provide high-confidence data each minute
2. **Cross-Method Validation** - Scatter plots comparing methods (e.g., BCD amplitude vs 440 Hz power)
3. **Confidence Heat Map** - 24-hour grid showing per-method confidence scores
4. **Agreement Analysis** - Show when methods agree/disagree, confidence levels
5. **Method Selection Rationale** - Explain weighted voting decisions with visual breakdown

**Benefits:**
- Showcases unique value of each method
- Helps users understand why 5 methods are better than 1
- Validates cross-method consistency
- Educational for new users

---

### 3. **BCD Visualization Enhancements**

**Current State:**
- BCD windows parsed and displayed in discrimination.js (lines 184-209)
- Shows amplitude and differential delay
- Displayed alongside other methods

**Enhancements:**

**A. High-Resolution BCD Panel**
```javascript
// Dedicated panel showing BCD's temporal resolution advantage
{
    name: 'BCD WWV Amplitude (1-sec resolution)',
    x: bcdTimestamps,
    y: bcdWwvAmplitude,
    mode: 'lines+markers',
    marker: { size: 2 },
    line: { width: 1, color: '#10b981' }
}
```

**B. BCD Quality Indicator**
```javascript
// Color-code BCD points by correlation quality
marker: {
    size: 3,
    color: bcdCorrelationQuality,
    colorscale: 'Viridis',
    showscale: true,
    colorbar: { title: 'BCD Quality' }
}
```

**C. Differential Delay Time-Series**
- Currently shown, but could add statistical bounds
- Highlight outliers (>30ms = likely detection error)
- Show running mean/std to track ionospheric stability

---

### 4. **Method Performance Metrics Dashboard**

**New Endpoint:** `/api/v1/channels/{channel}/discrimination/metrics`

**Metrics to Track:**
```json
{
    "date": "2025-11-23",
    "method_1_timing_tones": {
        "measurements": 1440,
        "wwv_detections": 1250,
        "wwvh_detections": 980,
        "differential_delays_valid": 950,
        "mean_power_ratio_db": 5.2,
        "std_power_ratio_db": 3.1
    },
    "method_2_bcd": {
        "minutes_processed": 1440,
        "total_windows": 21600,  // 15 per minute
        "valid_correlations": 20100,
        "mean_wwv_amplitude": 0.65,
        "mean_wwvh_amplitude": 0.42,
        "mean_differential_delay_ms": 12.3,
        "outliers_rejected": 150
    },
    "method_3_hz440": {
        "wwv_detections": 21,  // Minute 2, hourly
        "wwvh_detections": 19, // Minute 1, hourly
        "detection_rate": 0.83  // 40/48 possible
    },
    "method_4_ticks": {
        "windows_analyzed": 8640,  // 6 per minute
        "coherent_integration_pct": 0.72,
        "incoherent_integration_pct": 0.28,
        "mean_coherence_quality": 0.68
    },
    "method_5_voting": {
        "wwv_dominant": 892,
        "wwvh_dominant": 234,
        "balanced": 314,
        "high_confidence_pct": 0.64,
        "method_agreement_matrix": {
            "all_agree": 450,
            "4_agree": 680,
            "3_agree": 250,
            "2_agree": 60
        }
    }
}
```

**Dashboard Display:**
- Method utilization bars (what % of time each method provides valid data)
- Agreement matrix heatmap
- Confidence distribution histograms
- Method-specific quality trends over 24 hours

---

### 5. **Documentation Enhancements**

**Current Docs:**
- ✅ WWV_WWVH_DISCRIMINATION_METHODS.md (excellent)
- ✅ BCD_DISCRIMINATION_IMPLEMENTATION.md
- ✅ BCD_DISCRIMINATION_CORRECTIONS.md
- ✅ BCD_OPTIMIZATION_ANALYSIS.md

**Add New Docs:**

**A. WWV_WWVH_DISCRIMINATION_USER_GUIDE.md**
- For operators: What to expect, how to interpret
- When to trust which method
- Troubleshooting poor discrimination
- Examples of good/bad data

**B. WWV_WWVH_DISCRIMINATION_WEB_UI_GUIDE.md**
- Screenshots of each visualization panel
- How to identify ionospheric events
- Interpreting method disagreements
- Exporting data for further analysis

**C. Update README.md Section**
```markdown
### 🔬 5-Method WWV/WWVH Discrimination

Separate WWV (Fort Collins) and WWVH (Kauai) signals on shared frequencies (2.5, 5, 10, 15 MHz):

1. **Timing Tones (1000/1200 Hz)** - Per-minute baseline
2. **BCD Correlation (100 Hz)** - High-resolution continuous (~15 points/min)
3. **440 Hz ID Tones** - Hourly calibration reference
4. **Per-Second Ticks** - Sub-minute dynamics (6 points/min)
5. **Weighted Voting** - Final determination

**Why 5 Methods?**
- Redundancy: Multiple independent measurements
- Validation: Cross-check for consistency
- Adaptive: Use best method for conditions (SNR, contamination, fading)
- Temporal coverage: From hourly (440 Hz) to sub-second (ticks)

See [Discrimination Guide](docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md) for details.
```

---

### 6. **Live Status Indicators**

**Enhancement for summary.html:**

Add discrimination status for shared-frequency channels:

```html
<div class="discrimination-status">
    <div class="method-indicator bcd-active">
        BCD: 94% valid (15/min)
    </div>
    <div class="method-indicator ticks-active">
        Ticks: 87% coherent
    </div>
    <div class="method-indicator hz440-waiting">
        440Hz: Next in 23 min
    </div>
    <div class="discrimination-result wwv-dominant">
        Result: WWV +8.2dB
    </div>
</div>
```

**Color Coding:**
- 🟢 Green: High-quality data, good confidence
- 🟡 Yellow: Valid but low SNR or partial data
- 🔴 Red: No discrimination (both stations weak/absent)
- ⚪ Gray: Method not applicable now (e.g., 440 Hz between hours)

---

### 7. **API Enhancements**

**Current:** `/api/v1/channels/{channel}/discrimination/{date}`

**Add Endpoints:**

```
GET /api/v1/channels/{channel}/discrimination/{date}/methods
    → Separated by method (tone_detections, bcd, hz440, ticks, voting)

GET /api/v1/channels/{channel}/discrimination/{date}/summary
    → Daily statistics, dominant station %, agreement metrics

GET /api/v1/channels/{channel}/discrimination/{date}/quality
    → Per-method quality scores, data completeness, confidence distribution

GET /api/v1/channels/{channel}/discrimination/live
    → Last 60 minutes, all methods, for real-time monitoring
```

---

## Implementation Priority

### **Phase 1: Quick Wins** (1-2 hours)
1. ✅ Change BCD `step_seconds` default from 1 to 3
2. Add method performance metrics to existing API
3. Update summary.html with discrimination status indicators

### **Phase 2: Visualization** (4-6 hours)
4. Create discrimination-methods.html comparison dashboard
5. Enhance BCD visualization with quality color-coding
6. Add cross-method validation plots

### **Phase 3: Documentation** (2-3 hours)
7. Write user guide for operators
8. Create web UI guide with screenshots
9. Update README with discrimination section

### **Phase 4: Advanced Features** (optional, 8-10 hours)
10. Implement real-time discrimination status websocket
11. Add exportable reports (PDF/CSV summary)
12. Machine learning confidence scoring (train on 440 Hz ground truth)

---

## Success Metrics

**Performance:**
- ✅ BCD reprocessing <10 seconds/minute (vs 22.7s currently)
- ✅ Real-time discrimination updates <1 second latency

**User Experience:**
- ✅ Users can identify which method is providing best data at any time
- ✅ Clear visualization of method strengths and agreement
- ✅ Intuitive understanding of "why 5 methods are better than 1"

**Data Quality:**
- ✅ Cross-method validation catches detection errors
- ✅ Confidence scores accurately reflect reliability
- ✅ Temporal resolution matches ionospheric dynamics

---

## Questions for Discussion

1. **BCD step_seconds:** Agree with 3-second default? Or make it configurable per channel?

2. **Web UI priority:** Focus on methods comparison dashboard first, or enhance existing discrimination.html?

3. **Real-time vs batch:** How important is live discrimination monitoring vs historical analysis?

4. **Documentation audience:** Primarily for station operators, or also for scientists using the data?

5. **Performance:** Is BCD reprocessing speed critical, or is real-time performance more important?

6. **440 Hz coverage:** Currently 2 points/hour - should we log all 440 Hz detections (minutes 1&2 each hour) for better calibration coverage?

---

## Files to Modify

**Performance (Phase 1):**
- `src/signal_recorder/wwvh_discrimination.py` - line 939, change `step_seconds=3`
- Test with: `scripts/reprocess_discrimination.py`

**Visualization (Phase 2):**
- `web-ui/discrimination-methods.html` (new file)
- `web-ui/discrimination-methods.js` (new file)
- `web-ui/discrimination.js` - enhance BCD visualization
- `web-ui/summary.html` - add discrimination status

**API (Phase 2):**
- `web-ui/monitoring-server-v3.js` - add new endpoints

**Documentation (Phase 3):**
- `WWV_WWVH_DISCRIMINATION_USER_GUIDE.md` (new)
- `WWV_WWVH_DISCRIMINATION_WEB_UI_GUIDE.md` (new)
- `README.md` - update discrimination section

---

## Next Steps

Please review this plan and let me know:
1. Which phases/features to prioritize
2. Any concerns or alternative approaches
3. Whether to proceed with Phase 1 (quick wins) immediately

I'm ready to implement any or all of these improvements based on your priorities.
