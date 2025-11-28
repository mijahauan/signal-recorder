# WWV/WWVH Discrimination - Quick Win Improvements

**Implementation Time:** 1-2 hours  
**Impact:** High visibility, better user understanding

---

## Quick Win #1: BCD Performance Optimization (30 minutes)

### Change

**File:** `src/signal_recorder/wwvh_discrimination.py`  
**Line:** 939

```python
# BEFORE
def detect_bcd_discrimination(
    self,
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float,
    window_seconds: int = 10,
    step_seconds: int = 1,  # ← 45 windows per minute
    adaptive: bool = True
)

# AFTER  
def detect_bcd_discrimination(
    self,
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float,
    window_seconds: int = 10,
    step_seconds: int = 3,  # ← 15 windows per minute (3x speedup)
    adaptive: bool = True
)
```

### Impact

**Performance:**
- Reprocessing: 22.7s → 7.5s per minute (3x faster)
- Storage: ~65% reduction in BCD window data
- Still provides 15 data points/minute (excellent resolution)

**Science:**
- Captures all ionospheric dynamics >3 seconds
- Well within coherence time (Tc ~15-20 seconds)
- Still higher resolution than tick method (6/min)

### Testing

```bash
# Test on sample data
cd /home/mjh/git/signal-recorder
source venv/bin/activate
python scripts/reprocess_discrimination.py \
    --channel "WWV_5_MHz" \
    --start-date 2025-11-20 \
    --end-date 2025-11-20

# Check timing improvement in logs
```

---

## Quick Win #2: Add Method Labels to Plots (20 minutes)

### Change

**File:** `web-ui/discrimination.js`  
**Lines:** 258-530 (plot layout configuration)

Add method identifiers to panel titles:

```javascript
// BEFORE
const layout = {
    yaxis: { title: 'SNR Ratio (dB)' },
    yaxis2: { title: '440 Hz Power (dB)' },
    yaxis3: { title: 'Power Ratio (dB)' },
    // ...
}

// AFTER
const layout = {
    yaxis: { 
        title: '<b>Method 3:</b> Timing Tones (1000/1200 Hz)<br>SNR Ratio (dB)',
        titlefont: { size: 13 }
    },
    yaxis2: { 
        title: '<b>Method 1:</b> 440 Hz ID Tones<br>Power (dB)',
        titlefont: { size: 13 }
    },
    yaxis3: { 
        title: '<b>Method 2:</b> BCD Correlation (100 Hz)<br>Power Ratio (dB)',
        titlefont: { size: 13 }
    },
    yaxis4: {
        title: '<b>Method 2:</b> BCD High-Resolution (15/min)<br>Amplitude',
        titlefont: { size: 13 }
    },
    yaxis5: {
        title: '<b>Method 2:</b> Differential Delay<br>Time (ms)',
        titlefont: { size: 13 }
    },
    yaxis6: {
        title: '<b>Method 4:</b> Tick Windows (6/min)<br>SNR (dB)',
        titlefont: { size: 13 }
    },
    yaxis7: {
        title: '<b>Method 5:</b> Weighted Voting<br>Dominance',
        titlefont: { size: 13 }
    }
}
```

### Impact

Users immediately understand:
- Which method generates each plot
- How methods relate to documentation
- Why there are multiple views of "the same" data

---

## Quick Win #3: Info Panel with Method Summary (30 minutes)

### Change

**File:** `web-ui/discrimination.html`  
**After:** Line 50 (in info-panel section)

Add expandable method reference:

