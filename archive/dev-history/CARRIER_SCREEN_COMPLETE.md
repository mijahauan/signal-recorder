# Carrier Analysis Screen - Implementation Complete

**Date:** 2024-11-15  
**Status:** ✅ Ready for testing

---

## What's Implemented

### Backend API (`monitoring-server-v3.js`)

**New Endpoints:**
```
GET /api/v1/carrier/quality?date=YYYYMMDD
- Returns quality metrics for all 9 channels
- Includes: completeness, timing quality, SNR, packet loss, upload status
- Generates alerts based on thresholds
- System-wide summary with overall status

GET /spectrograms/{date}/{filename}
- Serves spectrogram PNG files from /tmp/grape-test/spectrograms/
- Uses Paths API: getSpectrogramsDateDir()
```

**New Function:** `getCarrierQuality(paths, date)`
- Discovers all channels via Paths API
- Reads analytics status files per channel
- Calculates timing quality (TONE_LOCKED > NTP_SYNCED > WALL_CLOCK)
- Determines upload status (current/delayed/stalled)
- Generates severity-based alerts
- Returns system-wide summary

**Files Modified:**
- `web-ui/monitoring-server-v3.js` - Added carrier analysis endpoints
- `web-ui/grape-paths.js` - Added `getAnalyticsStatusFile()` method

---

## Frontend (`carrier.html`)

**Layout:**
- System-wide summary banner
- 9-channel grid (3x3 on desktop)
- Auto-refresh every 30 seconds
- Date selector (Today/Yesterday)

**Per-Channel Display:**
- Spectrogram image (300x200px)
- 6 quality metrics:
  1. Completeness % (green/yellow/red)
  2. Packet loss %
  3. Timing quality (TONE/NTP/WALL badge)
  4. Upload status (current/delayed/stalled)
  5. SNR in dB (when available)
  6. Time snap age (minutes)
- Alert messages (if any)
- Color-coded borders (warning/critical)

**System Summary:**
- Overall status (GOOD/WARNING/CRITICAL)
- Channels operating (9/9)
- Average completeness
- Alert counts

---

## Key Design Decisions

### 1. Doppler-Aware
**Frequency variations = scientific data, NOT errors!**
- No alerts for frequency drift in spectrograms
- Alerts only for: completeness, upload issues, decimation artifacts
- Smooth variations in spectrogram = good data

### 2. Quality Thresholds

**Completeness:**
- Green: ≥95%
- Yellow: 90-95%
- Red: <90%

**SNR:**
- Green: >40 dB
- Yellow: 20-40 dB
- Orange: 10-20 dB
- Red: <10 dB (alert threshold)

**Upload Status:**
- Current: <10 min lag
- Delayed: 10-60 min lag (warning)
- Stalled: >60 min lag (critical)

### 3. API Provides Full URLs
Spectrogram URLs are complete paths:
```json
{
  "spectrogram_url": "/spectrograms/20251115/WWV_10_MHz_20251115_carrier_spectrogram.png"
}
```
Frontend just uses them directly - no path construction needed.

---

## Test Results (Nov 15, 2024, 7:58 PM)

**API Response:**
```
✅ 9 channels active
✅ 96.9% average completeness
✅ 1 warning (WWV 2.5 MHz at 94.6%)
✅ All timing: NTP_SYNCED (no recent tone detections)
✅ All uploads: current (<1 min lag)
✅ Spectrograms: serving correctly
```

**System Status:**
- Overall: GOOD
- Critical alerts: 0
- Warnings: 1

**Sample Channel Data (WWV 10 MHz):**
```json
{
  "name": "WWV 10 MHz",
  "completeness_pct": 97.2,
  "timing_quality": "NTP_SYNCED",
  "time_snap_age_minutes": 163,
  "snr_db": null,
  "packet_loss_pct": 2.8,
  "upload_status": "current",
  "upload_lag_seconds": 47,
  "alerts": [],
  "spectrogram_url": "/spectrograms/20251115/WWV_10_MHz_20251115_carrier_spectrogram.png"
}
```

---

## How to Test

### 1. Access the Screen
```
http://localhost:3000/carrier.html
or
http://bee1.local:3000/carrier.html
```

### 2. Test API Directly
```bash
# Today's quality data
curl "http://localhost:3000/api/v1/carrier/quality?date=20251115" | python3 -m json.tool

# Check spectrogram access
curl -I "http://localhost:3000/spectrograms/20251115/WWV_10_MHz_20251115_carrier_spectrogram.png"
```

