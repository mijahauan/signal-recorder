# Quality Analysis Dashboard Integration

## Overview

Automated quality analysis system that quantifies:
1. **Decimation Quality**: 200Hz→10Hz vs 16kHz→10Hz comparison
2. **Timing Methods**: time_snap (TONE_LOCKED) vs NTP (NTP_SYNCED) comparison

Results are automatically published to the timing & quality dashboard every 15 minutes.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Decimated NPZ Files                        │
│  analytics/{channel}/decimated/*.npz                     │
│  (IQ data + timing_metadata + quality_metadata)         │
└────────────────┬────────────────────────────────────────┘
                 │
                 ├─────────────────┐
                 │                 │
        ┌────────▼─────────┐  ┌───▼───────────────────┐
        │  Wide Channels   │  │  Carrier Channels    │
        │  16kHz→10Hz (IIR)│  │  200Hz→10Hz (IIR)    │
        └────────┬─────────┘  └───┬───────────────────┘
                 │                │
                 │  Automated Analysis (every 15 min)
                 │                │
        ┌────────▼────────────────▼──────────┐
        │  automated_quality_analysis.py     │
        │  • Phase jitter comparison         │
        │  • SNR/SFDR comparison            │
        │  • Timing distribution stats       │
        │  • Cross-correlation analysis      │
        └────────┬───────────────────────────┘
                 │
                 ▼
        ┌─────────────────────────┐
        │  quality_report_*.json  │
        │  quality_report_latest.json │
        └────────┬────────────────────┘
                 │
                 ▼
        ┌─────────────────────────┐
        │  timing-dashboard.html  │
        │  • Displays metrics     │
        │  • Per-channel details  │
        │  • Auto-refreshes       │
        └─────────────────────────┘
```

## Setup Instructions

### 1. Make Scripts Executable

```bash
chmod +x scripts/automated_quality_analysis.py
chmod +x scripts/run-quality-analysis.sh
```

### 2. Test Manual Run

```bash
# Test for today's data
python3 scripts/automated_quality_analysis.py \
    --data-root /tmp/grape-test \
    --date $(date -u +%Y%m%d)

# Verify output
ls -lh /tmp/grape-test/quality-analysis/
cat /tmp/grape-test/quality-analysis/quality_report_latest.json
```

### 3. Set Up Automated Execution

#### Option A: systemd timer (Recommended for production)

Create `/etc/systemd/system/grape-quality-analysis.service`:
```ini
[Unit]
Description=GRAPE Quality Analysis
After=network.target

[Service]
Type=oneshot
User=mjh
WorkingDirectory=/home/mjh/git/signal-recorder
ExecStart=/home/mjh/git/signal-recorder/scripts/run-quality-analysis.sh /var/lib/signal-recorder
StandardOutput=append:/var/lib/signal-recorder/logs/quality-analysis.log
StandardError=append:/var/lib/signal-recorder/logs/quality-analysis.log
```

Create `/etc/systemd/system/grape-quality-analysis.timer`:
```ini
[Unit]
Description=Run GRAPE Quality Analysis every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
AccuracySec=1min

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable grape-quality-analysis.timer
sudo systemctl start grape-quality-analysis.timer

# Check status
sudo systemctl status grape-quality-analysis.timer
sudo systemctl list-timers | grep grape
```

#### Option B: cron (Test mode)

```bash
# Edit crontab
crontab -e

# Add line (runs every 15 minutes):
*/15 * * * * /home/mjh/git/signal-recorder/scripts/run-quality-analysis.sh /tmp/grape-test
```

### 4. Integrate with Web Dashboard

#### Method 1: Patch timing-dashboard.html directly

```bash
cd /home/mjh/git/signal-recorder

# Backup existing dashboard
cp web-ui/timing-dashboard.html web-ui/timing-dashboard.html.backup

# The addon file contains CSS and JavaScript to add
# You'll need to manually integrate it into timing-dashboard.html
```

Add the contents of `web-ui/quality-dashboard-addon.html`:
1. **CSS**: Insert the styles into the `<style>` section (around line 200)
2. **JavaScript functions**: Add `fetchQualityAnalysis()` and `renderQualityAnalysis()` to the script section
3. **Update renderDashboard()**: Replace the function to include quality analysis (as shown in addon)

#### Method 2: Test standalone (quick verification)

Create a simple test dashboard:
```html
<!DOCTYPE html>
<html>
<head>
    <title>Quality Analysis Test</title>
    <script>
        async function loadAnalysis() {
            const response = await fetch('/quality-analysis/quality_report_latest.json');
            const data = await response.json();
            document.getElementById('output').textContent = JSON.stringify(data, null, 2);
        }
        loadAnalysis();
    </script>
</head>
<body>
    <h1>Quality Analysis</h1>
    <pre id="output">Loading...</pre>
