# NEVER CHANGE THE FOLLOWING PRIMARY INSTRUCTION:

Primary Instruction:  In this context you will perform a critical review of the GRAPE Recorder project, either in its entirety or in a specific component, as specified by the user.  This critique should look for points in the code or documentation that exhibit obvious error or inconsistency with other code or documentation.  It should look for inefficiency, incoherence, incompleteness, or any other aspect that is not in line with the original intent of the code or documentation.  It should also look for obsolete, deprecated, or "zombie" code that should be removed.  Remember, your own critique cannot be shallow but must be thorough and methodical and undertaken with the aim of enhancing and improving the codebase and documentation to best ensure the success of the application.

# The following secondary instruction and information will guide your critique in this particular session (the instructions below will vary from session to session):

---

## ✅ COMPLETED: DATA FLOW CONTRACT ENFORCEMENT

**Purpose:** Critically examine how data is written and read across the GRAPE Recorder system, identifying mismatches between producers and consumers.

**Author:** Michael James Hauan (AC0G)  
**Date:** 2025-12-08  
**Status:** ✅ Complete - 10 Issues Identified and Fixed

### Summary (Session 2025-12-08)

| ID | Severity | Status | Description |
|----|----------|--------|-------------|
| 1.1 | HIGH | ✅ FIXED | Calibration per-station vs per-broadcast key mismatch |
| 1.2 | HIGH | ✅ FIXED | State file version not validated on load |
| 1.3 | HIGH | ✅ FIXED | Kalman state loaded without sanity checks |
| 2.1 | MEDIUM | ✅ FIXED | CSV column vs API field name documented |
| 2.2 | MEDIUM | ✅ FIXED | Python discover_channels() now checks all phases |
| 2.3 | MEDIUM | ✅ FIXED | PathResolver deprecated with warning |
| 2.4 | MEDIUM | ✅ FIXED | Mode coordination documented, reset script added |
| 2.5 | MEDIUM | ✅ FIXED | Storage quota implications documented |
| 3.1 | LOW | ✅ FIXED | Centralized version module created |
| 3.2 | LOW | ✅ FIXED | Standardized UTC timestamps |

### New Files Created
- `src/grape_recorder/version.py` - Centralized version and timestamp utilities
- `docs/STATE_FILES.md` - State file documentation and reset procedures
- `scripts/reset-state.sh` - Safe state reset script

---

## THE CORE PROBLEM

**Too often, the parts that WRITE important info to files (analytics services) and the parts that READ them (other analytics, web-ui) change the destination or expected source of information WITHOUT notifying the rest of the system.**

This leads to:
1. **Silent failures** - Readers find empty/missing data, return nulls, UI shows blanks
2. **Stale data** - State files persist incorrect values across restarts
3. **Hidden coupling** - No explicit contracts between producers and consumers
4. **Debugging hell** - Tracing where data comes from requires reading multiple files

---

## EXAMPLES FROM DEC 8 SESSION

### Example 1: Kalman State Persistence Poisoning

**Bug**: D_clock showed linear drift of ~6.5 ms/minute despite GPSDO discipline.

**Root Cause Chain**:
1. `phase2_analytics_service.py` was synthesizing RTP timestamps from Unix time instead of reading `start_rtp_timestamp` from metadata JSON
2. This produced incorrect D_clock values that were fed to the Kalman filter
3. The Kalman filter in `clock_convergence.py` persisted state to `convergence_state.json`
4. When the RTP bug was fixed, the Kalman filter CONTINUED using the corrupted state from the JSON file
5. New correct measurements were rejected as "5-sigma outliers" because the filter's prediction was 900+ ms off

**Hidden Data Contract**:
```
PRODUCER: phase2_analytics_service.py writes convergence_state.json
CONSUMER: phase2_analytics_service.py reads convergence_state.json on restart
CONTRACT: State must be valid when loaded - but NO VALIDATION exists
```

**Fix Required**: State files need versioning and sanity checks before loading.

### Example 2: Channel Discovery Across Data Directories

