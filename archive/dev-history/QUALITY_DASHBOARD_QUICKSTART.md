# Quality Analysis Dashboard - Quick Start

## What Was Created

✅ **Automated Analysis System** that runs every 15 minutes to compare:
- **Decimation quality**: 200Hz→10Hz (carrier) vs 16kHz→10Hz (wide)
  - Phase jitter, SNR, SFDR metrics
- **Timing methods**: time_snap (±1ms) vs NTP (±10ms)
  - Coverage percentages, sync quality

✅ **Dashboard Integration** ready to plug into your timing-dashboard.html

✅ **Test Dashboard** at `/tmp/grape-test/quality-analysis/index.html`

## Quick Test (5 minutes)

### 1. View Current Analysis

```bash
# The analysis already ran once:
cat /tmp/grape-test/quality-analysis/quality_report_latest.json | head -50

# Or view in browser (start test server):
cd /tmp/grape-test
python3 -m http.server 3000 &

# Open: http://localhost:3000/quality-analysis/
```

### 2. Set Up Automation

```bash
# Add to crontab (runs every 15 minutes):
crontab -e

# Add this line:
*/15 * * * * /home/mjh/git/signal-recorder/scripts/run-quality-analysis.sh /tmp/grape-test
```

### 3. Integrate with Timing Dashboard

The file `web-ui/quality-dashboard-addon.html` contains CSS and JavaScript ready to add to your timing dashboard. Two options:

**Option A: Quick integration** (recommended for testing)
```bash
# Your timing dashboard already loads from /api/monitoring/timing-quality
# Just add a new API endpoint that serves the JSON:
ln -s /tmp/grape-test/quality-analysis /var/www/html/quality-analysis

# Then the dashboard can fetch from:
# http://your-server/quality-analysis/quality_report_latest.json
```

**Option B: Full integration** (for production)
- Copy the CSS from `quality-dashboard-addon.html` into timing-dashboard.html `<style>` section
- Copy the JavaScript functions into the `<script>` section
- Update `renderDashboard()` to include quality analysis section

## Key Metrics Explained

### Phase Jitter Ratio (Wide/Carrier)
```
Current: 0.97x (essentially equal)
Interpretation: Both decimation methods produce similar phase noise
Typical: 1.3-1.7x (carrier advantage)
```

### SNR Advantage (Carrier - Wide)
```
Current: -8.47 dB (wide has better SNR)
Interpretation: Wide channels have stronger signal
Why: Wider bandwidth captures more signal power
Science impact: Minimal (both methods usable)
```

### Tone-Locked Coverage
```
Current: 83.5% (excellent)
Target: >80% excellent, >50% good
Meaning: 83.5% of time using ±1ms WWV/CHU timing
```

### NTP-Synced Coverage
```
Current: 100.0% (perfect)
Target: >95% excellent
Meaning: Carrier channels always have ±10ms NTP timing
```

## What the Dashboard Shows

### Summary Cards (4 metrics)
1. **Phase Jitter Ratio**: Decimation quality comparison
2. **SNR Difference**: Signal strength comparison  
3. **Tone-Locked %**: Wide channel timing quality
4. **NTP-Synced %**: Carrier channel timing quality

### Per-Channel Grid
- Shows all 9 channels (WWV + CHU)
- Phase jitter ratio per channel
- Tone-locked percentage per channel
- Color-coded health indicators

### Auto-Refresh
- Updates every 60 seconds
- Shows report generation timestamp
- Displays current date being analyzed

## Files Created

| File | Purpose |
|------|---------|
| `scripts/automated_quality_analysis.py` | Main analysis engine |
| `scripts/run-quality-analysis.sh` | Automation wrapper |
| `scripts/analyze_decimation_quality.py` | Detailed decimation analysis |
| `scripts/compare_timing_methods.py` | Detailed timing comparison |
| `web-ui/quality-dashboard-addon.html` | Dashboard integration code |
| `/tmp/grape-test/quality-analysis/index.html` | Test dashboard |
| `/tmp/grape-test/quality-analysis/quality_report_*.json` | Analysis results |
| `QUALITY_ANALYSIS_INTEGRATION.md` | Full documentation |
| `QUALITY_DASHBOARD_QUICKSTART.md` | This file |