```html
<!-- Add after existing info-panel -->
<div class="info-panel method-reference">
    <h2>🔬 Discrimination Methods</h2>
    <div class="method-cards">
        <div class="method-card" data-method="1">
            <div class="method-header">
                <span class="method-badge">1</span>
                <h3>440 Hz ID Tones</h3>
                <span class="method-resolution">2/hour</span>
            </div>
            <p class="method-desc">
                Hourly calibration reference. WWVH transmits minute 1, WWV minute 2.
                Clean measurement, no harmonic contamination.
            </p>
            <div class="method-strength">✅ Highest confidence for calibration</div>
        </div>
        
        <div class="method-card highlight-bcd" data-method="2">
            <div class="method-header">
                <span class="method-badge">2</span>
                <h3>BCD Correlation</h3>
                <span class="method-resolution">15/min</span>
            </div>
            <p class="method-desc">
                100 Hz carrier analysis with sliding windows. Both stations transmit
                identical BCD code - correlation finds two peaks separated by propagation delay.
            </p>
            <div class="method-strength">🚀 Primary method - highest temporal resolution</div>
        </div>
        
        <div class="method-card" data-method="3">
            <div class="method-header">
                <span class="method-badge">3</span>
                <h3>Timing Tones</h3>
                <span class="method-resolution">1/min</span>
            </div>
            <p class="method-desc">
                Power ratio of 1000 Hz (WWV) vs 1200 Hz (WWVH) identification tones.
                Baseline measurement, works even with weak signals.
            </p>
            <div class="method-strength">✅ Reliable baseline</div>
        </div>
        
        <div class="method-card" data-method="4">
            <div class="method-header">
                <span class="method-badge">4</span>
                <h3>Tick Windows</h3>
                <span class="method-resolution">6/min</span>
            </div>
            <p class="method-desc">
                Per-second tick analysis in 10-second windows. Adaptive coherent/incoherent
                integration based on phase stability.
            </p>
            <div class="method-strength">✅ Sub-minute dynamics</div>
        </div>
        
        <div class="method-card" data-method="5">
            <div class="method-header">
                <span class="method-badge">5</span>
                <h3>Weighted Voting</h3>
                <span class="method-resolution">1/min</span>
            </div>
            <p class="method-desc">
                Combines all methods with minute-specific weighting. 440 Hz highest weight
                in minutes 1-2, BCD highest weight in minutes 0/8-10/29-30.
            </p>
            <div class="method-strength">📊 Final determination</div>
        </div>
    </div>
</div>

<style>
.method-reference { margin-bottom: 25px; }
.method-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 15px;
    margin-top: 15px;
}
.method-card {
    background: rgba(255, 255, 255, 0.03);
    border: 2px solid rgba(139, 92, 246, 0.3);
    border-radius: 10px;
    padding: 18px;
    transition: all 0.3s;
    cursor: pointer;
}
.method-card:hover {
    border-color: rgba(139, 92, 246, 0.6);
    background: rgba(255, 255, 255, 0.05);
    transform: translateY(-2px);
}
.method-card.highlight-bcd {
    border-color: rgba(139, 92, 246, 0.6);
    background: rgba(139, 92, 246, 0.08);
}
.method-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}
.method-badge {
    background: linear-gradient(135deg, #8b5cf6, #6366f1);
    color: white;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 14px;
}
.method-header h3 {
    flex: 1;
    font-size: 16px;
    font-weight: 600;
    color: #e0e0e0;
    margin: 0;
}
.method-resolution {
    background: rgba(139, 92, 246, 0.2);
    color: #c4b5fd;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
}
.method-desc {
    font-size: 13px;
    line-height: 1.5;
    color: #94a3b8;
    margin-bottom: 12px;
}
.method-strength {
    font-size: 12px;
    font-weight: 600;
    color: #10b981;
    padding: 8px 12px;
    background: rgba(16, 185, 129, 0.1);
    border-radius: 6px;
    border-left: 3px solid #10b981;
}
</style>
```

### Impact

- Users see method overview before diving into plots
- BCD's advantage (15/min) clearly highlighted
- Educational value for new users
- Professional appearance

---

## Quick Win #4: BCD Badge on High-Res Plot (10 minutes)

### Change

**File:** `web-ui/discrimination.js`  
**Around:** Line 235 (where plot container is created)

Add annotation to BCD panel:

```javascript
// After creating plot layout, add annotation
const layout = {
    // ... existing layout ...
    annotations: [
        {
            xref: 'paper',
            yref: 'y4',  // BCD amplitude panel
            x: 0.02,
            y: 0.95,
            yanchor: 'top',
            text: '⚡ HIGH RESOLUTION: 15 data points per minute',
            showarrow: false,
            font: {
                size: 12,
                color: '#10b981',
                weight: 'bold'
            },
            bgcolor: 'rgba(16, 185, 129, 0.1)',
            bordercolor: '#10b981',
            borderwidth: 2,
            borderpad: 6
        }
    ]
}
```

### Impact

- Immediately draws attention to BCD's key strength
- Users understand why BCD plot looks "busier" than others
- Reinforces documentation messaging

---

## Quick Win #5: Confidence Color-Coding (30 minutes)

### Change

**File:** `web-ui/discrimination.js`  
**Around:** Lines 260-280 (SNR ratio scatter plot)

Color data points by confidence level:

```javascript
// BEFORE
{
    x: timestamps, 
    y: snrRatio,
    name: 'SNR Ratio (raw)',
    mode: 'markers',
    marker: {
        size: 4,
        color: snrRatio,  // Color by value
        colorscale: [[0, '#ef4444'], [0.5, '#94a3b8'], [1, '#10b981']],
        // ...
    }
}

// AFTER
{
    x: timestamps, 
    y: snrRatio,
    name: 'SNR Ratio (raw)',
    mode: 'markers',
    marker: {
        size: filteredData.map(d => {
            // Larger markers for high confidence
            if (d.confidence === 'high') return 6;
            if (d.confidence === 'medium') return 4;
            return 3;
        }),
        color: filteredData.map(d => {
            // Color by confidence, not by value
            if (d.confidence === 'high') return '#10b981';  // Green
            if (d.confidence === 'medium') return '#f59e0b'; // Amber
            return '#94a3b8';  // Gray
        }),
        opacity: filteredData.map(d => {
            // Higher opacity for high confidence
            if (d.confidence === 'high') return 0.9;
            if (d.confidence === 'medium') return 0.6;
            return 0.3;
        })
    },
    hovertemplate: 'SNR: %{y:+.1f} dB<br>Confidence: %{text}<br>%{x|%H:%M} UTC<extra></extra>',
    text: filteredData.map(d => d.confidence)
}
```

