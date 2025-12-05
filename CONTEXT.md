# GRAPE Recorder - AI Context Document

**Author:** Michael James Hauan (AC0G)  
**Last Updated:** 2025-12-05  
**Version:** 3.9.0  
**Status:** ✅ Multi-Broadcast Fusion Complete, Timing Dashboards Consolidated

---

## 🎯 NEXT SESSION: DISCRIMINATION DISPLAY IMPROVEMENTS

The next task is to improve the `discrimination.html` page to better visualize WWV/WWVH station identification. The discrimination system should clearly display real-time results from the 12 voting methods.

### Current State of Discrimination Page

The discrimination.html page has:
- Diurnal Station Dominance panel (moved from phase2-dashboard.html)
- Basic discrimination data display

### Goals for Next Session

1. **Improve visualization of 12 voting methods** - Show which methods contributed to the decision
2. **Real-time per-minute updates** - Update as new Phase 2 data arrives
3. **Method confidence display** - Show weight/confidence for each voting method
4. **Cross-validation indicators** - Highlight when methods agree/disagree
5. **Historical view** - Show discrimination history over time (24h default)

### Key Questions to Address

- How should we visualize the 12 methods? (bar chart, matrix, timeline?)
- Should methods be grouped by type (power, timing, spectral)?
- How to display the weighted voting result vs individual method votes?
- What happens when methods disagree? (mixed propagation indicator)

### Key Files for Discrimination Integration

| File | Purpose | Notes |
|------|---------|-------|
| `web-ui/discrimination.html` | Frontend display | Needs to consume Phase 2 data |
| `web-ui/discrimination.js` | Chart/logic | Currently may use legacy patterns |
| `src/grape_recorder/grape/wwvh_discrimination.py` | Backend discrimination | Power ratio, BCD, tone methods |
| `src/grape_recorder/grape/phase2_temporal_engine.py` | Integrates discrimination | `compute_discrimination()` |
| `src/grape_recorder/grape/discrimination_csv_writers.py` | CSV output | Per-method CSV files |

### Discrimination Data Locations

```
phase2/{CHANNEL}/
├── discrimination/
│   └── discrimination_summary.csv    # Weighted voting result
├── tone_detections/
│   └── tone_detections.csv           # 1000/1200 Hz tones
├── bcd_discrimination/
│   └── bcd_discrimination.csv        # BCD correlation method
├── doppler/
│   └── doppler_analysis.csv          # Doppler shift analysis
└── station_id_440hz/
    └── station_id.csv                # Voice ID + 500/600 Hz
```

### Existing API Endpoints for Discrimination

```javascript
// In monitoring-server-v3.js
app.get('/api/v1/phase2/reception-matrix')    // WWV/WWVH detection per channel
app.get('/api/v1/phase2/diurnal-pattern')     // Hourly dominance patterns
app.get('/api/v1/discrimination/:channel')    // Per-channel discrimination details
```

### WWVH Frequency Constraint (Fixed Dec 5)

**IMPORTANT**: WWVH only broadcasts on 2.5, 5, 10, 15 MHz. It does NOT broadcast on 20 or 25 MHz.

```javascript
// web-ui/monitoring-server-v3.js
const WWVH_FREQUENCIES_MHZ = [2.5, 5, 10, 15];
const canReceiveWWVH = WWVH_FREQUENCIES_MHZ.includes(freqMHz);
```

---

## 🎯 SESSION COMPLETE (Dec 5 PM): Multi-Broadcast Fusion & Dashboard Consolidation

### 1. Multi-Broadcast Fusion (v3.9.0)

**New Module**: `src/grape_recorder/grape/multi_broadcast_fusion.py`

Combines 13 broadcasts (6 WWV + 4 WWVH + 3 CHU) to achieve ±0.5 ms UTC(NIST) alignment.

**Key Features:**
- **Auto-calibration**: Learns per-station offsets via Exponential Moving Average (α=0.5)
- **Weighted fusion**: Combines calibrated measurements using SNR, quality grade, propagation mode
- **Convergence indicators**: Per-station progress bars showing calibration status
- **API endpoint**: `/api/v1/timing/fusion` returns fused D_clock + per-station calibration