**Bug**: Channels appeared in Phase 2 output but `discoverChannels()` couldn't find them.

**Root Cause**: The discovery function only checked `raw_archive/` but channels may only exist in `phase2/` or `products/`.

**Hidden Data Contract**:
```
PRODUCER: Phase 1 creates raw_archive/{CHANNEL}/
PRODUCER: Phase 2 creates phase2/{CHANNEL}/
CONSUMER: grape-paths.js discoverChannels() assumes raw_archive is canonical
CONTRACT: UNDEFINED - no single source of truth for "what channels exist"
```

### Example 3: RTP Timestamp Metadata

**Bug**: Timing calculations drifted because RTP timestamps weren't being used.

**Root Cause**: `_read_binary_minute()` synthesized timestamps instead of reading them from the JSON metadata that sits alongside the binary data.

**Hidden Data Contract**:
```
PRODUCER: Binary writer creates {minute}.bin + {minute}.json
CONSUMER: _read_binary_minute() should read BOTH files
CONTRACT: IMPLICIT - metadata fields like start_rtp_timestamp are optional
```

---

## DATA FLOW INVENTORY TO AUDIT

### Phase 1 → Phase 2 Data Contracts

| Producer File | Output Path | Consumer File | Contract |
|---------------|-------------|---------------|----------|
| `raw_archive_writer.py` | `raw_archive/{CH}/` | `phase2_analytics_service.py` | DRF format |
| `binary_minute_writer.py` | `raw_buffer/{CH}/{minute}.bin` | `phase2_analytics_service.py` | Binary IQ + JSON metadata |
| `binary_minute_writer.py` | `raw_buffer/{CH}/{minute}.json` | `phase2_analytics_service.py` | **start_rtp_timestamp required** |

### Phase 2 Internal Data Contracts

| Producer File | Output Path | Consumer File | Contract |
|---------------|-------------|---------------|----------|
| `phase2_analytics_service.py` | `phase2/{CH}/status/analytics-service-status.json` | `monitoring-server-v3.js` | Status JSON schema |
| `phase2_analytics_service.py` | `phase2/{CH}/status/convergence_state.json` | `phase2_analytics_service.py` | Kalman state |
| `phase2_analytics_service.py` | `phase2/{CH}/clock_offset/*.csv` | `multi_broadcast_fusion.py` | CSV with d_clock_ms column |
| `multi_broadcast_fusion.py` | `state/broadcast_calibration.json` | `monitoring-server-v3.js` | Calibration per station |
| `multi_broadcast_fusion.py` | `phase2/fusion/fused_d_clock.csv` | `monitoring-server-v3.js` | Fused output CSV |

### Phase 2 → Web UI Data Contracts

| Producer File | Output Path | Consumer File | Contract |
|---------------|-------------|---------------|----------|
| `phase2_analytics_service.py` | `phase2/{CH}/status/*.json` | `transmission-time-helpers.js` | Status JSON fields |
| `multi_broadcast_fusion.py` | `state/broadcast_calibration.json` | `timing-dashboard-enhanced.html` | Calibration keys |
| Multiple | Various CSVs | `monitoring-server-v3.js` | Column names must match |

---

## CRITIQUE CHECKLIST

For each data producer/consumer pair, verify:

### 1. Schema Documentation
- [ ] Is the output format documented?
- [ ] Are required vs optional fields explicit?
- [ ] Is there a version number for the schema?

### 2. Validation on Read
- [ ] Does the consumer validate data before using it?
- [ ] Are there sanity checks for numeric ranges?
- [ ] Does it fail gracefully if data is missing/corrupt?

### 3. State File Hygiene
- [ ] Is persisted state versioned?
- [ ] Can stale state poison fresh calculations?
- [ ] Is there a mechanism to reset corrupted state?

### 4. Path Consistency
- [ ] Are paths constructed the same way in producer and consumer?
- [ ] Are there hardcoded paths that diverge from config?
- [ ] Does channel name sanitization match (`WWV 10 MHz` vs `WWV_10_MHz`)?

