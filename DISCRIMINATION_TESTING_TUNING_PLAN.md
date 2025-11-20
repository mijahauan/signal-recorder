# WWV/WWVH Discrimination Testing & Tuning Plan

## Objective
Empirically validate and optimize discrimination performance through systematic variation of adjustable parameters while measuring accuracy against ground truth.

---

## Phase 1: Establish Baseline & Ground Truth

### 1.1 Ground Truth Dataset
**Goal:** Identify periods with known single-station reception

**Method:**
1. **Geographic/Time-Based Selection**
   - Early morning (0300-0600 UTC): WWV typically dominant (shorter E-layer path)
   - Late evening (2100-0000 UTC): WWVH more likely (Pacific propagation)
   - Solar minimum periods: More stable propagation

2. **High-Confidence Discrimination**
   - Minutes 1/2 with 440 Hz detection (10× weight, unambiguous)
   - Strong single-station periods (power_ratio > 15 dB, SNR > 25 dB)
   - Multi-hour stability (same dominant station for >3 hours)

3. **Cross-Validation Sources**
   - PSWS propagation reports for same time periods
   - Known WWV/WWVH outage schedules
   - Other monitoring stations' discrimination results

**Output:** `ground_truth_periods.csv` with columns:
```
timestamp, dominant_station, confidence_level, source, notes
```

### 1.2 Baseline Performance Metrics
**Goal:** Establish current system performance

**Test Script:** `scripts/measure_discrimination_accuracy.py`

**Metrics to Track:**
1. **Accuracy by Minute Type**
   - Minutes 1/2 (440 Hz dominant): Expected >95% accuracy
   - Minutes 0,8-10,29-30 (BCD dominant): Expected >90% accuracy
   - Other minutes (carrier dominant): Expected >85% accuracy

2. **Accuracy by Signal Strength**
   - Strong signals (SNR > 20 dB): Expected >95%
   - Medium signals (10-20 dB): Expected >85%
   - Weak signals (0-10 dB): Expected >70%

3. **Confidence Calibration**
   - "High" confidence → >95% accuracy
   - "Medium" confidence → >85% accuracy
   - "Low" confidence → >70% accuracy

4. **Temporal Consistency**
   - Minute-to-minute stability (% agreement between adjacent minutes)
   - Hour-to-hour stability (dominant station hold time)

**Output:** `baseline_performance_report.json`

---

## Phase 2: Parameter Tuning Grid Search

### 2.1 Tunable Parameters

| Parameter | Current | Range | Step | Impact |
|-----------|---------|-------|------|--------|
| **BCD Integration Window** | 10s | 5-20s | 1s | SNR vs temporal resolution |
| **BCD Sliding Step** | 1s | 0.5-2s | 0.5s | Temporal resolution vs computation |
| **Coherent SNR Advantage Threshold** | 3 dB | 1-6 dB | 1 dB | Coherent vs incoherent selection |
| **Tick Window Size** | 10s | 5-15s | 5s | SNR vs resolution |
| **440 Hz Detection Threshold** | 10 dB | 5-15 dB | 2.5 dB | False positive vs sensitivity |
| **Discrimination Threshold (3 dB)** | 3 dB | 1-6 dB | 1 dB | BALANCED vs station decision |
| **Weight: 440 Hz** | 10.0 | 5-20 | 5 | Minute 1/2 priority |
| **Weight: BCD** | 10.0 | 5-20 | 5 | BCD minute priority |
| **Weight: Carrier** | 10.0 | 5-20 | 5 | Normal minute priority |
| **Weight: Tick** | 5.0 | 2-10 | 2 | Cross-validation weight |
| **Confidence Margin: High** | 0.7 | 0.6-0.9 | 0.1 | High confidence threshold |
| **Confidence Margin: Medium** | 0.4 | 0.3-0.6 | 0.1 | Medium confidence threshold |
| **BALANCED Threshold** | 0.15 | 0.1-0.3 | 0.05 | Balanced station sensitivity |

### 2.2 Parameter Categories

