# Real-Time Data Verification for GRAPE Recorder

**Date:** November 6, 2025  
**Purpose:** Continuous sanity checking without waiting for daily processing

---

## Problem Statement

You need to verify data capture is working correctly **now**, not tomorrow after daily processing. Requirements:

1. **Immediate feedback** - Know within minutes if data is good
2. **Continuous monitoring** - Not just once-per-day checks
3. **Minimal overhead** - Don't impact recording performance
4. **Actionable metrics** - Clear indicators of problems

---

## Solution: Multi-Layer Verification

### Layer 1: Packet-Level Monitoring (Real-Time)

**Already implemented** - Your V2 recorder tracks:

✅ RTP sequence numbers  
✅ Timestamp continuity  
✅ Gap detection and zero-filling  
✅ Packet loss rate  
✅ Sample count integrity  

**Monitoring:** Check `/tmp/signal-recorder-stats.json` every 60 seconds

```json
{
  "WWV_5_MHz": {
    "samples_received": 960000,
    "completeness_percent": 99.8,
    "packet_loss_percent": 0.2,
    "gaps": 2,
    "status": "healthy"
  }
}
```

**Health Criteria:**
- 🟢 Healthy: completeness ≥99%, packet_loss <1%
- 🟡 Warning: completeness 95-99%, packet_loss 1-5%
- 🔴 Error: completeness <95%, packet_loss >5%

### Layer 2: Signal Presence Check (Every Minute)

**Simple spectral check** - Verify signal energy is present:

```python
#!/usr/bin/env python3
"""
Real-time signal presence checker
Runs every minute to verify IQ data contains actual signal
"""
import numpy as np
import digital_rf as drf
from pathlib import Path
import time

def check_signal_presence(drf_path, channel='ch0', duration_seconds=10):
    """
    Quick spectral check to verify signal is present
    
    Returns:
        bool: True if signal detected, False if silent/corrupted
    """
    try:
        reader = drf.DigitalRFReader(str(drf_path))
        
        # Get latest 10 seconds of data
        bounds = reader.get_bounds(channel)
        if bounds[0] is None:
            return False
        
        # Read last 10 seconds (100 samples @ 10 Hz)
        end_sample = bounds[1]
        start_sample = end_sample - 100
        
        data = reader.read(start_sample, end_sample, channel)
        
        if len(data) == 0:
            return False
        
        # Compute power spectrum
        fft = np.fft.fft(data)
        power = np.abs(fft)**2
        
        # Check for signal energy
        mean_power = np.mean(power)
        max_power = np.max(power)
        
        # Signal should have dynamic range
        # If max/mean < 2, likely all zeros or constant
        dynamic_range = max_power / (mean_power + 1e-10)
        
        # Check for DC offset (carrier should be at DC)
        dc_power = power[0]
        total_power = np.sum(power)
        dc_fraction = dc_power / (total_power + 1e-10)
        
        # Good signal: strong DC component, good dynamic range
        has_signal = (dc_fraction > 0.1) and (dynamic_range > 2.0)
        
        print(f"DC fraction: {dc_fraction:.3f}, Dynamic range: {dynamic_range:.1f} - {'✓ SIGNAL' if has_signal else '✗ NO SIGNAL'}")
        
        return has_signal
        
    except Exception as e:
        print(f"Error checking signal: {e}")
        return False

if __name__ == '__main__':
    # Check all channels every minute
    data_root = Path('/tmp/grape-test/data')
    
    while True:
        print(f"\n{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        
        for channel_dir in data_root.glob('*/AC0G_EM38ww/*/'):
            channel_name = channel_dir.name
            if check_signal_presence(channel_dir, 'ch0', 10):
                print(f"  {channel_name}: ✓ Signal detected")
            else:
                print(f"  {channel_name}: ✗ NO SIGNAL - CHECK RADIOD!")
        
        time.sleep(60)
```

### Layer 3: WWV Tone Detection (Every Minute)

**Already implemented** - Your tone detector provides:

✅ Tone detected (yes/no)  
✅ Timing error (ms)  
✅ Signal strength (envelope level)  
✅ Tone duration (should be ~0.8s for WWV)  

**This is PERFECT for sanity checking!**

