# Overnight Multi-Frequency Discrimination Analysis

## Quick Start

```bash
# Run in background with nohup
nohup ./scripts/overnight_discrimination_analysis.sh > /tmp/overnight.log 2>&1 &

# Or in a screen session
screen -S discrimination
./scripts/overnight_discrimination_analysis.sh
# Ctrl+A, D to detach
```

## What It Does

### Phase 1: Reprocess 3 Frequencies × 7 Days
- **WWV 5 MHz** - Best nighttime (1-2 hop skywave)
- **WWV 10 MHz** - All-around good propagation  
- **WWV 15 MHz** - Best daytime (F2 layer)

**Total:** ~21 days worth of data, ~25,000 minutes

### Phase 2: Consolidate Results
Creates per-frequency master CSV files with all discrimination data

### Phase 3: BCD Joint Least Squares Validation
Analyzes each frequency to validate:
- ✅ Amplitude ratios show real separation (not mirroring bug)
- ✅ Significant discrimination (>40% with |ratio| >= 3 dB)
- ✅ Low near-zero ratios (<15%)

### Phase 4: Cross-Frequency Correlation
Compares discrimination agreement across frequencies:
- All 3 frequencies agree on dominant station
- Pairwise frequency agreement percentages
- Identifies propagation-dependent patterns

### Phase 5: Summary Report
Generates comprehensive summary with key findings

---

## Expected Runtime

**Estimated:** 4-8 hours total

- Phase 1 (Reprocessing): 3-6 hours (~2 min/day @ 3 frequencies)
- Phase 2 (Consolidation): 5-10 minutes
- Phase 3 (BCD Analysis): 5-10 minutes  
- Phase 4 (Cross-Frequency): 2-5 minutes
- Phase 5 (Summary): < 1 minute

---

## Output Structure

```
/tmp/grape-test/discrimination_analysis/
├── logs/
│   ├── reprocess_WWV_5_MHz_20251113.log
│   ├── reprocess_WWV_10_MHz_20251113.log
│   ├── reprocess_WWV_15_MHz_20251113.log
│   └── ... (21 reprocessing logs total)
│
├── csvs/
│   ├── discrimination_WWV_5_MHz.csv       (~10,000 minutes)
│   ├── discrimination_WWV_10_MHz.csv      (~10,000 minutes)
│   └── discrimination_WWV_15_MHz.csv      (~10,000 minutes)
│
└── reports/
    ├── SUMMARY.txt                        ← Read this first!
    ├── bcd_analysis_WWV_5_MHz.json
    ├── bcd_analysis_WWV_10_MHz.json
    └── bcd_analysis_WWV_15_MHz.json
```

---

## Success Criteria (What to Look For)

### 1. BCD Joint Least Squares Working Correctly

**Good Results:**
```
Ratio Spread: 4-6 dB           ✓ Shows real amplitude separation
Significant Separation: >40%   ✓ Clear discrimination working
Near-Zero Ratios: <15%         ✓ Not mirroring (old bug)
```

**Bad Results (Old Bug):**
```
Ratio Spread: <1 dB            ✗ Amplitude mirroring bug
Significant Separation: <10%   ✗ No real discrimination
Near-Zero Ratios: >80%         ✗ WWV_amp ≈ WWVH_amp
```

### 2. Cross-Frequency Agreement

**Expected:**
- All 3 agree: 60-80% (ionosphere affects frequencies differently)
- Pairwise 5-10 MHz: ~85% (similar propagation)
- Pairwise 10-15 MHz: ~75% (different layers)
- Pairwise 5-15 MHz: ~65% (very different paths)

**High agreement (>80%) = Reliable discrimination**
**Low agreement (<50%) = More investigation needed**

### 3. Propagation Patterns

**5 MHz:**
- Nighttime: WWV dominant (shorter groundwave + 1-hop)
- Daytime: More balanced or WWVH (skywave absorption)

**10 MHz:**
- All-day good propagation
- Most consistent discrimination

**15 MHz:**
- Daytime: Excellent F2-layer propagation
- Nighttime: Weaker signals, more variable

---

## Viewing Results

### Quick Summary
```bash
cat /tmp/grape-test/discrimination_analysis/reports/SUMMARY.txt
```

### Detailed BCD Analysis
```bash
# View JSON reports
cat /tmp/grape-test/discrimination_analysis/reports/bcd_analysis_WWV_10_MHz.json | jq '.'

# Or extract key metrics
jq '.ratio_stats, .separation_quality' \
    /tmp/grape-test/discrimination_analysis/reports/bcd_analysis_*.json
```

### Sample Data
```bash
# View first 10 rows of discrimination results
head -11 /tmp/grape-test/discrimination_analysis/csvs/discrimination_WWV_10_MHz.csv | column -t -s,
```

---

## Monitoring Progress

### Check if still running
```bash
ps aux | grep overnight_discrimination_analysis
```

### Watch progress in real-time
```bash
tail -f /tmp/overnight.log
```

### Check completion status
```bash
# Look for "ANALYSIS COMPLETE" in log
grep -c "ANALYSIS COMPLETE" /tmp/overnight.log
```

---

## What This Demonstrates

### 1. Joint Least Squares Effectiveness
- **Before:** BCD amplitudes identical (WWV_amp ≈ WWVH_amp ± 0 dB)
- **After:** Real amplitude separation with 4-6 dB spread
- **Proves:** Temporal leakage problem is solved

### 2. Multi-Method Discrimination
- BCD (100 Hz subcarrier)
- 440 Hz tone (minutes 1/2)
- Carrier tones (1000/1200 Hz)
- Tick SNR (per-second)
- **All working in concert with weighted voting**

### 3. Frequency-Dependent Propagation
- Different frequencies show different WWV/WWVH balance
- Validates physical propagation model
- Shows system adapts to ionospheric conditions

### 4. Long-Term Stability
- 7 days of continuous data
- No degradation or drift
- Consistent performance across conditions

---

## After Completion

### Next Steps:

1. **Review Summary**
   ```bash
   cat /tmp/grape-test/discrimination_analysis/reports/SUMMARY.txt
   ```

2. **Validate BCD Performance**
   - Check that ratio spread > 3 dB for all frequencies
   - Verify significant separation > 40%

3. **Create Ground Truth**
   - Use 440 Hz detections from minutes 1/2
   - Build accuracy measurement dataset

4. **Parameter Tuning**
   - If accuracy < 85%, adjust weight factors
   - If BCD separation weak, check correlation quality thresholds

5. **Compare to Old System**
   - If you have old discrimination results, compare
   - Document improvement metrics

---

## Troubleshooting

### Script Fails Early
```bash
# Check logs for specific error
cat /tmp/overnight.log

# Check if NPZ files exist for dates
find /tmp/grape-test/archives/WWV_10_MHz -name "*.npz" | head
```

### No BCD Windows Found
- Check that `wwv_bcd_encoder.py` is working
- Verify sample rate is 16 kHz
- Check template generation logs

### All Ratios Near Zero
- **This would indicate the old bug returned!**
- Check that joint least squares code is active
- Verify autocorrelation calculation

---

## Estimated Disk Usage

- Input NPZ files: ~50 GB (already exist)
- Output CSV files: ~500 MB (3 × ~170 MB)
- Log files: ~50 MB
- Report files: ~5 MB

**Total new disk usage: ~555 MB**

---

**Start Time:** Run at night before bed  
**Check Results:** Next morning  
**Expected:** Clear demonstration of discrimination improvements across multiple frequencies and propagation conditions
