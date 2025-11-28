# Coherent Integration Upgrade Guide

## What Changed

The discrimination analysis now includes **true coherent integration** with phase tracking for the 5ms tick tones, providing:
- **10 dB SNR gain** (instead of 5 dB) when ionosphere is stable
- **Coherence quality metrics** measuring ionospheric phase stability
- **Automatic fallback** to incoherent integration when phase is unstable
- **59 ticks analyzed per minute** (seconds 1-59, excluding second 0 which contains the 800ms tone marker)

## Reprocessing Existing Data

To regenerate discrimination CSVs with the new coherent integration data:

### Option 1: Interactive Script (Easiest)

```bash
./REPROCESS-DISCRIMINATION.sh
```

This will guide you through reprocessing:
1. Today only
2. Specific date
3. Date range
4. All available data

### Option 2: Command Line (Flexible)

```bash
# Reprocess specific date
python3 scripts/reprocess_discrimination.py --date 20251119 --channel "WWV 10 MHz"

# Reprocess date range
python3 scripts/reprocess_discrimination.py \
  --start-date 20251118 \
  --end-date 20251119 \
  --channel "WWV 10 MHz"

# Reprocess all available data
python3 scripts/reprocess_discrimination.py --all --channel "WWV 10 MHz"

# Keep existing data (append mode)
python3 scripts/reprocess_discrimination.py \
  --date 20251119 \
  --channel "WWV 10 MHz" \
  --keep-existing
```

### Other Channels

```bash
# WWV 2.5 MHz
python3 scripts/reprocess_discrimination.py --all --channel "WWV 2.5 MHz"

# WWV 5 MHz
python3 scripts/reprocess_discrimination.py --all --channel "WWV 5 MHz"

# WWV 15 MHz
python3 scripts/reprocess_discrimination.py --all --channel "WWV 15 MHz"
```

## What Gets Updated

The reprocessing script:
1. ✅ Finds all NPZ archives in the specified date range
2. ✅ Deletes existing discrimination CSV files (unless --keep-existing)
3. ✅ Re-runs tone detection on each archive
4. ✅ Re-runs discrimination analysis with **new coherent integration**
5. ✅ Generates new CSV files with all coherent integration fields:
   - `coherent_wwv_snr_db`, `coherent_wwvh_snr_db`
   - `incoherent_wwv_snr_db`, `incoherent_wwvh_snr_db`
   - `coherence_quality_wwv`, `coherence_quality_wwvh`
   - `integration_method` ('coherent', 'incoherent', or 'none')

## Viewing Results

### Web UI

Open discrimination page in your browser:
```
http://localhost:3000/discrimination.html
```

The existing 3-panel visualization will automatically display the new data!

### API

Check the tick window data via API:
```bash
# Get discrimination data for today
curl http://localhost:3000/api/v1/channels/WWV%2010%20MHz/discrimination/$(date -u +%Y%m%d) | jq .

# Check first tick window
curl -s http://localhost:3000/api/v1/channels/WWV%2010%20MHz/discrimination/$(date -u +%Y%m%d) | \
  jq '.data[0].tick_windows_10sec[0]'
```

Expected output:
```json
{
  "second": 1,
  "wwv_snr_db": 48.3,
  "wwvh_snr_db": 44.1,
  "ratio_db": 4.2,
  "coherent_wwv_snr_db": 48.3,
  "coherent_wwvh_snr_db": 44.1,
  "incoherent_wwv_snr_db": 38.1,
  "incoherent_wwvh_snr_db": 34.0,
  "coherence_quality_wwv": 0.87,
  "coherence_quality_wwvh": 0.82,
  "integration_method": "coherent",
  "tick_count": 10
}
```

### CSV Files

View raw CSV data:
```bash
# Today's discrimination data
tail /tmp/grape-test/analytics/WWV_10_MHz/discrimination/WWV_10_MHz_discrimination_$(date -u +%Y%m%d).csv

# Check for coherent integration fields
head -n1 /tmp/grape-test/analytics/WWV_10_MHz/discrimination/WWV_10_MHz_discrimination_$(date -u +%Y%m%d).csv | grep -o "tick_windows_10sec"
```

## Performance

**Processing speed**: ~6-10 files per second
- 1 hour of data (~60 files): ~10 seconds
- 1 day of data (~1440 files): ~3-4 minutes
- 1 week of data: ~20-30 minutes

## Real-Time Processing

Once reprocessing is complete, new data will automatically use coherent integration:

```bash
# Restart services to activate coherent integration for new data
./stop-dual-service.sh
./start-dual-service.sh

# Watch logs for coherent integration
journalctl -u grape-analytics-service -f | grep -E "COHERENT|INCOHERENT"
```

Expected log output:
```
COHERENT - sec 1-10: WWV=48.3dB, WWVH=44.1dB (coherence: WWV=0.87, WWVH=0.82, 10 ticks)
Tick analysis - 6/6 windows valid, 6/6 coherent, avg ratio: +4.3dB, coherence: WWV=0.89 WWVH=0.84
```

## Troubleshooting

### No NPZ files found

Check that archives exist:
```bash
ls -lh /tmp/grape-test/archives/WWV_10_MHz/*.npz | head
```

### Import errors

Ensure you're in the correct directory:
```bash
cd /home/mjh/git/signal-recorder
python3 scripts/reprocess_discrimination.py --help
```

### Slow processing

Large datasets take time. Use specific dates:
```bash
# Just reprocess today
python3 scripts/reprocess_discrimination.py --date $(date -u +%Y%m%d) --channel "WWV 10 MHz"
```

## What to Expect

### Stable Ionosphere (Daytime, Quiet Conditions)
- **Coherent method**: Used for most/all windows
- **Coherence quality**: 0.7-0.95
- **SNR gain**: Full 10 dB (coherent vs incoherent)
- **Log**: "COHERENT" for 6/6 windows

### Disturbed Ionosphere (Storms, Scintillation)
- **Incoherent method**: Automatic fallback
- **Coherence quality**: 0.2-0.6
- **SNR gain**: 5 dB (incoherent only)
- **Log**: Mix of "COHERENT" and "INCOHERENT"

### Transition Periods (Dawn/Dusk)
- **Mixed methods**: Some coherent, some incoherent
- **Coherence quality**: Varies rapidly
- **Scientific value**: Captures ionospheric instability!

## Scientific Benefits

With reprocessed data you can now:
1. **Measure coherence time**: Direct from quality metric
2. **Detect weak signals**: 10 dB gain = 10× more sensitive
3. **Track phase stability**: Window-by-window coherence
4. **Classify propagation**: Stable vs disturbed ionosphere
5. **Correlate with space weather**: Coherence vs Kp index

## Next Steps

After reprocessing:
1. View discrimination.html to see the updated 3-panel display
2. Compare coherent vs incoherent SNR values
3. Look for patterns in coherence quality over the day
4. Identify periods of stable vs unstable ionosphere

**Happy analyzing!** 🚀