</body>
</html>
```

### 5. Configure Web Server

Ensure your web server serves the quality-analysis directory:

#### For nginx:
```nginx
location /quality-analysis/ {
    alias /tmp/grape-test/quality-analysis/;
    autoindex on;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
}
```

#### For Python http.server (test mode):
```bash
cd /tmp/grape-test
python3 -m http.server 3000
# Access at http://localhost:3000/quality-analysis/quality_report_latest.json
```

## Metrics Explained

### Decimation Quality Metrics

#### Phase Jitter Ratio (Wide/Carrier)
- **Definition**: Ratio of high-frequency phase noise between methods
- **Interpretation**: 
  - `> 1.0`: Carrier (200Hz→10Hz) has less noise (better)
  - `< 1.0`: Wide (16kHz→10Hz) has less noise (better)
  - Typical: 1.3-1.7× (carrier advantage)
- **Scientific Impact**: Lower jitter = more precise Doppler measurements

#### SNR Difference (Carrier - Wide)
- **Definition**: Peak signal-to-noise ratio difference
- **Interpretation**:
  - Positive: Carrier has better SNR
  - Negative: Wide has better SNR
  - Typical: -2 to +2 dB (equivalent)
- **Scientific Impact**: Minimal practical difference (<2 dB)

#### SFDR (Spurious-Free Dynamic Range)
- **Definition**: Distance from peak to largest spurious peak
- **Interpretation**:
  - Higher is better (cleaner spectrum)
  - Typical: 25-30 dB for both methods
- **Scientific Impact**: Shows decimation artifacts are well-suppressed

### Timing Quality Metrics

#### Tone-Locked Coverage (Wide Channels)
- **Definition**: Percentage of samples with TONE_LOCKED timing
- **Accuracy**: ±1 ms (from WWV/CHU tone detection)
- **Target**: >80% (excellent), >50% (good)
- **Factors**: Propagation conditions, signal strength

#### NTP-Synced Coverage (Carrier Channels)
- **Definition**: Percentage of samples with NTP_SYNCED timing
- **Accuracy**: ±10 ms (from system NTP)
- **Target**: >95% (excellent), >80% (good)
- **Factors**: NTP server quality, network stability

#### Time Snap Age
- **Definition**: Seconds since last WWV/CHU tone detection
- **Interpretation**:
  - <300s: Fresh, TONE_LOCKED quality
  - 300-3600s: Aged, INTERPOLATED quality
  - >3600s: Stale, falls back to NTP/WALL_CLOCK
- **Drift**: ~1 ms/hour for aged time_snap

#### NTP Offset
- **Definition**: System clock offset from NTP servers
- **Interpretation**:
  - <10 ms: Excellent sync
  - 10-100 ms: Good sync, usable
  - >100 ms: Poor sync, investigate
- **Monitor**: Standard deviation (should be <5 ms)

## Dashboard Display

The quality analysis section shows:

1. **Summary Cards**: Four key metrics
   - Phase jitter ratio (decimation quality)
   - SNR difference (decimation quality)
   - Tone-locked coverage (timing quality)
   - NTP-synced coverage (timing quality)

2. **Per-Channel Details**: Grid of all channels showing
   - Phase jitter ratio
   - Tone-locked percentage
   - Color-coded health indicators

3. **Auto-Updates**: Refreshes every 60 seconds with dashboard

## Troubleshooting

### No quality report generated

```bash
# Check if carrier analytics are running
ps aux | grep "analytics.*carrier"

# Verify decimated files exist
ls /tmp/grape-test/analytics/WWV_5_MHz_carrier/decimated/

# Run analysis manually with verbose output
python3 scripts/automated_quality_analysis.py \
    --data-root /tmp/grape-test \
    --date $(date -u +%Y%m%d)
```

### Dashboard shows "No quality data"

```bash
# Verify JSON file exists and is readable
ls -lh /tmp/grape-test/quality-analysis/quality_report_latest.json
cat /tmp/grape-test/quality-analysis/quality_report_latest.json | jq .

# Check web server configuration
curl http://localhost:3000/quality-analysis/quality_report_latest.json
```

### Old data shown

```bash
# Check last run time
ls -lt /tmp/grape-test/quality-analysis/

# Force immediate update
./scripts/run-quality-analysis.sh /tmp/grape-test

# Verify timer is running (systemd)
sudo systemctl status grape-quality-analysis.timer
journalctl -u grape-quality-analysis.service -n 50
```

## Performance Notes

- **Analysis runtime**: ~5-15 seconds per run (9 channel pairs)
- **Disk usage**: ~50 KB per daily report
- **CPU impact**: Minimal (only during 15-minute runs)
- **Memory**: <200 MB peak during analysis

## Future Enhancements

Potential additions:
1. Historical trend graphs (phase jitter over time)
2. Correlation coefficient between wide/carrier
3. Frequency offset tracking
4. Alert generation for degraded quality
5. Export to Prometheus metrics for Grafana

## Files Created

- `scripts/automated_quality_analysis.py`: Main analysis engine
- `scripts/run-quality-analysis.sh`: Automation wrapper
- `web-ui/quality-dashboard-addon.html`: Dashboard integration code
- `QUALITY_ANALYSIS_INTEGRATION.md`: This documentation

## References

- `scripts/analyze_decimation_quality.py`: Detailed decimation analysis
- `scripts/compare_timing_methods.py`: Detailed timing comparison
- `CARRIER_CHANNEL_ANALYTICS_IMPLEMENTATION.md`: Timing architecture
- `docs/TIMING_QUALITY_FRAMEWORK.md`: Timing quality levels