#### Category A: High-Impact, Easy to Tune
**Test First - Most Likely to Need Adjustment**
- Discrimination threshold (3 dB) → Affects how "balanced" stations are classified
- Weight factors (10×, 5×, 2×) → Affects voting outcome
- Confidence margins (0.7, 0.4) → Affects confidence calibration
- Coherent SNR advantage (3 dB) → Affects coherent vs incoherent selection

#### Category B: Medium-Impact, Moderate Complexity
**Test Second - May Need Seasonal Adjustment**
- BCD integration window (10s) → SNR vs dynamics trade-off
- 440 Hz detection threshold (10 dB) → False positive rate
- Tick window size (10s) → Already optimized, but verify

#### Category C: Low-Impact, Stable Design
**Test Last - Should Be Stable**
- BCD sliding step (1s) → Computational load vs smoothness
- BALANCED threshold (0.15) → Already well-tuned
- Signal bandwidth (1.5 Hz) → Derived from Hann ENBW (fixed)

### 2.3 Grid Search Strategy

**Approach:** Hierarchical optimization (tune categories in order)

**Test Script:** `scripts/discrimination_grid_search.py`

**Example for Category A (Weight Factors):**
```python
# Test weight combinations
w_440_range = [5, 10, 15, 20]
w_bcd_range = [5, 10, 15, 20]
w_carrier_range = [5, 10, 15, 20]
w_tick_range = [2, 5, 8, 10]

for w_440 in w_440_range:
    for w_bcd in w_bcd_range:
        for w_carrier in w_carrier_range:
            for w_tick in w_tick_range:
                # Run discrimination with these weights
                # Measure accuracy against ground truth
                # Record results
```

**Smart Sampling:** Use **Bayesian optimization** to reduce search space:
- Start with current values (10, 10, 10, 5)
- Test neighbors (±1 step)
- Move toward accuracy improvements
- Converge when no improvement for 5 iterations

**Output:** `optimal_parameters.json`

---

## Phase 3: Ablation Studies

### 3.1 Method Importance
**Goal:** Verify each method contributes meaningfully

**Test:** Remove one method at a time, measure accuracy drop

| Method Disabled | Expected Accuracy Drop | Notes |
|----------------|----------------------|-------|
| None (baseline) | 0% (reference) | Full system |
| 440 Hz voting | -5% in minutes 1/2 | Should be significant |
| BCD voting | -8% in BCD minutes | Should be significant |
| Carrier voting | -10% in normal minutes | Should be significant |
| Tick voting | -3% overall | Cross-validation role |

**If accuracy drop < 2%:** Method not contributing → Consider removing

**Script:** `scripts/ablation_study.py`

### 3.2 Sensitivity Analysis
**Goal:** Understand parameter robustness

**Test:** Vary ONE parameter at a time, measure accuracy change

**Plot:** Accuracy vs Parameter Value
- Flat curve → Robust parameter, current value is fine
- Sharp peak → Critical parameter, needs careful tuning
- Monotonic → Current value may be suboptimal

**Example:**
```
BCD Integration Window:
5s  →  82% accuracy (too short, low SNR)
10s →  91% accuracy (current, optimal)
15s →  89% accuracy (too long, misses dynamics)
20s →  85% accuracy (excessive smoothing)
```

---

## Phase 4: Real-World Validation

### 4.1 Multi-Day Continuous Testing
**Goal:** Verify long-term stability

**Duration:** 7+ days continuous operation

**Monitor:**
1. **Accuracy Stability**
   - Daily accuracy trends
   - Degradation over time
   - Time-of-day patterns

2. **Confidence Calibration Drift**
   - Does "high" remain >95% accurate?
   - Does "medium" remain >85% accurate?

3. **Edge Cases**
   - Propagation fade transitions
   - Station outages (how quickly detected?)
   - Sudden ionospheric disturbances

**Alert Triggers:**
- Accuracy drops below 80% for >1 hour
- Confidence calibration error >10%
- Method disagreement >50% for >30 minutes

### 4.2 Cross-Station Validation
**Goal:** Verify discrimination quality across frequencies

**Test:** Compare discrimination results on 5 MHz, 10 MHz, 15 MHz simultaneously