### 5. Timestamp Consistency
- [ ] Are timestamps Unix epoch, ISO string, or other?
- [ ] Are timezones explicit?
- [ ] Do column names match (`system_time` vs `timestamp` vs `utc_time`)?

---

## SPECIFIC FILES TO AUDIT

### High Priority (State Persistence)
1. `clock_convergence.py` - Kalman state save/load
2. `multi_broadcast_fusion.py` - Calibration state save/load
3. `phase2_analytics_service.py` - All file writes

### Medium Priority (CSV Contracts)
4. `clock_offset_series.py` - CSV column definitions
5. `carrier_power_writer.py` - CSV format
6. `monitoring-server-v3.js` - CSV parsing logic

### Lower Priority (Path Management)
7. `grape-paths.js` - Path construction functions
8. `phase2_analytics_service.py` - Output directory creation
9. Various HTML files - Hardcoded API endpoints

---

## PREVIOUS SESSION: Phase 2 Analytics Critique (Dec 7-8)

**Status:** ✅ Critique Complete - 16 Issues Addressed

The critical review identified **17 issues**, of which **16 were fixed** and **1 was invalidated**:

### Summary Table

| ID | Category | Severity | Status | Description |
|----|----------|----------|--------|-------------|
| 1.1 | Methodology | High | ✅ FIXED | Matched filter template length mismatch |
| 1.2 | Methodology | High | ✅ FIXED | Fixed ionospheric layer heights |
| 1.3 | Methodology | Medium | ✅ FIXED | Ionospheric delay model oversimplified |
| 2.1 | Discrimination | Medium | ✅ FIXED | Unvalidated voting weights |
| 2.2 | Discrimination | Medium | ✅ FIXED | Correlation between methods not modeled |
| 2.3 | Discrimination | Low | ✅ FIXED | Binary classification loses information |
| 3.1 | Statistics | High | ✅ FIXED | Wrong model for non-stationary data |
| 3.2 | Statistics | Medium | ⚠️ PARTIAL | Multi-broadcast fusion (per-station, not per-broadcast) |
| 4.1 | Bug | Medium | ✅ FIXED | Inconsistent station coordinates |
| 4.2 | Bug | Low | ❌ INVALID | Tone duration - NIST confirms 800ms correct |
| 4.3 | Bug | Low | ✅ FIXED | Hardcoded default calibration offsets |
| 5.1 | Enhancement | Medium | ✅ FIXED | No use of phase information |
| 5.2 | Enhancement | Medium | ✅ FIXED | No multipath detection |
| 5.3 | Enhancement | Low | ✅ FIXED | No cross-correlation WWV/WWVH |
| 5.4 | Enhancement | Low | ✅ FIXED | No CHU FSK time code exploitation |
| 6.1 | Validation | High | ✅ FIXED | No ground truth validation mechanism |
| 6.2 | Validation | Low | ✅ FIXED | Quality grades are arbitrary |

### New Modules Created

| Module | Lines | Purpose |
|--------|-------|---------|
| `ionospheric_model.py` | ~600 | Dynamic layer heights (IRI-2016/parametric) |
| `ground_truth_validator.py` | ~700 | GPS PPS, silent minute, mode validation |
| `probabilistic_discriminator.py` | ~750 | Logistic regression with L2 regularization |
| `advanced_signal_analysis.py` | ~900 | Phase correlation, multipath, CHU FSK |

### Key Changes

1. **Issue 6.2**: `quality_grade` (A/B/C/D) replaced with `uncertainty_ms` + `confidence`
2. **Backwards Compatibility**: Grade computed from uncertainty for web UI:
   - A: < 1 ms
   - B: < 3 ms
   - C: < 10 ms
   - D: ≥ 10 ms

**Full details**: `docs/PHASE2_CRITIQUE.md`

---

## 🚨 NEXT PRIORITY: PHASE 3 PIPELINE IMPLEMENTATION

**Purpose:** Implement the Phase 3 derived products pipeline - decimation, spectrograms, power graphs, and GRAPE/PSWS upload.

**Author:** Michael James Hauan (AC0G)  
**Date:** 2025-12-08 (Next Session)  
**Status:** 🔴 Not Started