Expected behavior:
- WWV channels: Tone detected 50-100% of minutes (depends on propagation)
- Strong signal (envelope >0.05): Should detect reliably
- Weak signal (envelope <0.01): May not detect (normal)

**Alarm conditions:**
- 🔴 **No tones detected for 6 hours** - Likely receiver/antenna problem
- 🔴 **Timing error >100ms consistently** - Clock drift or processing issue
- 🟡 **Detection rate drops suddenly** - Possible propagation change or hardware issue

### Layer 4: Spectrogram Snapshots (Hourly)

**Generate quick waterfall** - Visual confirmation signal is present:

```python
#!/usr/bin/env python3
"""
Hourly spectrogram generator
Creates quick waterfall plot for visual inspection
"""
import numpy as np
import matplotlib.pyplot as plt
import digital_rf as drf
from pathlib import Path
from datetime import datetime, timedelta

def create_hourly_spectrogram(drf_path, channel='ch0', output_dir=Path('/tmp/spectrograms')):
    """
    Create 1-hour spectrogram (10 Hz bandwidth around carrier)
    
    Shows:
    - Time on X-axis (1 hour)
    - Frequency on Y-axis (±5 Hz around carrier)
    - Power in dB on color scale
    """
    try:
        reader = drf.DigitalRFReader(str(drf_path))
        
        # Get last hour of data
        bounds = reader.get_bounds(channel)
        end_sample = bounds[1]
        start_sample = end_sample - 36000  # 1 hour @ 10 Hz
        
        data = reader.read(start_sample, end_sample, channel)
        
        if len(data) < 3600:  # Need at least 10 minutes
            print("Insufficient data for spectrogram")
            return
        
        # Create spectrogram
        # NFFT=100 gives 0.1 Hz resolution
        # noverlap=90 gives good time resolution
        plt.figure(figsize=(12, 6))
        plt.specgram(data, NFFT=100, Fs=10, noverlap=90, 
                     cmap='viridis', scale='dB')
        
        plt.ylim(-5, 5)  # Focus on ±5 Hz around carrier
        plt.xlabel('Time (seconds)')
        plt.ylabel('Frequency (Hz) relative to carrier')
        plt.title(f'GRAPE Spectrogram - {channel} - {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}')
        plt.colorbar(label='Power (dB)')
        
        # Save
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M')
        output_file = output_dir / f'{channel}_{timestamp}.png'
        plt.savefig(output_file, dpi=100, bbox_inches='tight')
        plt.close()
        
        print(f"Saved spectrogram: {output_file}")
        
    except Exception as e:
        print(f"Error creating spectrogram: {e}")

if __name__ == '__main__':
    data_root = Path('/tmp/grape-test/data')
    
    for channel_dir in data_root.glob('*/AC0G_EM38ww/*/'):
        channel_name = channel_dir.name
        create_hourly_spectrogram(channel_dir, 'ch0', 
                                  Path(f'/tmp/spectrograms/{channel_name}'))
```

---

## Recommended Monitoring Dashboard

### Real-Time Health Display

Create simple web dashboard that shows:

```
GRAPE Recorder Health - 2025-11-06 11:42 UTC

Channel        Signal   Tone   Completeness   Packet Loss   Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WWV_2_5        ✓ Yes    ✗ No      99.2%          0.8%       🟢 Healthy
WWV_5          ✓ Yes    ✓ Yes     99.8%          0.2%       🟢 Healthy  
WWV_10         ✓ Yes    ✓ Yes     99.9%          0.1%       🟢 Healthy
WWV_15         ✓ Yes    ✗ No      98.1%          1.9%       🟡 Warning
WWV_20         ✗ No     ✗ No      45.2%         54.8%       🔴 ERROR
CHU_3_33       ✓ Yes    ✗ No      99.5%          0.5%       🟢 Healthy

Last WWV Tone Detections:
  WWV_5:  11:42:01 UTC (timing error: +2.3 ms, envelope: 0.082)
  WWV_10: 11:42:00 UTC (timing error: -1.8 ms, envelope: 0.124)

Spectrograms: [View Last Hour] [View Last 24 Hours]
```

### Implementation

You already have most of this! Just need to:

1. **Add signal presence check** (Layer 2 script above)
2. **Enable WWV tone logging** (already works, just expose in dashboard)
3. **Add spectrogram generation** (Layer 4 script above)
4. **Update web UI** to display all metrics

---

## Quick Verification Script

**Run this NOW to verify current data:**

```bash
#!/bin/bash
# quick-verify.sh - Immediate sanity check

echo "GRAPE Data Verification - $(date -u)"
echo "======================================"
echo ""

# Check 1: Stats file exists and recent
if [ -f /tmp/signal-recorder-stats.json ]; then
    echo "✓ Stats file found"
    age=$(($(date +%s) - $(stat -c %Y /tmp/signal-recorder-stats.json)))
    if [ $age -lt 120 ]; then
        echo "  Age: ${age}s (recent)"
    else
        echo "  ⚠ Age: ${age}s (stale - recorder may not be running)"
    fi
    echo ""
    echo "Current stats:"
    jq '.' /tmp/signal-recorder-stats.json 2>/dev/null || cat /tmp/signal-recorder-stats.json
else
    echo "✗ No stats file - recorder not running?"
fi

echo ""
echo "======================================"

# Check 2: Digital RF files exist
echo "Digital RF files created today:"
find /tmp/grape-test/data/$(date -u +%Y%m%d) -name "*.h5" 2>/dev/null | head -5
echo ""

# Check 3: WWV timing log
if [ -f /tmp/grape-test/analytics/timing/wwv_timing.csv ]; then
    echo "Recent WWV tone detections:"
    tail -5 /tmp/grape-test/analytics/timing/wwv_timing.csv
else
    echo "No WWV timing log found"
fi

echo ""
echo "======================================"
echo "Quick signal check (reading last 10 samples):"

python3 << 'EOF'
import digital_rf as drf
from pathlib import Path
import numpy as np

data_root = Path('/tmp/grape-test/data')
date_str = Path.cwd().name

for channel_dir in sorted(data_root.glob(f'*/AC0G_EM38ww/*/')):
    channel = channel_dir.name
    try:
        reader = drf.DigitalRFReader(str(channel_dir))
        bounds = reader.get_bounds('ch0')
        if bounds[0] is not None:
            # Read last 10 samples
            data = reader.read(bounds[1]-10, bounds[1], 'ch0')
            power = np.mean(np.abs(data)**2)
            print(f"  {channel:15s}: {len(data):3d} samples, power={power:.6f}")
        else:
            print(f"  {channel:15s}: No data")
    except Exception as e:
        print(f"  {channel:15s}: Error - {e}")
EOF
```

**Make it executable and run:**
```bash
chmod +x quick-verify.sh
./quick-verify.sh
```

---

## Continuous Monitoring Cron Job

Add to crontab:
```cron
# Every 5 minutes: Check signal presence
*/5 * * * * /home/mjh/git/signal-recorder/scripts/check_signal_presence.py

# Every hour: Generate spectrogram
0 * * * * /home/mjh/git/signal-recorder/scripts/create_hourly_spectrogram.py

# Daily at 00:05: Full validation
5 0 * * * /home/mjh/git/signal-recorder/scripts/daily_validation.sh
```

---

## Summary: Verification Strategy

| Layer | Frequency | What | Alert If |
|-------|-----------|------|----------|
| **Packet stats** | 60s | Completeness, gaps | <99% for 10 min |
| **Signal presence** | 5min | Spectral energy | No signal for 30 min |
| **WWV tone** | 1min | Tone detection | No tones for 6 hours on any strong channel |
| **Spectrogram** | 1hour | Visual waterfall | Manual review |
| **Full validation** | Daily | Complete dataset check | Any structural errors |

**Bottom line:** You can know within **5-10 minutes** if something is wrong, not 24 hours later!

---

## Next Steps

1. ✅ Run `quick-verify.sh` NOW to check current data
2. ⏭ Implement signal presence check (5-minute cron)
3. ⏭ Add spectrogram generation (hourly)
4. ⏭ Update web UI to show all metrics in real-time
5. ⏭ Set up alerts (email/SMS) for critical failures

The WWV tone detection you already have is GOLD for real-time validation!