**Accuracy Improvement:**
| Configuration | Accuracy |
|--------------|----------|
| Single broadcast, uncalibrated | ±5-10 ms |
| Multi-broadcast fusion | **±0.5 ms** |

### 2. Timing Dashboard Consolidation

**Removed**: `phase2-dashboard.html` (archived)

**Panels moved:**
- Diurnal Station Dominance → `discrimination.html`
- Reception Matrix → `summary.html`
- Propagation Paths (simplified) → `summary.html`

**`timing-dashboard-enhanced.html` now shows:**
- UTC(NIST) Alignment panel (fused D_clock with large display)
- 13-Broadcast D_clock Status table (raw values per broadcast)
- D_clock Time Series chart (with selection persistence)
- Per-station calibration cards with convergence progress bars

### 3. Advanced Timing Visualizations (Fusion-Corrected)

All graphs on `timing-advanced.html` now apply fusion calibration:

| Graph | Correction Applied | Notes |
|-------|-------------------|-------|
| Kalman Funnel | `offset + calibration[station]` | 24h default, drag-to-zoom |
| Constellation | `error_ms + calibration[base_station]` | Clustered at center when calibrated |
| Consensus KDE | `offset + calibration[station]` | Sharp peak at 0 ms |

### 4. Documentation

**New**: `/docs/timing-methodology.html` - Interactive documentation with:
- D_clock measurement explanation
- Multi-broadcast fusion algorithm
- What each visualization shows
- Accuracy expectations and factors

**Info links** (?) added to all timing graphs linking to relevant documentation sections.

### 5. Key Code Changes

| File | Change |
|------|--------|
| `multi_broadcast_fusion.py` | New fusion service with EMA calibration |
| `timing-advanced.html` | Fusion correction on all graphs, 24h zoom |
| `timing-dashboard-enhanced.html` | Consolidated panels, convergence indicators |
| `timing-visualizations.js` | Zoom controls, adaptive tick format |
| `monitoring-server-v3.js` | `/api/v1/timing/fusion` endpoint |
| `navigation.js` | Removed Phase 2 Analysis link |

---

## 🎯 SESSION COMPLETE (Dec 5 AM): Clock Convergence & UTC Standardization

### 1. Clock Convergence Model ("Set, Monitor, Intervention")

**New Module**: `src/grape_recorder/grape/clock_convergence.py`

With a GPSDO-disciplined receiver, we converge to a locked clock offset estimate, then monitor for anomalies instead of constantly recalculating.

```
State Machine:
ACQUIRING (N<10) → CONVERGING (building stats) → LOCKED (monitoring)
                                                       ↓
                                              5 anomalies → REACQUIRE
```

**Key Features:**
- **Running statistics**: Welford's online algorithm for mean/variance
- **Uncertainty**: σ/√N (shrinks with each measurement)
- **Lock criterion**: uncertainty < 1ms AND N ≥ 30 samples
- **Anomaly detection**: |residual| > 3σ flags propagation events
- **State persistence**: JSON file survives service restarts

**Integration**: `Phase2AnalyticsService._write_clock_offset()` now uses the convergence model:
- Locked state writes converged mean (not raw measurement)
- Quality grades A/B indicate convergence lock
- `utc_verified` field = True when locked
- Residuals reveal real ionospheric propagation effects

**Expected Timeline**:
| Time | State | Uncertainty | Kalman Color |
|------|-------|-------------|--------------|
| 0-10 min | ACQUIRING | ∞ | Gray |
| 10-30 min | CONVERGING | ~10 ms | Gray |
| 30+ min | **LOCKED** | < 1 ms | **Blue** |

### 2. Propagation Mode Probability (Gaussian Discrimination)

**Updated**: `web-ui/utils/transmission-time-helpers.js` → `getModeProbabilityData()`

Mode probabilities now use Gaussian likelihood based on converged uncertainty:

```
P(mode) ∝ exp(-0.5 × ((measured - expected) / σ)²)
where σ = √(uncertainty² + mode_spread²)
```