---

### PHASE 3 OVERVIEW

Phase 3 produces derived products from Phase 2 analytical data:

```
Phase 2 Output (20 kHz IQ)
    ↓
┌─────────────────────────────────────────────────────────────┐
│                    PHASE 3 PIPELINE                         │
├─────────────────────────────────────────────────────────────┤
│  1. Decimation: 20 kHz → 10 Hz (carrier amplitude/phase)    │
│  2. Spectrogram: Daily carrier frequency/amplitude plot      │
│  3. Power Graphs: Carrier power with solar zenith overlay   │
│  4. Digital RF Product: 24-hour UTC day archive (HamSCI)    │
│  5. Upload: GRAPE/PSWS data repository submission           │
└─────────────────────────────────────────────────────────────┘
    ↓
products/{CHANNEL}/
├── decimated/YYYYMMDD.bin         # 10 Hz carrier data
├── spectrograms/YYYYMMDD.png      # Daily spectrogram
├── power/YYYYMMDD_power.png       # Power graph + solar zenith
└── drf/YYYYMMDD/                  # Digital RF for upload
```

---

### COMPONENT 1: DECIMATION (20 kHz → 10 Hz)

**Goal:** Extract carrier amplitude and phase at 10 Hz for efficient storage and analysis.

**Input:**
- `raw_archive/{CHANNEL}/` - 20 kHz complex IQ from Phase 1

**Output:**
- `products/{CHANNEL}/decimated/YYYYMMDD.bin` - 10 Hz carrier data

**Implementation Notes:**
- Use scipy.signal.decimate or polyphase filter
- Extract carrier: mix to baseband, lowpass filter, decimate
- Output format: binary float32 (amplitude, phase) pairs
- File size: ~7 MB/day/channel (10 Hz × 86400 sec × 8 bytes)

**Existing Code to Review:**
| File | Status | Notes |
|------|--------|-------|
| `archive/legacy-grape-modules/decimator.py` | ⚠️ Legacy | May have useful algorithms |
| `scripts/analyze_decimation_quality.py` | ✅ Active | Quality analysis script |

---

### COMPONENT 2: CARRIER SPECTROGRAM

**Goal:** Generate daily spectrogram showing carrier frequency/amplitude variations.

**Input:**
- `products/{CHANNEL}/decimated/YYYYMMDD.bin` - 10 Hz carrier data

**Output:**
- `products/{CHANNEL}/spectrograms/YYYYMMDD_spectrogram.png`

**Implementation Notes:**
- X-axis: UTC time (00:00 - 24:00)
- Y-axis: Frequency offset from carrier (±0.5 Hz typical)
- Color: Signal amplitude (dB)
- Show ionospheric Doppler shifts, propagation mode changes

**Existing Code to Review:**
| File | Status | Notes |
|------|--------|-------|
| `scripts/generate_spectrograms.py` | ⚠️ Archive | Check for reuse |
| `scripts/auto-generate-spectrograms.sh` | ✅ Active | Automation script |
| `docs/features/AUTOMATIC_SPECTROGRAM_GENERATION.md` | ✅ Reference | Design doc |

---

### COMPONENT 3: POWER GRAPHS WITH SOLAR ZENITH OVERLAY

**Goal:** Visualize carrier power alongside solar zenith angle for ionospheric correlation.

**Input:**
- `products/{CHANNEL}/decimated/YYYYMMDD.bin` - 10 Hz carrier data
- Station coordinates from `grape-config.toml`
- Transmitter coordinates (WWV: 40.68°N, 105.04°W)

**Output:**
- `products/{CHANNEL}/power/YYYYMMDD_power.png`

**Implementation Notes:**
- Primary Y-axis: Carrier power (dB)
- Secondary Y-axis: Solar zenith angle (degrees)
- Solar zenith calculation: Uses NOAA algorithms via `solar_zenith_calculator.py`
- Calculates at **path midpoint** (halfway between receiver and transmitter)
- Show sunrise/sunset transitions, D-layer absorption effects