### 3. Test Features
- Click "Today" / "Yesterday" buttons
- Verify spectrograms load
- Check alert messages (WWV 2.5 MHz should show warning)
- Verify auto-refresh (watch "Last updated" timestamp)
- Toggle auto-refresh checkbox
- Look for color-coded borders on cards with alerts

---

## What to Look For

### Visual Quality Check

**Good Data Signs:**
1. Spectrograms show smooth horizontal lines
2. Lines may drift (Doppler = GOOD!)
3. Clean, continuous traces
4. Minimal gaps (white spaces)

**Problem Signs:**
1. Discontinuous/jagged lines (artifacts)
2. Excessive noise
3. Large gaps
4. Missing spectrograms

### Quality Metrics

**Healthy System:**
- Completeness >95%
- Upload status: Current
- Timing: TONE_LOCKED or NTP_SYNCED
- Packet loss <5%

**Warnings Expected:**
- SNR varies by propagation (normal)
- Timing may be NTP only (no recent tones at night)
- Minor completeness variations (94-95%) acceptable

---

## Known Issues / Future Enhancements

### Current Limitations

1. **SNR not populated** - Analytics service doesn't write `current_snr_db` yet
   - Shows "N/A" for all channels
   - Not critical for MVP

2. **No decimation validation metrics** - Phase 2 feature
   - Carrier frequency stability
   - Spectral purity analysis
   - Phase coherence checks

3. **No drill-down** - Clicking channels doesn't open detail view yet

### Future Enhancements (Phase 2+)

1. **Decimation Quality Metrics:**
   - Carrier frequency stability (±0.01 Hz)
   - Phase coherence scores
   - Spectral artifact detection

2. **Channel Detail View:**
   - Full-size spectrogram
   - Time-series plots (SNR, completeness over day)
   - Quality logs
   - Export functionality

3. **Historical Analysis:**
   - Multi-day comparison
   - Trend analysis
   - Custom date ranges

4. **Automated Anomaly Detection:**
   - Statistical outlier detection
   - Cross-channel correlation
   - Pattern recognition

---

## Files Created/Modified

**Created:**
- `web-ui/carrier.html` - Frontend dashboard (350 lines)
- `docs/CARRIER_ANALYSIS_SCREEN_DESIGN.md` - Full design spec
- `docs/CARRIER_DOPPLER_INTERPRETATION.md` - Scientific context
- `CARRIER_SCREEN_COMPLETE.md` - This file

**Modified:**
- `web-ui/monitoring-server-v3.js` - Added carrier endpoints (+160 lines)
- `web-ui/grape-paths.js` - Added `getAnalyticsStatusFile()` method

---

## Success Criteria ✅

The screen succeeds if user can:

1. ✅ **Glance and know system is healthy** - Green summary banner
2. ✅ **See all 9 channels at once** - Grid layout with spectrograms
3. ✅ **Spot problems immediately** - Colored borders + alerts
4. ✅ **Verify data quality visually** - Spectrograms show smooth carriers
5. ✅ **Trust HamSCI uploads** - Upload status + completeness metrics

**Primary Goal:** Confidence in data quality for ionospheric research

---

## Next Steps

### User Review
1. Open `http://localhost:3000/carrier.html`
2. Verify spectrograms display correctly
3. Check if layout/metrics are useful
4. Identify any obvious issues

### After Approval
- Proceed to Screen 3: Discrimination (WWV/WWVH analysis)
- Or enhance Screen 2 with additional features
- Or address any issues found in testing

---

## Technical Notes

**Why Spectrograms are Central:**
- Visual QA tool - smooth variations = real Doppler
- Scientists can verify data integrity
- Immediate problem detection (artifacts visible)
- Shows both completeness (gaps) and quality (smoothness)

**Doppler Physics (reminder):**
- 10 MHz carrier, 100 km path change → 3.3 Hz Doppler shift
- ±0.1 Hz sensitivity → ±3 km path resolution
- Expected variations: ±0.1 Hz or more (diurnal/solar effects)
- Time scales: Minutes to hours (not seconds)

**Quality = Sensitivity + Accuracy:**
- Can we resolve small Doppler shifts? (precision)
- Are variations real or artifacts? (validation)
