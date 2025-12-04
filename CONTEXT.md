# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-04  
**Version:** 3.5.0  
**Status:** ✅ Three-Phase Pipeline Complete, Ready for Web-UI Integration Testing

---

## 🎯 NEXT SESSION: WEB-UI INTEGRATION TESTING

The next session will focus on testing the Web-UI integration with the new three-phase architecture. The backend Python code is complete; now we need to verify the web dashboard correctly reads from the new directory structure.

### Testing Priorities

1. **Verify path synchronization** between `paths.py` and `grape-paths.js`
2. **Test spectrogram display** from `products/{CHANNEL}/spectrograms/`
3. **Test timing display** from `phase2/{CHANNEL}/clock_offset/`
4. **Test real-time status** from `status/` directory
5. **Verify 10-second sliding window monitor** JSON output

### Key Files for Web-UI Integration

| Python (Backend) | JavaScript (Frontend) | Purpose |
|------------------|----------------------|---------|
| `src/grape_recorder/paths.py` | `web-ui/grape-paths.js` | Path conventions (MUST STAY SYNCHRONIZED) |
| `analytics_service.py` | `monitoring-server-v3.js` | Status JSON writing/reading |
| `spectrogram_generator.py` | Spectrogram display pages | PNG image paths |
| `sliding_window_monitor.py` | Real-time dashboard | 10-second metrics JSON |

### Path Synchronization (CRITICAL)

**SYNC VERSION:** `2025-12-04-v2-three-phase`

Both files must define matching paths:

```
{DATA_ROOT}/
├── raw_archive/{CHANNEL}/       # Phase 1: 20 kHz Digital RF
├── phase2/{CHANNEL}/            # Phase 2: Timing analysis
│   ├── clock_offset/            # D_clock CSV files
│   └── state/                   # channel-status.json
├── products/{CHANNEL}/          # Phase 3: Derived products
│   ├── decimated/               # 10 Hz DRF for PSWS
│   ├── spectrograms/{YYYYMMDD}/ # PNG images
│   ├── gap_analysis/            # Gap JSON
│   └── timing_annotations/      # Timing CSV
├── status/                      # Real-time monitoring
│   ├── gpsdo_status.json        # GPSDO state
│   ├── timing_status.json       # Primary time reference
│   └── {CHANNEL}_monitor.json   # Sliding window metrics
├── state/                       # Service state files
└── logs/                        # Service logs
```

### Web-UI API Endpoints to Test

| Endpoint | Source | Status |
|----------|--------|--------|
| `/api/channels` | `phase2/*/state/channel-status.json` | Verify |
| `/api/spectrograms/:channel/:date` | `products/*/spectrograms/` | Verify |
| `/api/timing/:channel/:date` | `phase2/*/clock_offset/` | Verify |
| `/api/carriers/:channel/:date` | `phase2/*/carrier/` | Verify |
| `/api/status/gpsdo` | `status/gpsdo_status.json` | Verify |

---

## 📁 THREE-PHASE ARCHITECTURE (Complete)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    THREE-PHASE PIPELINE ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: IMMUTABLE RAW ARCHIVE                                             │
│  ════════════════════════════════                                            │
│  Input:  RTP multicast from radiod (20 kHz IQ)                              │
│  Output: raw_archive/{CHANNEL}/ (Digital RF with gzip)                      │
│  Key:    raw_archive_writer.py, core_recorder.py                            │
│  Scripts: grape-core.sh -start                                               │
│                                                                              │
│  PHASE 2: ANALYTICAL ENGINE                                                  │
│  ═════════════════════════════                                               │
│  Input:  raw_archive/{CHANNEL}/ (reads Phase 1)                             │
│  Output: phase2/{CHANNEL}/ (D_clock CSV, timing metrics)                    │
│  Key:    analytics_service.py, phase2_temporal_engine.py                    │
│  Scripts: grape-analytics.sh -start                                          │
│                                                                              │
│  PHASE 3: DERIVED PRODUCTS                                                   │
│  ══════════════════════════                                                  │
│  Input:  raw_archive/ + phase2/ (combines Phase 1 + 2)                      │
│  Output: products/{CHANNEL}/ (10 Hz DRF, spectrograms)                      │
│  Key:    phase3_product_engine.py, spectrogram_generator.py                 │
│  Scripts: grape-phase3.sh -yesterday                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Control Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `grape-all.sh` | Start/stop all services | `./scripts/grape-all.sh -start` |
| `grape-core.sh` | Phase 1 core recorder | `./scripts/grape-core.sh -start` |
| `grape-analytics.sh` | Phase 2 analytics (9 channels) | `./scripts/grape-analytics.sh -start` |
| `grape-ui.sh` | Web dashboard | `./scripts/grape-ui.sh -start` |
| `grape-phase3.sh` | Phase 3 batch processing | `./scripts/grape-phase3.sh -yesterday` |