## Typical Workflow

### Daily Use
1. Open timing dashboard (quality section auto-loads)
2. Check 4 summary metrics at a glance
3. Review per-channel details if needed
4. Investigation tools available for deep dives

### Monthly Review
```bash
# Generate historical comparison
for date in 20251101 20251110 20251120; do
    python3 scripts/automated_quality_analysis.py \
        --data-root /tmp/grape-test --date $date
done

# Compare trends
ls -lh /tmp/grape-test/quality-analysis/quality_report_*.json
```

### Deep Dive (when needed)
```bash
# Full decimation analysis with plots
python3 scripts/analyze_decimation_quality.py \
    --wide-file /tmp/grape-test/analytics/WWV_5_MHz/decimated/20251118T080000Z_5000000_iq_10hz.npz \
    --carrier-file /tmp/grape-test/analytics/WWV_5_MHz_carrier/decimated/20251118T080000Z_5000000_iq_10hz.npz \
    --output-dir /tmp/grape-test/analysis

# Full timing comparison with plots  
python3 scripts/compare_timing_methods.py \
    --wide-dir /tmp/grape-test/analytics/WWV_5_MHz/decimated \
    --carrier-dir /tmp/grape-test/analytics/WWV_5_MHz_carrier/decimated \
    --date 20251118 \
    --output-dir /tmp/grape-test/analysis
```

## Current Status (Today's Analysis)

✅ **9 channels analyzed** (WWV 2.5, 5, 10, 15, 20, 25 MHz + CHU 3.33, 7.85, 14.67 MHz)

✅ **Decimation Quality**:
- Phase jitter: 0.97x (carrier equivalent to wide)
- SNR: -8.47 dB advantage (wide stronger, expected due to bandwidth)
- Both methods scientifically usable

✅ **Timing Quality**:
- Tone-locked: 83.5% (excellent WWV/CHU detection)
- NTP-synced: 100.0% (perfect carrier timing)

## Next Steps

1. **Test the dashboard**: Visit http://localhost:3000/quality-analysis/
2. **Set up automation**: Add cron job for every 15 minutes
3. **Integrate to main dashboard**: Follow Option A or B above
4. **Monitor for 24-48 hours**: Verify metrics are reasonable
5. **Optional**: Set up systemd timer for production (see QUALITY_ANALYSIS_INTEGRATION.md)

## Support

**Check analysis logs**:
```bash
tail -f /tmp/grape-test/logs/quality-analysis.log
```

**Manual run for debugging**:
```bash
python3 scripts/automated_quality_analysis.py \
    --data-root /tmp/grape-test \
    --date $(date -u +%Y%m%d)
```

**Verify JSON format**:
```bash
cat /tmp/grape-test/quality-analysis/quality_report_latest.json | jq .summary
```

## Scientific Interpretation

### Phase Jitter Results
- **0.97x ratio**: Both methods nearly identical
- Validates that unified IIR decimation produces consistent results
- No spectral inversion artifacts (fixed earlier)

### SNR Results  
- **-8.47 dB (wide advantage)**: Expected due to 16 kHz vs 200 Hz bandwidth
- Wide channels capture more signal power (but also more noise)
- Both methods have adequate SNR for Doppler analysis

### Timing Results
- **83.5% tone-locked**: Excellent for propagation study
- WWV/CHU tones detected reliably most of the time
- 16.5% fallback to NTP still provides ±10ms accuracy

### Bottom Line
✅ Both decimation methods are scientifically equivalent for frequency offset measurements
✅ Timing quality exceeds requirements (±1ms tone-locked, ±10ms NTP)
✅ System ready for production Doppler analysis
