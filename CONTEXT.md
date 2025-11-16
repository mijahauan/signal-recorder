# GRAPE Signal Recorder - Context

Essential context for maintaining the GRAPE (Global Radio Amateur Propagation Experiment) signal recorder.

## Architecture

**Two Independent Services:**
1. **Core Recorder** - RTP packets → NPZ archives (16 kHz raw IQ)
2. **Analytics Service** - NPZ → tone detection → decimation (10 Hz) → Digital RF → upload

**Separation Rationale:** Analytics can restart/upgrade without data loss. RTP timestamps in NPZ enable reprocessing.

## Timing Design (Critical)

- **RTP timestamp = primary reference** (not wall clock)
- **time_snap:** WWV/CHU tone onset anchors RTP to UTC
- **Formula:** `utc = time_snap_utc + (rtp - time_snap_rtp) / sample_rate`
- **Monotonic indexing:** No backwards time, gaps filled with zeros
- **Quality levels:** GPS_LOCKED → NTP_SYNCED → INTERPOLATED → WALL_CLOCK
- **Always upload** - annotate quality, let scientists filter

## Tone Detection & WWV-H Discrimination

**Station Types:**
- WWV: 2.5, 5, 10, 15, 20, 25 MHz (1000 Hz, 0.8s)
- WWVH: 2.5, 5, 10, 15 MHz only (1200 Hz, 0.8s) - **frequency-aware**
- CHU: 3.33, 7.85, 14.67 MHz (1000 Hz, 0.5s)

**Discrimination (on shared freqs 2.5/5/10/15 MHz):**
- Power ratio: 1000 Hz vs 1200 Hz
- Differential delay: WWV - WWVH arrival time
- 440 Hz tones: Minute 1 = WWVH, Minute 2 = WWV
- Output: CSV with all metrics for web UI

**Key API Methods:**
- `detector.process_samples(timestamp, samples_3khz, rtp_ts)` - requires 3 kHz resampling\!
- `discriminator.analyze_minute_with_440hz(iq_16khz, sr, ts, detections)` - full analysis

## File Locations

- Raw archives: `/tmp/grape-test/archives/{channel}/*_iq.npz` (16 kHz)
- Decimated: `/tmp/grape-test/archives/{channel}/*_iq_10hz.npz` (10 Hz)
- Digital RF: `/tmp/grape-test/analytics/{channel}/digital_rf/`
- Discrimination CSV: `/tmp/grape-test/analytics/{channel}/discrimination_logs/`
- State: `/tmp/grape-test/analytics/{channel}/analytics_state.json` (time_snap here)
- Config: `config/grape-config.toml`, `src/signal_recorder/paths.py`

## Web UI (3 Screens + Next)

1. **summary.html** - All channels status, detection counts, upload progress
2. **carrier.html** - Spectrograms (Doppler shifts), phase analysis
3. **channels.html** - Per-channel details, gaps, WWV timing
4. **discrimination display** (next objective) - WWV-H analysis visualization

**Data Sources:** Status JSONs (live), spectrograms (nightly), CSVs (discrimination)

## Doppler Interpretation (Scientific Data)

- **Frequency variations in 10 Hz carrier = ionospheric Doppler shifts**
- ±0.1 Hz = ±3 km path length resolution
- Smooth drift = real science (diurnal, solar storms)
- Abrupt jumps = processing artifact (bad)
- **Don't "fix" Doppler - it's the measurement\!**

## Testing

- Activate venv: `source venv/bin/activate`
- Test scripts: `test-drf-writer.py`, `test-wwvh-discrimination.py`
- Test data: `/tmp/grape-test/archives/WWV_5_MHz/`
- API docs: `docs/API_REFERENCE.md` (function signatures, examples)

## Key Docs

- `docs/API_REFERENCE.md` - Complete API (use this for signatures\!)
- `WWVH_DISCRIMINATION_QUICKREF.md` - WWV-H discrimination summary
- `TEST_RESULTS_SUMMARY.md` - Latest test results
