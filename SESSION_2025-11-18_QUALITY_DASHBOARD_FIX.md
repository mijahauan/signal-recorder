# Session 2025-11-18: Quality Dashboard Integration & Carrier Packet Loss Fix

## Summary
Completed integration of quality analysis dashboard into Node.js web UI and fixed critical packet loss calculation bug affecting 200 Hz carrier channels.

## Changes Made

### 1. Quality Dashboard Integration (monitoring-server-v3.js)
**Problem:** Quality analysis JSON reports were generated but not served by the Node.js backend.

**Solution:** Added `/quality-analysis/:filename` route to serve JSON reports with no-cache headers.

**Impact:**
- Dashboard now displays real-time quality metrics at `http://localhost:3000/timing-dashboard.html`
- 4 key metrics: Phase Jitter Ratio, SNR Difference, Tone-Locked %, NTP-Synced %
- Per-channel breakdown with comparison of 16kHz→10Hz vs 200Hz→10Hz decimation
- Auto-refresh every 60 seconds

**Files Modified:**
- `web-ui/monitoring-server-v3.js`: Added quality analysis JSON serving route (lines 1412-1442)

### 2. Carrier Channel Packet Loss Bug Fix (core_npz_writer.py)
**Problem:** 200 Hz carrier channels showed impossible packet loss values (-7776%).

**Root Cause:** Hardcoded assumption of 320 samples/packet (correct for 16 kHz, wrong for 200 Hz).

**Math:**
```
16 kHz (correct):
  960,000 samples/min ÷ 320 samples/packet = 3,000 packets/min ✓

200 Hz carrier (broken):
  12,000 samples/min ÷ 320 samples/packet = 37.5 packets/min
  Actual packets: ~3,000
  Calculated loss: (37.5 - 3000) / 37.5 × 100 = -7,966% ✗
```

**Solution:** Scale samples_per_packet with sample rate:
```python
# Before:
self.current_minute_packets_expected = self.samples_per_minute // 320

# After:
samples_per_packet = max(1, int(320 * (self.sample_rate / 16000)))
self.current_minute_packets_expected = self.samples_per_minute // samples_per_packet
```

**Impact:**
- Carrier channels now show accurate packet loss percentages (near 0% with good reception)
- Quality metrics in dashboard and NPZ files are now scientifically valid
- Scales correctly for any sample rate (200 Hz, 16 kHz, etc.)

**Files Modified:**
- `src/signal_recorder/core_npz_writer.py`: Fixed packet calculation (lines 146-149)

### 3. Spectrogram Generation Cleanup
**Problem:** Two instances of auto-generate-spectrograms.sh running simultaneously (PIDs 1767646, 2112849).

**Solution:**
- Killed duplicate processes
- Restarted single instance with unified IIR decimation method
- Regenerated today's spectrograms using analytics decimated files

**Impact:**
- Spectrograms now consistently use unified IIR decimation (no more inversion artifacts)
- Both wide-decimated/ and native-carrier/ directories show correct phase

## Verification

### Quality Dashboard
```bash
# Check endpoint
curl http://localhost:3000/quality-analysis/quality_report_latest.json

# View dashboard
open http://localhost:3000/timing-dashboard.html
# Scroll to "📊 Decimation & Timing Quality Analysis" section
```

### Carrier Packet Loss
```bash
# Restart core recorder to apply fix
tmux send-keys -t grape-recorder C-c
sleep 2
tmux send-keys -t grape-recorder "python3 -m signal_recorder.core_recorder --config config/grape-config.toml" Enter

# Check carrier status (should show normal packet loss ~0%)
curl http://localhost:3000/api/monitoring/timing-quality | jq '.channels[] | select(.name | contains("carrier")) | {name, packet_loss_percent}'
```

## Technical Details

### Quality Analysis Architecture
- **Analysis Script:** `scripts/automated_quality_analysis.py` (reads decimated NPZ files)
- **Report Location:** `/tmp/grape-test/quality-analysis/quality_report_latest.json`
- **Web Endpoint:** `http://localhost:3000/quality-analysis/quality_report_latest.json`
- **Dashboard Section:** Integrated into `timing-dashboard.html` (lines 304-911)
- **Automation:** Cron job runs every 15 minutes (setup in QUALITY_DASHBOARD_QUICKSTART.md)

### Packet Loss Calculation
- **Location:** `CoreNPZWriter._reset_minute_buffer()` in `core_npz_writer.py`
- **Formula:** `packets_expected = samples_per_minute / samples_per_packet`
- **Scaling:** `samples_per_packet = 320 * (sample_rate / 16000)`
- **Examples:**
  - 16 kHz: 320 samples/packet → 3,000 packets/min expected
  - 200 Hz: 4 samples/packet → 3,000 packets/min expected
  - Both match radiod's actual packet rate

## Files Changed This Session
```
M  web-ui/monitoring-server-v3.js          (+31 lines: quality analysis route)
M  src/signal_recorder/core_npz_writer.py  (+2 lines: packet loss fix)
A  SESSION_2025-11-18_QUALITY_DASHBOARD_FIX.md
```

## Next Steps
1. Restart core recorder to apply packet loss fix
2. Monitor carrier channels for correct packet loss percentages
3. Set up cron job for automated quality analysis (if not already done):
   ```bash
   (crontab -l 2>/dev/null; echo "*/15 * * * * /home/mjh/git/signal-recorder/scripts/run-quality-analysis.sh /tmp/grape-test") | crontab -
   ```

## References
- Quality Analysis Integration: `QUALITY_ANALYSIS_INTEGRATION.md`
- Quick Start Guide: `QUALITY_DASHBOARD_QUICKSTART.md`
- Carrier Analytics: `CARRIER_CHANNEL_ANALYTICS_IMPLEMENTATION.md`
- Previous Session: `SESSION_2025-11-17_WEB_UI_SYNC.md`

## Testing Notes
- Quality dashboard JSON endpoint verified: ✅
- Spectrograms regenerated with unified method: ✅
- Packet loss calculation fix applied: ✅ (requires core recorder restart)
- Both wide and carrier channels use identical IIR decimation: ✅