### Impact

- Users immediately see which measurements are trustworthy
- High-confidence data stands out visually
- Helps identify problematic time periods

---

## Quick Win #6: Add Statistics Cards (20 minutes)

### Change

**File:** `web-ui/discrimination.html`  
**After:** Channel header section (line ~234)

Add method performance cards:

```html
<div class="method-stats-grid">
    <div class="stat-card method-1">
        <div class="stat-icon">🎺</div>
        <div class="stat-name">440 Hz Tones</div>
        <div class="stat-value" id="stat-hz440-count">--</div>
        <div class="stat-label">detections (of 48 possible)</div>
    </div>
    
    <div class="stat-card method-2 highlight">
        <div class="stat-icon">📊</div>
        <div class="stat-name">BCD Correlation</div>
        <div class="stat-value" id="stat-bcd-windows">--</div>
        <div class="stat-label">high-res windows analyzed</div>
    </div>
    
    <div class="stat-card method-4">
        <div class="stat-icon">⚡</div>
        <div class="stat-name">Tick Coherence</div>
        <div class="stat-value" id="stat-tick-coherent">--</div>
        <div class="stat-label">coherent integration rate</div>
    </div>
    
    <div class="stat-card method-5">
        <div class="stat-icon">✅</div>
        <div class="stat-name">High Confidence</div>
        <div class="stat-value" id="stat-high-conf">--</div>
        <div class="stat-label">minutes with strong discrimination</div>
    </div>
</div>

<style>
.method-stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
.stat-card {
    background: rgba(30, 41, 59, 0.6);
    border: 2px solid rgba(139, 92, 246, 0.3);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}
.stat-card.highlight {
    border-color: rgba(139, 92, 246, 0.6);
    background: rgba(139, 92, 246, 0.08);
}
.stat-icon {
    font-size: 32px;
    margin-bottom: 8px;
}
.stat-name {
    font-size: 13px;
    color: #94a3b8;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}
.stat-value {
    font-size: 28px;
    font-weight: 700;
    color: #e0e0e0;
    margin-bottom: 4px;
}
.stat-label {
    font-size: 11px;
    color: #64748b;
}
</style>
```

**JavaScript (in discrimination.js after data loads):**
```javascript
// Calculate and display method stats
const hz440Count = hz440WwvCount + hz440WwvhCount;
const bcdWindowsTotal = bcdTimestamps.length;
const tickCoherentPct = (
    tickTimestamps.filter((t, i) => 
        tickWwvCoherence[i] > 0.5 || tickWwvhCoherence[i] > 0.5
    ).length / tickTimestamps.length * 100
).toFixed(0);
const highConfMinutes = filteredData.filter(d => d.confidence === 'high').length;

document.getElementById('stat-hz440-count').textContent = 
    `${hz440Count} / 48`;
document.getElementById('stat-bcd-windows').textContent = 
    bcdWindowsTotal.toLocaleString();
document.getElementById('stat-tick-coherent').textContent = 
    `${tickCoherentPct}%`;
document.getElementById('stat-high-conf').textContent = 
    `${highConfMinutes} / ${filteredData.length}`;
```

### Impact

- Quick overview of method performance
- Users see at a glance which methods worked well today
- Highlights BCD's volume of data
- Professional dashboard appearance

---

## Implementation Order

**Recommended sequence (total ~2 hours):**

1. ✅ **BCD Performance** (30 min) - Immediate practical benefit
2. ✅ **Method Labels** (20 min) - Critical for understanding
3. ✅ **Info Panel** (30 min) - Educational foundation
4. ✅ **Statistics Cards** (20 min) - Quick wins visibility
5. ✅ **BCD Badge** (10 min) - Highlight key strength
6. ✅ **Confidence Colors** (30 min) - Data quality indicator

**Testing After Each:**
```bash
# Restart monitoring server
cd web-ui
./start-monitoring.sh

# View in browser
firefox http://localhost:3000/discrimination.html
```

---

## Expected Results

**Before:**
- Generic 7-panel plot
- Users confused about why multiple views
- BCD's advantage not obvious

**After:**
- Clear method identification
- Users understand 5-method approach
- BCD highlighted as primary high-res method
- Confidence levels visible
- Professional, polished appearance

**User Feedback Expected:**
- "Now I understand why there are 5 methods!"
- "BCD provides so much more data than I realized"
- "I can see which time periods have trustworthy discrimination"

---

## Files to Modify

**Backend:** (1 file, 1 line)
- `src/signal_recorder/wwvh_discrimination.py` - Line 939

**Frontend:** (2 files)
- `web-ui/discrimination.html` - Add info panel + stats cards
- `web-ui/discrimination.js` - Labels, badges, colors, stats calculations

**No Breaking Changes:** All enhancements are additive or cosmetic.

---

## Next Steps After Quick Wins

Once these are in place, consider:
1. Create dedicated BCD analysis page
2. Method comparison dashboard
3. Real-time discrimination status
4. User guide with screenshots

Ready to implement when you give the go-ahead! 🚀
