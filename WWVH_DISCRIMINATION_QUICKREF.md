# WWV-H Discrimination Quick Reference

## What Was Fixed

✅ **WWVH Detection Limited to Correct Frequencies**
- Before: WWVH (1200 Hz) detected on ALL WWV channels
- After: WWVH only on 2.5, 5, 10, 15 MHz (where it actually broadcasts)
- WWV 20 & 25 MHz now correctly ignore WWVH

✅ **440 Hz Tone Detection Integrated**
- Before: Code existed but never called
- After: Fully integrated into analytics pipeline
- Minute 1 → Detects WWVH 440 Hz tone (:15-:59)
- Minute 2 → Detects WWV 440 Hz tone (:15-:59)

✅ **Enhanced CSV Output**
- Before: Only 1000/1200 Hz data
- After: Complete discrimination with all 3 methods
- Ready for web UI visualization

## Three Discrimination Methods

| Method | Frequency | When | Output |
|--------|-----------|------|--------|
| **Power Ratio** | 1000 vs 1200 Hz | Every minute | `power_ratio_db` |
| **Delay** | Both | When both detected | `differential_delay_ms` |
| **440 Hz ID** | 440 Hz | Min 1 (WWVH), Min 2 (WWV) | `tone_440hz_*_detected` |

## CSV Output Format

```csv
timestamp_utc,minute_timestamp,minute_number,
wwv_detected,wwvh_detected,
wwv_power_db,wwvh_power_db,power_ratio_db,
differential_delay_ms,
tone_440hz_wwv_detected,tone_440hz_wwv_power_db,
tone_440hz_wwvh_detected,tone_440hz_wwvh_power_db,
dominant_station,confidence
```

## CSV Location

`/tmp/grape-test/analytics/{CHANNEL}/discrimination_logs/{CHANNEL}_discrimination_{DATE}.csv`

**Examples:**
- `WWV_2.5_MHz_discrimination_20251116.csv`
- `WWV_5_MHz_discrimination_20251116.csv`
- `WWV_10_MHz_discrimination_20251116.csv`
- `WWV_15_MHz_discrimination_20251116.csv`

**Note:** Only shared frequencies (2.5, 5, 10, 15 MHz) produce discrimination logs.

## Verification Commands

```bash
# Check WWVH detection is disabled on 20 & 25 MHz
grep "WWVH detection" /tmp/grape-test/logs/analytics-wwv20.log
grep "WWVH detection" /tmp/grape-test/logs/analytics-wwv25.log

# Check WWVH detection is enabled on shared frequencies
grep "WWVH detection enabled" /tmp/grape-test/logs/analytics-wwv5.log

# View discrimination CSV
head /tmp/grape-test/analytics/WWV_5_MHz/discrimination_logs/WWV_5_MHz_discrimination_$(date +%Y%m%d).csv

# Count 440 Hz detections
grep "440 Hz" /tmp/grape-test/logs/analytics-wwv5.log
```

## Web UI Integration

The CSV files are ready for visualization. Suggested displays:

1. **Power Ratio Timeline** - Shows WWV vs WWVH strength over time
2. **Differential Delay Plot** - Shows ionospheric path variations
3. **440 Hz Detection Matrix** - Shows when each station ID is detected
4. **Confidence Heatmap** - Shows best times/frequencies for discrimination
5. **Station Dominance Stats** - Pie chart of dominant station percentages

## Files Modified

- `tone_detector.py` - Frequency-aware WWVH detection
- `analytics_service.py` - 440 Hz integration + CSV enhancement
- `wwvh_discrimination.py` - No changes (already had 440 Hz code)

## Status

✅ All changes implemented  
✅ Code compiles successfully  
✅ Ready to test with live data  
✅ CSV format ready for web UI