---

## 📦 GRAPE MODULE STRUCTURE (Post-Cleanup)

### Essential Modules (33 files in `src/grape_recorder/grape/`)

**Phase 1 - Core Recording:**
- `raw_archive_writer.py` - Digital RF writer (20 kHz)
- `core_recorder.py` - Multi-channel RTP coordinator
- `sliding_window_monitor.py` - 10-second quality monitoring
- `gpsdo_monitor.py` - Timing integrity state machine

**Phase 2 - Analytics:**
- `analytics_service.py` - Per-channel analysis runner
- `phase2_temporal_engine.py` - 3-step temporal analysis
- `tone_detector.py` - WWV/WWVH/CHU tone detection
- `clock_offset_series.py` - D_clock computation
- `transmission_time_solver.py` - UTC back-calculation
- `wwvh_discrimination.py` - Station discrimination
- `discrimination_csv_writers.py` - CSV output
- `timing_metrics_writer.py` - Web-UI timing data
- `propagation_mode_solver.py` - Hop-count identification

**Phase 3 - Products:**
- `phase3_product_engine.py` - Decimation engine
- `decimation.py` - 20 kHz → 10 Hz filter chain
- `drf_batch_writer.py` - PSWS-compatible DRF output
- `spectrogram_generator.py` - PNG visualization

**Shared Infrastructure:**
- `wwv_constants.py` - Station coordinates, frequencies
- `wwv_tone_schedule.py` - Tone timing patterns
- `wwv_bcd_encoder.py` - BCD time code processing
- `wwv_geographic_predictor.py` - Geographic ToA prediction
- `solar_zenith_calculator.py` - Day/night calculation
- `quality_metrics.py` - Quality tracking dataclasses
- `gap_backfill.py` - Gap detection and handling
- `wwv_test_signal.py` - Test signal generation

**Advanced (kept for future use):**
- `pipeline_orchestrator.py`, `pipeline_recorder.py`
- `differential_time_solver.py`, `global_station_voter.py`
- `global_timing_coordinator.py`, `station_lock_coordinator.py`
- `primary_time_standard.py`, `time_standard_csv_writer.py`

### Archived Legacy Modules

8 files moved to `archive/legacy-grape-modules/`:
- `core_npz_writer.py` - NPZ replaced by Digital RF
- `grape_npz_writer.py` - Old segment writer
- `grape_recorder.py` - Two-phase recorder (superseded)
- `corrected_product_generator.py` - Superseded by phase3_product_engine
- `digital_rf_writer.py` - Superseded by drf_batch_writer
- `drf_writer_service.py` - Streaming mode (batch preferred)
- `startup_tone_detector.py` - Merged into phase2_temporal_engine
- `test_grape_refactor.py` - Old tests

---

## 🔑 KEY TECHNICAL DETAILS

### GPSDO Monitoring State Machine

| State | Description | Action |
|-------|-------------|--------|
| `STARTUP` | No anchor | Full tone search |
| `STEADY_STATE` | Anchor valid | Verify only, trust counter |
| `HOLDOVER` | Issue detected | Flag quality, continue |
| `REANCHOR` | Discontinuity | Force new anchor |

**Thresholds:**
- `VERIFICATION_TOLERANCE_MS = 0.1` (normal jitter)
- `PHYSICS_THRESHOLD_MS = 3.0` (something wrong)
- `REANCHOR_THRESHOLD_MS = 10.0` (force re-anchor)
- `DRIFT_ALARM_PPM = 0.1` (GPSDO unlock warning)

### 10-Second Sliding Window Monitor

Provides real-time quality metrics in parallel with 60-second D_clock computation:

```json
// status/{CHANNEL}_monitor.json (updated every 10s)
{
  "channel_name": "WWV 10 MHz",
  "timestamp": "2025-12-04T12:00:00Z",
  "current_window": {
    "wwv_snr_db": 18.5,
    "wwvh_snr_db": 12.3,
    "doppler_stability_hz": 0.08,
    "signal_present": true,
    "quality": "excellent"
  }
}
```

### Phase 2 Temporal Analysis (3 Steps)

1. **Step 1: Tone Detection** (±500ms)
   - Matched filter for 1000/1200 Hz tones
   - Output: `TimeSnapResult` with timing_error_ms

2. **Step 2: Channel Characterization** (±10-50ms)
   - BCD correlation, Doppler, Station ID
   - Output: `ChannelCharacterization`

3. **Step 3: Transmission Time Solution**
   - Propagation mode identification (hop count)
   - Output: `Phase2Result` with d_clock_ms, quality_grade

### Quality Grades

| Grade | D_clock Uncertainty | Description |
|-------|---------------------|-------------|
| A | < 1 ms | Excellent, single-hop |
| B | 1-5 ms | Good, stable propagation |
| C | 5-15 ms | Fair, multi-path |
| D | 15-50 ms | Poor, unstable |
| X | > 50 ms or failed | Invalid/no detection |

---

## 🧪 TESTING COMMANDS

```bash
# Start all services
./scripts/grape-all.sh -start

# Check status
./scripts/grape-all.sh -status

# View logs
tail -f /tmp/grape-test/logs/phase1-core.log
tail -f /tmp/grape-test/logs/phase2-wwv10.log

# Generate spectrograms for yesterday
./scripts/grape-phase3.sh -yesterday

# Test single spectrogram generation
python -m grape_recorder.grape.spectrogram_generator \
    --data-root /tmp/grape-test \
    --channel "WWV 10 MHz" \
    --date 2025-12-04

# Verify module imports
python3 -c "from src.grape_recorder.grape import SpectrogramGenerator; print('OK')"
```

---

## 📋 SESSION HISTORY

### Dec 4, 2025 (Current)
- ✅ Implemented `Phase3ProductEngine` for 10 Hz DRF generation
- ✅ Created `SpectrogramGenerator` for PNG visualization
- ✅ Integrated `SlidingWindowMonitor` into `RawArchiveWriter`
- ✅ Updated all shell scripts for three-phase architecture
- ✅ Archived 8 legacy modules to `archive/legacy-grape-modules/`
- ✅ Cleaned up `grape/__init__.py` exports

### Dec 3, 2025
- ✅ Fixed ChannelManager for proper channel reuse
- ✅ All 9 channels recording reliably (WWV + CHU)
- ✅ Phase 2 producing usable D_clock results

### Dec 2, 2025
- ✅ Unified installation system (TEST/PRODUCTION modes)
- ✅ Environment file for consistent paths
- ✅ Systemd services for production deployment

---

## 🔗 DOCUMENTATION REFERENCES

| Document | Purpose |
|----------|---------|
| `docs/PATH_CONVENTIONS.md` | Complete path reference |
| `docs/features/PHASE2_TEMPORAL_ENGINE.md` | Phase 2 algorithm details |
| `docs/features/PHASE3_PRODUCT_ENGINE.md` | Phase 3 architecture |
| `docs/PRODUCTION.md` | Production deployment guide |
| `archive/legacy-grape-modules/README.md` | Archived code documentation |

---

## ⚠️ KNOWN ISSUES / WATCHPOINTS

1. **Path Sync**: `paths.py` and `grape-paths.js` MUST stay synchronized
2. **ka9q module**: Not available in all environments (import may fail)
3. **matplotlib**: Required for spectrogram generation (optional dependency)
4. **digital_rf**: Required for DRF read/write operations

---

## 🏁 QUICK START FOR NEXT SESSION

```bash
cd /home/wsprdaemon/grape-recorder

# 1. Verify services can start
./scripts/grape-all.sh -status

# 2. Start services
./scripts/grape-all.sh -start

# 3. Open web dashboard
# http://localhost:3000/

# 4. Check if paths are correct
grep "SYNC VERSION" src/grape_recorder/paths.py web-ui/grape-paths.js

# 5. Verify new directory structure is being used
ls -la /tmp/grape-test/
```