**Expected:**
- High correlation in discrimination results
- Differential delays similar (ionospheric path is frequency-dependent but correlated)
- Any frequency-specific issues identified

### 4.3 Comparison to Other Systems
**Goal:** Benchmark against external discrimination systems

**Sources:**
- PSWS station discrimination logs
- Amateur radio WWV/WWVH reports
- Other monitoring stations (if available)

**Metric:** Agreement percentage with external sources

---

## Phase 5: Adaptive Parameter Tuning

### 5.1 Time-of-Day Optimization
**Goal:** Adjust parameters based on propagation patterns

**Hypothesis:** Different times benefit from different weights

**Test:**
```
Early Morning (0300-0600 UTC):
  - WWV typically stronger
  - May increase w_carrier for faster response

Midday (1200-1800 UTC):
  - Both stations strong
  - May increase discrimination threshold (reduce BALANCED)

Evening (2100-0000 UTC):
  - WWVH more likely
  - May increase w_bcd for stability
```

**Implementation:** Time-dependent weight profiles

### 5.2 SNR-Dependent Tuning
**Goal:** Adapt to signal strength conditions

**Strategy:**
```python
if avg_snr > 20 dB:  # Strong signals
    discrimination_threshold = 3.0 dB  # Standard
    confidence_high_margin = 0.7
elif avg_snr > 10 dB:  # Medium signals
    discrimination_threshold = 4.0 dB  # More conservative
    confidence_high_margin = 0.8  # Stricter
else:  # Weak signals
    discrimination_threshold = 6.0 dB  # Very conservative
    confidence_high_margin = 0.9  # Very strict
```

### 5.3 Seasonal Adjustment
**Goal:** Account for propagation changes across seasons

**Long-Term Study:** 3+ months

**Monitor:**
- Solar activity correlation
- Seasonal path length changes
- Optimal parameter drift

---

## Phase 6: Documentation & Deployment

### 6.1 Final Parameter Documentation

**File:** `DISCRIMINATION_OPTIMAL_PARAMETERS.md`

**Contents:**
```markdown
# Optimal Discrimination Parameters

## Empirically Validated Values (Date: YYYY-MM-DD)

### Integration Windows
- BCD Window: 10 seconds (tested 5-20s, optimal at 10s, ±2% accuracy within ±2s)
- BCD Step: 1 second (tested 0.5-2s, 1s provides best temporal resolution)
- Tick Window: 10 seconds (stable, no adjustment needed)

### Thresholds
- Discrimination: 3.0 dB (tested 1-6 dB, 3 dB optimal for BALANCED detection)
- Coherent SNR Advantage: 3.0 dB (tested 1-6 dB, 3 dB balances false coherence)
- 440 Hz Detection: 10.0 dB (tested 5-15 dB, 10 dB optimal false positive rate)

### Weight Factors
- 440 Hz: 10.0 (tested 5-20, 10 provides 96% accuracy in minutes 1/2)
- BCD: 10.0 (tested 5-20, 10 provides 92% accuracy in BCD minutes)
- Carrier: 10.0 (tested 5-20, 10 provides 87% accuracy in normal minutes)
- Tick: 5.0 (tested 2-10, 5 provides effective cross-validation)

### Confidence Margins
- High: 0.7 (calibrated to 96% accuracy)
- Medium: 0.4 (calibrated to 86% accuracy)
- BALANCED: 0.15 (calibrated to detect true balanced conditions)

## Validation Summary
- Baseline Accuracy: 89.3% (7-day average)
- High Confidence Accuracy: 96.1%
- Medium Confidence Accuracy: 86.4%
- Low Confidence Accuracy: 71.2%
- Temporal Consistency: 94.7% minute-to-minute agreement
```

### 6.2 Performance Report Template

**File:** `scripts/generate_performance_report.py`

**Generates:** Daily/weekly discrimination performance reports

**Includes:**
- Accuracy metrics by minute type
- Confidence calibration validation
- Temporal consistency plots
- Method contribution breakdown
- Alert summary (any accuracy drops)