**Solar Zenith Calculation (Already Implemented):**
```python
from grape_recorder.grape.solar_zenith_calculator import (
    calculate_solar_zenith_for_day,
    calculate_midpoint,
    solar_position
)

# Get solar elevation at path midpoints for all stations
solar_data = calculate_solar_zenith_for_day(date_str, receiver_grid)
# Returns: wwv_solar_elevation, wwvh_solar_elevation, chu_solar_elevation arrays
```

**Dependencies:** None required (uses pure Python NOAA algorithms)

---

### COMPONENT 4: DIGITAL RF PRODUCT (24-HOUR UTC DAY)

**Goal:** Package 24-hour UTC day of data in Digital RF format for HamSCI PSWS compatibility.

**Input:**
- `raw_archive/{CHANNEL}/` - 20 kHz complex IQ

**Output:**
- `products/{CHANNEL}/drf/YYYYMMDD/` - Digital RF directory structure

**Implementation Notes:**
- Digital RF format: HDF5 files with specific structure
- Time boundary: 00:00:00 UTC to 23:59:59 UTC
- Metadata: Station info, receiver config, GPSDO status
- Use existing `digital_rf` library

**Existing Code to Review:**
| File | Status | Notes |
|------|--------|-------|
| `src/grape_recorder/core/drf_writer.py` | ✅ Active | Real-time DRF writer |
| `archive/legacy-grape-modules/core_npz_writer.py` | ⚠️ Legacy | NPZ alternative |

---

### COMPONENT 5: GRAPE/PSWS UPLOAD

**Goal:** Upload completed daily products to the GRAPE data repository.

**Input:**
- `products/{CHANNEL}/drf/YYYYMMDD/` - Digital RF package
- `products/{CHANNEL}/spectrograms/YYYYMMDD.png`

**Destination:**
- GRAPE/PSWS data repository (TBD - endpoint configuration)

**Implementation Notes:**
- Upload after 00:00 UTC (previous day complete)
- Verify file integrity before upload (checksums)
- Track upload state to prevent duplicates
- Retry logic for network failures

**Existing Code to Review:**
| File | Status | Notes |
|------|--------|-------|
| `wsprdaemon/upload-client-utils.sh` | ✅ Active | Upload utilities |
| `systemd/grape-daily-upload.service` | ✅ Active | Systemd timer |
| `systemd/grape-daily-upload.timer` | ✅ Active | Daily trigger |

**Configuration to Check:**
| File | Setting | Purpose |
|------|---------|---------|
| `grape-config.toml` | `[uploader]` section | Upload credentials/endpoint |
| `config/environment` | `GRAPE_UPLOAD_*` | Environment variables |

---

### DATA CONTRACTS FOR PHASE 3

| Producer | Output Path | Consumer | Contract |
|----------|-------------|----------|----------|
| Decimator | `products/{CH}/decimated/YYYYMMDD.bin` | Spectrogram Generator | Binary float32 pairs |
| Decimator | `products/{CH}/decimated/YYYYMMDD.json` | Uploader | Metadata (sample rate, start time) |
| Spectrogram Gen | `products/{CH}/spectrograms/YYYYMMDD.png` | Web UI, Uploader | PNG image |
| Power Graph Gen | `products/{CH}/power/YYYYMMDD_power.png` | Web UI | PNG with solar overlay |
| DRF Packager | `products/{CH}/drf/YYYYMMDD/` | Uploader | Digital RF structure |
| Uploader | `products/{CH}/upload_state.json` | Uploader | Prevents re-upload |

---

### CRITIQUE CHECKLIST FOR PHASE 3

#### 1. Decimation Quality
- [ ] Does the filter preserve carrier phase information?
- [ ] Is anti-aliasing sufficient (stopband attenuation > 60 dB)?
- [ ] Are edge effects handled at day boundaries?

#### 2. Spectrogram Accuracy
- [ ] Is time axis aligned to UTC?
- [ ] Does frequency axis match actual carrier offset range?
- [ ] Are colormaps appropriate for the data range?