| Uncertainty | Discrimination |
|-------------|----------------|
| > 30 ms | Flat (no information) |
| 10-30 ms | Weak peaks |
| 3-10 ms | Moderate |
| **< 3 ms** | **Sharp peaks** ✓ |

### 3. UTC Time Standardization

**New Utility**: `web-ui/utils/utc-time.js`

All time displays now use UTC for scientific consistency:

```javascript
UTCTime.now()           // "13:45:23"
UTCTime.formatTime(ts)  // "13:45:23"
UTCTime.formatDate(ts)  // "2025-12-05"
UTCTime.formatDateTime(ts) // "2025-12-05 13:45:23 UTC"
```

**Updated Pages**: summary.html, timing-dashboard-enhanced.html, carrier.html, phase2-dashboard.html, gaps.html, logs.html, timing-visualizations.js

**Plotly Charts**: Use ISO strings for timestamps to force UTC display:
```javascript
const timestamps = data.map(p => new Date(p.timestamp * 1000).toISOString());
```

### 4. Phase 2 Dashboard Fixes

- **Receiver Location**: Fixed grid lookup from `[station]` config section
- **Maidenhead Conversion**: Proper 6-character grid to lat/lon
- **WWVH Filtering**: 20/25 MHz channels show "N/A" for WWVH (doesn't broadcast there)

### 5. Status JSON Enhancements

`phase2/{CHANNEL}/status/analytics-service-status.json` now includes:

```json
{
  "channels": {
    "WWV 10 MHz": {
      "d_clock_ms": -5.823,
      "quality_grade": "B",
      "uncertainty_ms": 0.87,
      "convergence": {
        "state": "locked",
        "is_locked": true,
        "sample_count": 45,
        "uncertainty_ms": 0.87,
        "convergence_progress": 1.0,
        "residual_ms": 0.12,
        "is_anomaly": false
      }
    }
  }
}
```

---

## 📋 SESSION HISTORY

### Dec 5, 2025 (PM) - Multi-Broadcast Fusion (v3.9.0)
- ✅ **Multi-Broadcast Fusion**: Combines 13 broadcasts → ±0.5 ms UTC(NIST) alignment
- ✅ **Auto-Calibration**: Per-station offsets learned via EMA (α=0.5)
- ✅ **Convergence Indicators**: Progress bars per station (✓ Locked, Converging, Learning)
- ✅ **Dashboard Consolidation**: Removed phase2-dashboard.html, moved panels
- ✅ **Fusion-Corrected Graphs**: Kalman funnel, constellation, consensus all centered at 0
- ✅ **24-Hour Zoom**: Kalman funnel with drag-to-zoom, scroll zoom, adaptive ticks
- ✅ **Methodology Docs**: `/docs/timing-methodology.html` with info links on graphs
- ✅ **Selection Persistence**: D_clock chart remembers user's channel/time selection

### Dec 5, 2025 (AM) - Clock Convergence & UTC
- ✅ **Clock Convergence Model**: "Set, Monitor, Intervention" architecture
- ✅ **Convergence State Machine**: ACQUIRING → CONVERGING → LOCKED → REACQUIRE
- ✅ **Welford Algorithm**: Running mean/variance with proper uncertainty
- ✅ **Anomaly Detection**: 3σ threshold for propagation events
- ✅ **State Persistence**: Convergence survives service restart
- ✅ **Mode Probability**: Gaussian likelihood-based discrimination
- ✅ **UTC Standardization**: All web-UI displays use UTC
- ✅ **Plotly Charts**: Force UTC timezone in all visualizations
- ✅ **WWVH Filtering**: 20/25 MHz correctly shows N/A for WWVH
- ✅ **Receiver Location**: Fixed grid square lookup and conversion

### Dec 4, 2025 - Session 2 (Audio & Status Fixes)

| Component | Status | Notes |
|-----------|--------|-------|
| Phase 1 (Core Recorder) | ✅ Working | 9 channels recording, auto-recovery on radiod restart |
| Phase 2 (Analytics) | ✅ Working | All 9 channels processing, D_clock being computed |
| Phase 3 (Products) | ✅ Working | Spectrograms, decimated DRF |
| Web-UI Summary | ✅ Working | Per-channel RTP status lights now accurate |
| Web-UI Audio | ✅ Working | AM streaming with AGC via ka9q-python |
| Web-UI Timing | ✅ Integrated | D_clock display, charts, pipeline status |

### Testing the Changes

```bash
cd ~/grape-recorder
./scripts/grape-ui.sh -stop      # Stop existing instance
./scripts/grape-ui.sh -start     # Start with new changes
./scripts/grape-ui.sh -status    # Verify running → http://localhost:3000/
```

Check logs if needed: `tail -f $DATA_ROOT/logs/webui.log`

### Key Files for Timing Integration

| Python (Backend) | JavaScript (Frontend) | Purpose |
|------------------|----------------------|---------|
| `phase2_analytics_service.py` | `monitoring-server-v3.js` | Timing metrics JSON |
| `phase2_temporal_engine.py` | `carrier.html` / `timing.html` | D_clock computation |
| `clock_offset_series.py` | Data display | CSV output format |
| `timing_metrics_writer.py` | Real-time dashboard | Web-UI timing data |

### Timing Data Locations (Phase 2 Architecture)

```
phase2/{CHANNEL}/
├── clock_offset/               # D_clock CSV files (per-minute)
│   └── YYYYMMDD/
│       └── {channel}_clock_offset_{YYYYMMDD}.csv
├── status/
│   └── analytics-service-status.json  # Real-time status including:
│       ├── last_carrier_snr_db        # Carrier SNR from 10 Hz IQ
│       ├── minutes_processed          # Processing count
│       └── last_d_clock_ms            # Most recent D_clock
└── state/
    └── channel-status.json     # TimeSnap reference, quality
```

### Carrier SNR (Fixed This Session)

**Important Change**: Carrier SNR is now computed from 10 Hz decimated IQ data in `_calculate_carrier_snr()` in `phase2_analytics_service.py`. This provides SNR for ALL channels regardless of tone detection success.

```python
# Carrier SNR calculation (always available)
carrier_snr_db = 10 * log10(mean_power / noise_variance)

# Previously depended on tone detection (often null for weak signals)
```

---

## � AUDIO STREAMING (Fixed This Session)

### Architecture

Audio streaming uses **ka9q-python** from the venv (NOT SWL-ka9q). The web-UI calls `radiod_audio_client.py` to create AM audio channels.

**Critical**: SSRC is **dynamically allocated by ka9q** - do NOT use legacy SSRC conventions (frequency + 999).

### Audio Flow

```
Browser → WebSocket → Node.js Server → RTP Multicast ← radiod AM Channel
                                              ↑
                              radiod_audio_client.py (Python/ka9q)
```

### Key Files

| File | Purpose |
|------|---------|
| `web-ui/radiod_audio_client.py` | Creates AM channels via ka9q-python |
| `web-ui/monitoring-server-v3.js` | WebSocket audio forwarding (lines 185-245) |
| `web-ui/summary.html` | Browser audio player (GRAPEAudioPlayer class) |

### Audio Client Usage

```python
# Create AM audio channel (ka9q auto-allocates SSRC)
from ka9q import RadiodControl, discover_channels

control = RadiodControl('bee1-hf-status.local')

# Check for existing channel first
channels = discover_channels('bee1-hf-status.local')
for ssrc, ch in channels.items():
    if ch.preset == 'am' and abs(ch.frequency - frequency_hz) < 1000:
        return existing_channel_info

# Create new channel
ssrc = control.create_channel(
    frequency_hz=10000000,
    preset='am',
    sample_rate=12000,
    agc_enable=1
)

# Explicitly set AM preset and AGC
control.set_preset(ssrc, 'am')
control.set_agc(ssrc, enable=True, headroom=6.0)
control.set_agc_threshold(ssrc, threshold_db=0.0)
control.set_gain(ssrc, gain_db=40.0)  # Boost for low SNR
```

### Server-Side SSRC Handling (Fixed)

The server **MUST use the SSRC returned by ka9q**, not calculate a legacy one:

```javascript
// monitoring-server-v3.js startAudioStream()
const result = JSON.parse(stdout.trim());
const ssrc = result.ssrc;  // Use ka9q's SSRC, NOT getAudioSSRC(freq)
this.activeStreams.set(ssrc, stream);
```

### Deprecated Patterns (DO NOT USE)

```javascript
// ❌ WRONG - Legacy SSRC calculation
const AUDIO_SSRC_OFFSET = 999;
const ssrc = frequencyHz + AUDIO_SSRC_OFFSET;  // Don't do this!

// ✅ CORRECT - Use SSRC from ka9q response
const ssrc = result.ssrc;
```

---

## � THREE-PHASE ARCHITECTURE (Complete)

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

### Dec 4, 2025 - Session 2 (Audio & Status Fixes)
- ✅ **Audio Streaming Fixed**: Uses ka9q-python from venv with dynamic SSRC allocation
- ✅ **AGC Configured**: headroom=6dB, threshold=0dB, gain=40dB for comfortable listening
- ✅ **Per-Channel RTP Status**: Fixed status lights to check `last_packet_time` per channel
- ✅ **Carrier SNR**: Now calculated from 10 Hz IQ data (independent of tone detection)
- ✅ **Duplicate AM Prevention**: Audio client checks for existing AM channels before creating
- ✅ **Server SSRC Fix**: Uses `result.ssrc` from ka9q, not legacy calculation
- ✅ **Channel Recovery Test**: Core recorder auto-recovers all 9 channels on radiod restart

### Dec 4, 2025 - Session 1 (Phase 3 Implementation)
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
2. **ka9q-python**: Must run scripts in venv (`source venv/bin/activate`)
3. **SSRC Allocation**: ka9q auto-allocates SSRCs - never hardcode or calculate legacy SSRCs
4. **matplotlib**: Required for spectrogram generation (optional dependency)
5. **digital_rf**: Required for DRF read/write operations
6. **Audio Channels**: Always check for existing AM channel before creating new one

### Per-Channel RTP Status (Fixed)

The web-UI now checks per-channel status using `last_packet_time` from the core status file:

```javascript
// monitoring-server-v3.js getChannelStatuses()
const coreStatusFile = paths.getCoreStatusFile();
const coreStatus = JSON.parse(fs.readFileSync(coreStatusFile, 'utf8'));

for (const [ssrc, chInfo] of Object.entries(coreStatus.channels)) {
    if (chInfo.description === channelName) {
        const lastPacket = new Date(chInfo.last_packet_time).getTime() / 1000;
        const age = Date.now() / 1000 - lastPacket;
        rtpStreaming = age < 10;  // 10 second timeout
    }
}
```

Previously, all channels showed same status (overall core running state). Now each channel's status light accurately reflects its individual RTP stream state.

---

## 🏁 QUICK START FOR NEXT SESSION

```bash
cd /home/wsprdaemon/grape-recorder

# 1. Verify services running
./scripts/grape-all.sh -status

# 2. Start if needed
./scripts/grape-all.sh -start

# 3. Open web dashboard
# http://localhost:3000/

# 4. Check Phase 2 timing data is being produced
ls -la /tmp/grape-test/phase2/*/clock_offset/
cat /tmp/grape-test/phase2/WWV\ 10\ MHz/status/analytics-service-status.json | jq .

# 5. Verify carrier SNR is being calculated
grep "carrier_snr" /tmp/grape-test/logs/phase2-wwv10.log | tail -5

# 6. Test audio (if needed)
source venv/bin/activate
python3 web-ui/radiod_audio_client.py --radiod-host bee1-hf-status.local create --frequency 10000000
```

### Files to Review for Timing Integration

```bash
# Backend - where timing data is written
cat src/grape_recorder/grape/phase2_analytics_service.py | head -100

# Frontend - where timing should be displayed
cat web-ui/monitoring-server-v3.js | grep -A5 "getChannelStatuses"
cat web-ui/carrier.html | grep -A5 "timeBasis"
```