### 6.3 Operational Monitoring

**Dashboard Metrics:**
1. **Real-Time**
   - Current dominant station
   - Confidence level
   - Method agreement (all 4 methods)

2. **Rolling Statistics (1 hour)**
   - Discrimination accuracy (if ground truth available)
   - Confidence calibration error
   - Station hold time

3. **Alerts**
   - Method disagreement >50% for >10 minutes
   - Confidence calibration error >10%
   - Accuracy drop >5% (if ground truth available)

---

## Testing Scripts to Create

### 1. `scripts/measure_discrimination_accuracy.py`
```bash
# Measure accuracy against ground truth
python3 scripts/measure_discrimination_accuracy.py \
    --date 20251119 \
    --channel "WWV 10 MHz" \
    --ground-truth ground_truth_periods.csv \
    --output baseline_performance.json
```

### 2. `scripts/discrimination_grid_search.py`
```bash
# Grid search for optimal parameters
python3 scripts/discrimination_grid_search.py \
    --date 20251119 \
    --channel "WWV 10 MHz" \
    --ground-truth ground_truth_periods.csv \
    --parameters config/tunable_params.yaml \
    --output optimal_parameters.json
```

### 3. `scripts/ablation_study.py`
```bash
# Test method importance
python3 scripts/ablation_study.py \
    --date 20251119 \
    --channel "WWV 10 MHz" \
    --ground-truth ground_truth_periods.csv \
    --output ablation_results.json
```

### 4. `scripts/sensitivity_analysis.py`
```bash
# Parameter sensitivity analysis
python3 scripts/sensitivity_analysis.py \
    --date 20251119 \
    --channel "WWV 10 MHz" \
    --parameter "bcd_integration_window" \
    --range "5,20,1" \
    --ground-truth ground_truth_periods.csv \
    --output sensitivity_bcd_window.png
```

### 5. `scripts/generate_performance_report.py`
```bash
# Generate daily performance report
python3 scripts/generate_performance_report.py \
    --date 20251119 \
    --channel "WWV 10 MHz" \
    --output reports/discrimination_20251119.html
```

---

## Success Criteria

### Minimum Acceptable Performance
- Overall Accuracy: >85%
- High Confidence Accuracy: >95%
- Minute 1/2 (440 Hz) Accuracy: >95%
- BCD Minutes Accuracy: >90%
- Temporal Consistency: >90% minute-to-minute agreement

### Target Performance
- Overall Accuracy: >90%
- High Confidence Accuracy: >97%
- Minute 1/2 (440 Hz) Accuracy: >98%
- BCD Minutes Accuracy: >93%
- Temporal Consistency: >95% minute-to-minute agreement

### Stretch Goals
- Overall Accuracy: >95%
- Automated adaptive tuning based on conditions
- Real-time confidence calibration monitoring
- Multi-frequency cross-validation integration

---

## Timeline

**Week 1: Baseline & Ground Truth**
- Establish ground truth periods
- Measure baseline performance
- Validate current implementation

**Week 2: Category A Parameter Tuning**
- Weight factors optimization
- Threshold tuning
- Confidence margin calibration

**Week 3: Category B Parameter Tuning**
- Integration window optimization
- Detection threshold tuning
- Validate improvements

**Week 4: Validation & Documentation**
- Multi-day continuous testing
- Cross-frequency validation
- Final parameter documentation
- Performance report generation

**Ongoing: Monitoring & Refinement**
- Weekly performance reports
- Seasonal adjustment tracking
- Long-term stability monitoring

---

## Notes

- **Parameter Coupling**: Some parameters interact (e.g., window size affects SNR, which affects threshold selection). Use hierarchical optimization.
- **Statistical Significance**: Each test should use >1000 minutes of data for statistically significant results.
- **Propagation Variability**: Test across multiple propagation conditions (strong, medium, weak signals; day/night; seasonal).
- **Computational Cost**: Grid search can be expensive - use smart sampling (Bayesian optimization) to reduce runtime.

---

**Version:** 1.0  
**Date:** November 19, 2025  
**Status:** Ready for Implementation
