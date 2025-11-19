# GPS_LOCKED → TONE_LOCKED Rename
**Date:** 2024-11-15  
**Reason:** "GPS" was misleading - no GPS involved, using WWV/CHU tone detection

---

## Changes Summary

### Timing Quality Hierarchy (Simplified)

**Old (4 levels):**
1. GPS_LOCKED - ±1ms (misleading name)
2. NTP_SYNCED - ±10ms
3. INTERPOLATED - degrades with age
4. WALL_CLOCK - ±seconds

**New (3 levels):**
1. **TONE_LOCKED** - ±1ms (WWV/CHU time_snap within 5 min)
2. **NTP_SYNCED** - ±10ms (System NTP synchronized)
3. **WALL_CLOCK** - ±seconds (Unsynchronized fallback)

**Rationale:**
- "TONE_LOCKED" accurately describes the mechanism (1000 Hz tone detection)
- Works for both WWV and CHU time standard stations
- Removed INTERPOLATED tier (simpler: tone-locked or not)
- Aged time_snap (>5 min) now falls back to NTP or wall clock

---

## Files Modified

### Python Backend
**`src/signal_recorder/analytics_service.py`:**
- `TimingQuality` enum: `GPS_LOCKED` → `TONE_LOCKED`
- Removed `INTERPOLATED` enum value
- Updated `_get_timing_annotation()` logic (removed interpolated path)
- Updated log messages: "GPS-locked" → "tone-locked"
- Updated comments referencing GPS

### JavaScript Backend
**`web-ui/monitoring-server-v3.js`:**
- Updated time basis logic: `GPS_LOCKED` → `TONE_LOCKED`
- Removed `INTERPOLATED` case
- Simplified to 3-tier hierarchy
- Updated comments

### Frontend
**`web-ui/summary.html`:**
- Updated CSS: `.timing-gps` → `.timing-tone`
- Removed `.timing-interp` styles
- Updated rendering logic: `GPS_LOCKED` → `TONE_LOCKED`
- Display label: "GPS" → "TONE"
- Removed INTERPOLATED display case

### Documentation
**`docs/SUMMARY_SCREEN_DESIGN.md`:**
- Updated time basis logic description
- Removed INTERPOLATED references

**`docs/THREE_SCREEN_MONITORING_DESIGN.md`:**
- Updated time basis section
- Removed INTERPOLATED badge description

---

## Migration Notes

### No Data Migration Required
- Digital RF metadata uses string values (`"gps_locked"` → `"tone_locked"`)
- Old data retains original values (historical record preserved)
- New data uses new terminology
- Both are valid and interpretable

### Expected Behavior After Update

**With fresh time_snap (<5 min):**
```json
{
  "time_basis": "TONE_LOCKED",
  "time_snap_age_seconds": 120
}
```

**With NTP sync (no recent time_snap):**
```json
{
  "time_basis": "NTP_SYNCED",
  "time_snap_age_seconds": null
}
```

**With aged time_snap (>5 min, previously INTERPOLATED):**
```json
{
  "time_basis": "NTP_SYNCED",  // Falls back to NTP if available
  "time_snap_age_seconds": 600  // Still tracked for reference
}
```

---

## Testing Checklist

- [x] Python enum updated
- [x] JavaScript backend updated
- [x] Frontend UI updated
- [x] CSS styles updated
- [x] Documentation updated
- [x] Log messages updated
- [x] Comments updated
- [ ] Restart monitoring server
- [ ] Verify UI displays "TONE" badge
- [ ] Verify API returns `TONE_LOCKED`
- [ ] Check browser console (no errors)

---

## Future Investigation

Per user discussion, the **relative accuracy** of tone-locked vs GPS timing remains an open empirical question:

**Theoretical:**
- GPS: ±10-100 nanoseconds (stable)
- Tone-locked: ±1 millisecond (propagation-dependent)

**Variables affecting tone-locked accuracy:**
1. Ionospheric propagation delay (5-50ms range)
2. Detection algorithm precision
3. Multipath interference
4. SNR dependency
5. Frequency-dependent paths

**Potential research:**
- Compare tone-locked timestamps to GPS reference
- Analyze multi-channel time_snap consistency
- Track day/night and seasonal variations
- Correlate with SNR and propagation conditions

**For now:** "Tone-locked" is the preferred term, acknowledging it's the best timing available from the WWV/CHU tone detection system.

---

## Deployment

Restart monitoring server to apply changes:
```bash
pkill -f "node monitoring-server-v3.js"
cd web-ui
node monitoring-server-v3.js
```

Refresh browser at: `http://bee1.local:3000/summary.html`

Look for green "TONE" badges instead of "GPS" badges.