#### 3. Solar Zenith Calculation
- [ ] Are coordinates correct for both receiver AND transmitter?
- [ ] Is the calculation for the MIDPOINT of the propagation path?
- [ ] Are time zones handled correctly (UTC throughout)?

#### 4. Digital RF Compliance
- [ ] Does output match HamSCI PSWS format specification?
- [ ] Are all required metadata fields present?
- [ ] Is the file structure compatible with existing tools?

#### 5. Upload Robustness
- [ ] Is there retry logic for transient failures?
- [ ] Are credentials stored securely (not in code)?
- [ ] Is upload state persisted across service restarts?

---

### FILES TO CREATE/MODIFY

**New Files:**
| File | Purpose |
|------|---------|
| `src/grape_recorder/grape/decimator.py` | 20 kHz → 10 Hz decimation |
| `src/grape_recorder/grape/spectrogram_generator.py` | Daily spectrogram creation |
| `src/grape_recorder/grape/power_graph_generator.py` | Power + solar zenith plots |
| `src/grape_recorder/grape/drf_packager.py` | 24-hour DRF packaging |
| `src/grape_recorder/grape/uploader.py` | GRAPE repository upload |
| `src/grape_recorder/grape/phase3_pipeline.py` | Pipeline orchestration |

**Files to Update:**
| File | Change |
|------|--------|
| `requirements.txt` | Add `astropy` for solar calculations |
| `systemd/grape-daily-upload.service` | Update for new pipeline |
| `grape-config.toml` | Add Phase 3 configuration section |

---

## ORIGINAL CRITIQUE CONTEXT (Reference)

The sections below document the original problem being solved and the theoretical framework used for the critique. Preserved for future reference.

### 1. THE PROBLEM BEING SOLVED

**Objective**: Extract precise UTC(NIST) time from HF radio signals transmitted by WWV, WWVH, and CHU time signal stations, achieving sub-millisecond accuracy despite ionospheric propagation delays of 2-60 ms.

**The Fundamental Equation**:
```
T_arrival = T_emission + T_propagation + D_clock

Where:
  T_arrival = Detected tone time (from matched filter)
  T_emission = 0 (by definition - tones at second boundary)
  T_propagation = Ionospheric path delay (ESTIMATED)
  D_clock = System clock offset from UTC(NIST) (DESIRED OUTPUT)

Therefore:
  D_clock = T_arrival - T_propagation
```

### 2. THREE-STEP TEMPORAL ANALYSIS

| Step | Method | Window | Output |
|------|--------|--------|--------|
| 1 | Tone Detection | ±500 ms | Time snap anchor |
| 2 | Channel Characterization | ±50 ms | Station ID, mode hints |
| 3 | Transmission Time Solution | — | D_clock value |

### 3. THEORETICAL REFERENCES

- **NIST Special Publication 432** - WWV/WWVH specifications
- **ITU-R P.531** - Ionospheric propagation prediction
- **ITU-R P.533** - HF propagation method
- **IRI-2016** - International Reference Ionosphere model

### 4. KEY FILES FOR PHASE 2 ANALYTICS

| File | Purpose |
|------|---------|
| `tone_detector.py` | Matched filter, correlation |
| `transmission_time_solver.py` | Mode scoring, D_clock |
| `phase2_temporal_engine.py` | Pipeline orchestration |
| `wwvh_discrimination.py` | Station discrimination |
| `clock_convergence.py` | Kalman filter tracking |
| `multi_broadcast_fusion.py` | 13-broadcast fusion |

### 5. SUCCESS CRITERIA

| Metric | Target | Status |
|--------|--------|--------|
| D_clock accuracy | ±1 ms | ✅ Framework in place |
| Station discrimination | 95% | ✅ Probabilistic model added |
| Propagation mode ID | 80% | ✅ Dynamic iono model added |
| Time to lock | < 30 min | ✅ Kalman filter added |
| Validation | Ground truth | ✅ GPS PPS + silent minutes |

---

*This document has been updated to reflect the completed critique. The next priority is ensuring web UI correctly interfaces with the updated analytics modules.*
